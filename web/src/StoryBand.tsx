/* 生成台的故事条（2026-10-21，据静态稿「生成初稿-故事线」过审）。
   五格：取数 → 生成 → 审计 → 签发 → 留痕，数据全部来自运行档案 + 取数记录 + 签单状态。
   打开时按真实顺序回放一遍：逐格点亮、数字从 0 滚到真值、生成格把 7 步走一遍、时钟跟着秒数走。
   🔴 只做**回放**（已经发生的事）与**实时**（任务在跑）两件事，不预告、不编数：
      - 没有任务记录 → 生成格说「无运行记录」，不显示 0 秒/一次跑通；
      - 任务在跑 → 生成格显示本机任务的最新一步，不演动画。 */

import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import {
  getArchive,
  type AcquisitionState,
  type ArchiveData,
  type PeriodDetail,
} from './api'
import { buildArchiveStory, type StoryStep } from './lib/archiveStory'
import { appHref } from './lib/status'

type Clock = { start: string; end: string; total: string } | { live: true }

type Props = {
  period: string | null
  approvalStatus: string
  detail: PeriodDetail | null
  /** 任务在跑：生成格显示实时进度，不放回放动画 */
  live: boolean
  /** 任务最后一步的人话（没有就退回「正在跑」） */
  liveNote?: string | null
}

const REDUCE = typeof window !== 'undefined'
  && window.matchMedia('(prefers-reduced-motion: reduce)').matches

const DUR: Record<StoryStep['key'], number> = {
  acquire: 900,
  generate: 2200,
  audit: 1000,
  sign: 560,
  trail: 800,
}

/** 取字符串里的第一个数字：回放时只滚这个数，其余原样留（「3 / 6 通过」只滚 3） */
function firstNumber(v: string): { n: number; start: number; len: number } | null {
  const m = /\d+/.exec(v)
  return m ? { n: Number(m[0]), start: m.index, len: m[0].length } : null
}

function fmtDur(sec: number): string {
  if (!Number.isFinite(sec) || sec <= 0) return ''
  const s = Math.round(sec)
  return s >= 60 ? `${Math.floor(s / 60)} 分 ${s % 60} 秒` : `${s} 秒`
}

function timePart(v: string): string {
  const m = /(\d{2}:\d{2}:\d{2})/.exec(v)
  return m ? m[1] : v
}

/** 起点＋耗时＝收尾（与故事格里的秒数同源，避免钟面比「全程」多出进程收尾的两秒） */
function addSeconds(start: string, sec: number): string {
  const m = /(\d{2}):(\d{2}):(\d{2})/.exec(start)
  if (!m) return ''
  const t = Number(m[1]) * 3600 + Number(m[2]) * 60 + Number(m[3]) + Math.round(sec)
  const pad = (n: number) => String(n).padStart(2, '0')
  return `${pad(Math.floor(t / 3600) % 24)}:${pad(Math.floor((t % 3600) / 60))}:${pad(t % 60)}`
}

function narration(s: StoryStep, archive: ArchiveData | null): string {
  switch (s.key) {
    case 'acquire':
      return `${s.value}，${s.note}。`
    case 'generate': {
      const wf = archive?.waterfall ?? []
      if (!wf.length) return `生成：${s.value}，${s.note}。`
      const max = wf.reduce((a, b) => (b.sec > a.sec ? b : a))
      return `生成 ${s.value}，${wf.length} 步；最费时的是「${max.name}」${Math.round(max.sec)} 秒。`
    }
    case 'audit':
      return `审计 ${s.value}：${s.note}。`
    case 'sign':
      return `签发：${s.value}——${s.note}。`
    case 'trail':
      return `留痕 ${s.value}，${s.note}。`
  }
}

