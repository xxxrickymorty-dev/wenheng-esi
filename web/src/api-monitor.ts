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

export type MonitorReportDone = { period: string; url: string; cached: boolean }

/** 学校名单。`field`＝学科英文名（2026-11-04 契约新增）：
    带上它，items[].in_field 才标「该校在该学科是否在榜」；
    旧服务不认识这个参数就原样忽略——in_field 缺省，界面优雅降级。 */
export async function getMonitorSchools(field?: string): Promise<MonitorSchools> {
  return req<MonitorSchools>(
    `/api/monitor/schools${field ? `?field=${encodeURIComponent(field)}` : ''}`)
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
