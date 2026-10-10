/* 票 01 单测：对话前门槽位的纯函数（ADR-0003：不引 jsdom）。 */

import { describe, expect, it } from 'vitest'
import { clearSlot, conversationTitle, emptySlots, hasSlots } from './dialog'

describe('槽位（可显示、可清、回未设）', () => {
  it('空态：两格都没设', () => {
    expect(emptySlots()).toEqual({ period: '', intent: '' })
    expect(hasSlots(emptySlots())).toBe(false)
  })

  it('清期次：回到未设，意图不动', () => {
    const s = clearSlot({ period: '202609', intent: '出报告' }, 'period')
    expect(s).toEqual({ period: '', intent: '出报告' })
    expect(hasSlots(s)).toBe(true)
  })

  it('清意图：回到未设，期次不动', () => {
    expect(clearSlot({ period: '202609', intent: '出报告' }, 'intent'))
      .toEqual({ period: '202609', intent: '' })
  })

  it('两格都清掉 = 回到未设状态', () => {
    const s = clearSlot(clearSlot({ period: '202609', intent: '出报告' }, 'period'), 'intent')
    expect(s).toEqual(emptySlots())
    expect(hasSlots(s)).toBe(false)
  })
})

describe('对话标题（取第一句话，不编）', () => {
  it('折叠空白', () => {
    expect(conversationTitle('  帮我做 9 月\n的报告 ')).toBe('帮我做 9 月 的报告')
  })

  it('超长截断加省略号', () => {
    const long = '帮我'.repeat(30)
    const t = conversationTitle(long)
    expect(t.length).toBe(40)
    expect(t.endsWith('…')).toBe(true)
  })
})
