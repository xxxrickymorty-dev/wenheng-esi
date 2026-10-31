/* 对话前门（票 01–05、07：期次识别 → 盘点 → 核对门 → 出稿两段式 → 两意图路由）。
   版面照 `mockups/对话前门.html`（五稿）：左＝对话历史 / 中＝对话流 / 底＝输入框。
   口径照 ADR-0006：对话只做指挥——数字全部来自后端；
   解析与路由走 `/api/dialog/turn`（后端 src/ai 能力口，规则版离线可跑）；
   **查数据**（kind="query"）的回答由服务器按意图调 qa 能力，本页只渲染（带角标可点来源）；
   **写报告＝两段式（票 05 口径 A）**：先走**既有**灵活报告流式口 `/api/periods/{p}/flexible/stream`
   （轨迹逐段出 + 停止键），流完**自动接复刻产线**（既有 `POST /api/jobs`）——
   出好了＝报告初稿 / 对勘本 / 红件清单；覆盖确认＝行内二次确认（复用 `ConfirmButton`），
   回滚走既有 `rollback-points` / `rollback`（旧稿在 `_superseded/`）。 */

import { useEffect, useMemo, useRef, useState, type PointerEvent as ReactPointerEvent } from 'react'
import type { EChartsOption } from 'echarts'
import { req, getArtifacts, getJobProgress, getMe, getPeriods,
         getRollbackPoints, postJob, rollbackPeriod,
         type Me, type RollbackPoint } from '../api'
import { getDialogHome, postDialogTurnStream,
         type DialogAction, type DialogAnswer, type DialogHome, type DialogQa, type DialogReceipt, type DialogReply,
         type DialogRun } from '../api-dialog'
import { ChartFigure } from '../charts/ChartFigure'
import { runFlexibleStream, stopFlexible, type FlexCheck, type FlexStreamEvent } from '../api-flexible'
import { ConfirmButton } from '../ConfirmButton'
import { clearSlot, conversationTitle, emptySlots, hasSlots,
         sessionIdFromSearch, withSessionId, type DialogSlots } from '../lib/dialog'
import { buildPeriodUrl } from '../lib/period'
import { trioLinks, type TrioLink } from '../lib/repro'
import { latestProgress } from '../lib/runMachine'
import { appHref, errorNote, isTerminalState, taskLabel } from '../lib/status'
import { markLabel, taskView } from '../lib/taskview'
import { NumberedText } from '../NumberedText'
import { getModels, setActiveModel, type ModelsPayload } from '../api-models'
import { ModelMenu, ModelSettings } from './ModelPanel'
import { ToolTrace, type ToolCall } from './ToolTrace'

/** 出稿轨迹（票 04）：逐段出（挑学科 / 配图 / 下载数据 / 数据校验 / 收尾 / 复刻）。
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
              /** 追问卡选了第几颗（已选态）；undefined＝还没选 */
              picked?: number; run?: DialogRun; trace?: Trace; answer?: DialogAnswer
              /** 问数图块（2026-10-31）：kind="qa" 轮后端直调引擎出的图；没图就缺省 */
              qa?: DialogQa
              /** 整轮耗时与时间（2026-10-31）：每句话都报，照 dsh 的消息元信息 */
              elapsed?: number
              ts?: string
              /** 工具回执（AI 层双面回执）；本轮没有就缺省/为空，界面不出回执条 */
              receipts?: DialogReceipt[]
              /** 这一轮的工具调用轨迹（2026-10-29）：模型查了哪些台账、查到没有 */
              tools?: ToolCall[] }
type Conversation = { id: number; title: string; turns: Turn[]; slots: DialogSlots
                      /** 服务端会话 id（票 11）：这页打开里的每段对话各归一个服务端会话 */
                      sessionId?: string }

/** 空态首页（2026-10-12，P0-③）：模式 chips 与示例胶囊——点击＝把示例句填进输入框。 */
const LANDING_MODES: { label: string; example: string }[] = [
  { label: '出报告', example: '帮我做 9 月的报告' },
  { label: '查数据', example: '查一下化学的接近度' },
  { label: '看进展', example: '202609 到哪一步了' },
]
const LANDING_EXAMPLES = [
  '帮我做 9 月的报告', '查一下化学的接近度', '云南大学国际排名走势',
  '物理学的 1% 阈值是多少', '数学什么时候进入前 1%', '202609 到哪一步了',
]

const sleep = (ms: number) => new Promise<void>((resolve) => window.setTimeout(resolve, ms))

/** 侧栏宽度（2026-10-29 rick：要能拖着调）。范围与默认值都写死一处，别处只读。 */
const SIDE_KEY = 'wenheng-dlg-side'
const SIDE_MIN = 208
const SIDE_MAX = 420
const SIDE_DEF = 264
function initialSideWidth(): number {
  try {
    const v = Number(localStorage.getItem(SIDE_KEY))
    if (Number.isFinite(v) && v >= SIDE_MIN && v <= SIDE_MAX) return v
  } catch { /* 浏览器不许存就用默认宽 */ }
  return SIDE_DEF
}

/** 相对时间（2026-10-29）：列表右侧只写「3天」这种量级——精确到秒没人看。 */
function relTime(iso: string): string {
  const t = new Date(String(iso || '').replace(' ', 'T')).getTime()
  if (!Number.isFinite(t) || t <= 0) return ''
  const sec = Math.max(0, Math.floor((Date.now() - t) / 1000))
  if (sec < 60) return '刚刚'
  if (sec < 3600) return `${Math.floor(sec / 60)}分钟`
  if (sec < 86400) return `${Math.floor(sec / 3600)}小时`
  if (sec < 86400 * 30) return `${Math.floor(sec / 86400)}天`
  return `${Math.floor(sec / 86400 / 30)}个月`
}

