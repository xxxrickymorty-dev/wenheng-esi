/* lab 最小 API 客户端 —— 端点与 web/src 同一套（契约不动），只取跨页壳用得到的形状。
   铁律同 web：本工程只做视图；数字必须能回溯到后端产物；缺数据如实显示，不编。 */

export type ApiError = { error: string; hint?: string }

export class HttpError extends Error {
  status: number
  body: ApiError | null
  constructor(status: number, body: ApiError | null) {
    super(`HTTP ${status}`)
    this.status = status
    this.body = body
  }
}

export async function req<T>(url: string, init?: RequestInit): Promise<T> {
  const res = await fetch(url, {
    credentials: 'same-origin',
    headers: { Accept: 'application/json' },
    ...init,
  })
  if (!res.ok) {
    let body: ApiError | null = null
    try { body = (await res.json()) as ApiError } catch { /* 404 的 HTML 等非 JSON 体 */ }
    throw new HttpError(res.status, body)
  }
  return (await res.json()) as T
}

/* ── 身份与期次 ─────────────────────────────────────────── */

export type Me = { name: string; role: 'admin' | 'operator' }
export const getMe = () => req<Me | null>('/api/me')

export type Period = {
  period: string
  label: string
  signed: boolean
  status: string
  generated?: boolean
  url: string
}
export const getPeriods = async (): Promise<Period[]> => {
  /* 服务端形状：{ periods: [...] }（实测 2026-10-25） */
  const j = await req<{ periods: Period[] }>('/api/periods')
  return j.periods ?? []
}

export type PeriodDetail = {
  period: string
  label?: string
  no?: number
  total?: number
  window?: string
  steps?: { fetch?: boolean; merge?: boolean; generate?: boolean }
  acquisition?: { started?: boolean; verified?: number | null; expected?: number | null; copy?: string }
  lastJob?: { id?: string; status?: string; created_at?: string }
}
export const getPeriodDetail = (period: string) =>
  req<PeriodDetail>(`/api/periods/${encodeURIComponent(period)}`)

/* ── 取数台（取数清单/并入副本） ────────────────────────── */

export type AcqFile = { name?: string; label?: string; state?: string }
export type AcqGroup = {
  id?: string; source?: string; title?: string; state?: string
  verified?: number; downloaded?: number; files?: AcqFile[]
}
export type AcquisitionState = {
  period: string
  started?: boolean
  mode?: string
  /** 要求期次 vs 实际下到哪一期；对不上＝拿当期数据冒充往期（票 03） */
  reconcile?: {
    expected?: { esi?: string; incites?: string }
    actual?: { esi?: string; incites?: string }
    ok?: boolean
  }
  updated_at?: string
  groups?: AcqGroup[]
  totals?: { groups?: number; expected?: number; verified?: number; downloaded?: number; failed?: number }
  copy?: { state?: string; path?: string; built_at?: string; merged_at?: string; merged_by?: string }
}
export const getAcquisition = (period: string) =>
  req<AcquisitionState>(`/api/periods/${encodeURIComponent(period)}/acquisition`)

/* ── 读数（水位矩阵 / 事实卡） ──────────────────────────── */

export type WaterRow = { subject: string; prox: number | null; state: 'in' | 'near' | 'far' | 'unknown' }
export type WaterLevel = { period: string; snapshot: string; rows: WaterRow[]; note?: string }
export const getWaterLevel = (period: string) =>
  req<WaterLevel>(`/api/periods/${encodeURIComponent(period)}/water`)

export type Facts = {
  period: string
  facts: {
    n_disc_1pct: number
    top_papers_now: number
    top_papers_prev: number
    rank_intl_now: number
    rank_intl_delta: number
    coverage_window: string
  }
  assertions: { total: number; fail: number }
  missing: string[]
}
export const getFacts = (period: string) =>
  req<Facts>(`/api/periods/${encodeURIComponent(period)}/facts`)

/* ── 预测选模（看板 / 已保存选择） ──────────────────────── */

export type ForecastBoardRow = {
  subject: string
  model: string
  prox: number | null
  threshold: number | null
}
export type ForecastBoard = { period: string; window: string; routes: Record<string, ForecastBoardRow[]>; note: string }
export const getForecastBoard = (period: string) =>
  req<ForecastBoard>(`/api/forecast/board?period=${encodeURIComponent(period)}`)

