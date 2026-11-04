/* 跨校单学科对比区测试（无 jsdom——与全站同口径，照 DisciplineSection.test.tsx 的缝）：
   - CompareView 静态渲染：学校行 / 「无数据」徽标只在 in_field=false 时出现
     （字段缺省不误标）/ 至少勾 2 所的门槛与提示 / 已选 chips / 生成中进度表三态 /
     成稿缩略书脊 / 空稿位 / 「打开报告」条件链；
   - sectionStates（进度推演纯逻辑）；
   - runCompare（生成按钮走的同一份控制器，api-flexible 整体 mock）：
     status/plan/section/done 逐事件回传，stopped/error 各上一句，
     请求就被拒（403）给 errorNote 口径的一句；
   - 看门狗：无事件 90s → abort＋中断提示；ping 重置计时；流终止无终态事件 → 中断提示。 */

import { afterEach, describe, expect, it, vi } from 'vitest'
import { renderToStaticMarkup } from 'react-dom/server'

vi.mock('../api-flexible', () => ({
  getFlexible: vi.fn(),
  runFlexibleStream: vi.fn(),
  stopFlexible: vi.fn(),
}))
vi.mock('../api-monitor', () => ({
  getMonitorSchools: vi.fn(),
}))

import {
  CompareView, compareReportUrl, MIN_PEERS, runCompare, sectionStates,
  STOPPED_NOTE,
} from './CompareSection'
import { runFlexibleStream, type FlexStreamEvent } from '../api-flexible'
import type { MonitorSchool } from '../api-monitor'

/* ------------------------------------------------------------------ 桩 */

function school(cn: string, in_field?: boolean): MonitorSchool {
  return { cn, en: cn, prov: '', is985: false, known: true,
           generated: false, url: null, ...(in_field === undefined ? {} : { in_field }) }
}

const SCHOOLS: MonitorSchool[] = [
  school('云南大学', true), school('贵州大学', true), school('广西大学'),
  school('昆明理工大学', false), school('上海财经大学', false),
]

const DISCIPLINES = [
  { en: 'Plant & Animal Science', cn: '植物与动物学' },
  { en: 'Chemistry', cn: '化学' },
]

