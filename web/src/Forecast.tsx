/* 预测台（票 13）——看图选模 + 逐科定稿。
   页头一条「期次 · 数据截至 · 路线 · 保存」带：路线只此一套控件、保存只此一处；
   01 预测图打开即出图（单模型与五模型同一张卡）；02 逐科选择；03 学科板 · 现状（折叠）；
   04 预测口径与边界（折叠）。数字全部来自服务端产物——本页只显示，不重算。 */

import { useEffect, useRef, useState } from 'react'
import {
  formatProvenanceTime, getForecastBoard, runForecast,
  type ForecastBoard, type ForecastChoiceEntry, type ForecastMeta,
  type ForecastModelResult, type ForecastRun,
} from './api-forecast'
import { Info } from './Info'
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

/** 数据期次 202609 → 2026-09（页头「数据截至」的说法；期次本身仍原样 6 位） */
function fmtMonth(v: string | null | undefined): string {
  if (!v) return '—'
  return v.length >= 6 ? `${v.slice(0, 4)}-${v.slice(4, 6)}` : v
}

/** 路线短名：'路线1 · 总被引 / ESI前1%被引阈值' → '总被引'（全名放悬停与 ⓘ） */
function shortRoute(label: string): string {
  const head = label.split('/')[0] ?? label
  const parts = head.split('·')
  return (parts[parts.length - 1] ?? head).trim() || label
}

/** 期数档位：默认 18 与报告一致；24 是模型包的硬上限（要更远得升模型版本） */
const HORIZONS = [12, 18, 24]

/** 图结果缓存：内存 + sessionStorage（刷新不用重跑；配额满就静默放弃）。
    键里带数据期次——期次变了就重跑，不拿旧图冒充新数据。 */
const STORE_PREFIX = 'wh-fc-gal:'

function loadStoredRun(key: string): ForecastRun | null {
  try {
    const raw = sessionStorage.getItem(STORE_PREFIX + key)
    return raw ? JSON.parse(raw) as ForecastRun : null
  } catch {
    return null
  }
}

function storeRun(key: string, run: ForecastRun) {
  try {
    sessionStorage.setItem(STORE_PREFIX + key, JSON.stringify(run))
  } catch {
    /* 配额满/隐私模式：不缓存，不影响运行 */
  }
}

/* ---------------------------------------------------------------- 图卡（两种模式共用一张） */

/** 逐期预测值表——图卡折叠块里的明细表。 */
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

/** 候选模型图卡：五模型比较和单模型试跑都走这一张（卡题、标签、按钮、折叠一致）。 */
function ModelCard({
  run, r, mine, active, pickable, onPick,
}: {
  run: ForecastRun
  r: ForecastModelResult
  /** 用户显式改选的那一个（空＝跟随推荐） */
  mine: boolean
  /** 现在生效的那一个 */
  active: boolean
  pickable: boolean
  onPick: (model: string) => void
}) {
  const isRec = r.model === run.recommended_model
  const isBest = run.compared_all && r.model === run.comparison_best_model
  return (
    <article className="fc-model">
      <div className="fc-model-h">
        <h3>{r.model}</h3>
        {isRec && <span className="pill signed">V1 推荐</span>}
        {isBest && <span className="pill stale">本次误差最低</span>}
        {mine && <span className="pill manual">当前选用</span>}
        {!mine && active && <span className="pill">正在使用</span>}
        <span className="hint ml-auto">数据截至 {fmtMonth(run.source_period)}</span>
      </div>

      <div className="fc-metrics">
        <div><b>{fmtNum(r.rolling_mape, 2)}%</b><span>滚动 MAPE</span></div>
        <div><b>{fmtNum(r.fit_mape, 2)}%</b><span>拟合 MAPE</span></div>
        <div><b>{fmtPeriod(r.first_crossing)}</b><span>首次过线</span></div>
        <div><b>{r.status === 'PASS' ? '通过' : '需复核'}</b><span>运行状态</span></div>
      </div>

      <img className="fc-chart" src={r.chart} alt={`${run.subject} · ${r.model} 预测趋势图`} />

      <div className="fc-actions">
        {active
          ? <button type="button" className="btn" disabled>{mine ? '当前选用' : '正在使用'}</button>
          : <button type="button" className="btn primary" disabled={!pickable}
                    onClick={() => onPick(r.model)}>选用此模型</button>}
      </div>

      <details className="fc-more">
        <summary>分项与逐期（{r.forecast.length} 期）</summary>
        {r.metric_mapes && (
          <p className="fc-break">
            分项滚动：
            {Object.entries(r.metric_mapes).map(([name, m]) => `${name} ${fmtNum(m.rolling, 2)}%`).join(' · ')}
          </p>
        )}
        <ForecastTable run={run} r={r} />
      </details>
    </article>
  )
}

