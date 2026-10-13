/* 生成台工具卡（阶段 1 · P1 收尾）：上传当期数据表 / 产物下载 / 重跑本期。
   数据源都是现成的：POST /api/jobs（带 file 字段）· GET /api/jobs/{id}/artifacts ·
   POST /api/jobs/{id}/rerun（老站 job.js 一直在用）。🔴 只透传，不编造。 */

import { useEffect, useState } from 'react'
import {
  getJob, getPeriodArtifacts, getPeriodDetail,
  getRollbackPoints, humanSize, postJobWithFile, rerunJob, rollbackPeriod,
  type Artifact, type Job, type RollbackPoint,
} from './api'
import { ConfirmButton } from './ConfirmButton'
import { Icon } from './icons'
import { choosePeriodJobId } from './lib/run'
import { appHref } from './lib/status'
import { Waterfall } from './Waterfall'

/** 留档目录名 20260928T083041 → 09-28 08:30 */
function fmtPoint(id: string): string {
  const m = id.match(/^(\d{4})(\d{2})(\d{2})T(\d{2})(\d{2})/)
  return m ? `${m[2]}-${m[3]} ${m[4]}:${m[5]}` : id
}

type PeriodJobView = {
  period: string | null
  propJobId: string | null
  refreshToken: number
  effJobId: string | null
  artifacts: Artifact[] | null
  loading: boolean
  note: string | null
}

