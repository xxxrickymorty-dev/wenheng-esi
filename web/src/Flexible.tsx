/* 分析台第二块 · 灵活报告（第二条产线）——契约 #21①–④。
   对话式**流式**输出：问一句，报告在下面一步步长出来（规划 → 逐节 → 图 → 状态行）；
   两图一排（后端 mdview 已把连续图分组）；「AI 润色」走写作位重写叙述段（数字/图表/来源链不动）。
   正文来自后端（后端自己的 mdview.render，图指向 /p/<期次>/flexible/chart/<intent>/<name>）——
   前端只摆进去：不引 md 渲染器、不改一个字、不换算。
   ⚠ innerHTML 用在这里的前提：正文来自本仓产线产物、无任何用户输入（与老站同一渲染器）；
   将来若允许人工往里写正文，这里必须先过白名单清洗。 */

import { useEffect, useRef, useState } from 'react'
import {
  getFlexible, polishFlexible, runFlexibleStream,
  type FlexStreamEvent, type FlexibleData, type FlexWriteSummary,
} from './api5'
import { HttpError } from './api'
import { Icon } from './icons'

type Section = { title: string; html: string }

type Bot = {
  kind: 'bot'
  id: number
  intent: string
  discCn: string
  title: string
  outline: string[]
  sections: Section[]
  status: 'planning' | 'streaming' | 'polishing' | 'done' | 'error'
  backend: string
  elapsed: number
  nCharts: number
  checkPass: boolean | null
  error: string
  write: FlexWriteSummary | null
  polished: boolean
  hasRule: boolean
  variant: 'rule' | ''
  fromHistory: boolean
}

type User = { kind: 'user'; id: number; text: string }
type Msg = User | Bot

