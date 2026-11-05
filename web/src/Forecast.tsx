/* 预测台（票 13；2026-11-05 按 rick 的新逻辑重做）——
   八个未入 1% 的学科各一张卡：接近度看得见，点开在卡墙下方展开五个模型的预测图
   （第一张＝AI 推荐，图例在面板顶上），点哪张图＝这次用哪个模型。
   卡上有「进报告」开关：报告正文只有两个学科的位置，默认＝接近度前二
   （分子生物学与遗传学、物理学），保存后重出，报告就按这两个学科出图。
   数字全部来自服务端产物——本页只显示，不重算。 */

import { useEffect, useMemo, useRef, useState } from 'react'
import {
  formatProvenanceTime, runForecast,
  type ForecastChoiceEntry, type ForecastMeta, type ForecastModelResult, type ForecastRun,
} from './api-forecast'
import { Info } from './Info'
import { Icon } from './icons'
import { forecastAppliedDiffs, forecastAppliedStale, resolveSubjects, shortRouteLabel } from './lib/forecast'
import { ChartFigure } from './charts/ChartFigure'
import { FORECAST_SERIES_COLORS, forecastRunOption } from './charts/options'

/** 显示格式（千分位 + 固定小数位）——只影响「怎么显示」，不参与任何计算。
    后端没给的数一律显示 —，不补零、不猜。 */
function fmtNum(v: number | null | undefined, digits = 1): string {
  if (v == null || !Number.isFinite(Number(v))) return '—'
  return Number(v).toLocaleString('zh-CN', { maximumFractionDigits: digits, minimumFractionDigits: digits })
}

/** 期次 202609 → 2026-09；空＝预测期内没过线 */
function fmtPeriod(v: number | null | undefined): string {
  return v == null ? '窗口内未过线' : `${String(v).slice(0, 4)}-${String(v).slice(4)}`
}

/** 数据期次 202609 → 2026-09（页头「数据截至」的说法；期次本身仍原样 6 位） */
function fmtMonth(v: string | null | undefined): string {
  if (!v) return '—'
  return v.length >= 6 ? `${v.slice(0, 4)}-${v.slice(4, 6)}` : v
}

/** 与报告一致的外推期数（报告母版固定 18 期；本页不再给第二个旋钮） */
const HORIZON = 18

/* ---------------------------------------------------------------- 单个模型图卡 */

function ModelCard({
  run, r, active, onPick,
}: {
  run: ForecastRun
  r: ForecastModelResult
  /** 这一张就是这次要用的那个 */
  active: boolean
  onPick: () => void
}) {
  const option = useMemo(
    () => forecastRunOption(run.history ?? [], r.forecast, run.metric_names, false),
    [run.history, r.forecast, run.metric_names])
  const recommended = r.model === run.recommended_model
  return (
    /* 整张卡就是「点这张图」的靶子：图里嵌着 ECharts 的 canvas，不能用 <button> 包块级内容，
       用 button 语义 + 键盘等效（Enter/Space）——与 ConfirmButton 同款口径。 */
    <div className={`fc-mcard${active ? ' on' : ''}`} role="button" tabIndex={0}
         aria-pressed={active} aria-label={`用 ${r.model} 预测 ${run.subject}`}
         onClick={onPick}
         onKeyDown={(e) => {
           if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); onPick() }
         }}>
      <span className="fc-mcard-h">
        <b>{r.model}</b>
        {recommended && <span className="pill signed">推荐</span>}
        {active && <span className="hint ml-auto">本次选用</span>}
      </span>
      {run.history && run.history.length > 0
        ? <ChartFigure option={option} height={168} ariaLabel={`${run.subject} · ${r.model} 预测趋势图`} />
        : <img className="fc-chart" src={r.chart} alt={`${run.subject} · ${r.model} 预测趋势图`}
               loading="lazy" decoding="async" />}
      <span className="fc-mcard-f">
        <span>滚动 MAPE {fmtNum(r.rolling_mape, 2)}%</span>
        <span>{fmtPeriod(r.first_crossing)}</span>
      </span>
    </div>
  )
}

