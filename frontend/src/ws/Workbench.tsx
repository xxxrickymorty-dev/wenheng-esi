/* 生成台（工作台）——工具面。
   v2 极致低密（2026-10-24 rick 过审）：一行期次身份＋四节点流程图＋一行主动作，
   状态全部长在图上（状态一约 70 字）；故事条与运行回放迁往「可视化工作流」屏。
   设计稿：mockups/生成台-重设计-静态稿v2-极致低密-20261024.html；状态规格见 web/UX-生成台.md。 */

import type { ApiError, ArchiveData, Me, Period, PeriodDetail } from './api'
import { getArchive } from './api'
import { useEffect, useState } from 'react'
import { getForecastBoard, getWaterLevel, type ForecastBoardRow, type ForecastChoiceEntry, type WaterRow } from './api-forecast'
import { ConfirmButton } from './ConfirmButton'
import { Info } from './Info'
import { approvalLabel } from './lib/status'
import { Icon } from './icons'
import { failureCopy, isTerminal, type Workbench as WB, type WBState } from './wb'
import type { ActivityState, Run } from './hooks/useJobRun'

/** 五个模型的一句话说明（界面上"帮馆员选"的文案；预测台也用同一份，改一处两边一致） */
export const MODEL_DESC: Record<string, string> = {
  'Holt趋势模型': '只抓长期趋势、不管季节。适合稳定上升/下降的学科，外推最直接。',
  '阻尼Holt模型': '趋势会「减速」——越往前推越保守。适合增长在放缓的学科。',
  '季节性ETS模型': '抓「6 期一轮」的双月节律。适合受学年与发布节奏影响的指标。',
  'SARIMA模型': '趋势 + 季节都管，参数在最初 30 期按 AIC 选定后固定。通用、稳。',
  '经验贝叶斯状态空间模型': '把趋势与季节当「状态」逐期更新。对噪声大的序列更稳健。',
}

/** 进度连接状态的一句话（只在跑任务时显示——任务完成后不再复读状态）。 */
function runConnLabel(run: Run): string {
  return run.connection === 'live' ? '进度自动刷新'
    : run.connection === 'snapshot' ? '正在读取任务进度'
      : run.connection === 'reconnecting' ? '连接中断，正在恢复进度'
        : '暂时连不上服务，页面会继续更新进度'
}

function Banners({ wb, err, healthy, onRerun, canRerun, period, approvalStatus }: {
  wb: WB
  err: ApiError | null
  healthy: boolean
  onRerun: () => void
  canRerun: boolean
  period: string | null
  approvalStatus: string
}) {
  if (wb.state === 'warned') {
    return (
      <div className="banner warn">
        <span className="ico"><Icon name="alert" size={22} /></span>
        <span>
          <b className="title">已生成，有校验提醒</b>
          <ul>
            <li>本次校验有未通过项，但系统仍生成了提醒初稿。</li>
            <li>任务完成与报告是否合格、是否签发是两回事。</li>
            <li>具体未通过项与核对说明，请在报告页本期产物中打开“校验说明”。</li>
            <li>本期签单状态：{approvalLabel(approvalStatus)}。</li>
            {approvalStatus !== 'signed' && <li>管理员当前不能下载未签发初稿。</li>}
          </ul>
          <span className="acts">
            <a className="btn" href={`/app/?view=report${period ? `&period=${encodeURIComponent(period)}` : ''}`}><Icon name="doc" size={19} />查看报告与校验说明</a>
            <a className="btn" href={`/app/?view=review${period ? `&period=${encodeURIComponent(period)}` : ''}`}><Icon name="seal" size={19} />查看审核状态</a>
          </span>
        </span>
      </div>
    )
  }
  if (wb.state === 'fail-ledger' || wb.state === 'fail-other' || wb.state === 'stalled') {
    const c = wb.state === 'stalled'
      ? { title: '已停住', lines: ['已有一段时间没有进展，可以重跑试试。', '上一版报告仍然有效。'] }
      : failureCopy(err, healthy)
    return (
      <>
        <div className="banner bad">
          <span className="ico"><Icon name="alert" size={22} /></span>
          <span>
            <b className="title">{c.title}</b>
            <ul>{c.lines.map((l, i) => <li key={i}>{l}</li>)}</ul>
            <span className="acts">
              <button className="btn" onClick={onRerun} disabled={!canRerun}><Icon name="refresh" size={19} />重新生成</button>
              {!healthy && (
                <button className="btn" onClick={() => location.reload()}><Icon name="refresh" size={19} />重新检查服务</button>
              )}
            </span>
          </span>
        </div>
        <div className="banner warn">
          <span className="ico"><Icon name="clock" size={22} /></span>
          <span><b className="title">上一版报告仍然有效</b>
            <span>本次失败没有动它；旧稿会先被撤下、可回滚，可追溯。</span></span>
        </div>
      </>
    )
  }
  return null
}

