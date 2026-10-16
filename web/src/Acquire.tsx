/* 自动取数台（X2·票 12）：工作流第一站——取数 → 核对并并入 → 生成。
   只读视图：状态全部来自 GET /api/periods/{period}/acquisition（服务端只读）。
   重试/并入等写动作由人按（写路径与机械保证见 docs/adr/0004）；按钮可用性读状态里的
   capabilities——工具还没接入时按钮禁用并说明，不假装能点。
   静态稿对照：web/mockups/取数台.html；契约：§2.2 #26。 */

import { useCallback, useEffect, useRef, useState } from 'react'
import { getAcquisition, openPeriod, postAcquisition, postAcqBrowser, type AcquisitionState, type AcqGroup } from './api'
import { ConfirmButton } from './ConfirmButton'
import { Info } from './Info'
import { Icon } from './icons'
import { acqFileLabel, acqGroupLabel, errorNote } from './lib/status'

/** 任务进行中的一句话（op.kind → 人话） */
const OP_CN: Record<string, string> = {
  fetch: '正在按组取数', copy: '正在新建当期核对副本', merge: '正在并入主台账', preflight: '正在检查',
}

const SOURCE_NAME: Record<string, string> = { esi: 'ESI', incites: 'InCites' }

function groupStateClass(v?: string) {
  return v === 'done' ? 'ok' : v === 'live' || v === 'retrying' ? 'live' : v === 'fail' ? 'bad' : ''
}

function pfText(kind: 'browser' | 'site', v?: string) {
  if (v === 'ok') return kind === 'browser' ? '已连接' : '已登录'
  if (v === 'bad') return kind === 'browser' ? '未连接' : '未登录'
  if (v === 'waiting') return kind === 'browser' ? '待检查' : '等浏览器'
  return '待检查'
}

/** 开新一期的期次校验（与后端同口径）：六位 YYYYMM 且月份是双月（1/3/5/7/9/11）。 */
function newPeriodProblem(v: string): string {
  if (!/^\d{6}$/.test(v)) return '期次要六位数字，如 202611。'
  if (![1, 3, 5, 7, 9, 11].includes(Number(v.slice(4, 6)))) {
    return '期次是每年的 1 / 3 / 5 / 7 / 9 / 11 月。'
  }
  return ''
}

type PageView = 'ready' | 'blocked' | 'running' | 'partial' | 'review' | 'merged'

function deriveView(s: AcquisitionState): PageView {
  const copy = s.copy?.state ?? 'none'
  if (copy === 'merged') return 'merged'
  if (copy === 'review') return 'review'
  if (!s.started) return 'ready'
  const failed = s.totals?.failed ?? 0
  if (failed > 0) return 'partial'
  const expected = s.totals?.expected ?? 0
  const verified = s.totals?.verified ?? 0
  if (expected > 0 && verified < expected) return 'running'
  const pf = s.preflight ?? {}
  if (pf.browser === 'bad' || pf.esi === 'bad' || pf.incites === 'bad') return 'blocked'
  return verified > 0 ? 'review' : 'ready'
}

