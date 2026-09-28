/* 生成台（工作台）——工具面。
   第一屏＝「这一期现在到哪一步、下一步做什么」；全屏只有一处朱色实心焦点。
   设计取自静态稿 mockups/v2-工作台与报告.html；状态与文案规格见 web/UX-生成台.md。 */

import type { ApiError, Me, Period, PeriodDetail } from './api'
import { formatProvenanceTime, type ForecastChoiceEntry, type ForecastMeta } from './api5'
import { useState } from 'react'
import { ConfirmButton } from './ConfirmButton'
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

function Steps({ wb }: { wb: WB }) {
  return (
    <ol className="steplist">
      {wb.steps.map((s, i) => (
        <li key={s.key} className={`step ${s.on ? 'on' : ''} ${s.now ? 'now' : ''}`}>
          <span className="dot">{s.on ? <Icon name="check" size={13} /> : i + 1}</span>
          <span>
            {s.title}
            <small>{s.detail}</small>
          </span>
        </li>
      ))}
    </ol>
  )
}

function Progress() {
  const rows = [
    { name: '读取台账', pct: 100, state: 'done' },
    { name: '汇总数据', pct: 100, state: 'done' },
    { name: '预测与回看', pct: 100, state: 'done' },
    { name: '画图', pct: 69, state: 'now' },
    { name: '装配报告', pct: 0, state: 'wait' },
  ]
  return (
    <>
      <div className="elapsed">
        <Icon name="refresh" size={20} />
        正在生成 · 已用 8 秒
      </div>
      <div className="progress">
        {rows.map((r) => (
          <div key={r.name} className={`prow ${r.state === 'now' ? 'now' : ''}`}>
            <span style={{ flex: '0 0 22px', color: r.state === 'done' ? 'var(--ok)' : 'var(--ink-3)' }}>
              <Icon name={r.state === 'done' ? 'check' : r.state === 'now' ? 'refresh' : 'clock'} size={19} />
            </span>
            <span className="name">{r.name}</span>
            <span className="bar">
              <i style={{ width: `${r.pct}%` }} />
            </span>
            <span className="pct">
              {r.state === 'done' ? '完成' : r.state === 'now' ? `${r.pct}%` : '等待'}
            </span>
          </div>
        ))}
      </div>
    </>
  )
}

