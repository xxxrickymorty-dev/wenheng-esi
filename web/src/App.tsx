/* 文衡 · 工作台（外壳）
   一个应用两屏：工作台（工具面，本文件）→ 陈列馆（G 的体验，挂在 /app/shelf/）。
   数据全部来自后端 API；接口没就绪的地方**如实标注"未就绪"**，不编数据。 */

import { useEffect, useMemo, useState } from 'react'
import {
  getHealth, getMe, getPeriodDetail, getPeriods, postJob,
  type ApiError, type Me, type Period, type PeriodDetail,
} from './api'
import { Icon, Sprite } from './icons'
import { Workbench } from './Workbench'
import { deriveWorkbench, type WBState } from './wb'

const DEMO_STATES: WBState[] = ['empty', 'ready', 'running', 'done', 'fail-ledger', 'fail-other', 'stalled', 'signed']

export default function App() {
  const [healthy, setHealthy] = useState<boolean | null>(null)
  const [me, setMe] = useState<Me | null>(null)
  const [periods, setPeriods] = useState<Period[]>([])
  const [selected, setSelected] = useState<string | null>(null)
  const [detail, setDetail] = useState<PeriodDetail | null>(null)
  const [err, setErr] = useState<ApiError | null>(null)
  const [busy, setBusy] = useState(false)

  const demo = useMemo(() => {
    const v = new URLSearchParams(location.search).get('demo') as WBState | null
    return v && DEMO_STATES.includes(v) ? v : null
  }, [])

  useEffect(() => {
    let alive = true
    ;(async () => {
      const ok = await getHealth()
      if (!alive) return
      setHealthy(ok)
      if (!ok) return
      setMe(await getMe())
      try {
        const list = await getPeriods()
        if (!alive) return
        setPeriods(list)
        setSelected(list[0]?.period ?? null)
      } catch (e) {
        if (alive) setErr(e as ApiError)
      }
    })()
    return () => { alive = false }
  }, [])

  useEffect(() => {
    if (!selected) { setDetail(null); return }
    let alive = true
    getPeriodDetail(selected).then((d) => { if (alive) setDetail(d) })
    return () => { alive = false }
  }, [selected])

  const wb = deriveWorkbench(selected, periods, detail, healthy === true, demo)

  async function onGenerate() {
    if (!selected) return
    setBusy(true)
    setErr(null)
    try {
      await postJob(selected)
    } catch (e) {
      const h = e as { status?: number; body?: ApiError; message?: string }
      setErr(h.body ?? { error: h.message ?? '生成请求失败' })
    } finally {
      setBusy(false)
    }
  }

  return (
    <>
      <Sprite />
      <header className="topbar">
        <div className="brand">
          <strong>文衡</strong>
          <span>学科信息参考</span>
        </div>
        <nav className="nav" aria-label="工作区">
          <a href="/app/" aria-current="page"><Icon name="play" size={19} />生成台</a>
          <a href="/app/shelf/"><Icon name="book" size={19} />陈列馆</a>
        </nav>
        <div className="who">
          <span className="avatar">{me?.name?.slice(0, 1) ?? '？'}</span>
          {me?.name ?? '角色未知'}
          {me?.role ? ` · ${me.role === 'admin' ? '管理员' : '游客'}` : '（未提供 /api/me）'}
        </div>
      </header>

      <main className="wrap">
        {healthy === false && (
          <div className="banner bad" style={{ marginTop: 0 }}>
            <span className="ico"><Icon name="alert" size={22} /></span>
            <span>
              <b className="title">连不上本机服务</b>
              <ul>
                <li>后端没有响应 —— 检查它是否在运行（`/healthz`）。</li>
                <li>下面显示的期次列表可能不完整；你的台账与已出的报告都没有受影响。</li>
              </ul>
            </span>
          </div>
        )}

        <Workbench
          period={selected}
          me={me}
          wb={wb}
          err={err}
          healthy={healthy === true}
          onGenerate={onGenerate}
        />

        <a className="entry" href="/app/shelf/">
          <span>
            <span className="t">陈列馆 · 历期卷宗</span>
            <span className="d">按期翻看已出刊的报告（书架 → 端详 → 开卷）</span>
          </span>
          <span className="go" aria-hidden="true">→</span>
        </a>

        <section className="card" style={{ marginTop: 18, overflow: 'hidden' }}>
          <table className="periods">
            <thead>
              <tr>
                <th>期次</th><th>目录名</th><th>状态</th><th style={{ width: 90 }}>操作</th>
              </tr>
            </thead>
            <tbody>
              {periods.length === 0 && (
                <tr><td colSpan={4} style={{ color: 'var(--ink-3)' }}>
                  {healthy === false ? '服务未启动，读不到期次。' : '暂无期次。'}
                </td></tr>
              )}
              {periods.map((p) => (
                <tr key={p.period}
                    onClick={() => setSelected(p.period)}
                    style={{ cursor: 'pointer', background: p.period === selected ? 'var(--panel)' : undefined }}>
                  <td>{p.label}</td>
                  <td className="mono">{p.period}</td>
                  <td>
                    <span className={`pill ${p.status === 'signed' ? 'signed' : p.status === 'stale' ? 'stale' : 'unsigned'}`}>
                      {p.status === 'signed' ? '已签发' : p.status === 'stale' ? '签名已失效' : '未签发'}
                    </span>
                  </td>
                  <td>
                    <a href={p.url} onClick={(e) => e.stopPropagation()}>打开</a>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </section>

        <p className="hint" style={{ marginTop: 14 }}>
          {busy && '正在提交生成请求……'}
          {!busy && '演示时想直接看某个状态（空/生成中/失败…）可在网址后加 '}
          {!busy && <code>?demo=fail-ledger</code>}
        </p>
      </main>
    </>
  )
}