/* ---------- v2 流程图：四节点（取数/生成/审计/签发）＋连接符（静态稿 v2 同构） ---------- */

type NodeSt = 'done' | 'now' | 'bad' | 'todo'

function FlowNode({ k, st, v, n }: { k: string; st: NodeSt; v: string; n?: string }) {
  return (
    <div className={`wb2-node ${st}`}>
      <span className="k">{k}</span>
      <span className="v">{v}</span>
      {n && <span className="n">{n}</span>}
      <span className="mark" aria-hidden="true">
        {st === 'done' ? '✓' : st === 'bad' ? '✕' : st === 'now' ? '●' : ''}
      </span>
    </div>
  )
}

function FlowLink({ st }: { st: 'ok' | 'bad' | 'todo' }) {
  return (
    <span className={`wb2-link ${st}`} aria-hidden="true">
      {st === 'ok' ? '✓' : st === 'bad' ? '✕' : '·'}
    </span>
  )
}

/** 差值只留两位小数、去尾零（接近度是百分数点值，两期相减会有浮点尾巴） */
function fmtDelta(n: number): string {
  return Number.isInteger(n) ? String(n) : String(Math.round(n * 100) / 100)
}

/** 「较上一期」差值小签（本期读数，2026-10-24）：箭头＋差值；上一期没数据时整枚不渲染。
    semantic＝进入数（升＝可喜、降＝要留意），走绿/红；其余差值中性色。 */
function DeltaChip({ diff, semantic }: { diff: number | null; semantic?: boolean }) {
  if (diff == null) return null
  const cls = semantic ? (diff > 0 ? 'up' : diff < 0 ? 'down' : '') : ''
  const txt = diff > 0 ? `↑ ${fmtDelta(diff)}` : diff < 0 ? `↓ ${fmtDelta(-diff)}` : '持平'
  return <span className={cls ? `d delta ${cls}` : 'd delta'}>{txt} · 较上一期</span>
}

/** 审计行计数（数字只来自运行档案，不换算） */
function countAudit(a: ArchiveData) {
  const rows = a.audit?.rows ?? []
  return {
    total: rows.length,
    pass: rows.filter(r => r.status === 'pass').length,
    review: rows.filter(r => r.status === 'review').length,
    fail: rows.filter(r => r.status === 'fail').length,
  }
}

