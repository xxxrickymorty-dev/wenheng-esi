/* 换馆沙盘（2026-10-20，决赛推广证据）。
   只读 tmp/_migration_sandbox/readiness.json：把「换馆=换配置包」拆成 5 项可核验的结构检查。
   不在这里跑流水线；真实换馆要换的四件事写在页脚上方。 */

import { useEffect, useState } from 'react'
import { getMigrateSandbox, type MigrateStory } from './api'

const FOUR = [
  { t: '台账模板', d: '按 12 张工作表 + 22 个规范学科名的固定结构维护；换校不换表结构。' },
  { t: '学科清单', d: '22 个学科的中英文名与顺序；别名表按新校口径补。' },
  { t: '数据源', d: 'ESI / InCites 的导出目录与账号；换馆只换源，不改引擎。' },
  { t: '母版封面', d: '报告母版里的校名、期号、封面图；结构母版不动。' },
]

export function MigrateSandbox() {
  const [d, setD] = useState<MigrateStory | null>(null)
  const [note, setNote] = useState('')

  useEffect(() => {
    getMigrateSandbox()
      .then(setD)
      .catch(() => setNote('换馆故事卡读不到——先跑一次换馆沙盘工具，再刷新本页。'))
  }, [])

  if (note) return <div className="pending-box mt-0">{note}</div>
  if (!d) return <div className="pending-box mt-0">正在读换馆故事卡……</div>

  if (!d.available) {
    return (
      <>
        <p className="hint mt-2">换馆沙盘 · 只碰台账副本，不碰 input/ 原件</p>
        <section className="card pad-card-lg">
          <h1 className="fs-24">换馆沙盘</h1>
          <p className="fc-lead">还没跑过。先在终端执行一次，再刷新本页：</p>
          <p className="mono mt-10">uv run python tools\migration_check.py</p>
          <p className="hint mt-10">{d.hint || '只做结构检查，不跑流水线、不改原件。'}</p>
        </section>
      </>
    )
  }

  return (
    <>
      <p className="hint mt-2">换馆沙盘 · 只碰台账副本，不碰 input/ 原件</p>

      <section className="card pad-card-lg">
        <h1 className="fs-24">换馆沙盘</h1>
        <p className="fc-lead">
          拿一份台账副本，按引擎的读表要求逐项检查：表在不在、22 个学科名认不认、
          最新期次列有没有、母版在不在。<b>不跑流水线、不改原件。</b>
        </p>
        <div className="rowc mt-14">
          <span className={`pill ${d.ready ? 'signed' : 'stale'}`}>
            {d.ready ? '结构齐全，换馆只差配置' : '还有缺项'}
          </span>
          <span className="hint">生成于 {d.generated_at || '—'} · 样本：{d.ledger || '—'}</span>
        </div>
      </section>

      <section className="ar-story" aria-label="换馆结构检查">
        {(d.checks || []).map((c) => (
          <div className={`ar-story-step ${c.ok ? 'ok' : 'warn'}`} key={c.id}>
            <span className="ar-story-k">{c.label}</span>
            <b>{c.ok ? '通过' : '缺项'}</b>
            <small>{c.detail}</small>
          </div>
        ))}
      </section>

      <section className="card mt-18 pad-card">
        <h2 className="h-sec">换馆只改四件事</h2>
        <div className="mig-four">
          {FOUR.map((x) => (
            <div className="mig-card" key={x.t}>
              <b>{x.t}</b>
              <small>{x.d}</small>
            </div>
          ))}
        </div>
        <p className="hint mt-12">
          这次用的是<b>云大样本的副本</b>，验证的是「引擎不依赖校名、只依赖台账的固定结构」；
          真实换馆按上面四件事替换，不需要改引擎。
        </p>
      </section>

      <p className="hint mt-16">
        重跑一次：<span className="mono">uv run python tools\migration_check.py</span>，刷新本页即可。
      </p>
    </>
  )
}
