/* 可视化工作流 · 产线全景（2026-10-24 rick 定：「产线全景」静态稿升格为正式屏）。
   设计稿：web/mockups/文衡-产线全景（静态稿 20261023）.html（并行会话出品）。
   🔴 只做两件事：把已有状态摆到空间里（回放）、任务在跑时如实点亮（实时）。
   不新增数字、不演没发生的动画——流动动画只在任务真在跑时出现。
   真值四个只读源：取数记录 · 运行档案 · 红色件清单 · 签单状态；期次由顶栏全局选择器切换。 */

import { useEffect, useMemo, useRef, useState, type PointerEvent as RPointerEvent, type ReactNode } from 'react'
import {
  getAcquisition, getArchive, req,
  type AcquisitionState, type ArchiveData, type PeriodDetail, type Period,
} from './api'
import { StoryBand } from './StoryBand'

type RowState = 'done' | 'run' | 'warn' | 'idle'
type PanelRow = { name: string; state: RowState; note: string }
type PanelSection = { title: string; rows: PanelRow[] }

type Props = {
  period: string | null
  periods: Period[]
  detail: PeriodDetail | null
  approvalStatus: string
  /** 任务在跑：产线建筑点亮「运行中」、路上出现流动，机器仍画上一轮的事实 */
  live: boolean
  liveNote?: string | null
  /** 嵌入场合（如陈列馆）没有顶栏期次选择器——尾句可换成当场的切换方式 */
  periodSwitchNote?: string
}

/* ---------- 等轴测几何（与静态稿同一套常数；P(x,y,z) → 屏幕坐标） ---------- */

const P = (x: number, y: number, z = 0): [number, number] =>
  [470 + (x - y) * 4.3, 150 + (x + y) * 2.45 - z * 4.3]
const pts = (arr: [number, number][]) => arr.map(([a, b]) => `${a.toFixed(1)},${b.toFixed(1)}`).join(' ')

/* 色板＝现行工作区令牌（整座工厂随主题走）；纸感墙面色无令牌，就地常量 */
const C = {
  card: 'var(--card)', ground: 'var(--panel)', grid: 'var(--line)', line: 'var(--line)',
  ink: 'var(--ink)', ink2: 'var(--ink-2)', ink3: 'var(--ink-3)',
  tool: 'var(--tool)', tool3: 'var(--tool-3)', zhu: 'var(--zhu)', warn: 'var(--warn)',
  wallT: '#FBF8F0', wallL: '#F4EFE2', wallR: '#DAD1BD', idleTop: '#CFC9B7', paper: '#E6E0CF',
}

function IsoBox({ x, y, w, d, h, z0 = 0, top, left = C.wallL, right = C.wallR,
                  stroke = C.line, foot = true, parapet = false }: {
  x: number; y: number; w: number; d: number; h: number; z0?: number
  top: string; left?: string; right?: string; stroke?: string; foot?: boolean; parapet?: boolean
}) {
  const zt = z0 + h
  const o = { stroke, strokeWidth: 0.7 }
  return (
    <g>
      {foot && <polygon points={pts([P(x, y, z0), P(x + w, y, z0), P(x + w, y + d, z0), P(x, y + d, z0)])} fill="rgba(21,34,43,.04)" transform="translate(2,1.2)" />}
      {foot && <polygon points={pts([P(x, y, z0), P(x + w, y, z0), P(x + w, y + d, z0), P(x, y + d, z0)])} fill="rgba(21,34,43,.06)" />}
      <polygon points={pts([P(x, y + d, zt), P(x + w, y + d, zt), P(x + w, y + d, z0), P(x, y + d, z0)])} fill={left} {...o} />
      <polygon points={pts([P(x + w, y, zt), P(x + w, y + d, zt), P(x + w, y + d, z0), P(x + w, y, z0)])} fill={right} {...o} />
      <polygon points={pts([P(x, y, zt), P(x + w, y, zt), P(x + w, y + d, zt), P(x, y + d, zt)])} fill={top} {...o} />
      {parapet && <polygon points={pts([P(x + 0.9, y + 0.9, zt), P(x + w - 0.9, y + 0.9, zt), P(x + w - 0.9, y + d - 0.9, zt), P(x + 0.9, y + d - 0.9, zt)])} fill="none" stroke={stroke} strokeWidth={0.7} opacity={0.55} />}
    </g>
  )
}

