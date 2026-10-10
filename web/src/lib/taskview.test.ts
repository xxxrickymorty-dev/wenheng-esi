/* 票 06 · 空态第一屏：三步状态 → 显示文案（S3 纯函数）。
   状态由后端从既有产物判（GET /api/dialog/home）；这里只把状态翻成馆员话术与主按钮。
   卡在哪＝第一个没做完的那步（都做完但没签发＝卡在签单）。 */
import { describe, expect, it } from 'vitest'
import { taskView, type DialogHome } from './taskview'

const home = (over: Partial<DialogHome> = {}): DialogHome => ({
  period: '202607',
  released: true,
  n_missing: 1,
  steps: [
    { key: 'acquire', done: false },
    { key: 'merge', done: false },
    { key: 'generate', done: false },
  ],
  stuck: 'acquire',
  prev: null,
  ...over,
})

describe('本期任务视图（票 06）', () => {
  it('空数据不显示（返回 null，界面退回普通问候）', () => {
    expect(taskView(null)).toBeNull()
    expect(taskView(home({ period: '' }))).toBeNull()
  })

  it('卡在取数（没并入）：数据未到 / 缺 N 件两种说法', () => {
    const notYet = taskView(home({ released: false, n_missing: 4 }))
    expect(notYet?.rows.map((r) => r.mark)).toEqual(['●', '○', '○'])
    expect(notYet?.rows[0].note).toBe('数据未到（随发布）')
    expect(notYet?.cta).toEqual({ label: '去取数台 ▸', kind: 'goto', view: 'acquire' })

    const missing = taskView(home({ released: true, n_missing: 2 }))
    expect(missing?.rows[0].note).toBe('还缺 2 件')
  })

  it('卡在核对：① ✓ ② ● ③ ○，主按钮去核对（同一张核对页）', () => {
    const tv = taskView(home({ stuck: 'merge',
      steps: [{ key: 'acquire', done: true }, { key: 'merge', done: false },
              { key: 'generate', done: false }] }))
    expect(tv?.rows.map((r) => r.mark)).toEqual(['✓', '●', '○'])
    expect(tv?.rows[1].note).toBe('卡在这')
    expect(tv?.cta).toEqual({ label: '去核对 ▸', kind: 'goto', view: 'acquire' })
  })

  it('卡在一键生成：主按钮是「一键生成」（在前门里当场出稿）', () => {
    const tv = taskView(home({ stuck: 'generate',
      steps: [{ key: 'acquire', done: true }, { key: 'merge', done: true },
              { key: 'generate', done: false }] }))
    expect(tv?.rows.map((r) => r.mark)).toEqual(['✓', '✓', '●'])
    expect(tv?.cta).toEqual({ label: '一键生成 ▸', kind: 'gen' })
  })

  it('三步全成未签发：卡在签单，第三行说「已出好 · 待签单」', () => {
    const tv = taskView(home({ stuck: 'sign', period: '202609',
      steps: [{ key: 'acquire', done: true }, { key: 'merge', done: true },
              { key: 'generate', done: true }] }))
    expect(tv?.rows.map((r) => r.mark)).toEqual(['✓', '✓', '✓'])
    expect(tv?.rows[2].note).toBe('已出好 · 待签单')
    expect(tv?.cta).toEqual({ label: '去审核台签单 ▸', kind: 'goto', view: 'review' })
  })

  it('标题带本期期次；上一期签发状态如实说（三种状态都有说法）', () => {
    const tv = taskView(home({ period: '202611', prev: { period: '202609', status: 'signed' } }))
    expect(tv?.title).toBe('本期任务 · 202611')
    expect(tv?.prevNote).toBe('上一期 202609：已签单')
    const tv2 = taskView(home({ prev: { period: '202609', status: 'stale' } }))
    expect(tv2?.prevNote).toBe('上一期 202609：签名已失效')
    const tv3 = taskView(home({ prev: { period: '202609', status: 'unsigned' } }))
    expect(tv3?.prevNote).toBe('上一期 202609：待签单')
    const tv4 = taskView(home({ prev: null }))
    expect(tv4?.prevNote).toBe('')
  })
})
