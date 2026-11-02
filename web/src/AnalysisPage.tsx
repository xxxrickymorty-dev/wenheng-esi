/* 分析台（2026-11-02 静态稿落地）——同一期的两种看法：
   上面看分布（四组卡片），下面查数（22 行阈值表）。版式照《分析台-静态稿（20261102）》，
   壳与左栏在 App.tsx（跨页书式），这里只管右页。

   🔴 数字只来自后端产物，前端一不算、二不聚合、三不换算：
   · 学科分组与接近度：GET /api/periods/{p}/water（matrix.json 的「云大」列，后端已判 in/near/far）
   · 接近度的小数位：同一条 /charts-data 的 _overview['1pct'].items[].ratio（后端算好的
     「被引 ÷ 1% 阈值 ×100」，含已入学科的超出倍数）——water 对已入学科只给 100，
     看不出「进了多少」，所以有 ratio 就用 ratio，没有才退回 water 的 prox。
     两者都是后端算好的同口径值，前端只做取舍，不做除法。
   · 被引 / 1% 阈值：/charts-data 的 disciplines[*].cites_threshold 取窗口最后一期＝当期。
   · 论文数、1‰ 阈值、距 1‰ 次数：接口没有给（charts-data 只导出「论文的相邻期差分」
     papers_new，以及 1permille 的**百分数**差，不是次数；table2 的原始列没有 JSON 出口）。
     按纪律显示「—」，不在前端拿 cites/threshold 现算缺口——那正是被禁的「自己算」。 */

import { useEffect, useMemo, useState } from 'react'
import { getWaterLevel, type WaterRow } from './api-forecast'
import { getChartsData, type ChartsData } from './lib/chartsData'
import type { Period } from './api'
import './analysis.css'

/** 四组：已入 1% / 接近 / 未入 / 未参评（顺序即版式顺序，与静态稿一致） */
type GroupKey = 'in' | 'near' | 'far' | 'none'
const GROUPS: { key: GroupKey; label: string }[] = [
  { key: 'in', label: '已入 1%' },
  { key: 'near', label: '接近' },
  { key: 'far', label: '未入' },
  { key: 'none', label: '未参评' },
]

/** 一行学科的全部展示值；null＝接口没给，渲染成「—」 */
type Row = {
  subject: string
  prox: number | null
  cites: number | null
  thr: number | null
}

const nf = new Intl.NumberFormat('zh-CN')

/** 千分位与两位小数只是**格式**，不是口径（api.ts 允许前端做格式）。 */
const fmtInt = (n: number | null) => (n == null ? '—' : nf.format(n))
const fmtPct = (n: number | null) => (n == null ? '—' : n.toFixed(2))

