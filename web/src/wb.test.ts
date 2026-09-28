/* 票 01（ADR-0003）：wb.ts 纯逻辑的第一批单测——状态推导与文案。
   只测公共接口行为（输入 → 输出），不碰渲染；UI 行为仍由 check_web_app.py 真浏览器验收。 */

import { describe, expect, it } from 'vitest'
import { deriveWorkbench, failureCopy, isTerminal, statusToWB } from './wb'
import type { ApiError, Period, PeriodDetail } from './api'

const period = (over: Partial<Period> = {}): Period => ({
  period: '202607',
  label: '2026年第4期',
  signed: false,
  status: 'completed',
  url: '/p/202607',
  ...over,
})

const detail = (steps?: PeriodDetail['steps']): PeriodDetail => ({ period: '202607', steps })

describe('isTerminal / statusToWB（后端十态 → 工作台状态）', () => {
  it('十个终态判定', () => {
    for (const s of ['completed', 'warned', 'escalated', 'failed', 'cancelled']) {
      expect(isTerminal(s), s).toBe(true)
    }
    for (const s of ['pending', 'running', 'retrying', 'stalled', 'waiting_approval']) {
      expect(isTerminal(s), s).toBe(false)
    }
    expect(isTerminal(undefined)).toBe(false)
  })

  it('十态全覆盖映射（无遗漏、无意外落到默认）', () => {
    expect(statusToWB('completed')).toBe('done')
    expect(statusToWB('warned')).toBe('warned')
    expect(statusToWB('waiting_approval')).toBe('waiting-approval')
    expect(statusToWB('escalated')).toBe('fail-other')
    expect(statusToWB('failed')).toBe('fail-other')
    expect(statusToWB('cancelled')).toBe('fail-other')
    expect(statusToWB('stalled')).toBe('stalled')
    expect(statusToWB('pending')).toBe('running')
    expect(statusToWB('running')).toBe('running')
    expect(statusToWB('retrying')).toBe('running')
    expect(statusToWB('unknown-state')).toBe('ready')
  })
})

describe('deriveWorkbench（真实数据推导，不编状态）', () => {
  it('服务不通 → fail-other，且注明"不是实时状态"', () => {
    const wb = deriveWorkbench('202607', [], null, false)
    expect(wb.state).toBe('fail-other')
    expect(wb.note).toContain('不是实时状态')
  })

  it('未放监测表（detail 说没 input）→ empty', () => {
    const wb = deriveWorkbench('202607', [], detail({ ledger: true, input: false }), true)
    expect(wb.state).toBe('empty')
    expect(wb.focusAction).toBe('none')
  })

  it('台账齐、无 input 记录 → ready（可生成）', () => {
    const wb = deriveWorkbench('202607', [], detail({ ledger: true, input: true }), true)
    expect(wb.state).toBe('ready')
    expect(wb.focusAction).toBe('generate')
  })

  it('已出稿（期次在列表）→ done，主动作是签单', () => {
    const wb = deriveWorkbench('202607', [period()], detail({ ledger: true, input: true, generated: true }), true)
    expect(wb.state).toBe('done')
    expect(wb.focusAction).toBe('sign')
  })

  it('已签发（status=signed 或 signed=true）→ signed', () => {
    expect(deriveWorkbench('202607', [period({ status: 'signed' })], null, true).state).toBe('signed')
    expect(deriveWorkbench('202607', [period({ signed: true })], null, true).state).toBe('signed')
  })

  it('demo 覆盖会标明是演示、不是真实状态', () => {
    const wb = deriveWorkbench('202607', [period()], null, true, 'running')
    expect(wb.state).toBe('running')
    expect(wb.note).toContain('演示模式')
  })

  it('步骤条：没有详情时前两步写「未就绪」、第三步写「尚未出稿」，不编数据', () => {
    const wb = deriveWorkbench('202607', [], null, true)
    expect(wb.stepsKnown).toBe(false)
    expect(wb.steps[0].detail).toBe('未就绪')
    expect(wb.steps[1].detail).toBe('未就绪')
    expect(wb.steps[2].detail).toBe('202607 尚未出稿')
  })
})

describe('failureCopy（失败文案：缺什么＋下一步）', () => {
  it('结构化 missing 优先，并给"补上后重新生成"', () => {
    const err: ApiError = {
      error: '校验未过',
      missing: [{ sheet: '顶尖论文合计', column: '202609 列', note: '缺当期列' }],
    }
    const copy = failureCopy(err, true)
    expect(copy.title).toContain('数据还没齐')
    expect(copy.lines.join('')).toContain('《顶尖论文合计》缺少 202609 列（缺当期列）')
    expect(copy.lines.join('')).toContain('补上后点「重新生成」')
  })

  it('无结构化信息 → 用后端 error/hint，并说明上一版仍有效', () => {
    const copy = failureCopy({ error: '内部错误', hint: '把这一屏截图给开发' }, true)
    expect(copy.title).toBe('内部错误')
    expect(copy.lines.join('')).toContain('上一版报告仍然有效')
  })

  it('服务不通 → 先讲检查服务，不甩术语', () => {
    const copy = failureCopy(null, false)
    expect(copy.title).toBe('连不上服务')
    expect(copy.lines.join('')).not.toMatch(/api|fetch|端口/i)
  })
})