export type ForecastChoice = {
  period: string
  choice: Record<string, Record<string, string>>
  by: string
  at: string
  applied?: { choice: Record<string, Record<string, string>>; by: string; at: string; snapshot_at: string } | null
}
export const getForecastChoice = (period: string) =>
  req<ForecastChoice>(`/api/periods/${encodeURIComponent(period)}/forecast-choice`)

/* ── 工作台记录（待填/存疑）与产物 ──────────────────────── */

export type WorkbenchData = {
  period: string
  traceable?: { n: number; with_source: number }
  todo_fill: Array<{ id: string; title: string; filled: string | null }>
  n_filled: number
  n_doubt: number
  approvalStatus?: string
}
export const getWorkbench = (period: string) =>
  req<WorkbenchData>(`/api/periods/${encodeURIComponent(period)}/workbench`)

export type Artifact = { key: string; label: string; name: string; size: number | null; url: string; primary: boolean }
export const getArtifacts = async (period: string): Promise<Artifact[]> => {
  /* 服务端形状：{ period, artifacts: [...] }（实测 2026-10-25） */
  const j = await req<{ artifacts: Artifact[] }>(`/api/periods/${encodeURIComponent(period)}/artifacts`)
  return j.artifacts ?? []
}

/* ── 签单 / 撤回（真门在后端） ──────────────────────────── */

export const signPeriod = (period: string, body: { known: boolean; note?: string }) =>
  req<{ status: string; fingerprint?: unknown }>(
    `/api/periods/${encodeURIComponent(period)}/sign`,
    { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) },
  )

export const revokePeriod = (period: string, note = '') =>
  req<{ status: string }>(
    `/api/periods/${encodeURIComponent(period)}/revoke`,
    { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ note }) },
  )

/* ── 馆员话术（词表沿 lib/status，只拷本壳用到的） ──────── */

export const APPROVAL_LABEL: Record<string, string> = {
  unsigned: '未签发', signed: '已签发', stale: '签发已失效',
}
export const approvalLabel = (status?: string | null): string =>
  (status && APPROVAL_LABEL[status]) || status || '—'

export const TASK_LABEL: Record<string, string> = {
  pending: '待运行', running: '运行中', retrying: '自动修复中', stalled: '已停住',
  waiting_approval: '待签单', completed: '已完成', warned: '已完成（有提醒）',
  escalated: '需人工接手', failed: '失败', cancelled: '已取消',
}
export const taskLabel = (status?: string | null): string =>
  (status && TASK_LABEL[status]) || status || '—'

export function humanSize(n: number | null): string {
  if (n == null) return '—'
  if (n < 1024) return `${n} B`
  if (n < 1024 * 1024) return `${Math.round(n / 1024)} KB`
  return `${(n / 1024 / 1024).toFixed(1)} MB`
}

/** 取数台分组状态 → 馆员话术（未知值原样透出，不编词） */
export function acqStateLabel(state?: string): string {
  const m: Record<string, string> = {
    ok: '已取', done: '已取', verified: '已取', complete: '已取',
    partial: '部分', wait: '待取', missing: '缺', pending: '待取', error: '失败',
  }
  return (state && m[state]) || state || '—'
}

/* ── 运行档案（产线全景的回放真源） ──────────────────────── */

export type WaterfallRow = {
  step: string
  name: string
  status: string
  detail: string
  sec: number
  at: string
  /** 只有开工或只有收工记录：耗时不闭合，界面要标出来 */
  orphan: boolean
}

export type ArchiveAudit = {
  exists: boolean
  verdict: string
  verdict_label: string
  rows: { id: string; title: string; status: string; metric: string; reason: string }[]
  generated_at: string
  truth_chain: string
  elapsed_s: number
}

export type ArchiveData = {
  period: string
  job: Record<string, unknown>
  job_id: string
  /** 一次运行的事实（server/archive.run）：产线只读它，不解释 job/run_log。 */
  run?: { has_run: boolean; status: string; failed: boolean; progress_missing: boolean; steps: number; elapsed_sec: number }
  waterfall: WaterfallRow[]
  waterfall_total: number
  audit: ArchiveAudit
  logpack: { key: string; n_files: number; bytes: number }
}

/** 这次运行的完整档案（状态机回放 / 瀑布 / 审计 / 日志包）——只读 */
export const getArchive = (period: string) =>
  req<ArchiveData>(`/api/periods/${encodeURIComponent(period)}/archive`)
