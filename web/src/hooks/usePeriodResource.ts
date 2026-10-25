/* 按期次分桶的「取一次」原语。
   2026-10-25 P1 探针：从 App.tsx refreshDetail 与选模 effect 的手写语义抽出——
   两处逐行同构（按期 ref 计数器 + fetch + then/catch 双守卫 + 按期分桶写状态）。

   两个机制各防一件事：
   - 按期自增序号：同一期连发两次，迟到旧响应作废（防同期重发竞态）；
   - 按 key 分桶由调用方持有（onData/onError 只写该期自己的桶）：旧响应盖不到
     新期次（防跨期串写），且切走的期次数据留存，切回来不用重取。

   调用方必须用 useMemo(..., []) 包住 options——request 的稳定性依赖它
   （onRunTerminal 等消费方把 request 放进依赖数组）。 */
import { useCallback, useRef } from 'react'

export type PeriodResourceOptions<K extends string, V> = {
  /** 按期次取一份数据；不可取消（没有 abort），乱序由序号守卫兜。 */
  load: (period: K) => Promise<V>
  /** 序号仍相符时调用：只允许写 period 自己那一桶。 */
  onData: (period: K, value: V) => void
  /** 序号仍相符时调用：错误也要落进 period 自己那一桶。 */
  onError: (period: K, error: unknown) => void
}

export function usePeriodResource<K extends string, V>(
  options: PeriodResourceOptions<K, V>,
): {
  /** 发一次请求：序号 +1 → load → 序号不符则丢弃，相符则写桶。 */
  request: (period: K) => void
  /** 只把序号 +1：作废在途响应，但不发请求（供「重置占位让 effect 重拉」用）。 */
  invalidate: (period: K) => void
} {
  const seqRef = useRef<Record<string, number>>({})

  const request = useCallback((period: K) => {
    const ticket = (seqRef.current[period] ?? 0) + 1
    seqRef.current[period] = ticket
    void options.load(period).then((value) => {
      if (seqRef.current[period] !== ticket) return
      options.onData(period, value)
    }).catch((error: unknown) => {
      if (seqRef.current[period] !== ticket) return
      options.onError(period, error)
    })
  }, [options])

  const invalidate = useCallback((period: K) => {
    seqRef.current[period] = (seqRef.current[period] ?? 0) + 1
  }, [])

  return { request, invalidate }
}
