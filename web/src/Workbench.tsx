/* 生成台（工作台）——工具面。
   第一屏＝「这一期现在到哪一步、下一步做什么」；全屏只有一处朱色实心焦点。
   设计取自静态稿 mockups/v2-工作台与报告.html；状态与文案规格见 web/UX-生成台.md。 */

import type { ApiError, Me, Period, PeriodDetail } from './api'
import { useEffect, useState } from 'react'
import { getForecastBoard, getWaterLevel, type ForecastBoardRow, type ForecastChoiceEntry, type WaterRow } from './api-forecast'
import { ConfirmButton } from './ConfirmButton'
import { Info } from './Info'
import { Tools } from './Tools'
import { appHref, approvalLabel, taskLabel as runStatusText } from './lib/status'
import { Icon } from './icons'
import { failureCopy, isTerminal, STATE_LABEL, type Workbench as WB, type WBState } from './wb'
import type { ActivityState, Run } from './hooks/useJobRun'

/** 五个模型的一句话说明（界面上"帮馆员选"的文案；预测台也用同一份，改一处两边一致） */
export const MODEL_DESC: Record<string, string> = {
  'Holt趋势模型': '只抓长期趋势、不管季节。适合稳定上升/下降的学科，外推最直接。',
  '阻尼Holt模型': '趋势会「减速」——越往前推越保守。适合增长在放缓的学科。',
  '季节性ETS模型': '抓「6 期一轮」的双月节律。适合受学年与发布节奏影响的指标。',
  'SARIMA模型': '趋势 + 季节都管，参数在最初 30 期按 AIC 选定后固定。通用、稳。',
  '经验贝叶斯状态空间模型': '把趋势与季节当「状态」逐期更新。对噪声大的序列更稳健。',
}

