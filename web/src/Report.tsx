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
function Artifacts({ guest }: { guest?: boolean }) {
  const [items, setItems] = useState<Artifact[] | null>(null)
  const [note, setNote] = useState<string | null>(null)

  /* 角色的确定晚于首屏（App 先探活再取 /api/me）：guest 由 true 变 false 时
     这个 effect 必须重跑，否则管理员的产物清单永远停在"正在读……"。 */
  useEffect(() => {
    if (guest) return   // 游客不请求（后端也会拒）
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
  }, [guest])

  if (guest) return null
  if (note) return <div className="pending-box">{note}</div>
  if (!items) return <div className="pending-box">正在读产物清单……</div>

  return (
    <div className="artifacts art-grid">
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
        /* 全量对勘：分区计数 / 待人工清单要的是全部（716 处量级），
           不是分页默认的 50 行——否则分区只出现前几组、计数也少。 */
        const [c, ch] = await Promise.all([getCollation(period, true), getCharts(period)])
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
          <div className="sections-grid">
            {Object.entries(bySection).map(([sec, n]) => (
              <a className="art" key={sec} style={{ textDecoration: 'none', color: 'inherit' }}
                 href={`/app/?view=reading&period=${encodeURIComponent(period ?? '')}&section=${encodeURIComponent(sec)}`}>
                <span className="ico"><Icon name="doc" size={20} /></span>
                <span>
                  <span className="n">{sec}</span>
                  <span className="m">{n} 处 · 点开逐句对照</span>
                </span>
              </a>
            ))}
          </div>
          {/* 对勘本入口卡（P0-2）：正文级阅读视图 */}
          <a className="entry" style={{ marginTop: 12 }}
             href={`/app/?view=reading${period ? `&period=${encodeURIComponent(period)}` : ''}`}>
            <span>
              <span className="t">打开对勘本（正文级对照）</span>
              <span className="d">左分组 / 中改动卡 / 右校记 · 可搜、可只看待人工、← → 换分组</span>
            </span>
            <span className="go">→</span>
          </a>
          {/* 红件全量清单入口（P0-3）：本屏只给入口，全量表在 ?view=red */}
          <a className="entry" style={{ marginTop: 12 }}
             href={`/app/?view=red${period ? `&period=${encodeURIComponent(period)}` : ''}`}>
            <span>
              <span className="t">红色件清单</span>
              <span className="d">签单依据：逐格列出「改了什么、来自哪里」，可搜索、可下载 Markdown</span>
            </span>
            <span className="go">→</span>
          </a>
          {/* 逐格溯源入口（P1）：报告里的值 ↔ 台账现场重读 */}
          <a className="entry" style={{ marginTop: 12 }}
             href={`/app/?view=trace${period ? `&period=${encodeURIComponent(period)}` : ''}`}>
            <span>
              <span className="t">逐格溯源</span>
              <span className="d">报告里每个数字 ↔ 台账现场重读的值并排对照，写清来源表与「怎么来的」</span>
            </span>
            <span className="go">→</span>
          </a>
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
            （真数据：共 {charts.length} 张）
          </span>
        </h2>
        <p className="hint" style={{ marginTop: 8 }}>
          本期报告写入的全部配图——按学科平铺、可按图名搜，点开看原图。
        </p>
        {/* 图册全量入口（P0-4）：以前这里指老站 /p/<期次>/charts，现已改指新站自己的图册页 */}
        <a className="entry" style={{ marginTop: 12 }}
           href={`/app/?view=charts${period ? `&period=${encodeURIComponent(period)}` : ''}`}>
          <span>
            <span className="t">打开图册</span>
            <span className="d">{charts.length} 张 · 按学科分组 · 可搜索</span>
          </span>
          <span className="go">→</span>
        </a>
      </section>
    </>
  )
}

/** 顶尖论文增长轨迹（契约 #19 的 trend 序列；借「学科分析平台」那版的版式）。
    曲线与点都是后端给的数；**每期数值直接标在点上**——45 期按固定绘制宽度横向排开
    （卡片装不下就横向拉动），不缩成一团（rick 定 2026-09-25）。
    轴上只标**真实值**（0 / 序列最大值），不另造刻度数。 */
