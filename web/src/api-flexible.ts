/* 灵活报告（第二条产线）与写作位的数据口（契约 §21）。
   🔴 正文由后端自己的 md 渲染器出稿；这一层只取形状与流事件，不改一个字。
   预测台的数据口在 api-forecast.ts（原 api5 一拆为二，2026-10-01）。 */

import { req } from './api'

export type FlexibleReport = {
  intent: string; title: string; meta: Record<string, unknown>; has_rule?: boolean
}

/** 监测学科（下拉）：en 是数据里的英文名，cn 是界面显示的中文名 */
export type FlexibleDiscipline = { en: string; cn: string }

/** 写作位（AI 润色）的部署状态：enabled＝部署开关，available＝开关开且配了云 */
export type FlexibleWriteState = { enabled: boolean; available: boolean }

export type FlexibleData = {
  period: string
  intents: { id: string; cn: string }[]
  reports: FlexibleReport[]
  cur: string | null
  /** 当前看的是规则稿（variant=rule）还是润色稿（空串） */
  variant?: 'rule' | ''
  has_rule?: boolean
  disciplines: FlexibleDiscipline[]
  write: FlexibleWriteState
  /** 正文（后端同一个 md 渲染器出的 html，图已指向 /p/<期次>/flexible/chart/…） */
  body_html: string
}

export async function getFlexible(period: string, intent?: string,
                                  variant?: 'rule'): Promise<FlexibleData> {
  const q = new URLSearchParams()
  if (intent) q.set('intent', intent)
  if (variant) q.set('variant', variant)
  const qs = q.toString()
  return req<FlexibleData>(
    `/api/periods/${encodeURIComponent(period)}/flexible${qs ? `?${qs}` : ''}`)
}

export async function runFlexible(
  period: string,
  body: { intent: string; disc?: string },
): Promise<{ ok: boolean; intent: string; elapsed: number; n_charts?: number; backend?: string }> {
  return req<{ ok: boolean; intent: string; elapsed: number; n_charts?: number; backend?: string }>(
    `/api/periods/${encodeURIComponent(period)}/flexible`,
    { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) },
  )
}

/** 流式生成事件（契约 #21③，一行一个）：真实节点——规划完成、每节完成、收尾。 */
export type FlexWriteSummary = {
  segments: number; rewritten: number; fallbacks: number; reasons: string[]
}
export type FlexStreamEvent =
  | { event: 'status'; stage: string }
  | { event: 'plan'; intent: string; title: string; backend: string; mode: string
      disc: string; outline: string[]; fallback_reason?: string | null }
  | { event: 'section'; title: string; html: string }
  | { event: 'done'; elapsed: number; n_charts: number; backend: string; mode: string
      title: string; check_pass: boolean; write: FlexWriteSummary | null }
  | { event: 'error'; message: string }

/** 逐行读取 NDJSON 流（fetch + ReadableStream；不引依赖、不用 EventSource）。 */
export async function runFlexibleStream(
  period: string,
  body: { intent: string; disc?: string },
  onEvent: (ev: FlexStreamEvent) => void,
): Promise<void> {
  const res = await fetch(
    `/api/periods/${encodeURIComponent(period)}/flexible/stream`,
    {
      method: 'POST',
      credentials: 'same-origin',
      headers: { 'Content-Type': 'application/json', Accept: 'application/x-ndjson' },
      body: JSON.stringify(body),
    })
  if (!res.ok || !res.body) {
    let msg = `生成没成功（HTTP ${res.status}）`
    try {
      const j = (await res.json()) as { error?: string; hint?: string }
      msg = j.hint ?? j.error ?? msg
    } catch { /* 非 JSON 错误体 */ }
    throw new Error(msg)
  }
  const reader = res.body.getReader()
  const dec = new TextDecoder()
  let buf = ''
  for (;;) {
    const { value, done } = await reader.read()
    if (done) break
    buf += dec.decode(value, { stream: true })
    let idx: number
    while ((idx = buf.indexOf('\n')) >= 0) {
      const line = buf.slice(0, idx).trim()
      buf = buf.slice(idx + 1)
      if (line) onEvent(JSON.parse(line) as FlexStreamEvent)
    }
  }
  const tail = buf.trim()
  if (tail) onEvent(JSON.parse(tail) as FlexStreamEvent)
}

/** AI 润色（写作位，契约 #21④）：只重写叙述段；数字、图表、来源链不变。 */
export type FlexPolishResp = {
  ok: boolean; intent: string; elapsed: number; mode: string
  write: FlexWriteSummary | null; backend: string
}

export async function polishFlexible(period: string, intent: string): Promise<FlexPolishResp> {
  return req<FlexPolishResp>(
    `/api/periods/${encodeURIComponent(period)}/flexible/polish`,
    { method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ intent }) },
  )
}
