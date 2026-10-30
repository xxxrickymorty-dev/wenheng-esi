/* 趋势图构建器：事件标注（markers）不得改动原有输出。
   快照是在**加 markers 参数之前**用同一份数据抓的——它过的意思是逐字节没变。 */
import { describe, expect, it } from 'vitest'
import { schoolTrendOption, trendTableOption, type ChartMarker } from './options'

const trend = {
  periods: ['202511', '202601', '202603', '202605', '202607', '202609'],
  series: [
    { disc: 'Chemistry', name_cn: '化学', color: '#4472C4', values: [88.1, 90.2, 91.5, 92.0, 93.1, 94.4] },
    { disc: 'Engineering', name_cn: '工程学', color: '#70AD47', values: [60.1, 61.2, 62.3, 63.4, 64.5, 65.6] },
  ],
  baseline: 100,
}

/* 与 202609 三校实测同形（昆工 [12]×6、海大 [9,10,11,11,11,12]） */
const schools = {
  periods: ['202511', '202601', '202603', '202605', '202607', '202609'],
  schools: [
    { name: '昆明理工大学', counts: [12, 12, 12, 12, 12, 12] },
    { name: '海南大学', counts: [9, 10, 11, 11, 11, 12] },
  ],
}

type Serie = { name?: string; data?: unknown[]; markPoint?: { data: Item[] }; markLine?: { data: Item[] } }
type Item = { name?: string; coord?: [string, number]; xAxis?: string }

const seriesOf = (opt: unknown) => (opt as { series: Serie[] }).series

describe('trendTableOption · 不传 markers', () => {
  it('输出与旧版逐字节一致（快照）', () => {
    expect(JSON.stringify(trendTableOption(trend))).toMatchSnapshot()
  })

  it('没有事件竖线这一条 series', () => {
    expect(seriesOf(trendTableOption(trend)).map((s) => s.name))
      .toEqual(['化学', '工程学', 'ESI1‰基线'])
  })
})

describe('trendTableOption · 传 markers', () => {
  const markers: ChartMarker[] = [
    { index: 2, text: '3 期转涨', kind: 'inflect' },
    { index: 5, text: '连续 4 期持平', kind: 'flat' },
  ]
  const opt = trendTableOption(trend, markers)

  it('原有三条例线的数据一个数没动', () => {
    const base = seriesOf(trendTableOption(trend))
    const withMarkers = seriesOf(opt)
    expect(JSON.stringify(withMarkers.slice(0, 3))).toBe(JSON.stringify(base))
  })

  it('事件按传入期次画竖线，文字原样', () => {
    const ev = seriesOf(opt)[3]
    expect(ev.name).toBe('事件')
    expect(ev.markLine?.data.map((d) => d.xAxis)).toEqual(['202603', '202609'])
    expect(ev.markLine?.data.map((d) => d.name)).toEqual(markers.map((m) => m.text))
  })
})

describe('schoolTrendOption · 事件标注', () => {
  const markers: ChartMarker[] = [
    { index: 1, text: '新进 1 个学科：微生物学', kind: 'enter', school: '海南大学' },
    { index: 5, text: '连续 6 期持平', kind: 'flat', school: '昆明理工大学' },
    { index: 5, text: '6 期追平昆明理工', kind: 'overtake', school: '昆明理工大学' },
    { index: 3, text: '3 期转涨', kind: 'inflect' },                  // 没有对应校 → 竖线
    { index: 99, text: '越界期次', kind: 'enter', school: '海南大学' }, // 越界 → 丢掉
  ]
  const opt = schoolTrendOption(schools, markers)
  const byName = new Map(seriesOf(opt).map((s) => [s.name, s]))

  it('每校一条线，数据与传入的 counts 一致', () => {
    expect(byName.get('昆明理工大学')?.data).toEqual([12, 12, 12, 12, 12, 12])
    expect(byName.get('海南大学')?.data).toEqual([9, 10, 11, 11, 11, 12])
  })

  it('markPoint 落在正确的期次下标与该期数值上', () => {
    const hai = byName.get('海南大学')?.markPoint?.data ?? []
    expect(hai).toHaveLength(1)                       // 越界那条没混进来
    const [period, value] = hai[0].coord ?? ['', -1]
    expect(schools.periods.indexOf(period)).toBe(1)   // 与 markers[0].index 同一下标
    expect(value).toBe(10)                            // 该期计数，直接取同源数据
  })

  it('同一期两条事件都画在该校线上，文字原样', () => {
    const km = byName.get('昆明理工大学')?.markPoint?.data ?? []
    expect(km.map((d) => d.name)).toEqual(['连续 6 期持平', '6 期追平昆明理工'])
    expect(km.map((d) => schools.periods.indexOf(d.coord?.[0] ?? ''))).toEqual([5, 5])
  })

  it('对不上任何一条线的事件画成竖线，不静默丢', () => {
    const ev = byName.get('事件')
    expect(ev?.markLine?.data.map((d) => d.xAxis)).toEqual(['202605'])
  })

  it('不传 markers 时没有 markPoint / 事件竖线', () => {
    const plain = schoolTrendOption(schools)
    expect(seriesOf(plain).map((s) => s.name)).toEqual(['昆明理工大学', '海南大学'])
    expect(seriesOf(plain).every((s) => !s.markPoint && !s.markLine)).toBe(true)
  })

  it('该期没数（窗口缺口）的点不标——不替它猜一个位置', () => {
    const gap = { periods: ['202511', '202601'], schools: [{ name: '云南大学', counts: [null, 13] }] }
    const o = schoolTrendOption(gap, [{ index: 0, text: '新进 1 个学科：数学', kind: 'enter', school: '云南大学' }])
    expect(seriesOf(o)[0].markPoint).toBeUndefined()
  })
})