/** 自检明细（票 05）→ 没过的那几条（馆员话术；全过给空表）。 */
function checkFailures(c?: FlexCheck): string[] {
  if (!c) return ['自检明细没拿到（去运行档案看）']
  const out: string[] = []
  if (!c.trace_ok) out.push(`有 ${c.trace_bad} 处数字没指回台账`)
  if (!c.has_charts) out.push('一张图都没出')
  if (!c.judgement_marked) out.push('还有判断句没带标记')
  if (c.judgement_leaks.length) out.push(`漏标 ${c.judgement_leaks.length} 处`)
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

/** 服务端会话回读（票 11，契约 #36）：刷新/换设备带 `?s=<id>` 即恢复。 */
type RestoredSession = {
  id: string
  slots: DialogSlots
  turns: { who: 'me' | 'wh'; text: string; ts: string }[]
}

async function getDialogSession(id: string): Promise<RestoredSession> {
  return req<RestoredSession>(`/api/dialog/session/${encodeURIComponent(id)}`)
}

/** 保存的对话（2026-10-24 rick：要能看到/回到之前的对话）——服务端会话清单。 */
type SavedSession = { id: string; title: string; n_turns: number; updated: string }

async function getDialogSessions(): Promise<SavedSession[]> {
  const d = await req<{ sessions: SavedSession[] }>('/api/dialog/sessions')
  return d.sessions ?? []
}

async function dropDialogSession(id: string): Promise<void> {
  await req<unknown>(`/api/dialog/session/${encodeURIComponent(id)}/drop`, { method: 'POST' })
}

/** 一轮对话（票 11 增补 session 收发；本页是唯一调用方，就地接线）。
    `session_id` 是票 11 新增字段（api-dialog.ts 的类型面外挂在这一层）。 */
type TurnReply = DialogReply & { session_id?: string }

async function postTurn(text: string, slots: DialogSlots,
                        history: { who: string; text: string }[],
                        session?: string): Promise<TurnReply> {
  return req<TurnReply>('/api/dialog/turn', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ text, slots, history, session }),
  })
}

/** 会话 id 回写 URL（history.replaceState；`ask` 等其他参数原样保留）。 */
function writeSessionUrl(id: string) {
  const rest = withSessionId(window.location.search, id)
  window.history.replaceState(null, '', window.location.pathname + (rest ? `?${rest}` : ''))
}

