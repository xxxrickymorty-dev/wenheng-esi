/* 图册／预测台共用：一种图型一个 EChartsOption 构建器。
   观感与 `src/charts.py` 的 PNG 同口径（同色、同轴、同标签规则），
   数字全部来自 lib/chartsData 的同源载荷——这里只做形状与格式化，不换算数值。
   ECharts 自带的回调参数类型面很宽（value 可能是数组/对象），这里只按我们用到的
   字段取值，出口统一 `as EChartsOption`——形状由真件渲染验证守着。 */

import type { EChartsOption } from 'echarts'
import type {
  CollegeItem, DisciplineCharts, ForecastSeries, Num, OnePctItem, RankPctRow,
  RankTableRow, TrendTableRow,
} from '../lib/chartsData'

export const FONT = '"Microsoft YaHei","Noto Sans SC",sans-serif'
const INK = '#15222B'
const INK2 = '#43525C'
const LINE = '#D8D2C2'
const GRID = '#E8EAED'
const C_BLUE = '#4472C4'
const C_GREEN = '#70AD47'
const C_ORANGE = '#ED7D31'
const PURPLE = '#B4A7D6'
const LGREEN = '#A9D18E'
const RED = '#FF0000'

const baseText = { color: INK2, fontSize: 11, fontFamily: FONT }

const fmt2 = (v: Num) => (v == null ? '—' : v.toFixed(2) + '%')
const fmtInt = (v: Num) => (v == null ? '—' : Math.round(v).toLocaleString('en-US'))

/* 回调只取这些字段（数字都来自同源载荷） */
type Param = { dataIndex?: number; value?: unknown; name?: string; percent?: unknown;
               seriesName?: string; marker?: string; data?: { pct?: unknown } }
const asFmt = (f: (p: Param) => string) => f as unknown as (p: never) => string
const asTip = (f: (ps: Param[]) => string) => f as unknown as (p: never) => string

/** 端点标签：与 PNG 的 `_ends` 同规——只标首末两点（2026-10-26 馆员批注整改） */
function endLabels(n: number, fmt: (v: Num) => string, position: 'top' | 'bottom' = 'top') {
  return {
    show: true, fontFamily: FONT, fontSize: 11, color: INK, position,
    formatter: asFmt((p) =>
      p.value == null || (p.dataIndex !== 0 && p.dataIndex !== n - 1)
        ? '' : fmt(p.value as number)),
  }
}

/** 标签布局：挤了就挪开——不藏数字（复核场景每个数都要看得见）。
    ⚠ labelLayout 是 series 级配置，挂在 label 里不生效（2026-10-28 实踩）。 */
const LX = { moveOverlap: 'shiftX' as const }   // 柱/点标签：横向让位
const LY = { moveOverlap: 'shiftY' as const }   // 端点标签：纵向让位

/** 全点标签（柱/点上方；复核场景数字不许藏） */
const allLabels = (fmt: (v: Num) => string) => ({
  show: true, fontFamily: FONT, fontSize: 10, color: INK, position: 'top' as const,
  formatter: asFmt((p) => (p.value == null ? '' : fmt(p.value as number))),
})

const catAxis = (data: string[], rotate = 0, fontSize = 10.5) => ({
  type: 'category' as const, data,
  axisTick: { show: false }, axisLine: { lineStyle: { color: LINE } },
  // 期次/季度这类短标签全量显示（PNG 口径）——自动隐藏会在窄槽位吞掉一半期次
  axisLabel: { color: INK2, fontSize, fontFamily: FONT, rotate,
               interval: 0, hideOverlap: false },
})

const valAxis = (extra?: Record<string, unknown>) => ({
  type: 'value' as const,
  axisLabel: { color: INK2, fontSize: 10.5, fontFamily: FONT },
  splitLine: { lineStyle: { color: GRID } },
  ...extra,
})

const legendTop = (extra?: Record<string, unknown>) => ({
  top: 2, left: 'center', itemWidth: 14, itemHeight: 2, itemGap: 10,
  textStyle: { color: INK2, fontSize: 10.5, fontFamily: FONT }, ...extra,
})

