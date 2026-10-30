/* 工具调用轨迹（2026-10-29）：这一轮模型到底问了台账什么问题、问到没有、花多久。
   DeepSeek 那种折叠块——**流式时自动展开**（能看见它一条条查），答完收起来只留一行。
   🔴 这里只显示后端给的「工具名 + 中文摘要 + 耗时 + 成没成」；
      模型自己写的字一个都不进来（防它在轨迹里夹带没出处的数字）。 */

import { useEffect, useRef, useState } from 'react'

export type ToolCall = {
  tool: string
  /** 人话标签：「查台账」「盘点」「产物核对」 */
  label: string
  /** 一句摘要：「查 数学·接近度」 */
  summary: string
  ok: boolean
  refused: boolean
  ms: number
}

export function ToolTrace({ calls, live }: { calls: ToolCall[]; live?: boolean }) {
  const [open, setOpen] = useState(!!live)
  const lastLive = useRef(!!live)

  /* 流式时自动展开；答完那一刻自动收起（人已看到过程，结果是要读的正文）。 */
  useEffect(() => {
    if (live && !lastLive.current) setOpen(true)
    if (!live && lastLive.current) setOpen(false)
    lastLive.current = !!live
  }, [live])

  if (!calls.length) return null
  const n = calls.length
  return (
    <div className={`tt${open ? ' open' : ''}`}>
      <button type="button" className="tt-h" aria-expanded={open}
              onClick={() => setOpen((v) => !v)}>
        <span className="tt-h-t">
          {live ? '正在查台账…' : `工具调用 · ${n} 次`}
          {live && <span className="tt-dots" aria-hidden="true"><i /><i /><i /></span>}
        </span>
        <span className="tt-h-c" aria-hidden="true">{open ? '收起' : '展开'}</span>
      </button>
      {open && (
        <ol className="tt-list">
          {calls.map((c, i) => (
            <li key={i} className={`tt-row${c.ok ? '' : ' bad'}`}>
              <span className="tt-n" aria-hidden="true">{i + 1}</span>
              <code className="tt-tool">{c.tool}</code>
              <span className="tt-s">{c.summary || c.label}</span>
              <span className="tt-ms">
                {c.refused ? '被拒' : c.ok ? '✓' : '×'} {c.ms}ms
              </span>
            </li>
          ))}
        </ol>
      )}
    </div>
  )
}