export function Tools({
  period, jobId, approvalStatus, actionsLocked, actionLockReason,
  onActionStart, onActionEnd, onUploaded, refreshToken = 0,
}: {
  period: string | null
  jobId: string | null
  approvalStatus: string
  actionsLocked: boolean
  actionLockReason: string | null
  onActionStart: (action: 'upload' | 'rerun' | 'rollback') => boolean
  onActionEnd: (action: 'upload' | 'rerun' | 'rollback') => void
  onUploaded: (jobId: string, period: string) => void
  refreshToken?: number
}) {
  const [file, setFile] = useState<File | null>(null)
  const [newPeriod, setNewPeriod] = useState('')
  const [busy, setBusy] = useState(false)
  const [msg, setMsg] = useState<{ period: string | null; ok: boolean; text: string } | null>(null)
  const [rerunning, setRerunning] = useState(false)
  const [jobView, setJobView] = useState<PeriodJobView>({
    period: null, propJobId: null, refreshToken: -1, effJobId: null, artifacts: null,
    loading: false, note: null,
  })
  const currentView = jobView.period === period && jobView.propJobId === jobId && jobView.refreshToken === refreshToken
    ? jobView
    : null
  const effJobId = currentView?.effJobId ?? null
  const message = msg?.period === period ? msg : null
  const [points, setPoints] = useState<RollbackPoint[]>([])
  const [point, setPoint] = useState('')
  const [localRefresh, setLocalRefresh] = useState(0)

  /* 回滚点（票 07）：切期次/操作后重取；没有留档就整块不显示。 */
  useEffect(() => {
    if (!period) { setPoints([]); setPoint(''); return }
    let alive = true
    getRollbackPoints(period)
      .then((ps) => {
        if (!alive) return
        setPoints(ps)
        setPoint((cur) => (ps.some((p) => p.id === cur) ? cur : ps[0]?.id ?? ''))
      })
      .catch(() => { if (alive) setPoints([]) })
    return () => { alive = false }
  }, [period, localRefresh])

  /* 任务按请求期次选；文件列表从精确期次目录读取。 */
  useEffect(() => {
    let alive = true
    const emptyView: PeriodJobView = {
      period, propJobId: jobId, refreshToken, effJobId: null, artifacts: null,
      loading: !!period, note: null,
    }
    if (!period) return () => { alive = false }

    const artifactsRequest = getPeriodArtifacts(period)
      .then((artifacts) => ({ artifacts, note: null as string | null }))
      .catch(() => ({ artifacts: null, note: '读取这一期的产物失败。' }))

    const taskRequest = (async () => {
      let detail: Awaited<ReturnType<typeof getPeriodDetail>>
      try {
        detail = await getPeriodDetail(period)
      } catch {
        return null
      }
      if (!alive) return null

      let candidate: Job | null = null
      if (jobId) {
        try {
          candidate = await getJob(jobId)
        } catch {
          candidate = null
        }
      }
      if (!alive) return null

      return choosePeriodJobId(
        period, detail?.period ?? period, jobId, candidate, detail?.lastJob?.id ?? null,
      )
    })()

    ;(async () => {
      const [id, result] = await Promise.all([taskRequest, artifactsRequest])
      if (alive) {
        setJobView({
          ...emptyView, effJobId: id, artifacts: result.artifacts,
          loading: false, note: result.note,
        })
      }
    })()
    return () => { alive = false }
  }, [period, jobId, refreshToken, localRefresh])

  async function upload() {
    if (actionsLocked || busy || rerunning) return
    const actionPeriod = period
    if (!file) { setMsg({ period: actionPeriod, ok: false, text: '先选一个台账文件（.xlsx）。' }); return }
    if (!/^\d{6}$/.test(newPeriod.trim())) { setMsg({ period: actionPeriod, ok: false, text: '期次要填 6 位数，如 202609。' }); return }
    if (!onActionStart('upload')) return
    setBusy(true); setMsg(null)
    try {
      const r = await postJobWithFile(newPeriod.trim(), file)
      onUploaded(r.job_id, newPeriod.trim())
      setMsg({ period: actionPeriod, ok: true, text: `已开始生成 ${newPeriod.trim()}——进度就在上面。` })
      setFile(null); setNewPeriod('')
    } catch (e) {
      const h = e as { status?: number; body?: { error?: string; hint?: string }; message?: string }
      setMsg({ period: actionPeriod, ok: false, text: (h.body?.error ?? h.message ?? '上传失败') + (h.body?.hint ? `（${h.body.hint}）` : '') })
    } finally {
      setBusy(false)
      onActionEnd('upload')
    }
  }

  async function rerun() {
    if (actionsLocked || busy || rerunning) return
    const id = effJobId
    const actionPeriod = period
    if (!id || !actionPeriod) return
    if (!onActionStart('rerun')) return
    setRerunning(true); setMsg(null)
    try {
      const r = await rerunJob(id)
      onUploaded(r.job_id ?? id, actionPeriod)
      setMsg({ period: actionPeriod, ok: true, text: '已重新开始——旧稿会先撤下（可回滚），不会悄悄覆盖。' })
    } catch (e) {
      const h = e as { status?: number; body?: { error?: string; hint?: string }; message?: string }
      setMsg({ period: actionPeriod, ok: false, text: (h.body?.error ?? h.message ?? '重跑失败') + (h.body?.hint ? `（${h.body.hint}）` : '') })
    } finally {
      setRerunning(false)
      onActionEnd('rerun')
    }
  }

  async function rollback() {
    if (actionsLocked || busy || rerunning) return
    const actionPeriod = period
    if (!actionPeriod || !point) return
    if (!onActionStart('rollback')) return
    setRerunning(true); setMsg(null)
    try {
      const r = await rollbackPeriod(actionPeriod, point)
      setMsg({ period: actionPeriod, ok: true,
               text: `已回滚到 ${fmtPoint(point)}（${r.restored.length} 个文件）；回滚前的成品已另存留档，报告变了以后签名需重签。` })
      setLocalRefresh((n) => n + 1)
    } catch (e) {
      const h = e as { status?: number; body?: { error?: string; hint?: string }; message?: string }
      setMsg({ period: actionPeriod, ok: false, text: (h.body?.error ?? h.message ?? '回滚失败') + (h.body?.hint ? `（${h.body.hint}）` : '') })
    } finally {
      setRerunning(false)
      onActionEnd('rollback')
    }
  }

  return (
    <section className="card mt-18 pad-18-22" id="tools">
      {actionsLocked && actionLockReason && (
        <p className="hint mt-8">{actionLockReason}</p>
      )}

      <div className="mt-12">
        <div>
          {/* 上传当期数据表（老站同一套口径：期次 6 位必填） */}
          <h3 className="fs-15">上传当期数据表</h3>
          <div className="toolbar">
            <input type="file" accept=".xlsx" aria-label="选择要上传的当期数据表（xlsx）"
                   onChange={(e) => setFile(e.target.files?.[0] ?? null)} />
            <input className="search maxw-150" value={newPeriod} aria-label="新期次（六位数字）"
                   onChange={(e) => setNewPeriod(e.target.value)} placeholder="期次 202609" />
            <ConfirmButton className="btn" disabled={actionsLocked || busy || rerunning}
                           confirmText="确认上传？会覆盖本期的核对副本"
                           onConfirm={upload}>
              <Icon name="refresh" size={19} />{busy ? '正在上传……' : '上传并生成'}
            </ConfirmButton>
          </div>

          {/* 产物下载 + 重跑 */}
          <h3 className="fs-15 mt-18">产物与重跑</h3>
          {!period ? (
            <p className="hint mt-4">先选一期。</p>
          ) : currentView?.note ? (
            <p className="hint mt-4">{currentView.note}</p>
          ) : !currentView || currentView.loading ? (
            <p className="hint mt-4">正在读取……</p>
          ) : !currentView.artifacts || currentView.artifacts.length === 0 ? (
            <p className="hint mt-4">还没有产物，先「开始生成」。</p>
          ) : (
            <div className="chips mt-8">
              {currentView.artifacts.map((a) => (
                a.key === 'report' && approvalStatus !== 'signed'
                  ? <span className="pill" key={a.key} role="note" aria-disabled="true">
                      {a.name}{a.size ? ` · ${humanSize(a.size)}` : ''} · 未签发，管理员暂不能下载
                    </span>
                  : <a className="pill" key={a.key} href={a.url}
                       {...(a.key && !['red_view', 'collation'].includes(a.key) ? { download: '' } : {})}>
                      {a.key === 'diagnosis' ? '校验说明' : a.name}{a.size ? ` · ${humanSize(a.size)}` : ''}
                    </a>
              ))}
            </div>
          )}
          {period && effJobId && (
            <div className="toolbar">
              <ConfirmButton className="btn" disabled={actionsLocked || busy || rerunning}
                             confirmText="确认重跑？会撤下当前成品"
                             title="按同一期台账再跑一遍；旧稿先撤下、可回滚"
                             onConfirm={rerun}>
                <Icon name="refresh" size={19} />{rerunning ? '正在重跑……' : '重跑本期'}
              </ConfirmButton>
              {message && <span className="hint" style={{ color: message.ok ? 'var(--ok)' : 'var(--bad)' }}>{message.text}</span>}
            </div>
          )}
          {period && points.length > 0 && (
            <div className="toolbar mt-10">
              <span className="hint">旧版留档</span>
              <select value={point} onChange={(e) => setPoint(e.target.value)} aria-label="选择要回滚到的版本"
                      style={{ maxWidth: 220, padding: '7px 10px', border: '1px solid var(--line)',
                               borderRadius: 8, background: 'var(--card)', color: 'var(--ink)', font: 'inherit' }}>
                {points.map((p) => <option key={p.id} value={p.id}>{fmtPoint(p.id)} · {p.files.length} 个文件</option>)}
              </select>
              <ConfirmButton className="btn" disabled={actionsLocked || busy || rerunning}
                             confirmText="确认回滚？当前成品会先撤下"
                             onConfirm={rollback}>
                <Icon name="refresh" size={19} />回滚到这一版
              </ConfirmButton>
            </div>
          )}
          {message && !(period && effJobId) && <p className="hint" style={{ color: message.ok ? 'var(--ok)' : 'var(--bad)' }}>{message.text}</p>}
        </div>
      </div>

      {/* 这次运行每一步用了多久（跑完也能回看；生成中自动刷新） */}
      {period && effJobId && <Waterfall jobId={effJobId} />}

      {period && (
        <p className="hint mt-10">
          <a href={appHref('archive', period)}>
            看这一期运行档案 →
          </a>
        </p>
      )}
    </section>
  )
}
