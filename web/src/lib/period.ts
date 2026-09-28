/* 期次上下文（票 02）：**唯一真相 = URL 的 ?period=**。
   为什么是 URL：刷新、复制链接、后退都能回到同一期（审计 A1-A5 的根因）。

   结构（ADR-0003：纯逻辑先抽出，可用 vitest 直接测）：
   - 纯函数：`isValidPeriod` / `parsePeriod` / `buildPeriodUrl`——不碰 DOM；
   - 薄壳：`readPeriod` / `applyPeriod` / `usePeriod`——只在浏览器里做 IO。

   ⚠ 本票只落模块与测试，**不改任何页面行为**；顶栏期次章与页内入口改造在票 03。 */

import { useEffect, useState } from 'react'

/** 期次变更事件：页内组件（票 03 及以后）订阅它来跟随刷新。 */
export const PERIOD_EVENT = 'wh-period-changed'

/** 期次合法形状：6 位数，可选 `_后缀`（如 `202605_复现`）——与后端期次名规则一致。 */
export function isValidPeriod(value: unknown): value is string {
  return typeof value === 'string' && /^\d{6}(_[\w\u4e00-\u9fa5-]+)?$/.test(value)
}

/**
 * 从 query string 里解析期次；缺失或非法时回退 `fallback`（通常传「最新一期」）。
 * 纯函数——不读全局 location，方便单测。
 */
export function parsePeriod(search: string, fallback: string | null = null): string | null {
  const raw = new URLSearchParams(search).get('period')
  return isValidPeriod(raw) ? raw : fallback
}

/**
 * 在 href 上写入期次并**保留其余参数**，返回可交给 history.replaceState 的相对地址。
 * 纯函数；缺 `period` 时补，已有时覆盖。
 */
export function buildPeriodUrl(href: string, period: string): string {
  const url = new URL(href, 'http://placeholder.local')
  url.searchParams.set('period', period)
  return url.pathname + url.search + url.hash
}

/** 读当前 URL 里的期次（缺省回退 fallback）。浏览器薄壳。 */
export function readPeriod(fallback: string | null = null): string | null {
  return parsePeriod(window.location.search, fallback)
}

/** 把期次写进 URL（replaceState，不新增历史条）并广播事件。浏览器薄壳。 */
export function applyPeriod(period: string): void {
  if (!isValidPeriod(period)) return
  window.history.replaceState(null, '', buildPeriodUrl(window.location.href, period))
  window.dispatchEvent(new CustomEvent(PERIOD_EVENT, { detail: period }))
}

/**
 * React 薄皮：跟随 URL 里的期次（popstate + 自定义事件），返回 `[期次, 设置期次]`。
 * 页面接线在票 03；本票先备好，不引用。
 */
export function usePeriod(fallback: string | null = null): readonly [string | null, (p: string) => void] {
  const [period, setPeriod] = useState<string | null>(() => readPeriod(fallback))
  useEffect(() => {
    const sync = () => setPeriod(readPeriod(fallback))
    window.addEventListener('popstate', sync)
    window.addEventListener(PERIOD_EVENT, sync)
    return () => {
      window.removeEventListener('popstate', sync)
      window.removeEventListener(PERIOD_EVENT, sync)
    }
  }, [fallback])
  return [period, applyPeriod] as const
}
