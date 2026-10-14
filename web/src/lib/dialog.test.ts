/* 票 01 单测：对话前门槽位的纯函数（ADR-0003：不引 jsdom）。 */

import { describe, expect, it } from 'vitest'
import { clearSlot, conversationTitle, emptySlots, hasSlots,
         parseNdjsonChunks, sessionIdFromSearch, withSessionId } from './dialog'

describe('进度流的行解析（票 12）：半行留缓冲、坏行丢弃', () => {
  it('整行解析 + 半行跨块拼回', () => {
    const a = parseNdjsonChunks(
      '', '{"event":"stage","stage":"理解","text":"正在理解这句话…"}\n{"event":"do')
    expect(a.events).toEqual([{ event: 'stage', stage: '理解', text: '正在理解这句话…' }])
    expect(a.buffer).toBe('{"event":"do')
    const b = parseNdjsonChunks(a.buffer, 'ne","payload":{"kind":"query"}}\n')
    expect(b.events).toEqual([{ event: 'done', payload: { kind: 'query' } }])
    expect(b.buffer).toBe('')
  })

  it('坏行与空行丢弃，不炸', () => {
    const r = parseNdjsonChunks('', 'not json\n\n{"event":"error","error":"x"}\n')
    expect(r.events).toEqual([{ event: 'error', error: 'x' }])
  })
})

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

describe('会话 id（URL `s`，票 11）', () => {
  it('合法形状读出；缺省/不合法当没带', () => {
    expect(sessionIdFromSearch('?s=s-20261013-0a1b2c3d')).toBe('s-20261013-0a1b2c3d')
    expect(sessionIdFromSearch('?ask=x&s=s-20261013-0a1b2c3d')).toBe('s-20261013-0a1b2c3d')
    expect(sessionIdFromSearch('?s=乱七八糟')).toBe('')
    expect(sessionIdFromSearch('?s=s-20261013-0A1B2C3D')).toBe('')
    expect(sessionIdFromSearch('')).toBe('')
  })

  it('回写保留其他参数；空 id 清掉', () => {
    expect(withSessionId('?ask=x', 's-20261013-0a1b2c3d')).toBe('ask=x&s=s-20261013-0a1b2c3d')
    expect(withSessionId('?s=s-20261013-0a1b2c3d&ask=x', '')).toBe('ask=x')
    expect(withSessionId('', 's-20261013-0a1b2c3d')).toBe('s=s-20261013-0a1b2c3d')
  })
})
