/* 图册同源数据查找层：slug 反解、文件名取键、按（组，图名）命中数据。
   数字本身在后端算好——这里钉住的是「查找不打错门」。 */
import { describe, expect, it } from 'vitest'
import { chartDataFor, slugToDiscipline, stemOf, type ChartsData } from './chartsData'

const data: ChartsData = {
  schema: 2,
  end_period: '202607',
  periods: ['202507', '202607'],
  rank_pct: {
    'Plant & Animal Science': {
      name_cn: '植物与动物学', periods: ['202507'],
      series: { intl: [29.37], cn: [30.86] },
      labels: { intl: '国际排名百分位值', cn: '国内排名百分位值' },
    },
  },
  disciplines: {
    'Plant & Animal Science': {
      name_cn: '植物与动物学',
      papers_new: { periods: ['202509'], values: [3] },
    },
  },
  _overview: { '1pct': { items: [{ name_cn: '工程学', ratio: 706.16, gap: 0 }] } },
  forecast: {},
}

describe('stemOf', () => {
  it('剥掉 .png 后缀', () => {
    expect(stemOf('rank_pct.png')).toBe('rank_pct')
    expect(stemOf('forecast_1_cites.png')).toBe('forecast_1_cites')
  })
})

describe('slugToDiscipline', () => {
  it('目录 slug 反解回台账学科英文名', () => {
    expect(slugToDiscipline(data, 'PlantAnimalScience')).toBe('Plant & Animal Science')
  })
  it('未知 slug 返回 null（页面回退 PNG）', () => {
    expect(slugToDiscipline(data, 'Nope')).toBeNull()
  })
})

describe('chartDataFor', () => {
  it('学科图：分组目录 + 文件名命中 papers_new', () => {
    const hit = chartDataFor(data, 'PlantAnimalScience', 'papers_new.png')
    expect(hit?.kind).toBe('papers_new')
  })
  it('rank_pct 走独立键', () => {
    const hit = chartDataFor(data, 'PlantAnimalScience', 'rank_pct.png')
    expect(hit?.kind).toBe('rank_pct')
  })
  it('概览图直接落 _overview 键', () => {
    const hit = chartDataFor(data, '_overview', '1pct.png')
    expect(hit?.kind).toBe('1pct')
  })
  it('缺数据的图（老期次预测图）如实返回 null', () => {
    expect(chartDataFor(data, '_overview', 'forecast_1_cites.png')).toBeNull()
  })
})
