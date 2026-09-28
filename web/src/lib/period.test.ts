/* 票 02 单测：期次上下文的纯函数（ADR-0003：不引 jsdom，DOM 薄壳不进单测）。 */

import { describe, expect, it } from 'vitest'
import { buildPeriodUrl, isValidPeriod, parsePeriod } from './period'

describe('isValidPeriod（与后端期次名规则一致）', () => {
  it('接受 6 位期次与带后缀的复现期次', () => {
    expect(isValidPeriod('202607')).toBe(true)
    expect(isValidPeriod('202605_复现')).toBe(true)
    expect(isValidPeriod('202605_fix-2')).toBe(true)
  })

  it('拒绝非法形状', () => {
    for (const v of ['', '20260', '2026070', '2026-07', 'abc', '202607_', '_202607', ' 202607 ', null, undefined, 202607]) {
      expect(isValidPeriod(v), String(v)).toBe(false)
    }
  })
})

describe('parsePeriod（缺省回退，不猜）', () => {
  it('取到合法期次', () => {
    expect(parsePeriod('?period=202607')).toBe('202607')
    expect(parsePeriod('?view=red&period=202605_复现')).toBe('202605_复现')
  })

  it('缺失或非法 → 回退 fallback；没有 fallback → null', () => {
    expect(parsePeriod('', '202607')).toBe('202607')
    expect(parsePeriod('?view=red', '202607')).toBe('202607')
    expect(parsePeriod('?period=', '202607')).toBe('202607')
    expect(parsePeriod('?period=bad', '202607')).toBe('202607')
    expect(parsePeriod('')).toBeNull()
    expect(parsePeriod('?period=bad')).toBeNull()
  })
})

describe('buildPeriodUrl（写期次、保其它参数）', () => {
  it('覆盖已有期次，保留 view', () => {
    expect(buildPeriodUrl('/app/?view=report&period=202607', '202609'))
      .toBe('/app/?view=report&period=202609')
  })

  it('没有期次时补上', () => {
    expect(buildPeriodUrl('/app/?view=charts', '202607')).toBe('/app/?view=charts&period=202607')
    expect(buildPeriodUrl('/app/', '202607')).toBe('/app/?period=202607')
  })

  it('保留 hash 与其它参数', () => {
    expect(buildPeriodUrl('/app/?view=reading&section=一&period=202605', '202607'))
      .toBe('/app/?view=reading&section=%E4%B8%80&period=202607')
    expect(buildPeriodUrl('http://127.0.0.1:8080/app/?period=202605#top', '202607'))
      .toBe('/app/?period=202607#top')
  })
})
