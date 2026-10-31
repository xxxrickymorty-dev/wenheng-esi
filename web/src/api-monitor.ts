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
}

export type MonitorSchools = {
  period: string
  built: string | null
  schools: MonitorSchool[]
}

export type MonitorReportDone = { period: string; url: string; cached: boolean }

export async function getMonitorSchools(): Promise<MonitorSchools> {
  return req<MonitorSchools>('/api/monitor/schools')
}

export async function generateMonitorReport(cn: string): Promise<MonitorReportDone> {
  return req<MonitorReportDone>('/api/monitor/report', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ school: cn }),
  })
}

export async function generateCompareReport(cns: string[]): Promise<{ period: string; url: string; n: number }> {
  return req('/api/monitor/compare', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ schools: cns }),
  })
}
