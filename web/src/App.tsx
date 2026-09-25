/* 文衡 · 工作台（外壳）
   一个应用两屏：工作台（工具面，本文件）→ 陈列馆（G 的体验，挂在 /app/shelf/）。
   数据全部来自后端 API；接口没就绪的地方**如实标注"未就绪"**，不编数据。 */

import { useEffect, useMemo, useState } from 'react'
import {
  getHealth, getMe, getPeriodDetail, getPeriods, jobEventsUrl, postJob,
  type ApiError, type Me, type Period, type PeriodDetail,
} from './api'

/** 一次真实生成的过程（SSE 推来的）：状态 / 最后一行进度 / 最近若干行日志 */
export type Run = { jobId: string; status?: string; last?: string; lines: string[] }
import { Icon, Sprite } from './icons'
import { Workbench } from './Workbench'
import { Report } from './Report'
import { Review } from './Review'
import { Ledger } from './Ledger'
import { Analysis } from './Analysis'
import { RedList } from './RedList'
import { Charts } from './Charts'
import { Reading } from './Reading'
import { Trace } from './Trace'
import { Tools } from './Tools'
import { Forecast } from './Forecast'
import { Archive } from './Archive'
import { deriveWorkbench, isTerminal, statusToWB, type WBState } from './wb'

const DEMO_STATES: WBState[] = ['empty', 'ready', 'running', 'done', 'fail-ledger', 'fail-other', 'stalled', 'signed']