function GroupCard({ g, onRetry, busy, readonly }: {
  g: AcqGroup; onRetry?: (gid: string) => void; busy?: boolean; readonly?: boolean
}) {
  const files = g.files ?? []
  const stateText = g.state ? acqGroupLabel(g.state) : '未开始'
  const got = g.verified ?? 0
  const pct = files.length > 0 ? Math.min(100, Math.round(got / files.length * 100)) : 0
  const srcName = g.source ? (SOURCE_NAME[g.source] ?? g.source) : ''
  /* 缺份 = 这一组里还有没下到的（含中断残留 live / 待下 pending）——「已并入」之后也允许补下 */
  const missing = files.length > 0 ? files.length - got : 0
  return (
    <article className={`aq-g ${groupStateClass(g.state)}`}>
      <div className="aq-gtop">
        <span className="aq-src">{srcName}{g.index ? ` · 第 ${g.index} 组` : ''}</span>
        <span className={`aq-gstat ${groupStateClass(g.state)}`}>{stateText}</span>
      </div>
      <div className="aq-gname"><Icon name="doc" size={18} />{g.title ?? '未命名组'}</div>
      <div className="aq-bar">
        <span className="aq-track"><i style={{ transform: `scaleX(${pct / 100})` }} /></span>
        <span className="aq-num">{got} / {files.length || '—'}</span>
      </div>
      {files.length > 0 && (
        <details className="aq-files">
          <summary>查看文件</summary>
          <ul>
            {files.map((f, i) => {
              const cls = f.state === 'ok' ? 'ok' : f.state === 'bad' ? 'bad' : ''
              return (
                <li key={i}>
                  <span className={`aq-fmark ${cls}`}>
                    <Icon name={f.state === 'ok' ? 'check' : f.state === 'bad' ? 'alert' : 'clock'} size={15} />
                  </span>
                  <span className="aq-fname">{f.name ?? '（未命名文件）'}<small>{f.label}</small></span>
                  <span className={`aq-fres ${cls}`}>{f.state ? acqFileLabel(f.state) : '待取数'}</span>
                </li>
              )
            })}
          </ul>
        </details>
      )}
      {missing > 0 && onRetry && !readonly && g.id && (
        <div className="aq-gacts">
          <button className="btn small" disabled={busy}
                  title="只补这一组里还没下到的文件；已下过的不重复下载"
                  onClick={() => onRetry(g.id as string)}>
            <Icon name="refresh" size={16} />补下这一组（还缺 {missing} 份）
          </button>
          <span className="hint">已下过的不重复下载；已并入台账不影响补下。</span>
        </div>
      )}
    </article>
  )
}

