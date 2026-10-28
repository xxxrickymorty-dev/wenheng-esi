/* 图册行 → EChartsOption / 附表 的分派：一种图型一个构建器（options.ts）。
   没有构建器的图型返回 null → 页面回退 PNG 原图（如实，不硬画）。 */

import type { EChartsOption } from 'echarts'
import type { ReactNode } from 'react'
import type { ChartHit, RankTableRow, TrendTableRow } from '../lib/chartsData'
import {
  citesThresholdOption, collegePieOption, cnciOption, forecastOption, onePctOption,
  onePermilleOption, papersNewOption, qDistOption, rankPctOption, rankTableOption,
  topBySubjectOption, topByYearOption, topPapersOption, trendTableOption,
} from './options'

export function buildOption(hit: ChartHit): EChartsOption | null {
  switch (hit.kind) {
    case 'rank_pct': return rankPctOption(hit.row as Parameters<typeof rankPctOption>[0])
    case 'cnci': return cnciOption(hit.row as Parameters<typeof cnciOption>[0])
    case 'papers_new': return papersNewOption(hit.row as Parameters<typeof papersNewOption>[0])
    case 'cites_threshold': return citesThresholdOption(hit.row as Parameters<typeof citesThresholdOption>[0])
    case 'top_papers': return topPapersOption(hit.row as Parameters<typeof topPapersOption>[0])
    case 'q_dist': return qDistOption(hit.row as Parameters<typeof qDistOption>[0])
    case '1pct': return onePctOption(hit.row as Parameters<typeof onePctOption>[0])
    case '1permille': return onePermilleOption(hit.row as Parameters<typeof onePermilleOption>[0])
    case 'rank_table': return rankTableOption(hit.row as RankTableRow)
    case 'trend_table': return trendTableOption(hit.row as TrendTableRow)
    case 'top_by_year': return topByYearOption(hit.row as Parameters<typeof topByYearOption>[0])
    case 'top_by_subject': return topBySubjectOption(hit.row as Parameters<typeof topBySubjectOption>[0])
    case 'college_cites': return collegePieOption(hit.row as Parameters<typeof collegePieOption>[0], 'cites')
    case 'college_papers': return collegePieOption(hit.row as Parameters<typeof collegePieOption>[0], 'papers')
    case 'forecast': return forecastOption(hit.row as Parameters<typeof forecastOption>[0])
    default: return null
  }
}

const num = (v: number | null, fmt: (v: number) => string) => (v == null ? '' : fmt(v))

/** rank_table / trend_table 这两张 PNG 自带数据表——表也是图的一部分，照数据画出来 */
export function chartTable(hit: ChartHit): ReactNode {
  if (hit.kind === 'rank_table') {
    const t = hit.row as RankTableRow
    const keys = ['cn', 'cn_uni', 'intl'] as const
    return (
      <table className="mini-table">
        <thead>
          <tr><th></th>{t.periods.map((p) => <th key={p}>{p}</th>)}</tr>
        </thead>
        <tbody>
          {keys.map((k) => (
            <tr key={k}>
              <td style={{ color: t.labels[k].color }}>{t.labels[k].label}</td>
              {t.series[k].map((v, i) => <td key={i}>{num(v, (x) => Math.round(x).toString())}</td>)}
            </tr>
          ))}
        </tbody>
      </table>
    )
  }
  if (hit.kind === 'trend_table') {
    const t = hit.row as TrendTableRow
    return (
      <table className="mini-table">
        <thead>
          <tr><th></th>{t.periods.map((p) => <th key={p}>{p}</th>)}</tr>
        </thead>
        <tbody>
          {t.series.map((s) => (
            <tr key={s.disc}>
              <td style={{ color: s.color }}>{s.name_cn}</td>
              {s.values.map((v, i) => <td key={i}>{num(v, (x) => x.toFixed(2) + '%')}</td>)}
            </tr>
          ))}
        </tbody>
      </table>
    )
  }
  return null
}
