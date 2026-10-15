/* 票 04 单测：词表与禁用词（含「数字图书馆」绝迹守卫）。 */

import { describe, expect, it } from 'vitest'
import { BANNED_UI_TERMS, findBanned } from './banned'
import { TERMS } from './terms'

describe('核心词表 TERMS', () => {
  it('每个词非空，且不得含被禁称谓「数字图书馆」', () => {
    for (const [key, value] of Object.entries(TERMS)) {
      expect(value.length, key).toBeGreaterThan(0)
      expect(value.includes('数字图书馆'), key).toBe(false)
    }
  })

  it('图书馆品牌与短标签按定案', () => {
    expect(TERMS.libraryBrand).toBe('云南大学图书馆')
    expect(TERMS.library).toBe('陈列馆')
    expect(TERMS.signAction).toBe('签单')
    expect(TERMS.redList).toBe('红色件清单')
  })
})

describe('禁用词表 BANNED_UI_TERMS / findBanned', () => {
  it('无空项、无重复', () => {
    for (const t of BANNED_UI_TERMS) expect(t.length).toBeGreaterThan(0)
    expect(new Set(BANNED_UI_TERMS).size).toBe(BANNED_UI_TERMS.length)
  })

  it('能抓住典型违规', () => {
    expect(findBanned('请看 /api/me 的返回')).toContain('/api')
    expect(findBanned('task_runs 与 state_history 都在')).toContain('state_history')
    expect(findBanned('本次断言全过')).toContain('断言')
    expect(findBanned('旧稿在 _superseded/ 里')).toContain('_superseded')
    expect(findBanned('打开 /app/?demo=running')).toContain('?demo=')
    // 2026-10-15 UX 评估：内部黑话与模型串
    expect(findBanned('盾 · 2 个数字已登记')).toContain('盾')
    expect(findBanned('规划后端：openai:deepseek-v4.1-flash')).toEqual(
      expect.arrayContaining(['规划后端', 'openai:', 'deepseek']))
  })

  it('干净文案零命中，且结果去重', () => {
    expect(findBanned('这一版报告等你复核签单。')).toEqual([])
    expect(findBanned('台账文件可能正被占用，重新检查')).toEqual([])
    const dup = findBanned('/api 与 /api 又 /api')
    expect(dup.filter((t) => t === '/api')).toHaveLength(1)
  })
})
