/* 学科报告区测试（2026-11-04 票 1 自学科分析页迁移，用例语义不变；无 jsdom——
   与全站同口径，照 ModelPanel.test.tsx 的缝）：
   - DisciplineView 静态渲染：22 张学科卡 / 空名单空态 / 「打开最近一份」条件链 /
     写作位时长预告 / 生成中禁用与其余卡的锁 / 非 admin 提示上卡面；
   - cardAction（权限分流）：admin 生成 / 非 admin 且最近报告同学科 → 打开 / 否则提示；
   - generateDisciplineReport（卡片 onClick 走的同一份控制器，api-flexible 整体 mock）：
     进度句 规划中…→第 N 节…→收尾…，done 后 window.open 开 report.html，
     error 事件与请求失败各上一句、不开窗；
   - 票 2 看门狗：无事件 90s → abort＋中断提示；ping 重置计时（不上进度）；
     流终止无终态事件 → 中断提示。 */

import { afterEach, describe, expect, it, vi } from 'vitest'
import { renderToStaticMarkup } from 'react-dom/server'

vi.mock('../api-flexible', () => ({
  getFlexible: vi.fn(),
  runFlexibleStream: vi.fn(),
}))

import {
  cardAction, DisciplineView, generateDisciplineReport, INTERRUPTED_NOTE,
  latestDiscOf, reportUrl, STAGE_PLANNING, STAGE_TAIL, stageSection, WATCHDOG_MS,
} from './DisciplineSection'
import { runFlexibleStream, type FlexStreamEvent, type FlexibleDiscipline } from '../api-flexible'
import type { Me } from '../api'

/* ------------------------------------------------------------------ 桩 */

/** ESI 22 学科（名单本体在后端；这里照 SchoolsPage 同一份名录给满 22 张） */
const DISC22: FlexibleDiscipline[] = [
  'Agricultural Sciences|农业科学', 'Biology & Biochemistry|生物学与生物化学', 'Chemistry|化学',
  'Clinical Medicine|临床医学', 'Computer Science|计算机科学', 'Economics & Business|经济与商业',
  'Engineering|工程学', 'Environment/Ecology|环境生态学', 'Geosciences|地球科学', 'Immunology|免疫学',
  'Materials Science|材料科学', 'Mathematics|数学', 'Microbiology|微生物学',
  'Molecular Biology & Genetics|分子生物学与遗传学', 'Multidisciplinary|多学科',
  'Neuroscience & Behavior|神经系统科学与行为学', 'Pharmacology & Toxicology|药理学与毒理学',
  'Physics|物理学', 'Plant & Animal Science|植物与动物学', 'Psychiatry/Psychology|精神病学与心理学',
  'Social Sciences, general|社会科学', 'Space Science|空间科学',
].map((s) => { const [en, cn] = s.split('|'); return { en, cn } })

const ADMIN: Me = { name: '馆员', role: 'admin' }
const OPERATOR: Me = { name: '评委', role: 'operator' }
const MATH: FlexibleDiscipline = { en: 'Mathematics', cn: '数学' }

function view(over: Partial<Parameters<typeof DisciplineView>[0]> = {}): string {
  return renderToStaticMarkup(
    <DisciplineView period="202607" loading={false} loadErr="" hasReport={false}
                    writeAvailable={false} disciplines={DISC22} busy={null} stage=""
                    note={null} recent={null} onCard={() => {}} {...over} />)
}

/** runFlexibleStream 的假流：把 events 依序喂给 onEvent 后正常收束。 */
function emit(events: FlexStreamEvent[]) {
  vi.mocked(runFlexibleStream).mockImplementation(
    async (_period, _body, onEvent) => { for (const ev of events) onEvent(ev) })
}

afterEach(() => {
  vi.unstubAllGlobals()
  vi.clearAllMocks()
})

/* ------------------------------------------------------------------ 渲染 */

