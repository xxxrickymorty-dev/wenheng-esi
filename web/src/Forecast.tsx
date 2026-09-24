/* 预测台（工作区）——潜力学科各用什么模型 + 试跑验证。
   数据全部来自后端：模型池/学科/路线来自 /api/forecast/meta，试跑走 /api/forecast/run，
   逐科选择落盘走 /api/periods/{期次}/forecast-choice——期次就是数据来源那一期
   （meta.source_period，最新一期），选择和试跑绑在同一期上。
   本页不做任何换算：表上图上都是后端给的数（只有"怎么显示"的格式化，见 fmtNum）。 */

import { useEffect, useState } from 'react'
import {
  getForecastChoice, getForecastMeta, runForecast, saveForecastChoice,
  type ForecastMeta, type ForecastModelResult, type ForecastRun,
} from './api5'
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
    </article>
  )
}

function Trial({ meta }: { meta: ForecastMeta }) {
  const [subject, setSubject] = useState(meta.subjects[0] ?? '')
  const [task, setTask] = useState(meta.routes[0]?.value ?? '')
  const [model, setModel] = useState('recommended')
  const [horizon, setHorizon] = useState(18)
  const [busy, setBusy] = useState(false)
  const [data, setData] = useState<ForecastRun | null>(null)
  const [err, setErr] = useState('')

  async function onRun() {
    setBusy(true)
    setErr('')
    setData(null)
    try {
      setData(await runForecast({ subject, task, model, horizon }))
    } catch (e) {
      const h = e as { body?: { error?: string; hint?: string }; message?: string }
      setErr(h.body?.error ?? h.message ?? '运行失败')
    } finally {
      setBusy(false)
    }
  }

  return (
    <section className="card" style={{ marginTop: 18, padding: '20px 22px' }}>
      <h2 style={{ fontSize: 19, display: 'flex', alignItems: 'center', gap: 10 }}>
        <span className="fc-no">02</span>试跑一个学科（验证）
      </h2>
      <p className="fc-lead" style={{ fontSize: 15.5 }}>
        选学科、路线、模型，跑一次看看：滚动样本外误差、首次模型过线期、逐期预测值。
        「V1 基线推荐」是各学科冻结下来的那一个；「五模型全部运行比较」只做横向比较，不改写推荐。
      </p>

      <div className="fc-form">
        <label>潜力学科
          <select value={subject} onChange={(e) => setSubject(e.target.value)}>
            {meta.subjects.map((s) => <option key={s} value={s}>{s}</option>)}
          </select>
        </label>
        <label>预测路线
          <select value={task} onChange={(e) => setTask(e.target.value)}>
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
        <button className="btn primary" onClick={onRun} disabled={busy || !subject}>
          {busy ? '运行中……' : '运行预测'}
        </button>
      </div>

      {err && <div className="pending-box" style={{ marginTop: 14 }}>{err}</div>}
      {busy && (
        <p className="hint" style={{ marginTop: 14 }}>
          {model === 'all' ? '正在跑五模型滚动回测与预测，需要一点时间……' : '正在跑模型，请稍候……'}
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

          {data.results.map((r) => <ModelCard key={r.model} run={data} r={r} />)}

          <p className="hint" style={{ marginTop: 12 }}>{data.notice}</p>
        </>
      )}
    </section>
  )
}

/* ---------------------------------------------------------------- 逐科选择 */