/* 中台：八边形大厅（两级） */
function Octagon({ cx, cy, r, z0, h, top, left = C.wallL, right = C.wallR }: {
  cx: number; cy: number; r: number; z0: number; h: number
  top: string; left?: string; right?: string
}) {
  const p8: [number, number][] = []
  for (let k = 0; k < 8; k++) {
    const a = (22.5 + k * 45) * Math.PI / 180
    p8.push([cx + r * Math.cos(a), cy + r * Math.sin(a)])
  }
  const o = { stroke: C.line, strokeWidth: 0.7 }
  const faces: ReactNode[] = []
  for (let k = 0; k < 8; k++) {
    const a = p8[k], b = p8[(k + 1) % 8]
    const mx = (a[0] + b[0]) / 2 - cx, my = (a[1] + b[1]) / 2 - cy
    if (mx + my <= 0) continue
    faces.push(
      <polygon key={k} {...o}
        points={pts([P(a[0], a[1], z0 + h), P(b[0], b[1], z0 + h), P(b[0], b[1], z0), P(a[0], a[1], z0)])}
        fill={(mx - my) > 0 ? right : left} />,
    )
  }
  return (
    <g>
      <polygon {...o} points={pts(p8.map(p => P(p[0], p[1], z0)))} fill="rgba(21,34,43,.04)" transform="translate(2,1.2)" />
      <polygon {...o} points={pts(p8.map(p => P(p[0], p[1], z0)))} fill="rgba(21,34,43,.06)" />
      {faces}
      <polygon {...o} points={pts(p8.map(p => P(p[0], p[1], z0 + h)))} fill={top} />
    </g>
  )
}

/* 道路：live 时才有流动虚线（不演没发生的动画） */
function Road({ points, w = 13, flow = false, base = '#DCD6C5' }: {
  points: [number, number][]; w?: number; flow?: boolean; base?: string
}) {
  const d = points.map(([x, y], i) =>
    `${i ? 'L' : 'M'}${P(x, y)[0].toFixed(1)},${P(x, y)[1].toFixed(1)}`).join(' ')
  return (
    <g>
      <path d={d} fill="none" stroke={base} strokeWidth={w} strokeLinejoin="round" strokeLinecap="round" />
      {flow
        ? <path className="pano-flow" d={d} fill="none" stroke={C.tool3} strokeWidth={w * 0.32}
            strokeDasharray="8 12" strokeLinecap="round" />
        : <path d={d} fill="none" stroke="#C7C0AE" strokeWidth={1.8} strokeDasharray="5 8" />}
    </g>
  )
}

/* 链路方向：路段中点一枚小三角指向下游站——产线走向不靠文字也能读（静态装饰，无动画） */
function Chevron({ points }: { points: [number, number][] }) {
  const i = Math.floor((points.length - 1) / 2)
  const [ax, ay] = P(points[i][0], points[i][1])
  const [bx, by] = P(points[i + 1][0], points[i + 1][1])
  const t = Math.atan2(by - ay, bx - ax), s = Math.sin(t), c = Math.cos(t)
  const p2 = [bx - 8 * c - 4 * s, by - 8 * s + 4 * c]
  const p3 = [bx - 8 * c + 4 * s, by - 8 * s - 4 * c]
  return <polygon points={`${bx.toFixed(1)},${by.toFixed(1)} ${p2[0].toFixed(1)},${p2[1].toFixed(1)} ${p3[0].toFixed(1)},${p3[1].toFixed(1)}`} fill="#C7C0AE" />
}

function Tree({ x, y, r, color }: { x: number; y: number; r: number; color: string }) {
  const [bx, by] = P(x, y, 0)
  return (
    <g>
      <ellipse cx={bx} cy={by} rx={r * 10} ry={r * 4} fill="rgba(21,34,43,.06)" />
      <rect x={bx - 1.4} y={by - r * 4} width={2.8} height={r * 4} fill="#8A7C63" />
      <ellipse cx={bx} cy={by - r * 5.6} rx={r * 6} ry={r * 5.8} fill={color} />
    </g>
  )
}

/* 立面窗：左面（y+d 侧）竖长条窗×n，均匀分布；墙面提亮色（无令牌，就地常量与墙面同法） */
function Windows({ x, y, w, d, z0, h, n = 3 }: {
  x: number; y: number; w: number; d: number; z0: number; h: number; n?: number
}) {
  const els: ReactNode[] = []
  const ww = 0.9, zh = Math.min(2.4, h * 0.45), zc = z0 + h * 0.38
  const step = n > 1 ? (w - 1.8 - n * ww) / (n - 1) + ww : 0
  for (let k = 0; k < n; k++) {
    const xk = x + 0.9 + k * step
    els.push(<polygon key={k}
      points={pts([P(xk, y + d, zc), P(xk + ww, y + d, zc), P(xk + ww, y + d, zc + zh), P(xk, y + d, zc + zh)])}
      fill="rgba(255,253,246,.55)" />)
  }
  return <g>{els}</g>
}

/* 建筑落影包围盒（标签锚点用） */
function mark(x: number, y: number, w: number, d: number, z0: number, zt: number) {
  const c = [P(x, y, z0), P(x + w, y, z0), P(x + w, y + d, zt), P(x, y + d, zt), P(x, y, zt), P(x + w, y + d, z0)]
  const xs = c.map(p => p[0]), ys = c.map(p => p[1])
  const mx = Math.min(...xs), my = Math.min(...ys)
  return { x: mx, y: my, w: Math.max(...xs) - mx, h: Math.max(...ys) - my }
}

