/* 带角标的正文（查数据回答；票 07 从分析台抽出——问文衡已并入对话前门）。
   第 k 个数字 ↔ sources[k-1]（后端已按出现次序对齐），点开看来源。
   数字与来源全部来自后端——前端只渲染，不计算、不换算。 */

import { useMemo, useState, type ReactNode } from 'react'

export type NumberedSource = {
  index: number
  kind: string
  pointer: string
  label: string
  detail: string
  value: string
}

export function NumberedText({ text, sources }: { text: string; sources: NumberedSource[] }) {
  const [open, setOpen] = useState<number | null>(null)
  const parts = useMemo(() => {
    const nodes: ReactNode[] = []
    const re = /\d+(?:\.\d+)?/g
    let last = 0
    let k = 0
    let m: RegExpExecArray | null
    while ((m = re.exec(text)) !== null) {
      k += 1
      const idx = k
      if (m.index > last) nodes.push(text.slice(last, m.index))
      const src = sources[idx - 1]
      nodes.push(
        <span key={`n${k}`} className="rel-ib">
          <button
            type="button"
            className="nt-num"
            onClick={(e) => { e.stopPropagation(); setOpen(open === idx ? null : idx) }}
            title={src ? `${src.label}：${src.value}` : undefined}
          >
            {m[0]}
          </button>
          {open === idx && src && (
            <span className="card an-pop">
              <b className="ink">{src.label}</b>
              <br />
              {src.detail}
              <span className="hint"> · 台账数字</span>
            </span>
          )}
        </span>,
      )
      last = m.index + m[0].length
    }
    if (last < text.length) nodes.push(text.slice(last))
    return nodes
  }, [text, sources, open])

  return (
    <p className="serif-prose" onClick={() => setOpen(null)}>
      {parts}
    </p>
  )
}
