/* 自愈沙盘（2026-10-20，决赛「AI 在哪」证据页）。
   只读 tmp/_heal_sandbox/story.json：一眼看完「一处脏 → 拦停 → 自愈 → 重跑 → 原件未动」。
   不在这里跑流水线；重跑命令写在页脚，避免把演示变成不可控的长任务。 */

import { useEffect, useState } from 'react'
import { getHealSandbox, type HealSandboxStory } from './api'

type Step = { title: string; value: string; note: string; state: 'ok' | 'warn' | 'todo' }

function shortHash(h?: string) {
  return h ? `${h.slice(0, 16)}…` : '—'
}

export function HealSandbox() {
  const [d, setD] = useState<HealSandboxStory | null>(null)
  const [note, setNote] = useState('')

  useEffect(() => {
    getHealSandbox()
      .then(setD)
      .catch(() => setNote('沙盘故事卡读不到——先跑一次 tools/heal_sandbox.py。'))
  }, [])

  if (note) return <div className="pending-box mt-0">{note}</div>
  if (!d) return <div className="pending-box mt-0">正在读沙盘故事卡……</div>

  if (!d.available) {
    return (
      <>
        <p className="hint mt-2">自愈沙盘 · 只碰副本，不碰 input/ 原件</p>
        <section className="card pad-card-lg">
          <h1 className="fs-24">自愈沙盘</h1>
          <p className="fc-lead">还没跑过。先在终端执行一次，再刷新本页：</p>
          <p className="mono mt-10">uv run python tools\heal_sandbox.py</p>
          <p className="hint mt-10">{d.hint || '沙盘不在这里跑，避免把演示变成不可控的长任务。'}</p>
        </section>
      </>
    )
  }

  const steps: Step[] = [
    { title: '复制台账', value: '只读副本',
      note: `源：${d.ledger || '动态监测表'}；写入 tmp/_heal_sandbox/`, state: 'ok' },
    { title: '注入一处脏', value: `${d.old} → ${d.new}`,
      note: d.dirty_cell || '', state: 'warn' },
    { title: '首轮拦停', value: '断言未过',
      note: d.failure || '系统没有带病往下走', state: 'warn' },
    { title: '自愈', value: (d.rules || []).join(' / ') || '规则命中',
      note: d.outcome === 'repaired' ? '只改解析口径，不改断言' : (d.outcome || ''), state: 'ok' },
    { title: '重跑', value: (d.attempts || []).join(' → ') || '—',
      note: d.status === 'completed' ? '完成；原件与脏件都零字节改动' : (d.status || ''), state: d.ok ? 'ok' : 'warn' },
  ]

  return (
    <>
      <p className="hint mt-2">自愈沙盘 · 只碰副本，不碰 input/ 原件</p>

      <section className="card pad-card-lg">
        <h1 className="fs-24">自愈沙盘</h1>
        <p className="fc-lead">
          一处脏：<b className="mono">{d.dirty_cell}</b> 的 <b>{d.old}</b> 被改成 <b>{d.new}</b>。
          系统先拦停，再自己认出这是同一个学科，修解析口径后重跑通过。
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
        <h2 className="h-sec">哈希对账</h2>
        <div className="tablewrap mt-10">
          <table className="ar-tbl">
            <thead>
              <tr><th>文件</th><th>SHA-256</th><th>运行前后</th></tr>
            </thead>
            <tbody>
              <tr>
                <td><b>原件</b><br /><span className="hint">input/{d.ledger || '监测表.xlsx'}</span></td>
                <td className="mono">{shortHash(d.src_sha256)}</td>
                <td>{d.src_unchanged ? '不变' : '变了（异常）'}</td>
              </tr>
              <tr>
                <td><b>脏件</b><br /><span className="hint">tmp/_heal_sandbox/监测表_脏.xlsx</span></td>
                <td className="mono">{shortHash(d.dirty_sha256)}</td>
                <td>{d.dirty_unchanged ? '不变' : '变了（异常）'}</td>
              </tr>
            </tbody>
          </table>
        </div>
        <p className="hint mt-10">
          自愈改的是「怎么读」，不是台账本身——所以两份文件的哈希前后一致。
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
                <span className="heal-phase">{e.phase || '—'}</span>
                <b>{e.tool || e.decision || '—'}</b>
                <small>{e.observation || e.reason || ''}</small>
              </li>
            ))}
          </ol>
          <p className="hint mt-10">
            规划 → 执行 → 观察 → 决定 → 自愈 → 重试；每一步都进了 `agent_events.jsonl`，可回放。
          </p>
        </section>
      )}

      <p className="hint mt-16">
        重跑一次：<span className="mono">uv run python tools\heal_sandbox.py</span>，刷新本页即可。
      </p>
    </>
  )
}
