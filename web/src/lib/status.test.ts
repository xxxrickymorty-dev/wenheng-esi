/* 票 04 单测：状态/签单话术的唯一映射。 */

import { describe, expect, it } from 'vitest'
import {
  APPROVAL_LABEL, APPROVAL_STATES, TASK_LABEL, TASK_STATES, TERMINAL_STATES,
  approvalLabel, isApprovalState, isTaskState, isTerminalState, taskLabel,
} from './status'

describe('任务十态映射', () => {
  it('十态全覆盖、话术无重复（一词一义）', () => {
    expect(TASK_STATES).toHaveLength(10)
    const labels = TASK_STATES.map((s) => TASK_LABEL[s])
    for (const l of labels) expect(l.length).toBeGreaterThan(0)
    expect(new Set(labels).size).toBe(labels.length)
  })

  it('终态集合与后端一致（completed/warned/escalated/failed/cancelled）', () => {
    expect([...TERMINAL_STATES].sort()).toEqual(
      ['cancelled', 'completed', 'escalated', 'failed', 'warned'].sort(),
    )
    expect(isTerminalState('running')).toBe(false)
    expect(isTerminalState('warned')).toBe(true)
    expect(isTerminalState(undefined)).toBe(false)
  })

  it('taskLabel：已知翻译、未知原样、空值破折号', () => {
    expect(taskLabel('retrying')).toBe('自动修复中')
    expect(taskLabel('escalated')).toBe('需人工接手')
    expect(taskLabel('some-new-state')).toBe('some-new-state')   // 不编
    expect(taskLabel(null)).toBe('—')
    expect(isTaskState('pending')).toBe(true)
    expect(isTaskState('pending ')).toBe(false)
  })
})

describe('签单三态映射', () => {
  it('三态全覆盖且话术唯一', () => {
    expect(APPROVAL_STATES).toHaveLength(3)
    const labels = APPROVAL_STATES.map((s) => APPROVAL_LABEL[s])
    expect(new Set(labels).size).toBe(3)
  })

  it('approvalLabel 与守卫', () => {
    expect(approvalLabel('signed')).toBe('已签发')
    expect(approvalLabel('stale')).toBe('签名已失效')
    expect(approvalLabel('unsigned')).toBe('未签发')
    expect(approvalLabel(undefined)).toBe('—')
    expect(approvalLabel('pending')).toBe('pending')
    expect(isApprovalState('signed')).toBe(true)
    expect(isApprovalState('ok')).toBe(false)
  })
})