const legendBottom = (extra?: Record<string, unknown>) => ({
  bottom: 0, left: 'center', itemWidth: 14, itemHeight: 2,
  textStyle: { color: INK2, fontSize: 10.5, fontFamily: FONT }, ...extra,
})

/* ---------- ① 国际／国内排名百分位（反向轴，只标首末） ---------- */

export function rankPctOption(row: RankPctRow): EChartsOption {
  const ri = row.series.intl
  const rc = row.series.cn
  const yv = [...ri, ...rc].filter((v): v is number => v != null)
  const pad = yv.length ? (Math.max(...yv) - Math.min(...yv)) * 0.10 : 1
  return {
    textStyle: baseText,
    legend: legendTop(),
    tooltip: { trigger: 'axis', confine: true, valueFormatter: (v: Num) => fmt2(v) },
    grid: { left: 56, right: 18, top: 30, bottom: 38 },    // 斜排期次需要额外底部空间
    xAxis: catAxis(row.periods, 32, 10),
    yAxis: valAxis({
      inverse: true,                                  // 百分位越小＝排名越好＝越靠上
      min: Math.floor((Math.min(...yv) - pad) * 100) / 100,
      max: Math.ceil((Math.max(...yv) + pad) * 100) / 100,
      axisLabel: { formatter: (v: number) => v.toFixed(2) + '%', color: INK2, fontSize: 10.5, fontFamily: FONT },
    }),
    series: [
      { name: row.labels.intl, type: 'line', data: ri, symbol: 'circle', symbolSize: 5,
        itemStyle: { color: C_BLUE }, lineStyle: { width: 1.4, color: C_BLUE },
        label: endLabels(row.periods.length, fmt2, 'top'), labelLayout: LY },
      { name: row.labels.cn, type: 'line', data: rc, symbol: 'circle', symbolSize: 5,
        itemStyle: { color: C_GREEN }, lineStyle: { width: 1.4, color: C_GREEN },
        label: endLabels(row.periods.length, fmt2, 'bottom'), labelLayout: LY },
    ],
  } as unknown as EChartsOption
}

/* ---------- ② CNCI（原始值 + 1.0 国际均值基准线，逐点标数） ---------- */

export function cnciOption(row: NonNullable<DisciplineCharts['cnci']>): EChartsOption {
  const withBase = [...row.values, row.baseline].filter((v): v is number => v != null)
  const lo = Math.min(...withBase)
  const hi = Math.max(...withBase)
  const pad = (hi - lo) * 0.18
  // 刻度两位小数再去尾零——toPrecision(2) 会把 1.05 舍成 "1.1"，跟 1.1 撞字
  const fmtG = (v: Num) => (v == null ? '' : Number(v.toFixed(2)).toString())
  return {
    textStyle: baseText,
    legend: legendTop(),
    tooltip: { trigger: 'axis', confine: true, valueFormatter: (v: Num) => (v == null ? '—' : v.toFixed(2)) },
    grid: { left: 40, right: 16, top: 30, bottom: 38 },    // 斜排期次需要额外底部空间
    xAxis: catAxis(row.periods, 32, 10),
    yAxis: valAxis({
      min: Math.floor((lo - pad) * 10) / 10, max: Math.ceil((hi + pad) * 10) / 10,
      axisLabel: { formatter: (v: number) => fmtG(v), color: INK2, fontSize: 10.5, fontFamily: FONT },
    }),
    series: [
      { name: 'CNCI 值', type: 'line', data: row.values, symbol: 'circle', symbolSize: 5,
        itemStyle: { color: C_BLUE }, lineStyle: { width: 1.4, color: C_BLUE },
        label: allLabels((v) => (v == null ? '' : v.toFixed(2))), labelLayout: LX },
      { name: 'CNCI 国际均值', type: 'line', data: row.periods.map(() => row.baseline),
        symbol: 'circle', symbolSize: 5,
        itemStyle: { color: C_GREEN }, lineStyle: { width: 1.4, color: C_GREEN },
        label: allLabels(fmtG), labelLayout: LX },
    ],
  } as unknown as EChartsOption
}

/* ---------- ③ 新增发文量（差分柱，0 必须在轴内，整数标数） ---------- */

