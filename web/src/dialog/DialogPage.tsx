/* 对话前门（票 01–05、07：期次识别 → 盘点 → 核对门 → 出稿两段式 → 两意图路由）。
   版面照 `mockups/对话前门.html`（五稿）：左＝对话历史 / 中＝对话流 / 底＝输入框。
   口径照 ADR-0006：对话只做指挥——数字全部来自后端；
   解析与路由走 `/api/dialog/turn`（后端 src/ai 能力口，规则版离线可跑）；
   **查数据**（kind="query"）的回答由服务器按意图调 qa 能力，本页只渲染（带角标可点来源）；
   **写报告＝两段式（票 05 口径 A）**：先走**既有**灵活报告流式口 `/api/periods/{p}/flexible/stream`
   （轨迹逐段出 + 停止键），流完**自动接复刻产线**（既有 `POST /api/jobs`）——
   出好了＝报告初稿 / 对勘本 / 红件清单；覆盖确认＝行内二次确认（复用 `ConfirmButton`），
   回滚走既有 `rollback-points` / `rollback`（旧稿在 `_superseded/`）。 */

import { useEffect, useRef, useState } from 'react'
import { getAiCapabilities, getArtifacts, getJobProgress, getMe, getPeriods,
         getRollbackPoints, postAiSwitch, postJob, rollbackPeriod,
         type AiCapability, type Me, type RollbackPoint } from '../api'
import { postDialogTurn, type DialogAction, type DialogAnswer, type DialogRun } from '../api-dialog'
import { runFlexibleStream, stopFlexible, type FlexCheck, type FlexStreamEvent } from '../api-flexible'
import { ConfirmButton } from '../ConfirmButton'
import { clearSlot, conversationTitle, emptySlots, hasSlots, type DialogSlots } from '../lib/dialog'
import { buildPeriodUrl } from '../lib/period'
import { trioLinks, type TrioLink } from '../lib/repro'
import { latestProgress } from '../lib/runMachine'
import { appHref, errorNote, isTerminalState, taskLabel } from '../lib/status'
import { NumberedText } from '../NumberedText'

/** 出稿轨迹（票 04）：逐段出（挑学科 / 配图 / 取数 / 数据校验 / 收尾 / 复刻）。
    全部文字由事件与接口字段组装（视图层只读，不现算数字）。 */
type TraceStep = { n: number; title: string; detail: string; state: 'doing' | 'done' | 'halt' }
type Trace = {
  status: 'streaming' | 'done' | 'stopped' | 'error'
  steps: TraceStep[]
  note?: string
  /** 出好了（票 05）：三件套下载 + 运行档案 + 回滚出路 */
  result?: TraceResult
}
type TraceResult = {
  period: string
  /** 实产三件（报告初稿 / 对勘本 / 红件清单；缺谁不凑） */
  artifacts?: TrioLink[]
  /** 该期当前是否已签发——报告初稿（docx）未签发不能下载（平台既有闸，见生成台同款） */
  signed?: boolean
  archiveHref: string
  /** 有留档才出现——回滚到上一版（旧稿在 `_superseded/`） */
  rollback?: { points: RollbackPoint[]; out?: string }
  /** 校验没过 / 没出成：给「自动修复」的出路（flex＝重出灵活稿；repro＝重跑复刻） */
  fixable?: 'flex' | 'repro'
}
type Turn = { who: 'me' | 'wh' | 'sys'; text: string; notice?: string; actions?: DialogAction[]
              dismissed?: boolean; run?: DialogRun; trace?: Trace; answer?: DialogAnswer }
type Conversation = { id: number; title: string; turns: Turn[]; slots: DialogSlots }

const PALETTE_STORAGE_KEY = 'wenheng-palette'