function PickTable({ meta, picks, setPicks, saved, saving, saveErr, onSave }: {
  meta: ForecastMeta
  picks: Record<string, Record<string, string>>
  setPicks: (p: Record<string, Record<string, string>>) => void
  saved: { n: number; by: string; at: string } | null
  saving: boolean
  saveErr: string
  onSave: () => void
}) {
  const [route, setRoute] = useState(meta.routes[0]?.value ?? '')
  const models = meta.models.filter((m) => m.value !== 'recommended' && m.value !== 'all')
  const recOf = (s: string) => meta.recommendations?.[route]?.[s] ?? ''

  return (
    <section className="card" style={{ marginTop: 18, padding: '20px 22px' }}>
      <h2 style={{ fontSize: 19, display: 'flex', alignItems: 'center', gap: 10 }}>
        <span className="fc-no">01</span>本期用哪个模型
      </h2>
      <p className="fc-lead" style={{ fontSize: 15.5 }}>
        默认就用 V1 推荐；想改哪科改哪科，改完保存。两条路线的推荐不一样，先选你在改哪条路线。
      </p>

      <div className="fc-tabs" role="tablist" aria-label="预测路线">
        {meta.routes.map((r) => (
          <button key={r.value} role="tab" aria-selected={r.value === route}
                  className={r.value === route ? 'on' : ''} onClick={() => setRoute(r.value)}>
            {r.label}
          </button>
        ))}
      </div>
      <p className="hint" style={{ marginTop: 8 }}>
        两条路线的结论不一定一致——报告里会分别标注，不合成一个结论。
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
              const mine = picks[route]?.[s] ?? ''
              const rec = recOf(s)
              return (
                <tr key={s}>
                  <td>{s}</td>
                  <td className="fc-rec">{rec || 'V1 基线推荐'}</td>
                  <td>
                    <select value={mine} aria-label={`${s}的预测模型`}
                            onChange={(e) => setPicks({
                              ...picks,
                              [route]: { ...(picks[route] ?? {}), [s]: e.target.value },
                            })}>
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
        <button className="btn primary" onClick={onSave} disabled={saving}>
          {saving ? '正在保存……' : '保存本期选择'}
        </button>
        <span className="hint">
          {saveErr ? saveErr : saved
            ? `已保存 ${saved.n} 科改选${saved.by ? ` · ${saved.by}` : ''}${saved.at ? ` · ${saved.at}` : ''}（未改的学科用 V1 推荐）`
            : '尚未保存——只存改过的学科，未改的用 V1 推荐。'}
        </span>
      </div>

      <div className="degraded">
        <b>这一块的后端进度</b>：选择已能落盘（存进本期档案）；把选择带进报告预测章、
        并逐科显示 V1 推荐的具体模型名，这两条后端还在接线——接线前报告仍用 V1 基线推荐。
      </div>
    </section>
  )
}

/* ---------------------------------------------------------------- 页面 */

export function Forecast() {
  const [meta, setMeta] = useState<ForecastMeta | null>(null)
  const [metaErr, setMetaErr] = useState('')
  const [picks, setPicks] = useState<Record<string, Record<string, string>>>({})
  const [saved, setSaved] = useState<{ n: number; by: string; at: string } | null>(null)
  const [saving, setSaving] = useState(false)
  const [saveErr, setSaveErr] = useState('')

  useEffect(() => {
    let alive = true
    ;(async () => {
      try {
        const m = await getForecastMeta()
        if (!alive) return
        setMeta(m)
        if (!m.available || !m.source_period) return
        const c = await getForecastChoice(m.source_period)
        if (!alive) return
        const init: Record<string, Record<string, string>> = {}
        let n = 0
        for (const r of m.routes) {
          init[r.value] = {}
          for (const s of m.subjects) {
            const v = c.choice?.[r.value]?.[s] ?? ''
            init[r.value][s] = v
            if (v) n += 1
          }
        }
        setPicks(init)
        if (n > 0) setSaved({ n, by: c.by, at: c.at })
      } catch (e) {
        const h = e as { status?: number; body?: { error?: string; hint?: string }; message?: string }
        if (!alive) return
        setMetaErr(h.status === 403
          ? '预测台要管理员权限——用馆员账号登录后再来。'
          : (h.body?.error ?? h.message ?? '读不到预测台的数据。'))
      }
    })()
    return () => { alive = false }
  }, [])

  async function onSave() {
    if (!meta) return
    setSaving(true)
    setSaveErr('')
    try {
      const payload: Record<string, Record<string, string>> = {}
      let n = 0
      for (const r of meta.routes) {
        const per: Record<string, string> = {}
        for (const s of meta.subjects) {
          const v = picks[r.value]?.[s]
          if (v) { per[s] = v; n += 1 }
        }
        payload[r.value] = per
      }
      await saveForecastChoice(meta.source_period, payload)
      /* 存完回读核对：**看到文件里确实有**才算保存成功（不靠响应自报） */
      const c = await getForecastChoice(meta.source_period)
      const landed = meta.routes.every((r) => meta.subjects.every(
        (s) => (payload[r.value]?.[s] ?? '') === (c.choice?.[r.value]?.[s] ?? '')))
      if (!landed) {
        setSaveErr('这次没有保存成功——后端的保存接口有故障（已记下，等后端修）。改的选择现在只在页面上，刷新会丢。')
        return
      }
      setSaved({ n, by: c.by, at: c.at })
    } catch (e) {
      const h = e as { body?: { error?: string; hint?: string }; message?: string }
      setSaveErr(h.body?.error ?? h.message ?? '保存失败。')
    } finally {
      setSaving(false)
    }
  }

  return (
    <>
      <section className="card" style={{ padding: '22px 24px' }}>
        <h1 style={{ fontSize: 25 }}>潜力学科预测</h1>
        <p className="fc-lead">
          报告预测章用哪套模型，在这里定：<b>潜力学科</b>各有一条 V1 基线推荐，想改哪科就改，改完保存。
          想先看某个模型准不准，在下面试跑一次——滚动误差、首次过线期都摆出来。
        </p>
        <div className="fc-stamps">
          <span>模型版本 <b className="mono">{meta?.model_version ?? '—'}</b></span>
          <span>数据期次 <b className="mono">{meta?.source_period || '未就绪'}</b>（最新一期派生产物 · 选择与试跑都绑在这一期）</span>
          <span>运行路径 <b>确定性计算 · 大模型不参与数据路径</b></span>
        </div>
      </section>

      {metaErr && <div className="pending-box" style={{ marginTop: 14 }}>{metaErr}</div>}

      {meta && !meta.available && (
        <div className="pending-box" style={{ marginTop: 14 }}>
          这一期的派生产物还没就绪，暂时跑不了预测：{meta.load_error}
        </div>
      )}

      {meta && meta.available && (
        <>
          <PickTable meta={meta} picks={picks} setPicks={setPicks}
                     saved={saved} saving={saving} saveErr={saveErr} onSave={onSave} />
          <Trial meta={meta} />

          <section className="card" style={{ marginTop: 18, padding: '20px 22px' }}>
            <h2 style={{ fontSize: 19, display: 'flex', alignItems: 'center', gap: 10 }}>
              <span className="fc-no">03</span>口径说明
            </h2>
            <ul className="fc-ticks">
              <li><b>被引路线</b>：预测总被引达到或超过预测 ESI 前1%被引阈值时，记为模型过线。</li>
              <li><b>排名路线</b>：预测国内排名不大于预测国内前1%机构数时，记为辅助条件达到。</li>
              <li><b>模型冻结</b>：SARIMA 阶数和状态空间方差只用初始 30 期确定，滚动期不重新选结构。</li>
              <li><b>多期外推</b>：正式验证范围是一步预测；页面逐期追加预测值并重新拟合，用于形成监测趋势。</li>
              <li><b>结果边界</b>：预测过线是滚动监测信号，不等同于正式入榜时间或入榜概率。</li>
            </ul>
          </section>
        </>
      )}

      <a className="entry" href="/app/shelf/">
        <span>
          <span className="t">陈列馆 · 历期卷宗</span>
          <span className="d">按期翻看已出刊的报告（书架 → 端详 → 开卷）</span>
        </span>
        <span className="go" aria-hidden="true">→</span>
      </a>

      <p className="hint" style={{ marginTop: 14 }}>
        <Icon name="clock" size={15} /> 预测是只读推演：不改台账、不改报告，跑多少次都不会动已有产物。
      </p>
    </>
  )
}