export function papersNewOption(row: NonNullable<DisciplineCharts['papers_new']>): EChartsOption {
  const vals = row.values
  const hi = Math.max(0, ...vals.filter((v): v is number => v != null))
  return {
    textStyle: baseText,
    legend: legendTop({ left: 'right' }),
    tooltip: { trigger: 'axis', confine: true, valueFormatter: fmtInt },
    grid: { left: 40, right: 16, top: 30, bottom: 38 },    // 斜排期次需要额外底部空间
    xAxis: catAxis(row.periods, 32, 10),
    yAxis: valAxis({
      min: (v: { min: number }) => Math.min(0, v.min),
      max: Math.ceil(hi / 10) * 10 + 10,
      axisLabel: { formatter: '{value}', color: INK2, fontSize: 10.5, fontFamily: FONT },
    }),
    series: [{
      name: '新增发文量', type: 'bar', data: vals, barWidth: '40%',
      itemStyle: { color: C_BLUE },
      label: allLabels(fmtInt), labelLayout: LX,
    }],
  } as unknown as EChartsOption
}

/* ---------- ④ 被引频次与 ESI 阈值（双线，首末标数千分位） ---------- */

export function citesThresholdOption(
  row: NonNullable<DisciplineCharts['cites_threshold']>): EChartsOption {
  const n = row.periods.length
  return {
    textStyle: baseText,
    legend: legendTop(),
    tooltip: { trigger: 'axis', confine: true, valueFormatter: fmtInt },
    grid: { left: 62, right: 18, top: 30, bottom: 38 },    // 斜排期次需要额外底部空间
    xAxis: catAxis(row.periods, 32, 10),
    yAxis: valAxis({
      axisLabel: { formatter: (v: number) => Math.round(v).toLocaleString('en-US'), color: INK2, fontSize: 10.5, fontFamily: FONT },
    }),
    series: [
      { name: '被引频次', type: 'line', data: row.cites, symbol: 'circle', symbolSize: 5,
        itemStyle: { color: C_BLUE }, lineStyle: { width: 1.4, color: C_BLUE },
        label: endLabels(n, fmtInt, 'top'), labelLayout: LY },
      { name: 'ESI 阈值', type: 'line', data: row.threshold, symbol: 'circle', symbolSize: 5,
        itemStyle: { color: C_GREEN }, lineStyle: { width: 1.4, color: C_GREEN },
        label: endLabels(n, fmtInt, 'bottom'), labelLayout: LY },
    ],
  } as unknown as EChartsOption
}

/* ---------- ⑤ 顶尖论文量（截断轴，逐点标数） ---------- */

export function topPapersOption(row: NonNullable<DisciplineCharts['top_papers']>): EChartsOption {
  const vals = row.values.filter((v): v is number => v != null)
  const lo = Math.min(...vals)
  const hi = Math.max(...vals)
  const pad = Math.max(1, (hi - lo) * 0.25)
  return {
    textStyle: baseText,
    legend: legendTop({ left: 'right' }),
    tooltip: { trigger: 'axis', confine: true, valueFormatter: fmtInt },
    grid: { left: 36, right: 16, top: 30, bottom: 38 },    // 斜排期次需要额外底部空间
    xAxis: catAxis(row.periods, 32, 10),
    yAxis: valAxis({
      // 原件是截断轴（下界跟本学科最小值走），保留这个观感
      min: Math.max(0, Math.floor(lo - pad)), max: Math.ceil(hi + pad),
      axisLabel: { formatter: '{value}', color: INK2, fontSize: 10.5, fontFamily: FONT },
    }),
    series: [{
      name: '顶尖论文发文量', type: 'bar', data: row.values, barWidth: '40%',
      itemStyle: { color: C_BLUE },
      label: allLabels(fmtInt), labelLayout: LX,
    }],
  } as unknown as EChartsOption
}

/* ---------- ⑥ Q1–Q4 分区占比（三实体分组柱，逐柱标数） ---------- */

