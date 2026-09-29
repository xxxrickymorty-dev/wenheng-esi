/* 预测台 + 灵活报告的数据口（契约 §2.1 的 forecast 两件、§2.2 #3 选择落盘、#21 灵活报告两口）。
   🔴 数字只来自后端：这一层只取形状，不做任何换算、聚合、四舍五入。 */

import { req } from './api'

export type ForecastRoute = { value: string; label: string }
export type ForecastModelOption = { value: string; label: string }

/** GET /api/forecast/meta —— 数据期次 / 潜力学科 / 路线 / 模型池 */
export type ForecastMeta = {
  available: boolean
  source_period: string
  upstream_workbook: { name: string; last_modified_at: string | null }
  processed_input: { name: string | null; last_modified_at: string | null }
  run_record_at: string | null
  data_freshness: 'needs_check' | 'unverified'
  master_workbook_consumption_verified: boolean
  subjects: string[]
  routes: ForecastRoute[]
  models: ForecastModelOption[]
  model_version: string
  load_error: string
  /** 逐科 V1 推荐：recommendations[路线][学科] = 模型名（契约 #16；未就绪时缺省） */
  recommendations?: Record<string, Record<string, string>>
  recommendation_baseline?: string
}

export function formatProvenanceTime(value: string | null | undefined): string {
  if (!value) return '无法核实'
  const date = new Date(value)
  if (!Number.isFinite(date.getTime())) return '无法核实'
  return new Intl.DateTimeFormat('zh-CN', {
    dateStyle: 'medium', timeStyle: 'medium', timeZone: 'Asia/Shanghai',
  }).format(date)
}

export async function getForecastMeta(): Promise<ForecastMeta> {
  return req<ForecastMeta>('/api/forecast/meta')
}

/** 试跑结果里的一期 */
export type ForecastPoint = {
  period: number
  metric1: number | null
  metric2: number | null
  proximity: number | null
  crossed: boolean
}

export type ForecastModelResult = {
  model: string
  fit_mape: number | null
  rolling_mape: number | null
  gap: number | null
  metric_mapes?: Record<string, { fit: number | null; rolling: number | null }>
  failures: number
  both_under_5: boolean
  status: string
  first_crossing: number | null
  forecast: ForecastPoint[]
  chart: string
}

export type ForecastRun = {
  subject: string
  task: string
  metric_names: string[]
  model_version: string
  data_start: number
  data_end: number
  history_periods: number
  horizon: number
  recommended_model: string
  compared_all: boolean
  comparison_best_model: string
  errors: { model: string; error: string }[]
  notice: string
  source_period: string
  results: ForecastModelResult[]
}

/** 试跑一个学科（后端跑确定性模型，不在数据路径上用大模型） */
export async function runForecast(body: {
  subject: string
  task: string
  model: string
  horizon: number
}): Promise<ForecastRun> {
  return req<ForecastRun>('/api/forecast/run', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  })
}

/** 已保存的逐科选择：choice[路线][学科] = 模型名；未列出的学科＝用 V1 推荐 */
export type ForecastChoice = {
  period: string
  choice: Record<string, Record<string, string>>
  by: string
  at: string
}

export type ForecastChoiceEntry = {
  loaded: boolean
  loading: boolean
  saving: boolean
  error: string
  choice: ForecastChoice['choice']
  saved: ForecastChoice['choice']
  by: string
  at: string
}

export async function getForecastChoice(period: string): Promise<ForecastChoice> {
  return req<ForecastChoice>(`/api/periods/${encodeURIComponent(period)}/forecast-choice`)
}

export async function saveForecastChoice(
  period: string,
  choice: Record<string, Record<string, string>>,
): Promise<{ ok: boolean; saved: number; path: string }> {
  return req<{ ok: boolean; saved: number; path: string }>(
    `/api/periods/${encodeURIComponent(period)}/forecast-choice`,
    { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ choice }) },
  )
}

/* ---------------------------------------------------------------- 学科板（#20） */

export type ForecastBoardRow = {
  subject: string
  model: string
  fit_mape: number | null
  rolling_mape: number | null
  cur_value: number | null
  threshold: number | null
  gap: number | null
  both_under_5: boolean
  /** 接近度（百分数点值：14.23 表示 14.23%） */
  prox: number | null
  /** 最早/最可能/最晚过线期；空串＝该窗口内未过线 */
  t1: string
  t2: string
  t3: string
}

export type ForecastBoard = {
  period: string
  window: string
  routes: Record<string, ForecastBoardRow[]>
  note: string
}

/** 选模与过线学科板（源：out/<期次>/预测选模与过线.md）——纯只读 */
export async function getForecastBoard(period?: string): Promise<ForecastBoard> {
  const q = period ? `?period=${encodeURIComponent(period)}` : ''
  return req<ForecastBoard>(`/api/forecast/board${q}`)
}

/* ---------------------------------------------------------------- 灵活报告（#21） */

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
