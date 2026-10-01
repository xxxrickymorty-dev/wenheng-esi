/* 票 04 单测：状态/签单话术的唯一映射。 */

import { describe, expect, it } from 'vitest'
import {
  ACQ_FILE_LABEL, ACQ_GROUP_LABEL, APPROVAL_LABEL, APPROVAL_STATES, AUDIT_LABEL,
  TASK_LABEL, TASK_STATES, TERMINAL_STATES,
  acqFileLabel, acqGroupLabel, appHref, approvalLabel, errorNote,
  isApprovalState, isTaskState, isTerminalState, taskLabel,
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

describe('取数与审计话术', () => {
  it('组状态五态唯一、未知原样', () => {
    expect(Object.keys(ACQ_GROUP_LABEL)).toEqual(
      ['pending', 'live', 'done', 'fail', 'retrying'],
    )
    expect(new Set(Object.values(ACQ_GROUP_LABEL)).size).toBe(5)
    expect(acqGroupLabel('live')).toBe('进行中')
    expect(acqGroupLabel('weird')).toBe('weird')
    expect(acqGroupLabel(null)).toBe('—')
  })

  it('文件状态与审计结果', () => {
    expect(Object.values(ACQ_FILE_LABEL)).toEqual(
      ['待取数', '已收到 · 待核验', '核验通过', '未通过'],
    )
    expect(acqFileLabel('received')).toBe('已收到 · 待核验')
    expect(Object.values(AUDIT_LABEL)).toEqual(['通过', '待确认', '不通过'])
  })
})

describe('errorNote（HTTP 失败 → 馆员话术）', () => {
  const e = (status: number, body?: unknown) => ({ status, body: body ?? null })

  it('401 / 403 标准说法', () => {
    expect(errorNote(e(401), '产物清单')).toBe('需要登录才能看产物清单。')
    expect(errorNote(e(403), '运行档案'))
      .toBe('运行档案需要管理员权限（用馆员账号登录后再来）。')
  })

  it('404：body.hint 优先，其次 opts，最后默认', () => {
    expect(errorNote(e(404, { hint: '自定义提示' }), '图册')).toBe('自定义提示')
    expect(errorNote(e(404), '图册', { n404: '还没取数' })).toBe('还没取数')
    expect(errorNote(e(404), '图册')).toBe('这一期还没有图册（可能尚未出稿）。')
  })

  it('409 与兜底：body.error → message → 默认', () => {
    expect(errorNote(e(409, { error: '签单被拒' }), '签单')).toBe('签单被拒')
    expect(errorNote(e(500, { error: '内部错' }), '数据')).toBe('内部错')
    expect(errorNote({ message: '网络断了' }, '数据')).toBe('网络断了')
    expect(errorNote(new Error('炸了'), '数据')).toBe('炸了')
    expect(errorNote(null, '数据')).toBe('读取数据失败。')
  })
})

describe('appHref（站内视图链接）', () => {
  it('带当期且保留视图', () => {
    expect(appHref('workbench', '202607')).toBe('/app/?view=workbench&period=202607')
    expect(appHref('archive', '202605_复现'))
      .toBe('/app/?view=archive&period=202605_%E5%A4%8D%E7%8E%B0')
  })
})