function Steps({ wb, period }: { wb: WB; period: string | null }) {
  const acquireHref = `/app/?view=acquire${period ? `&period=${encodeURIComponent(period)}` : ''}`
  return (
    <ol className="steplist">
      {wb.steps.map((s, i) => (
        <li key={s.key} className={`step ${s.on ? 'on' : ''} ${s.now ? 'now' : ''}`}>
          <span className="dot">{s.on ? <Icon name="check" size={13} /> : i + 1}</span>
          <span>
            {s.key === 'fetch' && period
              ? <a className="steplink" href={acquireHref} title="去下载数据台">{s.title}</a>
              : s.title}
            <small>{s.detail}</small>
          </span>
        </li>
      ))}
    </ol>
  )
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

export function Workbench({
  period, me, wb, err, healthy, run, approvalStatus, activityState,
  actionLockReason, activeRun, actionsLocked, submitting, onGenerate,
  periods, forecastChoice,
  forecastAppliedStale, forecastAppliedDiffs, autoConfirmRerun,
  showTools, toolJobId, toolArtifactsToken, onToolActionStart, onToolActionEnd, onToolUploaded,
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
  /** 已保存的模型选择 ≠ 上次出稿实际用的选择（报告还是旧的）；无出稿快照时恒 false */
  forecastAppliedStale: boolean
  /** 提示条里列的改动（「总被引：免疫学 → SARIMA模型」这类人话） */
  forecastAppliedDiffs: string[]
  /** 从预测台「回出报告并重新生成」来（?rerun=1）：重跑确认态直接打开一次 */
  autoConfirmRerun: boolean
  /** 「工具调用记录」折叠（2026-10-01 从 App 抽出）：角色未确认/操作员（只读）时不渲染 */
  showTools: boolean
  toolJobId: string | null
  toolArtifactsToken: number
  onToolActionStart: (action: 'upload' | 'rerun' | 'rollback') => boolean
  onToolActionEnd: (action: 'upload' | 'rerun' | 'rollback') => void
  onToolUploaded: (jobId: string, period: string) => void
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
  const issueNo = /第 (\d+) 期/.exec(periods.find((p) => p.period === period)?.label ?? '')?.[1] ?? ''
  /* 2026-10-12：出报告对操作员也开放（后端 POST /api/jobs 已开）；下载数据/工具折仍只管理员。 */
  const canRun = !!me
  const canGenerate = canRun && period != null && /^\d{6}$/.test(period) && !actionsLocked && !activeRun && !submitting
    && (!run || isTerminal(run.status ?? undefined))
  const hasGenerateAction = wb.focusAction === 'generate' || wb.focusAction === 'rerun'
  /** 水尺行：矩阵优先（全 22 学科），预测看板兜底（旧期次没有 matrix.json 时）。
      「潜力学科」看的是还没进前 1% 的——已进入的排在最前会把水尺刷成 8 根满格。 */
  const gaugePool: WaterRow[] = water.length
    ? water
    : board.map((r) => ({ subject: r.subject, prox: r.prox, state: 'unknown' as const }))
  const gaugePotential = gaugePool.filter((r) => r.state !== 'in')
  const gaugeRows = gaugePotential.length ? gaugePotential : gaugePool

  return (
    <>
      {/* 蓝场题头（2026-10-17 绿蓝融合 U2，据 汇-绿蓝.html）：焦点陈述＋主动作＋翻牌数字 */}
      <section className="wb-hero">
        <div className="wb-hero-main">
          <p className="kik">云南 大 學 圖 書 館 藏 · 学 科 情 報 · 出 報 告 台</p>
          <div className="wb-hero-pills">
            <span className="pill on-field">{STATE_LABEL[wb.state]}</span>
            <span className={`pill on-field ${approvalStatus === 'signed' ? 'signed' : approvalStatus === 'stale' ? 'stale' : 'unsigned'}`}>
              {approvalLabel(approvalStatus)}
            </span>
            <Info label="状态从哪来">
              <p>任务状态来自本期任务记录；签发状态来自审核台签单。本页只读，不改任何数据。</p>
            </Info>
          </div>
          <h1>{wb.focusTitle}</h1>
          <p className="wb-hero-sub">{wb.focusSub}</p>
          <div className="wb-hero-act">
            {wb.focusAction === 'generate' && canRun && (
              <>
                <button className="btn primary big" onClick={onGenerate} disabled={!canGenerate}>
                  <Icon name="play" size={20} />开始生成
                </button>
                <span className="wb-hero-link">约 3 分钟</span>
              </>
            )}
            {wb.focusAction === 'rerun' && canRun && (
              <ConfirmButton className="btn primary big" disabled={!canGenerate}
                             confirmText="确认重跑？会撤下当前成品" onConfirm={onGenerate}>
                <Icon name="refresh" size={20} />重新生成
              </ConfirmButton>
            )}
            {wb.focusAction === 'sign' && (
              <>
                <a className="btn primary big" href={`/app/?view=review${period ? `&period=${encodeURIComponent(period)}` : ''}`}><Icon name="seal" size={20} />复核并签单</a>
                <a className="wb-hero-link" href={`/app/?view=report${period ? `&period=${encodeURIComponent(period)}` : ''}`}>打开报告 ↗</a>
              </>
            )}
            {wb.focusAction === 'open' && (
              <a className="btn primary big" href={`/app/?view=report${period ? `&period=${encodeURIComponent(period)}` : ''}`}><Icon name="doc" size={20} />打开报告</a>
            )}
            {wb.focusAction === 'acquire' && isAdmin && (
              <a className="btn primary big" href={`/app/?view=acquire${period ? `&period=${encodeURIComponent(period)}` : ''}`}>
                <Icon name="download" size={20} />去取数台
              </a>
            )}
          </div>
        </div>
        <div className="wb-flaps" aria-label="本期读数">
          <div className="flaprow">
            <span className="flabel">期 次 · 目 錄</span>
            <span className="flaps">{(period ?? '——————').split('').map((d, i) => <i key={i}>{d}</i>)}</span>
          </div>
          <div className="flaprow">
            <span className="flabel">總 第 · 期</span>
            <span className="flaps">{(issueNo || '—').split('').map((d, i) => <i key={i}>{d}</i>)}</span>
            <span className="flabel">簽 發</span>
            <span className="flaps sm"><i>{approvalStatus === 'signed' ? '签' : approvalStatus === 'stale' ? '效' : '待'}</i></span>
          </div>
        </div>
      </section>

      {/* 绿·器（汇-绿蓝）：潜力学科水尺（预测看板真值）＋ 本期工序进度 */}
      <section className="gaugeband">
        <div className="gb-grid">
          <div className="gb-copy">
            <p className="kik">水 位 標 尺 · 接 近 度</p>
            <h2>阈值即水位线，<br />潜力学科各是一根水尺。</h2>
            <p className="gb-note">ESI 前 1% 被引阈值是警戒水位。读数来自本期学科矩阵（接近度＝百分数点值），前端不换算。</p>
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
        <Steps wb={wb} period={period} />
      </section>

      {/* 三枚橡皮戳（戳印之一）＋ 本期数据 */}
      <section className="wb-stamps">
        <div className="stamp-col">
          <div className={`stamp ${wb.steps[1]?.on ? 'on' : ''}`}><b>已并入<br />台账</b><small>{wb.steps[1]?.on ? '完成' : '未完成'}</small></div>
          <div className={`stamp ${wb.steps[2]?.on ? 'on' : ''}`}><b>已出稿</b><small>{wb.steps[2]?.on ? '完成' : '未完成'}</small></div>
          <div className={`stamp warn ${approvalStatus === 'signed' ? 'on' : ''}`}><b>复核通过</b><small>{approvalStatus === 'signed' ? '已签发' : 'PENDING'}</small></div>
        </div>
        <dl className="data">
          <div><dt>期 次</dt><dd className="mono">{period ?? '—'}</dd></div>
          <div><dt>取 数</dt><dd>{wb.steps[0]?.detail ?? '—'}</dd></div>
          <div><dt>核对并并入</dt><dd>{wb.steps[1]?.detail ?? '—'}</dd></div>
          <div><dt>一键生成</dt><dd>{wb.steps[2]?.detail ?? '—'}</dd></div>
          <div><dt>签 发</dt><dd>{approvalLabel(approvalStatus)}</dd></div>
        </dl>
      </section>

      {wb.focusAction === 'sign' && (
        /* 签单区（戳印之二：钤印落在动作上，据 汇-绿蓝.html） */
        <section className="sign">
          <div>
            <p className="kik">核 驗 與 簽 單</p>
            <h2>盖印签单，此版归档。</h2>
            <p className="sign-note">{wb.focusSub}</p>
            <div className="wb-hero-act">
              <a className="btn primary big" href={`/app/?view=review${period ? `&period=${encodeURIComponent(period)}` : ''}`}><Icon name="seal" size={20} />复核并签单</a>
            </div>
          </div>
          <div className="seal-mark" aria-hidden="true">至公天下</div>
        </section>
      )}

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
        ) : run ? (
          <div className="runbar">
            <span className="elapsed">
              最近任务 {run.requestedPeriod} · {run.status ? runStatusText(run.status) : '—'}
            </span>
            <a className="btn runbar-log" href={`/app/?view=archive${period ? `&period=${encodeURIComponent(period)}` : ''}`}>查看运行档案 →</a>
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
      {showTools && (
        <details className="fold">
          <summary>这一期的工具<span className="sm">重跑 · 回滚 · 台账 · 日志包</span></summary>
          <p className="hint fold-lead">
            看数据源：<a href={`/app/?view=ledger${period ? `&period=${encodeURIComponent(period)}` : ''}`}>主台账（只读）→</a>
          </p>
          <Tools
            period={period}
            jobId={toolJobId}
            approvalStatus={approvalStatus}
            actionsLocked={actionsLocked}
            actionLockReason={actionLockReason}
            onActionStart={onToolActionStart}
            onActionEnd={onToolActionEnd}
            onUploaded={onToolUploaded}
            refreshToken={toolArtifactsToken}
          />
        </details>
      )}
    </>
  )
}

/** 全部期次（生成台尾块，2026-10-01 从 App.tsx 抽出）：行点击是鼠标便利，
    「期次」单元格里的按钮是它的键盘等价物（点击冒泡到行，同一动作）。 */
export function PeriodsPanel({ periods, selected, healthy, onPick }: {
  periods: Period[]
  selected: string | null
  healthy: boolean | null
  onPick: (period: string) => void
}) {
  return (
    <details className="fold">
      <summary>全部期次<span className="sm">共 {periods.length} 期</span></summary>
      <section className="card tablewrap mt-18">
        <table className="periods">
          <thead>
            <tr>
              <th>期次</th><th>状态</th><th className="w-90">操作</th>
            </tr>
          </thead>
          <tbody>
            {periods.length === 0 && (
              <tr><td colSpan={3} className="ink-3">
                {healthy === false ? (
                  <>服务未启动，读不到期次。起好服务后
                    <button className="btn btn-xs mx-6" 
                            onClick={() => location.reload()}>重新检查</button>
                    一次。</>
                ) : (
                  <>还没有任何期次。数据按期次自动读台账；生成第一期后这里就有记录。<a href="#tools">去看这一期的工具 →</a></>
                )}
              </td></tr>
            )}
            {periods.map((p) => (
              <tr key={p.period} className="period-row"
                  onClick={() => onPick(p.period)}
                  style={{ background: p.period === selected ? 'var(--panel)' : undefined }}>
                <td><button type="button" className="rowbtn">{p.label}</button></td>
                <td>
                  <span className={`pill ${p.status === 'signed' ? 'signed' : p.status === 'stale' ? 'stale' : 'unsigned'}`}>
                    {approvalLabel(p.status)}
                  </span>
                </td>
                <td>
                  <a href={appHref('report', p.period)}
                     onClick={(e) => e.stopPropagation()}>打开</a>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </section>
    </details>
  )
}

export type { WBState, Period, PeriodDetail }
