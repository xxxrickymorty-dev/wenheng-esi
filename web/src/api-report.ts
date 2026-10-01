/* 审核台 · 试排报告预览（后端 2026-09-28 交付）。
   🔴 只透传：报告文本/表格/图全部来自 docx 本身，前端不重排文字、不重算数字。 */

import { req } from './api'

/** 段落里的一个片段：普通文字（t）或一处待填空（ph = 工作台的 todo id）。 */
export type PreviewSeg =
  | { t: string; b?: boolean; size?: number | null }
  | { ph: string; title: string; b?: boolean; size?: number | null }

export type PreviewCell = { text: string; imgs?: string[]; span?: number }

export type PreviewBlock =
  | { t: 'p'; align?: string | null; runs: PreviewSeg[] }
  | { t: 'img'; rid: string; w_cm?: number; h_cm?: number }
  | { t: 'tbl'; rows: PreviewCell[][] }

export type ReportPreview = {
  period: string
  /** null = 这一期还没出稿（接口会连同 404 一起给） */
  docx: string | null
  updated_at: string
  blocks: PreviewBlock[]
  /** 报告里的空：todo id → {where, title}（id 与工作台同一套键） */
  fields: Record<string, { where: string; title: string }>
  /** 当前 docx 里还留着的空位处数 */
  n_manual_ph: number
}

/** GET /api/periods/{p}/report-preview —— 报告全文块 + 在线填空字段（admin） */
export async function getReportPreview(period: string): Promise<ReportPreview> {
  return req<ReportPreview>(`/api/periods/${encodeURIComponent(period)}/report-preview`)
}

/** 报告预览里的插图地址（按 docx 内部 rId；同源、需登录） */
export function reportImageUrl(period: string, rid: string): string {
  return `/api/periods/${encodeURIComponent(period)}/report-image/${encodeURIComponent(rid)}`
}

/** POST /api/periods/{p}/rebuild —— 把填值写进报告并重出（旧版先撤下，可回滚）。
 *  会先保存 items，再重出；2–15 秒同步阻塞。 */
export async function rebuildPeriod(
  period: string,
  items: Record<string, string>,
): Promise<{ ok: boolean; rebuilt: number; docx: string; elapsed: number }> {
  return req<{ ok: boolean; rebuilt: number; docx: string; elapsed: number }>(
    `/api/periods/${encodeURIComponent(period)}/rebuild`,
    {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ items }),
    },
  )
}