/* 标签药丸：中文 12.6px/字、其他 6.7px 估宽；向下避让已放药丸（与静态稿同法） */
type Pill = { text: string; dot: string | null; box: { x: number; y: number; w: number; h: number }
  side: 'top' | 'left' | 'right' | 'bottom'; stroke?: string }

const measure = (t: string, dot: boolean) =>
  [...t].reduce((s, ch) => s + (/[\u4e00-\u9fa5]/.test(ch) ? 12.6 : 6.7), 0) + (dot ? 32 : 20)
const hit = (a: Pill['box'], b: Pill['box'], m = 5) =>
  !(a.x + a.w + m < b.x || b.x + b.w + m < a.x || a.y + a.h + m < b.y || b.y + b.h + m < a.y)

function Labels({ pills }: { pills: Pill[] }) {
  const placed: { p: Pill; r: Pill['box'] }[] = []
  const out: ReactNode[] = []
  pills.forEach((p, i) => {
    const w = measure(p.text, !!p.dot), hg = 23
    let x: number, y: number
    const b = p.box
    if (p.side === 'right') { x = b.x + b.w + 12; y = b.y + 12 }
    else if (p.side === 'left') { x = b.x - w - 12; y = b.y + 12 }
    else if (p.side === 'bottom') { x = b.x + b.w / 2 - w / 2; y = b.y + b.h + 12 }
    else { x = b.x + b.w / 2 - w / 2; y = b.y - hg - 12 }
    x = Math.max(8, Math.min(992 - w, x))
    const r = { x, y, w, h: hg }
    let guard = 0
    while (placed.some(q => hit(r, q.r)) && guard++ < 12) { y += hg + 6; r.y = y }
    placed.push({ p, r })
    const ax = p.side === 'right' ? x : p.side === 'left' ? x + w : b.x + b.w / 2
    const ay = p.side === 'right' || p.side === 'left' ? y + hg / 2 : p.side === 'bottom' ? y : y + hg
    out.push(
      <g key={i}>
        <line x1={ax.toFixed(1)} y1={ay.toFixed(1)}
          x2={(p.side === 'left' ? b.x + b.w / 2 : ax).toFixed(1)}
          y2={(p.side === 'top' ? b.y : p.side === 'bottom' ? b.y + b.h : ay).toFixed(1)}
          stroke={C.ink3} strokeWidth={1} />
        <circle cx={(p.side === 'left' ? b.x + b.w / 2 : ax).toFixed(1)}
          cy={(p.side === 'top' ? b.y : p.side === 'bottom' ? b.y + b.h : ay).toFixed(1)}
          r={1.6} fill={C.ink3} />
        <rect x={(r.x + 0.9).toFixed(1)} y={(r.y + 0.9).toFixed(1)} width={r.w.toFixed(1)} height={hg} fill="rgba(21,34,43,.10)" />
        <rect x={r.x.toFixed(1)} y={r.y.toFixed(1)} width={r.w.toFixed(1)} height={hg}
          fill="var(--card-hi)" stroke={p.stroke ?? C.line} strokeWidth={1} />
        {p.dot && <circle cx={(x + 12).toFixed(1)} cy={(y + hg / 2).toFixed(1)} r={4.2} fill={p.dot} />}
        <text x={(x + (p.dot ? 22 : 10)).toFixed(1)} y={(y + hg / 2 + 4.4).toFixed(1)}>{p.text}</text>
      </g>,
    )
  })
  return <g>{out}</g>
}

/* ---------- 真相模型：四个只读源 → 面板 / 计数 / 建筑态（不换算，只翻译状态） ---------- */

type Machine = { name: string; sec: number; state: RowState }
type Model = {
  sections: PanelSection[]
  machines: Machine[]
  esi: RowState; hall: RowState; line: RowState; qc: RowState; sign: RowState
  labels: Record<'esi' | 'hall' | 'line' | 'qc' | 'sign' | 'arch', { text: string; state: RowState }>
  signedCount: number
}

