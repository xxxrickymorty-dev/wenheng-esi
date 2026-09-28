/* 票 05 单测：执行条只认同期次（A3 回归守卫）。 */

import { describe, expect, it } from 'vitest'
import { pickRunForPeriod } from './run'

const run = (period: string) => ({ requestedPeriod: period, jobId: `j-${period}` })

describe('pickRunForPeriod', () => {
  it('同期次 → 原样返回', () => {
    const r = run('202607')
    expect(pickRunForPeriod(r, '202607')).toBe(r)
  })

  it('别期次 → null（不把别期的执行条画到本屏）', () => {
    expect(pickRunForPeriod(run('202609'), '202607')).toBeNull()
  })

  it('没有运行 / 没选期次 → null', () => {
    expect(pickRunForPeriod(null, '202607')).toBeNull()
    expect(pickRunForPeriod(undefined, '202607')).toBeNull()
    expect(pickRunForPeriod(run('202607'), null)).toBeNull()
  })
})
