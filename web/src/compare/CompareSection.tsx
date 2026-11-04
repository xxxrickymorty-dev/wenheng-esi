/* 跨校单学科对比（2026-11-04 静态稿 rick「过」）——分析台的一个区：
    选一个学科 × 勾任意几所高校（默认一个都不勾，不设默认名单）→ 流式生成对比稿。
    版式与交互照《单学科分析台-跨校对比-静态稿（20261104）》四态：
    ① 选科＋选校抽屉 ② 已勾（含「无数据」徽标——徽标可勾入，不拦死：
      「证明不在榜」本身就是馆员要的结论）③ 流式生成中 ④ 稿已生成（缩略预览）。
    术语照 GLOSSARY：区题「跨校单学科对比」；按钮「生成分析稿」；
    进度三词 未开始 / 进行中 / 已完成。

    数据口（全部既有/契约冻结）：
    · 学科名单：getFlexible().disciplines（en 是要传的英文名，cn 上屏）——与分析台
      现有学科选择器同一数据源；
    · 学校名单：getMonitorSchools(field=学科英文名)——items[].in_field 是
      2026-11-04 契约新字段，**优雅降级**：接口没这字段或拉取失败时徽标不显示
      （不误标），勾选不受影响；换学科先摘旧徽标（旧学科的 in_field 不能带到新学科）；
    · 生成：runFlexibleStream { intent:'school_compare', disc, peers }——NDJSON
      status→plan→section×N→done|error|stopped；ping 心跳不渲染，只喂看门狗
      （90s 无任何事件判连接中断，与学科报告区同一口径）。
      节渲染照灵活报告（fx-md）、停止键照问文衡（status 事件带 run 令牌，
      stopFlexible 喊停，终态 stopped 从原流回来）、成稿照灵活报告流完重取
      getFlexible(period,'school_compare') 上屏——前端不造数，只摆后端正文。
      done 事件的 backend 也带回：'rule'＝规则稿时代的旧产物，缩略上一枚
      「规则稿」小标（缺省不标）。

    🔴 本区没有一个是前端算的数字：对比数据全在后端正文里，界面上只有
    学校名单、勾选状态与流事件文案。

    测试无 jsdom（与全站同口径，照 DisciplineSection.test.tsx 的缝）：
    展示件 CompareView、进度推演 sectionStates、生成控制器 runCompare 都导出。 */

import { useEffect, useRef, useState } from 'react'
import {
  getFlexible, runFlexibleStream, stopFlexible, reportBackend,
  type FlexStreamEvent, type FlexibleData,
} from '../api-flexible'
import { getMonitorSchools, type MonitorSchool } from '../api-monitor'
import type { Me } from '../api'
import { errorNote } from '../lib/status'
import { humanBody } from '../Flexible'
import { Icon } from '../icons'
import './compare.css'

/** 单学科报告的公开读路由——灵活报告一个意图一个目录，跨校对比同款。 */
export function compareReportUrl(period: string): string {
  return `/p/${encodeURIComponent(period)}/flexible/school_compare/report.html`
}

/** 生成按钮的门槛：至少勾 2 所（spec 原话「至少勾 2 所」）。 */
export const MIN_PEERS = 2

/** 生成中的流态（与灵活报告窗格同构；null＝空闲）。 */
export type CompareStream = {
  title: string
  outline: string[]
  sections: { title: string; html: string }[]
}

/** 稿位缩略（后端成稿正文；title 取 plan/done 的报告题）。
    backend＝这份稿的出稿后端（'rule'＝规则稿 → 缩略上一枚小标；
    缺省不标）。 */
export type CompareDraft = { title: string; html: string; backend?: string }

/** 进度表每节的状态（GLOSSARY 任务状态三词）。 */
export type ProgState = 'done' | 'run' | 'idle'

/** 进度推演（纯逻辑）：outline 第 i 节——写完的节数盖到哪，哪节「进行中」。 */
export function sectionStates(outline: string[], nSections: number): ProgState[] {
  return outline.map((_, i) => (i < nSections ? 'done' : i === nSections ? 'run' : 'idle'))
}

