/* Batch 2 的三个只读端点（后端 7223ba5 交付）。形状按**实测响应**写，不按猜的。 */

import { req } from './api'

/** 循环拉全分页接口（后端上限 500/页）——页面上写「共 N 条/张」就得是真数，
    别把默认第一页（50）当全部。 */
async function reqAll<T>(url: string): Promise<T[]> {
  const out: T[] = []
  let offset = 0
  for (;;) {
    const sep = url.includes('?') ? '&' : '?'
    const r = await req<{ rows: T[]; has_more?: boolean }>(
      `${url}${sep}limit=500&offset=${offset}`)
    const rows = r.rows ?? []
    out.push(...rows)
    offset += rows.length
    if (!r.has_more || rows.length === 0) break
  }
  return out
}

export type ChartRow = {
  name: string
  group: string
  url: string
  /** 读得懂的名字（如预测图的「免疫学 · 被引频次与阈值（预测图）」）；空串＝回落文件名 */
  label?: string
}

/** 图册：期次图，按分组（109 张量级，全量） */
export async function getCharts(period: string): Promise<ChartRow[]> {
  return reqAll<ChartRow>(`/api/periods/${encodeURIComponent(period)}/charts`)
}

export type RedRow = {
  group: string
  label: string
  old: string
  new: string
  src: string
  kind: string
}

/** 红件（逐格全量表）：716 条量级，全量拉回；页面自己搜索/截断 */
export async function getRedSlots(period: string): Promise<RedRow[]> {
  return reqAll<RedRow>(`/api/periods/${encodeURIComponent(period)}/redslots`)
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
