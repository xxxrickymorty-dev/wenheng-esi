/* AI 调用统计的数据口（2026-11-04 票 2，契约冻结照此消费）：
   GET /api/ai/call-stats（管理员）→
   { total, modes:{model,rule,failed},
     labels:[{ label, total, model, rule, failed, fallback:{<原因码>:count} }] }
   只读不改、不换算：数字原样上屏。403（非管理员）与拉取失败由
   调用方静默处理——整块不显示（不误显）。 */

import { req } from './api'

export type CallStatsModes = { model: number; rule: number; failed: number }

export type CallStatsLabel = {
  label: string
  total: number
  model: number
  rule: number
  failed: number
  /** 回落原因码 → 次数（后端口径原样透传） */
  fallback: Record<string, number>
}

export type CallStats = {
  total: number
  modes: CallStatsModes
  labels: CallStatsLabel[]
}

export async function getCallStats(): Promise<CallStats> {
  return req<CallStats>('/api/ai/call-stats')
}
