/* 报告 · 成品展示台（只读）（取自静态稿 mockups/v2-工作台与报告.html 的报告屏；票 03 定为只读）
   定位：**只看不改的成品展示台**——按期次看全文 / 读数 / 图 / 期次印记链，四个下钻入口
   （红件清单、图册、对勘本、逐格溯源）。
   与 G 的翻书**分工**：翻书＝读正文（人的阅读）；这里＝看数据与出处（大表 / 朱批 / 溯源 / 印记链）。
   🔴 本屏无任何写动作（生成 / 签单 / 覆盖 / 重跑）：要改请到「出报告 · ④ 核验定稿」，
      未签发的期在这里只给一句下一步引导，不给写入口。

   🔴 诚实边界（项目红线：缺数据不填假数）：
     读数带 / 印记链 / 产物 / 对勘 / 朱批 / 图册 都已接真数据；
     哪一块没接上就整块写明"等什么"，不放占位数字、不假装有内容。
*/

import { useEffect, useState } from 'react'
import {
  getPeriodArtifacts, humanSize,
  type Artifact, type Period,
} from './api'
import { getCharts, getCollation, type ChartRow, type CollationRow } from './api-collation'
import { getFacts, type Facts } from './api-workbench'
import { Icon } from './icons'
import { APPROVAL_LABEL, approvalLabel, appHref, errorNote } from './lib/status'
import { collationSectionLabel } from './lib/labels'

/** 人工空位的来源说人话（票 14）：内部脚本名不直出面客 */
function humanSource(source?: string): string {
  if (source && source.includes('sentences.py')) return '正文里这一句'
  return source ?? ''
}

/** 期次印记链：签过＝朱印 / 签名失效＝金印 / 未签发＝墨线框。这是产品的原创资产，也是本屏的记忆点。 */
function Chain({
  periods, current,
}: {
  periods: Period[]
  current: string | null
}) {
  return (
    <aside className="chain">
      <h3>期次印记链</h3>
      <p className="cap">
        按时间从左到右。已签发是朱印，签发已失效是金印，未签发是墨线框。
        <br />
        （期号与月份来自后端；换期次用顶栏的期次选择。）
      </p>
      <div className="seals">
        {periods.map((p) => {
          const cls = p.status === 'signed' ? 'signed' : p.status === 'stale' ? 'stale' : 'unsigned'
          const isNow = p.period === current
          return (
            <span
              key={p.period}
              className="sealbox"
              aria-current={isNow}
            >
              <span className="now-tag">{isNow ? '本期' : ''}</span>
              <span className={`seal ${cls} ${isNow ? 'now' : ''}`}>{p.period}</span>
              <span className="lbl">{p.label}</span>
            </span>
          )
        })}
      </div>
      <div className="legend">
        <span><i className="bg-zhu" />{APPROVAL_LABEL.signed}</span>
        <span><i className="sw-gold" />{APPROVAL_LABEL.stale}</span>
        <span><i className="sw-line" />{APPROVAL_LABEL.unsigned}</span>
      </div>
    </aside>
  )
}

