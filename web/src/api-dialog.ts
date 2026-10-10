/* 对话前门（票 01/02）与后端的唯一通道：POST /api/dialog/turn（契约 #33）。
   一轮对话 = 一句话 + 当前槽位 → 答复字段面（Answer）+ 合并后的槽位 + 盘点。
   解析、盘点与合并都在后端（数字只来自后端，前端不猜期次、不判件齐没齐）。 */

import { req } from './api'
import type { DialogSlots } from './lib/dialog'

/** 必需件一行（key/label/state）。state: ok | missing */
export type DialogPiece = {
  key: string
  label: string
  state: 'ok' | 'missing'
  note?: string
}

/** 盘点结果（四件）。n_missing>0 即缺件；released=false 即该期数据未发布。 */
export type DialogInventory = {
  period: string
  released: boolean
  pieces: DialogPiece[]
  n_pieces: number
  n_missing: number
  fallback: string
}

/** 一轮对话给出的动作：
    send＝把 text 当作下一句话发出去；goto＝跳站内视图；dismiss＝先等等（仅界面）；
    run＝开跑出稿（调既有 POST /api/jobs；产物已在时先问一次，人点了才跑）。 */
export type DialogAction = {
  kind: 'send' | 'goto' | 'dismiss' | 'run'
  text: string
  view?: string
  period?: string
}

/** 出稿意图（票 03/04）：auto=true 直接开跑；false＝产物已在、等人在按钮上确认；
    intent＝出什么稿（票 04 起 = 灵活报告·单学科趋势诊断，走既有流式口）。 */
export type DialogRun = { period: string; auto: boolean; intent: string }

export type DialogReply = {
  mode: string
  backend: string
  text: string
  rule_text: string
  notice: string
  sources: { index: number; kind: string; pointer: string; label: string; detail: string; value: string }[]
  shield: { checked: number; passed: number }
  record_id: string | null
  /** 合并后的槽位：本轮解析到的才覆盖，其余不变 */
  slots: DialogSlots
  /** 盘点裁决：unpublished（未发布）/ missing（缺件）/ ready（齐）/ 空（本轮没判） */
  verdict: 'unpublished' | 'missing' | 'ready' | ''
  inventory: DialogInventory | null
  actions: DialogAction[]
  /** 出稿意图（票 03）：null＝本轮不涉及开跑 */
  run: DialogRun | null
}

export async function postDialogTurn(text: string, slots: DialogSlots): Promise<DialogReply> {
  return req<DialogReply>('/api/dialog/turn', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ text, slots }),
  })
}
