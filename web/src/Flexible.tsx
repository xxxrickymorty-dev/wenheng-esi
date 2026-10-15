/* 分析台 · 灵活报告（第二条产线）——**双栏定稿**（rick 2026-10-14，grilling 两轮）：
   左右两栏 = 两份报告并排（横看 / 纵看），各栏独立滚动；生成中对应栏逐节长出；
   窗格头 = 短名 + 一行视角 + 出稿信息 + 看规则稿 / 下载报告 / 重新生成。
   全文写作升级（高推理、判断草稿、待审线）在引擎侧第二段做（ADR-0009）。

   正文来自后端（后端自己的 mdview.render，图指向 /p/<期次>/flexible/chart/<intent>/<name>）——
   前端只摆进去：不引 md 渲染器、不换算。唯一一处改写＝`humanBody` 把正文抬头里的
   「规划后端：模型串」换成人话（技术串收进窗格头「生成详情」折叠块），不改任何数字。
   ⚠ innerHTML 用在这里的前提：正文来自本仓产线产物、无任何用户输入（与老站同一渲染器）；
   将来若允许人工往里写正文，这里必须先过白名单清洗。 */

import { useEffect, useRef, useState } from 'react'
import {
  getFlexible, runFlexibleStream,
  type FlexStreamEvent, type FlexibleDiscipline,
} from './api-flexible'
import { Icon } from './icons'
import { ConfirmButton } from './ConfirmButton'
import { errorNote } from './lib/status'

type Section = { title: string; html: string }

type Pane = {
  loading: boolean
  has: boolean
  hasRule: boolean
  meta: Record<string, unknown> | null
  variant: '' | 'rule'
  /** 正文缓存：normal＝标准稿，rule＝规则稿留底（切回去不重取） */
  bodies: { normal?: string; rule?: string }
  /** 生成中的流式态；null＝没在生成 */
  stream: null | {
    status: 'planning' | 'streaming' | 'error'
    title: string
    outline: string[]
    sections: Section[]
    backend: string
    error: string
  }
  /** 读取/生成失败的提示（栏内显示，不打断另一栏） */
  error: string
}

function emptyPane(): Pane {
  return { loading: true, has: false, hasRule: false, meta: null,
           variant: '', bodies: {}, stream: null, error: '' }
}

/** 每栏一句话的视角（界面文案；未知意图不硬凑） */
const PANE_LEAD: Record<string, string> = {
  cross_compare: '横看 · 22 个学科与 1% 的距离',
  single_trend: '纵看 · 单学科的多指标走势',
}

/** 栏序（rick 2026-10-14 定稿）：左·多学科横向 / 右·单学科纵向；未知意图排在后面 */
const PANE_ORDER = ['cross_compare', 'single_trend']

function metaLine(meta: Record<string, unknown> | null): string {
  const m = meta ?? {}
  const parts: string[] = []
  if (typeof m.n_charts === 'number') parts.push(`${m.n_charts} 张图`)
  if (typeof m.generated_at === 'string' && m.generated_at) {
    parts.push(`生成于 ${String(m.generated_at).slice(5, 16)}`)
  }
  const backend = String(m.backend ?? '')
  if (backend) parts.push(backend === 'rule' ? '规则规划' : 'AI 自主规划')
  return parts.join(' · ')
}

/** 出稿方式的人话（技术串不露脸；原始模型名收进窗格头「生成详情」折叠块）。 */
function humanBackend(raw: string): string {
  return !raw || raw === 'rule' ? '规则规划' : 'AI 自主规划'
}

/** 需要藏进折叠块的原始模型名（规则规划无需可追溯的模型串，回空）。 */
function modelName(meta: Record<string, unknown> | null): string {
  const b = String((meta ?? {}).backend ?? '')
  return b && b !== 'rule' ? b : ''
}

/** 后端正文里的「规划后端：模型串」换成人话（UX.md §十 / 纪律②）；两栏同一处代码，天然一致。 */
function humanBody(html: string): string {
  return html.replace(/规划后端：\s*(?:<strong>)?([^<）\s]+)(?:<\/strong>)?/g,
    (_m, raw: string) => `规划方式：${humanBackend(raw)}`)
}