export function qDistOption(row: NonNullable<DisciplineCharts['q_dist']>): EChartsOption {
  const flat = row.entities.flatMap((e) => e.values).filter((v): v is number => v != null)
  const hi = Math.max(...flat)
  return {
    textStyle: baseText,
    legend: legendTop({ itemWidth: 12, itemHeight: 8 }),
    tooltip: { trigger: 'axis', confine: true, axisPointer: { type: 'shadow' }, valueFormatter: (v: Num) => (v == null ? '—' : v + '%') },
    grid: { left: 42, right: 12, top: 50, bottom: 24 },
    xAxis: catAxis(['Q1', 'Q2', 'Q3', 'Q4'], 0, 11),
    yAxis: valAxis({
      // 顶端留标签位：三系列标签逐级抬 16px（见下），最高柱上方要有余量
      max: Math.min(100, Math.ceil((hi + 14) / 20) * 20),
      axisLabel: { formatter: '{value}%', color: INK2, fontSize: 10.5, fontFamily: FONT },
    }),
    series: row.entities.map((e, j) => ({
      name: e.name, type: 'bar', data: e.values, barGap: '12%', barCategoryGap: '55%',
      itemStyle: { color: e.color },
      // 三系列标签跨系列不参与统一布局（labelLayout 只算本系列）——
      // 用 labelLayout.dy 按系列逐级抬 16px（≥标签盒高 12px）：
      // 同高柱组的标签也分层不压。⚠ label.offset 在本版本不生效（实踩）。
      label: { ...allLabels((v) => (v == null ? '' : v + '%')), fontSize: 9.5 },
      labelLayout: { moveOverlap: 'shiftY', dy: -j * 16 },
    })),
  } as unknown as EChartsOption
}

/* ---------- ⑦ 1% 接近度（紫实际＋绿差距堆叠，红基线） ---------- */

export function onePctOption(row: { items: OnePctItem[] }): EChartsOption {
  const items = row.items
  const hi = Math.max(100, ...items.map((i) => (i.ratio ?? 0)))
  const xmax = Math.ceil(hi / 100) * 100
  return {
    textStyle: baseText,
    legend: legendBottom({ itemWidth: 12, itemHeight: 8 }),
    tooltip: {
      confine: true, trigger: 'axis', axisPointer: { type: 'shadow' },
      formatter: asTip((ps) => {
        const bars = ps.filter((p) => p.seriesName !== 'ESI前1%基线')
        return (bars[0]?.name ?? '') + '<br>' +
          bars.map((p) => `${p.marker ?? ''}${p.seriesName}：${fmt2(p.value as Num)}`).join('<br>')
      }),
    },
    grid: { left: 92, right: 24, top: 8, bottom: 34 },
    xAxis: valAxis({
      min: 0, max: xmax, interval: 100,
      axisLabel: { formatter: '{value}%', color: INK2, fontSize: 10, fontFamily: FONT },
      splitLine: { show: false },
    }),
    yAxis: {
      type: 'category', data: items.map((i) => i.name_cn),
      axisTick: { show: false }, axisLine: { lineStyle: { color: LINE } },
      axisLabel: { color: INK, fontSize: 10.5, fontFamily: FONT },
    },
    series: [
      { name: '与ESI前1%的接近度', type: 'bar', stack: 't', barWidth: '62%',
        data: items.map((i) => i.ratio), itemStyle: { color: PURPLE },
        label: { show: true, position: 'insideLeft', distance: 5, fontFamily: FONT,
                 fontSize: 9.5, color: INK,
                 formatter: asFmt((p) => fmt2(p.value as Num)) },
        markLine: { silent: true, symbol: 'none', data: [{ xAxis: 100 }],
                    lineStyle: { color: RED, width: 1.4 }, label: { show: false } } },
      { name: '与ESI前1%的差距', type: 'bar', stack: 't', barWidth: '62%',
        data: items.map((i) => i.gap), itemStyle: { color: LGREEN } },
    ],
  } as unknown as EChartsOption
}

/* ---------- ⑧ 1‰ 接近度（已进 1% 学科；标签贴柱尾） ---------- */

