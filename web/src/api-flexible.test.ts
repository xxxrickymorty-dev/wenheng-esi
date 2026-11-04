/* reportBackend 单测（2026-11-04 票 1）：每意图出稿后端的读取口径——
   新契约字段（ctx 每意图 backend）优先，缺了回 meta.backend（同出
   flex_meta.json，旧产物也带着）；两处都没有 / 非字符串 → 空串（不标，不误标）。 */

import { describe, expect, it } from 'vitest'
import { reportBackend } from './api-flexible'

describe('reportBackend：每意图出稿后端', () => {
  it('新契约字段优先于 meta', () => {
    expect(reportBackend({ backend: 'rule', meta: { backend: 'deepseek-chat' } }))
      .toBe('rule')
    expect(reportBackend({ backend: 'deepseek-chat', meta: { backend: 'rule' } }))
      .toBe('deepseek-chat')
  })

  it('顶层缺了回 meta.backend（旧产物同源 flex_meta.json）', () => {
    expect(reportBackend({ meta: { backend: 'rule' } })).toBe('rule')
    expect(reportBackend({ meta: { backend: 'deepseek-chat' } }))
      .toBe('deepseek-chat')
  })

  it('两处都没有 → 空串（调用方不显示标记）', () => {
    expect(reportBackend({})).toBe('')
    expect(reportBackend({ meta: null })).toBe('')
    expect(reportBackend({ backend: '', meta: {} })).toBe('')
  })

  it('非字符串一律当缺省（不误标）', () => {
    expect(reportBackend({ backend: 3, meta: { backend: 0 } })).toBe('')
    expect(reportBackend({ backend: true, meta: { backend: ['rule'] } })).toBe('')
  })
})