function buildModel(
  acq: AcquisitionState | null,
  archive: ArchiveData | null,
  redTotal: number | null,
  approvalStatus: string,
  periods: Period[],
  live: boolean,
  liveNote: string | null,
): Model {
  const groups = acq?.groups ?? []
  const bySrc = (src: string) => groups.filter(g => (g.source ?? '') === src)
  const srcRow = (src: string, name: string): PanelRow => {
    const gs = bySrc(src)
    if (!gs.length) return { name, state: 'idle', note: '无记录' }
    const v = gs.reduce((s, g) => s + (g.verified ?? 0), 0)
    if (gs.some(g => g.state === 'failed')) return { name, state: 'warn', note: '有失败件' }
    const allDone = gs.every(g => g.state === 'done' || (g.verified ?? 0) > 0)
    return allDone
      ? { name, state: 'done', note: `${v} 件已核验` }
      : { name, state: 'run', note: `${v} 件 · 未完` }
  }

  const copy = acq?.copy?.state
  const merged = copy === 'merged'
  const rec = acq?.reconcile
  const wf = archive?.waterfall ?? []
  const run = archive?.run
  const audit = archive?.audit
  const aRows = audit?.rows ?? []
  const aPass = aRows.filter(r => r.status === 'pass').length
  const aReview = aRows.filter(r => r.status === 'review').length
  const aFail = aRows.filter(r => r.status === 'fail').length
  const signed = approvalStatus === 'signed'
  const stale = approvalStatus === 'stale'
  const logpackN = archive?.logpack?.n_files ?? 0

  const sections: PanelSection[] = [
    {
      title: '取数',
      rows: [srcRow('esi', 'ESI 导出（Clarivate）'), srcRow('incites', 'InCites 导出')],
    },
    {
      title: '中台',
      rows: [
        merged
          ? { name: '台账入库', state: 'done', note: '已并入' }
          : copy
            ? { name: '台账入库', state: 'run', note: '副本就位，尚未并入' }
            : { name: '台账入库', state: 'idle', note: '无副本' },
        rec
          ? (rec.ok
              ? { name: '口径核对', state: 'done' as RowState, note: '数据期对上' }
              : { name: '口径核对', state: 'warn' as RowState, note: '数据期对不上' })
          : { name: '口径核对', state: 'idle', note: '无核对记录' },
      ],
    },
    {
      title: live ? '产线（图上为上一轮）' : `产线${wf.length ? `（${wf.length} 步）` : ''}`,
      rows: [
        ...(live ? [{ name: '本轮运行', state: 'run' as RowState, note: liveNote ?? '正在跑' }] : []),
        ...(wf.length
          ? wf.map((r): PanelRow => ({
              name: r.name,
              state: r.status === 'failed' ? 'warn'
                : r.status === 'warn' ? 'warn'
                  : r.orphan ? 'warn'
                    : r.status === 'done' ? 'done' : 'idle',
              note: r.orphan ? '未闭合' : `${Math.round(r.sec)} 秒${r.status === 'warn' ? ' · 有提醒' : ''}`,
            }))
          : [{ name: '流水线', state: (archive ? 'warn' : 'idle') as RowState, note: archive ? '档案里没有步骤记录' : '无运行记录' }]),
      ],
    },
    {
      title: '质检',
      rows: [
        audit?.exists
          ? { name: '机器断言', state: (aFail || aReview ? 'warn' : 'done') as RowState, note: `${aPass} / ${aRows.length} 通过` }
          : { name: '机器断言', state: 'idle', note: '未执行' },
        redTotal != null
          ? { name: '红色件清单', state: (signed ? 'done' : 'run') as RowState, note: `${redTotal} 项${signed ? ' · 已随签发' : ' · 待看'}` }
          : { name: '红色件清单', state: 'idle', note: '未生成' },
      ],
    },
    {
      title: '签发',
      rows: [
        signed
          ? { name: '馆员签单', state: 'done', note: '已签发' }
          : stale
            ? { name: '馆员签单', state: 'warn', note: '待重签' }
            : { name: '馆员签单', state: 'idle', note: '未签发' },
        logpackN
          ? { name: '三件套归档', state: 'done', note: `${logpackN} 个文件 · 可回放` }
          : { name: '三件套归档', state: 'idle', note: '日志包未生成' },
      ],
    },
  ]

  const doneSteps = wf.filter(r => r.status === 'done' && !r.orphan).length
  void doneSteps   /* 计数器已删（2026-10-24 rick：这一页内容太多）；步数/断言/红件都在面板与场景标签上 */

  const failedRun = run ? run.failed : /fail|error|escalat|cancel|abort/i.test(String(archive?.job?.['status'] ?? ''))
  const line: RowState = live ? 'run'
    : !wf.length && !run?.has_run ? 'idle'
      : failedRun ? 'warn' : 'done'
  const qc: RowState = aFail ? 'warn' : (aReview || (!signed && redTotal)) ? 'run' : archive ? 'done' : 'idle'
  const signedCount = periods.filter(p => p.signed).length

  const esiState: RowState = merged ? 'done' : acq?.started ? 'run' : 'idle'
  const totals = acq?.totals
  const v = totals?.verified, e = totals?.expected
  const esiText = merged && v != null && e != null
    ? `取数站 · ${v} 件已并入`
    : acq?.started ? (v != null && e != null ? `取数站 · ${v} / ${e} 件` : '取数站 · 取数在途') : '待取数'

  return {
    sections,
    machines: wf.map(r => ({
      name: r.name, sec: r.sec,
      state: r.status === 'failed' || r.status === 'warn' || r.orphan ? 'warn'
        : r.status === 'done' ? 'done' : 'idle',
    })),
    esi: esiState,
    hall: merged ? 'done' : acq?.started ? 'run' : 'idle',
    line, qc,
    sign: signed ? 'done' : stale ? 'warn' : 'idle',
    labels: {
      esi: { text: esiText, state: esiState },
      hall: { text: merged ? '中台 · 本期已入库' : '中台 · 未并入', state: merged ? 'done' : acq?.started ? 'run' : 'idle' },
      line: {
        text: live ? '产线 · 任务在跑' : failedRun ? '产线 · 上次运行失败'
          : wf.length ? `产线 · ${wf.length} 步跑完` : '产线 · 无运行记录',
        state: line,
      },
      qc: { text: redTotal != null ? `质检 · 红件 ${redTotal} 项` : '质检 · 无清单', state: qc },
      sign: { text: signed ? '签发台 · 已签发' : stale ? '签发台 · 待重签' : '签发台 · 待馆员签单', state: signed ? 'done' : stale ? 'warn' : 'idle' },
      arch: { text: `档案架 · 已归档 ${signedCount} 期`, state: 'done' },
    },
    signedCount,
  }
}