export function Workbench({
  period, me, wb, err, healthy, run, approvalStatus, activityState,
  actionLockReason, activeRun, actionsLocked, submitting, onGenerate,
  periods, forecastChoice, detail,
  forecastAppliedStale, forecastAppliedDiffs, autoConfirmRerun,
}: {
  period: string | null
  me: Me | null
  wb: WB
  err: ApiError | null
  healthy: boolean
  run?: Run | null
  approvalStatus: string
  activityState: ActivityState
  actionLockReason: string | null
  activeRun: boolean
  actionsLocked: boolean
  submitting: boolean
  onGenerate: () => void
  periods: Period[]
  forecastChoice: ForecastChoiceEntry | null
  /** 单期详情（取数/并入/出稿三步与取数摘要）；故事条用它在不读档案时也能说真话 */
  detail: PeriodDetail | null
  /** 已保存的模型选择 ≠ 上次出稿实际用的选择（报告还是旧的）；无出稿快照时恒 false */
  forecastAppliedStale: boolean
  /** 提示条里列的改动（「总被引：免疫学 → SARIMA模型」这类人话） */
  forecastAppliedDiffs: string[]
  /** 从预测台「回出报告并重新生成」来（?rerun=1）：重跑确认态直接打开一次 */
  autoConfirmRerun: boolean
}) {
  const isAdmin = me?.role === 'admin'
  /* 水位卡读数＝预测看板真值（接近度/阈值），只透传不换算（2026-10-17 绿蓝融合 U2）。
     只在已出稿后取——没出过稿的期次没有看板文件，取了只会白报 404。 */
  const [board, setBoard] = useState<ForecastBoardRow[]>([])
  const [water, setWater] = useState<WaterRow[]>([])
  const generated = wb.steps[2]?.on === true
  useEffect(() => {
    if (!period || !generated) { setBoard([]); setWater([]); return }
    let alive = true
    // 先读学科矩阵（matrix.json 的云大列，202609 起都有）；没有再退回预测看板。
    getWaterLevel(period)
      .then((w) => {
        if (!alive) return
        if (w.rows.length) { setWater(w.rows); setBoard([]); return }
        setWater([])
        return getForecastBoard(period).then((b) => {
          if (alive) setBoard(Object.values(b.routes ?? {})[0] ?? [])
        })
      })
      .catch(() => { if (alive) { setWater([]); setBoard([]) } })
    return () => { alive = false }
  }, [period, generated])
  /* 审计节点读数：运行档案（v2 把原故事条里的一枚数搬上节点；回放动画在「可视化工作流」屏） */
  const [audit, setAudit] = useState<{ total: number; pass: number; review: number; fail: number } | null>(null)
  const canReadArchive = !!detail?.steps?.generate
  useEffect(() => {
    if (!period || !canReadArchive) { setAudit(null); return }
    let alive = true
    setAudit(null)
    getArchive(period)
      .then(a => { if (alive) setAudit(countAudit(a)) })
      .catch(() => { if (alive) setAudit(null) })
    return () => { alive = false }
  }, [period, canReadArchive])
  /* 2026-10-12：出报告对操作员也开放（后端 POST /api/jobs 已开）；下载数据/工具折仍只管理员。 */
  const canRun = !!me
  const canGenerate = canRun && period != null && /^\d{6}$/.test(period) && !actionsLocked && !activeRun && !submitting
    && (!run || isTerminal(run.status ?? undefined))
  const hasGenerateAction = wb.focusAction === 'generate' || wb.focusAction === 'rerun'
  /* 任务在跑（含进度还没接上的空窗）：故事条走「实时」，不放回放 */
  const live = (!!run && !isTerminal(run.status ?? undefined)) || wb.state === 'running'
  /** 水尺行：矩阵优先（全 22 学科），预测看板兜底（旧期次没有 matrix.json 时）。
      「潜力学科」看的是还没进前 1% 的——已进入的排在最前会把水尺刷成 8 根满格。 */
  const gaugePool: WaterRow[] = water.length
    ? water
    : board.map((r) => ({ subject: r.subject, prox: r.prox, state: 'unknown' as const }))
  const gaugePotential = gaugePool.filter((r) => r.state !== 'in')
  const gaugeRows = gaugePotential.length ? gaugePotential : gaugePool

  /* ── v2 四节点：空·待生成·生成中·已出稿·失败·已签发，同一张图（状态长在图上）── */
  const acqSum = detail?.acquisition
  const merged = acqSum?.copy === 'merged'
  const av = acqSum?.verified, ae = acqSum?.expected
  const running = live || wb.state === 'running'
  const lastAt = detail?.lastJob?.created_at
    ? detail.lastJob.created_at.slice(5, 16).replace('T', ' ') : ''
  const fetchNode: { st: NodeSt; v: string; n?: string } =
    wb.state === 'fail-ledger' ? { st: 'bad', v: '✕ 数据没齐', n: '解析拦停' }
      : merged ? { st: 'done', v: av != null && ae != null ? `${av} / ${ae}` : '已并入', n: '已并入台账' }
        : acqSum?.started || detail?.steps?.fetch ? { st: 'now', v: '未并入', n: '在取数台' }
          : { st: 'now', v: '未开始' }
  const genNode: { st: NodeSt; v: string; n?: string } = running
    ? { st: 'now', v: '⟳ 生成中', n: run?.last ?? '正在跑' }
    : wb.state === 'fail-other' || wb.state === 'stalled' ? { st: 'bad', v: '✕ 没出稿', n: '上一版仍有效' }
      : wb.state === 'fail-ledger' ? { st: 'todo', v: '—' }
        : generated ? { st: 'done', v: '已出稿', n: lastAt || undefined }
          : wb.state === 'ready' ? { st: 'now', v: '待生成', n: '约 3 分钟' }
            : { st: 'todo', v: '—' }
  const auditNode: { st: NodeSt; v: string; n?: string } = !generated && !running
    ? { st: 'todo', v: '—' }
    : audit
      ? (audit.fail
          ? { st: 'bad', v: `✕ ${audit.fail} 项不过`, n: '看校验说明' }
          : { st: 'done', v: `${audit.pass} 项过`, n: audit.review ? `${audit.review} 项待签看` : '机器断言全过' })
      : { st: 'done', v: '已审计', n: '读数在运行档案' }
  const signNode: { st: NodeSt; v: string; n?: string } =
    approvalStatus === 'signed' ? { st: 'done', v: '已签发', n: '报告可下载' }
      : approvalStatus === 'stale' ? { st: 'now', v: '待重签', n: '内容改过，签名失效' }
        : generated && !running ? { st: 'now', v: '待签发', n: '复核后签单' }
          : { st: 'todo', v: '—' }
  const linkSt = (a: NodeSt): 'ok' | 'bad' | 'todo' =>
    a === 'done' ? 'ok' : a === 'bad' ? 'bad' : 'todo'
  /* 上一期一行已撤（2026-10-28 rick 裁「小字都删」）；
     prevP 仍供上一期水位差值（较上一期小签）使用 */
  const prevIdx = periods.findIndex(p => p.period === period)
  const prevP = prevIdx >= 0 ? periods[prevIdx + 1] : undefined
  /* 上一期水位（2026-10-24 本期读数）：单独再取一次，取不到 → 不出「较上一期」差值小签。
     只在本期已有矩阵读数时才取——本期没有（未出稿 / 临时期次），上一期多半也没有，
     白跑一趟只会给没开过的期次打出 404 噪声。 */
  const prevPeriodId = prevP?.period ?? ''
  const waterReady = water.length > 0
  const [prevWater, setPrevWater] = useState<WaterRow[] | null>(null)
  useEffect(() => {
    if (!prevPeriodId || !waterReady) { setPrevWater(null); return }
    let alive = true
    setPrevWater(null)
    getWaterLevel(prevPeriodId)
      .then((w) => { if (alive) setPrevWater(w.rows) })
      .catch(() => { if (alive) setPrevWater(null) })
    return () => { alive = false }
  }, [prevPeriodId, waterReady])

  /* ── 本期读数（2026-10-24）：学科矩阵三枚真值＋较上一期差值。
     读数只认学科矩阵（水位接口）——预测看板兜底里没有「已进入」状态，拿来会编出假 0；
     矩阵没读到就如实显示 —；上一期没有矩阵时差值小签整枚不渲染。差值只做减法展示。 ── */
  const readIn = water.filter((r) => r.state === 'in').length
  let near: WaterRow | null = null
  for (const r of water) {
    if (r.state === 'in' || r.prox == null) continue
    if (!near || r.prox > (near.prox ?? 0)) near = r
  }
  let prevNear: WaterRow | null = null
  for (const r of prevWater ?? []) {
    if (r.state === 'in' || r.prox == null) continue
    if (!prevNear || r.prox > (prevNear.prox ?? 0)) prevNear = r
  }
  const prevLen = prevWater?.length ?? 0
  const prevHas = prevLen > 0
  const dTotal = water.length && prevHas ? water.length - prevLen : null
  const dIn = water.length && prevHas
    ? readIn - (prevWater?.filter((r) => r.state === 'in').length ?? 0)
    : null
  const dProx = near?.prox != null && prevNear?.prox != null ? near.prox - prevNear.prox : null
  /* 状态说明小字（WHY/why）已撤（2026-10-28 rick 裁「小字都删」） */

  return (
    <>
      {/* v2 极致低密（2026-10-24 rick 过审，静态稿 v2 同构）：一行期次身份＋四节点流程图＋一行主动作。
          旧题头（题句/状态药丸/翻牌）与故事条退役——故事回放迁往「可视化工作流」屏。
          2026-10-28：期次旁的期数/数据截至小字、右上「上一期」小字、
          主动作行的状态说明小字一并退役。 */}
      <section className="wb2" aria-label="本期进度">
        <div className="wb2-line">
          <h1 className="wb2-period">本期 {period ?? '——————'}</h1>
        </div>
        <div className="wb2-flow">
          <FlowNode k="取 数" st={fetchNode.st} v={fetchNode.v} n={fetchNode.n} />
          <FlowLink st={linkSt(fetchNode.st)} />
          <FlowNode k="生 成" st={genNode.st} v={genNode.v} n={genNode.n} />
          <FlowLink st={linkSt(genNode.st)} />
          <FlowNode k="审 计" st={auditNode.st} v={auditNode.v} n={auditNode.n} />
          <FlowLink st={linkSt(auditNode.st)} />
          <FlowNode k="签 发" st={signNode.st} v={signNode.v} n={signNode.n} />
        </div>
        <div className="wb2-cta">
          {wb.focusAction === 'generate' && canRun && (
            <button className="btn primary big" onClick={onGenerate} disabled={!canGenerate}>
              <Icon name="play" size={20} />开始生成
            </button>
          )}
          {wb.focusAction === 'rerun' && canRun && (
            <ConfirmButton className="btn primary big" disabled={!canGenerate}
                           confirmText="确认重跑？会撤下当前成品" onConfirm={onGenerate}
                           autoConfirm={autoConfirmRerun}>
              <Icon name="refresh" size={20} />重新生成
            </ConfirmButton>
          )}
          {wb.focusAction === 'sign' && (
            <a className="btn primary big" href={`/app/?view=review${period ? `&period=${encodeURIComponent(period)}` : ''}`}>
              <Icon name="seal" size={20} />复核并签单
            </a>
          )}
          {wb.focusAction === 'open' && (
            <a className="btn primary big" href={`/app/?view=report${period ? `&period=${encodeURIComponent(period)}` : ''}`}>
              <Icon name="doc" size={20} />打开报告
            </a>
          )}
          {wb.focusAction === 'acquire' && isAdmin && (
            <a className="btn primary big" href={`/app/?view=acquire${period ? `&period=${encodeURIComponent(period)}` : ''}`}>
              <Icon name="download" size={20} />去取数台
            </a>
          )}
          <a className="btn wb2-ghost" href={`/app/?view=pano${period ? `&period=${encodeURIComponent(period)}` : ''}`}>
            查看可视化工作流 →
          </a>
          <Info label="状态从哪来">
            <p>取数/生成节点来自单期详情与任务记录；审计读数来自运行档案；签发状态来自审核台签单。本页只读，不改任何数据。</p>
          </Info>
        </div>
      </section>

      {/* 本期读数（2026-10-24）：学科矩阵三枚真值＋较上一期差值小签（读法沿用报告读数带）。
          没读到矩阵就如实显示 —；差值只在上一期也有矩阵时出现——不显示假 0。 */}
      <section className="readouts" aria-label="本期读数">
        <div className="readout">
          <div className="k">学科总数</div>
          <div className={`v${water.length ? '' : ' pending'}`}>{water.length || '—'}</div>
          <DeltaChip diff={dTotal} />
        </div>
        <div className="readout">
          <div className="k">已进入前 1%</div>
          <div className={`v${water.length ? '' : ' pending'}`}>{water.length ? readIn : '—'}</div>
          <DeltaChip diff={dIn} semantic />
        </div>
        <div className="readout">
          <div className="k">最接近前 1% 的潜力学科</div>
          <div className={`v${near ? ' tx' : ' pending'}`}>{near ? `${near.subject} ${near.prox}%` : '—'}</div>
          <DeltaChip diff={dProx} />
        </div>
      </section>

      {/* 绿·器（汇-绿蓝）：潜力学科水尺（预测看板真值） */}
      <section className="gaugeband">
        <div className="gb-grid">
          <div className="gb-copy">
            <p className="kik">水 位 標 尺 · 接 近 度</p>
            <h2>阈值即水位线，<br />潜力学科各是一根水尺。</h2>
          </div>
          <div className="gauge">
            <div className="gauge-head"><span>潜 力 學 科 水 位</span><span className="mono">{period ?? ''}</span></div>
            {gaugeRows.length ? gaugeRows.slice(0, 8).map((r) => (
              <div className="gauge-row" key={r.subject}>
                <span className="g-name">{r.subject}</span>
                <span className="g-bar"><i style={{ width: `${Math.min(100, Math.max(0, r.prox ?? 0))}%` }} /></span>
                <span className="g-val mono">{r.state === 'in' ? '已进入' : r.prox == null ? '—' : `${r.prox}%`}</span>
              </div>
            )) : <p className="gb-note">这一期还没有水位读数——看板生成后显示。</p>}
            <div className="gauge-thr">ESI 前 1% 阈值（100%）</div>
          </div>
        </div>
      </section>

        {forecastAppliedStale && (!run || isTerminal(run.status ?? undefined)) && (
          /* 改选还没进报告（2026-10-16，rick）：说清哪几处改了、报告是旧的、重出才生效。
             重出进行中或刚落定（run 非终态）时先不显示——那一刻提示只会误导。 */
          <div className="banner warn mx-card-22" role="status">
            <span className="ico"><Icon name="alert" size={22} /></span>
            <span>
              <b className="title">模型选择改过，报告还是旧的</b>
              <span>
                {forecastAppliedDiffs.join('；')}
                {forecastChoice?.at
                  ? `（${forecastChoice.by ? `${forecastChoice.by} · ` : ''}${forecastChoice.at} 保存）`
                  : ''}
                。当前报告仍按改选前的选择生成——重新生成后生效：未进 1% 的学科都会按你的选择出图；
                报告正文优先出改过模型的学科（不足两个按接近度补齐）。
              </span>
              <span className="acts">
                <ConfirmButton className="btn" disabled={!canGenerate}
                               confirmText="确认重跑？会撤下当前成品" onConfirm={onGenerate}
                               autoConfirm={autoConfirmRerun}>
                  <Icon name="refresh" size={19} />重新生成
                </ConfirmButton>
                <a className="btn" href={`/app/?view=forecast${period ? `&period=${encodeURIComponent(period)}` : ''}`}>
                  去预测台看选择 →
                </a>
              </span>
            </span>
          </div>
        )}

        {!canGenerate && hasGenerateAction && (
          <p className="hint card-foot">
            {actionLockReason ?? (me == null
              ? <>系统暂时无法确认你的身份，为保护数据，生成按钮暂时不能使用。</>
              : <>先选择一期，再开始生成。</>)}
        </p>
        )}

        {run && !isTerminal(run.status ?? undefined) ? (
          <div className="runbar">
            <span className="elapsed" aria-live="polite">
              <Icon name="refresh" size={19} />
              {`任务进行中 · 期次 ${run.requestedPeriod}${run.outputPeriod && run.outputPeriod !== run.requestedPeriod ? `（实际输出 ${run.outputPeriod}）` : ''} · ${runConnLabel(run)}`}
              {run.last ? ` · ${run.last}` : ''}
            </span>
          </div>
        ) : activeRun ? (
            <div className="elapsed"><Icon name="refresh" size={20} />有任务正在进行——完成后才能开始新的生成；想跟进进度，切到任务所属期次。</div>
          ) : wb.state === 'running' ? (
            /* 页面刚回来、进度还没接上时的如实提示（原先是固定百分比假进度，已删） */
            <div className="elapsed">
              <Icon name="refresh" size={19} />
              任务正在生成——正在获取进度，稍等片刻这里会显示实况。
            </div>
          ) : null}
        <Banners wb={wb} err={err} healthy={healthy} onRerun={onGenerate} canRerun={canGenerate} period={period}
          approvalStatus={approvalStatus} />

        {activityState === 'unknown' && !hasGenerateAction && (
          <p className="hint card-foot">{actionLockReason}</p>
        )}

        {wb.note && (
          <div className="pad-card-foot2">
            <div className="degraded">{wb.note}</div>
          </div>
        )}
      {/* 「这一期的工具」折块（2026-10-24 rick 工作台减负）迁往运行档案页（App.tsx archive 分支）：
          重跑/回滚/上传是管理向动作，生成台首屏回归极致低密；props 与门控原样搬走，组件未动。 */}
    </>
  )
}

export type { WBState, Period, PeriodDetail }
