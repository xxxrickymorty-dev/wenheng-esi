/* 供应商节·AI 调用统计（2026-11-04 票 2）：
   一行汇总（模型 / 规则 / 失败三数）＋ 按位明细折叠（回落原因码照后端口径透传）。
   落点＝设置中心供应商节——「模型模式 / 规则稿模式」就在这一节定，
   统计是它的结果，两件事看一处。§十：布局自解释，不写解释段；
   403（非管理员）与拉取失败整块不显示（不误显）；
   一次调用都没有（total=0）也不显示——一排 0 不是信息。 */

import { useEffect, useState } from 'react'
import { getCallStats, type CallStats, type CallStatsLabel } from '../api-ai-stats'

/** 一枚位（label）的回落明细：「原因码 ×n」串；没有回落回空串。 */
export function fallbackText(lb: CallStatsLabel): string {
  return Object.entries(lb.fallback ?? {})
    .filter(([, n]) => n > 0)
    .map(([code, n]) => `${code} ×${n}`)
    .join(' · ')
}

export function CallStatsBlock({ open }: { open: boolean }) {
  const [stats, setStats] = useState<CallStats | null>(null)
  useEffect(() => {
    if (!open) return
    let alive = true
    setStats(null)
    getCallStats()
      .then((s) => { if (alive) setStats(s) })
      .catch(() => { /* 403 / 拉不到：整块不显示 */ })
    return () => { alive = false }
  }, [open])
  if (!stats || !stats.total) return null
  const m = stats.modes ?? { model: 0, rule: 0, failed: 0 }
  const labels = stats.labels ?? []
  return (
    <details className="mdl-stats">
      <summary>
        调用&nbsp;
        <b>{m.model}</b> 模型 · <b>{m.rule}</b> 规则 · <b>{m.failed}</b> 失败
      </summary>
      {labels.length > 0 && (
        <table className="mdl-stats-tbl">
          <thead>
            <tr><th>位</th><th>模型</th><th>规则</th><th>失败</th><th>回落</th></tr>
          </thead>
          <tbody>
            {labels.map((lb) => {
              const fb = fallbackText(lb)
              return (
                <tr key={lb.label}>
                  <td>{lb.label}</td>
                  <td>{lb.model}</td>
                  <td>{lb.rule}</td>
                  <td>{lb.failed}</td>
                  <td>{fb}</td>
                </tr>
              )
            })}
          </tbody>
        </table>
      )}
    </details>
  )
}
