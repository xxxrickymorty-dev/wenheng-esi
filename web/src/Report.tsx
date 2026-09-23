/* 报告 · 数据视图（取自静态稿 mockups/v2-工作台与报告.html 的报告屏）
   与 G 的翻书**分工**：翻书＝读正文（人的阅读）；这里＝看数据与改动（大表 / 朱批 / 溯源 / 印记链）。

   🔴 诚实边界（项目红线：缺数据不填假数）：
     读数带 / 印记链 / 产物 / 对勘 / 朱批 / 图册 都已接真数据；
     哪一块没接上就整块写明"等什么"，不放占位数字、不假装有内容。
*/

import { useEffect, useState } from 'react'
import {
  getArtifacts, getStatus, humanSize,
  type Artifact, type Period,
} from './api'
import { getCharts, getCollation, type ChartRow, type CollationRow } from './api2'
import { getFacts, type Facts } from './api4'
import { Icon } from './icons'

/** 期次印记链：签过＝朱印 / 签名失效＝金印 / 未签发＝墨线框。这是产品的原创资产，也是本屏的记忆点。 */
function Chain({
  periods, current, onPick,
}: {
  periods: Period[]
  current: string | null
  onPick: (p: string) => void
}) {
  return (
    <aside className="chain">
      <h3>期次印记链</h3>
      <p className="cap">
        按时间从左到右。签过是朱印，签名失效是金印，未签发是墨线框。
        <br />
        （期号与月份来自后端；点一枚换一期。）
      </p>
      <div className="seals">
        {periods.map((p) => {
          const cls = p.status === 'signed' ? 'signed' : p.status === 'stale' ? 'stale' : 'unsigned'
          const isNow = p.period === current
          return (
            <button
              key={p.period}
              type="button"
              className="sealbox"
              onClick={() => onPick(p.period)}
              style={{ background: 'none', border: 0, cursor: 'pointer', padding: 0 }}
              aria-current={isNow}
            >
              <span className="now-tag">{isNow ? '本期' : ''}</span>
              <span className={`seal ${cls} ${isNow ? 'now' : ''}`}>{p.period}</span>
              <span className="lbl">{p.label}</span>
            </button>
          )
        })}
      </div>
      <div className="legend">
        <span><i style={{ background: 'var(--zhu)' }} />已签发</span>
        <span><i style={{ boxShadow: 'inset 0 0 0 2px var(--gold)' }} />签名失效</span>
        <span><i style={{ boxShadow: 'inset 0 0 0 2px var(--line)' }} />未签发</span>
      </div>
    </aside>
  )
}

/** 产物卡：真数据（/api/status 取最近一次任务 → /api/jobs/{id}/artifacts） */
function Artifacts() {
  const [items, setItems] = useState<Artifact[] | null>(null)
  const [note, setNote] = useState<string | null>(null)

  useEffect(() => {
    let alive = true
    ;(async () => {
      try {
        const st = await getStatus()
        const id = st.last?.id
        if (!id) {
          if (alive) setNote('还没有任何一次生成记录。')
          return
        }
        const list = await getArtifacts(id)
        if (alive) setItems(list)
      } catch (e) {
        const h = e as { status?: number }
        if (!alive) return
        setNote(
          h.status === 403
            ? '产物清单需要管理员权限（后端按角色拦的，不是前端藏起来的）。'
            : h.status === 401
              ? '需要登录才能看产物清单。'
              : '读产物清单失败。',
        )
      }
    })()
    return () => { alive = false }
  }, [])

  if (note) return <div className="pending-box">{note}</div>
  if (!items) return <div className="pending-box">正在读产物清单……</div>

  return (
    <div className="artifacts">
      {items.map((a) => (
        <div className="art" key={a.key}>
          <span className="ico"><Icon name={a.key === 'report' ? 'doc' : a.key.includes('red') ? 'list' : 'chart'} size={22} /></span>
          <span>
            <span className="n">{a.label}</span>
            <span className="m">
              {a.name}
              {a.size != null ? ` · ${humanSize(a.size)}` : ''}
            </span>
          </span>
          <span className="go"><a href={a.url} target="_blank" rel="noreferrer">打开</a></span>
        </div>
      ))}
    </div>
  )
}

