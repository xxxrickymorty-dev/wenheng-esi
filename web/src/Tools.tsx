/* 生成台工具卡（阶段 1 · P1 收尾）：上传新台账 / 扫码在手机上看 / 产物下载 / 重跑本期。
   数据源都是现成的：POST /api/jobs（带 file 字段）· /qr.png · GET /api/jobs/{id}/artifacts ·
   POST /api/jobs/{id}/rerun（老站 job.js 一直在用）。🔴 只透传，不编造。 */

import { useEffect, useState } from 'react'
import {
  choosePeriodJobId, getJob, getPeriodArtifacts, getPeriodDetail,
  postJobWithFile, rerunJob,
  type Artifact, type Job,
} from './api'
import { Icon } from './icons'
import { Waterfall } from './Waterfall'

type PeriodJobView = {
  period: string | null
  propJobId: string | null
  effJobId: string | null
  artifacts: Artifact[] | null
  loading: boolean
  note: string | null
}

export function Tools({ period, jobId, onUploaded }: {
  period: string | null
  jobId: string | null
  onUploaded: (jobId: string, period: string) => void
}) {
  const [file, setFile] = useState<File | null>(null)
  const [newPeriod, setNewPeriod] = useState('')
  const [busy, setBusy] = useState(false)
  const [msg, setMsg] = useState<{ period: string | null; ok: boolean; text: string } | null>(null)
  const [rerunning, setRerunning] = useState(false)
  const [jobView, setJobView] = useState<PeriodJobView>({
    period: null, propJobId: null, effJobId: null, artifacts: null,
    loading: false, note: null,
  })
  const currentView = jobView.period === period && jobView.propJobId === jobId
    ? jobView
    : null
  const effJobId = currentView?.effJobId ?? null
  const message = msg?.period === period ? msg : null

  /* 任务按请求期次选；文件列表从精确期次目录读取。 */
  useEffect(() => {
    let alive = true
    const emptyView: PeriodJobView = {
      period, propJobId: jobId, effJobId: null, artifacts: null,
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
  }, [period, jobId])

  async function upload() {
    const actionPeriod = period
    if (!file) { setMsg({ period: actionPeriod, ok: false, text: '先选一个台账文件（.xlsx）。' }); return }
    if (!/^\d{6}$/.test(newPeriod.trim())) { setMsg({ period: actionPeriod, ok: false, text: '期次要填 6 位数，如 202609。' }); return }
    setBusy(true); setMsg(null)
    try {
      const r = await postJobWithFile(newPeriod.trim(), file)
      onUploaded(r.job_id, newPeriod.trim())
      setMsg({ period: actionPeriod, ok: true, text: `已开始生成 ${newPeriod.trim()}——进度就在上面。` })
      setFile(null); setNewPeriod('')
    } catch (e) {
      const h = e as { status?: number; body?: { error?: string; hint?: string }; message?: string }
      setMsg({ period: actionPeriod, ok: false, text: (h.body?.error ?? h.message ?? '上传失败') + (h.body?.hint ? `（${h.body.hint}）` : '') })
    } finally { setBusy(false) }
  }

  async function rerun() {
    const id = effJobId
    const actionPeriod = period
    if (!id || !actionPeriod) return
    setRerunning(true); setMsg(null)
    try {
      const r = await rerunJob(id)
      onUploaded(r.job_id ?? id, actionPeriod)
      setMsg({ period: actionPeriod, ok: true, text: '已重新开始——旧稿会撤到 _superseded/，不会悄悄覆盖。' })
    } catch (e) {
      const h = e as { status?: number; body?: { error?: string; hint?: string }; message?: string }
      setMsg({ period: actionPeriod, ok: false, text: (h.body?.error ?? h.message ?? '重跑失败') + (h.body?.hint ? `（${h.body.hint}）` : '') })
    } finally { setRerunning(false) }
  }

  return (
    <section className="card" style={{ marginTop: 18, padding: '18px 22px' }}>
      <h2 style={{ fontSize: 19, display: 'flex', alignItems: 'center', gap: 10 }}>
        <Icon name="doc" size={21} />这一期的工具
      </h2>

      <div style={{ display: 'grid', gap: 18, gridTemplateColumns: 'minmax(0,1fr) 190px', marginTop: 12 }}>
        <div>
          {/* 上传新台账（老站同一套口径：期次 6 位必填） */}
          <h3 style={{ fontSize: 15 }}>上传新台账</h3>
          <p className="hint" style={{ marginTop: 4 }}>
            贴好表的《监测表.xlsx》直接传上来就能跑；期次填 6 位（如 202609）。
          </p>
          <div className="toolbar">
            <input type="file" accept=".xlsx"
                   onChange={(e) => setFile(e.target.files?.[0] ?? null)} />
            <input className="search" style={{ maxWidth: 150 }} value={newPeriod}
                   onChange={(e) => setNewPeriod(e.target.value)} placeholder="期次 202609" />
            <button className="btn" onClick={upload} disabled={busy || rerunning}>
              <Icon name="refresh" size={19} />{busy ? '正在上传……' : '上传并生成'}
            </button>
          </div>

          {/* 产物下载 + 重跑 */}
          <h3 style={{ fontSize: 15, marginTop: 18 }}>产物与重跑</h3>
          {!period ? (
            <p className="hint" style={{ marginTop: 4 }}>先选一期，再查看这一期的产物。</p>
          ) : currentView?.note ? (
            <p className="hint" style={{ marginTop: 4 }}>{currentView.note}</p>
          ) : !currentView || currentView.loading ? (
            <p className="hint" style={{ marginTop: 4 }}>正在读取这一期的产物……</p>
          ) : !currentView.artifacts || currentView.artifacts.length === 0 ? (
            <p className="hint" style={{ marginTop: 4 }}>这一期暂时没有产物。</p>
          ) : (
            <div className="chips" style={{ marginTop: 8 }}>
              {currentView.artifacts.map((a) => (
                <a className="pill" key={a.key} href={a.url}
                   {...(a.key && !['red_view', 'collation'].includes(a.key) ? { download: '' } : {})}>
                  {a.name}{a.size ? ` · ${a.size}` : ''}
                </a>
              ))}
            </div>
          )}
          {period && effJobId && (
            <div className="toolbar">
              <button className="btn" onClick={rerun} disabled={busy || rerunning}
                      title="按同一期台账再跑一遍；旧稿撤到 _superseded/（可回滚）">
                <Icon name="refresh" size={19} />{rerunning ? '正在重跑……' : '重跑本期'}
              </button>
              {message && <span className="hint" style={{ color: message.ok ? 'var(--ok)' : 'var(--bad)' }}>{message.text}</span>}
            </div>
          )}
          {message && !(period && effJobId) && <p className="hint" style={{ color: message.ok ? 'var(--ok)' : 'var(--bad)' }}>{message.text}</p>}
        </div>

        {/* 扫码在手机上看 */}
        <div style={{ textAlign: 'center' }}>
          <h3 style={{ fontSize: 15 }}>手机上接着看</h3>
          <img src="/qr.png" alt="扫码打开本页" width={150} height={150}
               style={{ marginTop: 8, border: '1px solid var(--line)', borderRadius: 'var(--r-sm)', background: '#fff' }} />
          <p className="hint" style={{ marginTop: 6, fontSize: 13 }}>扫一下，同一页在手机上打开</p>
        </div>
      </div>

      {/* 这次运行每一步用了多久（跑完也能回看；生成中自动刷新） */}
      {period && effJobId && <Waterfall jobId={effJobId} />}

      {period && (
        <p className="hint" style={{ marginTop: 10 }}>
          <a href={`/app/?view=archive&period=${encodeURIComponent(period)}`}>
            看这一期的运行档案（状态回放 / 审计结论 / 下载日志包）→
          </a>
        </p>
      )}
    </section>
  )
}