export function onePermilleOption(row: { items: OnePctItem[] }): EChartsOption {
  return {
    textStyle: baseText,
    legend: legendBottom({ itemWidth: 12, itemHeight: 8 }),
    tooltip: { trigger: 'axis', confine: true, axisPointer: { type: 'shadow' }, valueFormatter: fmt2 },
    grid: { left: 92, right: 46, top: 8, bottom: 34 },
    xAxis: valAxis({
      min: 0, max: 105,
      axisLabel: { formatter: '{value}%', color: INK2, fontSize: 10, fontFamily: FONT },
    }),
    yAxis: {
      type: 'category', data: row.items.map((i) => i.name_cn),
      axisTick: { show: false }, axisLine: { lineStyle: { color: LINE } },
      axisLabel: { color: INK, fontSize: 10.5, fontFamily: FONT },
    },
    series: [
      { name: '1‰接近度', type: 'bar', stack: 't', barWidth: '62%',
        data: row.items.map((i) => i.ratio), itemStyle: { color: PURPLE },
        label: { show: true, position: 'right', distance: 4, fontFamily: FONT,
                 fontSize: 9.5, color: INK, formatter: asFmt((p) => fmt2(p.value as Num)) } },
      { name: '与前1‰差距', type: 'bar', stack: 't', barWidth: '62%',
        data: row.items.map((i) => i.gap), itemStyle: { color: LGREEN } },
    ],
  } as unknown as EChartsOption
}

/* ---------- ⑨ 我校 ESI 排名情况（双轴反序三线；数据表由页面另画） ---------- */

export function rankTableOption(row: RankTableRow): EChartsOption {
  const n = row.periods.length
  const mk = (key: 'cn' | 'cn_uni' | 'intl', yAxisIndex = 0) => ({
    name: row.labels[key].label, type: 'line', yAxisIndex,
    data: row.series[key], symbol: 'circle', symbolSize: 5,
    itemStyle: { color: row.labels[key].color },
    lineStyle: { width: 1.6, color: row.labels[key].color },
    label: endLabels(n, fmtInt, 'top'), labelLayout: LY,
  })
  return {
    textStyle: baseText,
    legend: legendBottom(),
    tooltip: { trigger: 'axis', confine: true, valueFormatter: fmtInt },
    title: { text: '我校ESI排名情况', left: 'center', top: 0,
             textStyle: { color: '#1F1F1F', fontSize: 13, fontFamily: FONT, fontWeight: 600 } },
    grid: { left: 46, right: 52, top: 32, bottom: 44 },
    xAxis: catAxis(row.periods, 32, 10),
    yAxis: [
      { type: 'value', inverse: true, min: 120, max: 170, interval: 5,
        axisLabel: { color: INK2, fontSize: 10, fontFamily: FONT },
        splitLine: { lineStyle: { color: GRID } } },
      { type: 'value', inverse: true, min: 400, max: 1400, interval: 200,
        axisLabel: { color: INK2, fontSize: 10, fontFamily: FONT },
        splitLine: { show: false } },
    ],
    series: [mk('cn'), mk('cn_uni'), mk('intl', 1)],
  } as unknown as EChartsOption
}

/* ---------- ⑩ 发展趋势（1‰ 接近度前 4 学科 + 100% 红基线；表另画） ---------- */

export function trendTableOption(row: TrendTableRow): EChartsOption {
  const n = row.periods.length
  return {
    textStyle: baseText,
    legend: legendBottom(),
    tooltip: { trigger: 'axis', confine: true, valueFormatter: fmt2 },
    title: { text: '我校主要学科近期发展趋势', left: 'center', top: 0,
             textStyle: { color: '#1F1F1F', fontSize: 13, fontFamily: FONT, fontWeight: 600 } },
    grid: { left: 52, right: 20, top: 30, bottom: 40 },
    xAxis: { ...catAxis(row.periods), axisLabel: { show: false },   // 期次只在下方表头出现
             axisTick: { show: false }, axisLine: { show: false } },
    yAxis: { type: 'value', min: 20, max: 100, interval: 20,
             axisLabel: { formatter: (v: number) => v.toFixed(2) + '%', color: INK2, fontSize: 10, fontFamily: FONT },
             splitLine: { lineStyle: { color: GRID } } },
    series: [
      ...row.series.map((s) => ({
        name: s.name_cn, type: 'line', data: s.values,
        symbol: 'circle', symbolSize: 5, itemStyle: { color: s.color },
        lineStyle: { width: 1.6, color: s.color },
        label: {
          show: true, fontFamily: FONT, fontSize: 10, color: INK, position: 'top' as const,
          formatter: asFmt((p) =>
            p.dataIndex === n - 1 && p.value != null ? fmt2(p.value as number) : ''),
        },
        labelLayout: LY,
      })),
      { name: 'ESI1‰基线', type: 'line', data: [],
        markLine: { silent: true, symbol: 'none', data: [{ yAxis: row.baseline }],
                    lineStyle: { color: RED, width: 1.4 },
                    label: { show: true, position: 'insideEndTop', formatter: 'ESI1‰ 基线 = 100%',
                             color: RED, fontSize: 10, fontFamily: FONT } } },
    ],
  } as unknown as EChartsOption
}

