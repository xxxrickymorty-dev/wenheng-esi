/* 与后端的唯一通道。
   契约见 docs/前后端分工与接口契约（2026-09-23）.md——改字段先改那份文档。
   🔴 铁律：数字只来自后端。这一层**不做换算、不聚合、不四舍五入**，原样透传。 */

export type Period = {
  period: string
  label: string
  signed: boolean
  status: string
  /** 是否已出过稿（有 out/<期次>/red_slots.json）；取数在途的期次为 false（2026-09-29 补） */
  generated?: boolean
  url: string
}

/** 单期详情（契约 §2.2 #2）——形状按实测的响应写，别按猜的。
    2026-09-29 契约变更：steps 改为 {fetch,merge,generate}（取数 → 核对并并入 → 生成，ADR-0004），
    另加 acquisition 摘要（取数台口径；见契约 §2.2 #26）。 */
export type PeriodDetail = {
  period: string
  label?: string
  no?: number
  total?: number
  window?: string
  palette?: { primary: string; deep: string; lift: string }
  steps?: { fetch?: boolean; merge?: boolean; generate?: boolean }
  acquisition?: { started?: boolean; verified?: number | null; expected?: number | null; copy?: string }
  lastJob?: { id?: string; status?: string; created_at?: string }
}

/** 两个角色（2026-10-11）：admin＝管理员（全可见可写）；operator＝操作员（评委，只读）。 */
export type Me = { name: string; role: 'admin' | 'operator' }

/** 统一错误体（契约 §3.4）：{error, hint?, missing?} */
export type ApiError = { error: string; hint?: string; missing?: { sheet: string; column: string; note?: string }[] }

export class HttpError extends Error {
  status: number
  body: ApiError | null
  constructor(status: number, body: ApiError | null) {
    super(body?.error ?? `HTTP ${status}`)
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
    try {
      body = (await res.json()) as ApiError
    } catch {
      /* 非 JSON 的错误体（比如 404 的 HTML）——留 null，调用方按状态码处理 */
    }
    throw new HttpError(res.status, body)
  }
  return (await res.json()) as T
}

export async function getHealth(): Promise<boolean> {
  try {
    const r = await req<{ ok: boolean }>('/healthz')
    return !!r.ok
  } catch {
    return false
  }
}

/** 角色。后端未提供 /api/me 时降级为「未知」——**不冒充馆员**（权限的真门在后端） */
export async function getMe(): Promise<Me | null> {
  try {
    return await req<Me>('/api/me')
  } catch {
    return null
  }
}

export async function getPeriods(): Promise<Period[]> {
  const r = await req<{ periods: Period[] }>('/api/periods')
  return r.periods ?? []
}

/** 单期详情：404/401 都当"未就绪"处理（拿不到就标注未就绪，不编数据）——契约 #2 已交付 */
export async function getPeriodDetail(period: string): Promise<PeriodDetail | null> {
  try {
    return await req<PeriodDetail>(`/api/periods/${encodeURIComponent(period)}`)
  } catch {
    return null
  }
}

/** 触发一次生成。⚠️ 后端收的是**表单**（period 字段），不是 JSON —— 发错了会 400/422 */
export async function postJob(period: string): Promise<{ job_id: string; url: string }> {
  const fd = new FormData()
  fd.append('period', period)
  return req<{ job_id: string; url: string }>('/api/jobs', { method: 'POST', body: fd })
}

/** 任务事件流（SSE）：progress＝进度行 / log＝{line} / status＝任务对象 JSON */
export function jobEventsUrl(jobId: string): string {
  return `/api/jobs/${encodeURIComponent(jobId)}/events`
}

export type Job = {
  id: string
  status?: string
  period?: string
  out_period?: string
  stats?: Record<string, unknown>
  [k: string]: unknown
}

export async function getJob(jobId: string): Promise<Job> {
  return req<Job>(`/api/jobs/${encodeURIComponent(jobId)}`)
}

/** 任务瀑布里的一步（契约 §2.2 #15）。sec 是**后端算好的**本步耗时，前端不自己减。 */
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

/** 收束汇总事件（「全链路 96.5 秒…」那一条）——不是流水线的一步，单列不混进步骤数组 */
export type WaterfallSummary = { name: string; detail: string; at: string; sec: number }