/* ---------- 场景 ---------- */

const DOT: Record<RowState, string> = {
  done: C.tool3, run: C.zhu, warn: C.warn, idle: C.ink3,
}

function Factory({ m, live }: { m: Model; live: boolean }) {
  const els: ReactNode[] = []

  /* 地面网格 */
  els.push(<rect key="g" x={-600} y={-600} width={2400} height={2000} fill={C.ground} />)
  const grid: ReactNode[] = []
  for (let v = -120; v <= 140; v += 5) {
    const a = P(v, -120), b = P(v, 140), c = P(-120, v), d = P(140, v)
    grid.push(<line key={`v${v}`} x1={a[0]} y1={a[1]} x2={b[0]} y2={b[1]} stroke={C.grid} strokeWidth={0.55} opacity={0.35} />)
    grid.push(<line key={`h${v}`} x1={c[0]} y1={c[1]} x2={d[0]} y2={d[1]} stroke={C.grid} strokeWidth={0.55} opacity={0.35} />)
  }
  els.push(<g key="grid">{grid}</g>)
  els.push(<g key="trees">
    <Tree x={2} y={26} r={3.2} color={C.tool3} />
    <Tree x={88} y={2} r={2.6} color="#3E7F5F" />
    <Tree x={97} y={44} r={2.9} color={C.tool3} />
    <Tree x={30} y={74} r={2.6} color="#3E7F5F" />
  </g>)

  /* 取数站（左上）：主楼＝ESI，披屋＝InCites */
  els.push(<g key="esi">
    <Road points={[[20, 17], [30, 28], [38, 35]]} />
    <Chevron points={[[20, 17], [30, 28], [38, 35]]} />
    <Road points={[[34, 20], [40, 30], [42, 34]]} />
    <Chevron points={[[34, 20], [40, 30], [42, 34]]} />
    <IsoBox x={4} y={4} w={14} d={11} h={8} top={C.tool} parapet />
    <Windows x={4} y={4} w={14} d={11} z0={0} h={8} n={4} />
    <IsoBox x={6.5} y={6.5} w={3.2} d={3.2} h={3.4} z0={8} top={C.paper} />
    <IsoBox x={23} y={7} w={12} d={10} h={6.5} top={C.tool3} parapet />
    <IsoBox x={28} y={11} w={1.1} d={1.1} h={3.2} z0={6.5} top={C.paper} foot={false} />
  </g>)

  /* 中台（正中）：八边形大厅 */
  els.push(<g key="hall">
    <Octagon cx={47} cy={40} r={10} z0={0} h={8} top="#EDE8DA" />
    <Octagon cx={47} cy={40} r={6.8} z0={8} h={4} top={C.tool} />
    <IsoBox x={45.8} y={38.8} w={2.4} d={2.4} h={2.8} z0={12} top={C.zhu} foot={false} />
  </g>)

  /* 产线车间（右上）：机器数＝真实步骤数，高度＝该步耗时占比 */
  const mlist = m.machines.length ? m.machines.slice(0, 9)
    : [1, 2, 3, 4, 5].map(() => ({ name: '', sec: 0, state: 'idle' as RowState }))
  const maxSec = Math.max(1, ...mlist.map(x => x.sec))
  const n = mlist.length
  const startX = 60.5
  const gap = n > 1 ? Math.min(6.2, 33.5 / (n - 1)) : 0
  /* 中台→车间（主链路补断链，2026-10-25：原六段链路缺这一段，产线走向读不出来） */
  els.push(<g key="hall2line">
    <Road points={[[52, 33], [57, 27], [61, 21]]} />
    <Chevron points={[[52, 33], [57, 27], [61, 21]]} />
  </g>)
  els.push(<g key="linebg">
    <polygon points={pts([P(58, 10), P(96, 10), P(96, 32), P(58, 32)])} fill="#EDE8DA" stroke={C.line} strokeWidth={0.8} />
    {[0.3, 0.55, 0.8].map(t => (
      <line key={t} x1={P(58 + 38 * t, 10.6)[0]} y1={P(58 + 38 * t, 10.6)[1]}
        x2={P(58 + 38 * t, 31.4)[0]} y2={P(58 + 38 * t, 31.4)[1]}
        stroke={C.line} strokeWidth={0.6} opacity={0.5} />
    ))}
    <IsoBox x={58} y={10} w={38} d={1.3} h={10} top={C.tool} foot={false} parapet />
    <IsoBox x={58} y={10} w={1.3} d={22} h={10} top={C.tool} foot={false} parapet />
    <Road points={[[62, 26], [78, 26], [93, 26]]} w={7} flow={live} base="#DFDAC9" />
  </g>)
  mlist.forEach((mm, i) => {
    const h = mm.sec ? 3.6 + 4.6 * (mm.sec / maxSec) : 3.6 + [0.4, 0.9, 1.4, 0.7, 0.2][i % 5]
    const x = startX + i * gap
    const top = mm.state === 'done' ? C.tool3 : mm.state === 'warn' ? C.idleTop : C.idleTop
    els.push(<g key={`m${i}`}>
      <IsoBox x={x} y={16} w={4.4} d={8} h={h} top={top} />
      <IsoBox x={x + 1} y={17} w={2.2} d={2.2} h={2} z0={h}
        top={mm.state === 'warn' ? C.warn : C.paper} foot={false} />
      {mm.name && <title>{`${mm.name} · ${Math.round(mm.sec)} 秒`}</title>}
    </g>)
  })
  if (live) {
    const [px, py] = P(75.2, 21, 9.2)
    els.push(<circle key="pulse" cx={px} cy={py} r={3} fill={C.warn} opacity={0.5}>
      <animate attributeName="r" values="2.2;4.6;2.2" dur="2.8s" repeatCount="indefinite" />
      <animate attributeName="opacity" values=".5;.1;.5" dur="2.8s" repeatCount="indefinite" />
    </circle>)
  }

  /* 质检塔（右侧）：天线灯色＝质检态，红件待看时双圈示警 */
  const [ax, ay] = P(72.4, 50.4, 22.4)
  els.push(<g key="qc">
    <Road points={[[96, 29], [88, 40], [79, 46]]} />
    <Chevron points={[[96, 29], [88, 40], [79, 46]]} />
    <IsoBox x={68} y={46} w={9} d={9} h={15} top={C.card} parapet />
    <Windows x={68} y={46} w={9} d={9} z0={0} h={15} n={3} />
    <IsoBox x={70.6} y={48.6} w={3.6} d={3.6} h={4} z0={15} top={C.tool} />
    <line x1={P(72.4, 50.4, 19)[0]} y1={P(72.4, 50.4, 19)[1]} x2={ax} y2={ay} stroke={C.ink2} strokeWidth={1.2} />
    <circle cx={ax} cy={ay} r={3} fill={DOT[m.qc]} />
    <IsoBox x={78} y={47} w={3.4} d={3.4} h={10} top={C.idleTop} />
    {m.qc === 'warn' && <>
      <circle cx={P(79.7, 48.7, 12)[0]} cy={P(79.7, 48.7, 12)[1]} r={4} fill={C.warn} opacity={0.3} />
      <circle cx={P(80.8, 49.8, 14.6)[0]} cy={P(80.8, 49.8, 14.6)[1]} r={5.2} fill={C.warn} opacity={0.16} />
    </>}
  </g>)

  /* 签发台（中下）：桌面白纸＋印章 */
  els.push(<g key="sign">
    <Road points={[[73, 55], [64, 60], [54, 61]]} />
    <Chevron points={[[73, 55], [64, 60], [54, 61]]} />
    <Road points={[[34, 66], [28, 64], [25, 61]]} base="#DFDAC9" />
    <Chevron points={[[34, 66], [28, 64], [25, 61]]} />
    <IsoBox x={36} y={60} w={15} d={8} h={3} top="#E9E3D4" parapet />
    <IsoBox x={38} y={61.6} w={4} d={3} h={0.5} z0={3} top="#FFFDF6" foot={false} />
    <IsoBox x={43} y={62} w={2.6} d={2.6} h={2.8} z0={3} top={C.zhu} foot={false} />
    <IsoBox x={46.4} y={62} w={2.2} d={2.2} h={1.2} z0={3} top={C.ink2} foot={false} />
    <IsoBox x={47.2} y={64} w={1} d={1} h={4.6} z0={3} top={C.idleTop} foot={false} />
    <IsoBox x={46.3} y={63.2} w={2.8} d={2.8} h={0.8} z0={7.6} top={C.paper} foot={false} />
  </g>)

  /* 档案架（左下）：最新一格器色 */
  els.push(<g key="arch">
    <IsoBox x={4} y={50} w={21} d={16} h={1.8} top="#EDE8DA" />
    {[5.5, 11, 16.5].map((bx, i) => (
      <g key={bx}>
        <IsoBox x={bx} y={53} w={4.6} d={11} h={8} z0={1.8} top={i === 2 ? C.tool : C.ink2} parapet />
        {[0, 1, 2].map(k => (
          <IsoBox key={k} x={bx + 0.6 + k * 1.4} y={54} w={1} d={2.2} h={2.4} z0={9.8}
            top={k === 1 ? C.tool3 : C.idleTop} foot={false} />
        ))}
      </g>
    ))}
  </g>)

  /* 标签 */
  const pills: Pill[] = [
    { text: m.labels.esi.text, dot: DOT[m.labels.esi.state], box: mark(4, 4, 14, 11, 0, 8), side: 'left' },
    { text: m.labels.hall.text, dot: DOT[m.labels.hall.state], box: mark(36, 31, 22, 18, 0, 12), side: 'top' },
    { text: m.labels.line.text, dot: DOT[m.labels.line.state], box: mark(58, 10, 38, 22, 0, 10), side: 'top' },
    { text: m.labels.qc.text, dot: DOT[m.labels.qc.state], box: mark(68, 46, 9, 9, 0, 19),
      side: 'top', stroke: m.labels.qc.state === 'warn' ? '#E2B3A8' : undefined },
    { text: m.labels.sign.text, dot: DOT[m.labels.sign.state], box: mark(36, 60, 15, 8, 0, 8.4), side: 'left' },
    { text: m.labels.arch.text, dot: DOT[m.labels.arch.state], box: mark(4, 50, 21, 16, 0, 12), side: 'left' },
  ]
  els.push(<Labels key="labels" pills={pills} />)

  return <>{els}</>
}