export default function DialogPage() {
  /* 模型清单（2026-10-29）：当前用哪个模型由服务端保存，这里只读写清单 */
  const [models, setModels] = useState<ModelsPayload | null>(null)
  const [settingsOpen, setSettingsOpen] = useState(false)
  /* 本轮正在发生的工具调用（流式时实时追加；答完随回合落进 turns[i].tools） */
  const [liveTools, setLiveTools] = useState<ToolCall[]>([])
  const [modelMsg, setModelMsg] = useState('')
  /* 侧栏宽度／用户菜单／搜索（2026-10-29 照 DeepSeek harness 的侧栏） */
  const [sideW, setSideW] = useState(initialSideWidth)
  const [meMenu, setMeMenu] = useState(false)
  const [q, setQ] = useState('')
  const [qOpen, setQOpen] = useState(false)
  const [me, setMe] = useState<Me | null>(null)
  const [roleKnown, setRoleKnown] = useState(false)
  const [convs, setConvs] = useState<Conversation[]>(() => [freshConversation(1)])
  const [activeId, setActiveId] = useState(1)
  const [input, setInput] = useState('')
  const [busy, setBusy] = useState(false)
  /* 阶段进度流（票 12）：等待时显示「正在做什么」（后端真实节点给，不演） */
  const [stage, setStage] = useState('')
  /* 流式正文（2026-10-30）：answer 分块回流时的累积文本——有内容就盖掉 stage 占位，
     让等待气泡渐进显示答案，不再卡在「正在写答案…」；done 到达后由真实回合接管。 */
  const [streamText, setStreamText] = useState('')
  /* 空态第一屏「本期任务」（票 06）：从既有产物判的三步状态；拿不到就退回普通问候。 */
  const [home, setHome] = useState<DialogHome | null>(null)
  /* 正在出稿的那条回复（停止键要用：期次 + 消息下标 + run 令牌） */
  const [running, setRunning] = useState<{ period: string; index: number } | null>(null)
  const runTokenRef = useRef<string>('')
  const [tick, setTick] = useState(0)
  const nextIdRef = useRef(2)
  const threadRef = useRef<HTMLDivElement>(null)
  /* 保存的对话（服务端清单）：左栏「保存的对话」组；这次打开的本地对话仍归「这次打开」组 */
  const [saved, setSaved] = useState<SavedSession[]>([])
  const savedSeqRef = useRef(0)

  function refreshSaved() {
    const seq = ++savedSeqRef.current
    getDialogSessions()
      .then((list) => { if (seq === savedSeqRef.current) setSaved(list) })
      .catch(() => { /* 清单拿不到不挡对话；下次动作再刷 */ })
  }

  const active = convs.find((c) => c.id === activeId) ?? convs[0]
  const others = convs.filter((c) => c.turns.length > 0)
  /* 空态第一屏＝本期任务视图（票 06）；拿不到状态就退回普通问候 */
  const tv = active.turns.length === 0 ? taskView(home) : null
  /* 2026-10-11：管理员专属位（AI 开关、回滚、自动修复）；2026-10-12：出报告/审批对
     操作员也开放——「开跑/覆盖重出」用 canRun（两种角色都行），真门仍在后端。 */
  const canEdit = me?.capabilities?.actions?.edit ?? me?.role === 'admin'
  const canRun = me?.capabilities?.actions?.run ?? !!me

  useEffect(() => {
    let alive = true
    void (async () => {
      const m = await getMe()
      if (!alive) return
      setMe(m)
      setRoleKnown(true)
      refreshSaved()
      getModels().then(setModels).catch(() => setModels(null))
      /* 两种角色都进前门（2026-10-11）：操作员可查数据；出稿等写动作在下面按角色裁剪。 */
    })()
    return () => { alive = false }
  }, [])

  /* 会话恢复（票 11）：URL `?s=<id>` → 拉服务端会话恢复渲染（恢复回合无 actions/trace 就空着）。
     只在对话还空着时落位；拿不到（不存在/不属于我）就清掉参数、照常新开。 */
  const restoredRef = useRef(false)
  const activeIdRef = useRef(activeId)
  useEffect(() => { activeIdRef.current = activeId }, [activeId])
  useEffect(() => {
    if (!roleKnown || !me || restoredRef.current) return
    restoredRef.current = true
    const sid = sessionIdFromSearch(window.location.search)
    if (!sid) return
    void (async () => {
      try {
        const data = await getDialogSession(sid)
        setConvs((list) => list.map((c) => (c.id === 1 && c.turns.length === 0 ? {
          ...c,
          title: c.title || conversationTitle(data.turns.find((t) => t.who === 'me')?.text || ''),
          slots: data.slots,
          sessionId: data.id,
          turns: data.turns.map((t) => ({ who: t.who, text: t.text })),
        } : c)))
        if (activeIdRef.current === 1) writeSessionUrl(data.id)
        refreshSaved()
      } catch {
        writeSessionUrl('')          // 拿不到就当没带：清参数，不挡新对话
      }
    })()
    // eslint-disable-next-line react-hooks/exhaustive-deps -- 只在身份确认后跑一次
  }, [roleKnown, me])

  /* 陈列馆「问文衡」入口带问题来（`/app/dialog/?ask=…`，2026-10-12）：
     身份确认后自动发送一次，随即清掉参数（刷新不重发）。 */
  const askedRef = useRef(false)
  useEffect(() => {
    if (!roleKnown || !me || askedRef.current) return
    askedRef.current = true
    const params = new URLSearchParams(window.location.search)
    const ask = (params.get('ask') || '').trim()
    if (!ask) return
    params.delete('ask')
    const rest = params.toString()
    window.history.replaceState(null, '', window.location.pathname + (rest ? `?${rest}` : ''))
    void sendText(ask)
    // eslint-disable-next-line react-hooks/exhaustive-deps -- 只在身份确认后跑一次
  }, [roleKnown, me])

  /* 本期任务（票 06）：每次切到（或新开）一个空对话时重取——出稿后状态就变了。 */
  useEffect(() => {
    let alive = true
    getDialogHome()
      .then((h) => { if (alive) setHome(h) })
      .catch(() => { if (alive) setHome(null) })
    return () => { alive = false }
  }, [activeId])

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
    writeSessionUrl('')              // 票 11：「新对话」清掉 URL 里的 s（本地状态随新对话走）
  }

  /* 打开一段保存的对话：拉全量回合落进本地列表并切过去（URL 跟过去，刷新仍可恢复） */
  async function openSaved(s: SavedSession) {
    try {
      const data = await getDialogSession(s.id)
      const conv: Conversation = {
        id: nextIdRef.current++,
        title: s.title || '保存的对话',
        slots: data.slots,
        sessionId: data.id,
        turns: data.turns.map((t) => ({ who: t.who, text: t.text })),
      }
      setConvs((list) => [conv, ...list])
      setActiveId(conv.id)
      writeSessionUrl(data.id)
    } catch {
      /* 拿不到（刚被删等）就不切；清单下次刷新自会更新 */
    }
  }

  async function dropSaved(s: SavedSession) {
    try { await dropDialogSession(s.id) } catch { /* 删失败不动本地 */ }
    refreshSaved()
  }

  async function sendText(raw: string, slotsOverride?: DialogSlots) {
    const text = raw.trim()
    if (!text || busy || running) return
    setInput('')
    setBusy(true)
    setStage('')
    setStreamText('')
    setLiveTools([])
    const convId = active.id
    const slots = slotsOverride ?? active.slots
    const replyIndex = active.turns.length + 1          // 先发用户话，回复接在它后面
    updateActive((c) => ({
      ...c,
      title: c.title || conversationTitle(text),
      turns: [...c.turns, { who: 'me', text }],
    }))
    try {
      /* 对话上文（2026-10-12）：追问（「这是几月的」「那物理学呢」）要靠它解指代——
         只带上最近 6 轮、每轮截 200 字；服务端还会再截一次。
         带会话时服务端改从会话库读（票 11），body 历史只是没有会话时的兜底。 */
      const history = active.turns
        .filter((t) => t.who !== 'sys')
        .slice(-6)
        .map((t) => ({ who: t.who, text: t.text.slice(0, 200) }))
      let r: DialogReply
      let calls: ToolCall[] = []
      try {
        /* 阶段进度流（票 12）：等待时看得到「正在做什么」；正文分块回流（2026-10-29），
           工具调用逐条实时报（同日）：等待气泡里能看到它查了哪些台账。 */
        r = await postDialogTurnStream(text, slots, history, active.sessionId,
                                       (t) => setStage(t),
                                       (t) => setStreamText((s) => s + t),
                                       (c) => {
                                         calls = [...calls, c]
                                         setLiveTools(calls)
                                       })
      } catch {
        /* 进度流不可用（网络/部署差异）→ 回退同步口：界面照常，只是没有阶段提示 */
        r = await postTurn(text, slots, history, active.sessionId)
      }
      updateActive((c) => ({
        ...c,
        sessionId: r.session_id || c.sessionId,
        slots: r.slots,
        turns: [...c.turns, { who: 'wh', text: r.text, notice: r.notice,
                              actions: r.actions, run: r.run ?? undefined,
                              answer: r.answer ?? undefined,
                              qa: r.qa ?? undefined,
                              elapsed: r.elapsed_ms ?? undefined,
                              ts: r.ts ?? undefined,
                              receipts: r.receipts,
                              tools: calls.length ? calls : undefined }],
      }))
      /* 票 11：把本回合的会话 id 回写 URL——刷新/换设备带它即恢复；
         还在这一段对话上才写（中途切走别把 URL 指到别处）。 */
      if (r.session_id && activeIdRef.current === convId) writeSessionUrl(r.session_id)
      refreshSaved()
      /* 出稿意图（票 03/05）：auto=true 直接开跑，且此时**没有产物**＝首出期次
         （两段式要复刻先行——灵活报告只消费流水线产物）；auto=false 产物已在，
         等人在按钮上点了才跑（行内二次确认）。
         2026-10-12：操作员也有出报告权限（后端 POST /api/jobs 已对两角色开放）。 */
      if (canRun && r.run?.auto && r.run.period) void startRun(r.run.period, replyIndex, r.run.intent, true)
    } catch (e) {
      updateActive((c) => ({
        ...c,
        turns: [...c.turns, { who: 'wh', text: `这轮没成功。${errorNote(e, '这轮对话')}` }],
      }))
    } finally {
      setBusy(false)
      setStage('')
      setStreamText('')
      setLiveTools([])
    }
  }

  /** 追问卡「已选」态（票 04）：记下选了哪一颗，留在时间线——回看时知道走的是哪条路。
      「先等等」仍只是界面动作：不发请求、不落账。 */
  function pickAction(index: number, picked: number) {
    updateActive((c) => ({
      ...c,
      turns: c.turns.map((t, i) => (i === index ? { ...t, picked } : t)),
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

  /** 灵活报告段（票 04）：既有流式口 + 轨迹 + 停止键。
      `base`＝本段从第几号步骤起排（复刻先行时是 2，否则 1）；`afterRepro`＝复刻已先出好。
      返回 done 事件；null＝没走到收尾（停/错/异常，轨迹里已明说）。 */
  async function runFlexStage(period: string, index: number, intent: string,
                              base: number, afterRepro: boolean) {
    runTokenRef.current = ''
    setRunning({ period, index })
    const upd = traceUpdater(index)
    const step = (k: number, title: string, detail: string,
                  state: TraceStep['state'] = 'doing'): TraceStep =>
      ({ n: base + k, title, detail, state })
    const keepLead = (t: Trace): TraceStep[] => t.steps.filter((s) => s.n < base)
    updateActive((c) => ({
      ...c,
      turns: c.turns.map((t, i) => (i === index
        ? { ...t, trace: { status: 'streaming',
                           steps: [...(t.trace ? keepLead(t.trace) : []),
                                   step(0, '挑学科', '正在规划…')] } }
        : t)),
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
            ...keepLead(t),
            step(0, '挑学科', pick, 'done'),
            step(1, '配图',
              charts.length ? `${charts.length} 张：${charts.map((c) => c.why || c.kind).join('；')}`
                            : '按规划出图',
              'done'),
            step(2, '下载数据', '逐节下载数据与写稿…'),
          ] }))
        } else if (ev.event === 'section') {
          sections += 1
          upd((t) => ({ ...t, steps: t.steps.map((s) =>
            s.n === base + 2 ? { ...s, detail: `逐节下载数据与写稿：已完成 ${sections} 节…` } : s) }))
        } else if (ev.event === 'done') {
          doneRef.ev = ev
          if (ev.check_pass) {
            upd((t) => ({
              ...t,
              steps: [
                ...t.steps.map((s) => ({ ...s, state: 'done' as const })),
                step(3, '数据校验', `一次通过（${checkSummary(ev, sections)}）`, 'done'),
                step(4, '收尾', `分析稿已出（用时 ${ev.elapsed} 秒）`, 'done'),
              ],
              note: afterRepro ? '分析稿也出好了——' : '数据校验一次通过——接着生成报告初稿（复刻产线）…',
            }))
          } else {
            upd((t) => ({
              ...t,
              status: 'error',
              steps: [
                ...t.steps.map((s) => ({ ...s, state: 'halt' as const })),
                step(3, '数据校验', `没过：${checkFailures(ev.check).join('；')}`, 'halt'),
              ],
              /* 复刻已先出好时不设「不带着问题出稿」的拦截——三件套已实产，
                 由收尾如实带出「分析稿没过校验」（orchestrator 的 finalize 覆写 note）。 */
              note: afterRepro ? 'AI 分析稿没过校验——三件套已出好（见下）。'
                               : '没出好——数据校验没过，先不出报告初稿。',
              ...(afterRepro ? {} : { result: { period, archiveHref: appHref('archive', period),
                                                fixable: 'flex' as const } }),
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
    return doneRef.ev
  }

  /** 复刻产线段（票 05 口径 A）：起既有开跑口 → 轮询到终态（进度写进第 `base` 号步骤）。
      成功返回 {jobId,status}；失败把轨迹停在出错那步并返回 null。 */
  async function runReproStage(period: string, index: number, base: number) {
    const upd = traceUpdater(index)
    const stepAt = (detail: string, state: TraceStep['state'] = 'doing'): TraceStep =>
      ({ n: base, title: '生成报告初稿', detail, state })
    updateActive((c) => ({
      ...c,
      turns: c.turns.map((t, i) => (i === index
        ? { ...t, trace: { status: 'streaming',
                           steps: [...(t.trace ? t.trace.steps.filter((s) => s.n !== base) : []),
                                   stepAt('正在排复刻产线…')] } }
        : t)),
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
        upd((t) => ({ ...t, steps: t.steps.map((s) => s.n === base
          ? { ...s, detail: latest ? `正在跑：${latest}` : '正在跑…' } : s) }))
        if (isTerminalState(status)) break
      }
      if (status !== 'completed' && status !== 'warned') {
        throw new Error(`复刻产线${taskLabel(status)}。`)
      }
      upd((t) => ({ ...t, steps: t.steps.map((s) => s.n === base
        ? { ...s, detail: '报告初稿 + 对勘本 + 红件清单', state: 'done' as const } : s) }))
      return { jobId: job_id, status }
    } catch (e) {
      upd((t) => ({
        ...t,
        status: 'error',
        steps: t.steps.map((s) => (s.n === base ? { ...s, state: 'halt' as const } : s)),
        note: `报告初稿没出成：${errorNote(e, '报告初稿')}`,
        result: { period, archiveHref: appHref('archive', period), fixable: 'repro' },
      }))
      return null
    }
  }

  /** 出好了的收尾：实产三件 + 运行档案 + 回滚出路（note 由调用方按两段结果给）。 */
  async function finalizeDone(period: string, index: number,
                              repro: { jobId: string; status: string }, note: string) {
    const upd = traceUpdater(index)
    const arts = trioLinks(await getArtifacts(repro.jobId))
    /* 报告初稿（docx）走平台既有的签发闸：未签发时只能看、不能下载（与生成台同款）。
       签名本就随这次重出失效（stale）——如实显示，不假称可下载。 */
    const signed = await getPeriods()
      .then((ps) => ps.find((p) => p.period === period)?.signed === true)
      .catch(() => false)
    const points = await getRollbackPoints(period).catch(() => [] as RollbackPoint[])
    upd((t) => ({
      ...t,
      status: 'done',
      note,
      result: { period, artifacts: arts, signed, archiveHref: appHref('archive', period),
                rollback: points.length ? { points } : undefined },
    }))
  }

  /** 出稿（票 04/05，口径 A 两段式：灵活流 + 复刻三件套）。
      **已有产物** → 灵活流先行，流完校验通过自动接复刻（票 04 的既定画面）；
      **首出期次（无产物）** → 复刻先行（灵活报告只消费流水线产物），再走灵活流。 */
  async function startRun(period: string, index: number, intent: string, fresh = false) {
    if (!period || running) return
    if (fresh) {
      const repro = await runReproStage(period, index, 1)
      if (!repro) return
      const doneEv = await runFlexStage(period, index, intent, 2, true)
      await finalizeDone(period, index, repro,
        doneEv?.check_pass
          ? okNote(doneEv, repro.status === 'warned')
          : doneEv
            ? '报告初稿 / 对勘本 / 红件清单已出好；AI 分析稿没过校验（先不放心用它）。三件套：'
            : '报告初稿 / 对勘本 / 红件清单已出好；AI 分析稿没出成（去运行档案看）。三件套：')
      return
    }
    const doneEv = await runFlexStage(period, index, intent, 1, false)
    if (!doneEv?.check_pass) return          // 没过/停/错：轨迹里已明说，不出复刻
    const repro = await runReproStage(period, index, 6)
    if (repro) await finalizeDone(period, index, repro, okNote(doneEv, repro.status === 'warned'))
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

  /** 换当前模型（2026-10-29）：写服务端，下一句话即生效；失败只说一句，不挡对话。 */
  async function pickModel(id: string) {
    try {
      setModels(await setActiveModel(id))
    } catch (e) {
      setModelMsg(errorNote(e, '换模型'))
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

  /* 用户菜单：点外面或按 Esc 就收（2026-10-29，DeepSeek 同款手感） */
  useEffect(() => {
    if (!meMenu) return
    const onDoc = (e: MouseEvent) => {
      if (!(e.target as HTMLElement).closest('.dlg-me-wrap')) setMeMenu(false)
    }
    const onEsc = (e: KeyboardEvent) => { if (e.key === 'Escape') setMeMenu(false) }
    document.addEventListener('click', onDoc)
    document.addEventListener('keydown', onEsc)
    return () => {
      document.removeEventListener('click', onDoc)
      document.removeEventListener('keydown', onEsc)
    }
  }, [meMenu])

  /** Ctrl+, 开模型设置（与用户菜单里那行 kbd 一致；只有管理员能开）。 */
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if ((e.ctrlKey || e.metaKey) && e.key === ',') {
        e.preventDefault()
        if (me?.role === 'admin') setSettingsOpen(true)
      }
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [me])

  /** 拖侧栏右缘调宽（2026-10-29）：pointer 事件整套走 window，拖出侧栏也不断。 */
  function startResize(e: ReactPointerEvent<HTMLDivElement>) {
    e.preventDefault()
    const startX = e.clientX
    const startW = sideW
    const move = (ev: PointerEvent) => {
      setSideW(Math.min(SIDE_MAX, Math.max(SIDE_MIN, startW + ev.clientX - startX)))
    }
    const up = () => {
      window.removeEventListener('pointermove', move)
      window.removeEventListener('pointerup', up)
      document.body.classList.remove('dlg-resizing')
      setSideW((w) => {
        try { localStorage.setItem(SIDE_KEY, String(Math.round(w))) } catch { /* 存不了就这页有效 */ }
        return w
      })
    }
    document.body.classList.add('dlg-resizing')
    window.addEventListener('pointermove', move)
    window.addEventListener('pointerup', up)
  }

  /* 侧栏清单：本地这段对话不重复出现（它就是当前这段），搜索只按标题过滤。 */
  const savedList = saved.filter((x) => x.id !== active?.sessionId)
  const savedShown = savedList.filter((x) =>
    !q.trim() || String(x.title || '').toLowerCase().includes(q.trim().toLowerCase()))

  if (roleKnown && !me) {
    return (
      <main className="dlg-gate">
        <b>请先登录</b> —— 对话前门只对馆员开放，<a href="/login">去登录</a>后再来；
        若已登录，检查本机服务是否在运行。
      </main>
    )
  }

  const withPeriod = (href: string) => {
    /* 空态首屏还没进对话，槽位期次为空——用 home.period 兜底，CTA 才不会丢掉期次。 */
    const period = active.slots.period || home?.period || ''
    return period && href !== '/app/shelf/' ? buildPeriodUrl(href, period) : href
  }

  return (
    <div className="dlg-shell">
      <a className="dlg-skip" href="#dlg-thread">跳到对话内容</a>
      <h1 className="dlg-vh">文衡 · 对话前门</h1>

      <aside className="dlg-side" style={{ width: `${sideW}px` }}>
        {/* 顶部两页签（照 DeepSeek harness：应用 / 编辑 → 对话 / 工作台） */}
        <div className="dlg-tabs">
          <a className="dlg-tab on" href="/app/dialog/" aria-current="page">对话</a>
          <a className="dlg-tab" href={withPeriod('/app/')}>工作台</a>
        </div>

        <div className="dlg-brand"><strong>文衡</strong><span>ESI 报告台</span></div>

        <button className="dlg-newchat" type="button" onClick={newChat}>
          <span className="dlg-newchat-i" aria-hidden="true">＋</span>新对话
        </button>

        <nav className="dlg-nav" aria-label="功能入口">
          <a href={withPeriod('/app/?view=tools')}>
            <span className="dlg-nav-i" aria-hidden="true">◈</span>工具
          </a>
          <a href={withPeriod('/app/?view=archive')}>
            <span className="dlg-nav-i" aria-hidden="true">▤</span>运行档案
          </a>
          <a href={withPeriod('/app/?view=review')}>
            <span className="dlg-nav-i" aria-hidden="true">✎</span>审核台
          </a>
          <a href="/app/schools/">
            <span className="dlg-nav-i" aria-hidden="true">▦</span>高校ESI报告
          </a>
        </nav>

        <div className="dlg-ws">
          <div className="dlg-ws-h">
            <span>工作区</span>
            <div className="dlg-ws-tools">
              <button type="button" aria-label="搜索对话" title="搜索对话"
                      onClick={() => setQOpen((v) => !v)}>⌕</button>
              <button type="button" aria-label="新对话" title="新对话" onClick={newChat}>＋</button>
            </div>
          </div>
          {qOpen && (
            <input className="dlg-ws-q" value={q} autoFocus placeholder="搜索对话"
                   onChange={(e) => setQ(e.target.value)}
                   onKeyDown={(e) => { if (e.key === 'Escape') { setQ(''); setQOpen(false) } }} />
          )}
          <nav className="dlg-hist" aria-label="对话历史">
            {savedShown.map((x) => (
              <div key={x.id} className="dlg-hist-row">
                <a href="#对话" title={`${x.title || '保存的对话'} · ${x.updated}`}
                   onClick={(e) => { e.preventDefault(); void openSaved(x) }}>
                  <span className="dlg-hist-t">{x.title || '保存的对话'}</span>
                  <span className="dlg-hist-w">{relTime(x.updated)}</span>
                </a>
                <ConfirmButton className="dlg-drop" confirmText="删除？"
                               title="删除这段对话"
                               onConfirm={() => { void dropSaved(x) }}>✕</ConfirmButton>
              </div>
            ))}
            {others.map((c) => (
              <div key={c.id} className="dlg-hist-row">
                <a href="#对话" aria-current={c.id === activeId ? 'true' : undefined}
                   onClick={(e) => {
                     e.preventDefault()
                     setActiveId(c.id)
                     writeSessionUrl(c.sessionId || '')
                   }}>
                  <span className="dlg-hist-t">{c.title || '新对话'}</span>
                  <span className="dlg-hist-w">当前</span>
                </a>
              </div>
            ))}
          </nav>
        </div>

        <div className="dlg-me-wrap">
          <button type="button" className="dlg-me" aria-haspopup="menu" aria-expanded={meMenu}
                  title={me ? `${me.name} · ${me.role === 'admin' ? '管理员' : '操作员'}` : ''}
                  onClick={() => setMeMenu((v) => !v)}>
            <span className="dlg-av" aria-hidden="true">{(me?.name || '·').slice(0, 1)}</span>
            <span className="dlg-me-n">{me?.name || '…'}</span>
            <span className="dlg-me-i" aria-hidden="true">⋯</span>
          </button>
          {meMenu && (
            <div className="dlg-me-menu" role="menu">
              {me?.role === 'admin' && (
                <button type="button" role="menuitem"
                        onClick={() => { setMeMenu(false); setSettingsOpen(true) }}>
                  <span aria-hidden="true">⚙</span>设置
                  <kbd>Ctrl + ,</kbd>
                </button>
              )}
              <a role="menuitem" href="/logout">
                <span aria-hidden="true">→</span>退出登录
              </a>
            </div>
          )}
        </div>

        <div className="dlg-resize" role="separator" aria-orientation="vertical"
             aria-label="拖动调节侧栏宽度" title="拖动调节宽度"
             onPointerDown={startResize} />
      </aside>

      <section className="dlg-main">
        <header className="dlg-topbar">
          <span className="dlg-ttl">{active.title || '新对话'}</span>
          <div className="dlg-right">
            <SlotChip label="期次" value={active.slots.period}
                      onClear={() => updateActive((c) => ({ ...c, slots: clearSlot(c.slots, 'period') }))} />
            <SlotChip label="意图" value={active.slots.intent}
                      onClear={() => updateActive((c) => ({ ...c, slots: clearSlot(c.slots, 'intent') }))} />
            <SlotChip label="学科" value={active.slots.qdisc}
                      onClear={() => updateActive((c) => ({ ...c, slots: clearSlot(c.slots, 'qdisc') }))} />
            <SlotChip label="指标" value={active.slots.qmetric}
                      onClear={() => updateActive((c) => ({ ...c, slots: clearSlot(c.slots, 'qmetric') }))} />
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
              <section className="dlg-land" aria-label="文衡首页">
                <h1 className="dlg-land-title">文衡，帮你做报告、查数据</h1>
                {/* 2026-10-24 rick 红框删：副题段与「想做什么」提示行（内容太多，一页展示不用下滑） */}
                <div className="dlg-land-modes">
                  {LANDING_MODES.map((mode) => (
                    <button key={mode.label} type="button" className="dlg-land-mode"
                            title={`把示例句填进输入框：${mode.example}`}
                            onClick={() => setInput(mode.example)}>
                      {mode.label}
                    </button>
                  ))}
                </div>
                <div className="dlg-land-pills">
                  {LANDING_EXAMPLES.map((example) => (
                    <button key={example} type="button" className="dlg-land-pill"
                            onClick={() => setInput(example)}>{example}</button>
                  ))}
                </div>
                {tv && (
                  <>
                    <div className="dlg-land-dyn">
                      <b>本期动态 · {home?.period}</b>
                      {tv.rows.map((row, index) => (
                        <span key={row.label}
                              className={`dlg-dyn-step ${row.mark === '✓' ? 'ok'
                                : row.mark === '●' ? 'cur' : ''}`}
                              title={markLabel(row.mark)}>
                          {['①', '②', '③'][index]} {row.label}
                          <i className="dlg-dyn-glyph" aria-hidden="true">{row.mark}</i>
                        </span>
                      ))}
                      {tv.cta && (
                        <a href={withPeriod(tv.cta.kind === 'gen'
                          ? '/app/'
                          : `/app/?view=${tv.cta.view ?? 'workbench'}`)}>
                          {tv.cta.label}
                        </a>
                      )}
                    </div>
                  </>
                )}
              </section>
            )}
            {active.turns.map((t, i) => t.who === 'sys' ? (
              <p key={i} className="dlg-sys">{t.text}</p>
            ) : (
              <div key={i} className={`dlg-turn ${t.who}`}>
                <div className="dlg-who">{t.who === 'me' ? '你' : '文'}</div>
                <div className="dlg-bub">
                  {t.who === 'wh' && <div className="dlg-nm">文衡</div>}
                  {!!t.tools?.length && <ToolTrace calls={t.tools} />}
                  {t.text}
                  {t.answer && <AnswerBlock answer={t.answer} />}
                  {t.qa && <QaChart qa={t.qa} />}
                  {t.notice && <p className="dlg-notice">{t.notice}</p>}
                  {t.who === 'wh' && t.elapsed != null && (
                    <p className="dlg-notice">
                      耗时 {(t.elapsed / 1000).toFixed(1)} 秒{t.ts ? ` · ${t.ts}` : ''}
                    </p>
                  )}
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
                          {running ? '正在出稿…（要停就点输入框那个键）' : '正在出稿…'}
                        </p>
                      )}
                      {t.trace.note && <p className="dlg-trk-note">{t.trace.note}</p>}
                      {t.trace.result && (
                        <ResultBlock result={t.trace.result} index={i}
                                     disabled={busy || !!running} canEdit={canEdit}
                                     onFix={(r, idx) => {
                                       /* 自动修复：flex＝重出灵活稿（产物已在）；
                                          repro＝重跑两段式且复刻先行（首出失败后最稳的再试）*/
                                       if (r.fixable === 'flex') void startRun(r.period, idx, 'single_trend')
                                       else void startRun(r.period, idx, 'single_trend', true)
                                     }}
                                     onRollback={(idx, period, point) => void doRollback(idx, period, point)} />
                      )}
                    </div>
                  )}
                  {t.who === 'wh' && !!t.actions?.length && (
                    <div className="dlg-acts">
                      {/* 2026-10-20：出稿（run）与证据面入口（取数台/运行档案）两种角色都有；
                          真门都在后端，前端不再按角色二次筛掉动作。 */}
                      {t.actions.map((a, j) => {
                          const isPicked = t.picked === j
                          const locked = busy || !!running || t.picked !== undefined
                          const pickedTag = isPicked
                            ? <span className="dlg-picked">✓ 已选</span> : null
                          if (a.kind === 'goto') {
                            return (
                              <a key={j} className={`dlg-act primary${isPicked ? ' picked' : ''}`}
                                 aria-disabled={locked || undefined}
                                 href={buildPeriodUrl(`/app/?view=${a.view ?? 'acquire'}`,
                                                      a.period || active.slots.period || '')}
                                 onClick={(e) => {
                                   if (t.picked !== undefined) { e.preventDefault(); return }
                                   pickAction(i, j)
                                 }}>{a.text}{pickedTag}</a>
                            )
                          }
                          if (a.kind === 'run') {
                            /* 覆盖确认（票 05）：唯一会问一次的地方——行内二次确认，不做弹窗 */
                            return (
                              <ConfirmButton key={j}
                                             className={`dlg-act primary${isPicked ? ' picked' : ''}`}
                                             confirmText="确认覆盖？" disabled={locked}
                                             onConfirm={() => {
                                               pickAction(i, j)
                                               void startRun(
                                                 a.period || active.slots.period || '', i,
                                                 t.run?.intent || 'single_trend')
                                             }}>
                                {a.text}{pickedTag}
                              </ConfirmButton>
                            )
                          }
                          return (
                            <button key={j} type="button" disabled={locked}
                                    className={`dlg-act ${a.kind === 'dismiss' ? 'ghost' : 'primary'}${isPicked ? ' picked' : ''}`}
                                    aria-pressed={isPicked || undefined}
                                    onClick={() => {
                                      pickAction(i, j)
                                      if (a.kind === 'send') void sendText(a.text)
                                    }}>
                              {a.text}{pickedTag}
                            </button>
                          )
                        })}
                    </div>
                  )}
                  {t.who === 'wh' && !!t.receipts?.length && (
                    <ReceiptBar receipts={t.receipts} />
                  )}
                </div>
              </div>
            ))}
            {busy && (
              <div className="dlg-turn wh">
                <div className="dlg-who">文</div>
                <div className="dlg-bub dlg-wait">
                  {streamText ? (
                    <span className="serif-prose dlg-streaming">
                      {streamText.replace(/^#{1,3}\s*/gm, '').replace(/\*\*/g, '')}
                      <span className="dlg-caret" aria-hidden="true" />
                    </span>
                  ) : (
                    <>
                      <span className="dlg-dot" aria-hidden="true" />
                      {stage || '正在理解这句话…'}
                    </>
                  )}
                  {!streamText && !!liveTools.length && <ToolTrace calls={liveTools} live />}
                </div>
              </div>
            )}
          </div>
        </div>

        <div className="dlg-composer">
          <form className="dlg-composer-in" onSubmit={(e) => { e.preventDefault(); void sendText(input) }}>
            <div className="dlg-box">
              <textarea rows={1} aria-label="对文衡说话" value={input}
                        placeholder={running ? '正在出稿…（点右边的 ■ 可以停）'
                                             : '发消息给文衡'}
                        disabled={!!running}
                        onChange={(e) => setInput(e.target.value)}
                        onKeyDown={(e) => {
                          if (e.key === 'Enter' && !e.shiftKey && !e.nativeEvent.isComposing) {
                            e.preventDefault()
                            void sendText(input)
                          }
                        }} />
              <div className="dlg-box-bar">
                <ModelMenu payload={models} busy={busy || !!running}
                           onPicked={(id) => void pickModel(id)} />
                {running ? (
                  <button className="dlg-send" type="button" aria-label="停止出稿"
                          onClick={() => void stopRun()}>■</button>
                ) : (
                  <button className="dlg-send" type="submit" aria-label="发送"
                          disabled={busy || !input.trim()}>↑</button>
                )}
              </div>
            </div>
            {modelMsg && <p className="dlg-composer-note">{modelMsg}</p>}
          </form>
        </div>
      </section>

      <ModelSettings open={settingsOpen} me={me}
                     onClose={() => setSettingsOpen(false)}
                     onChanged={(p) => { setModels(p); setModelMsg('') }} />
    </div>
  )
}

/** 出好了的出路（票 05）：三件套下载 / 去运行档案 / 自动修复 / 回滚到上一版。
    操作员只读（2026-10-11）：只留三件套下载；修复/回滚/运行档案入口不出现。 */
function ResultBlock({ result, index, disabled, canEdit, onFix, onRollback }: {
  result: TraceResult
  index: number
  disabled: boolean
  canEdit: boolean
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
      {canEdit && result.fixable && (
        <div className="dlg-acts">
          <button type="button" className="dlg-act primary" disabled={disabled}
                  onClick={() => onFix(result, index)}>自动修复</button>
          <a className="dlg-act ghost" href={result.archiveHref}>需人工接手 ▸</a>
        </div>
      )}
      {canEdit && point && !result.rollback?.out && (
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

/** 回退附注（票 04）：机制语 →「我该做什么」。命中回退时给一句人话，
    模型名/原因码收进可折叠「详情」；不是回退的 notice 原样显示。 */
function fallbackNote(notice: string): { human: string; detail: string } | null {
  if (!notice.includes('已回退规则版')) return null
  const human = notice.includes('数字校验')
    ? '这题按台账原文作答（AI 表述未通过数字核对，已改用原文）。'
    : '这题按台账原文作答（AI 这一轮没答上，已改用原文）。'
  return { human, detail: notice }
}

/** 查数据的回答（票 07）：正文带角标（点数字看来源）＋作答方式小字＋规则版对照。 */
function AnswerBlock({ answer }: { answer: DialogAnswer }) {
  const answered = answer.mode === 'model' || answer.mode === 'rule'
  const fb = fallbackNote(answer.notice)
  return (
    <div className="dlg-ans">
      {!!answer.text && <NumberedText text={answer.text} sources={answer.sources} />}
      {!!answer.rule_text && answer.rule_text !== answer.text && (
        <details className="dlg-rule">
          <summary>看规则版</summary>
          <NumberedText text={answer.rule_text} sources={answer.sources} />
        </details>
      )}
      {!!answer.receipts?.length && <ReceiptBar receipts={answer.receipts} />}
      {answered && (
        <div className="an-footer">
          <span className={`pill ${answer.mode === 'failed' ? 'bad' : answer.mode === 'model' ? 'signed' : 'stale'}`}>
            {answer.mode === 'failed' ? '本轮未作答' : answer.mode === 'model' ? '大模型作答' : '规则版作答'}
          </span>
          {answer.shield.checked > 0 && (
            <span className="pill ok">数字已核对：{answer.shield.passed} 个</span>
          )}
          <span className="hint">点数字看来源</span>
          <a className="hint" href="/app/?view=ledger" target="_blank" rel="noopener">打开台账 ↗</a>
        </div>
      )}
      {fb ? (
        <>
          <p className="dlg-notice">{fb.human}</p>
          <details className="dlg-detail">
            <summary>详情</summary>
            <p className="dlg-notice">{fb.detail}</p>
          </details>
        </>
      ) : (
        !!answer.notice && <p className="dlg-notice">{answer.notice}</p>
      )}
    </div>
  )
}

/** 问数图块（2026-10-31）：图型建议是柱/折/饼且引擎给了序列才画（table／空序列不画）。
    option 照问数工作台同款（颜色取站内令牌）；复用图册的 ChartFigure 画布——
    进入视野才初始化、随宽自适应、卸载销毁。前端只做形状搬运，不换算数值。 */
function qaOption(qa: DialogQa): EChartsOption | null {
  const cd = qa.chart_data
  const kind = qa.chart?.kind
  if (!cd || !cd.series?.length || (kind !== 'bar' && kind !== 'line' && kind !== 'pie')) {
    return null
  }
  const styles = getComputedStyle(document.documentElement)
  const ink = styles.getPropertyValue('--ink').trim() || '#15222B'
  const accent = styles.getPropertyValue('--zhu').trim() || '#26483B'
  const line = styles.getPropertyValue('--line').trim() || '#D6D0C0'
  if (kind === 'pie') {
    return {
      textStyle: { color: ink },
      tooltip: { trigger: 'item' },
      legend: { bottom: 0, textStyle: { color: ink } },
      series: [{
        type: 'pie', radius: ['35%', '68%'],
        data: cd.categories
          .map((c, i) => ({ name: String(c), value: cd.series[0].data[i] }))
          .filter((d): d is { name: string; value: number } => d.value != null),
        label: { color: ink },
      }],
    }
  }
  if (kind === 'line') {
    return {
      textStyle: { color: ink },
      tooltip: { trigger: 'axis' },
      grid: { left: 70, right: 24, top: 30, bottom: 40 },
      xAxis: { type: 'category', data: cd.categories,
               axisLine: { lineStyle: { color: line } }, axisLabel: { color: ink } },
      yAxis: { type: 'value', splitLine: { lineStyle: { color: line } },
               axisLabel: { color: ink } },
      series: cd.series.map((s) => ({
        type: 'line', name: s.name, data: s.data,
        itemStyle: { color: accent }, lineStyle: { color: accent, width: 2 }, symbolSize: 5,
      })),
    }
  }
  return {
    textStyle: { color: ink },
    tooltip: { trigger: 'axis' },
    grid: { left: 70, right: 24, top: 30, bottom: 60 },
    xAxis: { type: 'category', data: cd.categories,
             axisLine: { lineStyle: { color: line } },
             axisLabel: { color: ink, rotate: cd.categories.length > 8 ? 30 : 0 } },
    yAxis: { type: 'value', splitLine: { lineStyle: { color: line } },
             axisLabel: { color: ink } },
    series: cd.series.map((s) => ({
      type: 'bar', name: s.name, data: s.data, itemStyle: { color: accent },
    })),
  }
}

function QaChart({ qa }: { qa: DialogQa }) {
  const option = useMemo(() => qaOption(qa), [qa])
  if (!option) return null
  return (
    <div className="dlg-qachart">
      <ChartFigure option={option} height={230}
                   ariaLabel={qa.chart_data.title || '问数图表'} />
    </div>
  )
}

/** 回执条（AI 层工具调用的双面回执）：每条一枚 chip＝✓/×＋名称＋用时，明细（summary）
    收进悬浮提示（title）；没成或被拒的走琥珀降级（同 AnswerBlock「规则版作答」pill 的
    克制程度，不红色警报）。样式全用 index.css 既有类：.chips 容器＋.pill ok/.pill stale，
    零圆角、不另起色。chip 的类名与文字由 receiptChips 出（纯函数，vitest 直测）。 */
export type ReceiptChipVM = { cls: string; text: string; summary: string }

export function receiptChips(receipts: DialogReceipt[]): ReceiptChipVM[] {
  return receipts.map((r) => {
    const degraded = !r.ok || r.refused
    const ms = r.elapsed_ms > 0 ? ` ${r.elapsed_ms}ms` : ''
    return {
      cls: degraded ? 'pill stale' : 'pill ok',
      text: `${degraded ? '×' : '✓'} ${r.label}${ms}`,
      summary: r.summary,
    }
  })
}

function ReceiptBar({ receipts }: { receipts: DialogReceipt[] }) {
  return (
    <div className="chips mt-8">
      {receiptChips(receipts).map((c, i) => (
        <span key={i} className={c.cls} title={c.summary}>{c.text}</span>
      ))}
    </div>
  )
}
