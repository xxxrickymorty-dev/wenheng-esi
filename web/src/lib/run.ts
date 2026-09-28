/* 运行条的选择（票 05）：执行条只画**与本屏同期次**的运行。
   别的期次在跑时，由工作台用一行提示说明（不复用别期的执行条——审计 A3）。 */

export type RunPeriodLike = { requestedPeriod: string }

/** 同期才返回运行；不同期或没有运行 → null。纯函数。 */
export function pickRunForPeriod<T extends RunPeriodLike>(
  run: T | null | undefined,
  selected: string | null,
): T | null {
  if (!run || !selected) return null
  return run.requestedPeriod === selected ? run : null
}
