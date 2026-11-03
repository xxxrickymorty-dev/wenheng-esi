/* 模型清单（2026-10-29）：对话框里切模型、设置里配模型。
   后端 `/api/models*`（server/app.py）。**key 只回掩码**——界面上永远看不到原文，
   要换 key 就在设置里重新填一次。

   口径：当前模型是**全局**的（服务端保存），切完下一句话即生效；
   清单落服务器 `out/_ai/models.json`，不进仓库。 */

import { req } from './api'

export type ModelRow = {
  /** 空串＝服务器 `.env` 里的部署配置（界面里改不了，只能选用） */
  id: string
  label: string
  base_url: string
  model: string
  /** `sk-…末四位` 或「未配置 key」「由环境变量提供」 */
  key_hint: string
  note: string
  builtin: boolean
  /** 地址/型号/key 齐了才算能用 */
  ready: boolean
  active: boolean
  /** 目前只有 OpenAI Compatible 一种（后端存 "openai" 缺省，展示用） */
  protocol?: string
  /** 自定义请求头（票 4）：探活与调用时叠加；只在配了时才出现 */
  headers?: Record<string, string>
}

export type Preset = { key: string; label: string; base_url: string; models: string[] }

export type ModelsPayload = { active: string; models: ModelRow[]; presets: Preset[] }

export type ModelDraft = {
  id?: string
  label: string
  base_url: string
  model: string
  /** 留空＝沿用已存的 key（新增时必须填） */
  key: string
  note?: string
  /** 目前只有 OpenAI Compatible 一种，随表单提交（后端存 "openai" 缺省） */
  protocol?: string
  /** 自定义请求头（表单 Headers 每行 K=V 解析成对象提交）；空对象＝没有 */
  headers?: Record<string, string>
}

export type ProbeResult = {
  ok: boolean
  ms: number
  msg: string
  n_models?: number
  error?: string
}

export async function getModels(): Promise<ModelsPayload> {
  return req<ModelsPayload>('/api/models')
}

export async function saveModel(draft: ModelDraft): Promise<ModelsPayload> {
  const r = await req<{ models: ModelsPayload }>('/api/models/save', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(draft),
  })
  return r.models
}

export async function removeModel(id: string): Promise<ModelsPayload> {
  const r = await req<{ models: ModelsPayload }>('/api/models/remove', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ id }),
  })
  return r.models
}

export async function setActiveModel(id: string): Promise<ModelsPayload> {
  const r = await req<{ models: ModelsPayload }>('/api/models/active', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ id }),
  })
  return r.models
}

/** 探活：给了 id 就测清单里那条（后端用已存的 key 与 headers），否则测表单里这一组。 */
export async function testModel(p: { id?: string; base_url?: string; key?: string; model?: string;
                                     headers?: Record<string, string> }):
  Promise<ProbeResult> {
  return req<ProbeResult>('/api/models/test', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(p),
  })
}
