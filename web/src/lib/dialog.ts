/* 对话前门（票 01）：槽位的纯逻辑（ADR-0003 → vitest 直接测）。
   槽位＝可显示、可清、可审计的少量状态（GLOSSARY「槽位」）：当前期次 / 当前意图 /
   问数槽（学科 · 指标，2026-10-31——追问「上一期呢」「那数学呢」的继承载体）。
   每轮的合并由后端完成（只覆盖本轮解析到的）；这里只有「空态 / 清掉 / 起标题」——
   不存历史、不猜期次、不做换算。 */

export type SlotKey = 'period' | 'intent' | 'qmetric' | 'qdisc'

export type DialogSlots = { period: string; intent: string;
  /** 问数槽（2026-10-31）：上一轮认出的指标/学科，追问继承用 */
  qmetric: string; qdisc: string }

/** 未设状态：两格都空（清掉后回到这里）。 */
export function emptySlots(): DialogSlots {
  return { period: '', intent: '', qmetric: '', qdisc: '' }
}

/** 清掉一格（✕）：另一格不变。 */
export function clearSlot(slots: DialogSlots, key: SlotKey): DialogSlots {
  return { ...slots, [key]: '' }
}

export function hasSlots(slots: DialogSlots): boolean {
  return !!slots.period || !!slots.intent
}

/** 对话历史标题：取第一句话（空白折叠、超长截断）——不编标题。 */
export function conversationTitle(text: string): string {
  const t = text.replace(/\s+/g, ' ').trim()
  return t.length > 40 ? `${t.slice(0, 39)}…` : t
}

/* 会话 id（票 11）：URL 参数 `s`——刷新/换设备带 URL 即恢复。
   形状 `s-YYYYMMDD-8hex`（服务端生成）；形状不合法＝当没带，不猜。 */
export const SESSION_PARAM = 's'
const SESSION_ID_RE = /^s-\d{8}-[0-9a-f]{8}$/

/** 从 URL 查询串读会话 id；缺省或形状不合法都返回空串。 */
export function sessionIdFromSearch(search: string): string {
  const v = new URLSearchParams(search).get(SESSION_PARAM) || ''
  return SESSION_ID_RE.test(v) ? v : ''
}

/** 回写会话 id 后的查询串（空 id → 去掉 `s`）；其余参数原样保留。 */
export function withSessionId(search: string, id: string): string {
  const params = new URLSearchParams(search)
  if (id) params.set(SESSION_PARAM, id)
  else params.delete(SESSION_PARAM)
  return params.toString()
}

/* 阶段进度流（票 12，契约 #37）：一行一个事件（NDJSON）。
   只做**纯解析**——网络与界面在 api-dialog / DialogPage；这里可 vitest 直测。 */
export type StreamEvent =
  | { event: 'stage'; stage: string; text: string }
  | { event: 'delta'; text: string }
  /* 工具调用轨迹（2026-10-29）：后端执行完一次只读工具就发一条——
     名字与摘要是后端给的，模型写的字不进来（防夹带没出处的数字）。 */
  | { event: 'tool'; tool: string; label: string; summary: string
      ok: boolean; refused: boolean; ms: number }
  | { event: 'done'; payload: unknown }
  | { event: 'error'; error: string; status?: number }

/** 缓冲 + 新块 → 完整事件；不完整的行留在缓冲里（下一块再拼）。坏行丢弃，不炸。 */
export function parseNdjsonChunks(buffer: string, chunk: string):
    { events: StreamEvent[]; buffer: string } {
  const lines = (buffer + chunk).split('\n')
  const rest = lines.pop() ?? ''
  const events: StreamEvent[] = []
  for (const line of lines) {
    const s = line.trim()
    if (!s) continue
    try {
      const ev = JSON.parse(s) as StreamEvent
      if (ev && typeof ev === 'object' && 'event' in ev) events.push(ev)
    } catch {
      /* 半行/坏行丢弃——进度只是旁路，不挡这一轮对话 */
    }
  }
  return { events, buffer: rest }
}
