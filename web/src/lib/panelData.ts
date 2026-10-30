/* 他校简报的同源数据（GET /api/periods/<期次>/panel-data，src/flexible/panel.py 出）。
   🔴 这一层只取形状、不做任何换算：`counts` 原样、`events` 原样、`common`/`only` 原样。
   默认载荷里没有 `grid`（全量矩阵只在前端真要画时才用 `?grid=1` 取）。 */

import { req } from '../api'
import type { Num } from './chartsData'

export type PanelSchool = {
  /** 用户输入的写法 */
  query: string
  /** 规范中文名（画图与表格都用它） */
  cn: string
  en: string
  /** ok＝查到了；absent＝整校未上榜或校名对不上；error＝校名对上多家，不能猜 */
  status: 'ok' | 'absent' | 'error'
  match: string
  /** 每期上榜学科数；null＝该期无数据（**不是 0**） */
  counts: Num[]
  entered: { period: string; disc: string; cn: string }[]
  exited: { period: string; disc: string; cn: string }[]
  note: string
}

export type PanelEvent = {
  kind: 'enter' | 'exit' | 'overtake' | 'flat' | 'inflect' | string
  school: string
  period: string
  /** 期次下标（0 = 窗口首期） */
  index: number
  value: number
  /** 后端定稿的标注文字，前端不改写 */
  text: string
  meta: Record<string, unknown>
}

export type PanelData = {
  periods: string[]
  /** 窗口内没有数据的期次（有缺口时后端整段不出事件） */
  missing: string[]
  period_end: string
  disciplines: string[]
  schools: PanelSchool[]
  common: string[]
  only: Record<string, string[]>
  events: PanelEvent[]
  summary: {
    periods: string[]
    schools: { cn: string; status: string; counts: Num[] }[]
    common_count: number
    events: string[]
  }
  source: { dataset: string; period: string; generated_at: string }
}

export async function getPanelData(opts: {
  /** 期次；`latest`＝ESI 数据目录里最新一期 */
  period: string
  /** 校名，逗号分隔（顿号、分号、「和」后端也认）——原样交给后端拆 */
  schools: string
  n?: number
}): Promise<PanelData> {
  const q = new URLSearchParams({ schools: opts.schools, n: String(opts.n ?? 6) })
  return req<PanelData>(
    `/api/periods/${encodeURIComponent(opts.period)}/panel-data?${q.toString()}`)
}
