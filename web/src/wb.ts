/* 生成台的八种状态 + 失败文案。
   规格见 web/UX-生成台.md（§3 状态清单、§4 错误文案）。
   🔴 这一层只做**推导**与**文案**，不产生任何数字——数字一律来自 api.ts。 */

import type { ApiError, Period, PeriodDetail } from './api'
import { TERMINAL_STATES } from './lib/status'

export type WBState =
  | 'empty' | 'ready' | 'running' | 'done' | 'warned' | 'waiting-approval'
  | 'fail-ledger' | 'fail-other' | 'stalled' | 'signed'

export const STATE_LABEL: Record<WBState, string> = {
  empty: '数据还没取齐',
  ready: '待生成',
  running: '生成中',
  done: '已生成',
  warned: '已生成，有校验提醒',
  'waiting-approval': '待签单',
  'fail-ledger': '数据还没齐',
  'fail-other': '这次没有出稿',
  stalled: '已停住',
  signed: '已签发',
}

/** 三步条上每格显示什么（ADR-0004：下载数据 → 核对并并入 → 生成） */
export type StepView = { key: 'fetch' | 'merge' | 'generate'; title: string; detail: string; on: boolean; now: boolean }

export type Workbench = {
  state: WBState
  /** 三步里前两步的状态是否已知（后端没给单期详情时为 false —— 界面要说明） */
  stepsKnown: boolean
  steps: StepView[]
  focusTitle: string
  focusSub: string
  focusAction: 'generate' | 'rerun' | 'open' | 'sign' | 'acquire' | 'none'
  note?: string
}

/** 三步条：能算的算，算不出的写「未就绪」——不编数据。
    数字（已核验 x / y）只来自后端 acquisition 摘要，前端不做任何换算。 */
function buildSteps(detail: PeriodDetail | null, generated: boolean, period: string): StepView[] {
  const s = detail?.steps
  const acq = detail?.acquisition
  const known = !!s
  const fetchDetail = !known ? '未就绪'
    : s?.fetch
      ? (acq?.started ? `下载数据完成（${acq.verified ?? '—'} / ${acq.expected ?? '—'}）` : '数据已就位')
      : acq?.started
        ? `下载中（${acq.verified ?? '—'} / ${acq.expected ?? '—'}）`
        : '还没开始下载数据'
  const mergeDetail = !known ? '未就绪'
    : s?.merge ? '已并入台账'
      : acq?.copy === 'review' ? '待核对（核对副本已建）' : '核对副本还没建'
  return [
    { key: 'fetch', title: '下载数据', detail: fetchDetail, on: !!s?.fetch, now: known && !s?.fetch },
    { key: 'merge', title: '核对并并入', detail: mergeDetail,
      on: !!s?.merge, now: known && !!s?.fetch && !s?.merge },
    { key: 'generate', title: '一键生成', detail: generated ? '已出稿' : (known ? '约 20 秒出报告' : `${period} 尚未出稿`),
      on: generated, now: known ? (!!s?.fetch && !!s?.merge && !generated) : !generated },
  ]
}

/** 失败文案：能拿到结构化 missing 就用它；拿不到就说清"没有详情"，不去解析字符串 */
export function failureCopy(err: ApiError | null, healthy: boolean) {
  if (!healthy) {
    return {
      title: '连不上服务',
      lines: ['本机的服务没有响应 —— 检查它是否在运行。', '你的台账与上一版报告都没有受影响。'],
    }
  }
  if (err?.missing?.length) {
    return {
      title: '数据还没齐，这次没有出报告',
      lines: [
        ...err.missing.map((m) => `《${m.sheet}》缺少 ${m.column}${m.note ? `（${m.note}）` : ''}`),
        '补上后点「重新生成」即可。',
      ],
    }
  }
  return {
    title: err?.error ?? '这次没有出稿',
    lines: [
      err?.hint ?? '点「重新生成」再试一次；若反复失败，把这一屏截图给开发。',
      '上一版报告仍然有效 —— 本次失败没有动它。',
    ],
  }
}

