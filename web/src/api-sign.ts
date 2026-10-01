/* Batch 3/4 的写操作（后端 2b14850 / 6a748b8 交付）。形状按实测源码写。 */

import { req } from './api'

/** 钤印签单。known = 已知悉待人工项；服务端还会校验指纹与闸门（失败 409） */
export async function signPeriod(
  period: string,
  body: { known: boolean; note?: string },
): Promise<{ status: string; fingerprint?: unknown }> {
  return req<{ status: string; fingerprint?: unknown }>(
    `/api/periods/${encodeURIComponent(period)}/sign`,
    {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
    },
  )
}

/** 撤回签单（历史保留） */
export async function revokePeriod(period: string, note = ''): Promise<{ status: string }> {
  return req<{ status: string }>(`/api/periods/${encodeURIComponent(period)}/revoke`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ note }),
  })
}

/** 给某一处打/取消存疑（loc 来自对勘的 loc，如 '正文/p1'） */
export async function flagLoc(
  period: string,
  loc: string,
): Promise<{ ok: boolean; loc: string; state: string; n_doubt: number }> {
  return req<{ ok: boolean; loc: string; state: string; n_doubt: number }>(
    `/api/periods/${encodeURIComponent(period)}/flag`,
    {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ loc }),
    },
  )
}