/** 工作台入口（按需打开；深链保留）——与 mockup 顶栏「工作台 ▾」一致。 */
const WORKBENCH: [string, string][] = [
  ['生成台', '/app/'],
  ['AI 分析台 · 灵活报告', '/app/?view=analysis'],
  ['取数台', '/app/?view=acquire'],
  ['审核台 · 对勘本', '/app/?view=review'],
  ['运行档案', '/app/?view=archive'],
  ['陈列馆', '/app/shelf/'],
]

function initialPalette(): 'ynu' | 'zhu' {
  try {
    return localStorage.getItem(PALETTE_STORAGE_KEY) === 'zhu' ? 'zhu' : 'ynu'
  } catch {
    return 'ynu'
  }
}

const sleep = (ms: number) => new Promise<void>((resolve) => window.setTimeout(resolve, ms))

/** 自检明细（票 05）→ 没过的那几条（馆员话术；全过给空表）。 */
function checkFailures(c?: FlexCheck): string[] {
  if (!c) return ['自检明细没拿到（去运行档案看）']
  const out: string[] = []
  if (!c.trace_ok) out.push(`有 ${c.trace_bad} 处数字没指回台账`)
  if (!c.has_charts) out.push('一张图都没出')
  if (!c.hypotheses_complete) out.push('待验证假设不完整')
  if (!c.no_professional_judgement) out.push('正文里出现了专业判断')
  return out
}

function checkSummary(ev: FlexStreamEvent & { event: 'done' }, sections: number): string {
  return `${ev.n_sources ?? 0} 个数据点能指回台账 · 图 ${ev.n_charts} 张 · 章节 ${ev.n_sections ?? sections} 节`
}

/** 出好了的那句话（口径 A＝两段都出完；warned＝复刻有提醒，去档案看明细）。 */
function okNote(ev: (FlexStreamEvent & { event: 'done' }) | undefined, warned: boolean): string {
  const base = ev ? `数据校验一次通过（${checkSummary(ev, 0)}）。` : ''
  const tail = warned ? '复刻产线跑完有提醒——去运行档案看明细。' : ''
  return `出好了——${base}${tail}三件套：`
}

function freshConversation(id: number): Conversation {
  return { id, title: '', turns: [], slots: emptySlots() }
}