/** 产物卡：始终读取当前选择期次的产物清单。 */
function Artifacts({ period, guest, approvalStatus, refreshToken }: {
  period: string | null
  guest?: boolean
  approvalStatus: string
  refreshToken: number
}) {
  const isGuest = !!guest
  const [result, setResult] = useState<{
    period: string | null
    guest: boolean
    refreshToken: number
    items: Artifact[] | null
    note: string | null
  }>({ period: null, guest: false, refreshToken: -1, items: null, note: null })

  useEffect(() => {
    let alive = true
    if (isGuest || !period) return () => { alive = false }

    getPeriodArtifacts(period).then((items) => {
      if (alive) setResult({ period, guest: isGuest, refreshToken, items, note: null })
    }).catch((e: unknown) => {
      if (!alive) return
      setResult({ period, guest: isGuest, refreshToken, items: null,
                  note: errorNote(e, '产物清单') })
    })
    return () => { alive = false }
  }, [period, isGuest, refreshToken])

  if (isGuest) return null
  if (!period) return <div className="pending-box">先选一期，再查看这一期的产物。</div>
  const current = result.period === period && result.guest === isGuest && result.refreshToken === refreshToken ? result : null
  if (current?.note) return <div className="pending-box">{current.note}</div>
  if (!current?.items) return <div className="pending-box">正在读取这一期的产物清单……</div>
  if (current.items.length === 0) return <div className="pending-box">这一期目前没有可用产物。</div>

  return (
    <div className="artifacts art-grid">
      {current.items.map((a) => {
        const blocked = a.key === 'report' && approvalStatus !== 'signed'
        return (
          <div className="art" key={a.key}>
            <span className="ico"><Icon name={a.key === 'report' ? 'doc' : a.key.includes('red') ? 'list' : 'chart'} size={22} /></span>
            {blocked ? (
              <span>
                <span className="n">{a.key === 'diagnosis' ? '校验说明' : a.label}</span>
                <span className="m">
                  {a.name}
                  {a.size != null ? ` · ${humanSize(a.size)}` : ''}
                  {' · 未签发，暂不能下载'}
                </span>
              </span>
            ) : (
              <a className="art-open" href={a.url} target="_blank" rel="noreferrer">
                <span className="n">{a.key === 'diagnosis' ? '校验说明' : a.label}</span>
                <span className="m">
                  {a.name}
                  {a.size != null ? ` · ${humanSize(a.size)}` : ''}
                </span>
              </a>
            )}
          </div>
        )
      })}
    </div>
  )
}