/* ---------------------------------------------------------------- 卡墙里的一张卡 */

function SubjectCard({
  subject, prox, selected, open, onToggleOpen, onToggleSelect,
}: {
  subject: string
  prox: number | null
  selected: boolean
  open: boolean
  onToggleOpen: () => void
  onToggleSelect: () => void
}) {
  return (
    <div className={`fc-subj${open ? ' on-view' : ''}`}>
      <button type="button" className="fc-subj-main" aria-expanded={open}
              aria-label={`${subject}，${open ? '收起' : '展开'}预测图`}
              onClick={onToggleOpen}>
        <span className="fc-subj-n">{subject}</span>
        <span className="fc-subj-p">
          {prox == null ? '—' : fmtNum(prox, 2)}<small>{prox == null ? '' : '%'}</small>
        </span>
        <span className="fc-subj-bar" aria-hidden="true">
          <i style={{ transform: `scaleX(${Math.min(100, Math.max(0, prox ?? 0)) / 100})` }} />
        </span>
      </button>
      <button type="button" className={`fc-subj-tag${selected ? ' on' : ''}`}
              aria-pressed={selected} onClick={onToggleSelect}>
        {selected ? '本期报告' : '进报告'}
      </button>
    </div>
  )
}

/* ---------------------------------------------------------------- 展开的模型面板 */

function ModelPanel({
  subject, run, busy, error, mine, recommended, onPick, onReload,
}: {
  subject: string
  run: ForecastRun | null
  busy: boolean
  error: string
  mine: string
  recommended: string
  onPick: (model: string) => void
  onReload: () => void
}) {
  const effective = mine || recommended || run?.recommended_model || ''
  /* 推荐排第一（rick：第一张图就是 AI 默认推荐的那个），其余保持后端给的顺序 */
  const rec = run?.recommended_model || recommended
  const results = run
    ? [...run.results].sort((a, b) => Number(b.model === rec) - Number(a.model === rec))
    : []

  return (
    <div className="fc-open">
      {busy && (
        <p className="fc-run" role="status">
          <span className="fc-run-dot" aria-hidden="true" />
          正在跑{subject}的五个模型……
        </p>
      )}
      {!busy && error && (
        <div className="pending-box">
          {error}
          <button type="button" className="btn ml-10" onClick={onReload}>再跑一次</button>
        </div>
      )}
      {!busy && !error && run && (
        <>
          {run.errors.length > 0 && (
            <p className="hint fc-mcard-note">
              有 {run.errors.length} 个模型没跑成：{run.errors.map((x) => `${x.model}（${x.error}）`).join('；')}
            </p>
          )}
          <div className="fc-open-h">
            <b>{subject}</b>
            <span className="fc-legend">
              {run.metric_names.slice(0, 2).map((name, i) => (
                <span key={name}>
                  <i style={{ borderTopColor: FORECAST_SERIES_COLORS[i] }} />{name}
                  <i className="dash" style={{ borderTopColor: FORECAST_SERIES_COLORS[i] }} />预测值
                </span>
              ))}
            </span>
          </div>
          <div className="fc-models">
            {results.map((r) => (
              <ModelCard key={r.model} run={run} r={r}
                         active={r.model === effective}
                         onPick={() => onPick(r.model === rec ? '' : r.model)} />
            ))}
          </div>
        </>
      )}
    </div>
  )
}

/* ---------------------------------------------------------------- 页面 */