export default function DialogPage() {
  const [palette, setPalette] = useState(initialPalette)
  const [me, setMe] = useState<Me | null>(null)
  const [roleKnown, setRoleKnown] = useState(false)
  const [convs, setConvs] = useState<Conversation[]>(() => [freshConversation(1)])
  const [activeId, setActiveId] = useState(1)
  const [input, setInput] = useState('')
  const [busy, setBusy] = useState(false)
  /* 「查数据」能力开关（票 07）：问文衡并入前门——开关跟着能力放这儿（管理员可关）。 */
  const [qa, setQa] = useState<AiCapability | null>(null)
  const [qaBusy, setQaBusy] = useState(false)
  /* 正在出稿的那条回复（停止键要用：期次 + 消息下标 + run 令牌） */
  const [running, setRunning] = useState<{ period: string; index: number } | null>(null)
  const runTokenRef = useRef<string>('')
  const [tick, setTick] = useState(0)
  const nextIdRef = useRef(2)
  const threadRef = useRef<HTMLDivElement>(null)

  const active = convs.find((c) => c.id === activeId) ?? convs[0]
  const others = convs.filter((c) => c.turns.length > 0)

  useEffect(() => {
    document.documentElement.dataset.palette = palette
    try {
      localStorage.setItem(PALETTE_STORAGE_KEY, palette)
    } catch {
      /* 浏览器不允许保存时，当前页面仍可正常切换 */
    }
  }, [palette])

  useEffect(() => {
    let alive = true
    void (async () => {
      const m = await getMe()
      if (!alive) return
      setMe(m)
      setRoleKnown(true)
      /* 工作区只对馆员开放：游客送回陈列馆（与工作台同一待遇） */
      if (m && m.role !== 'admin') window.location.replace('/app/shelf/')
    })()
    return () => { alive = false }
  }, [])

  useEffect(() => {
    let alive = true
    getAiCapabilities()
      .then((cs) => { if (alive) setQa(cs.find((c) => c.id === 'qa') ?? null) })
      .catch(() => { /* 拿不到开关表就不显示开关——真门在后端 */ })
    return () => { alive = false }
  }, [])

  /** 开关「查数据」（qa 能力）：关闭后对话里照旧说「已关闭」，报告不受影响。 */
  async function toggleQa(next: boolean) {
    setQaBusy(true)
    try {
      await postAiSwitch('qa', next)
      setQa((c) => (c ? { ...c, enabled: next } : c))
    } finally { setQaBusy(false) }
  }

  useEffect(() => {
    const el = threadRef.current
    if (el) el.scrollTop = el.scrollHeight
  }, [activeId, active.turns.length, busy, running, tick])

  function updateActive(fn: (c: Conversation) => Conversation) {
    setConvs((list) => list.map((c) => (c.id === activeId ? fn(c) : c)))
  }

  function newChat() {
    const conv = freshConversation(nextIdRef.current++)
    setConvs((list) => [conv, ...list])
    setActiveId(conv.id)
    setInput('')
  }

  async function sendText(raw: string) {
    const text = raw.trim()
    if (!text || busy || running) return
    setInput('')
    setBusy(true)
    const replyIndex = active.turns.length + 1          // 先发用户话，回复接在它后面
    updateActive((c) => ({
      ...c,
      title: c.title || conversationTitle(text),
      turns: [...c.turns, { who: 'me', text }],
    }))
    try {
      const r = await postDialogTurn(text, active.slots)
      updateActive((c) => ({
        ...c,
        slots: r.slots,
        turns: [...c.turns, { who: 'wh', text: r.text, notice: r.notice,
                              actions: r.actions, run: r.run ?? undefined,
                              answer: r.answer ?? undefined }],
      }))
      /* 出稿意图（票 03/04）：auto=true 直接开跑；产物已在时 auto=false，等人在按钮上点 */
      if (r.run?.auto && r.run.period) void startRun(r.run.period, replyIndex, r.run.intent)
    } catch (e) {
      updateActive((c) => ({
        ...c,
        turns: [...c.turns, { who: 'wh', text: `这轮没成功。${errorNote(e, '这轮对话')}` }],
      }))
    } finally {
      setBusy(false)
    }
  }

  /** 「先等等」：只是界面收起这一行动作，不发请求、不落账。 */
  function dismissActions(index: number) {
    updateActive((c) => ({
      ...c,
      turns: c.turns.map((t, i) => (i === index ? { ...t, dismissed: true } : t)),
    }))
  }

  /** 轨迹更新器：只动某一条回复的 trace（不碰别的轮次）。 */
  function traceUpdater(index: number) {
    return (fn: (t: Trace) => Trace) => {
      updateActive((c) => ({
        ...c,
        turns: c.turns.map((t, i) => (i === index && t.trace ? { ...t, trace: fn(t.trace) } : t)),
      }))
      setTick((x) => x + 1)
    }
  }

  /** 出稿第一段（票 04/05）：走**既有**灵活报告流式口（NDJSON，真实节点）——
      轨迹逐段落在回复里；发送键原地变停止键；流完且校验通过 → 自动接复刻产线（第二段）。
      校验没过：**不带着问题出稿**——停下明说哪条没过，给「自动修复 / 需人工接手」。 */
  async function startRun(period: string, index: number, intent: string) {
    if (!period || running) return
    runTokenRef.current = ''
    setRunning({ period, index })
    const upd = traceUpdater(index)
    const trace0: Trace = { status: 'streaming', steps: [
      { n: 1, title: '挑学科', detail: '正在规划…', state: 'doing' }] }
    updateActive((c) => ({
      ...c,
      turns: c.turns.map((t, i) => (i === index ? { ...t, trace: trace0 } : t)),
    }))
    let sections = 0
    const doneRef: { ev: (FlexStreamEvent & { event: 'done' }) | null } = { ev: null }
    try {
      await runFlexibleStream(period, { intent }, (ev: FlexStreamEvent) => {
        if (ev.event === 'status') {
          runTokenRef.current = ev.run ?? ''
        } else if (ev.event === 'plan') {
          const cons = ev.considered ?? []
          const pick = cons.length
            ? `还没进 1% 的里离过线最近：${cons.map((c) => `${c.disc_cn}（${c.proximity}）`).join(' ＞ ')}；本期挑 ${cons[0].disc_cn}`
            : `本期挑 ${ev.disc || '（按规划）'}`
          const charts = ev.charts ?? []
          upd((t) => ({ ...t, steps: [
            { n: 1, title: '挑学科', detail: pick, state: 'done' },
            { n: 2, title: '配图',
              detail: charts.length ? `${charts.length} 张：${charts.map((c) => c.why || c.kind).join('；')}`
                                    : '按规划出图',
              state: 'done' },
            { n: 3, title: '取数', detail: '逐节取数与写稿…', state: 'doing' },
          ] }))
        } else if (ev.event === 'section') {
          sections += 1
          upd((t) => ({ ...t, steps: t.steps.map((s) =>
            s.n === 3 ? { ...s, detail: `逐节取数与写稿：已完成 ${sections} 节…` } : s) }))
        } else if (ev.event === 'done') {
          doneRef.ev = ev
          if (ev.check_pass) {
            upd((t) => ({
              ...t,
              steps: [
                ...t.steps.map((s) => ({ ...s, state: 'done' as const })),
                { n: 4, title: '数据校验',
                  detail: `一次通过（${checkSummary(ev, sections)}）`, state: 'done' },
                { n: 5, title: '收尾', detail: `分析稿已出（用时 ${ev.elapsed} 秒）`, state: 'done' },
              ],
              note: '数据校验一次通过——接着生成报告初稿（复刻产线）…',
            }))
          } else {
            upd((t) => ({
              ...t,
              status: 'error',
              steps: [
                ...t.steps.map((s) => ({ ...s, state: 'halt' as const })),
                { n: 4, title: '数据校验',
                  detail: `没过：${checkFailures(ev.check).join('；')}`, state: 'halt' },
              ],
              note: '没出好——数据校验没过，先不出报告初稿。',
              result: { period, archiveHref: appHref('archive', period), fixable: 'flex' },
            }))
          }
        } else if (ev.event === 'stopped') {
          upd((t) => ({
            ...t, status: 'stopped',
            steps: t.steps.map((s) => (s.state === 'doing' ? { ...s, state: 'halt' } : s)),
            note: '停了——这次没出稿。',
          }))
        } else if (ev.event === 'error') {
          upd((t) => ({
            ...t, status: 'error',
            steps: t.steps.map((s) => (s.state === 'doing' ? { ...s, state: 'halt' } : s)),
            note: `没出成：${ev.message}`,
          }))
        }
      })
    } catch (e) {
      upd((t) => ({
        ...t, status: 'error',
        steps: t.steps.map((s) => (s.state === 'doing' ? { ...s, state: 'halt' } : s)),
        note: `没出成：${errorNote(e, '出稿')}`,
      }))
    } finally {
      setRunning(null)
    }
    /* 口径 A（票 05）：流完校验通过 → 自动接复刻产线（报告初稿 / 对勘本 / 红件清单） */
    if (doneRef.ev?.check_pass) void startRepro(period, index, doneRef.ev)
  }

  /** 出稿第二段（票 05 口径 A）：接**复刻产线**（既有开跑口）——
      进度从任务瀑布读；跑完给实产三件 + 运行档案 + 覆盖后的回滚出路。 */
  async function startRepro(period: string, index: number,
                            doneEv?: FlexStreamEvent & { event: 'done' }) {
    const upd = traceUpdater(index)
    upd((t) => ({
      ...t, status: 'streaming',
      steps: [...t.steps.filter((s) => s.n !== 6),
              { n: 6, title: '生成报告初稿', detail: '正在排复刻产线…', state: 'doing' }],
    }))
    try {
      const { job_id } = await postJob(period)
      let status = 'running'
      const deadline = Date.now() + 15 * 60 * 1000
      for (;;) {
        await sleep(1600)
        if (Date.now() > deadline) throw new Error('复刻产线跑得太久（超过 15 分钟），先去运行档案看看。')
        const p = await getJobProgress(job_id)
        status = p.status || status
        const latest = latestProgress(p)
        upd((t) => ({ ...t, steps: t.steps.map((s) => s.n === 6
          ? { ...s, detail: latest ? `正在跑：${latest}` : '正在跑…' } : s) }))
        if (isTerminalState(status)) break
      }
      if (status !== 'completed' && status !== 'warned') {
        throw new Error(`复刻产线${taskLabel(status)}。`)
      }
      const arts = trioLinks(await getArtifacts(job_id))
      /* 报告初稿（docx）走平台既有的签发闸：未签发时只能看、不能下载（与生成台同款）。
         签名本就在这次重出后失效（stale）——如实显示，不假称可下载。 */
      const signed = await getPeriods()
        .then((ps) => ps.find((p) => p.period === period)?.signed === true)
        .catch(() => false)
      const points = await getRollbackPoints(period).catch(() => [] as RollbackPoint[])
      upd((t) => ({
        ...t,
        status: 'done',
        steps: t.steps.map((s) => s.n === 6
          ? { ...s, detail: '报告初稿 + 对勘本 + 红件清单', state: 'done' as const } : s),
        note: okNote(doneEv, status === 'warned'),
        result: { period, artifacts: arts, signed, archiveHref: appHref('archive', period),
                  rollback: points.length ? { points } : undefined },
      }))
    } catch (e) {
      upd((t) => ({
        ...t,
        status: 'error',
        steps: t.steps.map((s) => (s.n === 6 ? { ...s, state: 'halt' as const } : s)),
        note: `报告初稿没出成：${errorNote(e, '报告初稿')}`,
        result: { period, archiveHref: appHref('archive', period), fixable: 'repro' },
      }))
    }
  }

  /** 回滚到上一版（票 05）：走既有回滚口（旧稿在 `_superseded/`；回滚本身还能再回滚）。 */
  async function doRollback(index: number, period: string, point: RollbackPoint) {
    const upd = traceUpdater(index)
    try {
      const res = await rollbackPeriod(period, point.id)
      upd((t) => t.result?.rollback ? {
        ...t,
        result: { ...t.result, rollback: { ...t.result.rollback,
          out: `已回滚到上一版（${(res.restored ?? []).length} 个文件）；这次回滚也能再回滚——当前稿已留档。` } },
      } : t)
    } catch (e) {
      upd((t) => t.result?.rollback ? {
        ...t,
        result: { ...t.result, rollback: { ...t.result.rollback,
          out: `没回成——${errorNote(e, '回滚')}` } },
      } : t)
    }
  }

  /** 停止出稿：拿 run 令牌喊停（终态 `stopped` 从原流回来，这里不掐连接）。 */
  async function stopRun() {
    if (!running) return
    const run = runTokenRef.current
    if (!run) return
    try {
      await stopFlexible(running.period, run)
    } catch {
      /* 喊停失败不打扰：流自己会走到终态 */
    }
  }

  if (roleKnown && me && me.role !== 'admin') return null
  if (roleKnown && !me) {
    return (
      <main className="dlg-gate">
        <b>请先登录</b> —— 对话前门只对馆员开放，<a href="/login">去登录</a>后再来；
        若已登录，检查本机服务是否在运行。
      </main>
    )
  }

  const withPeriod = (href: string) =>
    active.slots.period && href !== '/app/shelf/'
      ? buildPeriodUrl(href, active.slots.period)
      : href

  return (
    <div className="dlg-shell">
      <a className="dlg-skip" href="#dlg-thread">跳到对话内容</a>
      <h1 className="dlg-vh">文衡 · 对话前门</h1>

      <aside className="dlg-side">
        <div className="dlg-brand"><strong>文衡</strong><span>云南大学图书馆</span></div>
        <button className="dlg-newchat" type="button" onClick={newChat}>＋ 新对话</button>
        <nav className="dlg-hist" aria-label="对话历史">
          {others.length === 0 ? (
            <p className="dlg-hist-note">这次打开里的对话会列在这里。</p>
          ) : (
            others.map((c) => (
              <a key={c.id} href="#对话" aria-current={c.id === activeId ? 'true' : undefined}
                 onClick={(e) => { e.preventDefault(); setActiveId(c.id) }}>
                {c.title || '新对话'}
              </a>
            ))
          )}
        </nav>
        <div className="dlg-me">
          <span className="dlg-av" aria-hidden="true">{me?.name?.slice(0, 1) ?? '·'}</span>
          {me ? `${me.name} · 管理员` : '角色确认中…'}
        </div>
      </aside>

      <section className="dlg-main">
        <header className="dlg-topbar">
          <span className="dlg-ttl">{active.title || '新对话'}</span>
          <div className="dlg-right">
            <details className="dlg-wk">
              <summary>工作台 ▾</summary>
              <div className="dlg-wk-menu">
                {WORKBENCH.map(([label, href]) => (
                  <a key={href} href={withPeriod(href)}>{label}</a>
                ))}
              </div>
            </details>
            <span className="dlg-skin" role="group" aria-label="配色">
              <button type="button" aria-pressed={palette === 'ynu'}
                      onClick={() => setPalette('ynu')}>云大绿</button>
              <button type="button" aria-pressed={palette === 'zhu'}
                      onClick={() => setPalette('zhu')}>朱砂</button>
            </span>
            {qa && (
              <button type="button" className="dlg-qa" aria-pressed={qa.enabled} disabled={qaBusy}
                      title="管理员可关闭「查数据」；关闭后对话里照旧说「已关闭」，报告不受影响"
                      onClick={() => void toggleQa(!qa.enabled)}>
                查数据 · {qa.enabled ? '已开启' : '已关闭'}
              </button>
            )}
            <SlotChip label="期次" value={active.slots.period}
                      onClear={() => updateActive((c) => ({ ...c, slots: clearSlot(c.slots, 'period') }))} />
            <SlotChip label="意图" value={active.slots.intent}
                      onClear={() => updateActive((c) => ({ ...c, slots: clearSlot(c.slots, 'intent') }))} />
            {hasSlots(active.slots) && (
              <span className="dlg-vh" role="status">
                {`当前槽位：期次 ${active.slots.period || '未设'}，意图 ${active.slots.intent || '未设'}`}
              </span>
            )}
          </div>
        </header>

        <div className="dlg-thread" ref={threadRef} id="dlg-thread" aria-live="polite">
          <div className="dlg-thread-in">
            {active.turns.length === 0 && (
              <div className="dlg-turn wh">
                <div className="dlg-who">文</div>
                <div className="dlg-bub">
                  <div className="dlg-nm">文衡</div>
                  你好。说一句话就开始，比如「帮我做 9 月的报告」——期次我来认（按数据截止月），
                  认出来会先说给你看。
                </div>
              </div>
            )}
            {active.turns.map((t, i) => t.who === 'sys' ? (
              <p key={i} className="dlg-sys">{t.text}</p>
            ) : (
              <div key={i} className={`dlg-turn ${t.who}`}>
                <div className="dlg-who">{t.who === 'me' ? '你' : '文'}</div>
                <div className="dlg-bub">
                  {t.who === 'wh' && <div className="dlg-nm">文衡</div>}
                  {t.text}
                  {t.answer && <AnswerBlock answer={t.answer} />}
                  {t.notice && <p className="dlg-notice">{t.notice}</p>}
                  {t.trace && (
                    <div className="dlg-trk" aria-live="polite">
                      <div className="dlg-trk-h">
                        本期规划与数据校验
                        <span>{t.trace.status === 'streaming' ? '出稿中'
                              : t.trace.status === 'done' ? '完成'
                              : t.trace.status === 'stopped' ? '已停' : '出错'}</span>
                      </div>
                      {t.trace.steps.map((s) => (
                        <div key={s.n} className={`dlg-trk-row ${s.state}`}>
                          <span className="dlg-dot" aria-hidden="true">
                            {s.state === 'done' ? '✓' : s.state === 'halt' ? '·' : s.n}
                          </span>
                          <div>
                            <div className="dlg-trk-t">{s.title}</div>
                            <div className="dlg-trk-d">
                              {s.detail}
                              {s.state === 'doing' && <span className="dlg-caret" aria-hidden="true" />}
                            </div>
                          </div>
                        </div>
                      ))}
                      {t.trace.status === 'streaming' && (
                        <p className="dlg-stream">
                          <span className="dlg-dots" aria-hidden="true"><i /><i /><i /></span>
                          正在出稿…（要停就点输入框那个键）
                        </p>
                      )}
                      {t.trace.note && <p className="dlg-trk-note">{t.trace.note}</p>}
                      {t.trace.result && (
                        <ResultBlock result={t.trace.result} index={i}
                                     disabled={busy || !!running}
                                     onFix={(r, idx) => {
                                       if (r.fixable === 'flex') void startRun(r.period, idx, 'single_trend')
                                       else void startRepro(r.period, idx)
                                     }}
                                     onRollback={(idx, period, point) => void doRollback(idx, period, point)} />
                      )}
                    </div>
                  )}
                  {t.who === 'wh' && !!t.actions?.length && !t.dismissed && (
                    <div className="dlg-acts">
                      {t.actions.map((a, j) => a.kind === 'goto' ? (
                        <a key={j} className="dlg-act primary"
                           href={buildPeriodUrl(`/app/?view=${a.view ?? 'acquire'}`,
                                                a.period || active.slots.period || '')}>{a.text}</a>
                      ) : a.kind === 'run' ? (
                        /* 覆盖确认（票 05）：唯一会问一次的地方——行内二次确认，不做弹窗 */
                        <ConfirmButton key={j} className="dlg-act primary" confirmText="确认覆盖？"
                                       disabled={busy || !!running}
                                       onConfirm={() => void startRun(
                                         a.period || active.slots.period || '', i,
                                         t.run?.intent || 'single_trend')}>
                          {a.text}
                        </ConfirmButton>
                      ) : (
                        <button key={j} type="button" disabled={busy || !!running}
                                className={`dlg-act ${a.kind === 'dismiss' ? 'ghost' : 'primary'}`}
                                onClick={() => {
                                  if (a.kind === 'send') void sendText(a.text)
                                  else dismissActions(i)
                                }}>
                          {a.text}
                        </button>
                      ))}
                    </div>
                  )}
                </div>
              </div>
            ))}
            {busy && (
              <div className="dlg-turn wh">
                <div className="dlg-who">文</div>
                <div className="dlg-bub dlg-wait">正在理解这句话…</div>
              </div>
            )}
          </div>
        </div>

        <div className="dlg-composer">
          <form className="dlg-composer-in" onSubmit={(e) => { e.preventDefault(); void sendText(input) }}>
            <div className="dlg-box">
              <textarea rows={1} aria-label="对文衡说话" value={input}
                        placeholder={running ? '正在出稿…（点右边的 ■ 可以停）'
                                             : '说一句话，比如「帮我做 9 月的报告」…'}
                        disabled={!!running}
                        onChange={(e) => setInput(e.target.value)}
                        onKeyDown={(e) => {
                          if (e.key === 'Enter' && !e.shiftKey && !e.nativeEvent.isComposing) {
                            e.preventDefault()
                            void sendText(input)
                          }
                        }} />
              {running ? (
                <button className="dlg-send" type="button" aria-label="停止出稿"
                        onClick={() => void stopRun()}>■</button>
              ) : (
                <button className="dlg-send" type="submit" aria-label="发送"
                        disabled={busy || !input.trim()}>↑</button>
              )}
            </div>
          </form>
        </div>
      </section>
    </div>
  )
}

