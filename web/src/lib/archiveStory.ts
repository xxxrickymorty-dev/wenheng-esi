/* 运行档案「这一期怎么做出来的」故事条（2026-10-20）。
   纯函数：把 archive + acquisition + approval 三个只读源翻成五步，不重算、不猜。
   评委在 10 分钟里不看日志表格，看这五步就够：取数 → 生成 → 审计 → 签发 → 留痕。 */

import type { AcquisitionState, ArchiveData } from '../api'

export type StoryState = 'ok' | 'warn' | 'todo'

export type StoryStep = {
  key: 'acquire' | 'generate' | 'audit' | 'sign' | 'trail'
  title: string
  value: string
  note: string
  state: StoryState
}

function auditCounts(d: ArchiveData) {
  const rows = d.audit.rows ?? []
  return {
    total: rows.length,
    pass: rows.filter((r) => r.status === 'pass').length,
    review: rows.filter((r) => r.status === 'review').length,
    fail: rows.filter((r) => r.status === 'fail').length,
  }
}

export function buildArchiveStory(
  d: ArchiveData,
  acq: AcquisitionState | null,
  approvalStatus: string,
): StoryStep[] {
  const verified = acq?.totals?.verified
  const expected = acq?.totals?.expected
  const merged = acq?.copy?.state === 'merged'
  const short = verified != null && expected != null && verified < expected
  const acquire: StoryStep = acq?.started
    ? {
        key: 'acquire',
        title: '取数',
        value: verified != null && expected != null ? `${verified} / ${expected} 件` : '有下载记录',
        note: !merged ? '下载完成，尚未并入'
          : short ? `已并入，缺 ${expected - verified} 件`
            : '已并入主台账',
        state: !merged || short ? 'warn' : 'ok',
      }
    : { key: 'acquire', title: '取数', value: '无下载留痕', note: '可能早于留痕上线', state: 'todo' }

  const retried = (d.replay.chain ?? []).some(
    (c) => c.from === 'retrying' || c.to === 'retrying' || c.to === 'escalated',
  )
  const elapsed = Math.round(Number(d.run_log?.elapsed_sec ?? d.waterfall_total ?? 0))
  const jobStatus = String(d.job?.status ?? '')
  const failed = /fail|error|escalat|cancel|abort/i.test(jobStatus)
  const hasSteps = (d.waterfall?.length ?? 0) > 0
  const hasRun = !!d.job_id || hasSteps || elapsed > 0
  let generate: StoryStep
  if (!hasRun) {
    generate = { key: 'generate', title: '生成', value: '无运行记录',
                 note: '这一期没有任务记录', state: 'todo' }
  } else if (d.progress_missing) {
    generate = { key: 'generate', title: '生成', value: `${elapsed} 秒`,
                 note: '运行记录缺失，无法回放步骤', state: 'warn' }
  } else if (failed) {
    generate = { key: 'generate', title: '生成', value: `${elapsed} 秒`,
                 note: `运行失败${jobStatus ? `（${jobStatus}）` : ''}`, state: 'warn' }
  } else if (!hasSteps) {
    generate = { key: 'generate', title: '生成', value: `${elapsed} 秒`,
                 note: '缺少任务步骤记录', state: 'warn' }
  } else {
    generate = { key: 'generate', title: '生成', value: `${elapsed} 秒`,
                 note: retried ? '含自愈 / 升级' : `${d.waterfall.length} 步 · 一次跑通`,
                 state: retried ? 'warn' : 'ok' }
  }

  const audit = auditCounts(d)
  const auditStep: StoryStep = d.audit.exists
    ? {
        key: 'audit',
        title: '审计',
        value: `${audit.pass} / ${audit.total} 通过`,
        note: `${audit.review} 待确认 · ${audit.fail} 不通过`,
        state: audit.fail || audit.review ? 'warn' : 'ok',
      }
    : { key: 'audit', title: '审计', value: '未执行', note: '没有审计记录', state: 'todo' }

  const sign: StoryStep =
    approvalStatus === 'signed'
      ? { key: 'sign', title: '签发', value: '已签发', note: '报告可下载', state: 'ok' }
      : approvalStatus === 'stale'
        ? { key: 'sign', title: '签发', value: '待重签', note: '内容改过，签名失效', state: 'warn' }
        : { key: 'sign', title: '签发', value: '未签发', note: '签单后才可下载', state: 'todo' }

  const files = d.logpack?.n_files ?? 0
  const trail: StoryStep = {
    key: 'trail',
    title: '留痕',
    value: `${files} 个文件`,
    note: files ? '可回放 · 检查 / 审计 / 产物' : '日志包未生成',
    state: files ? 'ok' : 'todo',
  }

  return [acquire, generate, auditStep, sign, trail]
}
