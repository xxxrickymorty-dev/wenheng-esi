/* 读数带与在线填（前端催来的两个 GET，后端已交付）。
   形状按**实测响应**写，不按猜测；改动先改 docs/前后端分工与接口契约（2026-09-23）.md。
   🔴 数字只来自后端：这里只做透传，不换算、不聚合、不四舍五入。 */

import { req } from './api'

/** GET /api/periods/{p}/facts —— 读数带（源：报告同款的 overview_facts.json） */
export type Facts = {
  period: string
  period_prev: string
  facts: {
    rank_intl_now: number
    rank_intl_prev: number
    rank_intl_delta: number
    rank_cn_inst_now: number
    rank_cn_inst_delta: number
    rank_cn_uni_now: number
    rank_cn_uni_delta: number
    n_disc_1pct: number
    top_papers_now: number
    top_papers_prev: number
    top_papers_delta: number
    top3_by_top_papers: [string, number][]
    best_1permille: { discipline: string; prox_pct: number; prox_prev_pct: number }
    top2_prox_change: [string, number][]
    rank_up: number
    rank_down: number
    rank_flat: number
    worst_cn_rank: { discipline: string; drop: number; rank: number }
    top3_groups: [number, string[]][]
    top2_not_entered: { discipline: string; prox_pct: number; chg: number }[]
    any_1permille: boolean
    permille_years_est: number
    coverage_window: string
    prev_label: string
  }
  /** 数字防护的体检单：total 条断言、fail 条不符（0 才是干净） */
  assertions: { total: number; fail: number }
  /** 缺什么（空 = 齐） */
  missing: string[]
  /** 历期序列（契约 #19）：期次 → 顶尖论文数；票数少或无序列时缺省 */
  trend?: Record<string, number>
}

export const getFacts = (period: string) =>
  req<Facts>(`/api/periods/${encodeURIComponent(period)}/facts`)

/** 一处待办：补录（kind=fill）或待确认（kind=confirm） */
export type TodoItem = {
  id: string
  kind: string
  title: string
  /** 在报告的哪一处，如 '正文/p1' */
  where: string
  /** 这一处的来源（如「句骨架+数字槽」）——给馆员看的，不是代码路径 */
  source: string
  filled: string | null
  filled_by: string | null
  filled_at: string | null
}

/** 一条填写记录的处置状态：pending=填了还没写进报告 / applied=已写入 / orphan=对不上位置的旧残留 */
export type FillRow = {
  key: string
  value: string
  by: string
  at: string
  state: 'pending' | 'applied' | 'orphan'
}

/** 存疑明细：loc → 记录（存在即已标存疑） */
export type DoubtMap = Record<string, { state?: string; by?: string; at?: string }>

/** GET /api/periods/{p}/workbench —— 工作台全量数据（admin 可读） */
export type WorkbenchData = {
  period: string
  period_dir: string
  /** 可追溯性：n 个数字里 with_source 个有出处 */
  traceable: { n: number; with_source: number }
  todo: TodoItem[]
  todo_fill: TodoItem[]
  todo_confirm: TodoItem[]
  n_filled: number
  n_applied: number
  n_orphan: number
  n_doubt: number
  /** 填写记录的逐条处置（审核台据此判断「有值还没写进报告」） */
  fills_list?: FillRow[]
  /** 存疑明细（审核台的「标存疑」按位置显示状态） */
  review?: DoubtMap
  approvalStatus?: string
  [k: string]: unknown
}

export const getWorkbench = (period: string) =>
  req<WorkbenchData>(`/api/periods/${encodeURIComponent(period)}/workbench`)

/** POST /api/periods/{p}/fill —— 批量补录：{items: {todo_id: 值}} → {ok, saved}
    只写状态库里的填写记录，台账一个字节不动（后端口径）。 */
export async function postFill(
  period: string,
  items: Record<string, string>,
): Promise<{ ok: boolean; saved: number }> {
  return req<{ ok: boolean; saved: number }>(
    `/api/periods/${encodeURIComponent(period)}/fill`,
    {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ items }),
    },
  )
}
