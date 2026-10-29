/* 图册同源数据（GET /api/periods/<p>/charts-data，src/chart_data.py 出）。
   🔴 数字只来自后端：这一层只取形状与查找，不做任何换算、聚合、四舍五入。
   缺键（老期次预测图没落序列、学院统计缺席等）＝如实返回 null，调用方回退 PNG。 */

import { req } from '../api'

export type Num = number | null

/** 双折线：台账 rank_pct ×100 已由后端做掉，前端只格式化 */
export type RankPctRow = {
  name_cn: string
  periods: string[]
  series: { intl: Num[]; cn: Num[] }
  labels: Record<string, string>
}

export type DisciplineCharts = {
  name_cn: string
  cnci?: { periods: string[]; values: Num[]; baseline: number }
  papers_new?: { periods: string[]; values: Num[] }
  cites_threshold?: { periods: string[]; cites: Num[]; threshold: Num[] }
  top_papers?: { periods: string[]; values: Num[] }
  q_dist?: {
    quarter: string
    entities: { key: string; name: string; color: string; values: Num[] }[]
  }
}

export type OnePctItem = { name_cn: string; ratio: Num; gap: Num }

export type RankTableRow = {
  periods: string[]
  series: { cn: Num[]; cn_uni: Num[]; intl: Num[] }
  labels: Record<string, { label: string; color: string }>
}

export type TrendTableRow = {
  periods: string[]
  series: { disc: string; name_cn: string; color: string; values: Num[] }[]
  baseline: number
}

export type CollegeItem = { name: string; value: Num; pct: Num; color: string }

export type ForecastSeries = {
  hist_periods: string[]
  fut_periods: string[]
  columns: {
    actual_label: string
    model_label: string
    actual_color: string
    model_color: string
    actual: Num[]
    fitted: Num[]
    future: Num[]
  }[]
}

export type ChartsData = {
  schema: number
  end_period: string
  periods: string[]
  rank_pct: Record<string, RankPctRow>
  disciplines: Record<string, DisciplineCharts>
  _overview: {
    '1pct'?: { items: OnePctItem[] }
    '1permille'?: { items: OnePctItem[] }
    rank_table?: RankTableRow
    trend_table?: TrendTableRow
    top_by_year?: { labels: string[]; values: Num[] }
    top_by_subject?: { items: { name_cn: string; value: Num }[] }
    college_cites?: { items: CollegeItem[] }
    college_papers?: { items: CollegeItem[] }
  }
  forecast: Record<string, ForecastSeries>
  /** docx 插图 rId → 图册图位（2026-10-28 rick 裁决：审核台正文也换同源交互图）。
      后端逐字节比对得出，只收对得上的；对不上的（封面/截图）没有这个键。 */
  report_map?: Record<string, { group: string; name: string }>
}

export async function getChartsData(period: string): Promise<ChartsData> {
  return req<ChartsData>(`/api/periods/${encodeURIComponent(period)}/charts-data`)
}

/* ---------- 查找：图册行（分组目录名 + 文件名）→ 同源数据 ---------- */

/** 图册行名 `rank_pct.png` → 数据键 `rank_pct` */
export function stemOf(name: string): string {
  return name.replace(/\.png$/i, '')
}

/** 概览图的键直接落在 _overview / forecast 下；学科图的键按学科展开 */
export type ChartHit =
  | { kind: 'rank_pct'; row: RankPctRow }
  | { kind: 'cnci' | 'papers_new' | 'cites_threshold' | 'top_papers' | 'q_dist'; row: unknown }
  | { kind: string; row: unknown }

export function chartDataFor(
  data: ChartsData, group: string, name: string): ChartHit | null {
  const stem = stemOf(name)
  if (group === '_overview') {
    if (stem in data.forecast) return { kind: 'forecast', row: data.forecast[stem] }
    if (stem in data._overview) {
      return { kind: stem, row: (data._overview as Record<string, unknown>)[stem] }
    }
    return null
  }
  const disc = slugToDiscipline(data, group)
  if (!disc) return null
  if (stem === 'rank_pct' && data.rank_pct[disc]) {
    return { kind: 'rank_pct', row: data.rank_pct[disc] }
  }
  const per = data.disciplines[disc]
  if (per && stem in per) {
    return { kind: stem, row: (per as unknown as Record<string, unknown>)[stem] }
  }
  return null
}

/** 目录 slug（PlantAnimalScience）→ 台账学科英文名（Plant & Animal Science）。
    口径与 lib/labels.ts 的 disciplineSlug 同一条规则，这里做反向映射。 */
export function slugToDiscipline(data: ChartsData, slug: string): string | null {
  for (const disc of Object.keys(data.disciplines)) {
    if (disc.replace(/[^A-Za-z0-9]+/g, '') === slug) return disc
  }
  for (const disc of Object.keys(data.rank_pct)) {
    if (disc.replace(/[^A-Za-z0-9]+/g, '') === slug) return disc
  }
  return null
}
