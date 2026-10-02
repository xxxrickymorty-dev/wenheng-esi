/* 任务归属期次的全部规则（票 05）：两个问题、两条判据，别再散到页面里。
   ①「执行条画不画」——实时运行必须与本屏同期（审计 A3）；
   ②「本屏该看哪个任务」——报告屏/工具屏按请求期次选任务，服务端筛过的 lastJob 作受限回退。 */

import type { Job } from '../api'

export type RunPeriodLike = { requestedPeriod: string }

/** ① 同期才返回运行；不同期或没有运行 → null。纯函数。 */
export function pickRunForPeriod<T extends RunPeriodLike>(
  run: T | null | undefined,
  selected: string | null,
): T | null {
  if (!run || !selected) return null
  return run.requestedPeriod === selected ? run : null
}

/** ② 按任务记录中的请求期次选择任务；期次详情提供受限回退。 */
export function choosePeriodJobId(
  period: string | null,
  canonicalPeriod: string,
  candidateId: string | null,
  candidate: Job | null,
  fallbackId: string | null,
): string | null {
  if (!period) return null
  if (candidateId && candidate?.period === canonicalPeriod) return candidateId
  // api_period_detail 已按所请求期次筛选 lastJob；其 ID 是本期受限回退。
  return fallbackId
}
