/* 任务瀑布：这次运行每一步用了多久（老站任务页「03 任务瀑布」的对应物）。
   数字全部来自后端——每步秒数是后端换算好的，前端只排版、不自己算。
   生成中每 2 秒自己刷新一次，跑完自动停。
   收束汇总事件（「全链路 … 秒」）后端单列在 summary 里、不进步骤数组（2026-09-24 已修）。 */

import { useEffect, useState } from 'react'
import { getJobProgress, type WaterfallRow, type WaterfallSummary } from './api'
import { Icon } from './icons'
import { isTerminal } from './wb'

/** 步骤状态 → 馆员看得懂的话（后端给的是 done / warn / failed） */
const STEP_LABEL: Record<string, string> = { done: '完成', warn: '有告警', failed: '失败' }
const STEP_ICON: Record<string, string> = { done: 'check', warn: 'alert', failed: 'alert' }
const STEP_COLOR: Record<string, string> = {
  done: 'var(--ok)', warn: 'var(--warn)', failed: 'var(--bad)',
}

/** 瀑布行的渲染（生成台与运行档案共用；行原样来自后端，前端不减不加） */
export function WaterfallRows({ rows, totalSec, running, summary }: {
  rows: WaterfallRow[]
  totalSec: number
  running?: boolean
  summary?: WaterfallSummary | null
}) {
  const closedOrphan = rows.some((r) => r.orphan && !running)
  return (
    <>
      <div className="wf">
        {rows.map((r) => {
          const inProgress = !!running && r.orphan
          const color = inProgress ? 'var(--zhu)' : (STEP_COLOR[r.status] ?? 'var(--ink-3)')
          const pct = totalSec > 0 ? Math.min(100, Math.max(0, (r.sec / totalSec) * 100)) : 0
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
                <i style={{ transform: `scaleX(${pct / 100})`, background: color }} />
              </span>
              <span className="wf-sec">{inProgress ? '计时中…' : `${r.sec} 秒${r.orphan ? '*' : ''}`}</span>
            </div>
          )
        })}
      </div>
      {summary?.detail && (
        <p className="hint mt-10" data-src="backend">{summary.detail}</p>
      )}
      {closedOrphan && (
        <p className="hint mt-8 fs-135">
          * 这一步记录不齐，耗时仅供参考。
        </p>
      )}
    </>
  )
}

export function Waterfall({ jobId }: { jobId: string }) {
  const [rows, setRows] = useState<WaterfallRow[]>([])
  const [summary, setSummary] = useState<WaterfallSummary | null>(null)
  const [total, setTotal] = useState(0)
  const [running, setRunning] = useState(false)
  const [missing, setMissing] = useState<{ note: string } | null>(null)
  const [gone, setGone] = useState(false)
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    let alive = true
    let timer: number | undefined
    setGone(false); setMissing(null); setLoading(true)
    const load = async () => {
      try {
        const r = await getJobProgress(jobId)
        if (!alive) return
        setRows(r.waterfall ?? [])
        setSummary(r.summary ?? null)
        setTotal(r.total_sec ?? 0)
        const run = !!r.status && !isTerminal(r.status)
        setRunning(run)
        setMissing(r.missing ? { note: r.note } : null)
        setLoading(false)
        if (run) timer = window.setTimeout(load, 2000)
      } catch {
        if (alive) setGone(true)   /* 读不到（老任务 / 无权限）就不显示这一块 */
      }
    }
    load()
    return () => { alive = false; if (timer !== undefined) window.clearTimeout(timer) }
  }, [jobId])

  if (gone) return null

  return (
    <div className="mt-18 divider-top">
      <h3 className="fs-15">任务瀑布（各步耗时）</h3>

      {loading ? (
        <p className="hint mt-6">正在读取……</p>
      ) : missing ? (
        running
          ? <p className="hint mt-6">刚起步，记录还没写下来。</p>
          : <div className="pending-box mt-8">{missing.note || '这次运行没有留下每步记录。'}</div>
      ) : rows.length === 0 ? (
        <p className="hint mt-6">
          {running ? '运行开始后显示每一步耗时。' : '这次运行没有记录到每步耗时。'}
        </p>
      ) : (
        <WaterfallRows rows={rows} totalSec={total} running={running} summary={summary} />
      )}
    </div>
  )
}
