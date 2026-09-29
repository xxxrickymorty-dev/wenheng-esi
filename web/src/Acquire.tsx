/* 自动取数台（X2·票 12）：工作流第一站——取数 → 核对并并入 → 生成。
   只读视图：状态全部来自 GET /api/periods/{period}/acquisition（服务端只读）。
   重试/并入等写动作由人按（写路径与机械保证见 docs/adr/0004）；按钮可用性读状态里的
   capabilities——工具还没接入时按钮禁用并说明，不假装能点。
   静态稿对照：web/mockups/取数台.html；契约：§2.2 #26。 */

import { useCallback, useEffect, useState } from 'react'
import { getAcquisition, type AcquisitionState, type AcqGroup } from './api'
import { Info } from './Info'
import { Icon } from './icons'

/** 组/文件状态 → 馆员话术（与静态稿一致；不认识的取值原样显示，不编） */
const GROUP_STATE: Record<string, string> = {
  pending: '未开始', live: '下载中', done: '核验通过', fail: '有未通过', retrying: '重新核验中',
}
const FILE_STATE: Record<string, string> = {
  pending: '待取数', received: '已收到 · 待核验', ok: '核验通过', bad: '未通过',
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

function GroupCard({ g }: { g: AcqGroup }) {
  const files = g.files ?? []
  const stateText = g.state ? (GROUP_STATE[g.state] ?? g.state) : '未开始'
  const pct = files.length > 0 ? Math.min(100, Math.round((g.verified ?? 0) / files.length * 100)) : 0
  const srcName = g.source ? (SOURCE_NAME[g.source] ?? g.source) : ''
  return (
    <article className={`aq-g ${groupStateClass(g.state)}`}>
      <div className="aq-gtop">
        <span className="aq-src">{srcName}{g.index ? ` · 第 ${g.index} 组` : ''}</span>
        <span className={`aq-gstat ${groupStateClass(g.state)}`}>{stateText}</span>
      </div>
      <div className="aq-gname"><Icon name="doc" size={18} />{g.title ?? '未命名组'}</div>
      <div className="aq-bar">
        <span className="aq-track"><i style={{ width: `${pct}%` }} /></span>
        <span className="aq-num">{g.verified ?? 0} / {files.length || '—'}</span>
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
                  <span className={`aq-fres ${cls}`}>{f.state ? (FILE_STATE[f.state] ?? f.state) : '待取数'}</span>
                </li>
              )
            })}
          </ul>
        </details>
      )}
      {g.state === 'fail' && <p className="aq-gnote">没通过的可在本组重试，已通过的不重复下载。</p>}
    </article>
  )
}

