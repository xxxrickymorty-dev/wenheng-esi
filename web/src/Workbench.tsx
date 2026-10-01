/* 生成台（工作台）——工具面。
   第一屏＝「这一期现在到哪一步、下一步做什么」；全屏只有一处朱色实心焦点。
   设计取自静态稿 mockups/v2-工作台与报告.html；状态与文案规格见 web/UX-生成台.md。 */

import type { ApiError, Me, Period, PeriodDetail } from './api'
import { formatProvenanceTime, type ForecastChoiceEntry, type ForecastMeta } from './api-forecast'
import { useState } from 'react'
import { ConfirmButton } from './ConfirmButton'
import { taskLabel as runStatusText } from './lib/status'
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
              ? <a className="steplink" href={acquireHref} title="去取数台">{s.title}</a>
              : s.title}
            <small>{s.detail}</small>
          </span>
        </li>
      ))}
    </ol>
  )
}

/** 真实生成过程：任务状态与本期审批状态分开显示。
    （原先的「五步假进度」演示组件已删——固定百分比属于编造，违反只透传红线，2026-09-29） */
function LiveRun({ run, approvalStatus }: { run: Run; approvalStatus: string }) {
  const [open, setOpen] = useState(false)
  const approvalLabel = approvalStatus === 'signed' ? '已签发'
    : approvalStatus === 'stale' ? '签名已失效' : '未签发'
  const connectionLabel = run.connection === 'live' ? '页面正在更新进度'
    : run.connection === 'snapshot' ? '正在读取任务进度'
      : run.connection === 'reconnecting' ? '连接中断，正在恢复进度'
        : '暂时连不上服务，页面会继续更新进度'
  /* 一条工具栏：任务 / 签单状态 / 看详细过程（rick 2026-09-29：原来三行各占一行、右侧全空） */
  return (
    <>
      <div className="runbar">
        <span className="elapsed" aria-live="polite">
          <Icon name="refresh" size={19} />
          {`任务：${run.status ? runStatusText(run.status) : '正在读取状态'} · 期次 ${run.requestedPeriod}${run.outputPeriod && run.outputPeriod !== run.requestedPeriod ? `（实际输出 ${run.outputPeriod}）` : ''} · ${connectionLabel}`}
        </span>
        <span className="runbar-state">签单状态<b>{approvalLabel}</b></span>
        <button className="btn runbar-log" onClick={() => setOpen(!open)}>
          <Icon name="list" size={17} />{open ? '收起日志' : '看详细过程'}
        </button>
      </div>
      {open && (
        <div className="runlog">
          <p className="hint" style={{ marginBottom: 8 }}>
            最新进度：{run.last ?? '（进度还未返回…）'}
          </p>
          <pre>{run.lines.length ? run.lines.join('\n') : '（暂无日志行）'}</pre>
        </div>
      )}
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
    : approvalStatus === 'stale' ? '签名已失效' : '未签发'
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
            <li>本期签单状态：{approvalLabel}。</li>
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
        <span><b className="title">待签单</b><span>报告已出，等你在审核台签单。</span></span>
      </div>
    )
  }
  if (wb.state === 'done' || wb.state === 'signed') {
    return (
      <div className="banner ok">
        <span className="ico"><Icon name="check" size={22} /></span>
        <span>
          <b className="title">{wb.state === 'signed' ? '本期已签发' : '本期报告已生成'}</b>
          <span>本期签单状态：{approvalLabel}。{approvalStatus === 'signed'
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
    : '现有记录无法确认上游台账是否已进入预测所用数据。预测预览仍读取下方所示的预测数据。'
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
          期次
          <select id="workbench-task-period" value={period ?? ''} onChange={(e) => onPickPeriod(e.target.value)}
                  style={{ minWidth: 170, padding: '5px 9px', border: '1px solid var(--line)', borderRadius: 7, background: 'var(--card)', color: 'var(--ink)', font: 'inherit', fontSize: 16 }}>
            {!period && <option value="">请选择期次</option>}
            {periods.map((item) => <option key={item.period} value={item.period}>{item.period}</option>)}
            {period && !periods.some((item) => item.period === period) && <option value={period}>{period}</option>}
          </select>
        </label>
        <div style={{ minWidth: 160 }}>
          <small style={{ display: 'block', color: 'var(--ink-3)', fontSize: 13 }}>预测数据</small>
          <strong style={{ fontFamily: 'var(--mono)', fontSize: 16 }}>{meta?.source_period || '未就绪'}</strong>
        </div>
        <div style={{ minWidth: 190 }}>
          <small style={{ display: 'block', color: 'var(--ink-3)', fontSize: 13 }}>实际输出</small>
          <strong style={{ color: 'var(--gold-ink)', fontSize: 15 }}>{actualOutputPeriod || '任务完成后显示'}</strong>
        </div>
        <div style={{ minWidth: 260, flex: 1 }}>
          <small style={{ display: 'block', color: 'var(--ink-3)', fontSize: 13 }}>台账文件</small>
          <strong style={{ fontSize: 14 }}>{source?.name ?? '云大全学科排名、阈值动态检测表.xlsx'}</strong>
          <span style={{ display: 'block', color: 'var(--ink-3)', fontSize: 13 }}>
            最后修改（北京时间）：{sourceTime ? formatProvenanceTime(sourceTime) : '本机未找到'}
          </span>
        </div>
      </div>

      <div className="degraded" style={{ borderLeft: meta?.data_freshness === 'needs_check' ? '3px solid var(--gold)' : undefined }}>
        <b>期次与数据说明</b>：{freshnessText} 现有记录无法确认主台账是否被预测流程读取。V1 推荐的基线是 {meta?.recommendation_baseline ?? '—'}，它不是预测数据期次。
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
              <thead><tr><th>潜力学科</th><th>V1 推荐</th><th>本期已选</th><th>模型说明</th></tr></thead>
              <tbody>
                {subjects.map((subject) => {
                  const rec = meta.recommendations?.[currentRoute]?.[subject] ?? ''
                  const mine = state.choice[currentRoute]?.[subject] ?? ''
                  const actual = mine || rec
                  return (
                    <tr key={subject}>
                      <td>{subject}</td>
                      <td>{rec || 'V1 推荐'}</td>
                      <td>
                        <b>{actual || '—'}</b>
                        <span className="mdesc" style={{ color: mine ? 'var(--zhu)' : 'var(--ink-3)' }}>
                          {mine ? '已改选' : '跟随 V1 推荐'}
                        </span>
                      </td>
                      <td><span className="mdesc">{MODEL_DESC[actual] ?? '由 V1 推荐按学科指定。'}</span></td>
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
                  有未保存修改——保存后才能开始生成。
                </span>
                <ConfirmButton className="btn" confirmText="确认放弃？会回到上次保存的版本" onConfirm={onReload}>放弃修改并重新读取</ConfirmButton>
              </>
            ) : (
              <span role="status" className="hint" style={{ color: 'var(--ok)' }}>
                {state?.error || `已保存${state?.by ? ` · ${state.by}` : ''}${state?.at ? ` · ${state.at}` : ''}`}
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
          <Steps wb={wb} period={period} />
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
            {wb.focusAction === 'acquire' && (
              <a className="btn primary" href={`/app/?view=acquire${period ? `&period=${encodeURIComponent(period)}` : ''}`}>
                <Icon name="download" size={20} />去取数
              </a>
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
          <p className="hint" style={{ padding: '0 24px 18px' }}>{actionLockReason}</p>
        )}

        {wb.note && (
          <div style={{ padding: '0 24px 20px' }}>
            <div className="degraded">{wb.note}</div>
          </div>
        )}
      </section>

      <details className="fold">
        <summary>本期模型 · 预测选模（只读）<span className="sm">改选去预测台</span></summary>
        <ModelSummary period={period} periods={periods} meta={forecastMeta} metaError={forecastMetaError}
                      actualOutputPeriod={actualOutputPeriod} state={forecastChoice}
                      dirty={forecastChoiceDirty} onPickPeriod={onPickPeriod}
                      onReload={onReloadForecastChoice} />
      </details>
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
      <section className="card tablewrap" style={{ marginTop: 18 }}>
        <table className="periods">
          <thead>
            <tr>
              <th>期次</th><th>目录名</th><th>状态</th><th style={{ width: 90 }}>操作</th>
            </tr>
          </thead>
          <tbody>
            {periods.length === 0 && (
              <tr><td colSpan={4} style={{ color: 'var(--ink-3)' }}>
                {healthy === false ? (
                  <>服务未启动，读不到期次。起好服务后
                    <button className="btn" style={{ padding: '4px 10px', fontSize: 13.5, margin: '0 6px' }}
                            onClick={() => location.reload()}>重新检查</button>
                    一次。</>
                ) : (
                  <>还没有任何期次。先在下方「这一期的工具」上传监测表，生成第一期。<a href="#tools">去上传 →</a></>
                )}
              </td></tr>
            )}
            {periods.map((p) => (
              <tr key={p.period} className="period-row"
                  onClick={() => onPick(p.period)}
                  style={{ background: p.period === selected ? 'var(--panel)' : undefined }}>
                <td><button type="button" className="rowbtn">{p.label}</button></td>
                <td className="mono">{p.period}</td>
                <td>
                  <span className={`pill ${p.status === 'signed' ? 'signed' : p.status === 'stale' ? 'stale' : 'unsigned'}`}>
                    {p.status === 'signed' ? '已签发' : p.status === 'stale' ? '签名已失效' : '未签发'}
                  </span>
                </td>
                <td>
                  <a href={`/app/?view=report&period=${encodeURIComponent(p.period)}`}
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

/** 说明 · 口径、来源与只读声明（全站仅此一份；rick 2026-09-30 定，2026-10-01 从 App 抽出） */
export function SiteNote() {
  return (
    <details className="fold">
      <summary>说明 · 口径、来源与只读声明<span className="sm">全站仅此一份</span></summary>
      <p className="hint" style={{ padding: '2px 18px 16px', fontSize: 13.5, lineHeight: 1.9 }}>
        ① 数字只来自馆员维护的台账与派生产物，运行期大模型不进入数据路径；
        ② 本页是只读视图，不修改台账与报告；③ 预测章按「本期已选」的已保存选择执行，未列学科用 V1 推荐；
        ④ 期次与状态以任务记录为准，未签发报告不可下载。来源：期内产物目录 · 运行档案 · 预测选模配置。
      </p>
    </details>
  )
}

export type { WBState, Period, PeriodDetail }