/** 没拿到运行档案（还没出稿 / 档案读不到）时的五步：能确认的写确认，其余如实待办 */
function fallbackStory(detail: PeriodDetail | null, approvalStatus: string): StoryStep[] {
  const acq = detail?.acquisition
  const verified = acq?.verified
  const expected = acq?.expected
  const merged = acq?.copy === 'merged'
  const fetched = !!detail?.steps?.fetch
  const generated = !!detail?.steps?.generate

  const acquire: StoryStep = fetched || acq?.started
    ? {
        key: 'acquire',
        title: '取数',
        value: verified != null && expected != null ? `${verified} / ${expected} 件` : '有下载记录',
        note: merged ? '已并入主台账'
          : verified != null && expected != null && verified >= expected
            ? '下载完成，尚未并入'
            : '还没核验完',
        state: merged ? 'ok' : 'warn',
      }
    : { key: 'acquire', title: '取数', value: '还未开始', note: '先去取数台', state: 'todo' }

  const generate: StoryStep = generated
    ? { key: 'generate', title: '生成', value: '已出稿', note: '运行记录读不到', state: 'warn' }
    : { key: 'generate', title: '生成', value: '未执行', note: '还没出稿', state: 'todo' }

  const audit: StoryStep = { key: 'audit', title: '审计', value: '未执行', note: '没有审计记录', state: 'todo' }

  const sign: StoryStep = approvalStatus === 'signed'
    ? { key: 'sign', title: '签发', value: '已签发', note: '报告可下载', state: 'ok' }
    : approvalStatus === 'stale'
      ? { key: 'sign', title: '签发', value: '待重签', note: '内容改过，签名失效', state: 'warn' }
      : { key: 'sign', title: '签发', value: '未签发', note: '签单后才可下载', state: 'todo' }

  const trail: StoryStep = { key: 'trail', title: '留痕', value: '无', note: '日志包未生成', state: 'todo' }

  return [acquire, generate, audit, sign, trail]
}