/* ---------- ⑪⑫ 顶尖论文年代／学科分布 ---------- */

export function topByYearOption(row: { labels: string[]; values: Num[] }): EChartsOption {
  const hi = Math.max(0, ...row.values.filter((v): v is number => v != null))
  return {
    textStyle: baseText,
    title: { text: '顶尖论文年代分布（篇）', left: 'center', top: 0,
             textStyle: { color: '#1F1F1F', fontSize: 12, fontFamily: FONT, fontWeight: 600 } },
    tooltip: { trigger: 'axis', confine: true, valueFormatter: fmtInt },
    grid: { left: 36, right: 14, top: 32, bottom: 24 },
    xAxis: catAxis(row.labels, 0, 9.5),
    yAxis: valAxis({ max: Math.ceil((hi + 2) / 5) * 5,
                     axisLabel: { formatter: '{value}', color: INK2, fontSize: 10, fontFamily: FONT } }),
    series: [{
      name: '顶尖论文', type: 'bar', data: row.values, barWidth: '66%',
      itemStyle: { color: C_ORANGE },
      label: allLabels(fmtInt), labelLayout: LX,
    }],
  } as unknown as EChartsOption
}

export function topBySubjectOption(
  row: { items: { name_cn: string; value: Num }[] }): EChartsOption {
  const hi = Math.max(0, ...row.items.map((i) => (i.value ?? 0)))
  return {
    textStyle: baseText,
    title: { text: '顶尖论文学科分布（篇）', left: 'center', top: 0,
             textStyle: { color: '#1F1F1F', fontSize: 12, fontFamily: FONT, fontWeight: 600 } },
    tooltip: { trigger: 'axis', confine: true, valueFormatter: fmtInt },
    grid: { left: 36, right: 14, top: 32, bottom: 52 },
    xAxis: catAxis(row.items.map((i) => i.name_cn), 38, 9),
    yAxis: valAxis({ max: Math.ceil((hi + 2) / 5) * 5,
                     axisLabel: { formatter: '{value}', color: INK2, fontSize: 10, fontFamily: FONT } }),
    series: [{
      name: '顶尖论文', type: 'bar', data: row.items.map((i) => i.value), barWidth: '62%',
      itemStyle: { color: C_BLUE },
      label: allLabels(fmtInt), labelLayout: LX,
    }],
  } as unknown as EChartsOption
}

/* ---------- ⑬ 学院贡献双饼（<1.5% 已由后端并入「其他」，pct 也是后端出的） ---------- */

export function collegePieOption(row: { items: CollegeItem[] }, mode: 'cites' | 'papers'): EChartsOption {
  const donut = mode === 'papers'
  return {
    textStyle: baseText,
    tooltip: {
      confine: true, trigger: 'item',
      formatter: asFmt((p) =>
        `${p.name ?? ''}：${Number(p.value).toLocaleString('en-US')}（${Number(p.percent ?? 0).toFixed(2)}%）`),
    },
    series: [{
      type: 'pie', radius: donut ? ['34%', '62%'] : '62%',
      center: ['50%', '50%'],
      data: row.items.map((i) => ({ name: i.name, value: i.value, pct: i.pct,
                                    itemStyle: { color: i.color } })),
      label: { fontFamily: FONT, fontSize: 9.5, color: '#1F1F1F',
               formatter: asFmt((p) =>
                 `${p.name ?? ''}：${p.data?.pct == null ? '—' : Number(p.data.pct).toFixed(2)}%`) },
      labelLine: { length: 8, length2: 8, lineStyle: { color: '#A6A6A6', width: 0.6 } },
      startAngle: 90, clockwise: true,
    }],
  } as unknown as EChartsOption
}

/* ---------- ⑭ 预测图（报告章：实际＋模型拟合＋预测；序列出图时落档） ---------- */