/** 原始进度记录（一步可能有好几条：开工 / 提醒 / 收工） */
export type ProgressEvent = {
  ts?: string
  step?: string
  name?: string
  status?: string
  detail?: string
  elapsed?: number
}

export type JobProgress = {
  job_id: string
  status: string
  events: ProgressEvent[]
  waterfall: WaterfallRow[]
  summary?: WaterfallSummary
  total_sec: number
  /** 这台机器上读不到进度记录（如工作区迁移过） */
  missing: boolean
  note: string
}

/** 这次运行每一步用了多久（后端把进度事件换算好；生成中可反复取） */
export async function getJobProgress(jobId: string): Promise<JobProgress> {
  return req<JobProgress>(`/api/jobs/${encodeURIComponent(jobId)}/progress`)
}

/** 运行档案（契约 §2.2 #18）：一次运行的完整回放 */
export type ArchiveReplay = {
  chain: { from: string; to: string; trigger: string; ts: string; attempt?: number; synthetic?: boolean }[]
  synthetic: boolean
  note: string
  n: number
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
  stats: Record<string, unknown>
  run_log?: Record<string, unknown>
  waterfall: WaterfallRow[]
  waterfall_summary?: WaterfallSummary
  waterfall_total: number
  progress_missing: boolean
  replay: ArchiveReplay
  audit: ArchiveAudit
  env: Record<string, unknown>
  artifacts: Artifact[]
  logpack: { key: string; n_files: number; bytes: number; files?: { name: string; size: number }[] }
  logpack_url: string
  download_base: string
  trace_files: string[]
}

/** 这次运行的完整档案（状态机回放 / 瀑布 / 审计 / 环境 / 日志包）——只读 */
export async function getArchive(period: string): Promise<ArchiveData> {
  return req<ArchiveData>(`/api/periods/${encodeURIComponent(period)}/archive`)
}

/** 取数台状态（契约 §2.2 #26）：没有取数记录时只有 {period, started:false}。
    形状与 server/acquisition.py 的文档串一致；缺字段按「未就绪」显示，不编数据。 */
export type AcqFile = { name?: string; label?: string; state?: string }
export type AcqGroup = {
  id?: string
  source?: string
  index?: number
  title?: string
  state?: string
  verified?: number
  downloaded?: number
  files?: AcqFile[]
}
export type AcqReviewSheet = { name?: string; added?: string; content?: string; source?: string }
export type AcquisitionState = {
  period: string
  started: boolean
  updated_at?: string
  data_period?: { esi?: string; incites?: string }
  preflight?: { browser?: string; esi?: string; incites?: string }
  capabilities?: { start?: boolean; retry?: boolean; merge?: boolean }
  groups?: AcqGroup[]
  totals?: { groups?: number; expected?: number; verified?: number; downloaded?: number; failed?: number }
  copy?: { state?: string; path?: string; built_at?: string; merged_at?: string }
  review?: { sheets?: AcqReviewSheet[] }
  /** 正在跑的任务（取数/建副本/并入）；闲时没有这个字段 */
  op?: { kind?: string; state?: string; note?: string; at?: string }
}

export async function getAcquisition(period: string): Promise<AcquisitionState> {
  return req<AcquisitionState>(`/api/periods/${encodeURIComponent(period)}/acquisition`)
}

/** 取数写动作（人触发；服务端拉起任务、进度写回状态文件）。409 表示有任务在跑或前置不满足。 */
export type AcquisitionActionResp = {
  ok?: boolean
  started?: boolean
  preflight?: AcquisitionState['preflight']
  error?: string
  hint?: string
}

export async function postAcquisition(period: string, action: string,
                                      body?: Record<string, unknown>): Promise<AcquisitionActionResp> {
  return req<AcquisitionActionResp>(
    `/api/periods/${encodeURIComponent(period)}/acquisition/${action}`,
    {
      method: 'POST',
      ...(body
        ? { headers: { Accept: 'application/json', 'Content-Type': 'application/json' },
            body: JSON.stringify(body) }
        : {}),
    })
}

/** 最近一次有产出的任务（老接口，字段形状见 jobs.list_jobs） */
export type JobStatus = { active?: string | null; last?: { id?: string; period?: string } | null }