/** 停止键/错误的那句话（照问文衡口径：停了就是没出稿）。 */
export const STOPPED_NOTE = '停了——这次没出稿。'

/** 生成控制器（「生成分析稿」按钮走的就是这份代码）：
    进度逐事件回传，done 回传后由接线层重取成稿；error 事件或请求失败回传一句
    （errorNote 口径）；连接中断（看门狗 90s 无事件 / 流终止无终态事件）回传 onInterrupted。 */
export async function runCompare(
  period: string,
  disc: string,
  peers: string[],
  h: { onRun: (run: string) => void
       onPlan: (title: string, outline: string[]) => void
       onSection: (title: string, html: string) => void
       onDone: (backend: string) => void
       onError: (message: string) => void
       onInterrupted: () => void },
): Promise<void> {
  let doneSeen = false
  let failed = false
  let interrupted = false
  const ctrl = new AbortController()
  /* 看门狗（与学科报告区同一口径）：收到任何事件（含 ping）都重置计时；
     90s 全静默只可能是连接断了，不是「写得慢」。 */
  const WATCHDOG_MS = 90_000
  let watchdog: ReturnType<typeof setTimeout> | null = null
  const arm = () => {
    if (watchdog !== null) clearTimeout(watchdog)
    watchdog = setTimeout(() => { interrupted = true; ctrl.abort() }, WATCHDOG_MS)
  }
  arm()
  try {
    await runFlexibleStream(period, { intent: 'school_compare', disc, peers },
      (ev: FlexStreamEvent) => {
        arm()                                    // 任何事件都算「链路活着」
        if (ev.event === 'ping') return          // 心跳只喂看门狗，不是进度
        if (ev.event === 'status') { h.onRun(ev.run ?? ''); return }
        if (ev.event === 'plan') { h.onPlan(ev.title, ev.outline); return }
        if (ev.event === 'section') { h.onSection(ev.title, ev.html); return }
        if (ev.event === 'done') {
          doneSeen = true
          h.onDone(typeof ev.backend === 'string' ? ev.backend : '')
          return
        }
        if (ev.event === 'stopped') { failed = true; h.onError(STOPPED_NOTE); return }
        if (ev.event === 'error') { failed = true; h.onError(ev.message); return }
      }, { signal: ctrl.signal })
    if (!doneSeen && !failed) h.onInterrupted()  // 流终止但没等到终态事件＝连接中断
  } catch (e) {
    if (interrupted) h.onInterrupted()           // 看门狗掐断的那次 abort
    else h.onError(errorNote(e, '生成跨校对比稿'))
  } finally {
    if (watchdog !== null) clearTimeout(watchdog)
  }
}

/** 进度表（静态稿 ③：节名＋三态，状态词已含信息，不再另配图标）。 */
function ProgList({ outline, sections }: { outline: string[]; sections: number }) {
  const states = sectionStates(outline, sections)
  return (
    <ul className="cp-prog">
      {outline.map((t, i) => (
        <li key={t}>
          <span className="cp-secnm">{t}</span>
          <span className={`cp-st ${states[i]}`}>
            {states[i] === 'done' ? '已完成' : states[i] === 'run' ? '进行中' : '未开始'}
          </span>
        </li>
      ))}
    </ul>
  )
}

/** 展示件（测试从这里进：无 effect、无请求）。
    schools 为 null＝名单还没读到（抽屉画占位行，不闪错误）。 */