export default function App() {
  const [healthy, setHealthy] = useState<boolean | null>(null)
  const [me, setMe] = useState<Me | null>(null)
  /* 角色是否已有结论：false = 还没问过（探活失败 / 首屏）；true = 问过了（me 为 null 即未登录） */
  const [roleKnown, setRoleKnown] = useState(false)
  const [periods, setPeriods] = useState<Period[]>([])
  const [selected, setSelected] = useState<string | null>(null)
  const [detail, setDetail] = useState<PeriodDetail | null>(null)
  const [err, setErr] = useState<ApiError | null>(null)
  const [busy, setBusy] = useState(false)
  const [run, setRun] = useState<Run | null>(null)

  /* ?period= 深链：从老站迁移过来的等价地址（老站 /p/<期次> → 新站 ?view=report&period=<期次>） */
  const wantPeriod = new URLSearchParams(location.search).get('period')
  const _v = new URLSearchParams(location.search).get('view')
  const view: 'workbench' | 'report' | 'review' | 'ledger' | 'analysis' | 'red' | 'charts' | 'reading' | 'trace' | 'forecast' | 'archive' =
    _v === 'report' ? 'report'
      : _v === 'review' ? 'review'
        : _v === 'ledger' ? 'ledger'
          : _v === 'analysis' ? 'analysis'
            : _v === 'red' ? 'red'
              : _v === 'charts' ? 'charts'
                : _v === 'reading' ? 'reading'
                  : _v === 'trace' ? 'trace'
                    : _v === 'forecast' ? 'forecast'
                      : _v === 'archive' ? 'archive'
                        : 'workbench'

  const demo = useMemo(() => {
    const v = new URLSearchParams(location.search).get('demo') as WBState | null
    return v && DEMO_STATES.includes(v) ? v : null
  }, [])   // eslint-disable-line react-hooks/exhaustive-deps -- wantPeriod 只在首屏读一次

  useEffect(() => {
    let alive = true
    ;(async () => {
      const ok = await getHealth()
      if (!alive) return
      setHealthy(ok)
      if (!ok) return
      const m = await getMe()
      if (!alive) return
      setMe(m)
      setRoleKnown(true)
      try {
        const list = await getPeriods()
        if (!alive) return
        setPeriods(list)
        const hit = wantPeriod && list.some((p) => p.period === wantPeriod)
        setSelected(hit ? wantPeriod : (list[0]?.period ?? null))
      } catch (e) {
        if (alive) setErr(e as ApiError)
      }
    })()
    return () => { alive = false }
  }, [])

  useEffect(() => {
    if (!selected) { setDetail(null); return }
    let alive = true
    getPeriodDetail(selected).then((d) => { if (alive) setDetail(d) })
    return () => { alive = false }
  }, [selected])

  const wb0 = deriveWorkbench(selected, periods, detail, healthy === true, demo)
  /* 真实生成进行中/刚结束：状态以后端任务为准（权威），不被列表推断盖过 */
  const wb = run && run.status && !isTerminal(run.status)
    ? { ...wb0, state: statusToWB(run.status) }
    : run && run.status
      ? { ...wb0, state: statusToWB(run.status) }
      : wb0

  /* 上传台账 / 重跑后的接续：与 onGenerate 同一套（订阅同一个任务的事件流） */
  function attachRun(jobId: string) {
    setRun({ jobId, lines: [] })
  }

  async function onGenerate() {
    if (!selected) return
    setBusy(true)
    setErr(null)
    try {
      const r = await postJob(selected)
      setRun({ jobId: r.job_id, lines: [] })
    } catch (e) {
      const h = e as { status?: number; body?: ApiError; message?: string }
      setErr(h.body ?? { error: h.message ?? '生成请求失败' })
    } finally {
      setBusy(false)
    }
  }

  /* 订阅任务事件流：progress＝进度行 / log＝{line} / status＝任务对象。
     流在后端结束时关闭；终态到了就刷新期次列表（让"已出稿/已签发"跟着变）。 */
  useEffect(() => {
    const id = run?.jobId
    if (!id) return
    const es = new EventSource(jobEventsUrl(id))
    es.addEventListener('progress', (e) => {
      const line = (e as MessageEvent).data as string
      setRun((r) => (r && r.jobId === id ? { ...r, last: line } : r))
    })
    es.addEventListener('log', (e) => {
      try {
        const d = JSON.parse((e as MessageEvent).data) as { line: string }
        setRun((r) => (r && r.jobId === id
          ? { ...r, lines: [...r.lines.slice(-60), d.line] } : r))
      } catch { /* 非 JSON 的日志行忽略 */ }
    })
    es.addEventListener('status', (e) => {
      try {
        const j = JSON.parse((e as MessageEvent).data) as { status?: string }
        setRun((r) => (r && r.jobId === id ? { ...r, status: j.status } : r))
        if (isTerminal(j.status)) {
          es.close()
          getPeriods().then(setPeriods).catch(() => { /* 列表刷新失败不影响过程展示 */ })
        }
      } catch { /* 忽略 */ }
    })
    es.onerror = () => { es.close() }   /* 后端关闭/断线：停掉，不要让浏览器反复重连 */
    return () => es.close()
  }, [run?.jobId])

  /* 工作区导航（契约 §4：前端按 /api/me 的 role 决定显示什么；**真门在后端**，这里只是不打扰）。
     游客只留 报告 / 台账 / 陈列馆 这些「看已出的东西」的屏；管理页直连也挡在这里，给一句人话 + 去处。 */
  const NAV: { view: string; label: string; icon: string; href: string; admin?: boolean }[] = [
    { view: 'workbench', label: '生成台', icon: 'play', href: '/app/', admin: true },
    { view: 'report', label: '报告', icon: 'chart', href: '/app/?view=report' },
    { view: 'review', label: '审核台', icon: 'seal', href: '/app/?view=review', admin: true },
    { view: 'ledger', label: '台账', icon: 'doc', href: '/app/?view=ledger' },
    { view: 'analysis', label: '分析台', icon: 'chart', href: '/app/?view=analysis', admin: true },
    { view: 'forecast', label: '预测台', icon: 'trend', href: '/app/?view=forecast', admin: true },
    { view: 'shelf', label: '陈列馆', icon: 'book', href: '/app/shelf/' },
  ]
  const isGuest = me?.role === 'guest'
  const notLoggedIn = roleKnown && !me
  /* 未登录按游客待遇：管理入口不渲染（此前 fail-open——401 被当成「角色未知」，管理页照常开） */
  const gated = notLoggedIn || isGuest
  /* 角色还没确认时，先不渲染只给管理员的块（避免游客先发出被拒的请求） */
  const noAdminBits = !roleKnown || gated
  /* charts（图册）后端允许 guest 读（契约 §7.1），所以不进这张表 */
  const ADMIN_VIEWS = new Set(['workbench', 'review', 'analysis', 'forecast', 'archive', 'trace', 'red'])
  const denied = gated && ADMIN_VIEWS.has(view)
  const navHref = (h: string) =>
    (selected && h.startsWith('/app/?') ? `${h}&period=${encodeURIComponent(selected)}` : h)

  return (
    <>
      <Sprite />
      <header className="topbar">
        <div className="brand">
          <strong>文衡</strong>
          <span>学科信息参考</span>
        </div>
        <nav className="nav" aria-label="工作区">
          {NAV.filter((n) => !n.admin || !gated).map((n) => (
            <a key={n.view} href={navHref(n.href)}
               aria-current={view === n.view ? 'page' : undefined}>
              <Icon name={n.icon} size={19} />{n.label}
            </a>
          ))}
        </nav>
        <div className="who">
          <span className="avatar">{me?.name?.slice(0, 1) ?? '？'}</span>
          {me?.name ?? (roleKnown ? '未登录' : '角色未知')}
          {me?.role
            ? ` · ${me.role === 'admin' ? '管理员' : '游客'}`
            : notLoggedIn
              ? <> · <a href="/login">去登录</a></>
              : '（未提供 /api/me）'}
        </div>
      </header>

      <main className="wrap">
        {healthy === false && (
          <div className="banner bad" style={{ marginTop: 0 }}>
            <span className="ico"><Icon name="alert" size={22} /></span>
            <span>
              <b className="title">连不上本机服务</b>
              <ul>
                <li>后端没有响应 —— 检查它是否在运行（`/healthz`）。</li>
                <li>下面显示的期次列表可能不完整；你的台账与已出的报告都没有受影响。</li>
              </ul>
            </span>
          </div>
        )}

        {denied ? (
          <div className="pending-box" style={{ marginTop: 0 }}>
            {notLoggedIn ? (
              <><b>请先登录</b> —— 生成台 / 审核台 / 分析台 / 预测台要馆员账号，
                <a href="/login">去登录</a>后再来（游客账号只能看已出的东西）。
              </>
            ) : (
              <><b>这一屏要馆员账号</b> —— 生成台 / 审核台 / 分析台 / 预测台是馆员的工作区，
                你现在是游客身份（只能看已出的东西）。
              </>
            )}
            想看这一期报告去「<a href={navHref('/app/?view=report')}>报告</a>」，
            想按期翻看卷宗去「<a href="/app/shelf/">陈列馆</a>」。
          </div>
        ) : view === 'archive' ? (
          <Archive period={selected} />
        ) : view === 'forecast' ? (
          <Forecast />
        ) : view === 'trace' ? (
          <Trace period={selected} />
        ) : view === 'reading' ? (
          <Reading period={selected} />
        ) : view === 'charts' ? (
          <Charts period={selected} />
        ) : view === 'red' ? (
          <RedList period={selected} />
        ) : view === 'analysis' ? (
          <Analysis period={selected} />
        ) : view === 'ledger' ? (
          <Ledger />
        ) : view === 'review' ? (
          <Review
            period={selected}
            me={me}
            periods={periods}
            onChanged={() => { getPeriods().then(setPeriods).catch(() => { /* 刷新失败不影响操作结果 */ }) }}
          />
        ) : view === 'report' ? (
          <Report periods={periods} current={selected} onPick={setSelected} guest={noAdminBits} />
        ) : (
          <>
                      <Workbench
                        period={selected}
                        me={me}
                        wb={wb}
                        err={err}
                        healthy={healthy === true}
                        run={run}
                        onGenerate={onGenerate}
                      />
            {!noAdminBits && <Tools period={selected} jobId={run?.jobId ?? null} onUploaded={(jid) => attachRun(jid)} />}
          </>
        )}

        <a className="entry" href="/app/shelf/">
          <span>
            <span className="t">陈列馆 · 历期卷宗</span>
            <span className="d">按期翻看已出刊的报告（书架 → 端详 → 开卷）</span>
          </span>
          <span className="go" aria-hidden="true">→</span>
        </a>

        {view === 'workbench' && (
        <section className="card tablewrap" style={{ marginTop: 18 }}>
          <table className="periods">
            <thead>
              <tr>
                <th>期次</th><th>目录名</th><th>状态</th><th style={{ width: 90 }}>操作</th>
              </tr>
            </thead>
            <tbody>
              {periods.length === 0 && (
                <tr><td colSpan={4} style={{ color: 'var(--ink-3)' }}>
                  {healthy === false ? '服务未启动，读不到期次。' : '暂无期次。'}
                </td></tr>
              )}
              {periods.map((p) => (
                <tr key={p.period}
                    onClick={() => setSelected(p.period)}
                    style={{ cursor: 'pointer', background: p.period === selected ? 'var(--panel)' : undefined }}>
                  <td>{p.label}</td>
                  <td className="mono">{p.period}</td>
                  <td>
                    <span className={`pill ${p.status === 'signed' ? 'signed' : p.status === 'stale' ? 'stale' : 'unsigned'}`}>
                      {p.status === 'signed' ? '已签发' : p.status === 'stale' ? '签名已失效' : '未签发'}
                    </span>
                  </td>
                  <td>
                    <a href={`/app/?view=report&period=${encodeURIComponent(p.period)}`}
                       onClick={(e) => e.stopPropagation()}>打开</a>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </section>
        )}

        <p className="hint" style={{ marginTop: 14 }}>
          {busy && '正在提交生成请求……'}
          {!busy && '演示时想直接看某个状态（空/生成中/失败…）可在网址后加 '}
          {!busy && <code>?demo=fail-ledger</code>}
        </p>
      </main>
    </>
  )
}
