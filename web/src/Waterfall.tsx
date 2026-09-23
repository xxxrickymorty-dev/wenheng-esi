/* 任务瀑布：这次运行每一步用了多久（老站任务页「03 任务瀑布」的对应物）。
   数字全部来自 GET /api/jobs/{id}/progress——后端把进度记录换算成每步秒数，
   前端只排版、不自己算。生成中每 2 秒自己刷新一次，跑完自动停。 */

import { useEffect, useState } from 'react'
import { getJobProgress, type JobProgress, type ProgressEvent, type WaterfallRow } from './api'
import { Icon } from './icons'
import { isTerminal } from './wb'

/** 步骤状态 → 馆员看得懂的话（后端给的是 done / warn / failed） */
const STEP_LABEL: Record<string, string> = { done: '完成', warn: '有告警', failed: '失败' }
const STEP_ICON: Record<string, string> = { done: 'check', warn: 'alert', failed: 'alert' }
const STEP_COLOR: Record<string, string> = {
  done: 'var(--ok)', warn: 'var(--warn)', failed: 'var(--bad)',
}

/** 瀑布里带着最后一条「完成」汇总记录（与运行档案页同口径）。
    它不是流水线的一步，这里不单列——老站任务页也是这么处理的。 */
const isSummary = (r: WaterfallRow) => r.step === 'done'

/** 后端按「秒」给行排序，同一秒里开工的几步会按名字先后排（解析可能排到计算后面）。
    这里用原始记录里的出现次序把同一秒内的先后摆正——只调顺序，不产生数字。 */
function ordered(rows: WaterfallRow[], events: ProgressEvent[]): WaterfallRow[] {
  const firstSeen = new Map<string, number>()
  events.forEach((e, i) => {
    const s = e?.step
    if (s && !firstSeen.has(s)) firstSeen.set(s, i)
  })
  return [...rows].sort((a, b) => {
    const byTime = (a.at || '').localeCompare(b.at || '')
    if (byTime !== 0) return byTime
    return (firstSeen.get(a.step) ?? 0) - (firstSeen.get(b.step) ?? 0)
  })
}

export function Waterfall({ jobId }: { jobId: string }) {
  const [p, setP] = useState<JobProgress | null>(null)
  const [gone, setGone] = useState(false)

  useEffect(() => {
    let alive = true
    let timer: number | undefined
    setP(null); setGone(false)
    const load = async () => {
      try {
        const r = await getJobProgress(jobId)
        if (!alive) return
        setP(r)
        if (r.status && !isTerminal(r.status)) timer = window.setTimeout(load, 2000)
      } catch {
        if (alive) setGone(true)   /* 读不到（老任务 / 无权限）就不显示这一块 */
      }
    }
    load()
    return () => { alive = false; if (timer !== undefined) window.clearTimeout(timer) }
  }, [jobId])

  if (gone) return null

  const running = !!p && !!p.status && !isTerminal(p.status)
  const rows = ordered((p?.waterfall ?? []).filter((r) => !isSummary(r)), p?.events ?? [])
  const closedOrphan = rows.some((r) => r.orphan && !running)

  return (
    <div style={{ marginTop: 18, borderTop: '1px solid var(--line)', paddingTop: 14 }}>
      <h3 style={{ fontSize: 15 }}>任务瀑布（各步耗时）</h3>

      {!p ? (
        <p className="hint" style={{ marginTop: 6 }}>正在读这次运行的记录……</p>
      ) : p.missing ? (
        running
          ? <p className="hint" style={{ marginTop: 6 }}>这次运行刚起步，每步记录还没写下来……</p>
          : <div className="pending-box" style={{ marginTop: 8 }}>{p.note || '这次运行没有留下每步记录。'}</div>
      ) : rows.length === 0 ? (
        <p className="hint" style={{ marginTop: 6 }}>
          {running ? '运行开始后，这里显示每一步用了多久。' : '这次运行没有记录到每步耗时。'}
        </p>
      ) : (
        <>
          <div className="wf">
            {rows.map((r) => {
              const inProgress = running && r.orphan
              const color = inProgress ? 'var(--zhu)' : (STEP_COLOR[r.status] ?? 'var(--ink-3)')
              const pct = p.total_sec > 0 ? Math.min(100, Math.max(0, (r.sec / p.total_sec) * 100)) : 0
              return (
                <div className="wf-row" key={r.step}>
                  <span className="wf-name">
                    <b>{r.name}</b>
                    {r.detail && <small>{r.detail}</small>}
                  </span>
                  <span className="wf-state" style={{ color }}>
                    <Icon name={inProgress ? 'refresh' : (STEP_ICON[r.status] ?? 'clock')} size={16} />
                    {inProgress ? '运行中' : (STEP_LABEL[r.status] ?? r.status)}
                  </span>
                  <span className="wf-track" aria-hidden="true">
                    <i style={{ width: `${pct}%`, background: color }} />
                  </span>
                  <span className="wf-sec">{inProgress ? '计时中…' : `${r.sec} 秒${r.orphan ? '*' : ''}`}</span>
                </div>
              )
            })}
          </div>
          {closedOrphan && (
            <p className="hint" style={{ marginTop: 8, fontSize: 13.5 }}>
              * 这一步只有开工或只有收工记录，耗时对不上（多半是中途插入的提醒或中断）。
            </p>
          )}
        </>
      )}
    </div>
  )
}