/** 出好了的出路（票 05）：三件套下载 / 去运行档案 / 自动修复 / 回滚到上一版。 */
function ResultBlock({ result, index, disabled, onFix, onRollback }: {
  result: TraceResult
  index: number
  disabled: boolean
  onFix: (result: TraceResult, index: number) => void
  onRollback: (index: number, period: string, point: RollbackPoint) => void
}) {
  const point = result.rollback?.points?.[0]
  return (
    <div className="dlg-res">
      {!!result.artifacts?.length && (
        <div className="dlg-acts">
          {result.artifacts.map((a) => (
            a.key === 'report' && !result.signed
              ? <span key={a.key} className="dlg-act" aria-disabled="true"
                      title="未签发，管理员暂不能下载；去生成台复核并签单后即可下载">
                  {a.label} · 未签发，暂不能下载
                </span>
              : <a key={a.key} className="dlg-act" href={a.href} title={a.from}>{a.label}</a>
          ))}
          <a className="dlg-act ghost" href={result.archiveHref}>去运行档案看全程 ▸</a>
        </div>
      )}
      {result.fixable && (
        <div className="dlg-acts">
          <button type="button" className="dlg-act primary" disabled={disabled}
                  onClick={() => onFix(result, index)}>自动修复</button>
          <a className="dlg-act ghost" href={result.archiveHref}>需人工接手 ▸</a>
        </div>
      )}
      {point && !result.rollback?.out && (
        <div className="dlg-acts">
          <button type="button" className="dlg-act" disabled={disabled}
                  onClick={() => onRollback(index, result.period, point)}>回滚到上一版 ▸</button>
        </div>
      )}
      {result.rollback?.out && <p className="dlg-trk-note">{result.rollback.out}</p>}
    </div>
  )
}