/** 页边朱批 + 对勘分区 + 图册：都用 Batch 2 的真数据（后端 7223ba5 交付） */
function PeriodData({ period }: { period: string | null }) {
  const [col, setCol] = useState<CollationRow[] | null>(null)
  const [charts, setCharts] = useState<ChartRow[] | null>(null)
  const [note, setNote] = useState<string | null>(null)

  useEffect(() => {
    if (!period) return
    let alive = true
    setCol(null); setCharts(null); setNote(null)
    ;(async () => {
      try {
        const [c, ch] = await Promise.all([getCollation(period), getCharts(period)])
        if (!alive) return
        setCol(c); setCharts(ch)
      } catch (e) {
        const h = e as { status?: number }
        if (alive) setNote(h.status === 403 ? '这些数据需要管理员权限。'
          : h.status === 404 ? '这一期还没有对勘数据（可能尚未出稿）。'
            : '读对勘/图册失败。')
      }
    })()
    return () => { alive = false }
  }, [period])

  if (note) return <div className="pending-box">{note}</div>
  if (!col || !charts) return <div className="pending-box">正在读对勘与图册……</div>

  /* 页边朱批盯的是"要人补的地方"——manual 由后端标，前端只筛不算 */
  const manual = col.filter((r) => r.manual)
  /* 分区计数：让"这期报告有多少块"一眼可见（列表自己的条数，不是报告口径数字） */
  const bySection = col.reduce<Record<string, number>>((acc, r) => {
    acc[r.section] = (acc[r.section] ?? 0) + 1
    return acc
  }, {})

  return (
    <>
      <div className="body-grid" style={{ paddingTop: 22 }}>
        <div>
          <h2 style={{ fontSize: 19, display: 'flex', alignItems: 'center', gap: 10 }}>
            <Icon name="list" size={21} />对勘分区
            <span className="hint" style={{ fontWeight: 400, fontSize: 14 }}>
              （真数据：母版原文 ↔ 本期生成，共 {col.length} 处）
            </span>
          </h2>
          <div className="artifacts" style={{ marginTop: 12 }}>
            {Object.entries(bySection).map(([sec, n]) => (
              <div className="art" key={sec}>
                <span className="ico"><Icon name="doc" size={20} /></span>
                <span>
                  <span className="n">{sec}</span>
                  <span className="m">{n} 处</span>
                </span>
              </div>
            ))}
          </div>
        </div>

        {/* 页边朱批：待人工的那几处（本屏的"需要你拍板"） */}
        <div>
          <h2 style={{ fontSize: 19, display: 'flex', alignItems: 'center', gap: 10 }}>
            <Icon name="alert" size={20} />待你补 / 拍板
          </h2>
          {manual.length === 0 ? (
            <div className="pending-box" style={{ marginTop: 12 }}>
              这一期没有标「待人工」的地方。
            </div>
          ) : (
            <div style={{ marginTop: 12 }}>
              {manual.slice(0, 8).map((r) => (
                <div className="margin-note" key={r.section + r.loc}>
                  <div className="tag">朱批 · {r.loc}</div>
                  <p>
                    {(r.oldPreview || r.old) ? `原：${r.oldPreview ?? r.old}` : ''}
                    {(r.oldPreview || r.old) ? ' ' : ''}
                    {`→ 待填${r.source ? `（${r.source}）` : ''}`}
                  </p>
                </div>
              ))}
              {manual.length > 8 && (
                <p className="hint">还有 {manual.length - 8} 处待人工，完整清单见「红色件清单」。</p>
              )}
            </div>
          )}
        </div>
      </div>

      <section className="card" style={{ marginTop: 22, padding: '20px 22px' }}>
        <h2 style={{ fontSize: 19, display: 'flex', alignItems: 'center', gap: 10 }}>
          <Icon name="chart" size={21} />图册
          <span className="hint" style={{ fontWeight: 400, fontSize: 14 }}>
            （真数据：共 {charts.length} 张，本屏示前 24 张）
          </span>
        </h2>
        <div style={{
          marginTop: 12, display: 'grid', gap: 8,
          gridTemplateColumns: 'repeat(auto-fill,minmax(150px,1fr))',
        }}>
          {charts.slice(0, 24).map((c) => (
            <a key={c.url} href={c.url} target="_blank" rel="noreferrer"
               title={`${c.group} / ${c.name}`} style={{ textDecoration: 'none' }}>
              <img src={c.url} alt={c.name} loading="lazy"
                   style={{ width: '100%', border: '1px solid var(--line-2)',
                            borderRadius: 8, background: 'var(--panel)' }} />
              <span className="hint" style={{ fontSize: 12.5 }}>{c.group}</span>
            </a>
          ))}
        </div>
        <p className="hint" style={{ marginTop: 12 }}>
          看全部：<a href={`/p/${period}/charts`} target="_blank" rel="noreferrer">图册页（可搜索）</a>
        </p>
      </section>
    </>
  )
}

/** 读数带：真数据（GET /api/periods/{p}/facts，源与报告同款）。
    🔴 数字原样来自后端——这里只排版，不换算、不聚合、不四舍五入。 */