export function StoryBand({ period, approvalStatus, detail, live, liveNote }: Props) {
  const [archive, setArchive] = useState<ArchiveData | null | undefined>(undefined)
  const [phase, setPhase] = useState<'pending' | 'done'>('pending')
  const [playTick, setPlayTick] = useState(0)

  const token = useRef(0)
  const playing = useRef(false)
  const bandRef = useRef<HTMLDivElement>(null)
  const lineRef = useRef<HTMLElement>(null)
  const clockRef = useRef<HTMLParagraphElement>(null)
  const tagRef = useRef<HTMLSpanElement>(null)
  const sayRef = useRef<HTMLSpanElement>(null)
  const btnRef = useRef<HTMLButtonElement>(null)

  /* 期次变了：重读这一期的运行档案；404 = 没出稿 / 没有档案，不是错误 */
  useEffect(() => {
    if (!period) { setArchive(null); return }
    let alive = true
    setArchive(undefined)
    setPhase('pending')
    getArchive(period)
      .then((a) => { if (alive) setArchive(a) })
      .catch(() => { if (alive) setArchive(null) })
    return () => { alive = false }
  }, [period])

  const acq = useMemo<AcquisitionState | null>(() => {
    const a = detail?.acquisition
    if (!a) return null
    return {
      period: period ?? '',
      started: !!a.started,
      totals: { verified: a.verified ?? undefined, expected: a.expected ?? undefined },
      copy: { state: a.copy },
    }
  }, [detail, period])

  const steps = useMemo(() => {
    const list = archive
      ? buildArchiveStory(archive, acq, approvalStatus)
      : fallbackStory(detail, approvalStatus)
    if (!live) return list
    /* 任务在跑：生成格换成实时一句话，其余仍按已确认的事实 */
    return list.map((s) => s.key === 'generate'
      ? { ...s, value: '进行中', note: liveNote?.trim() || '正在跑', state: 'todo' as const }
      : s)
  }, [archive, acq, approvalStatus, detail, live, liveNote])

  const clock = useMemo<Clock | null>(() => {
    if (live) return { live: true }
    if (!archive) return null
    const job = archive.job ?? {}
    const start = String(job.started_at ?? job.created_at ?? '')
    const elapsed = Number(archive.run_log?.elapsed_sec ?? archive.waterfall_total ?? 0)
    const total = fmtDur(elapsed)
    if (!start) return null
    const end = addSeconds(start, elapsed)
    return { start, end: end || timePart(String(job.finished_at ?? '')), total }
  }, [archive, live])

  const canPlay = !live && archive !== undefined && (!!archive || !!detail?.steps?.generate)
  const hasRun = !!archive
  const intro = hasRun
    ? '五步都来自这次运行的记录；点一格可以回到那一段的原件。'
    : '这一期还没有运行记录；每一步的状态来自取数与签单记录，没有的不编。'
  const final = '点一格可以回到那一段的原件。'

  const clockFull = useCallback(() => {
    if (!clockRef.current || !clock || 'live' in clock) return
    clockRef.current.innerHTML = `<b>${clock.start}</b> → <b>${clock.end}</b> · ${clock.total}`
  }, [clock])

  const play = useCallback(async () => {
    const band = bandRef.current
    if (!band || !steps.length) return
    const my = ++token.current
    playing.current = true
    const cells = Array.from(band.querySelectorAll<HTMLElement>('.cell'))
    const wait = (ms: number) => new Promise((r) => window.setTimeout(r, ms))
    const tween = (dur: number, fn: (p: number) => void) => new Promise<boolean>((res) => {
      const t0 = performance.now()
      const frame = (t: number) => {
        if (my !== token.current) return res(false)
        const p = Math.min(1, (t - t0) / dur)
        fn(1 - Math.pow(1 - p, 3))
        if (p < 1) requestAnimationFrame(frame)
        else res(true)
      }
      requestAnimationFrame(frame)
    })
    const clockStart = () => {
      if (!clockRef.current || !clock) return
      if ('live' in clock) return
      clockRef.current.innerHTML = `<b>${clock.start}</b> 起 · 回放中`
    }
    const clockAt = (sec: number) => {
      if (!clockRef.current || !clock || 'live' in clock) return
      const m = /(\d{2}):(\d{2}):(\d{2})/.exec(clock.start)
      if (!m) return
      const t = Number(m[1]) * 3600 + Number(m[2]) * 60 + Number(m[3]) + Math.round(sec)
      const pad = (n: number) => String(n).padStart(2, '0')
      clockRef.current.innerHTML =
        `<b>${clock.start.slice(0, 10)} ${m[0]}</b> → ` +
        `<b>${pad(Math.floor(t / 3600))}:${pad(Math.floor((t % 3600) / 60))}:${pad(t % 60)}</b> · ${clock.total}`
    }

    if (btnRef.current) btnRef.current.textContent = '跳过'
    if (tagRef.current) tagRef.current.textContent = '回放中'
    if (lineRef.current) lineRef.current.style.width = '0%'
    clockStart()

    for (let i = 0; i < steps.length; i++) {
      if (my !== token.current) return
      const s = steps[i]
      const cell = cells[i]
      if (!cell) break
      cell.className = `cell ${s.state} live`
      if (lineRef.current) lineRef.current.style.width = `${((i + 0.7) / steps.length) * 100}%`
      if (sayRef.current) sayRef.current.textContent = narration(s, archive ?? null)

      const vEl = cell.querySelector<HTMLElement>('.v')
      const ntEl = cell.querySelector<HTMLElement>('.nt')
      if (!vEl || !ntEl) continue
      ntEl.textContent = s.note

      if (s.key === 'generate' && archive && archive.waterfall.length > 0) {
        /* 生成格：按真实步骤走一遍，数字是累计秒数 */
        const wf = archive.waterfall
        const slot = Math.round(DUR.generate / wf.length)
        let cum = 0
        for (const row of wf) {
          if (my !== token.current) return
          ntEl.textContent = `${row.name} · ${Math.round(row.sec)} 秒`
          const from = cum
          const to = cum + row.sec
          await tween(slot, (p) => {
            const sec = from + (to - from) * p
            vEl.textContent = `${Math.round(sec)} 秒`
            clockAt(sec)
          })
          cum = to
        }
        vEl.textContent = s.value
        ntEl.textContent = s.note
        if (clockRef.current && clock && !('live' in clock)) {
          clockRef.current.innerHTML = `<b>${clock.start}</b> → <b>${clock.end}</b> · ${clock.total}`
        }
        continue
      }

      const num = firstNumber(s.value)
      if (num) {
        await tween(DUR[s.key], (p) => {
          const n = Math.round(num.n * p)
          vEl.textContent = s.value.slice(0, num.start) + n + s.value.slice(num.start + num.len)
        })
        vEl.textContent = s.value
      } else {
        vEl.style.opacity = '0'
        await wait(90)
        vEl.textContent = s.value
        vEl.style.opacity = '1'
        await wait(DUR[s.key])
      }
    }

    if (my !== token.current) return
    playing.current = false
    if (btnRef.current) btnRef.current.textContent = '▶ 重放'
    if (lineRef.current) lineRef.current.style.width = ''
    clockFull()
    setPhase('done')
  }, [steps, archive, clock, clockFull])

  /* 期次/档案/状态变了就重放一次；减少动效、未出稿、任务在跑时直接给终态 */
  useEffect(() => {
    if (!canPlay || REDUCE) { setPhase('done'); return }
    setPhase('pending')
    const t = window.setTimeout(() => { void play() }, 80)
    return () => {
      window.clearTimeout(t)
      token.current++
      playing.current = false
    }
  }, [canPlay, play, playTick])

  const onPlay = () => {
    if (playing.current) {
      token.current++
      playing.current = false
      if (btnRef.current) btnRef.current.textContent = '▶ 重放'
      if (lineRef.current) lineRef.current.style.width = ''
      clockFull()
      setPhase('done')
      return
    }
    setPlayTick((n) => n + 1)
  }

  const cellHref = (key: StoryStep['key']) => {
    if (!period) return '/app/'
    if (key === 'acquire') return appHref('acquire', period)
    if (key === 'sign') return appHref('review', period)
    return appHref('archive', period)
  }

  const pending = phase === 'pending' && !live

  return (
    <section className="story" aria-label="这一期怎么走到这里">
      <div className="story-h">
        <div className="story-title">
          <h2>这一期怎么走到这里</h2>
          {clock && (
            <p className="runclock" ref={clockRef}>
              {'live' in clock
                ? <><b>进行中</b> · 进度实时更新</>
                : <><b>{clock.start}</b> → <b>{clock.end}</b> · {clock.total}</>}
            </p>
          )}
        </div>
        {!live && hasRun && (
          <button className="playbtn" ref={btnRef} type="button" onClick={onPlay}>
            ▶ 重放
          </button>
        )}
        <a className="hint" href={period ? appHref('archive', period) : '/app/?view=archive'}>
          运行档案 · 完整回放 →
        </a>
      </div>
      <div className={`playline${phase === 'done' && !live ? ' done' : ''}`} aria-hidden="true"><i ref={lineRef} /></div>
      <div className="band" ref={bandRef}>
        {steps.map((s, i) => (
          <a key={s.key} className={`cell ${pending ? 'pending' : s.state}`} href={cellHref(s.key)}>
            <span className="go">→</span>
            <span className="idx">{`0${i + 1}`}</span>
            <span className="t">{s.title}</span>
            <b className="v">{pending ? '—' : s.value}</b>
            <span className="n"><span className="st"><span className="dot" />
              <em className="nt">{pending ? '' : s.note}</em></span></span>
          </a>
        ))}
      </div>
      <p className="say" aria-live="polite">
        <span className="tag" ref={tagRef}>
          {live ? '实时' : hasRun && phase === 'done' ? '回放完' : '说明'}
        </span>
        <span className="txt" ref={sayRef}>
          {live ? '正在跑：进度来自本机任务的实时状态。' : hasRun && phase === 'done' ? final : intro}
        </span>
      </p>
    </section>
  )
}