/** 页边朱批 + 对勘分区 + 图册：都用 Batch 2 的真数据（后端 7223ba5 交付） */
function PeriodData({ period, canSeeAdminBits }: { period: string | null; canSeeAdminBits: boolean }) {
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
        if (alive) setNote(errorNote(e, '对勘数据'))
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
      <div className="pt-22">
        <div>
          <h2 className="h-sec">
            <Icon name="list" size={21} />对勘 · 红色件
            <span className="hint hint-num">
              共 {col.length} 处 · 待人工 {manual.length} 处
            </span>
          </h2>
          {/* 下钻入口收成一行小链接（2026-10-17 冗余收敛稿③：三卡＝第二套菜单，退化为行内链接）。
              2026-10-20：红色件清单/逐格溯源对操作员只读开放；下载口仍只给管理员。 */}
          <p className="hint rc-links">
            逐格核对：
            <a href={period ? appHref('reading', period) : '/app/?view=reading'}>对勘本（正文级对照）</a>
            {canSeeAdminBits && (
              <> · <a href={period ? appHref('red', period) : '/app/?view=red'}>红色件清单（定稿依据）</a></>
            )}
            {canSeeAdminBits && (
              <> · <a href={period ? appHref('trace', period) : '/app/?view=trace'}>逐格溯源</a></>
            )}
          </p>
          {/* 章节直达收进折叠：对勘本自己就能换分组，11 张卡不再占屏（票 14） */}
          <details className="fold">
            <summary>按章节直达（{Object.keys(bySection).length} 章）</summary>
            <div className="fold-inner">
              <div className="rc-chips">
                {Object.entries(bySection).map(([sec, n]) => (
                  <a className="rc-chip" key={sec}
                     href={`/app/?view=reading&period=${encodeURIComponent(period ?? '')}&section=${encodeURIComponent(sec)}`}>
                    {collationSectionLabel(sec)} <b>{n}</b>
                  </a>
                ))}
              </div>
            </div>
          </details>
        </div>

        {/* 页边朱批：待人工的那几处——本屏只读，逐条只做**下钻**（落到④对应空位），
            不在报告屏里改；真正的写动作在「出报告 · ④ 核验定稿」。 */}
        <div>
          <h2 className="h-sec">
            <Icon name="alert" size={20} />待人工的地方
            {manual.length > 0 && (
              <a className="hint ml-auto ink-zhu fw-650 no-underline"
                 href={period ? appHref('review', period) : '/app/?view=review'}>
                去「出报告 · 核验定稿」逐项处理（{manual.length} 处）→
              </a>
            )}
          </h2>
          {manual.length === 0 ? (
            <div className="pending-box mt-12">
              这一期没有标「待人工」的地方。
            </div>
          ) : (
            <div className="mt-12">
              {manual.slice(0, 8).map((r) => (
                <div className="margin-note" key={r.section + r.loc}>
                  <div className="tag">朱批 · {r.loc}</div>
                  {(r.oldPreview || r.old) && <p>原：{r.oldPreview ?? r.old}</p>}
                  <p className="mn-src">{r.source ? `待人工：${humanSource(r.source)}` : '待人工'}</p>
                  <div className="mn-acts">
                    <a className="btn"
                       href={`/app/?view=review${period ? `&period=${encodeURIComponent(period)}` : ''}${r.loc ? `&focus=${encodeURIComponent(r.loc)}` : ''}`}>
                      去核验定稿 →
                    </a>
                  </div>
                </div>
              ))}
              {manual.length > 8 && (
                <p className="hint">
                  另 {manual.length - 8} 处
                  {canSeeAdminBits ? '见图册「红色件清单」。' : '去「出报告 · 核验定稿」处理。'}
                </p>
              )}
            </div>
          )}
        </div>
      </div>

      <section className="card mt-22 pad-card">
        <h2 className="h-sec">
          <Icon name="chart" size={21} />图册
          <span className="hint hint-num">
            共 {charts.length} 张
          </span>
        </h2>
        {/* 图册全量入口（P0-4）：以前这里指老站 /p/<期次>/charts，现已改指新站自己的图册页 */}
        <a className="entry mt-12" 
           href={period ? appHref('charts', period) : '/app/?view=charts'}>
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
    曲线与点都是后端给的数；**数字隔期标注、本期必标**——45 期按每期 23px 排开，
    一屏放得下（rick 定 2026-09-25：隔期标，不滚动）。轴上只标真实值（0 / 序列最大值）。 */
function TrendCard({ trend, period }: { trend: Record<string, number>; period: string | null }) {
  const pts = Object.entries(trend).sort((a, b) => a[0].localeCompare(b[0]))
  if (pts.length < 2) return null
  const max = Math.max(...pts.map(([, v]) => v))
  /* 每期 23px：隔期标的数字间距 46px，一屏宽（约 1100px）全放下，不用横向拉 */
  const STEP = 23, H = 236, L = 58, R = 24, T = 28, B = 42
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
          <span className="hint">按双月期次 · 单位 篇</span>
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
          {pts.map(([k, v], i) => ((i % 2 === 0 || i === ci) ? (
            <text key={k} className="tr-val" x={x(i)} y={y(v) - 7} textAnchor="middle">{v}</text>
          ) : null))}
          {nowEntry && <circle className="tr-dot" cx={x(ci)} cy={y(cv)} r="4" />}
          <text className="tr-tick" x={L} y={H - 8}>{fmtP(pts[0][0])}</text>
          <text className="tr-tick" x={W - R} y={H - 8} textAnchor="end">{fmtP(pts[pts.length - 1][0])}</text>
        </svg>
      </div>
    </div>
  )
}

/** 读数带：真数据（GET /api/periods/{p}/facts，源与报告同款）。
    🔴 数字原样来自后端——这里只排版，不换算、不聚合、不四舍五入。
    趋势图不在这里画：它要占满整页宽（见 Report 里的 TrendCard），数据经 onFacts 上交。 */