export function Forecast({
  period, meta, metaError, choice, choiceDirty,
  onChoiceChange, onSubjectsChange, onSaveChoice, onReloadChoice, onRegenerate,
  regenBusy, regenNote, canEdit, canRegenerate,
}: {
  period: string | null
  meta: ForecastMeta | null
  metaError: string
  choice: ForecastChoiceEntry | null
  choiceDirty: boolean
  onChoiceChange: (route: string, subject: string, model: string) => void
  onSubjectsChange: (subjects: string[]) => void
  onSaveChoice: () => Promise<boolean>
  onReloadChoice: () => void
  onRegenerate: () => Promise<boolean>
  /** 这一期正在出报告（按钮转「正在重出」） */
  regenBusy: boolean
  regenNote: string
  /** 2026-10-11：操作员只读——改选/保存/重出仅管理员可用（真门在后端）。 */
  canEdit: boolean
  canRegenerate: boolean
}) {
  const routes = meta?.routes ?? []
  const [route, setRoute] = useState('')
  const currentRoute = routes.some((r) => r.value === route) ? route : (routes[0]?.value ?? '')

  /* 一张卡同时只开一张：八张全开＝一屏五张图 × 8，翻页翻到天亮 */
  const [openSubject, setOpenSubject] = useState('')
  const [runs, setRuns] = useState<Record<string, ForecastRun>>({})
  const [busyKey, setBusyKey] = useState('')
  const [runErrors, setRunErrors] = useState<Record<string, string>>({})
  const loadingRef = useRef(new Set<string>())

  const subjects = useMemo(() => resolveSubjects(choice?.subjects ?? [], meta), [choice?.subjects, meta])
  const rows = meta?.subject_rows?.length
    ? meta.subject_rows
    : (meta?.subjects ?? []).map((subject) => ({ subject, prox: null as number | null }))

  const runKey = (subject: string, routeName: string) =>
    `${meta?.source_period ?? ''}|${subject}|${routeName}`

  function loadRun(subject: string, routeName: string) {
    const key = runKey(subject, routeName)
    if (!subject || !routeName || runs[key] || loadingRef.current.has(key)) return
    loadingRef.current.add(key)
    setBusyKey(key)
    setRunErrors((current) => ({ ...current, [key]: '' }))
    runForecast({ subject, task: routeName, model: 'all', horizon: HORIZON })
      .then((result) => setRuns((current) => ({ ...current, [key]: result })))
      .catch((e: { body?: { error?: string }; message?: string }) => {
        setRunErrors((current) => ({
          ...current, [key]: e.body?.error ?? e.message ?? '预测跑不出来',
        }))
      })
      .finally(() => {
        loadingRef.current.delete(key)
        setBusyKey((current) => (current === key ? '' : current))
      })
  }

  useEffect(() => {
    if (openSubject && currentRoute) loadRun(openSubject, currentRoute)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [openSubject, currentRoute, meta?.source_period])

  /* 两科名额：多选一个说清楚，不悄悄顶掉谁（2026-11-04 的教训） */
  const [pairNote, setPairNote] = useState('')
  function toggleSubject(subject: string) {
    if (!canEdit) return
    if (subjects.includes(subject)) {
      if (subjects.length <= 1) { setPairNote('本期报告要放两个学科，至少留一个。'); return }
      setPairNote('')
      onSubjectsChange(subjects.filter((s) => s !== subject))
      return
    }
    if (subjects.length >= 2) {
      setPairNote('本期报告只放两个学科——先取消一个，再选这个。')
      return
    }
    setPairNote('')
    onSubjectsChange([...subjects, subject])
  }

  const [saving, setSaving] = useState(false)
  const [regenError, setRegenError] = useState('')
  async function save() {
    setSaving(true)
    try { await onSaveChoice() } finally { setSaving(false) }
  }
  async function regenerate() {
    setRegenError('')
    const ok = await onRegenerate()
    if (!ok) setRegenError('没能开始重出——先看上面的报错，或检查服务是否在跑。')
  }

  const freshnessText = meta?.data_freshness === 'needs_check'
    ? '检测到台账或输入文件比最近一次完整运行更新，请重新处理确认——图上读到的仍是预测数据。'
    : '无法确认上游台账的最新更新是否已进入预测数据；请以「数据截至」为准。'

  const saveState = choice?.saving || saving ? '正在保存……'
    : choice?.error ? choice.error
      : !choice?.loaded ? (metaError || '正在读取本期已保存的选择……')
        : choiceDirty ? '有未保存改动'
          : '已保存'

  /* 改选已保存、但报告还没重出（2026-10-16，rick）：比「保存的选择 vs 出稿快照」 */
  const appliedStale = forecastAppliedStale(choice, meta)
  const appliedDiffs = appliedStale && choice && meta ? forecastAppliedDiffs(choice, meta) : []
  const [staleHidden, setStaleHidden] = useState(false)

  const openRow = rows.find((r) => r.subject === openSubject) ?? null
  const openKey = openSubject ? runKey(openSubject, currentRoute) : ''
  const recommendedOf = (subject: string) =>
    meta?.recommendations?.[currentRoute]?.[subject] ?? ''

  return (
    <>
      <section className="card pad-20-22-18">
        <div className="rowc12">
          <h1 className="fs-25">预测选模</h1>
          {period && <span className="pill unsigned mono">{period}</span>}
          <a className="btn ml-auto" href={period ? `/app/?period=${encodeURIComponent(period)}` : '/app/'}>
            ← 回报告
          </a>
        </div>
      </section>

      {/* 一条带：数据截至 / 路线 / 保存与重出（页面上仅此一处） */}
      <div className="fc-band" role="region" aria-label="数据期次、路线与保存">
        <span className="kv">数据截至 <b className="mono">{fmtMonth(meta?.source_period)}</b></span>
        <Info label="期次与数据说明">
          <p><b>期次 {period ?? '—'}</b>：本期配置与报告的归档期——保存写进这一期。</p>
          <p><b>数据截至 {fmtMonth(meta?.source_period)}</b>：预测图与试跑读的那批完整数据；模型版本 {meta?.model_version ?? '—'}。</p>
          <p>最近一次完整运行记录：{formatProvenanceTime(meta?.run_record_at)}；上次处理使用的文件：{meta?.processed_input?.name ?? '无法核实'}
            {meta?.processed_input?.last_modified_at ? `（文件最后修改：${formatProvenanceTime(meta.processed_input.last_modified_at)}）` : ''}。</p>
        </Info>

        {routes.length > 1 && (
          <div className="fc-seg" role="group" aria-label="预测路线">
            {routes.map((r) => (
              <button key={r.value} type="button" title={r.label}
                      aria-pressed={r.value === currentRoute}
                      className={r.value === currentRoute ? 'on' : ''}
                      onClick={() => setRoute(r.value)}>
                {shortRouteLabel(r.label)}
              </button>
            ))}
          </div>
        )}
        {routes.length > 1 && (
          <Info label="两条路线各指什么">
            {routes.map((r) => <p key={r.value}><b>{r.label}</b></p>)}
            <p>两条路线的结论不一定一致——报告里分别标注、不合成一个结论。</p>
          </Info>
        )}

        <span className={`fc-band-state${choiceDirty ? ' dirty' : ''}`} role="status"
              title={choice?.loaded && !choiceDirty && !choice.error ? `已保存${choice.by ? ` · ${choice.by}` : ''}${choice.at ? ` · ${choice.at}` : ''}` : undefined}>
          {saveState}
        </span>
        {!canEdit && <span className="hint">操作员只读</span>}
        {choice?.error && (
          <button type="button" className="btn" onClick={onReloadChoice}>重新读取</button>
        )}
        {canEdit && (
          <>
            <button className="btn" onClick={() => void save()}
                    disabled={!choice?.loaded || !choiceDirty || saving || !period}>
              {saving ? '正在保存……' : '保存选择'}
            </button>
            <button className={`btn${choiceDirty || appliedStale ? ' primary' : ''}`}
                    onClick={() => void regenerate()}
                    disabled={!canRegenerate || regenBusy || !period || !choice?.loaded}>
              {regenBusy ? '正在重出……' : '重出报告'}
            </button>
          </>
        )}
        {/* 口径与边界 ⓘ（2026-10-24 rick 工作台减负）：五条口径＋与报告的关系＋期次说明收在这里 */}
        <Info label="口径与边界" end>
          <p><b>被引路线</b>：预测总被引达到或超过预测 ESI 前1%被引阈值时，记为模型过线。</p>
          <p><b>排名路线</b>：预测国内排名不大于预测国内前1%机构数时，记为辅助条件达到。</p>
          <p><b>模型冻结</b>：SARIMA 阶数和状态空间方差只用初始 30 期确定，滚动期不重新选结构。</p>
          <p><b>多期外推</b>：正式验证范围是一步预测；页面逐期追加预测值并重新拟合，用于形成监测趋势。</p>
          <p><b>结果边界</b>：预测过线是滚动监测信号，不等同于正式入榜时间或入榜概率。</p>
          <p>
            <b>与报告的关系</b>：报告正文只有两个学科的位置——标着「本期报告」的那两科进正文，
            其余学科只进图册；所选模型跑不出来会自动退回推荐。
          </p>
          <p>
            <b>期次与数据说明</b>：{freshnessText} V1 推荐基线为 {meta?.recommendation_baseline ?? '—'}（不是预测数据期次）。
          </p>
        </Info>
      </div>

      {regenBusy && (
        <div className="fc-run mt-14" role="status">
          <span className="fc-run-dot" aria-hidden="true" />
          正在按当前选择重出报告……{regenNote ? ` ${regenNote}` : ''}
        </div>
      )}
      {regenError && <div className="pending-box mt-14">{regenError}</div>}

      {appliedStale && !staleHidden && (
        <div className="banner warn mt-14" role="status">
          <span className="ico"><Icon name="alert" size={22} /></span>
          <span>
            <b className="title">选择已保存，报告还是旧的</b>
            <span>
              {appliedDiffs.join('；')}。重出后按上面这两科与所选模型出图。
            </span>
            <span className="acts">
              <button type="button" className="btn" disabled={!canRegenerate || regenBusy}
                      onClick={() => void regenerate()}>
                现在就重出 →
              </button>
              <button type="button" className="btn" onClick={() => setStaleHidden(true)}>留在本页继续看图</button>
            </span>
          </span>
        </div>
      )}

      {metaError && <div className="pending-box mt-14">{metaError}</div>}
      {!meta && !metaError && <div className="pending-box mt-14">正在读取预测模型清单……</div>}

      {meta && !meta.available && (
        <div className="pending-box mt-14">
          最新完整预测数据尚未就绪，暂时跑不了预测：{meta.load_error}
        </div>
      )}

      {meta?.available && (
        <section className="fc-wall" aria-label="未进入 ESI 前 1% 的潜力学科">
          <div className="fc-wall-h">
            <h2>未入 ESI 前 1%</h2>
            <span className="n">{rows.length}</span>
          </div>
          {pairNote && <p className="hint fc-pair-note" role="status">{pairNote}</p>}
          <div className="fc-cards">
            {rows.map((row) => (
              <SubjectCard
                key={row.subject}
                subject={row.subject}
                prox={row.prox}
                selected={subjects.includes(row.subject)}
                open={openSubject === row.subject}
                onToggleOpen={() => setOpenSubject((current) => (current === row.subject ? '' : row.subject))}
                onToggleSelect={() => toggleSubject(row.subject)}
              />
            ))}
          </div>
          {openRow && (
            <ModelPanel
              subject={openRow.subject}
              run={runs[openKey] ?? null}
              busy={busyKey === openKey}
              error={runErrors[openKey] ?? ''}
              mine={choice?.choice?.[currentRoute]?.[openRow.subject] ?? ''}
              recommended={recommendedOf(openRow.subject)}
              onPick={(model) => canEdit && onChoiceChange(currentRoute, openRow.subject, model)}
              onReload={() => loadRun(openRow.subject, currentRoute)}
            />
          )}
        </section>
      )}
    </>
  )
}
