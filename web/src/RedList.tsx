/* 红件全量清单（阶段 1 · P0-3）——签单依据的全量表。
   设计稿：web/mockups/报告深入视图.html（视图三）· 数据源 GET /api/periods/{p}/redslots
   🔴 只透传后端给的行，前端不聚合、不换算；分类计数是**行数统计**（不是报告口径数字）。 */

import { useEffect, useMemo, useState } from 'react'
import { getRedSlots, type RedRow } from './api-collation'
import { Icon } from './icons'
import { errorNote } from './lib/status'

export function RedList({ period }: { period: string | null }) {
  const [rows, setRows] = useState<RedRow[] | null>(null)
  const [note, setNote] = useState<string | null>(null)
  const [q, setQ] = useState('')

  useEffect(() => {
    if (!period) return
    let alive = true
    setRows(null); setNote(null); setQ('')
    getRedSlots(period)
      .then((r) => { if (alive) setRows(r) })
      .catch((e) => {
        if (!alive) return
        setNote(errorNote(e, '红色件清单'))
      })
    return () => { alive = false }
  }, [period])

  const shown = useMemo(() => {
    if (!rows) return []
    const k = q.trim().toLowerCase()
    return k ? rows.filter((r) => `${r.group} ${r.label} ${r.old} ${r.new} ${r.src} ${r.kind}`.toLowerCase().includes(k)) : rows
  }, [rows, q])

  const byGroup = useMemo(() => {
    const m = new Map<string, number>()
    for (const r of rows ?? []) m.set(r.group || '其他', (m.get(r.group || '其他') ?? 0) + 1)
    return [...m.entries()].sort((a, b) => b[1] - a[1])
  }, [rows])

  return (
    <section className="card mt-18 pad-card">
      <p className="hint mb-10">
        <a href={`/app/?view=report${period ? `&period=${encodeURIComponent(period)}` : ''}`}>← 回报告</a>
        {' · '}期次 <b className="mono">{period ?? '—'}</b>
      </p>
      <h2 className="h-sec">
        <Icon name="list" size={21} />红色件清单
        {rows && <span className="hint hint-num">共 {rows.length} 条</span>}
        {period && (
          <a className="btn line ml-auto btn-md" 
             href={`/p/${encodeURIComponent(period)}/download/red_list`}>下载 Markdown</a>
        )}
      </h2>

      {note ? (
        <div className="pending-box mt-12">
          {note}
          {note.includes('可能尚未出稿') && period && (
            <> <a href={`/app/?period=${encodeURIComponent(period)}`}>去生成这一期 →</a></>
          )}
        </div>
      ) : !rows ? (
        <div className="pending-box mt-12">正在读红色件清单……</div>
      ) : (
        <>
          <div className="chips mt-12">
            {byGroup.map(([g, n]) => <span className="pill" key={g}>{g} {n}</span>)}
          </div>
          <div className="toolbar mt-12">
            <input className="search" value={q} onChange={(e) => setQ(e.target.value)}
                   placeholder="搜索位置 / 修改前 / 修改后 / 来源…" />
            <span className="hint">匹配 <b className="mono">{shown.length} / {rows.length}</b> 条</span>
          </div>
          <div className="tablewrap">
            <table>
              <thead>
                <tr>
                  <th className="w-52">#</th>
                  <th className="w-170">位置</th>
                  <th>修改前</th>
                  <th>修改后</th>
                  <th className="w-190">来源</th>
                </tr>
              </thead>
              <tbody>
                {shown.map((r, i) => (
                  <tr key={`${r.group}-${r.label}-${i}`}>
                    <td className="mono ink-3">{i + 1}</td>
                    <td className="mono fs-135 ink-3 nowrap">
                      {r.label || r.group}
                    </td>
                    <td className="ink-3">{r.old}</td>
                    <td className="ink-zhu">{r.new}</td>
                    <td className="fs-14">{r.src}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          {shown.length === 0 && (
            <p className="hint mt-10">{q.trim() ? `没有匹配「${q}」的条目。` : '这一期还没有红色件条目。'}</p>
          )}
        </>
      )}
    </section>
  )
}