export function Acquire({ period, onOpenPeriod }: {
  period: string | null; onOpenPeriod?: (period: string) => void
}) {
  const [state, setState] = useState<AcquisitionState | null>(null)
  const [note, setNote] = useState<string | null>(null)
  const [loading, setLoading] = useState(false)
  const [busy, setBusy] = useState(false)
  /* 开新一期：页头行内表单（票 05）——只登记期次、落空状态，不取数 */
  const [openForm, setOpenForm] = useState(false)
  const [newPeriod, setNewPeriod] = useState('')
  const [openErr, setOpenErr] = useState('')
  const stateRef = useRef<AcquisitionState | null>(null)
  const reloadTimer = useRef<number | undefined>(undefined)
  useEffect(() => () => { if (reloadTimer.current !== undefined) window.clearTimeout(reloadTimer.current) }, [])

  const load = useCallback((silent = false) => {
    if (!period) { setState(null); setNote(null); return }
    if (!silent) setLoading(true)
    getAcquisition(period)
      .then((s) => { stateRef.current = s; setState(s); setNote(null) })
      .catch((e) => {
        setState(null)
        setNote(errorNote(e, '取数台', {
          n404: '没读到这一期的取数状态——确认期次是六位数，或稍等片刻重试。',
        }))
      })
      .finally(() => { if (!silent) setLoading(false) })
  }, [period])

  useEffect(() => { load() }, [load])
  /* 进度轮询：4 秒一次轻读；后台标签页不拉；已并入的期次降到 32 秒一次，切回页面立即刷新 */
  useEffect(() => {
    if (!period) return
    let tick = 0
    const t = window.setInterval(() => {
      if (document.hidden) return
      tick += 1
      const s = stateRef.current
      if (s && deriveView(s) === 'merged' && tick % 8 !== 0) return
      load(true)
    }, 4000)
    const onVisible = () => { if (!document.hidden) load(true) }
    document.addEventListener('visibilitychange', onVisible)
    return () => {
      window.clearInterval(t)
      document.removeEventListener('visibilitychange', onVisible)
    }
  }, [period, load])

  const act = useCallback(async (action: string, body?: Record<string, unknown>) => {
    if (!period) return null
    setBusy(true)
    try {
      const r = await postAcquisition(period, action, body)
      reloadTimer.current = window.setTimeout(() => load(true), 500)
      return r
    } catch (e) {
      setNote(errorNote(e, '这一步', { n409: '有一个取数任务还在跑，稍等它完成。' }))
      return null
    } finally {
      setBusy(false)
    }
  }, [period, load])

  /* 「开始前检查」先确保取数专用浏览器在跑：没连上就请服务端把窗口打开（独立 profile + CDP 9222），
     等它起来再查一次。**只开窗、不代登录**——首次仍要人在那个窗口登录 ESI / InCites
     （凭证靠 Chrome 自己记住，系统不碰账号密码）。 */
  const preflightWithBrowser = useCallback(async () => {
    let r = await act('preflight')
    if (r?.preflight?.browser !== 'ok') {
      await postAcqBrowser().catch(() => null)
      await new Promise((res) => setTimeout(res, 4500))   // 给窗口起来的时间
      r = await act('preflight')
    }
    return r
  }, [act])

  /* 开始取数前先看「开始前检查」：没过就不发车，页面会切到「检查未过」让人去连浏览器 */
  const onStart = useCallback(async () => {
    const r = await preflightWithBrowser()
    const pf = r?.preflight
    if (pf && (pf.browser !== 'ok' || pf.esi !== 'ok' || pf.incites !== 'ok')) {
      load(true)
      return
    }
    /* 数据期：这一期网站还没更新就不发车（票 04）——说清"当前是哪一期"，别让人白等 */
    if (pf?.data && pf.data.ok === false) {
      await load(true)
      setNote(pf.data.note || '这一期的数据还没更新——等网站更新后再取。')
      return
    }
    await act('start')
  }, [act, load, preflightWithBrowser])

  /* 补下一组：与「开始取数」同规矩——先看「开始前检查」，浏览器/登录没就绪就不发车
     （2026-10-15：先前直接发车，取数脚本会因连不上浏览器而拒绝，白记一次失败） */
  const onRetryGroup = useCallback(async (gid: string) => {
    const r = await preflightWithBrowser()
    const pf = r?.preflight
    if (pf && (pf.browser !== 'ok' || pf.esi !== 'ok' || pf.incites !== 'ok')) {
      load(true)
      return
    }
    if (pf?.data && pf.data.ok === false) {
      await load(true)
      setNote(pf.data.note || '这一期的数据还没更新——等网站更新后再取。')
      return
    }
    await act('retry', { group: gid })
  }, [act, load, preflightWithBrowser])

  /* 开新一期（票 05）：登记一个新期次 → 落空状态 → 进这一期的取数台。
     只登记、不取数——数据期校验（票 04）留到点「开始取数」时把关。 */
  const onOpen = useCallback(async () => {
    const v = newPeriod.trim()
    const problem = newPeriodProblem(v)
    if (problem) { setOpenErr(problem); return }
    setBusy(true); setOpenErr('')
    try {
      await openPeriod(v)
      setOpenForm(false); setNewPeriod('')
      onOpenPeriod?.(v)
    } catch (e) {
      setOpenErr(errorNote(e, '开新一期'))
    } finally {
      setBusy(false)
    }
  }, [newPeriod, onOpenPeriod])

  if (!period) {
    return <div className="pending-box">先在顶栏选一个期次；取数台会显示这一期的取数进度与核对状态。</div>
  }

  const op = state?.op
  const opRunning = op?.state === 'running'
  const view: PageView = state ? deriveView(state) : 'ready'
  const totals = state?.totals ?? {}
  const expected = totals.expected ?? 0
  const verified = totals.verified ?? 0
  const failed = totals.failed ?? 0
  const groups = state?.groups ?? []
  const failGroup = groups.find((g) => g.state === 'fail')
  const liveGroup = groups.find((g) => g.state === 'live')
  const reviewSheets = state?.review?.sheets ?? []
  const showReview = !!state && (state.copy?.state === 'review' || state.copy?.state === 'merged')
  /* 能力缺省＝可执行：`scan()` 会落这份默认；开新一期的空壳/只检查过的期次没有它，
     不该因此显示「取数工具还没接入」。真接不上的场景由状态显式给 false。 */
  const cap = state?.capabilities ?? { start: true, retry: true, merge: true }
  const toolMissing = '取数工具还没接入；接入后这里就能一键执行。'
  const capKey: 'start' | 'retry' | 'merge' = view === 'partial' ? 'retry' : view === 'review' ? 'merge' : 'start'
  const needsTool = view === 'ready' || view === 'partial' || view === 'review'
  const canRun = !!cap[capKey]
  /* 采集与并入台账是两条独立的线（2026-10-16 解耦）：采集＝本机取到多少份；并入＝台账并没并。
     重新取数只会补没下到的文件，台账那一列一字不动。
     2026-10-16 中午拍板：头条只留**采集**进度行——「已并入（期次 列）」的结论由焦点卡承担，
     两处同写一句「已并入（202609 列）」是重复，删去头条那行（去重守卫见 e2e）。 */
  /* 最近一次「取数」的时间（只在最近一步确实是取数时才显示，免得把别的动作当成重取） */
  const lastFetchAt = op?.kind === 'fetch' ? (op.at ?? '') : ''
  /* 往期档案只读（票 03）：期次早于「本机已取过的最新期次」就不能再取——ESI/InCites 没有历史数据 */
  const ro = state?.mode === 'readonly'
  const rec = state?.reconcile

  const pill: Record<PageView, [string, string]> = {
    ready: ['还没开始', 'unsigned'],
    blocked: ['还没开始', 'unsigned'],
    running: ['取数中', 'stale'],
    partial: [`有 ${failed} 份未通过`, 'bad'],
    review: ['待核对', 'stale'],
    merged: ['已并入', 'signed'],
  }

  /* 如实：只有「开始前检查」这轮真通过才说「可以开始取数」——状态文件在不在不算
     （开新一期落的只是空壳，票 05）。 */
  const pf = state?.preflight
  const pfPassed = !!pf && pf.browser === 'ok' && pf.esi === 'ok'
    && pf.incites === 'ok' && pf.data?.ok !== false
  const title = view === 'ready'
    ? (pfPassed ? '开始前检查通过，可以开始取数。' : '还没开始取数。')
    : view === 'blocked' ? '取数专用浏览器还没准备好。'
      : view === 'running' ? `正在取数${liveGroup?.title ? `：${liveGroup.title}` : ''}……`
        : view === 'partial' ? `${failGroup?.title ?? '有一组'}有 ${failed} 份没通过核验。`
          : view === 'review' ? '本期监测表已自动建好，请核对。'
            : `已并入主台账（${period} 列）`
  const sub = view === 'ready'
    ? (pfPassed ? '9 组文件，取到后逐份核验。' : '点「开始取数」会先检查网站的数据更新了没有；需要时自动打开取数专用浏览器（首次在里面登录 ESI / InCites）。')
    : view === 'blocked' ? '系统会自动打开取数专用浏览器；在里面登录 ESI / InCites 后，点「重新检查」。'
      : view === 'running' ? '可以离开这一页，进度不会丢。'
        : view === 'partial' ? '重试只补这一组，通过的不重复下载。'
          : view === 'review' ? `核对无误后并入台账（只动 ${period} 列）。`
            : ''

  return (
    <>
      {note && <div className="pending-box">{note}<button type="button" className="btn ml-10" onClick={() => { setNote(null); load() }}>重新读取</button></div>}
      {!state && !note && <div className="pending-box">{loading ? '正在读取取数状态……' : '还没有读到取数状态。'}</div>}

      {state && (
        <>
          {/* ===== 期次数据状态 ===== */}
          <section className="card pad-card-x">
            <div className="aq-head">
              <h1 className="fs-24">自动取数台</h1>
              <span className="pill unsigned mono">{period}</span>
              <span className={`pill ${pill[view][1]}`}>{pill[view][0]}</span>
              <span className="hint aq-num">采集 · {expected > 0 ? `已取到 ${verified} / ${expected}` : '未开始'}{lastFetchAt ? ` · 最近取数 ${lastFetchAt}` : ''}</span>
              <button type="button" className="btn small ml-auto" aria-expanded={openForm}
                      onClick={() => { setOpenForm((v) => !v); setOpenErr('') }}>
                <Icon name="plus" size={16} />开新一期
              </button>
            </div>
            {openForm && (
              <div className="aq-open">
                <label className="hint" htmlFor="aq-new-period">开一期新的</label>
                <input id="aq-new-period" className="aq-open-in mono" inputMode="numeric"
                       maxLength={6} placeholder="YYYYMM，如 202611" value={newPeriod}
                       onChange={(e) => { setNewPeriod(e.target.value.replace(/\D/g, '')); setOpenErr('') }}
                       onKeyDown={(e) => { if (e.key === 'Enter') void onOpen() }} />
                <button type="button" className="btn small primary" disabled={busy}
                        onClick={() => void onOpen()}>开这一期</button>
                <button type="button" className="btn small" disabled={busy}
                        onClick={() => { setOpenForm(false); setOpenErr('') }}>取消</button>
                {openErr && <span className="hint note-bad">{openErr}</span>}
              </div>
            )}
          </section>

          {/* ===== 主动作（每屏 1 个） ===== */}
          <div className="focus">
            <div aria-live="polite">
              <div className="big">{opRunning && op ? `${OP_CN[op.kind ?? ''] ?? '正在执行'}……` : title}</div>
              {((opRunning && op) || sub) && (
                <div className="sub">{opRunning && op ? (op.note || '进度会自动更新，可以留在这一页') : sub}</div>
              )}
              {op?.state === 'failed' && (
                <div className="hint note-bad">
                  上一步没有完成：{op.note || '原因见取数状态'}。
                </div>
              )}
              {needsTool && !canRun && !opRunning && (
                <div className="hint note-warn">{toolMissing}</div>
              )}
              {ro && (
                <div className="hint">
                  往期档案只读：ESI / InCites 不提供历史数据，这一期不能再取（要补档只能在当期取）。
                </div>
              )}
              {rec && rec.ok === false && (
                <div className="hint note-bad">
                  数据期对不上：这一期应是 {rec.expected?.esi || '—'} / {rec.expected?.incites || '—'}，
                  实际取到 {rec.actual?.esi || '—'} / {rec.actual?.incites || '—'}——别把它当这一期的数据用。
                </div>
              )}
            </div>
            <div className="cta">
              {!opRunning && !ro && view === 'ready' && (
                <button className="btn primary" disabled={!cap.start || busy || opRunning}
                        title={cap.start ? undefined : toolMissing} onClick={onStart}>
                  <Icon name="download" size={20} />开始取数
                </button>
              )}
              {/* 已取过之后（待核对 / 已并入）仍可重新取这一期——采集与并入台账是两条线，
                  「并入过台账」不该把采集锁死（2026-10-16 票 01）；但**往期只读**（票 03） */}
              {!opRunning && !ro && (view === 'review' || view === 'merged') && (
                <button className="btn" disabled={!cap.start || busy}
                        title={cap.start ? '重取只补没下到的文件；已并入台账不受影响' : toolMissing}
                        onClick={onStart}>
                  <Icon name="download" size={20} />重新取这一期
                </button>
              )}
              {!opRunning && view === 'blocked' && (
                <button className="btn" disabled={busy}
                        onClick={() => { void preflightWithBrowser().then(() => load(true)) }}>
                  <Icon name="refresh" size={20} />重新检查
                </button>
              )}
              {!opRunning && view === 'partial' && (
                <button className="btn primary" disabled={!cap.retry || busy || opRunning}
                        title={cap.retry ? undefined : toolMissing}
                        onClick={() => act('retry', failGroup?.id ? { group: failGroup.id } : undefined)}>
                  <Icon name="refresh" size={20} />重试这一组
                </button>
              )}
              {!opRunning && view === 'review' && (
                <ConfirmButton className="btn primary" confirmText="再点一次 · 确认并入"
                               disabled={!cap.merge || busy}
                               onConfirm={() => { void act('merge') }}>
                  <Icon name="check" size={20} />核对无误 · 并入台账
                </ConfirmButton>
              )}
              {!opRunning && view === 'merged' && (
                <a className="btn primary" href={`/app/?period=${encodeURIComponent(period)}`}>
                  <Icon name="play" size={20} />去生成台生成
                </a>
              )}
            </div>
          </div>

          {/* ===== 开始前检查 ===== */}
          <div className="aq-pf" role="group" aria-label="开始前检查">
            <span className="aq-pf-title">开始前检查</span>
            <span className={`aq-chip ${state.preflight?.browser === 'ok' ? 'ok' : state.preflight?.browser === 'bad' ? 'bad' : ''}`}>
              <Icon name="play" size={15} />取数专用浏览器 · {pfText('browser', state.preflight?.browser)}
            </span>
            <span className={`aq-chip ${state.preflight?.esi === 'ok' ? 'ok' : state.preflight?.esi === 'bad' ? 'bad' : ''}`}>
              <Icon name="seal" size={15} />ESI 网站 · {pfText('site', state.preflight?.esi)}
            </span>
            <span className={`aq-chip ${state.preflight?.incites === 'ok' ? 'ok' : state.preflight?.incites === 'bad' ? 'bad' : ''}`}>
              <Icon name="seal" size={15} />InCites 网站 · {pfText('site', state.preflight?.incites)}
            </span>
            {/* 第四个灯：这一期的数据更新了没有（票 04）——用网站数据集更新日 + 双月节拍判 */}
            <span className={`aq-chip ${state.preflight?.data?.ok === true ? 'ok' : state.preflight?.data?.ok === false ? 'bad' : ''}`}>
              <Icon name="clock" size={15} />数据期 · {state.preflight?.data?.ok === true ? '已更新'
                : state.preflight?.data?.ok === false ? `还没更新（当前 ${state.preflight?.data?.release || '—'}）` : '没读到'}
            </span>
            <Info label="开始前检查什么" end>
              <p>检查取数专用的浏览器是否开着、两家网站是否已登录、这一期的数据更新了没有。登录由馆员手动完成；本页不接触、不保存账号密码。检查通过后才能开始。</p>
              <p>「数据期」怎么判：拿网站当前的数据集更新日{state.preflight?.data?.deploy_date ? `（${state.preflight.data.deploy_date}）` : ''}按双月节拍归到期次，和你要取的这一期比；对不上就不发车。</p>
            </Info>
          </div>

          {/* ===== 取数清单（明细，默认收起） ===== */}
          <details className="fold">
            <summary>取数清单<span className="sm">{totals.groups ?? groups.length ?? 9} 组 · {expected > 0 ? `${expected} 份` : '份数待定'}</span></summary>
            <div className="fold-inner">
              {groups.length === 0 ? (
                <p className="hint m-0">还没有取数记录。</p>
              ) : (
                <>
                  <div className="aq-groups">
                    {groups.map((g, i) => (
                      <GroupCard key={g.id ?? i} g={g} busy={busy} readonly={ro}
                                 onRetry={(gid) => { void onRetryGroup(gid) }} />
                    ))}
                  </div>
                </>
              )}
            </div>
          </details>

          {/* ===== 本期新增列核对表（待核对/已并入时出现） ===== */}
          {showReview && reviewSheets.length > 0 && (
            <details className="fold">
              <summary>本期新增列核对表<span className="sm">{reviewSheets.length} 张表</span></summary>
              <div className="fold-inner">
                <p className="hint m-b-8">
                  将并入主台账 {period} 列；历史列不动。
                </p>
                <div className="tablewrap">
                  <table className="aq-rv">
                    <thead><tr><th>工作表</th><th>新增</th><th>内容 / 示例值</th><th>来源</th></tr></thead>
                    <tbody>
                      {reviewSheets.map((r, i) => (
                        <tr key={i}><td>{r.name}</td><td>{r.added}</td><td>{r.content}</td><td>{r.source}</td></tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              </div>
            </details>
          )}

          {state.updated_at && (
            <p className="hint mt-12">取数状态最后更新：{state.updated_at}</p>
          )}
        </>
      )}
    </>
  )
}
