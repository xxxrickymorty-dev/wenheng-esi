/* Batch 2 的三个只读端点（后端 7223ba5 交付）。形状按**实测响应**写，不按猜的。 */

import { req } from './api'

export type ChartRow = { name: string; group: string; url: string }

/** 图册：期次图，按分组。后端按 50/页分页——这里循环拉全，
    「共 N 张」与图册全量页要的是全部，不是第一页。 */
export async function getCharts(period: string): Promise<ChartRow[]> {
  const out: ChartRow[] = []
  let offset = 0
  for (;;) {
    const r = await req<{ rows: ChartRow[]; has_more?: boolean }>(
      `/api/periods/${encodeURIComponent(period)}/charts?limit=500&offset=${offset}`)
    const rows = r.rows ?? []
    out.push(...rows)
    offset += rows.length
    if (!r.has_more || rows.length === 0) break
  }
  return out
}

export type RedRow = {
  group: string
  label: string
  old: string
  new: string
  src: string
  kind: string
}

/** 红色件（逐格全量表）：704 条量级——**别一次全渲染**，调用方要截断 */
export async function getRedSlots(period: string): Promise<RedRow[]> {
  const r = await req<{ rows: RedRow[] }>(`/api/periods/${encodeURIComponent(period)}/redslots`)
  return r.rows ?? []
}

export type CollationRow = {
  section: string
  loc: string
  old: string
  new: string
  oldPreview?: string
  newPreview?: string
  source?: string
  kind?: string
  oldLabel?: string
  /** true = 这一处需要人补（【手工：…】），也就是页边朱批要盯的 */
  manual?: boolean
}

/** 对勘：母版原文 ↔ 本期生成（含正文/大表/图槽位），溯源信息在这一层。
    `full=true` 取全量——分区计数与待人工清单必须用全量，别拿分页前 50 行当全部 */
export async function getCollation(period: string, full = false): Promise<CollationRow[]> {
  const q = full ? '?full=true' : ''
  const r = await req<{ rows: CollationRow[] }>(`/api/periods/${encodeURIComponent(period)}/collation${q}`)
  return r.rows ?? []
}
