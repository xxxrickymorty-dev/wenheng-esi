/* 对话前门（票 01–07）与后端的唯一通道：POST /api/dialog/turn（契约 #33）。
   一轮对话 = 一句话 + 当前槽位 → 路由（两意图）+ 答复字段面（Answer）+ 槽位 + 盘点。
   查数据（kind="query"）时 answer ＝ qa 能力的 Answer（服务器按意图调）；
   解析、盘点、问答都在后端（数字只来自后端，前端不猜期次、不判件齐没齐）。 */

import { req } from './api'
import type { DialogSlots } from './lib/dialog'
import type { DialogHome } from './lib/taskview'

export type { DialogHome }

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
    run＝开跑出稿（产物已在时先问一次，人点了才跑）。 */
export type DialogAction = {
  kind: 'send' | 'goto' | 'dismiss' | 'run'
  text: string
  view?: string
  period?: string
}

/** 出稿意图（票 03/04）：auto=true 直接开跑；false＝产物已在、等人在按钮上确认；
    intent＝出什么稿（票 04 起 = 灵活报告·单学科趋势诊断，走既有流式口）。 */
export type DialogRun = { period: string; auto: boolean; intent: string }

/** 查数据的回答（qa 能力的 Answer 字段面；票 07）。模式：
    model＝大模型组织语言（数字仍只来自后端）｜rule＝规则版｜
    closed/denied/unavailable＝没作答（看 notice 里的话）。 */
export type DialogAnswer = {
  mode: string
  backend: string
  text: string
  rule_text: string
  notice: string
  sources: { index: number; kind: string; pointer: string; label: string; detail: string; value: string }[]
  shield: { checked: number; passed: number }
  record_id: string | null
}

export type DialogReply = {
  mode: string
  backend: string
  text: string
  rule_text: string
  notice: string
  sources: { index: number; kind: string; pointer: string; label: string; detail: string; value: string }[]
  shield: { checked: number; passed: number }
  record_id: string | null
  /** 两意图路由（票 07）：report（写报告）/ query（查数据）/ proceed（继续推进）/ unclear（认不准） */
  kind: 'report' | 'query' | 'proceed' | 'unclear' | ''
  /** 合并后的槽位：本轮解析到的才覆盖，其余不变 */
  slots: DialogSlots
  /** 盘点裁决：unpublished（未发布）/ missing（缺件）/ ready（齐）/ 空（本轮没判） */
  verdict: 'unpublished' | 'missing' | 'ready' | ''
  inventory: DialogInventory | null
  actions: DialogAction[]
  /** 出稿意图（票 03）：null＝本轮不涉及开跑 */
  run: DialogRun | null
  /** 查数据的回答（票 07）；其余轮次为 null */
  answer: DialogAnswer | null
}

export async function postDialogTurn(text: string, slots: DialogSlots): Promise<DialogReply> {
  return req<DialogReply>('/api/dialog/turn', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ text, slots }),
  })
}

/** 空态第一屏「本期任务」（票 06，契约 #35）：三步状态由后端从既有产物判（只读、不新算）。
    形状与展示文案的映射在 `lib/taskview.ts`（纯函数、vitest 直测）。 */
export async function getDialogHome(): Promise<DialogHome> {
  return req<DialogHome>('/api/dialog/home')
}
