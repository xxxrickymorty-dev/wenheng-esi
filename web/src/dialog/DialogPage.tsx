/* 对话前门（票 01–04：期次识别 → 盘点 → 核对门 → 出稿流式）。
   版面照 `mockups/对话前门.html`（五稿）：左＝对话历史 / 中＝对话流 / 底＝输入框。
   口径照 ADR-0006：对话只做指挥——数字全部来自后端；
   解析走 `/api/dialog/turn`（后端 src/ai 能力口，规则版离线可跑）；
   出稿走**既有**流式口 `/api/periods/{p}/flexible/stream`（NDJSON，真实节点），
   流式中发送键原地变停止键（契约 #21⑤ 喊停，终态 `stopped`）。 */

import { useEffect, useRef, useState } from 'react'
import { getMe, type Me } from '../api'
import { postDialogTurn, type DialogAction, type DialogRun } from '../api-dialog'
import { runFlexibleStream, stopFlexible, type FlexStreamEvent } from '../api-flexible'
import { clearSlot, conversationTitle, emptySlots, hasSlots, type DialogSlots } from '../lib/dialog'
import { buildPeriodUrl } from '../lib/period'
import { errorNote } from '../lib/status'

/** 出稿轨迹（票 04）：逐段出（挑学科 / 配图 / 取数 / 数据校验 / 收尾）。
    全部文字由事件字段组装（视图层只读，不现算数字）。 */
type TraceStep = { n: number; title: string; detail: string; state: 'doing' | 'done' | 'halt' }
type Trace = {
  status: 'streaming' | 'done' | 'stopped' | 'error'
  steps: TraceStep[]
  note?: string
}
type Turn = { who: 'me' | 'wh' | 'sys'; text: string; notice?: string; actions?: DialogAction[]
              dismissed?: boolean; run?: DialogRun; trace?: Trace }
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
                              actions: r.actions, run: r.run ?? undefined }],
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

  /** 出稿（票 04）：走**既有**流式口（NDJSON，真实节点）——轨迹逐段落在回复里；
      发送键原地变停止键；「停止」走 #21⑤ 喊停，终态 `stopped` 从原流回来。 */
  async function startRun(period: string, index: number, intent: string) {
    if (!period || running) return
    runTokenRef.current = ''
    setRunning({ period, index })
    const upd = (fn: (t: Trace) => Trace) => {
      updateActive((c) => ({
        ...c,
        turns: c.turns.map((t, i) => (i === index && t.trace ? { ...t, trace: fn(t.trace) } : t)),
      }))
      setTick((x) => x + 1)
    }
    const trace0: Trace = { status: 'streaming', steps: [
      { n: 1, title: '挑学科', detail: '正在规划…', state: 'doing' }] }
    updateActive((c) => ({
      ...c,
      turns: c.turns.map((t, i) => (i === index ? { ...t, trace: trace0 } : t)),
    }))
    let sections = 0
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
          const ok = ev.check_pass
          upd((t) => ({
            ...t,
            status: 'done',
            steps: [
              ...t.steps.map((s) => ({ ...s, state: 'done' as const })),
              { n: 4, title: '数据校验',
                detail: ok
                  ? `一次通过（${ev.n_sources ?? 0} 个数据点能指回台账 · 图 ${ev.n_charts} 张 · 章节 ${ev.n_sections ?? sections} 节）`
                  : '没过——去运行档案看是哪一条',
                state: ok ? 'done' : 'halt' },
              { n: 5, title: '收尾', detail: `报告已出（用时 ${ev.elapsed} 秒）`, state: 'done' },
            ],
            note: ok
              ? `出好了——「${ev.title || '报告'}」在「AI 分析台 · 灵活报告」里（顶栏「工作台 ▾」）。`
              : '没出好——数据校验没过，稿子没放出来。',
          }))
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
                    </div>
                  )}
                  {t.who === 'wh' && !!t.actions?.length && !t.dismissed && (
                    <div className="dlg-acts">
                      {t.actions.map((a, j) => a.kind === 'goto' ? (
                        <a key={j} className="dlg-act primary"
                           href={buildPeriodUrl(`/app/?view=${a.view ?? 'acquire'}`,
                                                a.period || active.slots.period || '')}>{a.text}</a>
                      ) : (
                        <button key={j} type="button" disabled={busy || !!running}
                                className={`dlg-act ${a.kind === 'dismiss' ? 'ghost' : 'primary'}`}
                                onClick={() => {
                                  if (a.kind === 'send') void sendText(a.text)
                                  else if (a.kind === 'run') {
                                    void startRun(a.period || '', i, t.run?.intent || 'single_trend')
                                  } else dismissActions(i)
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