export function CompareView(props: {
  period: string
  disciplines: FlexibleData['disciplines']
  disc: string
  onDisc: (en: string) => void
  schools: MonitorSchool[] | null
  schoolsErr: string
  picked: string[]
  onToggle: (cn: string) => void
  stream: CompareStream | null
  onStop: () => void
  draft: CompareDraft | null
  hasReport: boolean
  note: string | null
  onGenerate: () => void
}) {
  const { period, disciplines, disc, onDisc, schools, schoolsErr, picked, onToggle,
          stream, onStop, draft, hasReport, note, onGenerate } = props
  const generating = !!stream
  const nWritten = stream?.sections.length ?? 0
  const writing = stream && stream.outline[nWritten]
  return (
    <section aria-labelledby="cp-sec-h">
      <header className="cp-head">
        <h2 className="an-sec" id="cp-sec-h">跨校单学科对比</h2>
        {disciplines.length > 0 && (
          <label className="an-sel cp-sel">
            <select value={disc} disabled={generating} aria-label="对比学科"
                    onChange={(e) => onDisc(e.target.value)}>
              {!disc && <option value="">选学科</option>}
              {disciplines.map((d) => <option key={d.en} value={d.en}>{d.cn}</option>)}
            </select>
            <i aria-hidden="true" />
          </label>
        )}
        {hasReport && !generating && (
          <a className="cp-open" href={compareReportUrl(period)} target="_blank" rel="noopener">
            打开报告 ↗
          </a>
        )}
      </header>

      <div className="cp-work">
        {/* 左：选校抽屉（② 生成中换进度表） */}
        <section className="cp-picker" aria-label={generating ? '正在生成' : '对比学校'}>
          <div className="cp-pick-h">
            <h3>{generating ? '正在生成' : '对比学校'}</h3>
            <span className="cp-cnt">
              {generating ? '进度实时更新' : <>已选 <b>{picked.length}</b> 所</>}
            </span>
          </div>

          {generating ? (
            stream!.outline.length ? (
              <ProgList outline={stream!.outline} sections={nWritten} />
            ) : (
              <p className="cp-plan">正在规划这个题怎么拆</p>
            )
          ) : schoolsErr && !schools ? (
            <p className="cp-schools-err" role="alert">{schoolsErr}</p>
          ) : !schools ? (
            <p className="cp-plan">正在读学校名单……</p>
          ) : (
            <div className="cp-slist">
              {schools.map((s) => {
                const on = picked.includes(s.cn)
                /* 徽标只在后端明确说 in_field=false 时出现；
                   字段缺省 / 名单拉取失败一律不显示（不误标）。 */
                const nodata = s.in_field === false
                return (
                  <label className={`cp-srow${nodata ? ' nodata' : ''}`} key={s.cn}>
                    <input type="checkbox" checked={on} onChange={() => onToggle(s.cn)} />
                    <span className="cp-box" aria-hidden="true">
                      <Icon name="check" size={12} />
                    </span>
                    <span className="cp-nm">{s.cn}</span>
                    {nodata && (
                      <span className="cp-badge">
                        <Icon name="slash" size={11} />无数据
                      </span>
                    )}
                  </label>
                )
              })}
            </div>
          )}

          <div className="cp-pick-f">
            {generating ? (
              <button type="button" className="cp-stop" onClick={onStop}>停止</button>
            ) : (
              <>
                <button type="button" className="cp-go" disabled={picked.length < MIN_PEERS}
                        onClick={onGenerate}>
                  生成分析稿
                </button>
                {picked.length < MIN_PEERS && <span className="cp-need">至少勾 2 所</span>}
              </>
            )}
          </div>

          {!generating && picked.length > 0 && (
            <div className="cp-chips">
              {picked.map((cn) => {
                const nodata = schools?.find((s) => s.cn === cn)?.in_field === false
                return (
                  <button type="button" className={`cp-chip${nodata ? ' nodata' : ''}`} key={cn}
                          aria-label={`移除 ${cn}`} onClick={() => onToggle(cn)}>
                    {cn} <span className="cp-x" aria-hidden="true">✕</span>
                  </button>
                )
              })}
            </div>
          )}

          {note && <p className="cp-note" role="alert">{note}</p>}
        </section>

        {/* 右：稿位（空态 / 流式 / 成稿缩略） */}
        <section className="cp-stage" aria-label="稿位">
          {stream ? (
            <>
              <div className="fx-status" aria-live="polite">
                <span className="dot run" />
                <span>{writing ? `正在写「${writing}」` : '正在规划这个题怎么拆'}</span>
              </div>
              {stream.sections.map((s, i) => (
                <div key={i}>
                  {s.title && <h3 className="fx-sec-h">{s.title}</h3>}
                  <div className="fx-md" dangerouslySetInnerHTML={{ __html: humanBody(s.html) }} />
                </div>
              ))}
              {writing && (
                <div className="cp-skel" aria-hidden="true"><i /><i /><i /></div>
              )}
            </>
          ) : draft ? (
            <article className="cp-report" aria-label="报告缩略">
              <div className="cp-spine" aria-hidden="true">
                <span className="cp-vt">{draft.title}</span>
                <span className="cp-vp">{period}</span>
              </div>
              <div className="cp-rbody">
                {/* 规则稿时代的旧产物：一枚灰标诚实标注；backend 缺省不标 */}
                {draft.backend === 'rule' && (
                  <span className="rule-tag cp-ruletag"
                        title="本稿由规则版式生成，可在配置模型后重新生成">规则稿</span>
                )}
                <div className="fx-md" dangerouslySetInnerHTML={{ __html: humanBody(draft.html) }} />
              </div>
            </article>
          ) : (
            <p className="cp-empty"><b>勾选对比学校</b>生成后稿在此预览。</p>
          )}
        </section>
      </div>
    </section>
  )
}

