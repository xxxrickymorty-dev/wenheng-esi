/* 学科分析（2026-11-04 spec）——左栏新页＝灵活报告的卡片式入口。
   右页纸面：报头（眉标 / 期次只读 / 「打开最近一份」条件链）＋ 22 张学科卡网格
   （名单来自后端 getFlexible().disciplines，en/cn；空则整页空态）。点卡＝唯一动作：
   流式生成单学科分析报告（runFlexibleStream，NDJSON plan/section/done），
   同页同时只允许一个任务（busy 锁，其余卡禁用）；done 新窗开
   /p/<期次>/flexible/single_trend/report.html，卡面标「最近生成」（本地 state，不入库）；
   error 卡面一句。权限：生成口后端 admin-only——非 admin 点未生成的卡提示
   「生成请找管理员」（hint，不禁用整页）；已生成报告的打开人人可用。

   🔴 本页没有任何数字，只有学科名单与流事件文案——运行期大模型不进数据路径。
   测试无 jsdom（与全站同口径，照 ModelPanel 的缝）：展示件 DisciplineView、
   权限分流 cardAction、生成控制器 generateDisciplineReport 都导出，
   DisciplinePage.test.tsx 直接调（控制器就是卡片 onClick 走的那份代码）。 */

import { useEffect, useRef, useState } from 'react'
import {
  getFlexible, runFlexibleStream,
  type FlexStreamEvent, type FlexibleData, type FlexibleDiscipline,
} from './api-flexible'
import type { Me } from './api'
import { errorNote } from './lib/status'
import { Icon } from './icons'
import './discipline.css'

/** 单学科报告的公开读路由（票面 URL；报告与后端同源，前端只开窗不加工）。 */
export function reportUrl(period: string): string {
  return `/p/${encodeURIComponent(period)}/flexible/single_trend/report.html`
}

/** 最近一份 single_trend 报告是哪个学科的（meta.disc，en；没有已生成报告回 null）。
    「该学科无已生成报告」的判定口径：flex_meta.json 只留最近一次的学科，
    前端只认这份——不猜历史。 */
export function latestDiscOf(data: FlexibleData | null): string | null {
  const r = data?.reports.find((x) => x.intent === 'single_trend')
  const d = (r?.meta as { disc?: unknown } | undefined)?.disc
  return typeof d === 'string' && d ? d : null
}

export type CardAction = { kind: 'generate' } | { kind: 'open' } | { kind: 'hint' }

/** 卡片点击的分流（权限口径的唯一来源）：admin → 生成；
    最近一份报告正是这个学科 → 打开（spec 原话「已生成报告的打开人人可用」，
    打开不设角色门；页面本有登录门）；否则 → 提示找管理员。 */
export function cardAction(me: Me | null, disc: FlexibleDiscipline,
                           latestDisc: string | null): CardAction {
  if (me?.role === 'admin') return { kind: 'generate' }
  if (latestDisc && latestDisc === disc.en) return { kind: 'open' }
  return { kind: 'hint' }
}

/** 生成中卡面的进度句（spec：「规划中…」→「第 N 节…」→收尾）。 */
export const STAGE_PLANNING = '规划中…'
export const STAGE_TAIL = '收尾…'
export const stageSection = (n: number) => `第 ${n} 节…`

/** 点卡走的生成控制器（与 onClick 同一份代码）：进度上卡面，done 开新窗并回传 onDone
    （父层标「最近生成」），error 事件或请求失败回传 onError 一句（errorNote 口径）。 */
export async function generateDisciplineReport(
  period: string,
  disc: FlexibleDiscipline,
  h: { onStage: (label: string) => void; onDone: () => void; onError: (message: string) => void },
): Promise<void> {
  h.onStage(STAGE_PLANNING)
  let n = 0
  let doneSeen = false
  let failed = false
  try {
    await runFlexibleStream(period, { intent: 'single_trend', disc: disc.en },
      (ev: FlexStreamEvent) => {
        if (ev.event === 'section') { n += 1; h.onStage(stageSection(n)); return }
        if (ev.event === 'done') {
          doneSeen = true
          h.onStage(STAGE_TAIL)
          window.open(reportUrl(period), '_blank', 'noopener')
          return
        }
        if (ev.event === 'stopped') { failed = true; h.onError('这次生成被停了——可回卡面重新点。'); return }
        if (ev.event === 'error') { failed = true; h.onError(ev.message); return }
      })
    if (doneSeen) h.onDone()
    else if (!failed) h.onError('生成没有跑完——稍后再试。')
  } catch (e) {
    h.onError(errorNote(e, '生成学科报告'))
  }
}

/** 卡面一句话（生成失败 / 权限提示），标在点过的那张卡上。 */
export type CardNote = { en: string; kind: 'error' | 'hint'; text: string }

