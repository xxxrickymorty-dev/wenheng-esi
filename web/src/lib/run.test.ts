/* 票 05 单测：执行条只认同期次（A3 回归守卫）+ 本屏该看哪个任务。 */

import { describe, expect, it } from 'vitest'
import { choosePeriodJobId, pickRunForPeriod } from './run'

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

describe('choosePeriodJobId', () => {
  const candidate = { id: 'j-cand', period: '202607' }

  it('候选任务同规范期次 → 用候选', () => {
    expect(choosePeriodJobId('202607', '202607', 'j-cand', candidate, 'j-fallback')).toBe('j-cand')
  })

  it('候选是别期的（过期链）→ 回退服务端筛过的 lastJob', () => {
    expect(choosePeriodJobId('202607', '202607', 'j-cand',
                             { id: 'j-cand', period: '202605' }, 'j-fallback')).toBe('j-fallback')
    expect(choosePeriodJobId('202607', '202607', null, null, 'j-fallback')).toBe('j-fallback')
  })

  it('没选期次 / 没有回退 → null', () => {
    expect(choosePeriodJobId(null, '202607', 'j-cand', candidate, 'j-fallback')).toBeNull()
    expect(choosePeriodJobId('202607', '202607', null, null, null)).toBeNull()
  })
})
