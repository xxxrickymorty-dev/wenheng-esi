/* 任务运行状态机的纯测试：SSE / 快照 / 断线重连 / 轮询 的迁移语义。
   ADR-0003：不引 jsdom；hook 只做事件源与定时器。 */

import { describe, expect, it } from 'vitest'
import {
  IDLE_STATE, JOB_SNAPSHOT_INTERVAL_MS, MAX_LOG_LINES, POLL_INTERVAL_MS, RECONNECT_DELAYS,
  humanProgress, latestProgress, logLine, reduce, restoredJobFor, statusData,
  type RunEffect, type RunEvent, type RunState,
} from './runMachine'

function play(events: RunEvent[], from: RunState = IDLE_STATE) {
  let state = from
  const effects: RunEffect[] = []
  for (const e of events) {
    const r = reduce(state, e)
    state = r.state
    effects.push(...r.effects)
  }
  return { state, effects }
}

const attach: RunEvent = { type: 'attach', jobId: 'j1', requestedPeriod: '202607' }
const okSnapshot: RunEvent = { type: 'snapshot', status: 'running', outPeriod: null, last: '取数：第 3 组' }

describe('进度行解析', () => {
  it('name+detail 拼人话；单字段原样；非 JSON 不丢信息', () => {
    expect(humanProgress('{"name":"解析","detail":"第 2 张表"}')).toBe('解析：第 2 张表')
    expect(humanProgress('{"name":"解析"}')).toBe('解析')
    expect(humanProgress('不是 JSON')).toBe('不是 JSON')
  })

  it('快照取最后一条进度，没有就 null', () => {
    expect(latestProgress({ events: [{ name: 'a' }, { detail: 'b' }] })).toBe('b')
    expect(latestProgress({ events: [] })).toBeNull()
    expect(latestProgress(null)).toBeNull()
  })

  it('log / status 行容错', () => {
    expect(logLine('{"line":"跑完了"}')).toBe('跑完了')
    expect(logLine('junk')).toBeNull()
    expect(statusData('{"status":"completed","out_period":"202607"}'))
      .toEqual({ status: 'completed', outPeriod: '202607' })
    expect(statusData('junk')).toBeNull()
  })
})

describe('恢复接受规则', () => {
  const job = { id: 'j1', period: '202607', out_period: '202607', status: 'running' }
  it('输出期 / 请求期 / 规范请求期 任一吻合即接受', () => {
    expect(restoredJobFor({ period: '202607' }, job, '202607')?.jobId).toBe('j1')
    expect(restoredJobFor({ period: '202607' }, { ...job, out_period: '202605' }, '202607')?.jobId).toBe('j1')
    expect(restoredJobFor(null, { id: 'j2', period: '202605' }, '202605')?.jobId).toBe('j2')
    expect(restoredJobFor({ period: '202607' }, { id: 'j3', period: '202605' }, '202607')).toBeNull()
  })
})