/* ---------- 相机（只动 viewBox，不动数据） ---------- */

const VB_BASE = { x: 0, y: 30, w: 1000, h: 520 }
const clampN = (v: number, a: number, b: number) => Math.max(a, Math.min(b, v))

const CAMS: { act: string; label: string }[] = [
  { act: 'reset', label: '全景' },
  { act: 'left', label: '左转' },
  { act: 'right', label: '右转' },
  { act: 'in', label: '拉近' },
  { act: 'out', label: '拉远' },
]

export function Panorama({ period, periods, detail, approvalStatus, live, liveNote = null,
                            periodSwitchNote }: Props) {
  const [acq, setAcq] = useState<AcquisitionState | null>(null)
  const [archive, setArchive] = useState<ArchiveData | null | undefined>(undefined)
  const [redTotal, setRedTotal] = useState<number | null>(null)
  const [vb, setVb] = useState(VB_BASE)
  const stageRef = useRef<HTMLDivElement | null>(null)
  /* 拖动平移（2026-10-24 rick：模型要能动）：只动 viewBox，不动数据 */
  const dragRef = useRef<{ px: number; py: number; vb: { x: number; y: number; w: number; h: number } } | null>(null)
  const vbRef = useRef(vb)
  vbRef.current = vb

  /* 期次变了重读三个只读源；没出稿的期次不请求运行档案（避免 404 噪音，与故事条同法） */
  const canReadArchive = !!detail?.steps?.generate
  useEffect(() => {
    setVb(VB_BASE)
    if (!period) { setAcq(null); setArchive(undefined); setRedTotal(null); return }
    let alive = true
    getAcquisition(period).then(a => { if (alive) setAcq(a) }).catch(() => { if (alive) setAcq(null) })
    if (canReadArchive) {
      getArchive(period).then(a => { if (alive) setArchive(a) }).catch(() => { if (alive) setArchive(null) })
    } else setArchive(null)
    setRedTotal(null)
    req<{ total?: number }>(`/api/periods/${encodeURIComponent(period)}/redslots?limit=1&offset=0`)
      .then(r => { if (alive) setRedTotal(r.total ?? null) })
      .catch(() => { if (alive) setRedTotal(null) })
    return () => { alive = false }
  }, [period, canReadArchive])

  const model = useMemo(
    () => buildModel(acq, archive ?? null, redTotal, approvalStatus, periods, live, liveNote),
    [acq, archive, redTotal, approvalStatus, periods, live, liveNote],
  )

  const cam = (act: string) => setVb(prev => {
    const v = { ...prev }
    if (act === 'reset') return { ...VB_BASE }
    if (act === 'left') v.x = clampN(v.x - 60, -60, 240)
    if (act === 'right') v.x = clampN(v.x + 60, -60, 240)
    if (act === 'in') {
      const nw = clampN(v.w * 0.86, 380, 1200)
      v.x += (v.w - nw) / 2; v.y += (v.h - nw * 0.587) / 2; v.w = nw; v.h = nw * 0.587
    }
    if (act === 'out') {
      const nw = clampN(v.w * 1.16, 380, 1500)
      v.x -= (nw - v.w) / 2; v.y -= (nw * 0.587 - v.h) / 2; v.w = nw; v.h = nw * 0.587
    }
    return v
  })

  /* 滚轮缩放（朝光标；原生监听拿 passive:false 才能 preventDefault 屏蔽页面滚轮） */
  useEffect(() => {
    const el = stageRef.current
    if (!el) return
    const onWheel = (e: WheelEvent) => {
      e.preventDefault()
      const v = vbRef.current
      const rect = el.getBoundingClientRect()
      const cx = v.x + ((e.clientX - rect.left) / rect.width) * v.w
      const cy = v.y + ((e.clientY - rect.top) / rect.height) * v.h
      const k = e.deltaY > 0 ? 1.16 : 1 / 1.16
      const nw = clampN(v.w * k, 380, 1500)
      const nh = nw * (v.h / v.w)
      setVb({
        x: clampN(cx - (cx - v.x) * (nw / v.w), -260, 620),
        y: clampN(cy - (cy - v.y) * (nh / v.h), -140, 380),
        w: nw, h: nh,
      })
    }
    el.addEventListener('wheel', onWheel, { passive: false })
    return () => el.removeEventListener('wheel', onWheel)
  }, [period])   // 首渲染 period 为空时舞台不在树上（ref null），期次就位后要再挂一次

  const onPointerDown = (e: RPointerEvent<HTMLDivElement>) => {
    /* 相机按钮/链接不进拖拽（pointer capture 会吞掉它们的 click） */
    if ((e.target as HTMLElement).closest('button, a')) return
    dragRef.current = { px: e.clientX, py: e.clientY, vb: { ...vbRef.current } }
    e.currentTarget.setPointerCapture(e.pointerId)
  }
  const onPointerMove = (e: RPointerEvent<HTMLDivElement>) => {
    const d = dragRef.current
    const el = stageRef.current
    if (!d || !el) return
    const rect = el.getBoundingClientRect()
    const scale = d.vb.w / rect.width
    setVb(v => ({
      ...v,
      x: clampN(d.vb.x - (e.clientX - d.px) * scale, -260, 620),
      y: clampN(d.vb.y - (e.clientY - d.py) * scale, -140, 380),
    }))
  }
  const onPointerUp = () => { dragRef.current = null }

  if (!period) {
    return <div className="pending-box mt-0">选择期次后这里展示那一期的产线全景。</div>
  }

  const label = periods.find(p => p.period === period)?.label ?? period

  return (
    <div className="pano">
      <div className="pano-top">
        <h1 className="pano-title">产线全景
          <span className="pano-tag">{label} · 数字为真值</span>
        </h1>
      </div>

      {/* 五步故事条（2026-10-24 从生成台迁入，rick：要动态可播放；同日 rick 红框删计数器
          与题头——紧凑模式只留一枚重放按钮，五格回放不变）——与下面工厂是同一份真值的两种投影 */}
      <StoryBand
        period={period}
        approvalStatus={approvalStatus}
        detail={detail}
        live={live}
        liveNote={liveNote}
        compact
      />

      <div className="pano-wrap">
        <aside className="pano-panel" aria-label="真相面板">
          {model.sections.map(s => (
            <section className="pano-sec" key={s.title}>
              <h3>{s.title}</h3>
              {s.rows.map(r => (
                <p className="pano-row" key={r.name}>
                  <i className={`s-${r.state}`} title={r.name} />
                  <span className="nm">{r.name}</span>
                  <span className={`st${r.state === 'warn' ? ' warn' : ''}`}>{r.note}</span>
                </p>
              ))}
            </section>
          ))}
        </aside>

        <div className="pano-stage" ref={stageRef}
             onPointerDown={onPointerDown} onPointerMove={onPointerMove}
             onPointerUp={onPointerUp} onPointerCancel={onPointerUp}>
          <svg viewBox={`${vb.x} ${vb.y} ${vb.w} ${vb.h}`} preserveAspectRatio="xMidYMid meet"
            role="img"
            aria-label={`产线全景：${model.labels.line.text}；${model.labels.qc.text}；${model.labels.sign.text}`}>
            <Factory m={model} live={live} />
          </svg>
          <div className="pano-cams" role="group" aria-label="视角">
            <span className="pano-cams-hint" aria-hidden="true">拖动平移 · 滚轮缩放</span>
            {CAMS.map(c => (
              <button key={c.act} type="button" onClick={() => cam(c.act)}>{c.label}</button>
            ))}
          </div>
        </div>
      </div>

      <p className="pano-note">
        <b>这张图只做一件事：把已有状态摆到空间里。</b>
        左栏是真相（取数记录 · 运行档案 · 红色件清单 · 签单状态），场景是它的空间投影——
        不新增数字、不演没发生的动画；路上流动只在任务真在跑时出现。{periodSwitchNote ?? '期次用顶栏选择器切换。'}
      </p>
    </div>
  )
}