describe('DisciplineView：22 张学科卡', () => {
  it('后端名单 22 项 → 22 张卡，中文名衬线大字＋英文名小字＋角标箭头', () => {
    const html = view()
    expect((html.match(/class="dp-card"/g) ?? []).length).toBe(22)
    expect(html).toContain('数学')
    expect(html).toContain('Space Science')
    expect((html.match(/class="dp-arrow"/g) ?? []).length).toBe(22)
  })

  it('空名单给整区空态；名单未读到（loading）不闪空态', () => {
    const empty = view({ disciplines: [] })
    expect(empty).toContain('本期还没有可分析的学科')
    expect(empty).not.toContain('dp-card')
    const pending = view({ loading: true })
    expect(pending).not.toContain('本期还没有可分析的学科')
    expect(pending).not.toContain('dp-card')
  })

  it('「打开最近一份」只在 reports 含 single_trend 时出现，链到公开读路由', () => {
    const off = view()
    expect(off).not.toContain('打开最近一份')
    const on = view({ hasReport: true })
    expect(on).toContain('打开最近一份')
    expect(on).toContain(`href="${reportUrl('202607')}"`)
  })

  it('写作位开启 → 区头一句时长预告（票 2）；未开启不出现', () => {
    const off = view()
    expect(off).not.toContain('写作位开启')
    const on = view({ writeAvailable: true })
    expect(on).toContain('写作位开启：出稿含逐段润色，需数分钟')
  })

  it('生成中：全员禁用（单任务锁），正在生成那张全亮并显示进度句；完成后标「最近生成」', () => {
    const running = view({ busy: 'Mathematics', stage: stageSection(2) })
    expect((running.match(/disabled=""?/g) ?? []).length).toBe(22)
    expect(running).toContain('data-now="true"')
    expect(running).toContain('第 2 节…')
    const done = view({ recent: 'Mathematics' })
    expect(done).toContain('最近生成')
  })

  it('非 admin 点未生成卡的提示上卡面（hint，不禁用整区）', () => {
    const html = view({ note: { en: 'Chemistry', kind: 'hint', text: '生成请找管理员' } })
    expect(html).toContain('生成请找管理员')
    expect((html.match(/disabled=""?/g) ?? []).length).toBe(0)
  })
})

/* ------------------------------------------------------------------ 权限分流 */

describe('cardAction：生成 / 打开 / 提示 的唯一口径', () => {
  it('admin → 生成', () => {
    expect(cardAction(ADMIN, MATH, null)).toEqual({ kind: 'generate' })
  })

  it('非 admin：最近一份报告正是这个学科 → 打开（spec：打开人人可用，不设角色门）；否则 → 提示找管理员', () => {
    expect(cardAction(OPERATOR, MATH, 'Mathematics')).toEqual({ kind: 'open' })
    expect(cardAction(OPERATOR, MATH, 'Engineering')).toEqual({ kind: 'hint' })
    expect(cardAction(OPERATOR, MATH, null)).toEqual({ kind: 'hint' })
    expect(cardAction(null, MATH, 'Mathematics')).toEqual({ kind: 'open' })
    expect(cardAction(null, MATH, null)).toEqual({ kind: 'hint' })
  })

  it('latestDiscOf：只认最近一份 single_trend 的 meta.disc；没有报告回 null', () => {
    expect(latestDiscOf({
      period: '202607', intents: [], reports: [{ intent: 'single_trend', title: '', meta: { disc: 'Engineering' } }],
      cur: null, disciplines: [], write: { enabled: false, available: false }, body_html: '',
    })).toBe('Engineering')
    expect(latestDiscOf(null)).toBe(null)
  })
})

/* ------------------------------------------------------------------ 点卡生成 */

describe('generateDisciplineReport（卡片 onClick 走的同一份代码，stream 整体 mock）', () => {
  it('点卡 → runFlexibleStream 收 single_trend＋学科；进度句 规划中…→第 N 节…→收尾…；done 后 window.open 开 report.html', async () => {
    const open = vi.fn()
    vi.stubGlobal('window', { open })
    emit([
      { event: 'status', stage: 'start' },
      { event: 'plan', intent: 'single_trend', title: '数学', backend: 'rule', mode: 'write',
        disc: 'Mathematics', outline: ['概况', '影响力'] },
      { event: 'section', title: '概况', html: '' },
      { event: 'section', title: '影响力', html: '' },
      { event: 'done', elapsed: 3, n_charts: 2, backend: 'rule', mode: 'write',
        title: '数学', check_pass: true, write: null },
    ])
    const stages: string[] = []
    let done = 0
    await generateDisciplineReport('202607', MATH, {
      onStage: (s) => stages.push(s),
      onDone: () => { done += 1 },
      onError: () => { throw new Error('不该走错误分支') },
      onInterrupted: () => { throw new Error('不该走中断分支') },
    })
    expect(runFlexibleStream).toHaveBeenCalledWith(
      '202607', { intent: 'single_trend', disc: 'Mathematics' }, expect.any(Function),
      { signal: expect.any(AbortSignal) })
    expect(stages).toEqual([STAGE_PLANNING, stageSection(1), stageSection(2), STAGE_TAIL])
    expect(done).toBe(1)
    expect(open).toHaveBeenCalledTimes(1)
    expect(open).toHaveBeenCalledWith('/p/202607/flexible/single_trend/report.html', '_blank', 'noopener')
  })

  it('流事件 error → 卡面一句（原话上卡），不开窗、不标完成', async () => {
    const open = vi.fn()
    vi.stubGlobal('window', { open })
    emit([{ event: 'error', message: '生成额度用完了' }])
    const errors: string[] = []
    let done = 0
    await generateDisciplineReport('202607', MATH, {
      onStage: () => {}, onDone: () => { done += 1 }, onError: (m) => errors.push(m),
      onInterrupted: () => { throw new Error('不该走中断分支') },
    })
    expect(errors).toEqual(['生成额度用完了'])
    expect(done).toBe(0)
    expect(open).not.toHaveBeenCalled()
  })

  it('请求就被拒（403 admin-only）→ errorNote 口径的一句，不开窗', async () => {
    const open = vi.fn()
    vi.stubGlobal('window', { open })
    vi.mocked(runFlexibleStream).mockImplementation(async () => {
      throw { status: 403, message: 'HTTP 403' }
    })
    const errors: string[] = []
    await generateDisciplineReport('202607', MATH, {
      onStage: () => {}, onDone: () => {}, onError: (m) => errors.push(m),
      onInterrupted: () => { throw new Error('不该走中断分支') },
    })
    expect(errors).toEqual(['生成学科报告需要管理员权限（用馆员账号登录后再来）。'])
    expect(open).not.toHaveBeenCalled()
  })
})

