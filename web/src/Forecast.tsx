/* 预测台——潜力学科模型现状与试跑验证。
   学科、路线和模型说明来自服务端；模型选择与生成台共用当前任务期次。
   学科板和试跑仍读取最新完整预测数据；本页只显示结果，不重新计算。 */

import { useEffect, useRef, useState } from 'react'
import {
  formatProvenanceTime, getForecastBoard, runForecast,
  type ForecastBoard, type ForecastChoiceEntry, type ForecastMeta, type ForecastModelResult, type ForecastRun,
} from './api5'
import type { Period } from './api'
import { Icon } from './icons'
import { MODEL_DESC } from './Workbench'

/** 显示格式（千分位 + 固定小数位）——只影响「怎么显示」，不参与任何计算；
    位数沿用老站预测页。后端没给的数一律显示 —，不补零、不猜。 */
function fmtNum(v: number | null | undefined, digits = 1): string {
  if (v == null || !Number.isFinite(Number(v))) return '—'
  return Number(v).toLocaleString('zh-CN', { maximumFractionDigits: digits, minimumFractionDigits: digits })
}

/** 期次 202609 → 2026-09；空＝预测期内没过线 */
function fmtPeriod(v: number | null | undefined): string {
  return v == null ? '预测期内未过线' : `${String(v).slice(0, 4)}-${String(v).slice(4)}`
}

/** 期数档位：默认 18 与报告一致；24 是模型包的硬上限（要更远得升模型版本） */
const HORIZONS = [12, 18, 24]

/* ---------------------------------------------------------------- 试跑结果 */

