/* 模型清单（2026-10-29；2026-11-04 v2：供应商＋模型目录，照 DSH 图二形制）。
   对话框里切模型、设置里配供应商。后端 `/api/models*`（server/routes/dialog.py）。
   **key 只回掩码**——界面上永远看不到原文，要换 key 就在设置里重新填一次。

   口径：一条供应商＝一个网关接入（地址/key/协议/自定义头）＋一份模型目录
   （从网关拉来挑过的型号子集）；当前模型是「哪条供应商＋目录里哪个型号」，
   全局（服务端保存），切完下一句话即生效；
   清单落服务器 `out/_ai/models.json`，不进仓库。 */

import { req } from './api'

/** 三种协议（后端 `_models.PROTOCOLS` 同词表）；都真实现。 */
export type Protocol = 'openai' | 'openai-responses' | 'anthropic'

export const PROTOCOL_LABELS: Record<Protocol, string> = {
  'openai': 'OpenAI Chat Completions',
  'openai-responses': 'OpenAI Responses',
  'anthropic': 'Anthropic Messages',
}

export type ProviderRow = {
  /** 空串＝服务器 `.env` 里的部署配置（界面里改不了，只能选用） */
  id: string
  label: string
  base_url: string
  protocol: string
  /** `sk-…末四位` 或「未配置 key」「由环境变量提供」 */
  key_hint: string
  note: string
  builtin: boolean
  /** 地址/key/模型目录齐了才算能用 */
  ready: boolean
  /** 当前模型（全局那个）落在这条供应商上 */
  active: boolean
  /** 当前在这条上用的型号（未激活＝目录第一个，给「用这个」预览） */
  active_model: string
  /** 模型目录：从网关拉来挑过的型号子集 */
  models: string[]
  /** 自定义请求头；只在配了时才出现 */
  headers?: Record<string, string>
}

export type Preset = { key: string; label: string; base_url: string; models: string[] }

export type ModelsPayload = {
  active: { provider: string; model: string }
  providers: ProviderRow[]
  presets: Preset[]
}

export type ProviderDraft = {
  id?: string
  label: string
  base_url: string
  /** 留空＝沿用已存的 key（新增时必须填） */
  key: string
  note?: string
  /** 三选一；不给＝后端存 openai 缺省 */
  protocol?: string
  /** 整份模型目录随表单提交 */
  models?: string[]
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

/** 「获取可用模型」：网关型号清单（不落库，给界面挑）。 */
export type RemoteModels = {
  ok: boolean
  ms: number
  msg: string
  ids: string[]
}

export async function getModels(): Promise<ModelsPayload> {
  return req<ModelsPayload>('/api/models')
}

export async function saveProvider(draft: ProviderDraft): Promise<ModelsPayload> {
  const r = await req<{ models: ModelsPayload }>('/api/models/save', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(draft),
  })
  return r.models
}

export async function removeProvider(id: string): Promise<ModelsPayload> {
  const r = await req<{ models: ModelsPayload }>('/api/models/remove', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ id }),
  })
  return r.models
}

/** 切当前模型（哪条供应商＋目录里哪个型号；model 省略＝目录第一个）。 */
export async function setActiveModel(provider: string, model = ''): Promise<ModelsPayload> {
  const r = await req<{ models: ModelsPayload }>('/api/models/active', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ provider, model }),
  })
  return r.models
}

/** 探活：给了 id 就测清单里那条供应商（后端用已存的 key 与 headers），否则测表单里这组。 */
export async function testModel(p: { id?: string; base_url?: string; key?: string;
                                     model?: string; headers?: Record<string, string> }):
  Promise<ProbeResult> {
  return req<ProbeResult>('/api/models/test', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(p),
  })
}

/** 「获取可用模型」（图二按钮）：拉网关型号清单。给了 id 用清单里那条的地址与 key。 */
export async function listRemoteModels(p: { id?: string; base_url?: string; key?: string;
                                            headers?: Record<string, string> }):
  Promise<RemoteModels> {
  return req<RemoteModels>('/api/models/list-remote', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(p),
  })
}