/* ------------------------------------------------------------------ 看门狗（票 2） */

describe('generateDisciplineReport 看门狗：无事件 90s 判连接中断', () => {
  /** 永不主动收束的流：事件再也不来（断链），只有 abort 才让 promise 落地。 */
  function silentStream() {
    vi.mocked(runFlexibleStream).mockImplementation(
      (_p, _b, _on, opts) => new Promise<void>((_, reject) => {
        const sig = opts!.signal!
        sig.addEventListener('abort', () => reject(new Error('AbortError')))
      }))
  }

  it('无事件 90s → 看门狗 abort fetch，卡面报中断（不是笼统失败），不标完成', async () => {
    vi.useFakeTimers()
    try {
      silentStream()
      const notes: string[] = []
      let done = 0
      const p = generateDisciplineReport('202607', MATH, {
        onStage: () => {}, onDone: () => { done += 1 },
        onError: (m) => notes.push(m), onInterrupted: () => notes.push(INTERRUPTED_NOTE),
      })
      await vi.advanceTimersByTimeAsync(WATCHDOG_MS)
      await p
      const call = vi.mocked(runFlexibleStream).mock.calls[0]
      expect((call[3] as { signal: AbortSignal }).signal.aborted).toBe(true)
      expect(notes).toEqual([INTERRUPTED_NOTE])
      expect(done).toBe(0)
    } finally { vi.useRealTimers() }
  })

  it('ping 重置看门狗：80s 一条 ping，90s 不断、170s（=80+90）才断；ping 不上进度', async () => {
    vi.useFakeTimers()
    try {
      vi.mocked(runFlexibleStream).mockImplementation(
        (_p, _b, onEvent, opts) => new Promise<void>((_, reject) => {
          setTimeout(() => onEvent({ event: 'ping' }), 80_000)
          const sig = opts!.signal!
          sig.addEventListener('abort', () => reject(new Error('AbortError')))
        }))
      const stages: string[] = []
      const notes: string[] = []
      const p = generateDisciplineReport('202607', MATH, {
        onStage: (s) => stages.push(s), onDone: () => {},
        onError: (m) => notes.push(m), onInterrupted: () => notes.push(INTERRUPTED_NOTE),
      })
      await vi.advanceTimersByTimeAsync(90_000)
      expect(notes).toEqual([])                    // ping 在 80s 把计时重置了
      await vi.advanceTimersByTimeAsync(80_000)    // 再走 80s（共 170s）才到新计时
      await p
      expect(notes).toEqual([INTERRUPTED_NOTE])
      expect(stages).toEqual([STAGE_PLANNING])     // 心跳不是进度：卡面仍是规划中
    } finally { vi.useRealTimers() }
  })

  it('流终止但没等到 done/error/stopped → 报中断，不开窗不标完成', async () => {
    const open = vi.fn()
    vi.stubGlobal('window', { open })
    emit([{ event: 'status', stage: 'start' }])    // 发完即收束，无终态事件
    const notes: string[] = []
    let done = 0
    await generateDisciplineReport('202607', MATH, {
      onStage: () => {}, onDone: () => { done += 1 },
      onError: (m) => notes.push(m), onInterrupted: () => notes.push(INTERRUPTED_NOTE),
    })
    expect(notes).toEqual([INTERRUPTED_NOTE])
    expect(done).toBe(0)
    expect(open).not.toHaveBeenCalled()
  })
})