export function AnalysisPage({ period, periods, onPick }: {
  period: string | null
  periods: Period[]
  onPick: (period: string) => void
}) {
  const [rows, setRows] = useState<WaterRow[]>([])
  const [charts, setCharts] = useState<ChartsData | null>(null)
  /** pending＝还在读（不画空态，免得一进页就闪「未载入」）；ready/empty＝已有结论 */
  const [phase, setPhase] = useState<'pending' | 'ready' | 'empty'>('pending')

  useEffect(() => {
    if (!period) { setRows([]); setCharts(null); setPhase('empty'); return }
    let alive = true
    setPhase('pending')
    /* 两个口互不牵连：水位给了就能分组，图给不出来只是细列少几格（显示 —）。 */
    void Promise.allSettled([getWaterLevel(period), getChartsData(period)]).then(([w, c]) => {
      if (!alive) return
      const water = w.status === 'fulfilled' ? w.value.rows ?? [] : []
      setRows(water)
      setCharts(c.status === 'fulfilled' ? c.value : null)
      setPhase(water.length ? 'ready' : 'empty')
    })
    return () => { alive = false }
  }, [period])

  /* 学科中文名 → 后端算好的 1% 接近度（含已入学科的超出倍数） */
  const ratioByName = useMemo(() => {
    const map = new Map<string, number>()
    for (const it of charts?._overview?.['1pct']?.items ?? []) {
      if (it.ratio != null) map.set(it.name_cn, it.ratio)
    }
    return map
  }, [charts])

  /* 学科中文名 → 当期被引与 1% 阈值（cites_threshold 是七期序列，最后一格＝当期） */
  const citesByName = useMemo(() => {
    const map = new Map<string, { cites: number | null; thr: number | null }>()
    for (const [key, disc] of Object.entries(charts?.disciplines ?? {})) {
      const ct = disc.cites_threshold
      const end = ct?.periods?.length ? ct.periods.length - 1 : -1
      map.set(disc.name_cn ?? key, {
        cites: end >= 0 ? ct!.cites[end] ?? null : null,
        thr: end >= 0 ? ct!.threshold[end] ?? null : null,
      })
    }
    return map
  }, [charts])

  const all: Row[] = useMemo(() => rows.map((r) => ({
    subject: r.subject,
    prox: ratioByName.get(r.subject) ?? r.prox,
    ...(citesByName.get(r.subject) ?? { cites: null, thr: null }),
  })), [rows, ratioByName, citesByName])

  /* 分组只认 water 的 state：in／near／其余＝未入；拿不到接近度（＝阈值缺失）的进「未参评」。
     组内按接近度降序——后端给的行本来就是降序，这里只是保持同一顺序。 */
  const grouped = useMemo(() => {
    const g: Record<GroupKey, Row[]> = { in: [], near: [], far: [], none: [] }
    const stateOf = new Map(rows.map((r) => [r.subject, r.state]))
    for (const row of all) {
      const state = stateOf.get(row.subject)
      if (row.prox == null || state === 'unknown') g.none.push(row)
      else if (state === 'in') g.in.push(row)
      else if (state === 'near') g.near.push(row)
      else g.far.push(row)
    }
    for (const key of Object.keys(g) as GroupKey[]) {
      g[key].sort((a, b) => (b.prox ?? -1) - (a.prox ?? -1))
    }
    return g
  }, [all, rows])

  return (
    <>
      <header className="an-mast">
        <div>
          <p className="an-eyebrow">分析台</p>
          <h1>{period ?? '——————'}</h1>
        </div>
        {periods.length > 0 && (
          <label className="an-sel">
            <select value={period ?? ''} onChange={(e) => onPick(e.target.value)} aria-label="期次">
              {periods.map((p) => <option key={p.period} value={p.period}>{p.period}</option>)}
              {period && !periods.some((p) => p.period === period) && <option value={period}>{period}</option>}
            </select>
            <i aria-hidden="true" />
          </label>
        )}
      </header>

      <div className="an-rule" aria-hidden="true" />

      {phase === 'pending' ? null : phase === 'empty' ? (
        <p className="an-empty">该期明细未载入。</p>
      ) : (
        <>
          <section aria-labelledby="an-pan">
            <h2 className="an-sec" id="an-pan">学科全景</h2>
            {GROUPS.map((g) => {
              const list = grouped[g.key]
              return (
                <div className={`an-grp${list.length ? '' : ' is-empty'}`} key={g.key}>
                  {/* 组名已说明状态，卡内不再重复状态字样 */}
                  <p className="an-gh"><span>{g.label}</span><b>{list.length}</b></p>
                  {list.length > 0 && (
                    <ol className="an-cards">
                      {list.map((row) => (
                        <li className="an-card" key={row.subject}>
                          <p className="an-name" title={row.subject}>{row.subject}</p>
                          <p className="an-prox">{fmtPct(row.prox)}<i>%</i></p>
                          <span className="an-bar" aria-hidden="true">
                            <i style={{ width: `${Math.min(100, Math.max(0, row.prox ?? 0))}%` }} />
                          </span>
                          {/* 未入组多一行「还需」：次数接口没给，如实 —（见文件头注释） */}
                          {g.key === 'far' && <p className="an-gap">还需 —</p>}
                        </li>
                      ))}
                    </ol>
                  )}
                </div>
              )
            })}
          </section>

          <section aria-labelledby="an-thr">
            <h2 className="an-sec" id="an-thr">阈值查表</h2>
            <div className="an-tw">
              <table className="an-tt">
                <colgroup>
                  <col style={{ width: '25%' }} /><col style={{ width: '12.5%' }} /><col style={{ width: '12.5%' }} />
                  <col style={{ width: '12.5%' }} /><col style={{ width: '12.5%' }} /><col style={{ width: '12.5%' }} />
                  <col style={{ width: '12.5%' }} />
                </colgroup>
                <thead>
                  <tr>
                    <th scope="col">学科</th><th scope="col">论文</th><th scope="col">被引</th>
                    <th scope="col">1% 阈值</th><th scope="col">接近度</th>
                    <th scope="col">1‰ 阈值</th><th scope="col">距 1‰</th>
                  </tr>
                </thead>
                <tbody>
                  {all.map((row) => (
                    <tr key={row.subject}>
                      <td>{row.subject}</td>
                      <td>—</td>
                      <td>{fmtInt(row.cites)}</td>
                      <td>{fmtInt(row.thr)}</td>
                      <td>{row.prox == null ? '—' : `${fmtPct(row.prox)}%`}</td>
                      <td>—</td>
                      <td>—</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </section>
        </>
      )}
    </>
  )
}
