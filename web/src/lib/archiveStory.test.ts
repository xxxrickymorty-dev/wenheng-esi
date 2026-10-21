import { describe, expect, it } from 'vitest'
import type { AcquisitionState, ArchiveData } from '../api'
import { buildArchiveStory } from './archiveStory'

const step = (name: string, sec: number) => ({
  step: name, name, status: 'done', detail: '', sec, at: '', orphan: false,
})

const archive = (over: Partial<ArchiveData> = {}): ArchiveData => ({
  period: '202609',
  job: { status: 'completed' },
  job_id: 'job-1',
  stats: {},
  run_log: { elapsed_sec: 270 },
  waterfall: [step('parse', 9), step('charts', 261)],
  waterfall_total: 270,
  progress_missing: false,
  replay: { chain: [], synthetic: false, note: '', n: 0 },
  audit: {
    exists: true,
    verdict: 'review',
    verdict_label: '待人工确认',
    rows: [
      { id: '1', title: '大表', status: 'pass', metric: '242/242', reason: '' },
      { id: '2', title: '抽查', status: 'pass', metric: '72/716', reason: '' },
      { id: '3', title: '金样', status: 'review', metric: '待人工', reason: '' },
    ],
    generated_at: '2026-10-17T14:14:42',
    truth_chain: '',
    elapsed_s: 3,
  },
  env: {},
  artifacts: [],
  logpack: { key: 'logpack', n_files: 13, bytes: 153000 },
  logpack_url: '/p/202609/download/logpack',
  download_base: '/p/202609',
  trace_files: [],
  ...over,
} as ArchiveData)

const acq = (over: Partial<AcquisitionState> = {}): AcquisitionState => ({
  period: '202609',
  started: true,
  totals: { expected: 64, verified: 64 },
  copy: { state: 'merged' },
  ...over,
} as AcquisitionState)

describe('运行档案故事条', () => {
  it('五步齐全：取数 → 生成 → 审计 → 签发 → 留痕', () => {
    const story = buildArchiveStory(archive(), acq(), 'signed')
    expect(story.map((s) => s.key)).toEqual(['acquire', 'generate', 'audit', 'sign', 'trail'])
    expect(story[0].value).toBe('64 / 64 件')
    expect(story[0].note).toBe('已并入主台账')
    expect(story[1].value).toBe('270 秒')
    expect(story[1].note).toBe('2 步 · 一次跑通')
    expect(story[2].value).toBe('2 / 3 通过')
    expect(story[3].value).toBe('已签发')
    expect(story[4].value).toBe('13 个文件')
    expect(story.map((s) => s.state)).toEqual(['ok', 'ok', 'warn', 'ok', 'ok'])
  })

  it('自愈/升级与失败审计如实说', () => {
    const story = buildArchiveStory(
      archive({
        replay: { chain: [{ from: 'running', to: 'retrying', trigger: '断言', ts: '' }], synthetic: false, note: '', n: 1 },
        audit: {
          exists: true, verdict: 'fail', verdict_label: '不通过',
          rows: [{ id: '1', title: '大表', status: 'fail', metric: '1 格不符', reason: '' }],
          generated_at: '', truth_chain: '', elapsed_s: 1,
        },
      }),
      acq({ totals: { expected: 64, verified: 63 } }),
      'stale',
    )
    expect(story[0].state).toBe('warn')
    expect(story[1].note).toBe('含自愈 / 升级')
    expect(story[2].state).toBe('warn')
    expect(story[2].note).toBe('0 待确认 · 1 不通过')
    expect(story[3].value).toBe('待重签')
  })

  it('没有任务记录：生成说「无运行记录」，不说 0 秒/一次跑通', () => {
    const story = buildArchiveStory(
      archive({ job: {}, job_id: '', run_log: {}, waterfall: [], waterfall_total: 0 }),
      acq(), 'unsigned',
    )
    expect(story[1]).toMatchObject({ value: '无运行记录', state: 'todo' })
  })

  it('运行失败/记录缺失：生成说失败或缺失，不冒充一次跑通', () => {
    const failed = buildArchiveStory(
      archive({ job: { status: 'failed' }, replay: {
        chain: [{ from: 'running', to: 'failed', trigger: 'err', ts: '' }],
        synthetic: true, note: '', n: 1,
      } }), acq(), 'unsigned')
    expect(failed[1].state).toBe('warn')
    expect(failed[1].note).toContain('运行失败')

    const missing = buildArchiveStory(archive({ progress_missing: true }), acq(), 'unsigned')
    expect(missing[1].state).toBe('warn')
    expect(missing[1].note).toContain('缺失')
  })

  it('下载完但未并入：取数标「尚未并入」，不标绿', () => {
    const story = buildArchiveStory(archive(), acq({ copy: { state: 'downloaded' } }), 'unsigned')
    expect(story[0].state).toBe('warn')
    expect(story[0].note).toBe('下载完成，尚未并入')
  })

  it('没有取数/审计记录时退回「待办」，不编', () => {
    const story = buildArchiveStory(
      archive({
        audit: { exists: false, verdict: '', verdict_label: '', rows: [], generated_at: '', truth_chain: '', elapsed_s: 0 },
        logpack: { key: '', n_files: 0, bytes: 0 },
      }),
      null,
      'unsigned',
    )
    expect(story[0]).toMatchObject({ value: '无下载留痕', state: 'todo' })
    expect(story[2]).toMatchObject({ value: '未执行', state: 'todo' })
    expect(story[3]).toMatchObject({ value: '未签发', state: 'todo' })
    expect(story[4]).toMatchObject({ value: '0 个文件', state: 'todo' })
  })
})