/** 真实生成过程：任务状态与本期审批状态分开显示。 */
function LiveRun({ run, approvalStatus }: { run: Run; approvalStatus: string }) {
  const [open, setOpen] = useState(false)
  const taskLabel: Record<string, string> = {
    pending: '等待开始', running: '正在生成', retrying: '正在重试',
    waiting_approval: '等待馆员审批', completed: '已生成',
    warned: '已生成，有校验提醒', escalated: '已转交人工处理',
    failed: '生成失败', cancelled: '已取消', stalled: '暂时没有进展',
  }
  const approvalLabel = approvalStatus === 'signed' ? '已签发'
    : approvalStatus === 'stale' ? '签发记录已失效' : '未签发'
  const connectionLabel = run.connection === 'live' ? '页面正在更新进度'
    : run.connection === 'snapshot' ? '正在读取任务进度'
      : run.connection === 'reconnecting' ? '连接中断，正在恢复进度'
        : '暂时连不上服务，页面会继续更新进度'
  return (
    <>
      <div className="elapsed">
        <Icon name="refresh" size={20} />
        {`任务：${run.status ? taskLabel[run.status] ?? '任务状态已更新' : '正在读取状态'} · 任务期次 ${run.requestedPeriod}${run.outputPeriod ? ` · 报告期次 ${run.outputPeriod}` : ''} · ${connectionLabel}`}
      </div>
      <div className="progress">
        <div className="prow">
          <span className="name">任务期次审批</span>
          <span style={{ flex: 1, color: 'var(--ink-2)' }}>{approvalLabel}</span>
        </div>
        <div className="prow">
          <span className="name">最新进度</span>
          <span style={{ flex: 1, color: 'var(--ink-2)' }}>{run.last ?? '（进度还未返回…）'}</span>
        </div>
      </div>
      <div style={{ padding: '0 24px 16px' }}>
        <button className="btn" onClick={() => setOpen(!open)}>
          <Icon name="list" size={18} />{open ? '收起日志' : '看详细过程'}
        </button>
        {open && (
          <pre style={{
            marginTop: 10, maxHeight: 260, overflow: 'auto', background: 'var(--panel)',
            border: '1px solid var(--line)', borderRadius: 10, padding: '10px 12px',
            fontSize: 12.5, fontFamily: 'var(--mono)', color: 'var(--ink-2)',
          }}>
            {run.lines.length ? run.lines.join('\n') : '（暂无日志行）'}
          </pre>
        )}
      </div>
    </>
  )
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
  const approvalLabel = approvalStatus === 'signed' ? '已签发'
    : approvalStatus === 'stale' ? '签发记录已失效' : '未签发'
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
            <li>本期审批状态：{approvalLabel}。</li>
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
  if (wb.state === 'waiting-approval') {
    return (
      <div className="banner warn">
        <span className="ico"><Icon name="clock" size={22} /></span>
        <span><b className="title">等待馆员审批</b><span>生成任务还在等待馆员审批；本期签发状态请在审核台查看。</span></span>
      </div>
    )
  }
  if (wb.state === 'done' || wb.state === 'signed') {
    return (
      <div className="banner ok">
        <span className="ico"><Icon name="check" size={22} /></span>
        <span>
          <b className="title">{wb.state === 'signed' ? '本期已签发' : '本期报告已生成'}</b>
          <span>本期审批状态：{approvalLabel}。{approvalStatus === 'signed'
            ? ''
            : '任务结束不代表报告合格或已签发；管理员当前不能下载未签发初稿。'}</span>
          <span className="acts">
            <a className="btn" href={`/app/?view=report${period ? `&period=${encodeURIComponent(period)}` : ''}`}><Icon name="doc" size={19} />打开报告</a>
            <a className="btn" href={`/app/?view=review${period ? `&period=${encodeURIComponent(period)}` : ''}`}><Icon name="seal" size={19} />去审核台</a>
          </span>
        </span>
      </div>
    )
  }
  if (wb.state === 'fail-ledger' || wb.state === 'fail-other' || wb.state === 'stalled') {
    const c = wb.state === 'stalled'
      ? { title: '看起来卡住了', lines: ['已有一段时间没有进展，可以取消重跑。', '上一版报告仍然有效。'] }
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

function ModelSummary({
  period, periods, meta, metaError, actualOutputPeriod, state, dirty,
  onPickPeriod, onReload,
}: {
  period: string | null
  periods: Period[]
  meta: ForecastMeta | null
  metaError: string
  actualOutputPeriod: string | null
  state: ForecastChoiceEntry | null
  dirty: boolean
  onPickPeriod: (period: string) => void
  onReload: () => void
}) {
  const [route, setRoute] = useState(meta?.routes[0]?.value ?? '')
  const routes = meta?.routes ?? []
  const subjects = meta?.subjects ?? []
  const source = meta?.upstream_workbook
  const sourceTime = source?.last_modified_at ?? null
  const freshnessText = meta?.data_freshness === 'needs_check'
    ? '检测到台账或处理输入文件的修改时间晚于最近一次完整运行记录；无法确认这次更新是否已进入预测数据，请重新处理确认。'
    : '现有记录无法确认上游台账是否已进入预测所用数据。预测预览仍读取下方所示的最新完整预测数据。'
  const currentRoute = routes.some((item) => item.value === route) ? route : (routes[0]?.value ?? '')

  return (
    <section className="card" style={{ marginTop: 18, padding: '20px 22px' }}>
      <div style={{ display: 'flex', alignItems: 'center', gap: 10, flexWrap: 'wrap' }}>
        <span className="fc-no">01</span>
        <h2 style={{ fontSize: 21 }}>预测模型 · 本期已选</h2>
        <span style={{ padding: '3px 9px', borderRadius: 999, background: 'var(--gold-soft)', color: 'var(--gold-ink)', fontSize: 12, fontWeight: 650 }}>
          只读 · 改选去预测台
        </span>
      </div>
      <p style={{ margin: '9px 0 14px', color: 'var(--ink-2)', fontSize: 15.5 }}>
        模型选择只有一份，按期次保存；这里只显示本期配置，改选集中在预测台——那边能对着五个模型的预测图挑。
        改完保存后回到这里会同步显示；本期报告只应用实际进入预测章的学科。
      </p>

      <div style={{ display: 'flex', alignItems: 'center', gap: 12, flexWrap: 'wrap', padding: '12px 14px', background: 'var(--panel)', border: '1px solid var(--line-2)', borderRadius: 10 }}>
        <label htmlFor="workbench-task-period" style={{ display: 'grid', gap: 4, color: 'var(--ink-3)', fontSize: 13 }}>
          当前期次
          <select id="workbench-task-period" value={period ?? ''} onChange={(e) => onPickPeriod(e.target.value)}
                  style={{ minWidth: 170, padding: '5px 9px', border: '1px solid var(--line)', borderRadius: 7, background: 'var(--card)', color: 'var(--ink)', font: 'inherit', fontSize: 16 }}>
            {!period && <option value="">请选择期次</option>}
            {periods.map((item) => <option key={item.period} value={item.period}>{item.period}</option>)}
            {period && !periods.some((item) => item.period === period) && <option value={period}>{period}</option>}
          </select>
        </label>
        <div style={{ minWidth: 160 }}>
          <small style={{ display: 'block', color: 'var(--ink-3)', fontSize: 13 }}>最新完整预测数据</small>
          <strong style={{ fontFamily: 'var(--mono)', fontSize: 16 }}>{meta?.source_period || '未就绪'}</strong>
        </div>
        <div style={{ minWidth: 190 }}>
          <small style={{ display: 'block', color: 'var(--ink-3)', fontSize: 13 }}>本次实际输出期次</small>
          <strong style={{ color: 'var(--gold-ink)', fontSize: 15 }}>{actualOutputPeriod || '任务完成后显示'}</strong>
        </div>
        <div style={{ minWidth: 260, flex: 1 }}>
          <small style={{ display: 'block', color: 'var(--ink-3)', fontSize: 13 }}>上游只读台账文件</small>
          <strong style={{ fontSize: 14 }}>{source?.name ?? '云大全学科排名、阈值动态检测表.xlsx'}</strong>
          <span style={{ display: 'block', color: 'var(--ink-3)', fontSize: 13 }}>
            最后修改（北京时间）：{sourceTime ? formatProvenanceTime(sourceTime) : '本机未找到'}
          </span>
        </div>
      </div>

      <div className="degraded" style={{ borderLeft: meta?.data_freshness === 'needs_check' ? '3px solid var(--gold)' : undefined }}>
        <b>期次与数据说明</b>：{freshnessText} 现有记录无法确认主台账是否被预测流程读取。V1 推荐基线为 {meta?.recommendation_baseline ?? '—'}，它不是预测数据期次。
        <br />最近一次完整运行记录写入时间（北京时间）：{formatProvenanceTime(meta?.run_record_at)}；上次处理使用的文件：{meta?.processed_input?.name ?? '无法核实'}{meta?.processed_input?.last_modified_at ? `（文件最后修改：${formatProvenanceTime(meta.processed_input.last_modified_at)}）` : ''}。
      </div>

      {routes.length > 0 && (
        <div role="group" aria-label="模型路线" style={{ display: 'flex', gap: 8, flexWrap: 'wrap', margin: '14px 0 10px' }}>
          {routes.map((item) => (
            <button key={item.value} type="button" className="btn" aria-pressed={item.value === currentRoute}
                    onClick={() => setRoute(item.value)} style={item.value === currentRoute ? { borderColor: 'var(--zhu)', background: 'var(--zhu-soft)', color: 'var(--zhu)' } : undefined}>
              {item.label}
            </button>
          ))}
        </div>
      )}

      {!meta ? (
        <div className="pending-box" style={{ marginTop: 12 }}>{metaError || '正在读取模型清单……'}</div>
      ) : !state?.loaded ? (
        <div className="pending-box" style={{ marginTop: 12 }}>
          {state?.error || (state?.loading ? '正在读取本期已保存的选择……' : '尚未读取本期已保存的选择。')}
          {state?.error && <button type="button" className="btn" onClick={onReload} style={{ marginLeft: 10 }}>重新读取</button>}
        </div>
      ) : !meta?.available ? (
        <div className="pending-box" style={{ marginTop: 12 }}>预测数据随报告一起产出——先完成一次生成，这里就会出现候选学科。</div>
      ) : (
        <>
          <div className="tablewrap" style={{ marginTop: 12 }}>
            <table>
              <thead><tr><th>潜力学科</th><th>V1 基线推荐</th><th>本期已选</th><th>模型说明</th></tr></thead>
              <tbody>
                {subjects.map((subject) => {
                  const rec = meta.recommendations?.[currentRoute]?.[subject] ?? ''
                  const mine = state.choice[currentRoute]?.[subject] ?? ''
                  const actual = mine || rec
                  return (
                    <tr key={subject}>
                      <td>{subject}</td>
                      <td>{rec || 'V1 基线推荐'}</td>
                      <td>
                        <b>{actual || '—'}</b>
                        <span className="mdesc" style={{ color: mine ? 'var(--zhu)' : 'var(--ink-3)' }}>
                          {mine ? '已改选' : '跟随 V1 推荐'}
                        </span>
                      </td>
                      <td><span className="mdesc">{MODEL_DESC[actual] ?? '由 V1 基线按学科指定。'}</span></td>
                    </tr>
                  )
                })}
                {subjects.length === 0 && <tr><td colSpan={4} style={{ color: 'var(--ink-3)' }}>接口暂未返回候选学科。</td></tr>}
              </tbody>
            </table>
          </div>

          <div style={{ display: 'flex', alignItems: 'center', gap: 12, flexWrap: 'wrap', marginTop: 14, paddingTop: 13, borderTop: '1px solid var(--line-2)' }}>
            <a className="btn primary" href={`/app/?view=forecast${period ? `&period=${encodeURIComponent(period)}` : ''}`}>
              去预测台看图改选 →
            </a>
            {dirty ? (
              <>
                <span role="status" className="hint" style={{ color: 'var(--warn)', fontWeight: 650 }}>
                  有未保存修改（在预测台改的）——保存后才可开始生成。
                </span>
                <ConfirmButton className="btn" confirmText="确认放弃？会回到上次保存的版本" onConfirm={onReload}>放弃修改并重新读取</ConfirmButton>
              </>
            ) : (
              <span role="status" className="hint" style={{ color: 'var(--ok)' }}>
                {state?.error || `已保存${state?.by ? ` · ${state.by}` : ''}${state?.at ? ` · ${state.at}` : ''} · 未改选的学科使用 V1 推荐`}
              </span>
            )}
          </div>
        </>
      )}

      <div className="degraded"><b>与报告的关系</b>：任务启动时固定读取本期已保存选择。选择在本期报告进入预测章的学科上生效；所选模型若无法运行，仍按现有规则回退 V1 推荐并留下提醒。</div>
    </section>
  )
}

export function Workbench({
  period, me, wb, err, healthy, run, approvalStatus, runApprovalStatus, activityState,
  actionLockReason, activeRun, actionsLocked, submitting, onGenerate,
  periods, forecastMeta, forecastMetaError, actualOutputPeriod, forecastChoice, forecastChoiceDirty,
  onPickPeriod, onReloadForecastChoice,
}: {
  period: string | null
  me: Me | null
  wb: WB
  err: ApiError | null
  healthy: boolean
  run?: Run | null
  approvalStatus: string
  runApprovalStatus: string
  activityState: ActivityState
  actionLockReason: string | null
  activeRun: boolean
  actionsLocked: boolean
  submitting: boolean
  onGenerate: () => void
  periods: Period[]
  forecastMeta: ForecastMeta | null
  forecastMetaError: string
  actualOutputPeriod: string | null
  forecastChoice: ForecastChoiceEntry | null
  forecastChoiceDirty: boolean
  onPickPeriod: (period: string) => void
  onReloadForecastChoice: () => void
}) {
  const canGenerate = me?.role === 'admin' && period != null && /^\d{6}$/.test(period) && !actionsLocked && !activeRun && !submitting
    && (!run || isTerminal(run.status ?? undefined))
  const hasGenerateAction = wb.focusAction === 'generate' || wb.focusAction === 'rerun'

  return (
    <>
      <section className="card">
        <div className="steps">
          <h1>{period ?? '（选择期次）'}</h1>
          <span className="tag">{STATE_LABEL[wb.state]}</span>
          <Steps wb={wb} />
        </div>

        <div className="focus" style={{ margin: '0 24px 22px' }}>
          <div>
            <div className="big">{wb.focusTitle}</div>
            <div className="sub">{wb.focusSub}</div>
          </div>
          <div className="cta">
            {wb.focusAction === 'generate' && (
              <>
                <span className="hint">约 20 秒</span>
                <button className="btn primary" onClick={onGenerate} disabled={!canGenerate}>
                  <Icon name="play" size={20} />开始生成
                </button>
              </>
            )}
            {wb.focusAction === 'rerun' && (
              <ConfirmButton className="btn" disabled={!canGenerate}
                             confirmText="确认重跑？会撤下当前成品" onConfirm={onGenerate}>
                <Icon name="refresh" size={20} />重新生成
              </ConfirmButton>
            )}
            {wb.focusAction === 'sign' && (
              <a className="btn primary" href={`/app/?view=review${period ? `&period=${encodeURIComponent(period)}` : ''}`}><Icon name="seal" size={20} />复核并签单</a>
            )}
            {wb.focusAction === 'open' && (
              <a className="btn" href={`/app/?view=report${period ? `&period=${encodeURIComponent(period)}` : ''}`}><Icon name="doc" size={20} />打开报告</a>
            )}
          </div>
        </div>

        {!canGenerate && hasGenerateAction && (
          <p className="hint" style={{ padding: '0 24px 18px' }}>
            {actionLockReason ?? (me == null
              ? <>系统暂时无法确认你的身份，为保护数据，生成按钮暂时不能使用。</>
              : me.role === 'admin'
                ? <>先选择一期，再开始生成。</>
                : <>当前账号是<b>游客</b>：只能看报告目录与成品，不能生成或编辑。</>)}
        </p>
        )}

        {run ? <LiveRun run={run} approvalStatus={runApprovalStatus} />
          : activeRun ? (
            <div className="elapsed"><Icon name="refresh" size={20} />正在读取当前任务状态，完成后才能开始新的生成。</div>
          ) : wb.state === 'running' ? <Progress /> : null}
        <Banners wb={wb} err={err} healthy={healthy} onRerun={onGenerate} canRerun={canGenerate} period={period}
          approvalStatus={approvalStatus} />

        {activityState === 'unknown' && !hasGenerateAction && (
          <p className="hint" style={{ padding: '0 24px 18px' }}>{actionLockReason}</p>
        )}

        {wb.note && (
          <div style={{ padding: '0 24px 20px' }}>
            <div className="degraded">{wb.note}</div>
          </div>
        )}
      </section>

      <ModelSummary period={period} periods={periods} meta={forecastMeta} metaError={forecastMetaError}
                    actualOutputPeriod={actualOutputPeriod} state={forecastChoice}
                    dirty={forecastChoiceDirty} onPickPeriod={onPickPeriod}
                    onReload={onReloadForecastChoice} />
    </>
  )
}

export type { WBState, Period, PeriodDetail }
