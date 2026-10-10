/* 对话前门（票 01）与后端的唯一通道：POST /api/dialog/turn（契约 #33）。
   一轮对话 = 一句话 + 当前槽位 → 答复字段面（Answer）+ 合并后的槽位。
   解析与合并都在后端（数字只来自后端，前端不猜期次）。 */

import { req } from './api'
import type { DialogSlots } from './lib/dialog'

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
}

export async function postDialogTurn(text: string, slots: DialogSlots): Promise<DialogReply> {
  return req<DialogReply>('/api/dialog/turn', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ text, slots }),
  })
}
