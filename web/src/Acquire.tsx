/* 自动下载数据台（X2·票 12）：工作流第一站——下载数据 → 核对并并入 → 生成。
   只读视图：状态全部来自 GET /api/periods/{period}/acquisition（服务端只读）。
   重试/并入等写动作由人按（写路径与机械保证见 docs/adr/0004）；按钮可用性读状态里的
   capabilities——工具还没接入时按钮禁用并说明，不假装能点。
   静态稿对照：web/mockups/下载数据台.html；契约：§2.2 #26。 */

import { useCallback, useEffect, useRef, useState } from 'react'
import { getAcquisition, openPeriod, postAcquisition, postAcqBrowser, type AcquisitionState, type AcqGroup } from './api'
import { ConfirmButton } from './ConfirmButton'
import { Info } from './Info'
import { Icon } from './icons'
import { acqFileLabel, acqGroupLabel, errorNote } from './lib/status'

/** 任务进行中的一句话（op.kind → 人话） */
const OP_CN: Record<string, string> = {
  fetch: '正在按组下载数据', copy: '正在新建当期核对副本', merge: '正在并入主台账', preflight: '正在检查',
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

/** 后台脚本的原文（op.note）→ 馆员话（web/AGENTS.md 纪律 2：错误提示不出现技术术语）。
    认识的模式给整句人话；不认识的原样返回 ''，由调用方兜底展示原文——消息不吞。
    技术原文仍收进 title 供排查。已知模式：
    「清洗链退出码 1」「清洗链退出码 1；旧格被改…」「N 组命令失败 / M 份未通过核验」「gN 退出码 1」。 */
function humanOpNote(raw: string): string {
  if (raw.startsWith('清洗链退出码')) {
    const rest = raw.replace(/^清洗链退出码\s*\d+\s*；?/, '').trim()
    return rest
      ? `后台整理这一步没跑成：${rest}。数据没有变，可再试一次；反复失败请到运行档案看日志。`
      : '后台整理这一步没跑成（核对副本没有产出）。数据没有变，可再试一次；反复失败请到运行档案看日志。'
  }
  const groups = raw.match(/^(\d+)\s*组命令失败\s*\/\s*(\d+)\s*份未通过核验$/)
  if (groups) return `有 ${groups[1]} 组没下完、${groups[2]} 份没通过核验——可逐组重试，只会补缺的文件。`
  const one = raw.match(/^g?(\S+?)\s*退出码\s*\d+$/)
  if (one) return `第 ${one[1]} 组没下完——重试只会补缺的文件。`
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
                  <span className={`aq-fres ${cls}`}>{f.state ? acqFileLabel(f.state) : '待下载'}</span>
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
  /* 开新一期：页头行内表单（票 05）——只登记期次、落空状态，不下载数据 */
  const [openForm, setOpenForm] = useState(false)
  const [newPeriod, setNewPeriod] = useState('')
  const [openErr, setOpenErr] = useState('')
  /* ② 段收起后，「下载清单」仍可点开看（2026-10-19 三段式：明细不常驻，但要够得着） */
  const [showGroups, setShowGroups] = useState(false)
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
        setNote(errorNote(e, '下载数据台', {
          n404: '没读到这一期的下载数据状态——确认期次是六位数，或稍等片刻重试。',
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
      setNote(errorNote(e, '这一步', { n409: '有一个下载数据任务还在跑，稍等它完成。' }))
      return null
    } finally {
      setBusy(false)
    }
  }, [period, load])

  /* 「开始前检查」先确保下载数据专用浏览器在跑：没连上就请服务端把窗口打开（独立 profile + CDP 9222），
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

  /* 开始下载数据前先看「开始前检查」：没过就不发车，页面会切到「检查未过」让人去连浏览器 */
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

  /* 补下一组：与「开始下载数据」同规矩——先看「开始前检查」，浏览器/登录没就绪就不发车
     （2026-10-15：先前直接发车，下载数据脚本会因连不上浏览器而拒绝，白记一次失败） */
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

  /* 开新一期（票 05）：登记一个新期次 → 落空状态 → 进这一期的下载数据台。
     只登记、不下载数据——数据期校验（票 04）留到点「开始下载数据」时把关。 */
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
    return <div className="pending-box">先在顶栏选一个期次；下载数据台会显示这一期的下载数据进度与核对状态。</div>
  }

  const op = state?.op
  const opRunning = op?.state === 'running'
  /* 2026-10-19 晚（ADR-0010 落地补记）：`liveness` 是服务端**只读**判的（进程在不在）——
     running 但进程没了/太久没动静 = 上次中断，不许继续假装「下载中」（202609 的僵尸就是这么来的）。
     另两种「中断/停止」是服务端在写动作处落下的 failed（note 前缀见 server/app.py）。 */
  const opInterrupted = opRunning && (op?.liveness === 'dead' || op?.liveness === 'stale')
  const opBroken = op?.state === 'failed' && (op?.note ?? '').startsWith('上次运行中断')
  const opStopped = op?.state === 'failed' && (op?.note ?? '').startsWith('已停止')
  const opStory = opInterrupted || opBroken || opStopped
  /* 「真的有活着的任务在跑」——僵尸（进程没了）不算，否则会把重取/并入口一起藏掉
     （2026-10-19 实测：202609 的僵尸 op 让「重新下载这一期」不见了，check_web_app 逮到）。 */
  const opBusy = opRunning && !opInterrupted
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
     不该因此显示「下载数据工具还没接入」。真接不上的场景由状态显式给 false。 */
  const cap = state?.capabilities ?? { start: true, retry: true, merge: true }
  const toolMissing = '下载数据工具还没接入；接入后这里就能一键执行。'
  const capKey: 'start' | 'retry' | 'merge' = view === 'partial' ? 'retry' : view === 'review' ? 'merge' : 'start'
  const needsTool = view === 'ready' || view === 'partial' || view === 'review'
  const canRun = !!cap[capKey]
  /* 采集与并入台账是两条独立的线（2026-10-16 解耦）：采集＝本机取到多少份；并入＝台账并没并。
     重新下载数据只会补没下到的文件，台账那一列一字不动。
     2026-10-16 中午拍板：头条只留**采集**进度行——「已并入（期次 列）」的结论由焦点卡承担，
     两处同写一句「已并入（202609 列）」是重复，删去头条那行（去重守卫见 e2e）。 */
  /* 最近一次「下载数据」的时间（只在最近一步确实是下载数据时才显示，免得把别的动作当成重取） */
  const lastFetchAt = op?.kind === 'fetch' ? (op.at ?? '') : ''
  /* 打包下载（2026-10-19 馆员需求；rick 定「拆两个包、两个按钮」）：哪一路有文件就显示哪个按钮 */
  const hasEsiPack = groups.some((g) => g.source === 'esi' && (g.verified ?? 0) > 0)
  const hasIncitesPack = groups.some((g) => g.source === 'incites' && (g.verified ?? 0) > 0)
  const packHref = (source: 'esi' | 'incites') =>
    `/api/periods/${encodeURIComponent(period)}/acquisition/datapack?source=${source}`
  /* 往期档案只读（票 03）：期次早于「本机已取过的最新期次」就不能再取——ESI/InCites 没有历史数据 */
  const ro = state?.mode === 'readonly'
  const rec = state?.reconcile

  const pill: Record<PageView, [string, string]> = {
    ready: ['还没开始', 'unsigned'],
    blocked: ['还没开始', 'unsigned'],
    running: ['下载中', 'stale'],
    partial: [`有 ${failed} 份未通过`, 'bad'],
    review: ['待核对', 'stale'],
    merged: ['已并入', 'signed'],
  }
  /* 文件没取齐（view=running）时，「中断/停止」的故事占据头条（徽章与横幅都换上）；
     文件齐/已并入时它退成一行提示（见下方 hint），不抢「已并入」的结论——
     但**任何**「中断/停止」都不许再说「正在下载」（202609 的僵尸就是在这一点上骗人的）。 */
  const showOpHero = opStory && view === 'running'
  const [pillText, pillCls] = showOpHero
    ? (opStopped ? ['已停止', 'unsigned'] as [string, string] : ['已中断', 'bad'] as [string, string])
    : opStory ? pill[view]
      : opRunning ? ['下载中', 'stale'] as [string, string] : pill[view]

  /* 如实：只有「开始前检查」这轮真通过才说「可以开始下载数据」——状态文件在不在不算
     （开新一期落的只是空壳，票 05）。 */
  const pf = state?.preflight
  const pfPassed = !!pf && pf.browser === 'ok' && pf.esi === 'ok'
    && pf.incites === 'ok' && pf.data?.ok !== false
  /* ===== 三段式（2026-10-19 rick 定：① 开始前检查 → ② 下载数据 → ③ 并入台账，逐段解锁） =====
     每段三态：done（收起成一行结论＋重入口）/ now（展开）/ locked（虚线＋等什么）；
     上一段没通过，下一段的按钮不出现（rick：检查无误后才显示下载）。 */
  const fetchBusy = opBusy && (op?.kind === 'fetch' || op?.kind === 'stop')
  const copyBusy = opBusy && (op?.kind === 'copy' || op?.kind === 'merge')
  /* ① 的结论只认**这四盏灯本身**：不看「期次走到哪一步」——已并入的老期次如果现在没登录网站，
     也必须如实说「有没通过的项」，不能因为历史上下载过就打 ✓（2026-10-20 rick 逮到的假话）。 */
  const pfHasBad = !!pf && (pf.browser === 'bad' || pf.esi === 'bad' || pf.incites === 'bad'
    || pf.data?.ok === false)
  const s1done = pfPassed
  const s2collapsed = (view === 'review' || view === 'merged') && !fetchBusy
  const s2locked = !s2collapsed && !pfPassed && (view === 'ready' || view === 'blocked')
  const s1stat: [string, string] = s1done ? ['✓ 4 项都过了', 'ok']
    : pfHasBad ? ['有没通过的项', 'bad'] : ['还没检查', 'wait']
  const s2stat: [string, string] = s2collapsed ? [`✓ 已取到 ${verified} / ${expected}`, 'ok']
    : fetchBusy ? [`下载中 · ${verified} / ${expected}`, 'run']
      : opStory ? [(opStopped ? '已停止' : '已中断'), (opStopped ? 'wait' : 'bad')]
        : s2locked ? ['等 ① 检查通过', 'wait']
          : view === 'partial' ? [`有 ${failed} 份没通过`, 'bad']
            : ro ? ['往期只读', 'wait'] : ['可以下载', 'wait']
  const s3stat: [string, string] = view === 'merged' ? [`✓ 已并入（${period} 列）`, 'ok']
    : copyBusy ? [`${op?.kind === 'merge' ? '正在并入' : '正在建核对副本'}……`, 'run']
      : view === 'review' ? ['核对表已生成 · 待核对', 'run'] : ['等 ② 下载齐了自动解锁', 'wait']
  const s2big = showOpHero
    ? (opStopped ? '下载已停止' : '上次下载中断了')
    : fetchBusy ? `正在按组下载数据${liveGroup?.title ? `：${liveGroup.title}` : ''}……`
      : view === 'partial' ? `${failGroup?.title ?? '有一组'}有 ${failed} 份没通过核验。`
        : view === 'running' ? '这一期还没取齐'
          : pfPassed ? '检查都过了，可以下载这一期的数据' : '等上一步检查通过'
  const s2sub = showOpHero
    ? (opStopped
      ? `已经下载的文件都在${expected > 0 ? `（${verified} / ${expected}）` : ''}。等准备好再点「继续下载」，只补没下到的文件。`
      : (opInterrupted && op?.at
        ? `最后一次动静是 ${op.at}，之后就没有再往下走——下载程序已经停了。已经下载的文件都在，没有丢。`
        : '下载程序已经停了。已经下载的文件都在，没有丢。'))
    : fetchBusy ? '可以离开这一页，进度不会丢。'
      : view === 'partial' ? '重试只补这一组，通过的不重复下载。'
        : view === 'running' ? `已取到 ${verified} / ${expected}；继续下载只补缺的文件。`
          : pfPassed ? '9 组、共 64 份；下载中随时可停，停下的补缺不重复下载。'
            : '① 的检查都过了，这里会出现「开始下载」。'
  /* 失败的一行话：下载相关留 ②，建副本/并入相关留 ③（按 op.kind 归位） */
  const opNoteLine = op?.state === 'failed' && !opStory
    ? (humanOpNote(op.note ?? '') || `上一步没有完成：${op.note || '原因见下载数据状态'}`) : ''
  /* 下载清单（组卡）：② 展开时常驻一处；收起后从「下载清单」按钮点开——不重复造两份 */
  const groupsFold = (open?: boolean) => (
    <details className="fold" open={open}>
      <summary>下载数据清单<span className="sm">{totals.groups ?? groups.length ?? 9} 组 · {expected > 0 ? `${expected} 份` : '份数待定'}</span></summary>
      <div className="fold-inner">
        {groups.length === 0 ? (
          <p className="hint m-0">还没有下载数据记录。</p>
        ) : (
          <div className="aq-groups">
            {groups.map((g, i) => (
              <GroupCard key={g.id ?? i} g={g} busy={busy} readonly={ro}
                         onRetry={(gid) => { void onRetryGroup(gid) }} />
            ))}
          </div>
        )}
      </div>
    </details>
  )

  return (
    <>
      {note && <div className="pending-box">{note}<button type="button" className="btn ml-10" onClick={() => { setNote(null); load() }}>重新读取</button></div>}
      {!state && !note && <div className="pending-box">{loading ? '正在读取下载数据状态……' : '还没有读到下载数据状态。'}</div>}

      {state && (
        <>
          {/* ===== 期次数据状态 ===== */}
          <section className="card pad-card-x">
            <div className="aq-head">
              <h1 className="fs-24">取数核验</h1>
              <span className="pill unsigned mono">{period}</span>
              <span className={`pill ${pillCls}`}>{pillText}</span>
              <span className="hint aq-num">采集 · {expected > 0 ? `已取到 ${verified} / ${expected}` : '未开始'}{lastFetchAt ? ` · 最近下载 ${lastFetchAt}` : ''}</span>
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

          {/* ===== 三段式：① 开始前检查 → ② 下载数据 → ③ 并入台账（2026-10-19 rick 定） ===== */}
          <div className="flow">

            {/* ── ① 开始前检查（最上面；过了才显示下载） ── */}
            <section className={`stg ${s1done ? 'done' : 'now'}`}>
              <div className="node"><i>①</i></div>
              <div className="body"><div className="stg-card">
                <div className="stg-top">
                  <span className="stg-title">开始前检查</span>
                  <span className={`stg-stat ${s1stat[1]}`}>{s1stat[0]}</span>
                </div>
                {/* 通过后：收起成一行（四盏小灯 + 重查） */}
                <div className="stg-inline">
                  <span className={`aq-chip ${pf?.browser === 'ok' ? 'ok' : 'bad'}`}><Icon name="play" size={15} />浏览器</span>
                  <span className={`aq-chip ${pf?.esi === 'ok' ? 'ok' : 'bad'}`}><Icon name="seal" size={15} />ESI 登录</span>
                  <span className={`aq-chip ${pf?.incites === 'ok' ? 'ok' : 'bad'}`}><Icon name="seal" size={15} />InCites 登录</span>
                  <span className={`aq-chip ${pf?.data?.ok === true ? 'ok' : pf?.data?.ok === false ? 'bad' : ''}`}><Icon name="clock" size={15} />数据期</span>
                  <button type="button" className="btn small" disabled={busy}
                          onClick={() => { void preflightWithBrowser().then(() => load(true)) }}>
                    <Icon name="refresh" size={15} />重查
                  </button>
                </div>
                {/* 还没过：展开（四盏灯 + 检查按钮） */}
                <div className="stg-body">
                  <div className="stg-big">{view === 'blocked' ? '下载数据专用浏览器还没准备好'
                    : ro ? '往期档案只读'
                      : (view === 'review' || view === 'merged') ? '现在的连接状态不齐'
                        : '先检查，再下载'}</div>
                  <div className="stg-sub">{view === 'blocked'
                    ? '系统会自动打开下载数据专用浏览器；在里面登录 ESI / InCites 后，点「重新检查」。'
                    : ro ? '这一期不能再取；这里只显示浏览器与登录的当前状态。'
                      : (view === 'review' || view === 'merged')
                        ? '这一期已经取完；这里只显示浏览器与登录的当前状态。'
                        : '四件事：下载数据专用浏览器开着、两家网站登录着、这一期的数据更新了没有。'}</div>
                  <div className="stg-cta">
                    <div className="chips">
                      <span className={`aq-chip ${pf?.browser === 'ok' ? 'ok' : pf?.browser === 'bad' ? 'bad' : ''}`}>
                        <Icon name="play" size={15} />下载数据专用浏览器 · {pfText('browser', pf?.browser)}
                      </span>
                      <span className={`aq-chip ${pf?.esi === 'ok' ? 'ok' : pf?.esi === 'bad' ? 'bad' : ''}`}>
                        <Icon name="seal" size={15} />ESI 网站 · {pfText('site', pf?.esi)}
                      </span>
                      <span className={`aq-chip ${pf?.incites === 'ok' ? 'ok' : pf?.incites === 'bad' ? 'bad' : ''}`}>
                        <Icon name="seal" size={15} />InCites 网站 · {pfText('site', pf?.incites)}
                      </span>
                      <span className={`aq-chip ${pf?.data?.ok === true ? 'ok' : pf?.data?.ok === false ? 'bad' : ''}`}>
                        <Icon name="clock" size={15} />数据期 · {pf?.data?.ok === true ? '已更新'
                          : pf?.data?.ok === false ? `还没更新（当前 ${pf?.data?.release || '—'}）` : '没读到'}
                      </span>
                    </div>
                    <button type="button" className="btn primary" disabled={busy}
                            onClick={() => { void preflightWithBrowser().then(() => load(true)) }}>
                      <Icon name="refresh" size={20} />{view === 'blocked' ? '重新检查' : '检查一下（会自动开浏览器）'}
                    </button>
                    <Info label="开始前检查什么" end>
                      <p>检查下载数据专用的浏览器是否开着、两家网站是否已登录、这一期的数据更新了没有。登录由馆员手动完成；本页不接触、不保存账号密码。检查通过后才能开始。</p>
                      <p>「数据期」怎么判：拿网站当前的数据集更新日{pf?.data?.deploy_date ? `（${pf.data.deploy_date}）` : ''}按双月节拍归到期次，和你要取的这一期比；对不上就不发车。</p>
                    </Info>
                  </div>
                </div>
              </div></div>
            </section>

            {/* ── ② 下载数据（① 过了才亮；下载中/中断都在这段讲） ── */}
            <section className={`stg ${s2collapsed ? 'done' : s2locked ? 'locked' : 'now'}`}>
              <div className="node"><i>②</i></div>
              <div className="body"><div className="stg-card">
                <div className="stg-top">
                  <span className="stg-title">下载数据</span>
                  <span className={`stg-stat ${s2stat[1]}`}>{s2stat[0]}</span>
                </div>
                {/* 取齐后收起：结论 + 存回电脑 + 重取 */}
                <div className="stg-inline">
                  {(hasEsiPack || hasIncitesPack) && <span className="hint">存回电脑：</span>}
                  {hasEsiPack && (
                    <a className="btn small" href={packHref('esi')}
                       title="把这一期已下载的 ESI 数据打包成 zip，存到你自己的电脑上">
                      <Icon name="download" size={16} />ESI 下载
                    </a>
                  )}
                  {hasIncitesPack && (
                    <a className="btn small" href={packHref('incites')}
                       title="把这一期已下载的 InCites 数据打包成 zip（包比较大，点完在下载栏等一会）">
                      <Icon name="download" size={16} />InCites 下载
                    </a>
                  )}
                  {!ro && (
                    <button type="button" className="btn small" disabled={!cap.start || busy}
                            title={cap.start ? '重取只补没下到的文件；已并入台账不受影响' : toolMissing}
                            onClick={onStart}>
                      <Icon name="download" size={16} />重新下载这一期
                    </button>
                  )}
                  {opStory && (
                    <span className="hint">
                      {opStopped ? '上次的下载被停止了' : '上次的下载中断了（下载程序已经停了）'}
                      {expected > 0 ? `；当前取到 ${verified} / ${expected}。` : '。'}
                    </span>
                  )}
                  {ro && (
                    <span className="hint">往期档案只读，不能再取（要补档只能在当期取）。</span>
                  )}
                  <button type="button" className="btn small" aria-expanded={showGroups}
                          onClick={() => setShowGroups((v) => !v)}>
                    <Icon name="doc" size={16} />下载清单
                  </button>
                </div>
                {showGroups && <div className="stg-extra">{groupsFold(true)}</div>}
                {/* 展开态 */}
                <div className="stg-body">
                  <div className="stg-big">{s2big}</div>
                  <div className="stg-sub">{s2sub}</div>
                  {fetchBusy && expected > 0 && (
                    <div className="stg-prog">
                      <span className="aq-track"><i style={{ transform: `scaleX(${Math.min(100, Math.round(verified / expected * 100)) / 100})` }} /></span>
                      <span className="aq-num">{verified} / {expected}</span>
                    </div>
                  )}
                  {showOpHero && !opStopped && expected > 0 && (
                    <div className="hint note-bad">
                      已取到 {verified} / {expected}。点「继续下载」只会补没下到的文件，已下过的不重复下载。
                    </div>
                  )}
                  {fetchBusy && (
                    <div className="hint">停止后已下载的文件都会保留，之后可以继续下载补缺的。</div>
                  )}
                  {opNoteLine && op?.kind !== 'copy' && op?.kind !== 'merge' && (
                    <div className="hint note-bad" title={op?.note || undefined}>{opNoteLine}</div>
                  )}
                  {/* 下载/整理做完后的说明话（比如已经并入台账的期次补下载——下载完成了，
                      但本地已有这一期的数据，所以没有再合并）。 */}
                  {op?.state === 'done' && op.kind === 'fetch' && op.note && (
                    <div className="hint" title={op.note}>{op.note}</div>
                  )}
                  {needsTool && !canRun && !fetchBusy && view !== 'review' && (
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
                  <div className="stg-cta">
                    {!ro && showOpHero && (
                      <button className="btn primary" disabled={!cap.start || busy}
                              title={cap.start ? undefined : toolMissing} onClick={onStart}>
                        <Icon name="download" size={20} />继续下载（补缺的）
                      </button>
                    )}
                    {!ro && fetchBusy && (
                      <ConfirmButton className="btn stop" confirmText="再点一次 · 确认停止" disabled={busy}
                                     onConfirm={() => { void act('stop') }}>
                        <Icon name="stop" size={20} />停止下载
                      </ConfirmButton>
                    )}
                    {!ro && !opBusy && view === 'ready' && pfPassed && (
                      <button className="btn primary" disabled={!cap.start || busy}
                              title={cap.start ? undefined : toolMissing} onClick={onStart}>
                        <Icon name="download" size={20} />开始下载数据
                      </button>
                    )}
                    {!ro && !opBusy && !opStory && view === 'running' && expected > 0 && (
                      <button className="btn primary" disabled={!cap.start || busy}
                              title={cap.start ? undefined : toolMissing} onClick={onStart}>
                        <Icon name="download" size={20} />继续下载（补缺的）
                      </button>
                    )}
                    {!ro && !opBusy && view === 'partial' && (
                      <button className="btn primary" disabled={!cap.retry || busy}
                              title={cap.retry ? undefined : toolMissing}
                              onClick={() => act('retry', failGroup?.id ? { group: failGroup.id } : undefined)}>
                        <Icon name="refresh" size={20} />重试这一组
                      </button>
                    )}
                  </div>
                  {(hasEsiPack || hasIncitesPack) && (
                    <div className="stg-packs">
                      <span className="hint">存回电脑：</span>
                      {hasEsiPack && (
                        <a className="btn small" href={packHref('esi')}
                           title="把这一期已下载的 ESI 数据打包成 zip，存到你自己的电脑上">
                          <Icon name="download" size={16} />ESI 下载
                        </a>
                      )}
                      {hasIncitesPack && (
                        <a className="btn small" href={packHref('incites')}
                           title="把这一期已下载的 InCites 数据打包成 zip（包比较大，点完在下载栏等一会）">
                          <Icon name="download" size={16} />InCites 下载
                        </a>
                      )}
                    </div>
                  )}
                  {/* 下载数据清单（明细，默认收起；回到段内） */}
                  {groupsFold()}
                </div>
              </div></div>
            </section>

            {/* ── ③ 并入台账（② 取齐后自动解锁） ── */}
            <section className={`stg ${view === 'merged' ? 'done' : view === 'review' ? 'now' : 'locked'}`}>
              <div className="node"><i>③</i></div>
              <div className="body"><div className="stg-card">
                <div className="stg-top">
                  <span className="stg-title">并入台账</span>
                  <span className={`stg-stat ${s3stat[1]}`}>{s3stat[0]}</span>
                </div>
                <div className="stg-inline">
                  <span className="hint">数据已写进主台账。</span>
                  <a className="btn small primary" href={`/app/?period=${encodeURIComponent(period)}`}>
                    <Icon name="play" size={16} />去生成台生成
                  </a>
                </div>
                <div className="stg-body">
                  {view === 'review' ? (
                    <>
                      <div className="stg-big">下载齐了。核对一下，就可以并入台账</div>
                      <div className="stg-sub">下面这张「本期新增列」核对表，就是将要写进 {period} 列的全部数字。</div>
                      {copyBusy && (
                        <div className="hint" title={op?.note || undefined}>{OP_CN[op?.kind ?? ''] ?? '正在处理'}……</div>
                      )}
                      {opNoteLine && (op?.kind === 'copy' || op?.kind === 'merge') && (
                        <div className="hint note-bad" title={op?.note || undefined}>{opNoteLine}</div>
                      )}
                      {showReview && reviewSheets.length > 0 && (
                        <details className="fold" open>
                          <summary>本期新增列核对表<span className="sm">{reviewSheets.length} 张表</span></summary>
                          <div className="fold-inner">
                            <p className="hint m-b-8">将并入主台账 {period} 列；历史列不动。</p>
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
                      <div className="stg-cta">
                        <ConfirmButton className="btn primary" confirmText="再点一次 · 确认并入"
                                       disabled={!cap.merge || busy}
                                       onConfirm={() => { void act('merge') }}>
                          <Icon name="check" size={20} />核对无误 · 并入台账
                        </ConfirmButton>
                        <span className="hint">并入是唯一会写主台账的动作：写前自动备份、写后逐项复查。</span>
                      </div>
                      {needsTool && !cap.merge && (
                        <div className="hint note-warn">{toolMissing}</div>
                      )}
                    </>
                  ) : (
                    <div className="stg-sub">这一段不用手动开：② 的 {expected > 0 ? expected : 64} 份都核验通过后，这里会自动生成核对表。</div>
                  )}
                </div>
              </div></div>
            </section>
          </div>

          {state.updated_at && (
            <p className="hint mt-12 aq-stamp">下载数据状态最后更新：{state.updated_at}</p>
          )}
        </>
      )}
    </>
  )
}
