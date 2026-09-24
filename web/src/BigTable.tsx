/* 学科数据总览（读数版）——22 个学科 × 六列，一屏看完这一期的学科表现。
   值全部取自逐格溯源的数据口（GET /api/periods/{p}/trace?cat=bigtable），
   后端已经把每格格式化好（"1.36"、"↑33.87%"）——前端**不换算、不再四舍五入**。
   点一行展开该学科的逐格来源（出自哪张表、怎么算出来的）；想看全部 239 格另走逐格溯源页。 */

import { useEffect, useMemo, useState } from 'react'
import { req } from './api'
import { Icon } from './icons'

type TraceRow = {
  loc: string; col?: string; report?: string; label?: string
  sheet?: string; src_ref?: string; ledger?: string; how?: string
}
type TraceData = { period?: string; rows?: TraceRow[]; total?: number; n?: number }

/** 六列的键就是溯源数据里的 col 键名（后端定的，别改名） */
const COLS = [
  { key: 'papers', name: '发文量' },
  { key: 'total_cites', name: '总被引' },
  { key: 'cnci', name: 'CNCI' },
  { key: '顶尖论文', name: '顶尖论文' },
  { key: '国内排名/变化', name: '国内排名' },
  { key: '接近度变化', name: '较上期' },
]

type DiscRow = { cn: string; en: string; cells: Record<string, TraceRow> }

/** loc 形如 T01/r1c3：同一张表同一行 = 一个学科；列 = 指标 */
function groupByDiscipline(rows: TraceRow[]): DiscRow[] {
  const g = new Map<string, DiscRow>()
  for (const r of rows) {
    const m = /^(.+?)\/r(\d+)c(\d+)$/.exec(r.loc || '')
    if (!m) continue
    const key = `${m[1]}/r${m[2]}`
    const row = g.get(key) ?? { cn: '', en: '', cells: {} }
    if (r.col) row.cells[r.col] = r
    g.set(key, row)
  }
  for (const row of g.values()) {
    row.cn = row.cells['学科']?.report ?? '—'
    row.en = row.cells['学科']?.src_ref ?? ''
  }
  return [...g.values()]
}

/** 排序用的数值：只拿来排先后，不改显示的文字（显示一律用后端给的字符串） */
function orderNum(r: TraceRow | undefined): number {
  const n = Number((r?.report ?? '').replace(/[^\d.-]/g, ''))
  return Number.isFinite(n) ? n : -1
}