export async function getStatus(): Promise<JobStatus> {
  return req<JobStatus>('/api/status')
}

/** 产物：{key,label,name,size,url,primary}（jobs.collect_artifacts 的落盘形状） */
export type Artifact = {
  key: string
  label: string
  name: string
  size: number | null
  url: string
  primary: boolean
}

/** 某一期的产物清单；每张卡始终从所选期次读取。 */
export async function getPeriodArtifacts(period: string): Promise<Artifact[]> {
  const r = await req<{ period: string; artifacts: Artifact[] }>(
    `/api/periods/${encodeURIComponent(period)}/artifacts`,
  )
  return r.artifacts ?? []
}

export async function getArtifacts(jobId: string): Promise<Artifact[]> {
  const r = await req<{ job: unknown; artifacts: Artifact[] }>(
    `/api/jobs/${encodeURIComponent(jobId)}/artifacts`,
  )
  return r.artifacts ?? []
}

/** 字节数转人类可读——这是**格式**不是口径，允许在前端做 */
export function humanSize(n: number | null): string {
  if (n == null) return ''
  if (n < 1024) return `${n} B`
  if (n < 1024 * 1024) return `${Math.round(n / 1024)} KB`
  return `${(n / 1024 / 1024).toFixed(1)} MB`
}


/** 上传当期数据表并开跑（与老站 index.js 同一套：同一个 /api/jobs，带 file 字段） */
export async function postJobWithFile(period: string, file: File): Promise<{ job_id: string; url: string }> {
  const fd = new FormData()
  fd.append('period', period)
  fd.append('file', file)
  return req<{ job_id: string; url: string }>('/api/jobs', { method: 'POST', body: fd })
}

/** 重跑本期（老站 job.js 一直在用的端点；旧稿撤到 _superseded/） */
export async function rerunJob(jobId: string): Promise<{ job_id?: string; url?: string }> {
  return req<{ job_id?: string; url?: string }>(`/api/jobs/${encodeURIComponent(jobId)}/rerun`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: '{}',
  })
}

/** 回滚点（票 07）：旧版留档清单，新→旧；只列真带成品的目录。 */
export type RollbackPoint = { id: string; files: string[] }

export async function getRollbackPoints(period: string): Promise<RollbackPoint[]> {
  const r = await req<{ points?: RollbackPoint[] }>(
    `/api/periods/${encodeURIComponent(period)}/rollback-points`,
  )
  return r.points ?? []
}

export async function rollbackPeriod(period: string, point: string): Promise<{ ok: boolean; restored: string[] }> {
  return req<{ ok: boolean; restored: string[] }>(
    `/api/periods/${encodeURIComponent(period)}/rollback`,
    { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ point }) },
  )
}

/** AI 能力开关表（契约 §2.2 #28）：分析台「问文衡」的开关读它；仅 admin */
export type AiCapability = {
  id: string
  label: string
  stage: string
  min_role: string
  enabled: boolean
  allowed: boolean
  notice: string
}

export async function getAiCapabilities(): Promise<AiCapability[]> {
  const r = await req<{ capabilities: AiCapability[] }>('/api/ai/capabilities')
  return r.capabilities ?? []
}

/** 能力开关唯一写口（契约 §2.2 #29，仅管理员）。关掉只是不答问，数字与报告不受影响。 */
export async function postAiSwitch(capability: string, enabled: boolean): Promise<void> {
  await req<{ ok: boolean }>('/api/ai/switch', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ capability, enabled }),
  })
}

/** 问答与模型调用记录（契约 §2.2 #30；运行档案「问答与模型调用」块）。
    只有摘要（问题占位面/模式/后端/回落原因/盾计数/耗时），不含回答正文与提示词。 */
export type AiCall = {
  record_id: string
  ts: string
  capability: string
  mode: string
  backend: string
  fallback: string | null
  shield: { checked: number; passed: number }
  n_tools: number
  question: string
  label: string
  elapsed_ms: number
}
export type AiCalls = {
  period: string
  calls: AiCall[]
  stats: { n: number; model: number; fallback: number; avg_sec: number; last_ts: string }
}

export async function getAiCalls(period: string): Promise<AiCalls> {
  return req<AiCalls>(`/api/periods/${encodeURIComponent(period)}/ai-calls`)
}
