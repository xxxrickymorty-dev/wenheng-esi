/* 对话前门（票 01：骨架 + 期次识别）。
   版面照 `mockups/对话前门.html`（五稿）：左＝对话历史 / 中＝对话流 / 底＝输入框。
   口径照 ADR-0006：对话只做指挥——本页只认期次与意图槽位，数字全部来自后端；
   解析走 `/api/dialog/turn`（后端 src/ai 能力口，规则版离线可跑）。 */

import { useEffect, useRef, useState } from 'react'
import { getMe, type Me } from '../api'
import { postDialogTurn, type DialogAction } from '../api-dialog'
import { clearSlot, conversationTitle, emptySlots, hasSlots, type DialogSlots } from '../lib/dialog'
import { buildPeriodUrl } from '../lib/period'
import { errorNote } from '../lib/status'

type Turn = { who: 'me' | 'wh'; text: string; notice?: string; actions?: DialogAction[]; dismissed?: boolean }
type Conversation = { id: number; title: string; turns: Turn[]; slots: DialogSlots }

const PALETTE_STORAGE_KEY = 'wenheng-palette'

/** 工作台入口（按需打开；深链保留）——与 mockup 顶栏「工作台 ▾」一致。 */
const WORKBENCH: [string, string][] = [
  ['生成台', '/app/'],
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
  }, [activeId, active.turns.length, busy])

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
    if (!text || busy) return
    setInput('')
    setBusy(true)
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
        turns: [...c.turns, { who: 'wh', text: r.text, notice: r.notice, actions: r.actions }],
      }))
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
            {active.turns.map((t, i) => (
              <div key={i} className={`dlg-turn ${t.who}`}>
                <div className="dlg-who">{t.who === 'me' ? '你' : '文'}</div>
                <div className="dlg-bub">
                  {t.who === 'wh' && <div className="dlg-nm">文衡</div>}
                  {t.text}
                  {t.notice && <p className="dlg-notice">{t.notice}</p>}
                  {t.who === 'wh' && !!t.actions?.length && !t.dismissed && (
                    <div className="dlg-acts">
                      {t.actions.map((a, j) => a.kind === 'goto' ? (
                        <a key={j} className="dlg-act primary"
                           href={buildPeriodUrl(`/app/?view=${a.view ?? 'acquire'}`,
                                                a.period || active.slots.period || '')}>{a.text}</a>
                      ) : (
                        <button key={j} type="button" disabled={busy}
                                className={`dlg-act ${a.kind === 'send' ? 'primary' : 'ghost'}`}
                                onClick={() => a.kind === 'send' ? void sendText(a.text) : dismissActions(i)}>
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
                        placeholder="说一句话，比如「帮我做 9 月的报告」…"
                        onChange={(e) => setInput(e.target.value)}
                        onKeyDown={(e) => {
                          if (e.key === 'Enter' && !e.shiftKey && !e.nativeEvent.isComposing) {
                            e.preventDefault()
                            void sendText(input)
                          }
                        }} />
              <button className="dlg-send" type="submit" aria-label="发送"
                      disabled={busy || !input.trim()}>↑</button>
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
