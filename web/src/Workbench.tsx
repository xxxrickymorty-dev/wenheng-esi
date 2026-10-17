/* 生成台（工作台）——工具面。
   第一屏＝「这一期现在到哪一步、下一步做什么」；全屏只有一处朱色实心焦点。
   设计取自静态稿 mockups/v2-工作台与报告.html；状态与文案规格见 web/UX-生成台.md。 */

import type { ApiError, Me, Period, PeriodDetail } from './api'
import type { ForecastChoiceEntry } from './api-forecast'
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
  forecastChoice,
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
  /* 2026-10-12：出报告对操作员也开放（后端 POST /api/jobs 已开）；下载数据/工具折仍只管理员。 */
  const canRun = !!me
  const canGenerate = canRun && period != null && /^\d{6}$/.test(period) && !actionsLocked && !activeRun && !submitting
    && (!run || isTerminal(run.status ?? undefined))
  const hasGenerateAction = wb.focusAction === 'generate' || wb.focusAction === 'rerun'

  return (
    <>
      <section className="card">
        <div className="steps">
          <h1>{period ?? '（选择期次）'}</h1>
          <span className="steps-meta">
            <span className="pill">{STATE_LABEL[wb.state]}</span>
            <span className={`pill ${approvalStatus === 'signed' ? 'signed' : approvalStatus === 'stale' ? 'stale' : 'unsigned'}`}>
              {approvalLabel(approvalStatus)}
            </span>
            <Info label="状态从哪来" end>
              <p>任务状态来自本期任务记录；签发状态来自审核台签单。本页只读，不改任何数据。</p>
            </Info>
          </span>
          <Steps wb={wb} period={period} />
        </div>

        <div className="focus mx-card-22">
          <div>
            <div className="big">{wb.focusTitle}</div>
            <div className="sub">{wb.focusSub}</div>
          </div>
          <div className="cta">
            {wb.focusAction === 'generate' && canRun && (
              <>
                <span className="hint">约 3 分钟</span>
                <button className="btn primary" onClick={onGenerate} disabled={!canGenerate}>
                  <Icon name="play" size={20} />开始生成
                </button>
              </>
            )}
            {wb.focusAction === 'rerun' && canRun && (
              <ConfirmButton className="btn" disabled={!canGenerate}
                             confirmText="确认重跑？会撤下当前成品" onConfirm={onGenerate}>
                <Icon name="refresh" size={20} />重新生成
              </ConfirmButton>
            )}
            {wb.focusAction === 'sign' && (
              <>
                <a className="hint" href={`/app/?view=report${period ? `&period=${encodeURIComponent(period)}` : ''}`}>打开报告 ↗</a>
                <a className="btn primary" href={`/app/?view=review${period ? `&period=${encodeURIComponent(period)}` : ''}`}><Icon name="seal" size={20} />复核并签单</a>
              </>
            )}
            {wb.focusAction === 'open' && (
              <a className="btn" href={`/app/?view=report${period ? `&period=${encodeURIComponent(period)}` : ''}`}><Icon name="doc" size={20} />打开报告</a>
            )}
            {wb.focusAction === 'acquire' && isAdmin && (
              <a className="btn primary" href={`/app/?view=acquire${period ? `&period=${encodeURIComponent(period)}` : ''}`}>
                <Icon name="download" size={20} />去下载数据
              </a>
            )}
          </div>
        </div>

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
      </section>

      {showTools && (
        <details className="fold">
          <summary>这一期的工具<span className="sm">上传 · 重跑 · 回滚 · 台账 · 日志包</span></summary>
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
                  <>还没有任何期次。先在下方「这一期的工具」上传当期数据表，生成第一期。<a href="#tools">去上传 →</a></>
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