export function forecastOption(row: ForecastSeries): EChartsOption {
  const allP = [...row.hist_periods, ...row.fut_periods]
  let xt = allP.map((p, i) => (p.endsWith('01') ? i : -1)).filter((i) => i >= 0)
  if (xt.length > 12) xt = xt.filter((_, i) => i % 2 === 0)
  const nH = row.hist_periods.length
  const series = row.columns.map((col) => {
    const fittedLen = col.fitted.length
    const fittedWithFuture: Num[] = [
      ...col.fitted,
      ...Array<Num>(Math.max(0, nH - fittedLen)).fill(null),
      ...col.future,
    ]
    return [
      { name: col.actual_label, type: 'line', data: col.actual,
        symbol: 'none', itemStyle: { color: col.actual_color },
        lineStyle: { width: 1.6, color: col.actual_color } },
      { name: col.model_label, type: 'line', data: fittedWithFuture,
        symbol: 'none', connectNulls: true,
        itemStyle: { color: col.model_color },
        lineStyle: { width: 1.4, type: 'dashed', color: col.model_color } },
    ]
  }).flat()
  return {
    textStyle: baseText,
    legend: legendBottom(),
    tooltip: { trigger: 'axis', confine: true },
    grid: { left: 56, right: 18, top: 16, bottom: 40 },
    xAxis: {
      ...catAxis(allP, 0, 9.5),
      axisLabel: { ...catAxis(allP, 0, 9.5).axisLabel,
                   interval: (i: number) => xt.includes(i), rotate: 0 },
    },
    yAxis: valAxis({ scale: true }),
    series,
  } as unknown as EChartsOption
}

/* ---------- ⑮ 预测台试跑图（历史实线＋预测虚线，红色分界线） ---------- */

export type RunHistoryRow = { period: number; metric1: Num; metric2: Num }
export type RunForecastRow = { period: number; metric1: Num; metric2: Num }

export function forecastRunOption(
  history: RunHistoryRow[], forecast: RunForecastRow[], metricNames: string[]): EChartsOption {
  const hp = history.map((r) => String(r.period))
  const fp = forecast.map((r) => String(r.period))
  const allP = [...hp, ...fp]
  const step = Math.max(1, Math.floor(allP.length / 10))
  const shown = allP.filter((_, i) => i % step === 0)
  if (allP.length && shown[shown.length - 1] !== allP[allP.length - 1]) shown.push(allP[allP.length - 1])
  const colors = [C_BLUE, C_GREEN]
  const series = metricNames.slice(0, 2).map((name, j) => {
    const key = (['metric1', 'metric2'] as const)[j]
    const hv = history.map((r) => r[key])
    const fv = forecast.map((r) => r[key])
    const bridge: Num[] = hv.length
      ? [...Array<Num>(hp.length - 1).fill(null), hv[hv.length - 1], ...fv]
      : fv
    return [
      { name: `${name}·历史`, type: 'line', data: hv, symbol: 'none',
        itemStyle: { color: colors[j] }, lineStyle: { width: 1.6, color: colors[j] } },
      { name: `${name}·预测`, type: 'line', data: bridge, symbol: 'none',
        connectNulls: true, itemStyle: { color: colors[j] },
        lineStyle: { width: 1.6, type: 'dashed', color: colors[j] } },
    ]
  }).flat()
  return {
    textStyle: baseText,
    legend: legendTop(),
    tooltip: { trigger: 'axis', confine: true },
    grid: { left: 52, right: 16, top: 28, bottom: 24 },
    xAxis: {
      ...catAxis(allP, 35, 9),
      axisLabel: { ...catAxis(allP, 35, 9).axisLabel,
                   interval: (i: number) => shown.includes(allP[i]) },
    },
    yAxis: valAxis({ scale: true, splitLine: { lineStyle: { color: '#D8D5CC' } } }),
    series: [
      ...series,
      { name: '数据／预测分界', type: 'line', data: [],
        markLine: { silent: true, symbol: 'none', data: [{ xAxis: hp.length - 0.5 }],
                    lineStyle: { color: '#B23A2A', width: 1 }, label: { show: false } } },
    ],
  } as unknown as EChartsOption
}
