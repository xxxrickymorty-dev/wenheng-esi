/* 预测台 + 灵活报告的数据口（契约 §2.1 的 forecast 两件、§2.2 #3 选择落盘、#21 灵活报告两口）。
   🔴 数字只来自后端：这一层只取形状，不做任何换算、聚合、四舍五入。 */

import { req } from './api'

export type ForecastRoute = { value: string; label: string }
export type ForecastModelOption = { value: string; label: string }

/** GET /api/forecast/meta —— 数据期次 / 潜力学科 / 路线 / 模型池 */
export type ForecastMeta = {
  available: boolean
  source_period: string
  subjects: string[]
  routes: ForecastRoute[]
  models: ForecastModelOption[]
  model_version: string
  load_error: string
  /** 逐科 V1 推荐：recommendations[路线][学科] = 模型名（契约 #16；未就绪时缺省） */
  recommendations?: Record<string, Record<string, string>>
  recommendation_baseline?: string
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

/* ---------------------------------------------------------------- 灵活报告（#21） */

export type FlexibleReport = { intent: string; title: string; meta: Record<string, unknown> }

export type FlexibleData = {
  period: string
  intents: { id: string; cn: string }[]
  reports: FlexibleReport[]
  cur: string | null
  /** 正文（后端同一个 md 渲染器出的 html，图已指向 /p/<期次>/flexible/chart/…） */
  body_html: string
}

export async function getFlexible(period: string, intent?: string): Promise<FlexibleData> {
  const q = intent ? `?intent=${encodeURIComponent(intent)}` : ''
  return req<FlexibleData>(`/api/periods/${encodeURIComponent(period)}/flexible${q}`)
}

export async function runFlexible(
  period: string,
  body: { intent: string; backend?: string; disc?: string },
): Promise<{ ok: boolean; intent: string; elapsed: number; n_charts?: number; backend?: string }> {
  return req<{ ok: boolean; intent: string; elapsed: number; n_charts?: number; backend?: string }>(
    `/api/periods/${encodeURIComponent(period)}/flexible`,
    { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) },
  )
}
