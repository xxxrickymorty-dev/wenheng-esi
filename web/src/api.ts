/* 与后端的唯一通道。
   契约见 docs/前后端分工与接口契约（2026-09-23）.md——改字段先改那份文档。
   🔴 铁律：数字只来自后端。这一层**不做换算、不聚合、不四舍五入**，原样透传。 */

export type Period = {
  period: string
  label: string
  signed: boolean
  status: string
  url: string
}

/** 单期详情（契约 §2.2 #2，后端 Batch 1 已交付）——形状按实测的响应写，别按猜的 */
export type PeriodDetail = {
  period: string
  label?: string
  no?: number
  total?: number
  window?: string
  palette?: { primary: string; deep: string; lift: string }
  steps?: { ledger?: boolean; input?: boolean; generated?: boolean }
  lastJob?: { id?: string; status?: string; created_at?: string }
}

export type Me = { name: string; role: 'admin' | 'guest' }

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

async function req<T>(url: string, init?: RequestInit): Promise<T> {
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

/** 单期详情：404/401 都当"未就绪"（契约里的 P0#2 还没上），界面据此标注 */
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
  stats?: Record<string, unknown>
  [k: string]: unknown
}

export async function getJob(jobId: string): Promise<Job> {
  return req<Job>(`/api/jobs/${encodeURIComponent(jobId)}`)
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