function TrendCard({ trend, period }: { trend: Record<string, number>; period: string | null }) {
  const pts = Object.entries(trend).sort((a, b) => a[0].localeCompare(b[0]))
  if (pts.length < 2) return null
  const max = Math.max(...pts.map(([, v]) => v))
  /* 每期固定 30px 绘制宽度：45 期全标数字也不挤（窄屏/小屏横向拉动看） */
  const STEP = 30, H = 236, L = 58, R = 24, T = 28, B = 42
  const W = L + (pts.length - 1) * STEP + R
  const ih = H - T - B
  const x = (i: number) => L + i * STEP
  const y = (v: number) => T + ih - (v / (max || 1)) * ih
  const line = pts.map(([, v], i) => `${i ? 'L' : 'M'}${x(i).toFixed(1)} ${y(v).toFixed(1)}`).join(' ')
  const area = `${line} L${x(pts.length - 1).toFixed(1)} ${(T + ih).toFixed(1)} L${L} ${(T + ih).toFixed(1)} Z`
  /* 「本期」只认传入的期次（FactsStrip 用的是后端 facts.period）；
     序列里找不到就不标——不拿首点冒充本期。 */
  const ci = pts.findIndex(([k]) => k === period)
  const nowEntry = ci >= 0 ? pts[ci] : null
  const cv = nowEntry?.[1] ?? 0
  const fmtP = (k: string) => `${k.slice(0, 4)}.${k.slice(4)}`

  return (
    <div className="tr-wrap">
      <div className="tr-head">
        <div>
          <b>顶尖论文增长轨迹</b>
          <span className="hint">按双月期次 · 单位 篇（{pts.length} 期，{fmtP(pts[0][0])}–{fmtP(pts[pts.length - 1][0])}）</span>
        </div>
        {nowEntry && <div className="tr-now"><b>{cv}</b><span>本期 · {fmtP(pts[ci][0])}</span></div>}
      </div>
      <div className="tr-scroll">
        <svg width={W} height={H} viewBox={`0 0 ${W} ${H}`} className="tr-svg" role="img"
             aria-label={nowEntry
               ? `顶尖论文历期增长趋势图：${pts.length} 期，本期 ${cv} 篇`
               : `顶尖论文历期增长趋势图：${pts.length} 期（本期不在序列中）`}>
          {[0, 0.25, 0.5, 0.75, 1].map((q) => (
            <line key={q} className="tr-grid" x1={L} x2={W - R} y1={T + ih * (1 - q)} y2={T + ih * (1 - q)} />
          ))}
          <text className="tr-tick" x={L - 10} y={T + 4} textAnchor="end">{max}</text>
          <text className="tr-tick" x={L - 10} y={T + ih + 4} textAnchor="end">0</text>
          <path className="tr-area" d={area} />
          <path className="tr-line" d={line} />
          {pts.map(([k, v], i) => (
            <text key={k} className="tr-val" x={x(i)} y={y(v) - 7} textAnchor="middle">{v}</text>
          ))}
          {nowEntry && <circle className="tr-dot" cx={x(ci)} cy={y(cv)} r="4" />}
          <text className="tr-tick" x={L} y={H - 8}>{fmtP(pts[0][0])}</text>
          <text className="tr-tick" x={W - R} y={H - 8} textAnchor="end">{fmtP(pts[pts.length - 1][0])}</text>
        </svg>
      </div>
      <p className="hint">每个点上的数字都是台账派生的历期值，不掺预测值；图比屏宽时可横向拉动。</p>
    </div>
  )
}

/** 读数带：真数据（GET /api/periods/{p}/facts，源与报告同款）。
    🔴 数字原样来自后端——这里只排版，不换算、不聚合、不四舍五入。
    趋势图不在这里画：它要占满整页宽（见 Report 里的 TrendCard），数据经 onFacts 上交。 */
function FactsStrip({ period, onFacts }: {
  period: string | null
  onFacts?: (f: Facts | null) => void
}) {
  const [f, setF] = useState<Facts | null>(null)
  const [note, setNote] = useState<string | null>(null)

  useEffect(() => {
    if (!period) return
    let alive = true
    setF(null); setNote(null)
    onFacts?.(null)
    getFacts(period)
      .then((x) => { if (alive) { setF(x); onFacts?.(x) } })
      .catch((e: { status?: number }) => {
        if (!alive) return
        setNote(
          e.status === 403 ? '读数需要管理员权限（后端按角色拦的）。'
            : e.status === 404 ? '这一期还没有概览数字（可能尚未出稿）。'
              : '读读数失败。',
        )
      })
    return () => { alive = false }
  }, [period, onFacts])

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
  periods, current, onPick, guest,
}: {
  periods: Period[]
  current: string | null
  onPick: (p: string) => void
  guest?: boolean
}) {
  const row = periods.find((p) => p.period === current) ?? null
  /* 趋势图要占满整页宽：facts 由 FactsStrip 取回后交上来（读数带仍在左列） */
  const [facts, setFacts] = useState<Facts | null>(null)

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
          <FactsStrip period={current} onFacts={setFacts} />
        </div>

        {/* 印记链：今天就有真数据 */}
        <Chain periods={periods} current={current} onPick={onPick} />
      </div>

      {/* 顶尖论文增长轨迹——全页宽（rick 定 2026-09-25）：45 期每期标数值，
          「本期」用后端 facts.period（选 _复现 期次时 URL 期次与序列键对不上）。 */}
      {facts?.trend && Object.keys(facts.trend).length > 1 && (
        <TrendCard trend={facts.trend} period={facts.period || current} />
      )}

      {/* 对勘分区 / 页边朱批 / 图册 —— Batch 2 的真数据 */}
      <PeriodData period={current} />

      <section className="card" style={{ marginTop: 26, padding: '20px 22px' }}>
        <h2 style={{ fontSize: 19, display: 'flex', alignItems: 'center', gap: 10 }}>
          <Icon name="doc" size={21} />本期产物
          <span className="hint" style={{ fontWeight: 400, fontSize: 14 }}>
            （真数据：来自最近一次生成任务的产物清单）
          </span>
        </h2>
        <Artifacts guest={guest} />
      </section>
    </>
  )
}