export function BigTable({ period }: { period: string | null }) {
  const [rows, setRows] = useState<DiscRow[]>([])
  const [total, setTotal] = useState(0)
  const [note, setNote] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)
  const [q, setQ] = useState('')
  const [sortDesc, setSortDesc] = useState(true)
  const [sel, setSel] = useState<string | null>(null)

  useEffect(() => {
    if (!period) return
    let alive = true
    setBusy(true)
    setRows([]); setNote(null); setSel(null)
    ;(async () => {
      try {
        const j = await req<TraceData>(
          `/api/periods/${encodeURIComponent(period)}/trace?cat=bigtable&limit=300`,
        )
        if (!alive) return
        setRows(groupByDiscipline(j.rows ?? []))
        setTotal(j.total ?? (j.rows ?? []).length)
      } catch (e) {
        const h = e as { status?: number }
        if (alive) {
          setNote(h.status === 403 ? '学科数据总览需要管理员权限（后端按角色拦的）。'
            : h.status === 404 ? '这一期还没有大表数据（可能尚未出稿）。'
              : '读学科数据失败。')
        }
      } finally {
        if (alive) setBusy(false)
      }
    })()
    return () => { alive = false }
  }, [period])

  const view = useMemo(() => {
    const kw = q.trim().toLowerCase()
    const hit = kw
      ? rows.filter((r) => r.cn.toLowerCase().includes(kw) || r.en.toLowerCase().includes(kw))
      : rows
    // 默认按顶尖论文排（像老办法那样，一眼看谁产得多）；数值只用于排序
    return [...hit].sort((a, b) =>
      (orderNum(a.cells['顶尖论文']) - orderNum(b.cells['顶尖论文'])) * (sortDesc ? -1 : 1))
  }, [rows, q, sortDesc])

  const cur = view.find((r) => r.cn === sel) ?? rows.find((r) => r.cn === sel) ?? null

  return (
    <section className="card" style={{ padding: '22px 24px' }}>
      <h2 style={{ fontSize: 22, display: 'flex', alignItems: 'center', gap: 10, flexWrap: 'wrap' }}>
        <Icon name="list" size={22} />学科数据总览
        <span className="tag" style={{ marginLeft: 6 }}>{period ?? '（选择期次）'}</span>
      </h2>
      <p className="fc-lead" style={{ fontSize: 15.5 }}>
        当前报告收录的学科一屏看完；每格都能回读到原始表——点一行展开来源。
      </p>

      <div className="bt-tools">
        <label className="bt-search">
          <Icon name="search" size={16} />
          <input value={q} onChange={(e) => setQ(e.target.value)} placeholder="搜索学科名称" aria-label="搜索学科名称" />
        </label>
        <button className="btn" onClick={() => setSortDesc((v) => !v)}>
          顶尖论文排序 {sortDesc ? '↓' : '↑'}
        </button>
        <span className="hint">显示 {view.length} / {rows.length} 个学科{total ? ` · 共 ${total} 格已回读` : ''}</span>
      </div>

      {note && <div className="pending-box" style={{ marginTop: 14 }}>{note}</div>}
      {busy && !rows.length && <div className="pending-box" style={{ marginTop: 14 }}>正在读学科数据……</div>}

      {!!view.length && (
        <div className="tablewrap" style={{ marginTop: 12 }}>
          <table className="bt-tbl">
            <thead>
              <tr>
                <th>学科</th>
                {COLS.map((c) => <th key={c.key} style={{ textAlign: 'right' }}>{c.name}</th>)}
              </tr>
            </thead>
            <tbody>
              {view.map((r) => (
                <tr key={r.cn} className={r.cn === sel ? 'on' : ''} tabIndex={0}
                    role="button" aria-label={`查看${r.cn}的逐格来源`}
                    onClick={() => setSel(r.cn === sel ? null : r.cn)}
                    onKeyDown={(e) => {
                      if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); setSel(r.cn === sel ? null : r.cn) }
                    }}>
                  <td>{r.cn}<span className="bt-en">{r.en}</span></td>
                  {COLS.map((c) => {
                    const v = r.cells[c.key]?.report ?? '—'
                    const cls = c.key === '接近度变化' && v.startsWith('↑') ? 'num bt-up'
                      : c.key === '接近度变化' && v.startsWith('↓') ? 'num bt-down' : 'num'
                    return <td key={c.key} className={cls}>{v}</td>
                  })}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      {cur && (
        <div className="bt-detail">
          <h3>{cur.cn}<span className="bt-en" style={{ display: 'inline' }}>{cur.en}</span>
            <button className="btn" style={{ marginLeft: 'auto', padding: '6px 12px', fontSize: 14 }}
                    onClick={() => setSel(null)}>收起</button>
          </h3>
          <div className="bt-cells">
            {COLS.map((c) => {
              const cell = cur.cells[c.key]
              return (
                <div className="bt-cell" key={c.key}>
                  <div className="k">{c.name}</div>
                  <b>{cell?.report ?? '—'}</b>
                  {cell && (
                    <span className="s">
                      来源 {cell.sheet || '—'}{cell.how ? ` · ${cell.how}` : ''}
                    </span>
                  )}
                </div>
              )
            })}
          </div>
          <p className="hint" style={{ marginTop: 10 }}>
            这是这一行的六格来源；要看全部 239 格（含阈值、千分位等）请走
            {' '}<a href={`/app/?view=trace${period ? `&period=${encodeURIComponent(period)}` : ''}`}>逐格溯源</a>。
          </p>
        </div>
      )}
    </section>
  )
}