export function FactsStrip({ period, onFacts }: {
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
      .catch((e) => {
        if (!alive) return
        setNote(errorNote(e, '概览数字'))
      })
    return () => { alive = false }
  }, [period, onFacts])

  if (note) {
    return (
      <div className="pending-box">
        {note}
        {note.includes('可能尚未出稿') && period && (
          <> 本屏只展示成品；这一期还没出稿，去{' '}
             <a href={`/app/?period=${encodeURIComponent(period)}`}>「出报告」</a>看走到哪一步。</>
        )}
        {!note.includes('管理员权限') && (
          <> <button className="btn btn-xs" 
                     onClick={() => location.reload()}>重新读取</button></>
        )}
      </div>
    )
  }
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
    </>
  )
}

/** 签发态 · 只读声明（票 03）：报告屏只展示成品，不给生成 / 签单 / 覆盖 / 重跑任何入口；
    未签发的期在这里给一句「去④核验定稿」引导，写动作只在「出报告 · ④ 核验定稿」发生。 */
function ReportStatus({ status, period }: { status: string; period: string | null }) {
  const signed = status === 'signed'
  const stale = status === 'stale'
  const href = period ? appHref('review', period) : '/app/?view=review'
  return (
    <div className={`rep-status${signed ? ' ok' : stale ? ' warn' : ''}`} role="note">
      <span className="rep-flag">
        <Icon name={signed ? 'check' : 'alert'} size={15} />{approvalLabel(status)}
      </span>
      <span className="rep-note">
        {signed
          ? '这一版已签发：报告屏只读展示，内容不再改动。'
          : stale
            ? '这一版内容变过、签发已失效——要改请到「出报告 · 核验定稿」。'
            : '这一版还没签发——要改请到「出报告 · 核验定稿」。'}
      </span>
      {!signed && <a className="rep-go" href={href}>去核验定稿 →</a>}
    </div>
  )
}

export function Report({
  periods, current, guest, refreshToken = 0, canSeeAdminBits = true,
}: {
  periods: Period[]
  current: string | null
  guest?: boolean
  refreshToken?: number
  /** 2026-10-20：操作员也看红件清单/逐格溯源（只读证据面）；写动作的真门仍在后端。 */
  canSeeAdminBits?: boolean
}) {
  const row = periods.find((p) => p.period === current) ?? null
  /* 趋势图要占满整页宽：facts 由 FactsStrip 取回后交上来（读数带仍在左列） */
  const [facts, setFacts] = useState<Facts | null>(null)

  return (
    <>
      <div className="report-head">
        <div>
          <h1 className="display">
            {row?.label ?? '（选择期次）'}
            <small>
              学科信息参考 · ESI 双月报告 ｜ 成品展示台（只读）
            </small>
          </h1>
          <div className="rule" />

          {/* 签发态 + 只读声明：本屏只看不改；未签发只给「去④核验定稿」一句引导 */}
          <ReportStatus status={row?.status ?? 'unsigned'} period={current} />

          {/* 读数带：真数据（后端 facts 接口已交付） */}
          <FactsStrip period={current} onFacts={setFacts} />
        </div>

        {/* 印记链：今天就有真数据 */}
          <Chain periods={periods} current={current} />
      </div>

      {/* 顶尖论文增长轨迹——全页宽（rick 定 2026-09-25）：45 期每期标数值，
          「本期」用后端 facts.period（选 _复现 期次时 URL 期次与序列键对不上）。 */}
      {facts?.trend && Object.keys(facts.trend).length > 1 && (
        <TrendCard trend={facts.trend} period={facts.period || current} />
      )}

      {/* 对勘分区 / 页边朱批 / 图册 —— Batch 2 的真数据 */}
      <PeriodData period={current} canSeeAdminBits={canSeeAdminBits} />

      <section className="card mt-26 pad-card">
        <h2 className="h-sec">
          <Icon name="doc" size={21} />本期产物
        </h2>
        <Artifacts period={current} guest={guest} approvalStatus={row?.status ?? 'unsigned'} refreshToken={refreshToken} />
      </section>
    </>
  )
}
