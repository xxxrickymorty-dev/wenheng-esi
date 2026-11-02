/* 红件全量清单（阶段 1 · P0-3）——签单依据的全量表。
   设计稿：web/mockups/报告深入视图.html（视图三）· 数据源 GET /api/periods/{p}/redslots
   🔴 只透传后端给的行，前端不聚合、不换算；分类计数是**行数统计**（不是报告口径数字）。 */

import { useEffect, useMemo, useState } from 'react'
import { getRedSlots, type RedRow } from './api-collation'
import { Icon } from './icons'
import { errorNote } from './lib/status'
import { Info } from './Info'

/* 分组名＝内容名（T 编号退后台，2026-10-17 冗余收敛稿⑤）：名册照抄大纲口径
   server/app.py api_period_outline——T20＝学科×高校矩阵、T01/大表数值＝大表、
   T19＝省域表、T03–T18＝预测章学科表。只改分组显示，行照旧透传、计数仍是行数。 */
function contentGroup(g: string): string {
  if (g === 'T20') return '学科×高校矩阵'
  if (g === 'T01' || g === '大表数值') return '大表'
  if (g === 'T19') return '省域表'
  const m = /^T(\d{2})$/.exec(g)
  if (m && Number(m[1]) >= 3 && Number(m[1]) <= 18) return '预测学科表'
  if (g === '正文') return '正文'
  return '其他'
}

/* 位置坐标的人话读法（39 分册 D）：原始码 T01/r1c0 → 「第 1 表·第 1 行·第 1 列」
   （列号 c 从 0 起，展示按第 N 列）；矩阵列是高校名（T20/r3c云大）→ 「第 20 表·第 3 行·云大」；
   T01/表头 → 「第 1 表·表头」；正文/p2 → 「正文·第 2 段」；其余原样。
   原始码一律收进 title 悬停。转换只改显示，行数据零改动。 */
function posLabel(raw: string): string {
  let m = /^T(\d{1,2})\/r(\d+)(?:c([^/]+))?$/.exec(raw)
  if (m) {
    const col = m[3]
    const colTxt = col == null ? '' : /^\d+$/.test(col) ? `·第 ${Number(col) + 1} 列` : `·${col}`
    return `第 ${Number(m[1])} 表·第 ${Number(m[2])} 行${colTxt}`
  }
  m = /^T(\d{1,2})\/(.+)$/.exec(raw)
  if (m) return `第 ${Number(m[1])} 表·${m[2]}`
  m = /^正文\/p(\d+)$/.exec(raw)
  if (m) return `正文·第 ${m[1]} 段`
  return raw
}

export function RedList({ period, canDownload = false }: {
  period: string | null
  /** 红件 Markdown 下载口仍只给管理员（操作员只读屏，不给一点就 403 的按钮）。 */
  canDownload?: boolean
}) {
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
    const m = new Map<string, { n: number; raw: Set<string> }>()
    for (const r of rows ?? []) {
      const raw = r.group || '其他'
      const key = contentGroup(raw)
      const e = m.get(key) ?? { n: 0, raw: new Set<string>() }
      e.n += 1
      e.raw.add(raw)
      m.set(key, e)
    }
    return [...m.entries()].sort((a, b) => b[1].n - a[1].n)
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
        {period && canDownload && (
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
            {byGroup.map(([g, e]) => (
              <span className="pill" key={g} title={`含 ${[...e.raw].sort().join(' / ')}`}>{g} {e.n}</span>
            ))}
          </div>
          <div className="toolbar mt-12">
            <input className="search" value={q} onChange={(e) => setQ(e.target.value)}
                   placeholder="搜索位置 / 修改前 / 修改后 / 来源…" />
            <span className="hint">匹配 <b className="mono">{shown.length} / {rows.length}</b> 条</span>
          </div>
          {shown.some((r) => !r.old) && (
            <p className="hint mt-8">
              「修改前」显示「—」＝母版原处空白
              <Info label="「修改前」显示「—」是怎么回事">
                「修改前」显示「—」＝母版此处原本就是空白（大表在母版里是空表、本期逐格填入），不是漏记。
              </Info>
            </p>
          )}
          {/* 39 分册 D：表头冻结＋窄屏横滑。滚动容器限高，thead 吸顶常驻。 */}
          <p className="hint red-swipe mt-8">表格较宽，左右滑动查看 →</p>
          <div className="red-wrap">
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
                    <td className="fs-135 ink-3 red-pos" title={r.label || r.group}>
                      {posLabel(r.label || r.group)}
                    </td>
                    <td className="ink-3">{r.old || '—'}</td>
                    <td className="ink-zhu">{r.new}</td>
                    <td className="fs-14 red-src" title={r.src}>{r.src}</td>
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
