/* 监测版（高校 ESI 报告）——契约见 docs/前后端分工与接口契约 文档「监测版」节。
   数字只来自后端（ESI 全局件的缓存与产物），本层原样透传。 */

import { req } from './api'

export type MonitorSchool = {
  /** 中文名＝槽位主键（同一中文名一份报告） */
  cn: string
  /** ESI 机构名（报告页里展示，用于人工核对校名绑定） */
  en: string
  prov: string
  is985: boolean
  /** 本期全球机构总表 / 22 学科榜里搜得到该校（false＝报告会如实呈现未上榜） */
  known: boolean
  generated: boolean
  url: string | null
  /** 该校是否在本学科（?field= 学科英文名）的榜内（2026-11-04 契约新字段）；
      旧服务没这个字段 / 没带 field 参数时为空——界面徽标不显示（不误标）。 */
  in_field?: boolean
}

export type MonitorSchools = {
  period: string
  built: string | null
  schools: MonitorSchool[]
}

/* ---- 生成任务口（2026-11-04 任务制迁移；契约 §9）----
   生成不再走同步 POST（旧口 /api/monitor/report、/api/monitor/compare
   后端原样并存，前端不再调用）：先开任务（立刻回 job_id），再轮询
   任务状态到终态。单飞由后端把守：另有监测任务在跑 → 409 人话
   （HttpError.message 即后端原文，直接亮给馆员）。 */

/** 开任务的回执：job_id＋状态口地址。reused:true＝同参任务已在跑，
    直接复用它的 job_id（前端当普通任务盯即可）。 */
export type MonitorJobStart = {
  job_id: string
  /** 状态口地址（/api/monitor/jobs/{id}）；前端用 monitorJobUrl 拼同款 */
  url: string
  status: 'running'
  reused?: boolean
}

/** 任务状态（轮询口 GET /api/monitor/jobs/{id} 的响应）：
    completed 的 url＝产物页地址（直接用）；
    failed 的 error＝给人看的原因全文（后端已写成人话）。 */
export type MonitorJob = {
  id: string
  kind: 'monitor_report' | 'monitor_compare'
  period: string
  params: Record<string, unknown>
  status: 'running' | 'completed' | 'failed'
  url: string | null
  error: string | null
  created_at: string
  started_at: string | null
  finished_at: string | null
}

export function monitorJobUrl(jobId: string): string {
  return `/api/monitor/jobs/${encodeURIComponent(jobId)}`
}

/** 开一个单校报告生成任务。 */
/** 开一个单校站位报告生成任务。`force`＝「重新生成」：产物已存在也覆盖重出
    （不带则幂等复用旧件，模型解读不会重跑——2026-11-05 修）。 */
export async function startMonitorReportJob(cn: string, force = false): Promise<MonitorJobStart> {
  return req<MonitorJobStart>('/api/monitor/report/job', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ school: cn, force }),
  })
}

/** 开一个多校对比报告生成任务（名单去重保序由后端做）。 */
export async function startMonitorCompareJob(cns: string[]): Promise<MonitorJobStart> {
  return req<MonitorJobStart>('/api/monitor/compare/job', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ schools: cns }),
  })
}

/** 读任务状态（轮询）。 */
export async function getMonitorJob(jobId: string): Promise<MonitorJob> {
  return req<MonitorJob>(monitorJobUrl(jobId))
}

/** 学校名单。`field`＝学科英文名（2026-11-04 契约新增）：
    带上它，items[].in_field 才标「该校在该学科是否在榜」；
    旧服务不认识这个参数就原样忽略——in_field 缺省，界面优雅降级。 */
export async function getMonitorSchools(field?: string): Promise<MonitorSchools> {
  return req<MonitorSchools>(
    `/api/monitor/schools${field ? `?field=${encodeURIComponent(field)}` : ''}`)
}