/** 逐期预测值表——单模型详版与五模型图卡里的折叠块共用。 */
function ForecastTable({ run, r }: { run: ForecastRun; r: ForecastModelResult }) {
  return (
    <div className="tablewrap">
      <table className="fc-tbl">
        <thead>
          <tr>
            <th>期次</th>
            <th style={{ textAlign: 'right' }}>{run.metric_names[0]}</th>
            <th style={{ textAlign: 'right' }}>{run.metric_names[1]}</th>
            <th style={{ textAlign: 'right' }}>接近度</th>
          </tr>
        </thead>
        <tbody>
          {r.forecast.map((p) => (
            <tr key={p.period} className={p.crossed ? 'crossed' : ''}>
              <td>{fmtPeriod(p.period)}</td>
              <td className="num">{fmtNum(p.metric1)}</td>
              <td className="num">{fmtNum(p.metric2)}</td>
              <td className="num">{fmtNum(p.proximity, 2)}%</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}

function ModelCard({ run, r }: { run: ForecastRun; r: ForecastModelResult }) {
  const isRec = r.model === run.recommended_model
  const isBest = run.compared_all && r.model === run.comparison_best_model
  return (
    <article className="fc-model">
      <div className="fc-model-h">
        <h3>{r.model}</h3>
        {isRec && <span className="pill signed">V1 基线推荐</span>}
        {isBest && <span className="pill stale">本次误差最低</span>}
        <span className="hint" style={{ marginLeft: 'auto' }}>数据来源 {run.source_period} 期派生产物</span>
      </div>

      <div className="fc-metrics">
        <div><b>{fmtNum(r.rolling_mape, 2)}%</b><span>综合滚动 MAPE（验收线 &lt;5%）</span></div>
        <div><b>{fmtNum(r.fit_mape, 2)}%</b><span>历史拟合 MAPE</span></div>
        <div><b>{fmtPeriod(r.first_crossing)}</b><span>首次模型过线</span></div>
        <div><b>{r.status === 'PASS' ? '通过' : '需复核'}</b><span>V1 运行状态</span></div>
      </div>

      {r.metric_mapes && (
        <p className="fc-break">
          分项滚动误差：
          {Object.entries(r.metric_mapes).map(([name, m]) => `${name} ${fmtNum(m.rolling, 2)}%`).join(' · ')}
        </p>
      )}

      <img className="fc-chart" src={r.chart} alt={`${run.subject} · ${r.model} 预测趋势图`} />

      <ForecastTable run={run} r={r} />
    </article>
  )
}

/** 五模型预测图（rick 2026-09-28）：两列图卡，卡上直接改选；
    选择写进 02「本期用哪个模型」的同一份状态，保存仍在那里。 */
function ModelGallery({
  run, choice, recommendations, onChoiceChange,
}: {
  run: ForecastRun
  choice: ForecastChoiceEntry | null
  recommendations?: Record<string, Record<string, string>>
  onChoiceChange: (route: string, subject: string, model: string) => void
}) {
  const mine = choice?.choice?.[run.task]?.[run.subject] ?? ''
  const rec = recommendations?.[run.task]?.[run.subject] ?? run.recommended_model
  const effective = mine || rec
  const pickable = choice?.loaded && !choice?.saving

  return (
    <>
      <p className="hint" style={{ marginTop: 12 }} role="status">
        当前选用：<b>{effective || '未定'}</b>
        {mine ? `（已从 V1 推荐「${rec}」改选）` : '（未改，跟随 V1 推荐）'}
        {mine && <button type="button" className="btn fc-gal-reset" disabled={!pickable}
                          onClick={() => onChoiceChange(run.task, run.subject, '')}>恢复 V1 推荐</button>}
        <span className="hint"> · 改选后到 02 保存</span>
      </p>

      <div className="fc-gal">
        {run.results.map((r) => {
          const isRec = r.model === run.recommended_model
          const isBest = r.model === run.comparison_best_model
          const isMine = r.model === mine
          const isActive = r.model === effective
          return (
            <article className="fc-model" key={r.model}>
              <div className="fc-model-h">
                <h3>{r.model}</h3>
                {isRec && <span className="pill signed">V1 基线推荐</span>}
                {isBest && <span className="pill stale">本次误差最低</span>}
                {isMine && <span className="pill manual">当前选用</span>}
                {!mine && isRec && <span className="pill">正在使用</span>}
                <span className="hint" style={{ marginLeft: 'auto' }}>{run.source_period} 期数据</span>
              </div>

              <div className="fc-metrics">
                <div><b>{fmtNum(r.rolling_mape, 2)}%</b><span>综合滚动 MAPE</span></div>
                <div><b>{fmtNum(r.fit_mape, 2)}%</b><span>历史拟合 MAPE</span></div>
                <div><b>{fmtPeriod(r.first_crossing)}</b><span>首次模型过线</span></div>
                <div><b>{r.status === 'PASS' ? '通过' : '需复核'}</b><span>V1 运行状态</span></div>
              </div>

              {r.metric_mapes && (
                <p className="fc-break">
                  分项滚动：
                  {Object.entries(r.metric_mapes).map(([name, m]) => `${name} ${fmtNum(m.rolling, 2)}%`).join(' · ')}
                </p>
              )}

              <img className="fc-chart" src={r.chart} alt={`${run.subject} · ${r.model} 预测趋势图`} />

              <div className="fc-actions">
                {isActive
                  ? <button type="button" className="btn" disabled>{isMine ? '当前选用' : '正在使用（V1 推荐）'}</button>
                  : <button type="button" className="btn primary" disabled={!pickable}
                            onClick={() => onChoiceChange(run.task, run.subject, r.model)}>选用此模型</button>}
              </div>

              <details className="fc-more">
                <summary>逐期预测值（{r.forecast.length} 期）</summary>
                <ForecastTable run={run} r={r} />
              </details>
            </article>
          )
        })}
      </div>
    </>
  )
}

function Trial({ meta, choice, onChoiceChange }: {
  meta: ForecastMeta
  choice: ForecastChoiceEntry | null
  onChoiceChange: (route: string, subject: string, model: string) => void
}) {
  const [subject, setSubject] = useState(meta.subjects[0] ?? '')
  const [task, setTask] = useState(meta.routes[0]?.value ?? '')
  const [model, setModel] = useState('all')
  const [horizon, setHorizon] = useState(18)
  const [busy, setBusy] = useState(false)
  const [data, setData] = useState<ForecastRun | null>(null)
  const [err, setErr] = useState('')
  const cache = useRef(new Map<string, ForecastRun>())
  const selectedSubject = meta.subjects.includes(subject) ? subject : meta.subjects[0] ?? ''
  const selectedTask = meta.routes.some((route) => route.value === task)
    ? task
    : meta.routes[0]?.value ?? ''
  const runKey = `${selectedSubject}|${selectedTask}|${model}|${horizon}`

  // 参数一变先看有没有跑过：有缓存就立刻显示，没有就清空等用户点运行。
  useEffect(() => {
    const cached = cache.current.get(runKey)
    setData(cached ?? null)
    setErr('')
  }, [runKey])

  async function onRun() {
    setBusy(true)
    setErr('')
    try {
      const result = await runForecast({ subject: selectedSubject, task: selectedTask, model, horizon })
      cache.current.set(runKey, result)
      setData(result)
    } catch (e) {
      const h = e as { body?: { error?: string; hint?: string }; message?: string }
      setData(null)
      setErr(h.body?.error ?? h.message ?? '运行失败')
    } finally {
      setBusy(false)
    }
  }

  return (
    <section className="card" style={{ marginTop: 18, padding: '20px 22px' }}>
      <h2 style={{ fontSize: 19, display: 'flex', alignItems: 'center', gap: 10 }}>
        <span className="fc-no">03</span>全模型预测图（选前先看）
      </h2>
      <p className="fc-lead" style={{ fontSize: 15.5 }}>
        选学科和路线，跑一次五模型：每个候选模型的预测图、滚动误差与首次过线都摆出来，
        图上可直接改选——改完到 02 保存。单模型也能单独跑。
        「V1 基线推荐」是各学科冻结下来的那一个；「五模型全部运行比较」只做横向比较，改选不改写推荐。
      </p>

      <div className="fc-form">
        <label>潜力学科
          <select value={selectedSubject} onChange={(e) => setSubject(e.target.value)}>
            {meta.subjects.map((s) => <option key={s} value={s}>{s}</option>)}
          </select>
        </label>
        <label>预测路线
          <select value={selectedTask} onChange={(e) => setTask(e.target.value)}>
            {meta.routes.map((r) => <option key={r.value} value={r.value}>{r.label}</option>)}
          </select>
        </label>
        <label>模型
          <select value={model} onChange={(e) => setModel(e.target.value)}>
            {meta.models.map((m) => <option key={m.value} value={m.value}>{m.label}</option>)}
          </select>
        </label>
        <label>预测期数
          <select value={horizon} onChange={(e) => setHorizon(Number(e.target.value))}>
            {HORIZONS.map((h) => <option key={h} value={h}>{h} 期{h === 18 ? '（与报告一致）' : h === 24 ? '（模型上限）' : ''}</option>)}
          </select>
        </label>
        <button className="btn primary" onClick={onRun} disabled={busy || !selectedSubject || !selectedTask}>
          {busy ? '运行中……' : '运行预测'}
        </button>
      </div>

      {err && <div className="pending-box" style={{ marginTop: 14 }}>{err}</div>}
      {busy && (
        <p className="hint" style={{ marginTop: 14 }}>
          {model === 'all' ? '正在跑五模型滚动回测与预测，需要一点时间……' : '正在跑模型，请稍候……'}
        </p>
      )}
      {!busy && !data && !err && (
        <p className="hint" style={{ marginTop: 14 }}>
          还没有跑过这组参数——点「运行预测」出图；同一组参数再切回来不会重跑。
        </p>
      )}

      {data && (
        <>
          <div className="fc-readouts">
            <div><div className="v">{data.subject}</div><div className="k">预测学科</div></div>
            <div><div className="v">{data.model_version}</div><div className="k">模型版本</div></div>
            <div><div className="v">{data.history_periods}</div><div className="k">有效历史期数</div></div>
            <div><div className="v">{fmtPeriod(data.data_end)}</div><div className="k">数据截止期</div></div>
          </div>

          {data.errors.length > 0 && (
            <div className="pending-box" style={{ marginTop: 12 }}>
              有 {data.errors.length} 个模型没跑成：{data.errors.map((x) => `${x.model}（${x.error}）`).join('；')}
            </div>
          )}

          {data.compared_all
            ? <ModelGallery run={data} choice={choice} recommendations={meta.recommendations}
                            onChoiceChange={onChoiceChange} />
            : data.results.map((r) => <ModelCard key={r.model} run={data} r={r} />)}

          <p className="hint" style={{ marginTop: 12 }}>{data.notice}</p>
        </>
      )}
    </section>
  )
}

/* ---------------------------------------------------------------- 学科板（现状与研判） */

/** 期次 2027-01 → 2027-01（原样）；空串＝窗口内未过线 */
const fmtT = (v: string) => (v ? v : '窗口内未过线')

function Board({ meta }: { meta: ForecastMeta }) {
  const [d, setD] = useState<ForecastBoard | null>(null)
  const [note, setNote] = useState<string | null>(null)
  const [route, setRoute] = useState(meta.routes[0]?.value ?? '')

  useEffect(() => {
    let alive = true
    ;(async () => {
      try {
        const b = await getForecastBoard()
        if (!alive) return
        setD(b)
        if (!b.routes?.[route] && Object.keys(b.routes ?? {}).length) setRoute(Object.keys(b.routes)[0])
      } catch {
        if (alive) setNote('学科板暂时读不到（这份选模表还没生成）。')
      }
    })()
    return () => { alive = false }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [meta.source_period])

  const rows = (d?.routes ?? {})[route] ?? []

  return (
    <section className="card" style={{ marginTop: 18, padding: '20px 22px' }}>
      <h2 style={{ fontSize: 19, display: 'flex', alignItems: 'center', gap: 10, flexWrap: 'wrap' }}>
        <span className="fc-no">01</span>学科板 · 现状与研判
        <span className="hint">
          选模与过线（源：{d?.period ?? '—'} · 窗口 {d?.window ?? '—'}）
        </span>
      </h2>
      <p className="fc-lead" style={{ fontSize: 15.5 }}>
        8 个潜力学科两条路线一眼看完：接近度（离门槛还有多远）、预计过线期、用的模型与它的滚动误差。
        「接近度」是百分数点值；过线是滚动监测信号，不等同于正式入榜时间。
        <br />
        这一板的模型是预测阶段的选模记录（逐期滚动比较的结果），<b>不是</b>报告最终采用的模型——
        报告用哪套，看下面 02 的「V1 推荐」与你的选择。
      </p>

      <div className="fc-tabs" role="group" aria-label="预测路线">
        {meta.routes.map((r) => (
          <button key={r.value} type="button" aria-pressed={r.value === route}
                  className={r.value === route ? 'on' : ''} onClick={() => setRoute(r.value)}>
            {r.label}
          </button>
        ))}
      </div>

      {note && <div className="pending-box" style={{ marginTop: 12 }}>{note}</div>}

      {!!rows.length && (
        <div className="bd-grid">
          {rows.map((r) => (
            <div className="bd-card" key={r.subject}>
              <div className="bd-top">
                <b>{r.subject}</b>
                <span className="bd-prox">{r.prox == null ? '—' : `${r.prox}%`}</span>
              </div>
              <span className="bd-bar" aria-hidden="true">
                <i style={{ width: `${Math.min(100, Math.max(0, r.prox ?? 0))}%` }} />
              </span>
              <div className="bd-meta">
                <span>模型 {r.model}</span>
                <span>滚动 MAPE {r.rolling_mape == null ? '—' : `${r.rolling_mape}%`}</span>
              </div>
              <div className={`bd-cross${r.t1 ? ' on' : ''}`}>
                {r.t1 ? `预计过线 ${fmtT(r.t1)}${r.t3 && r.t3 !== r.t1 ? `（最晚 ${r.t3}）` : ''}` : fmtT(r.t1)}
              </div>
            </div>
          ))}
        </div>
      )}
      {d?.note && <p className="hint" style={{ marginTop: 10 }}>{d.note}</p>}
    </section>
  )
}

/* ---------------------------------------------------------------- 逐科选择 */

function PickTable({
  meta, period, periods, actualOutputPeriod, choice, dirty, metaError,
  onPickPeriod, onChange, onSave, onReload,
}: {
  meta: ForecastMeta
  period: string | null
  periods: Period[]
  actualOutputPeriod: string | null
  choice: ForecastChoiceEntry | null
  dirty: boolean
  metaError: string
  onPickPeriod: (period: string) => void
  onChange: (route: string, subject: string, model: string) => void
  onSave: () => void
  onReload: () => void
}) {
  const [route, setRoute] = useState(meta.routes[0]?.value ?? '')
  const models = meta.models.filter((m) => m.value !== 'recommended' && m.value !== 'all')
  const currentRoute = meta.routes.some((item) => item.value === route) ? route : (meta.routes[0]?.value ?? '')
  const recOf = (s: string) => meta.recommendations?.[currentRoute]?.[s] ?? ''
  const source = meta.upstream_workbook
  const freshnessText = meta.data_freshness === 'needs_check'
    ? '检测到台账或处理输入文件的修改时间晚于最近一次完整运行记录；无法确认这次更新是否已进入预测数据，请重新处理确认。'
    : '现有记录无法确认上游台账是否已进入预测所用数据。请以最新完整预测数据为准。'

  return (
    <section className="card" style={{ marginTop: 18, padding: '20px 22px' }}>
      <h2 style={{ fontSize: 19, display: 'flex', alignItems: 'center', gap: 10 }}>
        <span className="fc-no">02</span>本期用哪个模型
      </h2>
      <p className="fc-lead" style={{ fontSize: 15.5 }}>
        默认就用 V1 推荐；想改哪科改哪科，改完保存。两条路线的推荐不一样，先选你在改哪条路线。
      </p>

      <div className="fc-stamps">
        <label>模型配置对应的任务期次
          <select value={period ?? ''} onChange={(e) => onPickPeriod(e.target.value)}>
            {!period && <option value="">请选择期次</option>}
            {periods.map((item) => <option key={item.period} value={item.period}>{item.period}</option>)}
            {period && !periods.some((item) => item.period === period) && <option value={period}>{period}</option>}
          </select>
        </label>
        <span>最新完整预测数据 <b className="mono">{meta.source_period || '未就绪'}</b></span>
        <span>本次实际输出期次 <b className="mono">{actualOutputPeriod ?? '任务完成后显示'}</b></span>
        <span>上游只读台账 <b>{source.name}</b><br />最后修改（北京时间）<b className="mono">{source.last_modified_at ? formatProvenanceTime(source.last_modified_at) : '本机未找到'}</b></span>
      </div>
      <div className="degraded">
        <b>期次与数据说明</b>：{freshnessText} 现有记录无法确认主台账是否被预测流程读取。
        推荐基线为 {meta.recommendation_baseline ?? '—'}，不是预测数据期次。
        <br />最近一次完整运行记录写入时间（北京时间）：{formatProvenanceTime(meta.run_record_at)}；上次处理使用的文件：{meta.processed_input.name ?? '无法核实'}
        {meta.processed_input.last_modified_at ? `（文件最后修改：${formatProvenanceTime(meta.processed_input.last_modified_at)}）` : ''}。
      </div>

      <div className="fc-tabs" role="group" aria-label="预测路线">
        {meta.routes.map((r) => (
          <button key={r.value} type="button" aria-pressed={r.value === currentRoute}
                  className={r.value === currentRoute ? 'on' : ''} onClick={() => setRoute(r.value)}>
            {r.label}
          </button>
        ))}
      </div>
      <p className="hint" style={{ marginTop: 8 }}>
        两条路线的结论不一定一致——报告里会分别标注，不合成一个结论。
        「V1 推荐」是 {meta.recommendation_baseline ?? '—'} 冻结的基线推荐（报告预测章默认按它出图），
        和上方学科板的「选模记录」来源不同、值可能不一样。
      </p>

      <div className="tablewrap" style={{ marginTop: 12 }}>
        <table className="fc-pick">
          <thead>
            <tr>
              <th style={{ width: 170 }}>潜力学科</th>
              <th style={{ width: 200 }}>V1 推荐</th>
              <th style={{ width: 230 }}>我的选择</th>
              <th>模型说明（跟着选择变）</th>
            </tr>
          </thead>
          <tbody>
            {meta.subjects.map((s) => {
              const mine = choice?.choice[currentRoute]?.[s] ?? ''
              const rec = recOf(s)
              return (
                <tr key={s}>
                  <td>{s}</td>
                  <td className="fc-rec">{rec || 'V1 基线推荐'}</td>
                  <td>
                    <select value={mine} aria-label={`${s}的预测模型`}
                            disabled={!choice?.loaded || choice.saving}
                            onChange={(e) => onChange(currentRoute, s, e.target.value)}>
                      <option value="">用 V1 推荐</option>
                      {models.map((m) => <option key={m.value} value={m.value}>{m.label}</option>)}
                    </select>
                  </td>
                  <td>
                    <span className="mdesc">{MODEL_DESC[mine || rec] ?? '由 V1 基线按学科指定。'}</span>
                    <span className="fc-stat">
                      {mine ? (rec ? `已改：由 ${rec} 改为 ${mine}` : `已改：${mine}`) : '用推荐'}
                    </span>
                  </td>
                </tr>
              )
            })}
          </tbody>
        </table>
      </div>

      <div className="fc-save">
        <button className="btn primary" onClick={onSave} disabled={!choice?.loaded || !dirty || choice.saving || !period}>
          {choice?.saving ? '正在保存……' : `保存${period ?? '本期'}选择`}
        </button>
        <span className="hint" role="status" style={dirty ? { color: 'var(--warn)', fontWeight: 650 } : undefined}>
          {choice?.error || (dirty
            ? '有未保存修改 · 保存并确认成功后，才会用于之后开始的任务。'
            : choice?.loaded
              ? `已保存${choice.by ? ` · ${choice.by}` : ''}${choice.at ? ` · ${choice.at}` : ''} · 未改的学科使用 V1 推荐`
              : '正在读取本期已保存的选择……')}
        </span>
      </div>

      {!choice?.loaded && <div className="pending-box" style={{ marginTop: 12 }}>
        {metaError || choice?.error || '正在读取本期已保存的选择。'}
        {choice?.error && <button type="button" className="btn" onClick={onReload} style={{ marginLeft: 10 }}>重新读取</button>}
      </div>}

      <div className="degraded">
        <b>与报告的关系</b>：这里保存的选择进报告预测章——下次重出报告时，选中的学科按你的选择出图，
        未改的用 V1 推荐；所选模型若跑不出来，会自动退回推荐。
      </div>
    </section>
  )
}

/* ---------------------------------------------------------------- 页面 */

export function Forecast({
  period, periods, actualOutputPeriod, meta, metaError, choice, choiceDirty,
  onPickPeriod, onChoiceChange, onSaveChoice, onReloadChoice,
}: {
  period: string | null
  periods: Period[]
  actualOutputPeriod: string | null
  meta: ForecastMeta | null
  metaError: string
  choice: ForecastChoiceEntry | null
  choiceDirty: boolean
  onPickPeriod: (period: string) => void
  onChoiceChange: (route: string, subject: string, model: string) => void
  onSaveChoice: () => void
  onReloadChoice: () => void
}) {
  return (
    <>
      <section className="card" style={{ padding: '22px 24px' }}>
        <h1 style={{ fontSize: 25 }}>潜力学科预测</h1>
        <p className="fc-lead">
          报告预测章用哪套模型，在这里按任务期次设置；学科板和试跑使用最新完整派生产物，供当前查看和比较。
        </p>
        <div className="fc-stamps">
          <span>模型版本 <b className="mono">{meta?.model_version ?? '—'}</b></span>
          <span>预测预览数据期次 <b className="mono">{meta?.source_period || '未就绪'}</b>（最新完整派生产物）</span>
          <span>运行路径 <b>确定性计算 · 大模型不参与数据路径</b></span>
        </div>
      </section>

      {metaError && <div className="pending-box" style={{ marginTop: 14 }}>{metaError}</div>}
      {!meta && !metaError && <div className="pending-box" style={{ marginTop: 14 }}>正在读取预测模型清单……</div>}

      {meta && !meta.available && (
        <div className="pending-box" style={{ marginTop: 14 }}>
          最新完整预测数据尚未就绪，暂时跑不了预测：{meta.load_error}
        </div>
      )}

      {meta && (
        <>
          {meta.available && <Board meta={meta} />}
          <PickTable meta={meta} period={period} periods={periods}
                     actualOutputPeriod={actualOutputPeriod} choice={choice}
                     dirty={choiceDirty} metaError={metaError}
                     onPickPeriod={onPickPeriod} onChange={onChoiceChange}
                     onSave={onSaveChoice} onReload={onReloadChoice} />
          {meta.available && <Trial meta={meta} choice={choice} onChoiceChange={onChoiceChange} />}

          {meta.available && <section className="card" style={{ marginTop: 18, padding: '20px 22px' }}>
            <h2 style={{ fontSize: 19, display: 'flex', alignItems: 'center', gap: 10 }}>
              <span className="fc-no">04</span>口径说明
            </h2>
            <ul className="fc-ticks">
              <li><b>被引路线</b>：预测总被引达到或超过预测 ESI 前1%被引阈值时，记为模型过线。</li>
              <li><b>排名路线</b>：预测国内排名不大于预测国内前1%机构数时，记为辅助条件达到。</li>
              <li><b>模型冻结</b>：SARIMA 阶数和状态空间方差只用初始 30 期确定，滚动期不重新选结构。</li>
              <li><b>多期外推</b>：正式验证范围是一步预测；页面逐期追加预测值并重新拟合，用于形成监测趋势。</li>
              <li><b>结果边界</b>：预测过线是滚动监测信号，不等同于正式入榜时间或入榜概率。</li>
            </ul>
          </section>}
        </>
      )}

      <p className="hint" style={{ marginTop: 14 }}>
        <Icon name="clock" size={15} /> 预测是只读推演：不改台账、不改报告，跑多少次都不会动已有产物。
      </p>
    </>
  )
}