/* ---------------------------------------------------------------- 01 预测图 */

/** 打开即出图：任何「没跑过」的参数组合直接跑，跑过的秒回缓存——
    路线切换不会再出现「图没了」的空档；单模型与五模型同一张卡渲染。 */
function Trial({
  meta, choice, route, onChoiceChange,
}: {
  meta: ForecastMeta
  choice: ForecastChoiceEntry | null
  route: string
  onChoiceChange: (route: string, subject: string, model: string) => void
}) {
  const [subject, setSubject] = useState(meta.subjects[0] ?? '')
  const [model, setModel] = useState('all')
  const [horizon, setHorizon] = useState(18)
  const [busy, setBusy] = useState(false)
  const [data, setData] = useState<ForecastRun | null>(null)
  const [err, setErr] = useState('')
  const cache = useRef(new Map<string, ForecastRun>())
  const selectedSubject = meta.subjects.includes(subject) ? subject : meta.subjects[0] ?? ''
  const runKey = `${meta.source_period}|${selectedSubject}|${route}|${model}|${horizon}`
  const runKeyRef = useRef(runKey)
  runKeyRef.current = runKey

  async function run(subjectName: string, routeName: string, modelName: string, h: number, key: string) {
    setBusy(true)
    setErr('')
    try {
      const result = await runForecast({ subject: subjectName, task: routeName, model: modelName, horizon: h })
      cache.current.set(key, result)
      storeRun(key, result)
      /* 迟到的旧结果不覆盖当前参数（切选择快时会遇到） */
      if (runKeyRef.current === key) setData(result)
    } catch (e) {
      if (runKeyRef.current !== key) return
      const body = e as { body?: { error?: string; hint?: string }; message?: string }
      setData(null)
      setErr(body.body?.error ?? body.message ?? '运行失败')
    } finally {
      if (runKeyRef.current === key) setBusy(false)
    }
  }

  // 参数一变先看缓存（内存 → 会话）；没有就跑——首屏与切路线都自动出图。
  useEffect(() => {
    if (!selectedSubject || !route) return
    const cached = cache.current.get(runKey) ?? loadStoredRun(runKey)
    if (cached) {
      cache.current.set(runKey, cached)
      setData(cached)
      setErr('')
      return
    }
    setData(null)
    setErr('')
    void run(selectedSubject, route, model, horizon, runKey)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [runKey])

  const mine = choice?.choice?.[route]?.[selectedSubject] ?? ''
  const rec = meta.recommendations?.[route]?.[selectedSubject] ?? data?.recommended_model ?? ''
  const effective = mine || rec
  const pickable = !!choice?.loaded && !choice?.saving

  return (
    <section className="card" style={{ marginTop: 18, padding: '20px 22px' }}>
      <h2 className="h-sec">
        <span className="fc-no">01</span>预测图
      </h2>

      <div className="fc-form">
        <label>学科
          <select value={selectedSubject} onChange={(e) => setSubject(e.target.value)}>
            {meta.subjects.map((s) => <option key={s} value={s}>{s}</option>)}
          </select>
        </label>
        <label><span>模型 <Info label="模型怎么选">
          <p><b>五模型全部运行比较</b>＝五个候选模型各出一张图，选前先看（默认）。</p>
          <p>选单个模型＝只跑它一张；卡面与五图完全一致，看全部再切回「五模型全部运行比较」。</p>
        </Info></span>
          <select value={model} onChange={(e) => setModel(e.target.value)}>
            {meta.models.map((m) => <option key={m.value} value={m.value}>{m.label}</option>)}
          </select>
        </label>
        <label>期数
          <select value={horizon} onChange={(e) => setHorizon(Number(e.target.value))}>
            {HORIZONS.map((h) => <option key={h} value={h}>{h} 期{h === 18 ? '（与报告一致）' : h === 24 ? '（模型上限）' : ''}</option>)}
          </select>
        </label>
      </div>

      <p className="hint mt-9" role="status">
        当前选用：<b>{effective || '未定'}</b>
        {mine ? `（已从 V1 推荐「${rec}」改选）` : ''}
        {mine && (
          <button type="button" className="btn fc-gal-reset" disabled={!pickable}
                  onClick={() => onChoiceChange(route, selectedSubject, '')}>恢复推荐</button>
        )}
      </p>

      {err && (
        <div className="pending-box mt-12">
          {err}
          <button type="button" className="btn ml-10" 
                  onClick={() => void run(selectedSubject, route, model, horizon, runKey)}>重新运行</button>
        </div>
      )}
      {busy && (
        <div className="pending-box mt-12" role="status">
          正在跑{model === 'all' ? '五模型滚动回测与预测' : '模型'}……大约十几秒。
        </div>
      )}

      {data && (
        <>
          {data.errors.length > 0 && (
            <div className="pending-box mt-12">
              有 {data.errors.length} 个模型没跑成：{data.errors.map((x) => `${x.model}（${x.error}）`).join('；')}
            </div>
          )}
          <div className="fc-gal">
            {data.results.map((r) => (
              <ModelCard key={r.model} run={data} r={r}
                         mine={r.model === mine} active={r.model === effective}
                         pickable={pickable}
                         onPick={(m) => onChoiceChange(route, selectedSubject, m)} />
            ))}
          </div>
        </>
      )}
    </section>
  )
}

/* ---------------------------------------------------------------- 02 逐科选择 */

function PickTable({
  meta, route, choice, onChange,
}: {
  meta: ForecastMeta
  route: string
  choice: ForecastChoiceEntry | null
  onChange: (route: string, subject: string, model: string) => void
}) {
  const models = meta.models.filter((m) => m.value !== 'recommended' && m.value !== 'all')
  const recOf = (s: string) => meta.recommendations?.[route]?.[s] ?? ''

  return (
    <section className="card" style={{ marginTop: 18, padding: '20px 22px' }}>
      <h2 className="h-sec">
        <span className="fc-no">02</span>本期用哪个模型
      </h2>

      {!choice?.loaded && (
        <div className="pending-box mt-12">
          {choice?.error || '正在读取本期已保存的选择……'}
        </div>
      )}

      <div className="tablewrap mt-12">
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
              const mine = choice?.choice[route]?.[s] ?? ''
              const rec = recOf(s)
              return (
                <tr key={s}>
                  <td>{s}</td>
                  <td className="fc-rec">{rec || 'V1 推荐'}</td>
                  <td>
                    <select value={mine} aria-label={`${s}的预测模型`}
                            disabled={!choice?.loaded || choice.saving}
                            onChange={(e) => onChange(route, s, e.target.value)}>
                      <option value="">用 V1 推荐</option>
                      {models.map((m) => <option key={m.value} value={m.value}>{m.label}</option>)}
                    </select>
                  </td>
                  <td>
                    <span className="mdesc">{MODEL_DESC[mine || rec] ?? '由 V1 推荐按学科指定。'}</span>
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

      <p className="hint mt-9">保存后，从下次重出报告起生效。</p>
    </section>
  )
}

/* ---------------------------------------------------------------- 页面 */

export function Forecast({
  period, meta, metaError, choice, choiceDirty,
  onChoiceChange, onSaveChoice, onReloadChoice,
}: {
  period: string | null
  meta: ForecastMeta | null
  metaError: string
  choice: ForecastChoiceEntry | null
  choiceDirty: boolean
  onChoiceChange: (route: string, subject: string, model: string) => void
  onSaveChoice: () => void
  onReloadChoice: () => void
}) {
  const routes = meta?.routes ?? []
  const [route, setRoute] = useState('')
  const currentRoute = routes.some((r) => r.value === route) ? route : (routes[0]?.value ?? '')

  /* 学科板折在 03 里——数据在这里取，折头的一行摘要也要用（见下） */
  const [board, setBoard] = useState<ForecastBoard | null>(null)
  const [boardNote, setBoardNote] = useState<string | null>(null)
  useEffect(() => {
    let alive = true
    setBoard(null); setBoardNote(null)
    getForecastBoard()
      .then((b) => { if (alive) setBoard(b) })
      .catch(() => { if (alive) setBoardNote('学科板暂时读不到（这份选模表还没生成）。') })
    return () => { alive = false }
  }, [meta?.source_period])

  const boardRows = board?.routes?.[currentRoute] ?? []
  const crossings = boardRows.filter((r) => r.t1).map((r) => r.t1).sort()
  const boardSm = boardNote ? boardNote
    : !board ? '正在读取……'
      : crossings.length ? `${crossings.length} 科预计过线 · 最早 ${crossings[0]}` : '本路线暂无预计过线'

  const freshnessText = meta?.data_freshness === 'needs_check'
    ? '检测到台账或处理输入文件的修改时间晚于最近一次完整运行记录；无法确认这次更新是否已进入预测数据，请重新处理确认。'
    : '现有记录无法确认上游台账是否已进入预测所用数据，请以「数据截至」为准。'

  const saveState = choice?.saving ? '正在保存……'
    : choice?.error ? choice.error
      : !choice?.loaded ? (metaError || '正在读取本期已保存的选择……')
        : choiceDirty ? '有未保存改动'
          : '已保存'

  return (
    <>
      <section className="card" style={{ padding: '20px 22px 18px' }}>
        <h1 style={{ fontSize: 25 }}>潜力学科预测</h1>
        <p className="fc-lead mt-6">先看图，再定稿。</p>
      </section>

      {/* 页头一条带：期次 / 数据截至 / 路线（唯一一套控件）/ 保存（唯一一处） */}
      <div className="fc-band" role="region" aria-label="期次、路线与保存">
        <span className="kv">期次 <b className="mono">{period ?? '未选'}</b></span>
        <span className="kv">数据截至 <b className="mono">{fmtMonth(meta?.source_period)}</b></span>
        <Info label="期次与数据说明">
          <p><b>期次 {period ?? '—'}</b>：本期配置与报告的归档期——保存写进这一期。</p>
          <p><b>数据截至 {fmtMonth(meta?.source_period)}</b>：预测图与试跑读的那批完整数据；模型版本 {meta?.model_version ?? '—'}。</p>
          <p>最近一次完整运行记录：{formatProvenanceTime(meta?.run_record_at)}；上次处理使用的文件：{meta?.processed_input?.name ?? '无法核实'}。</p>
        </Info>

        {routes.length > 1 && (
          <div className="fc-seg" role="group" aria-label="预测路线">
            {routes.map((r) => (
              <button key={r.value} type="button" title={r.label}
                      aria-pressed={r.value === currentRoute}
                      className={r.value === currentRoute ? 'on' : ''}
                      onClick={() => setRoute(r.value)}>
                {shortRoute(r.label)}
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
        {choice?.error && (
          <button type="button" className="btn" onClick={onReloadChoice}>重新读取</button>
        )}
        <button className="btn primary" onClick={onSaveChoice}
                disabled={!choice?.loaded || !choiceDirty || choice.saving || !period}>
          {choice?.saving ? '正在保存……' : '保存选择'}
        </button>
      </div>

      {metaError && <div className="pending-box mt-14">{metaError}</div>}
      {!meta && !metaError && <div className="pending-box mt-14">正在读取预测模型清单……</div>}

      {meta && !meta.available && (
        <div className="pending-box mt-14">
          最新完整预测数据尚未就绪，暂时跑不了预测：{meta.load_error}
        </div>
      )}

      {meta?.available && (
        <>
          <Trial meta={meta} choice={choice} route={currentRoute} onChoiceChange={onChoiceChange} />

          <PickTable meta={meta} route={currentRoute} choice={choice} onChange={onChoiceChange} />

          <details className="fold">
            <summary>03 学科板 · 现状（本路线 {boardRows.length || 8} 科）<span className="sm">{boardSm}</span></summary>
            <div className="fold-inner">
              <p className="hint mt-4">
                接近度＝离门槛的百分数点值；过线是滚动监测信号，不等同于正式入榜时间。
                这一板是预测阶段的选模记录，<b>不是</b>报告最终采用的模型——报告用哪套看上面 02。
              </p>
              {boardNote && <div className="pending-box mt-10">{boardNote}</div>}
              {!!boardRows.length && (
                <div className="bd-grid">
                  {boardRows.map((r) => (
                    <div className="bd-card" key={r.subject}>
                      <div className="bd-top">
                        <b>{r.subject}</b>
                        <span className="bd-prox">{r.prox == null ? '—' : `${r.prox}%`}</span>
                      </div>
                      <span className="bd-bar" aria-hidden="true">
                        <i style={{ transform: `scaleX(${Math.min(100, Math.max(0, r.prox ?? 0)) / 100})` }} />
                      </span>
                      <div className="bd-meta">
                        <span>模型 {r.model}</span>
                        <span>滚动 MAPE {r.rolling_mape == null ? '—' : `${r.rolling_mape}%`}</span>
                      </div>
                      <div className={`bd-cross${r.t1 ? ' on' : ''}`}>
                        {r.t1 ? `预计过线 ${r.t1}${r.t3 && r.t3 !== r.t1 ? `（最晚 ${r.t3}）` : ''}` : '窗口内未过线'}
                      </div>
                    </div>
                  ))}
                </div>
              )}
              <p className="hint mt-10">
                源：预测选模与过线.md · 数据截至 {fmtMonth(board?.period ?? meta.source_period)}
                {board?.window ? ` · 窗口 ${board.window}` : ''}；t1/t2/t3 空＝该窗口内未过线。
              </p>
            </div>
          </details>

          <details className="fold">
            <summary>04 预测口径与边界<span className="sm">过线定义 · 模型冻结 · 多期外推 · 与报告的关系</span></summary>
            <div className="fold-inner">
              <ul className="fc-ticks">
                <li><b>被引路线</b>：预测总被引达到或超过预测 ESI 前1%被引阈值时，记为模型过线。</li>
                <li><b>排名路线</b>：预测国内排名不大于预测国内前1%机构数时，记为辅助条件达到。</li>
                <li><b>模型冻结</b>：SARIMA 阶数和状态空间方差只用初始 30 期确定，滚动期不重新选结构。</li>
                <li><b>多期外推</b>：正式验证范围是一步预测；页面逐期追加预测值并重新拟合，用于形成监测趋势。</li>
                <li><b>结果边界</b>：预测过线是滚动监测信号，不等同于正式入榜时间或入榜概率。</li>
              </ul>
              <p className="hint mt-10">
                <b>与报告的关系</b>：这里保存的选择进报告预测章——下次重出报告时，选中的学科按你的选择出图，未改的用 V1 推荐；所选模型若跑不出来，会自动退回推荐。
              </p>
              <p className="hint mt-6">
                <b>期次与数据说明</b>：{freshnessText} 推荐基线为 {meta.recommendation_baseline ?? '—'}，不是预测数据期次。
                最近一次完整运行记录写入时间（北京时间）：{formatProvenanceTime(meta.run_record_at)}；上次处理使用的文件：{meta.processed_input.name ?? '无法核实'}
                {meta.processed_input.last_modified_at ? `（文件最后修改：${formatProvenanceTime(meta.processed_input.last_modified_at)}）` : ''}。
              </p>
            </div>
          </details>
        </>
      )}
    </>
  )
}