describe('运行状态机', () => {
  it('attach 种子态 + 首帧快照；首帧即使终态也先开流', () => {
    const { state, effects } = play([attach])
    expect(state.phase).toBe('snapshot')
    expect(state.run).toMatchObject({ jobId: 'j1', requestedPeriod: '202607', connection: 'snapshot' })
    expect(effects).toEqual([{ type: 'snapshot', delay: 0 }])

    const r = play([attach, { type: 'snapshot', status: 'completed', outPeriod: '202607' }])
    expect(r.state.phase).toBe('live')
    expect(r.effects.at(-1)).toEqual({ type: 'open', attempt: 0 })
    expect(r.effects.some((e) => e.type === 'terminal')).toBe(false)
  })

  it('opened 后进快照循环；live 快照续期，终态才停', () => {
    const r1 = play([attach, okSnapshot, { type: 'opened' }])
    expect(r1.effects.at(-1)).toEqual({ type: 'snapshot', delay: JOB_SNAPSHOT_INTERVAL_MS })
    const r2 = play([{ type: 'snapshot', status: 'running' }], r1.state)
    expect(r2.state.phase).toBe('live')
    expect(r2.effects).toEqual([{ type: 'snapshot', delay: JOB_SNAPSHOT_INTERVAL_MS }])
    const r3 = play([{ type: 'snapshot', status: 'completed', outPeriod: '202607' }], r2.state)
    expect(r3.effects.map((e) => e.type)).toEqual(['stop', 'terminal'])
    expect(r3.state.phase).toBe('done')
  })

  it('SSE status 终态只回调一次；之后事件全忽略', () => {
    const r1 = play([attach, okSnapshot, { type: 'opened' },
                     { type: 'sse-status', data: '{"status":"failed","out_period":"202607"}' }])
    expect(r1.effects.filter((e) => e.type === 'terminal')).toHaveLength(1)
    const r2 = play([{ type: 'sse-status', data: '{"status":"completed"}' },
                     { type: 'sse-progress', data: '{"name":"x"}' }], r1.state)
    expect(r2.effects).toEqual([])
    expect(r2.state.run?.status).toBe('failed')     // 不是 completed
  })

  it('进度与日志：日志环 80 行', () => {
    let s = play([attach, okSnapshot]).state
    s = play([{ type: 'sse-progress', data: '{"name":"解析","detail":"第 3 组"}' }], s).state
    expect(s.run?.last).toBe('解析：第 3 组')
    for (let i = 1; i <= 90; i++) {
      s = play([{ type: 'sse-log', data: JSON.stringify({ line: `l${i}` }) }], s).state
    }
    expect(s.run?.lines).toHaveLength(MAX_LOG_LINES)
    expect(s.run?.lines[0]).toBe('l11')
    expect(s.run?.lines.at(-1)).toBe('l90')
  })

  it('断线先快照；非终态按 800/1600/3200 重连，第四次转轮询', () => {
    let s = play([attach, okSnapshot, { type: 'opened' }]).state
    const delays: number[] = []
    const attempts: number[] = []
    for (let i = 0; i < 3; i++) {
      const d = play([{ type: 'disconnect' }], s)
      expect(d.effects).toEqual([{ type: 'snapshot', delay: 0 }])
      const r = play([{ type: 'snapshot', status: 'running' }], d.state)
      const rec = r.effects.find((e) => e.type === 'reconnect')
      expect(rec && rec.type === 'reconnect' && rec.attempt).toBe(i + 1)
      delays.push(rec && rec.type === 'reconnect' ? rec.delay : -1)
      attempts.push(r.state.attempt)
      expect(r.state.run?.lines).toEqual([])
      s = r.state
    }
    expect(delays).toEqual(RECONNECT_DELAYS)
    expect(attempts).toEqual([1, 2, 3])
    const d4 = play([{ type: 'disconnect' }], s)
    const p = play([{ type: 'snapshot', status: 'running' }], d4.state)
    expect(p.state.phase).toBe('polling')
    expect(p.effects).toEqual([{ type: 'poll', delay: POLL_INTERVAL_MS }])

    const p2 = play([{ type: 'snapshot', status: 'running' }], p.state)
    expect(p2.state.pollDelay).toBe(Math.round(POLL_INTERVAL_MS * 1.5))
    expect(p2.effects).toEqual([{ type: 'poll', delay: Math.round(POLL_INTERVAL_MS * 1.5) }])
    const p3 = play([{ type: 'snapshot', status: 'warned', outPeriod: '202607' }], p2.state)
    expect(p3.effects.map((e) => e.type)).toEqual(['stop', 'terminal'])
  })

  it('断线后的快照若已终态：直接收束，不重连', () => {
    const r0 = play([attach, okSnapshot, { type: 'opened' }, { type: 'disconnect' }])
    const r = play([{ type: 'snapshot', status: 'completed', outPeriod: '202607' }], r0.state)
    expect(r.effects.map((e) => e.type)).toEqual(['stop', 'terminal'])
    expect(r.state.phase).toBe('done')
  })

  it('detach 停一切并清空', () => {
    const r = play([attach, okSnapshot, { type: 'detach' }])
    expect(r.effects.at(-1)).toEqual({ type: 'stop' })
    expect(r.state.run).toBeNull()
    expect(r.state.phase).toBe('idle')
  })
})