/**
 * 从**真实数据**推导当前状态。
 * 只有两条是"看数据就能确定"的：已签发（签单状态）、已出稿（期次出现在列表里＝有 red_slots.json）。
 * 其余（台账齐不齐、正在跑没跑）需要后端详情/任务接口；没就绪就如实说。
 */
export function deriveWorkbench(
  period: string | null,
  list: Period[],
  detail: PeriodDetail | null,
  healthy: boolean,
  demo?: WBState | null,
): Workbench {
  const row = list.find((p) => p.period === period) ?? null
  /* 「已出稿」以列表的 generated 标志为准（下载数据在途的期次也在列表里，但还没出稿）；
     老形状没有该字段时退回「在列表里＝出过稿」——不编数据。 */
  const generated = row ? (row.generated ?? true) : false
  const signed = row?.status === 'signed' || row?.signed === true

  let state: WBState
  let notes: string | undefined

  if (!healthy) {
    state = 'fail-other'
    notes = '服务未启动：下面显示的是上一次已知状态，不是实时状态。'
  } else if (signed) {
    state = 'signed'
  } else if (generated) {
    state = 'done'
  } else if (detail?.steps && (!detail.steps.fetch || !detail.steps.merge)) {
    state = 'empty'         /* 下载数据没齐，或取完了还没核对并入——都先去下载数据台 */
  } else {
    state = 'ready'
  }

  if (!detail && healthy) {
    notes = '后端未提供单期详情，前两步的状态暂时无法显示；' +
      '「是否已出稿 / 是否已签发」来自期次列表，是真的。'
  }
  if (demo) {
    state = demo
    notes = `演示模式：下面显示的是示例状态，不是真实状态。`
  }

  const steps = buildSteps(detail, generated, period ?? '本期')

  const FOCUS: Record<WBState, Pick<Workbench, 'focusTitle' | 'focusSub' | 'focusAction'>> = {
    empty: { focusTitle: '先去下载数据，再回来生成', focusSub: '在下载数据台：下载 → 逐份核验 → 核对并并入台账', focusAction: 'acquire' },
    ready: { focusTitle: '这一期还差最后一步：生成报告', focusSub: '前两步已就绪 · 约 20 秒出报告', focusAction: 'generate' },
    running: { focusTitle: '正在生成……', focusSub: '可以切到别的页面，进度不会丢', focusAction: 'none' },
    done: { focusTitle: '本期报告已就绪', focusSub: '复核后签单，这一版才会被标记为「可交付」', focusAction: 'sign' },
    warned: { focusTitle: '已生成，有校验提醒', focusSub: '任务结束不代表报告合格或已签发', focusAction: 'open' },
    'waiting-approval': { focusTitle: '待签单', focusSub: '报告已出，等你在审核台签单', focusAction: 'none' },
    'fail-ledger': { focusTitle: '数据还没齐，这次没有出报告', focusSub: '补上缺的列再重跑', focusAction: 'rerun' },
    'fail-other': { focusTitle: '这次没有出稿', focusSub: '上一版报告仍然有效', focusAction: 'rerun' },
    stalled: { focusTitle: '已停住', focusSub: '已有一段时间没有进展，可以重跑试试', focusAction: 'rerun' },
    signed: { focusTitle: '本期已签发', focusSub: '重新生成会使签名失效', focusAction: 'open' },
  }

  return { state, stepsKnown: !!detail, steps, note: notes, ...FOCUS[state] }
}

/** 后端任务状态（src/agent/states.py 的 10 态，权威）→ 工作台八态 */
const TERMINAL = new Set<string>(TERMINAL_STATES)

export function isTerminal(status?: string): boolean {
  return !!status && TERMINAL.has(status)
}

export function statusToWB(status?: string): WBState {
  switch (status) {
    case 'completed':
      return 'done'
    case 'warned':
      return 'warned'
    case 'waiting_approval':
      return 'waiting-approval'
    case 'escalated':
    case 'failed':
    case 'cancelled':
      return 'fail-other'
    case 'stalled':
      return 'stalled'
    case 'pending':
    case 'running':
    case 'retrying':
      return 'running'
    default:
      return 'ready'
  }
}
