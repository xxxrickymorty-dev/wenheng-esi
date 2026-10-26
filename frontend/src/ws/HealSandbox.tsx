/* 自愈沙盘（2026-10-20，决赛「AI 在哪」证据页）。
   只读 tmp/_heal_sandbox/story.json：一眼看完「一处改坏 → 拦停 → 自愈 → 重跑 → 原件未动」。
   不在这里跑流水线；重跑命令写在页脚，避免把演示变成不可控的长任务。 */

import { useEffect, useState } from 'react'
import { getHealSandbox, type HealSandboxStory } from './api'

type Step = { title: string; value: string; note: string; state: 'ok' | 'warn' | 'todo' }

const RULE_LABEL: Record<string, string> = {
  discipline_alias_map: '学科别名规则',
}
const TOOL_LABEL: Record<string, string> = {
  parse_ledger: '读台账',
  run_parse: '解析台账',
  apply_repair_rule: '套用修复规则',
}
const PHASE_LABEL: Record<string, string> = {
  plan: '计划', act: '执行', observe: '观察', decide: '决定',
}
const DECISION_LABEL: Record<string, string> = {
  halt: '拦停', continue: '继续', retry: '重试', heal: '自愈',
  completed: '完成', failed: '失败',
}

/** 馆员看得懂的短句：技术词换成「检查 / 文件指纹」这类说法。 */
function plain(s?: string) {
  return (s || '')
    .replace(/断言/g, '检查')
    .replace(/sha256/gi, '文件指纹')
    .replace(/哈希/g, '文件指纹')
}

function shortHash(h?: string) {
  return h ? `${h.slice(0, 16)}…` : '—'
}

export function HealSandbox() {
  const [d, setD] = useState<HealSandboxStory | null>(null)
  const [note, setNote] = useState('')

  useEffect(() => {
    getHealSandbox()
      .then(setD)
      .catch(() => setNote('沙盘故事卡读不到——先跑一次自愈沙盘工具，再刷新本页。'))
  }, [])

  if (note) return <div className="pending-box mt-0">{note}</div>
  if (!d) return <div className="pending-box mt-0">正在读沙盘故事卡……</div>

  if (!d.available) {
    return (
      <>
        <p className="hint mt-2">自愈沙盘 · 只碰副本，不碰原始台账</p>
        <section className="card pad-card-lg">
          <h1 className="fs-24">自愈沙盘</h1>
          <p className="fc-lead">还没跑过。先在终端执行一次，再刷新本页：</p>
          <p className="mono mt-10">uv run python tools\heal_sandbox.py</p>
          <p className="hint mt-10">{d.hint || '沙盘不在这里跑，避免把演示变成不可控的长任务。'}</p>
        </section>
      </>
    )
  }

  const ruleText = (d.rules || []).map((r) => RULE_LABEL[r] ?? '读表口径').join(' / ') || '读表口径'
  const steps: Step[] = [
    { title: '复制台账', value: '只读副本',
      note: `源：${d.ledger || '动态监测表'}；副本放在临时目录`, state: 'ok' },
    { title: '改坏一处', value: `${d.old} → ${d.new}`,
      note: d.dirty_cell ? `位置：${d.dirty_cell}` : '', state: 'warn' },
    { title: '首轮拦停', value: '检查未过',
      note: plain(d.failure) || '系统先拦停，没有带病往下走', state: 'warn' },
    { title: '自愈', value: ruleText,
      note: d.outcome === 'repaired' ? '只改读表口径，不改检查标准' : '已按规则修正', state: 'ok' },
    { title: '重跑', value: (d.attempts || []).join(' → ') || '—',
      note: d.status === 'completed' ? '完成；原始台账与改坏的副本都没有被改过' : '未完成；见下', state: d.ok ? 'ok' : 'warn' },
  ]

  return (
    <>
      <p className="hint mt-2">自愈沙盘 · 只碰副本，不碰原始台账</p>

      <section className="card pad-card-lg">
        <h1 className="fs-24">自愈沙盘</h1>
        <p className="fc-lead">
          一处故意改坏：<b className="mono">{d.dirty_cell}</b> 的 <b>{d.old}</b> 被改成 <b>{d.new}</b>。
          系统先拦停，再自己认出这是同一个学科，改读表口径后重跑通过。
        </p>
        <div className="rowc mt-14">
          <span className={`pill ${d.ok ? 'signed' : 'stale'}`}>
            {d.ok ? '一次自愈成功' : '未按预期完成'}
          </span>
          <span className="hint">生成于 {d.generated_at || '—'}</span>
        </div>
      </section>

      <section className="ar-story" aria-label="自愈五步">
        {steps.map((s) => (
          <div className={`ar-story-step ${s.state}`} key={s.title}>
            <span className="ar-story-k">{s.title}</span>
            <b>{s.value}</b>
            <small>{s.note}</small>
          </div>
        ))}
      </section>

      <section className="card mt-18 pad-card">
        <h2 className="h-sec">文件指纹对账</h2>
        <div className="tablewrap mt-10">
          <table className="ar-tbl">
            <thead>
              <tr><th>文件</th><th>文件指纹</th><th>运行前后</th></tr>
            </thead>
            <tbody>
              <tr>
                <td><b>原始台账</b><br /><span className="hint">{d.ledger || '监测表.xlsx'}</span></td>
                <td className="mono">{shortHash(d.src_sha256)}</td>
                <td>{d.src_unchanged ? '不变' : '变了（异常）'}</td>
              </tr>
              <tr>
                <td><b>改坏的副本</b><br /><span className="hint">沙盘副本</span></td>
                <td className="mono">{shortHash(d.dirty_sha256)}</td>
                <td>{d.dirty_unchanged ? '不变' : '变了（异常）'}</td>
              </tr>
            </tbody>
          </table>
        </div>
        <p className="hint mt-10">
          自愈改的是「怎么读」，不是台账本身——所以两份文件的内容前后一致。
        </p>
      </section>

      {!!d.events?.length && (
        <section className="card mt-18 pad-card">
          <h2 className="h-sec">
            决策轨迹
            <span className="hint">{d.events.length} 条</span>
          </h2>
          <ol className="heal-trace">
            {d.events.map((e, i) => (
              <li key={i} className={e.decision === 'halt' ? 'warn' : e.decision === 'completed' ? 'ok' : ''}>
                <span className="heal-phase">{PHASE_LABEL[String(e.phase || '').toLowerCase()] ?? '动作'}</span>
                <b>{e.tool ? (TOOL_LABEL[e.tool] ?? '系统动作')
                  : (DECISION_LABEL[String(e.decision || '')] ?? '—')}</b>
                <small>{plain(e.observation || e.reason)}</small>
              </li>
            ))}
          </ol>
          <p className="hint mt-10">
            计划 → 执行 → 观察 → 决定 → 自愈 → 重试；每一步都留了操作记录，可回放。
          </p>
        </section>
      )}

      <p className="hint mt-16">
        重跑一次：<span className="mono">uv run python tools\heal_sandbox.py</span>，刷新本页即可。
      </p>
    </>
  )
}