function view(over: Partial<Parameters<typeof CompareView>[0]> = {}): string {
  return renderToStaticMarkup(
    <CompareView period="202607" disciplines={DISCIPLINES} disc="Chemistry"
                 onDisc={() => {}} schools={SCHOOLS} schoolsErr=""
                 picked={[]} onToggle={() => {}} stream={null} onStop={() => {}}
                 draft={null} hasReport={false} note={null}
                 onGenerate={() => {}} {...over} />)
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

describe('CompareView：选校抽屉', () => {
  it('名单 5 项 → 5 行；行名衬线；勾选状态照 picked', () => {
    const html = view({ picked: ['云南大学', '上海财经大学'] })
    expect((html.match(/class="cp-srow[^"]*"/g) ?? []).length).toBe(5)
    expect(html).toContain('贵州大学')
    expect((html.match(/checked=""/g) ?? []).length).toBe(2)
    expect(html).toContain('已选 <b>2</b> 所')
  })

  it('「无数据」徽标只在 in_field=false 那行出现；字段缺省的不标（不误标）', () => {
    const html = view()
    /* 昆明理工 + 上海财经：徽标、行样式一一对应；
       云南/贵州（in_field=true）与广西（字段缺省）都不标 */
    expect((html.match(/cp-badge/g) ?? []).length).toBe(2)
    expect((html.match(/cp-srow nodata/g) ?? []).length).toBe(2)
    expect(html).toContain('无数据')
  })

  it('名单还没读到（schools=null）：不闪错误也不闪名单，画读取占位', () => {
    const html = view({ schools: null })
    expect(html).not.toContain('cp-srow')
    expect(html).toContain('正在读学校名单')
  })

  it('名单没读到且无旧名单：一句错误（勾选不受影响的降级口径），不显示徽标', () => {
    const html = view({ schools: null, schoolsErr: '读取学校名单失败。' })
    expect(html).toContain('读取学校名单失败。')
    expect(html).not.toContain('cp-badge')
  })

  it('门槛：少于 2 所按钮禁用＋「至少勾 2 所」；够了启用、提示退场', () => {
    const short = view({ picked: ['云南大学'] })
    expect(short).toContain('disabled')
    expect(short).toContain('至少勾 2 所')
    const ok = view({ picked: ['云南大学', '贵州大学', '广西大学'] })
    expect(ok).not.toContain('至少勾 2 所')
    expect(ok).not.toContain('disabled')
  })

  it('已选 chips：一所一颗，点一下移除（aria-label）；无数据校虚线边', () => {
    const html = view({ picked: ['贵州大学', '上海财经大学'] })
    /* class="cp-chip …" 精确数（cp-chips 容器名是它的超串，裸数会多算一颗） */
    expect((html.match(/class="cp-chip[ "]/g) ?? []).length).toBe(2)
    expect(html).toContain('aria-label="移除 贵州大学"')
    expect(html).toContain('cp-chip nodata')
  })

  it('错误/权限提示上一句（note），不遮抽屉', () => {
    const html = view({ note: '生成请找管理员' })
    expect(html).toContain('生成请找管理员')
  })

  it('学科下拉：名单里几项就几项，value 是英文名；生成中禁用换学科', () => {
    const html = view()
    expect(html).toContain('植物与动物学')
    expect(html).toContain('value="Plant &amp; Animal Science"')
    const busy = view({ stream: { title: '', outline: [], sections: [] } })
    expect(busy).toContain('disabled')
  })

  it('最近稿还在：区头「打开报告」链到公开读路由', () => {
    const off = view()
    expect(off).not.toContain('打开报告')
    const on = view({ hasReport: true })
    expect(on).toContain('打开报告')
    expect(on).toContain(`href="${compareReportUrl('202607')}"`)
  })
})

describe('CompareView：生成中与成稿', () => {
  it('生成中：抽屉换「正在生成」＋进度实时更新；进度表三态照节数推演', () => {
    /* 三节写了 1 节：一节已完成、一节进行中、一节未开始——三态同屏 */
    const html = view({ stream: { title: '植物与动物学跨校对比',
      outline: ['本期规划', '对比总览', '指标对比'], sections: [
        { title: '本期规划', html: '' }] } })
    expect(html).toContain('正在生成')
    expect(html).toContain('进度实时更新')
    expect(html).not.toContain('cp-srow')
    expect(html).toContain('已完成')
    expect(html).toContain('进行中')
    expect(html).toContain('未开始')
    expect(html).toContain('停止')
    expect(html).not.toContain('生成分析稿')
  })

  it('规划中（outline 未到）：状态行在稿位，稿位不空着', () => {
    const html = view({ stream: { title: '', outline: [], sections: [] } })
    expect(html).toContain('正在规划这个题怎么拆')
  })

  it('流式节：节题＋正文逐节摆进稿位', () => {
    const html = view({ stream: { title: '', outline: ['对比总览'],
      sections: [{ title: '对比总览', html: '<p>榜内 2,103 家</p>' }] } })
    expect(html).toContain('fx-sec-h')
    expect(html).toContain('榜内 2,103 家')
  })

  it('成稿缩略：书脊竖排题名＋期次，正文在稿位', () => {
    const html = view({ draft: { title: '植物与动物学跨校对比', html: '<p>贵州大学全球第 194 位</p>' } })
    expect(html).toContain('cp-report')
    expect(html).toContain('cp-spine')
    expect(html).toContain('植物与动物学跨校对比')
    expect(html).toContain('cp-vp')
    expect(html).toContain('贵州大学全球第 194 位')
  })

  it('「规则稿」小标（2026-11-04 票 1）：draft.backend=rule 才标；缺省/模型稿不标（不误标）', () => {
    const tagged = view({ draft: { title: 't', html: '', backend: 'rule' } })
    expect(tagged).toContain('rule-tag')
    expect(tagged).toContain('规则稿')
    expect(view({ draft: { title: 't', html: '' } })).not.toContain('rule-tag')
    expect(view({ draft: { title: 't', html: '', backend: 'deepseek-chat' } }))
      .not.toContain('rule-tag')
  })

  it('空稿位：一句话＋下一步（勾选对比学校），不只有解释', () => {
    const html = view({ schools: [] })
    expect(html).toContain('勾选对比学校')
    expect(html).toContain('生成后稿在此预览')
  })
})

/* ------------------------------------------------------------------ 纯逻辑 */

describe('sectionStates：进度推演', () => {
  it('写完的节「已完成」、正写的那节「进行中」、后面「未开始」；规划刚出（0 节）第一节即进行中', () => {
    expect(sectionStates(['一', '二', '三'], 1)).toEqual(['done', 'run', 'idle'])
    expect(sectionStates(['一', '二', '三'], 0)).toEqual(['run', 'idle', 'idle'])
    expect(sectionStates(['一', '二', '三'], 3)).toEqual(['done', 'done', 'done'])
    expect(sectionStates([], 0)).toEqual([])
  })

  it('MIN_PEERS：至少勾 2 所', () => {
    expect(MIN_PEERS).toBe(2)
  })
})

/* ------------------------------------------------------------------ 控制器 */

describe('runCompare（生成按钮走的同一份代码，stream 整体 mock）', () => {
  it('status/plan/section/done 逐事件回传；流口收 school_compare＋学科＋勾选名单', async () => {
    emit([
      { event: 'status', stage: 'start', run: 'r-1' },
      { event: 'plan', intent: 'school_compare', title: '植物与动物学跨校对比',
        backend: 'rule', mode: 'write', disc: 'Plant & Animal Science',
        outline: ['对比总览', '指标对比'] },
      { event: 'section', title: '对比总览', html: '' },
      { event: 'done', elapsed: 5, n_charts: 3, backend: 'rule', mode: 'write',
        title: '植物与动物学跨校对比', check_pass: true, write: null },
    ])
    const got: string[] = []
    let planned: [string, string[]] | null = null
    let done = 0
    await runCompare('202607', 'Plant & Animal Science', ['云南大学', '贵州大学'], {
      onRun: (r) => got.push(`run:${r}`),
      onPlan: (t, o) => { planned = [t, o] },
      onSection: (t) => got.push(`sec:${t}`),
      onDone: () => { done += 1 },
      onError: () => { throw new Error('不该走错误分支') },
      onInterrupted: () => { throw new Error('不该走中断分支') },
    })
    expect(vi.mocked(runFlexibleStream)).toHaveBeenCalledWith(
      '202607',
      { intent: 'school_compare', disc: 'Plant & Animal Science',
        peers: ['云南大学', '贵州大学'] },
      expect.any(Function),
      { signal: expect.any(AbortSignal) })
    expect(got).toEqual(['run:r-1', 'sec:对比总览'])
    expect(planned).toEqual(['植物与动物学跨校对比', ['对比总览', '指标对比']])
    expect(done).toBe(1)
  })

  it('done 的 backend 原样回传（「规则稿」小标用它）；事件缺字段回空串', async () => {
    emit([{ event: 'done', elapsed: 1, n_charts: 0, backend: 'rule', mode: 'write',
            title: 't', check_pass: true, write: null }])
    let got = ''
    await runCompare('202607', 'Chemistry', ['云南大学', '贵州大学'], {
      onRun: () => {}, onPlan: () => {}, onSection: () => {},
      onDone: (b) => { got = b }, onError: () => {}, onInterrupted: () => {},
    })
    expect(got).toBe('rule')
    emit([{ event: 'status', stage: 'start', run: 'r-2' },
          // 事件缺 backend 字段（类型上有，运行时防一手）：控制器回空串
          { event: 'done', elapsed: 1, n_charts: 0, mode: 'write',
            title: 't', check_pass: true, write: null } as FlexStreamEvent])
    let bare = 'x'
    await runCompare('202607', 'Chemistry', ['云南大学', '贵州大学'], {
      onRun: () => {}, onPlan: () => {}, onSection: () => {},
      onDone: (b) => { bare = b }, onError: () => {}, onInterrupted: () => {},
    })
    expect(bare).toBe('')
  })

  it('流事件 error → 原话上屏一句，不标完成', async () => {    emit([{ event: 'error', message: '对比学科的机构表还没取到' }])
    const errors: string[] = []
    let done = 0
    await runCompare('202607', 'Chemistry', ['云南大学', '贵州大学'], {
      onRun: () => {}, onPlan: () => {}, onSection: () => {},
      onDone: () => { done += 1 }, onError: (m) => errors.push(m),
      onInterrupted: () => { throw new Error('不该走中断分支') },
    })
    expect(errors).toEqual(['对比学科的机构表还没取到'])
    expect(done).toBe(0)
  })

  it('stopped（停止键喊停后的终态）→「停了——这次没出稿。」', async () => {
    emit([{ event: 'stopped' }])
    const errors: string[] = []
    await runCompare('202607', 'Chemistry', ['云南大学', '贵州大学'], {
      onRun: () => {}, onPlan: () => {}, onSection: () => {},
      onDone: () => {}, onError: (m) => errors.push(m),
      onInterrupted: () => { throw new Error('不该走中断分支') },
    })
    expect(errors).toEqual([STOPPED_NOTE])
  })

  it('请求就被拒（403 admin-only）→ errorNote 口径的一句', async () => {
    vi.mocked(runFlexibleStream).mockImplementation(async () => {
      throw { status: 403, message: 'HTTP 403' }
    })
    const errors: string[] = []
    await runCompare('202607', 'Chemistry', ['云南大学', '贵州大学'], {
      onRun: () => {}, onPlan: () => {}, onSection: () => {},
      onDone: () => {}, onError: (m) => errors.push(m),
      onInterrupted: () => { throw new Error('不该走中断分支') },
    })
    expect(errors).toEqual(['生成跨校对比稿需要管理员权限（用馆员账号登录后再来）。'])
  })
})

/* ------------------------------------------------------------------ 看门狗 */

describe('runCompare 看门狗：无事件 90s 判连接中断', () => {
  /** 永不主动收束的流：事件再也不来（断链），只有 abort 才让 promise 落地。 */
  function silentStream() {
    vi.mocked(runFlexibleStream).mockImplementation(
      (_p, _b, _on, opts) => new Promise<void>((_, reject) => {
        const sig = opts!.signal!
        sig.addEventListener('abort', () => reject(new Error('AbortError')))
      }))
  }

  it('无事件 90s → 看门狗 abort fetch，报中断（不是笼统失败），不标完成', async () => {
    vi.useFakeTimers()
    try {
      silentStream()
      const notes: string[] = []
      let done = 0
      const p = runCompare('202607', 'Chemistry', ['云南大学', '贵州大学'], {
        onRun: () => {}, onPlan: () => {}, onSection: () => {},
        onDone: () => { done += 1 }, onError: (m) => notes.push(m),
        onInterrupted: () => notes.push('连接中断'),
      })
      await vi.advanceTimersByTimeAsync(90_000)
      await p
      const call = vi.mocked(runFlexibleStream).mock.calls[0]
      expect((call[3] as { signal: AbortSignal }).signal.aborted).toBe(true)
      expect(notes).toEqual(['连接中断'])
      expect(done).toBe(0)
    } finally { vi.useRealTimers() }
  })

  it('ping 重置看门狗：80s 一条 ping，90s 不断、170s（=80+90）才断；ping 不是进度', async () => {
    vi.useFakeTimers()
    try {
      vi.mocked(runFlexibleStream).mockImplementation(
        (_p, _b, onEvent, opts) => new Promise<void>((_, reject) => {
          setTimeout(() => onEvent({ event: 'ping' }), 80_000)
          const sig = opts!.signal!
          sig.addEventListener('abort', () => reject(new Error('AbortError')))
        }))
      const plans: string[] = []
      const notes: string[] = []
      const p = runCompare('202607', 'Chemistry', ['云南大学', '贵州大学'], {
        onRun: () => {}, onPlan: (t) => plans.push(t), onSection: () => {},
        onDone: () => {}, onError: (m) => notes.push(m),
        onInterrupted: () => notes.push('连接中断'),
      })
      await vi.advanceTimersByTimeAsync(90_000)
      expect(notes).toEqual([])                    // ping 在 80s 把计时重置了
      await vi.advanceTimersByTimeAsync(80_000)    // 再走 80s（共 170s）才到新计时
      await p
      expect(notes).toEqual(['连接中断'])
      expect(plans).toEqual([])                    // 心跳不是进度：规划还没来就是没来
    } finally { vi.useRealTimers() }
  })

  it('流终止但没等到 done/error/stopped → 报中断，不标完成', async () => {
    emit([{ event: 'status', stage: 'start' }])    // 发完即收束，无终态事件
    const notes: string[] = []
    let done = 0
    await runCompare('202607', 'Chemistry', ['云南大学', '贵州大学'], {
      onRun: () => {}, onPlan: () => {}, onSection: () => {},
      onDone: () => { done += 1 }, onError: (m) => notes.push(m),
      onInterrupted: () => notes.push('连接中断'),
    })
    expect(notes).toEqual(['连接中断'])
    expect(done).toBe(0)
  })
})