function SlotChip({ label, value, onClear }: {
  label: string
  value: string
  onClear: () => void
}) {
  if (!value) return null
  return (
    <span className="dlg-slot">
      <span className="dlg-slot-k">{label}</span>
      <span className="dlg-slot-v">{value}</span>
      <button className="dlg-slot-x" type="button" aria-label={`清掉${label}`}
              onClick={onClear}>✕</button>
    </span>
  )
}

/** 查数据的回答（票 07）：正文带角标（点数字看来源）＋模式与盾小字＋规则版对照。 */
function AnswerBlock({ answer }: { answer: DialogAnswer }) {
  const answered = answer.mode === 'model' || answer.mode === 'rule'
  return (
    <div className="dlg-ans">
      {!!answer.text && <NumberedText text={answer.text} sources={answer.sources} />}
      {!!answer.rule_text && answer.rule_text !== answer.text && (
        <details className="dlg-rule">
          <summary>看规则版</summary>
          <NumberedText text={answer.rule_text} sources={answer.sources} />
        </details>
      )}
      {answered && (
        <div className="an-footer">
          <span className={`pill ${answer.mode === 'model' ? 'signed' : 'stale'}`}>
            {answer.mode === 'model' ? '大模型作答' : '规则版作答'}
          </span>
          {answer.shield.checked > 0 && (
            <span className="pill ok">盾 · {answer.shield.passed} 个数字已登记</span>
          )}
          <span className="hint">点数字看来源</span>
        </div>
      )}
      {!!answer.notice && <p className="dlg-notice">{answer.notice}</p>}
    </div>
  )
}