export function Flexible({ period, canEdit }: { period: string | null; canEdit: boolean }) {
  const [intents, setIntents] = useState<{ id: string; cn: string }[]>([])
  const [disciplines, setDisciplines] = useState<FlexibleDiscipline[]>([])
  const [pan, setPan] = useState<Record<string, Pane>>({})
  const [note, setNote] = useState<string | null>(null)
  const [intent, setIntent] = useState('')
  const [disc, setDisc] = useState('')
  const [busy, setBusy] = useState<string | null>(null)   // 正在生成的意图
  const [, setTick] = useState(0)

  const t0Ref = useRef(0)
  const timerRef = useRef<number | null>(null)
  const boxRef = useRef<HTMLDivElement | null>(null)

  function startTimer() {
    if (timerRef.current) window.clearInterval(timerRef.current)
    timerRef.current = window.setInterval(() => setTick((t) => t + 1), 200)
  }
  function stopTimer() {
    if (timerRef.current) { window.clearInterval(timerRef.current); timerRef.current = null }
  }
  useEffect(() => stopTimer, [])

  /** 一次性把两栏的稿取齐（清单 + 各栏正文；有稿的才有正文） */
  useEffect(() => {
    if (!period) return
    let alive = true
    setNote(null); setBusy(null); setIntent(''); setDisc('')
    setPan({})
    ;(async () => {
      try {
        const j = await getFlexible(period)
        if (!alive) return
        const list = [...j.intents].sort((a, b) => {
          const ia = PANE_ORDER.indexOf(a.id); const ib = PANE_ORDER.indexOf(b.id)
          return (ia < 0 ? 99 : ia) - (ib < 0 ? 99 : ib)
        })
        setIntents(list)
        setDisciplines(j.disciplines)
        if (list.length) setIntent(list[0].id)
        const init: Record<string, Pane> = {}
        for (const it of list) init[it.id] = emptyPane()
        for (const it of list) {
          const r = j.reports.find((x) => x.intent === it.id)
          if (!r) continue
          try {
            const jj = await getFlexible(period, it.id)
            if (!alive) return
            init[it.id] = { ...emptyPane(), loading: false, has: true,
                            hasRule: !!jj.has_rule, meta: r.meta ?? null,
                            bodies: { normal: jj.body_html } }
          } catch (e) {
            init[it.id] = { ...emptyPane(), loading: false, error: errorNote(e, '灵活报告') }
          }
        }
        for (const it of list) init[it.id].loading = false
        setPan(init)
      } catch (e) {
        if (alive) setNote(errorNote(e, '灵活报告'))
      }
    })()
    return () => { alive = false }
  }, [period])

  /** 正文里的图：点开看大图——img 默认不可聚焦，这里补键盘入口 */
  useEffect(() => {
    const el = boxRef.current
    if (!el) return
    const openImage = (img: HTMLImageElement) => {
      if (img.src) window.open(img.src, '_blank', 'noopener')
    }
    for (const img of Array.from(el.querySelectorAll<HTMLImageElement>('.fx-md img'))) {
      if (img.dataset.fxWired) continue
      img.dataset.fxWired = '1'
      img.tabIndex = 0
      img.setAttribute('role', 'link')
      img.setAttribute('aria-label', '查看大图')
      img.addEventListener('click', () => openImage(img))
      img.addEventListener('keydown', (event) => {
        if (event.key !== 'Enter' && event.key !== ' ') return
        event.preventDefault()
        openImage(img)
      })
    }
  }, [pan])

  /** 生成（流式）：表单用来选意图+学科；窗格头「重新生成」按该栏意图直接跑 */
  async function onGen(targetIntent: string, targetDisc?: string) {
    if (!period || !targetIntent || busy) return
    setBusy(targetIntent)
    setNote(null)
    setPan((p) => ({ ...p, [targetIntent]: {
      ...(p[targetIntent] ?? emptyPane()), error: '',
      stream: { status: 'planning', title: '', outline: [], sections: [],
                backend: '', error: '' },
    } }))
    t0Ref.current = Date.now(); startTimer()
    try {
      await runFlexibleStream(period, { intent: targetIntent, disc: targetDisc || undefined },
        (ev: FlexStreamEvent) => {
          setPan((p) => {
            const pane = p[targetIntent]
            if (!pane || !pane.stream) return p
            const st = pane.stream
            if (ev.event === 'plan') {
              return { ...p, [targetIntent]: { ...pane, stream: {
                ...st, status: 'streaming', title: ev.title, outline: ev.outline,
                backend: ev.backend } } }
            }
            if (ev.event === 'section') {
              return { ...p, [targetIntent]: { ...pane, stream: {
                ...st, sections: [...st.sections, { title: ev.title, html: ev.html }] } } }
            }
            if (ev.event === 'stopped') {
              return { ...p, [targetIntent]: { ...pane, stream: {
                ...st, status: 'error', error: '这次生成被停了——栏里还是上一版。' } } }
            }
            if (ev.event === 'error') {
              return { ...p, [targetIntent]: { ...pane, stream: {
                ...st, status: 'error', error: ev.message } } }
            }
            return p
          })
        })
      // 流完重取该栏：成稿上屏（正文与后端同源）
      const jj = await getFlexible(period, targetIntent)
      const r = jj.reports.find((x) => x.intent === targetIntent)
      setPan((p) => ({ ...p, [targetIntent]: {
        ...(p[targetIntent] ?? emptyPane()),
        loading: false, has: true, hasRule: !!jj.has_rule, meta: r?.meta ?? null,
        variant: '', bodies: { normal: jj.body_html }, stream: null, error: '' } }))
    } catch (e) {
      const msg = e instanceof Error ? e.message : '生成失败。'
      setPan((p) => {
        const pane = p[targetIntent]
        if (!pane) return p
        const stream = pane.stream ?? { status: 'error' as const, title: '', outline: [],
                                           sections: [], backend: '', error: '' }
        return { ...p, [targetIntent]: { ...pane, stream: { ...stream, status: 'error', error: msg } } }
      })
    } finally { setBusy(null); stopTimer() }
  }

  /** 看规则稿 ⇄ 看标准稿（同一份留底，一次取到就缓存） */
  async function onVariant(targetIntent: string) {
    if (!period || busy) return
    const pane = pan[targetIntent]
    if (!pane || !pane.has) return
    const next: '' | 'rule' = pane.variant === 'rule' ? '' : 'rule'
    if (next === '' || pane.bodies.rule !== undefined) {
      setPan((p) => ({ ...p, [targetIntent]: { ...pane, variant: next } }))
      return
    }
    try {
      const jj = await getFlexible(period, targetIntent, 'rule')
      setPan((p) => ({ ...p, [targetIntent]: {
        ...p[targetIntent],
        bodies: { ...p[targetIntent].bodies, rule: jj.body_html },
        variant: 'rule' } }))
    } catch {
      setNote('切到规则稿失败了。')
    }
  }

  function streamText(st: NonNullable<Pane['stream']>): string {
    const sec = st.outline[st.sections.length]
    const elapsed = Math.round((Date.now() - t0Ref.current) / 100) / 10
    if (st.status === 'planning') return `正在规划这个题怎么拆 · 已 ${elapsed} 秒`
    if (st.status === 'error') return '没写成'
    return `${sec ? `正在写「${sec}」` : '正在写'} · ${humanBackend(st.backend)} · 已 ${elapsed} 秒`
  }

  return (
    <>
      <section className="card pad-card-lg">
        <h2 className="h-sec h-lg">
          <Icon name="doc" size={22} />灵活报告 · 第二条产线
          <span className="tag ml-6">{period ?? '（选择期次）'}</span>
          <span className="pill stale">内部参考件</span>
        </h2>
        {canEdit && (
          <div className="fx-form">
            <label>分析意图
              <select value={intent} onChange={(e) => setIntent(e.target.value)}>
                {intents.map((i) => <option key={i.id} value={i.id}>{i.cn}</option>)}
              </select>
            </label>
            <label>指定学科
              <select value={disc} onChange={(e) => setDisc(e.target.value)}>
                <option value="">（不指定）</option>
                {disciplines.map((x) => (
                  <option key={x.en} value={x.en}>{x.cn}</option>
                ))}
              </select>
            </label>
            <button className="btn primary" onClick={() => void onGen(intent, disc)}
                    disabled={!period || !intent || busy !== null}>
              <Icon name="play" size={19} />{busy ? '正在出稿……' : '生成分析稿'}
            </button>
          </div>
        )}
        {note && <div className="pending-box mt-12">{note}</div>}
        {period && !note && !intents.length && (
          <p className="hint mt-12">正在读取灵活报告……</p>
        )}
      </section>

      <div className="fx-panes" ref={boxRef}>
        {intents.map((it) => {
          const pane = pan[it.id]
          if (!pane) return null
          const body = pane.variant === 'rule'
            ? (pane.bodies.rule ?? '')
            : (pane.bodies.normal ?? '')
          return (
            <section className="fx-pane" key={it.id} aria-label={it.cn}>
              <header className="fx-pane-h">
                <div>
                  <h3>{it.cn}</h3>
                  <p className="fx-pane-meta">
                    {PANE_LEAD[it.id] ? `${PANE_LEAD[it.id]} ｜ ` : ''}
                    {pane.stream ? '正在出稿' : (pane.has ? metaLine(pane.meta) : '还没有出稿')}
                  </p>
                  {pane.has && !pane.stream && modelName(pane.meta) && (
                    <details className="fx-backend" data-src="backend">
                      <summary>生成详情</summary>
                      <p>规划后端：{modelName(pane.meta)}</p>
                    </details>
                  )}
                </div>
                <div className="fx-pane-acts">
                  {pane.hasRule && (
                    <button className="btn small" disabled={busy !== null}
                            onClick={() => void onVariant(it.id)}>
                      {pane.variant === 'rule' ? '看标准稿' : '看规则稿'}
                    </button>
                  )}
                  {pane.has && (
                    <a className="btn small" download
                       href={`/p/${encodeURIComponent(period ?? '')}/flexible/${encodeURIComponent(it.id)}/report.html`}>
                      <Icon name="doc" size={15} />下载报告
                    </a>
                  )}
                  {pane.has && canEdit && (
                    <ConfirmButton className="btn small" confirmText="确认重出？"
                            disabled={busy !== null}
                            title="按这一栏的意图重新出一份（覆盖当前稿）"
                            onConfirm={() => void onGen(it.id)}>
                      <Icon name="play" size={15} />重新生成
                    </ConfirmButton>
                  )}
                </div>
              </header>

              <div className="fx-pane-b">
                {pane.error && <div className="pending-box">{pane.error}</div>}
                {pane.stream && (
                  <>
                    <div className="fx-status" aria-live="polite">
                      <span className={`dot ${pane.stream.status === 'error' ? 'bad' : 'run'}`} />
                      <span>{streamText(pane.stream)}</span>
                    </div>
                    {!!pane.stream.outline.length && (
                      <div className="fx-plan">
                        {pane.stream.outline.map((t) => <span key={t} className="chip">{t}</span>)}
                      </div>
                    )}
                    {pane.stream.sections.map((s, i) => (
                      <div key={i}>
                        {s.title && <h3 className="fx-sec-h">{s.title}</h3>}
                        <div className="fx-md" dangerouslySetInnerHTML={{ __html: humanBody(s.html) }} />
                      </div>
                    ))}
                    {pane.stream.status === 'error' && (
                      <div className="pending-box">{pane.stream.error}</div>
                    )}
                  </>
                )}
                {!pane.stream && pane.loading && <p className="hint mt-12">正在读取……</p>}
                {!pane.stream && !pane.loading && pane.has && (
                  <div className="fx-md" dangerouslySetInnerHTML={{ __html: humanBody(body) }} />
                )}
                {!pane.stream && !pane.loading && !pane.has && !pane.error && (
                  <p className="fx-empty">
                    {canEdit
                      ? '这一份还没出稿——到上方「生成分析稿」把它跑出来。'
                      : '这一期还没有灵活报告；操作员只读，生成仅管理员可用。'}
                  </p>
                )}
              </div>
            </section>
          )
        })}
      </div>
    </>
  )
}
