/* 票 06 · 空态第一屏「本期任务」：三步状态 → 显示文案（纯函数，vitest 直测）。
   状态由后端从**既有产物**判（GET /api/dialog/home）；这里只翻馆员话术与主按钮——
   前端不猜状态、不做期次换算。卡在哪＝第一个没做完的那步；都做完没签发＝卡在签单。 */

export type HomeStepKey = 'acquire' | 'merge' | 'generate'

export type HomeStep = { key: HomeStepKey; done: boolean }

export type DialogHome = {
  period: string
  /** 该期已在主台账里（并入的凭证；没并入＝「未到（随发布）」口径） */
  released: boolean
  /** 下载数据还缺几件（released 时用于「还缺 N 件」） */
  n_missing: number
  steps: HomeStep[]
  stuck: HomeStepKey | 'sign' | ''
  /** 上一期与它的签发状态（后端 approval 的口径：signed / stale / unsigned） */
  prev: { period: string; status: string } | null
}

export type TaskViewRow = { mark: '✓' | '●' | '○'; label: string; note: string }
export type TaskViewCta = { label: string; kind: 'goto' | 'gen'; view?: string }
export type TaskView = {
  title: string
  rows: TaskViewRow[]
  cta: TaskViewCta | null
  prevNote: string
}

const LABELS: Record<HomeStepKey, string> = {
  acquire: '取数', merge: '核对并并入', generate: '一键生成',
}

/** 上一期签发状态 → 馆员话术（后端 approval 三态 + 兜底原样）。 */
const PREV_LABEL: Record<string, string> = {
  signed: '已签发', stale: '签发已失效', unsigned: '未签发',
}

export function taskView(h: DialogHome | null): TaskView | null {
  if (!h || !h.period) return null
  const done = (k: HomeStepKey) => h.steps.find((s) => s.key === k)?.done === true
  const mark = (k: HomeStepKey): '✓' | '●' | '○' =>
    done(k) ? '✓' : h.stuck === k ? '●' : '○'

  const rows: TaskViewRow[] = [
    { mark: mark('acquire'), label: LABELS.acquire,
      note: done('acquire') ? '数据齐'
        : h.stuck === 'acquire' ? (h.released ? `还缺 ${h.n_missing} 件` : '数据未到（随发布）')
        : '未开始' },
    { mark: mark('merge'), label: LABELS.merge,
      note: done('merge') ? '已并入' : h.stuck === 'merge' ? '卡在这' : '未开始' },
    { mark: mark('generate'), label: LABELS.generate,
      note: done('generate') ? (h.stuck === 'sign' ? '已出好 · 未签发' : '已出好')
        : h.stuck === 'generate' ? '卡在这' : '未开始' },
  ]

  const cta: TaskViewCta | null =
    h.stuck === 'acquire' ? { label: '去取数台 ▸', kind: 'goto', view: 'acquire' }
    : h.stuck === 'merge' ? { label: '去核对 ▸', kind: 'goto', view: 'acquire' }
    : h.stuck === 'generate' ? { label: '一键生成 ▸', kind: 'gen' }
    : h.stuck === 'sign' ? { label: '去审核台签单 ▸', kind: 'goto', view: 'review' }
    : null

  const prevNote = h.prev
    ? `上一期 ${h.prev.period}：${PREV_LABEL[h.prev.status] ?? h.prev.status}`
    : ''
  return { title: `本期任务 · ${h.period}`, rows, cta, prevNote }
}