/** 分析台里的「跨校单学科对比」区（与学科报告区互不牵连，各自取数）。 */
export function CompareSection({ period, me }: { period: string; me: Me | null }) {
  /** 学科名单与最近报告（getFlexible 一份顶两用） */
  const [meta, setMeta] = useState<FlexibleData | null>(null)
  const [loadErr, setLoadErr] = useState('')
  /** 对比学科（en；名单到了取第一个，不设默认学校） */
  const [disc, setDisc] = useState('')
  /** 学校名单；null＝还没读到 */
  const [schools, setSchools] = useState<MonitorSchool[] | null>(null)
  const [schoolsErr, setSchoolsErr] = useState('')
  /** 勾中的校名（cn；默认一个不勾） */
  const [picked, setPicked] = useState<string[]>([])
  const [stream, setStream] = useState<CompareStream | null>(null)
  const [draft, setDraft] = useState<CompareDraft | null>(null)
  const [hasReport, setHasReport] = useState(false)
  const [note, setNote] = useState<string | null>(null)
  const aliveRef = useRef(true)
  const runRef = useRef('')
  const streamRef = useRef<CompareStream | null>(null)
  const schoolsRef = useRef<MonitorSchool[] | null>(null)
  useEffect(() => { streamRef.current = stream }, [stream])
  useEffect(() => { schoolsRef.current = schools }, [schools])
  useEffect(() => () => { aliveRef.current = false }, [])

  /* 期次换档：名单、勾选、生成中与稿位全部归零——期次隔离照 §十一
     （effect 卸载置亡旗，迟到响应不落位）。 */
  useEffect(() => {
    setMeta(null); setLoadErr(''); setDisc(''); setSchools(null); setSchoolsErr('')
    setPicked([]); setStream(null); setDraft(null); setHasReport(false); setNote(null)
    runRef.current = ''
    let alive = true
    void getFlexible(period).then(async (j) => {
      if (!alive) return
      setMeta(j)
      setDisc((cur) => cur || j.disciplines[0]?.en || '')
      /* 最近一份跨校对比稿还在：稿位直接摆缩略（回看不丢） */
      if (j.reports.some((x) => x.intent === 'school_compare')) {
        setHasReport(true)
        try {
          const jj = await getFlexible(period, 'school_compare')
          if (!alive) return
          const r = jj.reports.find((x) => x.intent === 'school_compare')
        setDraft({ title: r?.title || '跨校单学科对比', html: jj.body_html,
                   backend: r ? reportBackend(r) : '' })
        } catch { /* 有名无正文：缩略不出，「打开报告」链还在 */ }
      }
    }).catch((e) => {
      if (alive) setLoadErr(errorNote(e, '学科名单'))
    })
    return () => { alive = false }
  }, [period])

  /* 学科换档：重取学校名单（带 field 徽标位）。换档先摘旧徽标——
     旧学科的 in_field 带到新学科就是误标；拉取失败时名单在手就只当徽标没到。 */
  useEffect(() => {
    if (!disc) return
    let alive = true
    setSchools((cur) => cur ? cur.map((s) => ({ ...s, in_field: undefined })) : cur)
    setSchoolsErr('')
    void getMonitorSchools(disc).then((j) => {
      if (alive) setSchools(j.schools)
    }).catch((e) => {
      if (!alive) return
      if (!schoolsRef.current) setSchoolsErr(errorNote(e, '学校名单'))
      /* 名单在手：只是徽标数据没到——不显示徽标（不误标），勾选照常 */
    })
    return () => { alive = false }
  }, [disc])

  function onToggle(cn: string) {
    setPicked((cur) => cur.includes(cn) ? cur.filter((x) => x !== cn) : [...cur, cn])
  }

  function onStop() {
    const run = runRef.current
    if (!run) return
    void stopFlexible(period, run).catch(() => { /* 喊停失败不打扰：流自己会走到终态 */ })
  }

  function onGenerate() {
    if (stream || picked.length < MIN_PEERS || !disc) return
    /* 生成口后端 admin-only（与学科报告区同门）：非 admin 点了给一句，不禁用整区 */
    if (me?.role !== 'admin') { setNote('生成请找管理员'); return }
    setNote(null)
    setDraft(null)
    setStream({ title: '', outline: [], sections: [] })
    let doneSeen = false
    let doneBackend = ''
    void runCompare(period, disc, picked, {
      onRun: (run) => { runRef.current = run },
      onPlan: (title, outline) =>
        setStream((s) => s ? { ...s, title, outline } : s),
      onSection: (title, html) =>
        setStream((s) => s ? { ...s, sections: [...s.sections, { title, html }] } : s),
      onDone: (backend) => { doneSeen = true; doneBackend = backend },
      onError: (m) => { if (aliveRef.current) { setNote(m); setStream(null) } },
      onInterrupted: () => {
        if (aliveRef.current) {
          setNote('连接中断——报告可能已在后台完成，点「打开报告」查看')
          setStream(null)
        }
      },
    }).then(async () => {
      if (!aliveRef.current || !doneSeen) return
      /* 流完重取成稿（照灵活报告：正文与后端同源）；取不到就留在流式稿＋一句 */
      try {
        const jj = await getFlexible(period, 'school_compare')
        if (!aliveRef.current) return
        const r = jj.reports.find((x) => x.intent === 'school_compare')
        setDraft({ title: r?.title || streamRef.current?.title || '跨校单学科对比',
                   html: jj.body_html,
                   backend: (r ? reportBackend(r) : '') || doneBackend })
        setHasReport(true)
        setStream(null)
        setNote(null)
      } catch (e) {
        if (aliveRef.current) setNote(errorNote(e, '报告缩略'))
      }
    })
  }

  if (loadErr) {
    return (
      <section aria-labelledby="cp-sec-h">
        <header className="cp-head">
          <h2 className="an-sec" id="cp-sec-h">跨校单学科对比</h2>
        </header>
        <p className="cp-load-err" role="alert">{loadErr}</p>
      </section>
    )
  }

  return (
    <CompareView
      period={period}
      disciplines={meta?.disciplines ?? []}
      disc={disc}
      onDisc={setDisc}
      schools={schools}
      schoolsErr={schoolsErr}
      picked={picked}
      onToggle={onToggle}
      stream={stream}
      onStop={onStop}
      draft={draft}
      hasReport={hasReport}
      note={note}
      onGenerate={onGenerate}
    />
  )
}