function FactsStrip({ period }: { period: string | null }) {
  const [f, setF] = useState<Facts | null>(null)
  const [note, setNote] = useState<string | null>(null)

  useEffect(() => {
    if (!period) return
    let alive = true
    setF(null); setNote(null)
    getFacts(period)
      .then((x) => { if (alive) setF(x) })
      .catch((e: { status?: number }) => {
        if (!alive) return
        setNote(
          e.status === 403 ? '读数需要管理员权限（后端按角色拦的）。'
            : e.status === 404 ? '这一期还没有概览数字（可能尚未出稿）。'
              : '读读数失败。',
        )
      })
    return () => { alive = false }
  }, [period])

  if (note) return <div className="pending-box">{note}</div>
  if (!f) return <div className="pending-box">正在读读数……</div>

  const x = f.facts
  const dir = (n: number) => (n > 0 ? `升 ${n}` : n < 0 ? `降 ${-n}` : '持平')
  const cards: { k: string; v: string; d: string; good?: boolean; bad?: boolean }[] = [
    {
      k: '国际排名', v: String(x.rank_intl_now),
      d: `比上期${dir(x.rank_intl_delta)}（上期 ${x.rank_intl_prev}）`,
      good: x.rank_intl_delta > 0, bad: x.rank_intl_delta < 0,
    },
    {
      k: '国内高校排名', v: String(x.rank_cn_uni_now),
      d: `比上期${dir(x.rank_cn_uni_delta)} · 国内机构 ${x.rank_cn_inst_now}（${dir(x.rank_cn_inst_delta)}）`,
      good: x.rank_cn_uni_delta > 0, bad: x.rank_cn_uni_delta < 0,
    },
    {
      k: '前 1% 学科', v: String(x.n_disc_1pct),
      d: x.any_1permille ? '已有学科进入 1‰' : '尚无学科进入 1‰',
    },
    {
      k: '顶尖论文', v: String(x.top_papers_now),
      d: `比上期增 ${x.top_papers_delta} 篇（上期 ${x.top_papers_prev}）`,
    },
    {
      k: '学科升降', v: `${x.rank_up} 升`,
      d: `降 ${x.rank_down} · 持平 ${x.rank_flat}`,
    },
  ]

  return (
    <>
      <div className="readouts">
        {cards.map((c) => (
          <div className="readout" key={c.k}>
            <div className="k">{c.k}</div>
            <div className="v" style={c.good ? { color: 'var(--ok)' } : c.bad ? { color: 'var(--bad)' } : undefined}>
              {c.v}
            </div>
            <div className="d">{c.d}</div>
          </div>
        ))}
      </div>
      <p className="hint" style={{ marginTop: 10 }}>
        数字体检：{f.assertions.total} 项核对
        {f.assertions.fail === 0 ? '全部通过' : `有 ${f.assertions.fail} 项不符 ❗`}
        {' · '}覆盖窗口 {x.coverage_window} · 上期 {x.prev_label}
        {f.missing.length > 0 ? ` · 缺：${f.missing.join('、')}` : ''}
      </p>
      <p className="hint" style={{ marginTop: 6 }}>
        最接近 1‰：{x.best_1permille.discipline} {x.best_1permille.prox_pct}%
        （上期 {x.best_1permille.prox_prev_pct}%）· 按顶尖论文数的三甲：
        {x.top3_by_top_papers.map(([d, n]) => `${d} ${n}`).join('、')}
      </p>
    </>
  )
}

export function Report({
  periods, current, onPick,
}: {
  periods: Period[]
  current: string | null
  onPick: (p: string) => void
}) {
  const row = periods.find((p) => p.period === current) ?? null

  return (
    <>
      <div className="report-head">
        <div>
          <div className="eyebrow">学科信息参考 · ESI 双月报告</div>
          <h1 className="display">
            {row?.label ?? '（选择期次）'}
            <small>
              目录名 {current ?? '—'} · 读数与覆盖窗口见下方读数带
            </small>
          </h1>
          <div className="rule" />

          {/* 读数带：真数据（后端 facts 接口已交付） */}
          <FactsStrip period={current} />
        </div>

        {/* 印记链：今天就有真数据 */}
        <Chain periods={periods} current={current} onPick={onPick} />
      </div>

      {/* 对勘分区 / 页边朱批 / 图册 —— Batch 2 的真数据 */}
      <PeriodData period={current} />

      <section className="card" style={{ marginTop: 26, padding: '20px 22px' }}>
        <h2 style={{ fontSize: 19, display: 'flex', alignItems: 'center', gap: 10 }}>
          <Icon name="doc" size={21} />本期产物
          <span className="hint" style={{ fontWeight: 400, fontSize: 14 }}>
            （真数据：来自最近一次生成任务的产物清单）
          </span>
        </h2>
        <Artifacts />
      </section>
    </>
  )
}