/** 展示件（测试从这里进：无 effect、无请求）。loading＝名单还没读到（不画空态，
    免得一进页就闪「没有学科」）；empty 名单才给空态句。 */
export function DisciplineView(props: {
  period: string | null
  loading: boolean
  loadErr: string
  hasReport: boolean
  disciplines: FlexibleDiscipline[]
  busy: string | null
  stage: string
  note: CardNote | null
  recent: string | null
  onCard: (d: FlexibleDiscipline) => void
}) {
  const { period, loading, loadErr, hasReport, disciplines, busy, stage, note, recent, onCard } = props
  return (
    <>
      <header className="dp-mast">
        <div>
          <p className="dp-eyebrow">学科分析</p>
          <h1>{period ?? '——————'}</h1>
        </div>
        {hasReport && period && (
          <a className="dp-open" href={reportUrl(period)} target="_blank" rel="noopener">
            打开最近一份 ↗
          </a>
        )}
      </header>

      <div className="dp-rule" aria-hidden="true" />

      {loading ? null : loadErr ? (
        <p className="dp-empty" role="alert">{loadErr}</p>
      ) : disciplines.length === 0 ? (
        <p className="dp-empty">本期还没有可分析的学科。</p>
      ) : (
        <ol className="dp-grid">
          {disciplines.map((d) => {
            const state = busy === d.en
              ? { cls: 'run', text: stage }
              : note?.en === d.en
                ? { cls: note.kind, text: note.text }
                : recent === d.en
                  ? { cls: 'ok', text: '最近生成' }
                  : null
            return (
              <li key={d.en}>
                <button type="button" className="dp-card" disabled={!!busy}
                        data-now={busy === d.en || undefined}
                        onClick={() => onCard(d)}>
                  <span className="dp-cn">{d.cn}</span>
                  <span className="dp-en">{d.en}</span>
                  {state && <span className={`dp-state ${state.cls}`}>{state.text}</span>}
                  <i className="dp-arrow" aria-hidden="true"><Icon name="arrow" size={14} /></i>
                </button>
              </li>
            )
          })}
        </ol>
      )}
    </>
  )
}

export function DisciplinePage({ period, me }: { period: string | null; me: Me | null }) {
  const [data, setData] = useState<FlexibleData | null>(null)
  const [loadErr, setLoadErr] = useState('')
  /** busy＝正在生成的学科 en（单任务锁；null＝空闲） */
  const [busy, setBusy] = useState<string | null>(null)
  const [stage, setStage] = useState('')
  const [note, setNote] = useState<CardNote | null>(null)
  /** 最近生成的学科 en（本地 state，不入库——spec 原话） */
  const [recent, setRecent] = useState<string | null>(null)
  const aliveRef = useRef(true)
  useEffect(() => () => { aliveRef.current = false }, [])

  useEffect(() => {
    setLoadErr('')
    setNote(null)
    setBusy(null)
    setStage('')
    setRecent(null)
    if (!period) { setData(null); return }
    let alive = true
    setData(null)
    void getFlexible(period).then((j) => {
      if (alive) setData(j)
    }).catch((e) => {
      if (alive) setLoadErr(errorNote(e, '学科名单'))
    })
    return () => { alive = false }
  }, [period])

  const latestDisc = latestDiscOf(data)
  /* 页头链的开关照 spec 原话：reports 含 single_trend 即亮（与 meta.disc 的有无无关） */
  const hasReport = !!data?.reports.some((x) => x.intent === 'single_trend')

  function onCard(d: FlexibleDiscipline) {
    if (!period || busy) return
    const act = cardAction(me, d, latestDisc)
    if (act.kind === 'hint') {
      setNote({ en: d.en, kind: 'hint', text: '生成请找管理员' })
      return
    }
    if (act.kind === 'open') {
      window.open(reportUrl(period), '_blank', 'noopener')
      return
    }
    setNote(null)
    setBusy(d.en)
    const p = period
    void generateDisciplineReport(p, d, {
      onStage: setStage,
      onDone: () => {
        setRecent(d.en)
        setBusy(null)
        setStage('')
        /* 流完重取（Flexible.tsx 同款）：新报告进了 reports，页头「打开最近一份」随之亮起 */
        void getFlexible(p).then((j) => { if (aliveRef.current) setData(j) })
          .catch(() => { /* 重取失败不打扰：卡面已标「最近生成」 */ })
      },
      onError: (m) => {
        setNote({ en: d.en, kind: 'error', text: m })
        setBusy(null)
        setStage('')
      },
    })
  }

  const loading = !period || (!data && !loadErr)
  return (
    <DisciplineView
      period={period}
      loading={loading}
      loadErr={loadErr}
      hasReport={hasReport}
      disciplines={data?.disciplines ?? []}
      busy={busy}
      stage={stage}
      note={note}
      recent={recent}
      onCard={onCard}
    />
  )
}
