/* 回执条（AI 层工具调用的双面回执）的 chip 映射：receiptChips 纯函数（不引 jsdom）。
   渲染（ReceiptBar，回复气泡下方、仅 receipts 非空时出）在 DialogPage；这里只测
   「每条回执 → chip 的类名与文字」——含正常面与降级面。 */

import { describe, expect, it } from 'vitest'
import { receiptChips } from './DialogPage'
import type { DialogReceipt } from '../api-dialog'

const receipt = (over: Partial<DialogReceipt>): DialogReceipt => ({
  tool: 'inventory', label: '盘点', ok: true, summary: '四件齐',
  elapsed_ms: 12, args_digest: '', refused: false, ...over,
})

describe('回执条 chip（含 receipts 的回复渲染出回执）', () => {
  it('receipts 非空：每条一枚 chip；空清单不出 chip', () => {
    const chips = receiptChips([
      receipt({ label: '盘点' }),
      receipt({ tool: 'verify', label: '产物核对', elapsed_ms: 0 }),
    ])
    expect(chips).toHaveLength(2)
    expect(chips[0].text).toContain('盘点')
    expect(chips[1].text).toContain('产物核对')
    expect(receiptChips([])).toEqual([])
  })

  it('ok=true：正常面（pill ok），✓ ＋ 用时；用时为 0 省略', () => {
    const c = receiptChips([receipt({})])[0]
    expect(c.cls).toBe('pill ok')
    expect(c.text).toContain('✓')
    expect(c.text).toContain('12ms')
    const zero = receiptChips([receipt({ elapsed_ms: 0 })])[0]
    expect(zero.text).not.toContain('ms')
  })

  it('ok=false：降级类名（pill stale），× 标记，summary 保留给悬浮提示', () => {
    const c = receiptChips([receipt({ ok: false, summary: '产物核对没过' })])[0]
    expect(c.cls).toBe('pill stale')
    expect(c.text).toContain('×')
    expect(c.summary).toBe('产物核对没过')
  })

  it('refused=true 正常不出现，出现则同走降级并保留 summary', () => {
    const c = receiptChips([receipt({ refused: true })])[0]
    expect(c.cls).toBe('pill stale')
    expect(c.summary).toBe('四件齐')
  })
})