export function Flexible({ period }: { period: string | null }) {
  const [d, setD] = useState<FlexibleData | null>(null)
  const [msgs, setMsgs] = useState<Msg[]>([])
  const [note, setNote] = useState<string | null>(null)
  const [intent, setIntent] = useState('')
  const [disc, setDisc] = useState('')
  const [busy, setBusy] = useState(false)
  const [, setTick] = useState(0)

  const idRef = useRef(1)
  const t0Ref = useRef(0)
  const timerRef = useRef<number | null>(null)
  const logRef = useRef<HTMLDivElement | null>(null)

  function startTimer() {
    if (timerRef.current) window.clearInterval(timerRef.current)
    timerRef.current = window.setInterval(() => setTick((t) => t + 1), 200)
  }
  function stopTimer() {
    if (timerRef.current) { window.clearInterval(timerRef.current); timerRef.current = null }
  }
  useEffect(() => stopTimer, [])

  useEffect(() => {
    if (!period) return
    let alive = true
    setD(null); setNote(null); setMsgs([]); setBusy(false); setDisc('')
    ;(async () => {
      try {
        const j = await getFlexible(period)
        if (!alive) return
        setD(j)
        if (j.intents.length) setIntent(j.intents[0].id)
        if (j.body_html) {
          const cur = j.reports.find((x) => x.intent === j.cur)
          setMsgs([{
            kind: 'bot', id: idRef.current++, intent: j.cur ?? '', discCn: '',
            title: String(cur?.title ?? j.cur ?? ''), outline: [],
            sections: [{ title: '', html: j.body_html }],
            status: 'done', backend: '', elapsed: 0, nCharts: 0, checkPass: null,
            error: '', write: null, polished: false, hasRule: !!j.has_rule,
            variant: '', fromHistory: true,
          }])
        }
      } catch (e) {
        const h = e as HttpError
        if (alive) {
          setNote(h.status === 403 ? '灵活报告要管理员权限（用馆员账号登录后再来）。'
            : (h.body?.error ?? '读灵活报告失败。'))
        }
      }
    })()
    return () => { alive = false }
  }, [period])

  useEffect(() => {
    const el = logRef.current
    if (el) el.scrollTop = el.scrollHeight
  }, [msgs])

  function patch(id: number, f: (m: Bot) => Bot) {
    setMsgs((ms) => ms.map((m) => (m.kind === 'bot' && m.id === id ? f(m) : m)))
  }

  function elapsedLive() { return Math.round((Date.now() - t0Ref.current) / 100) / 10 }

  async function onGen() {
    if (!period || !intent || busy) return
    const itCn = d?.intents.find((x) => x.id === intent)?.cn ?? intent
    const discCn = d?.disciplines.find((x) => x.en === disc)?.cn ?? ''
    setBusy(true); setNote(null)
    const id = idRef.current++
    const bot: Bot = {
      kind: 'bot', id, intent, discCn, title: '', outline: [], sections: [],
      status: 'planning', backend: '', elapsed: 0, nCharts: 0, checkPass: null,
      error: '', write: null, polished: false, hasRule: false, variant: '',
      fromHistory: false,
    }
    setMsgs((ms) => [...ms,
      { kind: 'user', id: idRef.current++, text: `${discCn || '（学科由规划器挑）'} · ${itCn}（${period}）` },
      bot,
    ])
    t0Ref.current = Date.now(); startTimer()
    try {
      await runFlexibleStream(period, { intent, disc: disc || undefined }, (ev: FlexStreamEvent) => {
        patch(id, (m) => {
          if (ev.event === 'plan') {
            return { ...m, status: 'streaming', title: ev.title, outline: ev.outline,
                     backend: ev.backend }
          }
          if (ev.event === 'section') {
            return { ...m, sections: [...m.sections, { title: ev.title, html: ev.html }] }
          }
          if (ev.event === 'done') {
            return { ...m, status: 'done', elapsed: ev.elapsed, nCharts: ev.n_charts,
                     backend: ev.backend || m.backend, checkPass: ev.check_pass,
                     write: ev.write ?? null }
          }
          if (ev.event === 'error') {
            return { ...m, status: 'error', error: ev.message }
          }
          return m
        })
      })
      const j = await getFlexible(period, intent)
      setD(j)
    } catch (e) {
      const msg = e instanceof Error ? e.message : '生成失败。'
      patch(id, (m) => ({ ...m, status: 'error', error: msg }))
    } finally { setBusy(false); stopTimer() }
  }

  async function onPolish(m: Bot) {
    if (!period || busy) return
    setBusy(true); setNote(null)
    patch(m.id, (x) => ({ ...x, status: 'polishing' }))
    t0Ref.current = Date.now(); startTimer()
    try {
      const r = await polishFlexible(period, m.intent)
      const j = await getFlexible(period, m.intent)
      setD(j)
      patch(m.id, (x) => ({
        ...x, status: 'done', elapsed: r.elapsed, write: r.write ?? null,
        polished: !!r.write && r.write.rewritten > 0,
        sections: [{ title: '', html: j.body_html }], hasRule: true, variant: '',
      }))
    } catch (e) {
      const h = e as HttpError
      setNote(h.body?.error ?? h.message ?? '润色失败。')
      patch(m.id, (x) => ({ ...x, status: 'done' }))
    } finally { setBusy(false); stopTimer() }
  }

  async function onVariant(m: Bot, variant: 'rule' | '') {
    if (!period || busy) return
    setBusy(true)
    try {
      const j = await getFlexible(period, m.intent, variant || undefined)
      patch(m.id, (x) => ({ ...x, sections: [{ title: '', html: j.body_html }], variant }))
    } catch {
      setNote('切换这份稿失败了。')
    } finally { setBusy(false) }
  }

  async function onPick(which: string) {
    if (!period || busy) return
    try {
      const j = await getFlexible(period, which)
      const cur = j.reports.find((x) => x.intent === j.cur)
      setD(j)
      setMsgs((ms) => [...ms, {
        kind: 'bot', id: idRef.current++, intent: which, discCn: '',
        title: String(cur?.title ?? which), outline: [],
        sections: [{ title: '', html: j.body_html }], status: 'done', backend: '',
        elapsed: 0, nCharts: 0, checkPass: null, error: '', write: null,
        polished: false, hasRule: !!j.has_rule, variant: '', fromHistory: true,
      }])
    } catch { setNote('读取这份稿失败了。') }
  }

  function onLogClick(e: React.MouseEvent<HTMLDivElement>) {
    const t = e.target as HTMLElement
    if (t.tagName === 'IMG') {
      const src = (t as HTMLImageElement).src
      if (src) window.open(src, '_blank', 'noopener')
    }
  }

  function runState(m: Bot): string {
    if (m.status === 'planning') return `正在规划大纲 · ${elapsedLive()} 秒`
    if (m.status === 'streaming') return `正在生成 · ${m.backend || '模型'} · ${elapsedLive()} 秒`
    if (m.status === 'polishing') return `正在分析润色（逐段改写，数字不动）· ${elapsedLive()} 秒`
    if (m.status === 'error') return '生成失败'
    return ''
  }

  function doneText(m: Bot): string {
    if (m.fromHistory) return `已出稿${m.title ? ` · ${m.title}` : ''}（点「重新生成」出新版）`
    const base = `生成完成 · ${m.backend || '规则版'} · ${m.elapsed} 秒`
    const charts = m.nCharts ? ` · ${m.nCharts} 张图` : ''
    let extra = ''
    if (m.polished && m.write) {
      extra = ` · 已润色：${m.write.rewritten}/${m.write.segments} 段改写`
        + (m.write.fallbacks ? `，${m.write.fallbacks} 段保持规则稿` : '')
    } else if (m.polished === false && m.write && m.write.fallbacks === m.write.segments) {
      extra = ' · 本次未改写（整段保持规则稿）'
    }
    return base + charts + extra
  }

  return (
    <section className="card" style={{ marginTop: 18, padding: '22px 24px' }}>
      <h2 style={{ fontSize: 22, display: 'flex', alignItems: 'center', gap: 10, flexWrap: 'wrap' }}>
        <Icon name="doc" size={22} />灵活报告 · 第二条产线
        <span className="tag" style={{ marginLeft: 6 }}>{period ?? '（选择期次）'}</span>
        <span className="pill stale">内部参考件</span>
      </h2>

      <div className="fx-form">
        <label>分析意图
          <select value={intent} onChange={(e) => setIntent(e.target.value)}>
            {(d?.intents ?? []).map((i) => <option key={i.id} value={i.id}>{i.cn}</option>)}
          </select>
        </label>
        <label>指定学科
          <select value={disc} onChange={(e) => setDisc(e.target.value)}>
            <option value="">（不指定）</option>
            {(d?.disciplines ?? []).map((x) => (
              <option key={x.en} value={x.en}>{x.cn}</option>
            ))}
          </select>
        </label>
        <button className="btn primary" onClick={onGen} disabled={!period || !intent || busy}>
          <Icon name="play" size={19} />{busy ? '正在出稿……' : '生成分析稿'}
        </button>
      </div>
      {!!d?.reports.length && (
        <div className="fx-chips">
          <span>已出稿：</span>
          {d.reports.map((r) => (
            <button key={r.intent} className={r.intent === d.cur ? 'on' : ''}
                    onClick={() => onPick(r.intent)} disabled={busy}>
              {r.title || r.intent}
              {typeof r.meta?.n_charts === 'number' ? ` · ${r.meta.n_charts} 图` : ''}
              {typeof r.meta?.generated_at === 'string' && r.meta.generated_at
                ? ` · ${String(r.meta.generated_at).slice(5, 16)}` : ''}
              {r.has_rule ? ' · 可对照规则稿' : ''}
            </button>
          ))}
        </div>
      )}

      {note && <div className="pending-box" style={{ marginTop: 12 }}>{note}</div>}
      {d && !busy && !d.body_html && !msgs.length && (
        <p className="hint" style={{ marginTop: 12 }}>还没有出稿——点「生成分析稿」开始。</p>
      )}

      <div className="fx-log" ref={logRef} onClick={onLogClick}>
        {msgs.map((m) => m.kind === 'user' ? (
          <div key={m.id} className="fx-msg user">{m.text}</div>
        ) : (
          <div key={m.id} className="fx-msg bot">
            {(m.status !== 'done' || m.fromHistory === false) && (
              <div className="fx-status">
                <span className={`dot ${m.status === 'done' ? 'done'
                  : m.status === 'error' ? 'bad' : 'run'}`} />
                <span>{m.status === 'done' ? doneText(m) : runState(m)}</span>
              </div>
            )}
            {!!m.outline.length && (
              <div className="fx-plan">
                {m.outline.map((t) => <span key={t} className="chip">{t}</span>)}
              </div>
            )}
            {m.sections.map((s, i) => (
              <div key={i}>
                {s.title && <h3 className="fx-sec-h">{s.title}</h3>}
                <div className="fx-md" dangerouslySetInnerHTML={{ __html: s.html }} />
              </div>
            ))}
            {m.status === 'error' && <div className="pending-box">{m.error}</div>}
            {(m.status === 'done' || m.status === 'error') && (
              <div className="fx-foot">
                <span className={`dot ${m.status === 'done' ? 'done' : 'bad'}`} />
                <span>{m.status === 'done' ? doneText(m)
                  : `出稿没成功：${m.error}`}</span>
                <span className="spacer" />
                {m.hasRule && m.status === 'done' && (
                  <button className="btn small" disabled={busy}
                          onClick={() => onVariant(m, m.variant === 'rule' ? '' : 'rule')}>
                    {m.variant === 'rule' ? '看润色稿' : '看规则稿'}
                  </button>
                )}
                {m.status === 'done' && (
                  <button className="btn small" disabled={busy || !d?.write.available}
                          title={d?.write.available ? '按写作位重写叙述段（数字与图表不动）'
                            : '写作位未开启（部署开关未设或未配云端模型）'}
                          onClick={() => onPolish(m)}>
                    AI 润色
                  </button>
                )}
                <button className="btn small" disabled={busy}
                        onClick={() => { setIntent(m.intent); onGen() }}>
                  重新生成
                </button>
              </div>
            )}
          </div>
        ))}
      </div>
    </section>
  )
}
