/* 带角标的正文（查数据回答；票 07 从分析台抽出——问文衡已并入对话前门）。
   第 k 个数字 ↔ sources[k-1]（后端已按出现次序对齐），点开看来源。
   数字与来源全部来自后端——前端只渲染，不计算、不换算。

   2026-10-29 rick：规则版作答原来是一堵墙。这里改为**分块渲染**（空行分段）：
   `### 小标题` → 标题行、`- ` 行 → 列表、`**x**` → 粗体，其余 → 段落。
   数字编号 k 跨块连续，保证「第 k 个数字 ↔ sources[k-1]」不破。 */

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

  const blocks = useMemo(() => {
    let k = 0                                   // 全局角标序号：跨块、跨粗体连续

    const digits = (s: string, key: string): ReactNode[] => {
      const nodes: ReactNode[] = []
      const re = /\d+(?:\.\d+)?/g
      let last = 0
      let m: RegExpExecArray | null
      while ((m = re.exec(s)) !== null) {
        k += 1
        const idx = k
        if (m.index > last) nodes.push(s.slice(last, m.index))
        const src = sources[idx - 1]
        nodes.push(
          <span key={`${key}d${idx}`} className="rel-ib">
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
              </span>
            )}
          </span>,
        )
        last = m.index + m[0].length
      }
      if (last < s.length) nodes.push(s.slice(last))
      return nodes
    }

    const inline = (s: string, key: string): ReactNode[] => {
      const out: ReactNode[] = []
      // 先按 **粗体** 切，再在每片里切数字（顺序不变 → 编号不错位）
      s.split(/(\*\*[^*]+\*\*)/g).forEach((p, i) => {
        if (!p) return
        if (p.length > 4 && p.startsWith('**') && p.endsWith('**')) {
          out.push(<strong key={`${key}b${i}`}>{digits(p.slice(2, -2), `${key}b${i}`)}</strong>)
        } else {
          out.push(...digits(p, `${key}b${i}`))
        }
      })
      return out
    }

    const out: ReactNode[] = []
    let n = 0
    for (const raw of text.split(/\n{2,}/)) {
      const block = raw.trim()
      if (!block) continue
      n += 1
      const key = `b${n}`
      if (block.startsWith('### ')) {
        out.push(<h4 key={key} className="nt-h">{inline(block.slice(4), key)}</h4>)
        continue
      }
      if (/^\s*[-•]\s/m.test(block)) {
        const items = block.split('\n').map((l) => l.replace(/^\s*[-•]\s*/, '').trim()).filter(Boolean)
        out.push(
          <ul key={key} className="nt-ul">
            {items.map((it, ii) => <li key={ii}>{inline(it, `${key}-${ii}`)}</li>)}
          </ul>,
        )
        continue
      }
      out.push(<p key={key} className="serif-prose">{inline(block, key)}</p>)
    }
    return out
  }, [text, sources, open])

  return (
    <div className="nt-body" onClick={() => setOpen(null)}>
      {blocks}
    </div>
  )
}
