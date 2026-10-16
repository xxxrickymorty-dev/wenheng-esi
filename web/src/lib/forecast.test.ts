/* 预测选模纯逻辑（2026-10-16）：「报告还是旧的」判定与改动清单。
   判据是**比值**：已保存的选择 vs 上次出稿实际用的选择；无快照＝无法核实，不显示提示。 */
import { describe, expect, it } from 'vitest'
import type { ForecastChoice, ForecastChoiceEntry, ForecastMeta } from '../api-forecast'
import {
  forecastAppliedDiffs, forecastAppliedStale, sameForecastChoice,
  savedForecastChoice, shortRouteLabel,
} from './forecast'

function meta(subjects: string[] = ['免疫学', '物理学']): ForecastMeta {
  return {
    routes: [
      { value: 'citation', label: '路线1 · 总被引 / ESI前1%被引阈值' },
      { value: 'rank', label: '路线2 · 国内排名 / 国内前1%机构数' },
    ],
    subjects,
  } as unknown as ForecastMeta
}

function entry(
  saved: ForecastChoice['choice'],
  applied: ForecastChoice['choice'] | null,
): ForecastChoiceEntry {
  return {
    loaded: true, loading: false, saving: false, error: '',
    choice: saved, saved, by: 'admin', at: '2026-10-16 12:12:42',
    applied: applied === null ? null : { choice: applied, by: 'admin', at: '2026-10-13 14:59:44', snapshot_at: '' },
  }
}

describe('shortRouteLabel', () => {
  it('取「·」后一段：全名 → 短名', () => {
    expect(shortRouteLabel('路线1 · 总被引 / ESI前1%被引阈值')).toBe('总被引')
    expect(shortRouteLabel('路线2 · 国内排名 / 国内前1%机构数')).toBe('国内排名')
  })
  it('没有「·」时原样返回', () => {
    expect(shortRouteLabel('总被引')).toBe('总被引')
  })
})

describe('sameForecastChoice / savedForecastChoice', () => {
  it('缺键＝空；只看 meta 里的路线×学科', () => {
    const m = meta()
    expect(sameForecastChoice({}, { citation: {} }, m)).toBe(true)
    expect(sameForecastChoice(
      { citation: { 免疫学: 'SARIMA模型' } },
      { citation: {} }, m)).toBe(false)
  })
  it('保存规范化：空值不落盘', () => {
    const out = savedForecastChoice(
      { citation: { 免疫学: 'SARIMA模型', 物理学: '' }, rank: {} }, meta())
    expect(out).toEqual({ citation: { 免疫学: 'SARIMA模型' }, rank: {} })
  })
})

describe('forecastAppliedStale（报告还是旧的）', () => {
  it('没出过稿（applied=null）＝无法核实，不判旧', () => {
    expect(forecastAppliedStale(entry({ citation: { 免疫学: 'SARIMA模型' } }, null), meta())).toBe(false)
    expect(forecastAppliedStale(null, meta())).toBe(false)
  })
  it('两边一致＝已生效；不一致＝旧报告', () => {
    const m = meta()
    const same = { citation: { 免疫学: 'SARIMA模型' } }
    expect(forecastAppliedStale(entry(same, same), m)).toBe(false)
    expect(forecastAppliedStale(entry(same, {}), m)).toBe(true)
    expect(forecastAppliedStale(entry({}, same), m)).toBe(true)
  })
  it('202607/202609 真实对照：空 vs 空 不提示；空 vs 改选 提示', () => {
    expect(forecastAppliedStale(entry({}, {}), meta())).toBe(false)
    expect(forecastAppliedStale(entry({ citation: { 免疫学: 'SARIMA模型' } }, {}), meta())).toBe(true)
  })
})

describe('forecastAppliedDiffs（改动清单）', () => {
  it('改选列「学科 → 模型」带路线短名', () => {
    const e = entry({ citation: { 免疫学: 'SARIMA模型' } }, {})
    expect(forecastAppliedDiffs(e, meta())).toEqual(['总被引：免疫学 → SARIMA模型'])
  })
  it('撤掉改选＝「恢复 V1 推荐」', () => {
    const e = entry({}, { citation: { 物理学: 'SARIMA模型' } })
    expect(forecastAppliedDiffs(e, meta())).toEqual(['总被引：物理学 → 恢复 V1 推荐'])
  })
  it('两路线各自列出', () => {
    const e = entry(
      { citation: { 免疫学: 'SARIMA模型' }, rank: { 物理学: 'Holt趋势模型' } },
      {})
    expect(forecastAppliedDiffs(e, meta())).toEqual([
      '总被引：免疫学 → SARIMA模型', '国内排名：物理学 → Holt趋势模型',
    ])
  })
})