export function Acquire({ period }: { period: string | null }) {
  const [state, setState] = useState<AcquisitionState | null>(null)
  const [note, setNote] = useState<string | null>(null)
  const [loading, setLoading] = useState(false)

  const load = useCallback(() => {
    if (!period) { setState(null); setNote(null); return }
    setLoading(true)
    getAcquisition(period)
      .then((s) => { setState(s); setNote(null) })
      .catch((e) => {
        const h = e as { status?: number; body?: { error?: string; hint?: string }; message?: string }
        setState(null)
        setNote(h.status === 403 ? '取数台要管理员权限（用馆员账号登录后再来）。'
          : h.status === 404 ? '这个期次还认不出来（期次用六位数字）。'
            : (h.body?.hint ?? h.body?.error ?? h.message ?? '读取数状态失败。'))
      })
      .finally(() => setLoading(false))
  }, [period])

  useEffect(() => { load() }, [load])

  if (!period) {
    return <div className="pending-box">先在顶栏选一个期次；取数台会显示这一期的取数进度与核对状态。</div>
  }

  const started = !!state?.started
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
  const cap = state?.capabilities ?? {}
  const toolMissing = '取数工具还没接入；接入后这里就能一键执行。'
  const capKey: 'start' | 'retry' | 'merge' = view === 'partial' ? 'retry' : view === 'review' ? 'merge' : 'start'
  const needsTool = view === 'ready' || view === 'partial' || view === 'review'
  const canRun = !!cap[capKey]
  const dp = state?.data_period
  const dataPeriodText = dp && (dp.esi || dp.incites)
    ? `（${[dp.esi ? `ESI ${dp.esi}` : '', dp.incites ? `InCites 截至 ${dp.incites}` : ''].filter(Boolean).join(' · ')}）`
    : ''

  const pill: Record<PageView, [string, string]> = {
    ready: ['还没开始', 'unsigned'],
    blocked: ['还没开始', 'unsigned'],
    running: ['取数中', 'stale'],
    partial: [`有 ${failed} 份未通过`, 'bad'],
    review: ['待核对', 'stale'],
    merged: ['已并入', 'signed'],
  }

  const title = view === 'ready'
    ? (started ? '开始前检查通过，可以开始取数。' : '还没开始取数。')
    : view === 'blocked' ? '取数专用浏览器还没准备好。'
      : view === 'running' ? `正在取数${liveGroup?.title ? `：${liveGroup.title}` : ''}……`
        : view === 'partial' ? `${failGroup?.title ?? '有一组'}有 ${failed} 份没通过核验。`
          : view === 'review' ? '本期监测表已自动建好，请核对。'
            : `已并入主台账（${period} 列）。`
  const sub = view === 'ready'
    ? (started ? '9 组文件，取到后逐份核验。' : '在取数专用浏览器里登录两家网站，检查通过即可开始。')
    : view === 'blocked' ? '先双击它并登录两家网站，再点「重新检查」。'
      : view === 'running' ? '可以离开这一页，进度不会丢。'
        : view === 'partial' ? '重试只补这一组，通过的不重复下载。'
          : view === 'review' ? `核对无误后并入台账（只动 ${period} 列）。`
            : '下一步：去生成台一键生成。'

  return (
    <>
      <p className="hint" style={{ marginTop: 2 }}>
        <a href={`/app/?period=${encodeURIComponent(period)}`}>← 回生成台</a>
        {' · '}自动取数 · 期次 <b className="mono">{period}</b>
      </p>

      {note && <div className="pending-box">{note}<button type="button" className="btn" style={{ marginLeft: 10 }} onClick={load}>重新读取</button></div>}
      {!state && !note && <div className="pending-box">{loading ? '正在读取取数状态……' : '还没有读到取数状态。'}</div>}

      {state && (
        <>
          {/* ===== 期次数据状态 ===== */}
          <section className="card" style={{ padding: '20px 24px' }}>
            <div className="aq-head">
              <h1 style={{ fontSize: 24 }}>自动取数台</h1>
              <span className="pill unsigned mono">{period}</span>
              <span className={`pill ${pill[view][1]}`}>{pill[view][0]}</span>
              <span className="hint aq-num">{expected > 0 ? `已核验 ${verified} / ${expected}` : '已核验 —'}</span>
              <Info label="取数状态与口径">
                <p>进度按逐份核验结果统计：只有核验通过的文件才计入。</p>
                <p>数据期取自网站页面显示值{dataPeriodText}，不以下载当天代替。</p>
                <p>「下载完成」不等于「台账已更新」：先核对本期监测表，核对通过才并入主台账；并入只动本期列，历史一字不变。</p>
              </Info>
            </div>
          </section>

          {/* ===== 主动作（每屏 1 个） ===== */}
          <div className="focus">
            <div>
              <div className="big">{title}</div>
              <div className="sub">{sub}</div>
              {needsTool && !canRun && (
                <div className="hint" style={{ marginTop: 6, color: 'var(--warn)' }}>{toolMissing}</div>
              )}
            </div>
            <div className="cta">
              {view === 'ready' && (
                <button className="btn primary" disabled={!cap.start} title={cap.start ? undefined : toolMissing}>
                  <Icon name="download" size={20} />开始取数
                </button>
              )}
              {view === 'blocked' && (
                <button className="btn" onClick={load}><Icon name="refresh" size={20} />重新检查</button>
              )}
              {view === 'partial' && (
                <button className="btn primary" disabled={!cap.retry} title={cap.retry ? undefined : toolMissing}>
                  <Icon name="refresh" size={20} />重试这一组
                </button>
              )}
              {view === 'review' && (
                <button className="btn primary" disabled={!cap.merge} title={cap.merge ? undefined : toolMissing}>
                  <Icon name="check" size={20} />核对无误 · 并入台账
                </button>
              )}
              {view === 'merged' && (
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
            <Info label="开始前检查什么" end>
              <p>检查取数专用的浏览器是否开着、两家网站是否已登录。登录由馆员手动完成；本页不接触、不保存账号密码。检查通过后才能开始。</p>
            </Info>
          </div>

          {/* ===== 取数清单（明细，默认收起） ===== */}
          <details className="fold">
            <summary>取数清单<span className="sm">{totals.groups ?? groups.length ?? 9} 组 · {expected > 0 ? `${expected} 份` : '份数待定'}</span></summary>
            <div className="fold-inner">
              {groups.length === 0 ? (
                <p className="hint" style={{ margin: 0 }}>还没有取数记录。开始取数后，这里按组列出每一份文件与核验结果。</p>
              ) : (
                <>
                  <p className="hint" style={{ margin: '0 0 10px' }}>每份文件核验通过才计入；没通过的可在本组重试。</p>
                  <div className="aq-groups">
                    {groups.map((g, i) => <GroupCard key={g.id ?? i} g={g} />)}
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
                <p className="hint" style={{ margin: '0 0 8px' }}>
                  将并入主台账的 {period} 列；并入只动这些列，历史列一字不变。
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
            <p className="hint" style={{ marginTop: 12 }}>取数状态最后更新：{state.updated_at}</p>
          )}
        </>
      )}
    </>
  )
}
