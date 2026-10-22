/* 本机数据存储只读降级 → 告警文案（纯函数）。判定口径写在 lib/stateDb.ts 头注释：
   只认后端明确说的 degraded: true，其余一律按正常处理（不猜、不误警）。 */
import { describe, expect, it } from 'vitest'
import { READONLY_FALLBACK, READONLY_LINES, stateDbAlert } from './stateDb'

describe('本机数据存储告警', () => {
  it('正常（degraded=false）不挂横幅', () => {
    expect(stateDbAlert({ ok: true, degraded: false, message: '' })).toBeNull()
  })

  it('降级：用后端那句人话，并列出受影响的动作', () => {
    const alert = stateDbAlert({
      ok: false, schema_version: 4, code_schema_version: 3, degraded: true,
      message: '本机数据存储版本比程序新，已进入只读模式，请联系管理员。',
    })
    expect(alert?.message).toBe('本机数据存储版本比程序新，已进入只读模式，请联系管理员。')
    expect(alert?.lines).toEqual([...READONLY_LINES])
    expect(alert?.lines.join('')).toContain('签单')
    expect(alert?.lines.join('')).toContain('不会丢')
  })

  it('降级但没带文案（或只有空白）：退回同一句兜底，不显示空横幅', () => {
    expect(stateDbAlert({ degraded: true })?.message).toBe(READONLY_FALLBACK)
    expect(stateDbAlert({ degraded: true, message: '   ' })?.message).toBe(READONLY_FALLBACK)
    expect(stateDbAlert({ degraded: true, message: 42 })?.message).toBe(READONLY_FALLBACK)
  })

  it('缺字段（老服务没有 state_db）按正常处理：不告警', () => {
    expect(stateDbAlert(undefined)).toBeNull()
    expect(stateDbAlert(null)).toBeNull()
    expect(stateDbAlert({})).toBeNull()
  })

  it('字段形状非法按正常处理（告警只认明确的 true，不认「看起来像」）', () => {
    expect(stateDbAlert('degraded')).toBeNull()
    expect(stateDbAlert([])).toBeNull()
    expect(stateDbAlert({ degraded: 'true' })).toBeNull()
    expect(stateDbAlert({ degraded: 1 })).toBeNull()
    expect(stateDbAlert({ degraded: false, message: '旧提示' })).toBeNull()
  })
})
