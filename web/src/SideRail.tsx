/* 左页 · 会泽（跨页书式的左页）——工作区与问文衡共用同一套侧栏。
   同一块品牌、同一组导航、同样的口径ⓘ与身份行：换页不换脸（静态稿 20261102 定）。
   宽度与收起态存本地偏好（两页同键）：翻页保持同一形态，读不到就用默认，绝不挡页面。
   把手骑在订口金线上：拖＝调宽（232–420），**一直向左拖过最小宽＝收起**
   （2026-11-02 rick 口谕）；收起态向右拖回、双击或回车＝展开；
   收起态只留图标，悬停浮出中文全名（不让人靠一个字猜）。
   收起宽 64px：放得下 18px 图标与呼吸，再窄就只能靠猜。 */

import { useCallback, useEffect, useRef, useState } from 'react'
import type { CSSProperties, KeyboardEvent as RKeyEvent,
              PointerEvent as RPointerEvent, ReactNode } from 'react'
import type { Me, Period } from './api'
import { Info } from './Info'
import { Icon } from './icons'
import { approvalLabel } from './lib/status'
import { UserChip } from './lib/UserChip'

export type SideNavItem = { key: string; label: string; href: string; icon: string; jump?: boolean }

/* 导航就这五项＋管理组两项，顺序即版式顺序——主区四屏在上、管理区两项在下。
   高校 ESI 报告自成一个静态入口（web/schools），不归工作区路由，故不参与高亮判断。
   2026-10-31 撤出的灵活报告 / 他校简报 / AI 问数不回来（能力已并入高校ESI报告与问文衡）。 */
export const SIDE_NAV: SideNavItem[] = [
  { key: 'flow', label: '出报告', href: '/app/', icon: 'doc' },
  { key: 'analysis', label: '分析台', href: '/app/?view=analysis', icon: 'chart' },
  { key: 'schools', label: '高校 ESI 报告', href: '/app/schools/', icon: 'trend' },
  { key: 'ask', label: '问文衡', href: '/app/dialog/', icon: 'chat' },
]
/* 陈列馆是离开工作区的展示面，压一档亮度（↗ 照旧标着）。 */
export const SIDE_MANAGE: SideNavItem[] = [
  { key: 'archive', label: '运行档案', href: '/app/?view=archive', icon: 'archive' },
  { key: 'shelf', label: '陈列馆 ↗', href: '/app/shelf/', icon: 'book', jump: true },
]

export const SIDE_MIN = 232
export const SIDE_MAX = 420
export const SIDE_FOLD = 64
const SIDE_KEY = 'wenheng.side.v1'
const SIDE_STEP = 16

function readSidePref(): { w: number; fold: boolean } {
  try {
    const raw = localStorage.getItem(SIDE_KEY)
    if (raw) {
      const o = JSON.parse(raw) as { w?: number; fold?: boolean }
      const w = Number(o.w)
      return { w: Number.isFinite(w) ? Math.min(SIDE_MAX, Math.max(SIDE_MIN, w)) : 280, fold: !!o.fold }
    }
  } catch { /* 存储不可用：用默认宽度 */ }
  return { w: 280, fold: false }
}

export type SideRailState = {
  side: { w: number; fold: boolean }
  toggle: () => void
  /** 挂在页面根容器上：列宽变量与收起态都由它一处声明 */
  rootProps: { 'data-fold'?: '1'; style: CSSProperties }
  /** 挂在订口把手上 */
  gripProps: Record<string, unknown>
}

export function useSideRail(): SideRailState {
  /* 侧栏：宽度 + 收起。拖动左过最小宽＝收起；收起态拖右＝展开。 */
  const [side, setSide] = useState(readSidePref)
  const drag = useRef<{ x: number; w: number; fold: boolean } | null>(null)
  useEffect(() => {
    try { localStorage.setItem(SIDE_KEY, JSON.stringify(side)) } catch { /* 存不下就算了 */ }
  }, [side])
  const toggle = useCallback(() => setSide((s) => ({ ...s, fold: !s.fold })), [])
  const release = (e: RPointerEvent<HTMLDivElement>) => {
    try { e.currentTarget.releasePointerCapture(e.pointerId) } catch { /* 已经释放了 */ }
  }
  const onGripDown = (e: RPointerEvent<HTMLDivElement>) => {
    e.currentTarget.setPointerCapture(e.pointerId)
    drag.current = { x: e.clientX, w: side.w, fold: side.fold }
  }
  const onGripMove = (e: RPointerEvent<HTMLDivElement>) => {
    const d = drag.current
    if (!d) return
    const dx = e.clientX - d.x
    if (d.fold) {
      /* 收起态向右拖回一点＝展开（和向左拖收起对称） */
      if (dx > 12) { drag.current = null; release(e); setSide((s) => ({ ...s, fold: false })) }
      return
    }
    const next = d.w + dx
    /* 一直向左拖，过了最小宽就是「收起来」的意思 */
    if (next < SIDE_MIN) { drag.current = null; release(e); setSide((s) => ({ ...s, fold: true })); return }
    const w = Math.min(SIDE_MAX, next)
    setSide((s) => (s.w === w ? s : { ...s, w }))
  }
  const onGripUp = (e: RPointerEvent<HTMLDivElement>) => {
    drag.current = null
    release(e)
  }
  const onGripKey = (e: RKeyEvent<HTMLDivElement>) => {
    if (e.key === 'Enter' || e.key === ' ') {
      e.preventDefault()
      toggle()
    } else if (!side.fold && (e.key === 'ArrowLeft' || e.key === 'ArrowRight')) {
      e.preventDefault()
      const step = e.key === 'ArrowLeft' ? -SIDE_STEP : SIDE_STEP
      setSide((s) => ({ ...s, w: Math.min(SIDE_MAX, Math.max(SIDE_MIN, s.w + step)) }))
    }
  }
  return {
    side,
    toggle,
    rootProps: {
      'data-fold': side.fold ? '1' : undefined,
      style: { '--app-lw': side.fold ? `${SIDE_FOLD}px` : `${side.w}px` } as CSSProperties,
    },
    gripProps: {
      role: 'separator',
      'aria-orientation': 'vertical',
      tabIndex: 0,
      'aria-label': side.fold ? '拖动或双击展开侧栏' : '拖动调整侧栏宽度，拖到最左收起',
      'aria-valuenow': side.fold ? SIDE_FOLD : side.w,
      'aria-valuemin': SIDE_MIN,
      'aria-valuemax': SIDE_MAX,
      title: side.fold ? '展开侧栏' : '拖动调宽 · 拖到最左收起 · 双击收起',
      onPointerDown: onGripDown,
      onPointerMove: onGripMove,
      onPointerUp: onGripUp,
      onPointerCancel: onGripUp,
      onKeyDown: onGripKey,
      onDoubleClick: toggle,
    },
  }
}

/** 左页侧栏本体（含订口把手）。`middle`＝页自有的中段（问文衡＝对话历史），
    插在导航与身份行之间，收起态整块隐藏。
    `onSettings`（2026-11-03 票 2）：传了才在身份行旁渲染齿轮图标钮（设置中心入口；
    目前只有问文衡接线，收起态也在——64px 放得下一枚 16px 图标）。 */
export function SideRail(props: {
  rail: SideRailState
  active: string
  me: Me | null
  roleKnown: boolean
  /** 工作区会给导航链接带上当前期次；问文衡用默认（原样） */
  navHref?: (href: string) => string
  /** 期次是工作区的全局控件；问文衡的期次在会话槽位里，不给 */
  period?: { list: Period[]; selected: string | null; onPick: (p: string) => void }
  middle?: ReactNode
  /** 设置中心入口（齿轮）；不传＝这一页没有设置（其他页面暂不接线） */
  onSettings?: () => void
}) {
  const { rail, active, me, roleKnown, period, middle, onSettings } = props
  const navHref = props.navHref ?? ((href: string) => href)
  return (
    <>
      <aside className={`app-page-l${middle ? ' has-mid' : ''}`}>
        <i className="app-seal" aria-hidden="true">衡</i>
        <div className="app-lhead">
          <a className="app-brand" href={navHref('/app/')}>
            <b>文衡</b>
            <span>云南大学图书馆<br />学科信息参考</span>
          </a>
          <button className="app-fold" type="button" onClick={rail.toggle}
                  aria-expanded={!rail.side.fold} aria-controls="app-nav"
                  aria-label={rail.side.fold ? '展开侧栏' : '收起侧栏'}
                  title={rail.side.fold ? '展开侧栏' : '收起侧栏'}>
            <Icon name="menu" size={16} />
          </button>
        </div>
        <nav className="app-nav" id="app-nav" aria-label="工作区">
          {SIDE_NAV.map((n) => (
            <a key={n.key} href={navHref(n.href)}
               aria-current={active === n.key ? 'page' : undefined}>
              <Icon name={n.icon} size={18} />
              <span className="app-nav-lbl">{n.label}</span>
              <span className="app-tip" aria-hidden="true">{n.label}</span>
            </a>
          ))}
          <span className="app-nav-grp" aria-hidden="true">管 理</span>
          {SIDE_MANAGE.map((n) => (
            /* 运行档案是管理面：未登录不渲染（真门在后端）；陈列馆是展示面，谁都能去。 */
            (n.jump || me) && (
              <a key={n.key} href={navHref(n.href)}
                 className={n.jump ? 'app-jump-link' : undefined}
                 aria-current={active === n.key ? 'page' : undefined}>
                <Icon name={n.icon} size={18} />
                <span className="app-nav-lbl">{n.label}</span>
                <span className="app-tip" aria-hidden="true">{n.label}</span>
              </a>
            )
          ))}
        </nav>
        {middle && <div className="app-mid">{middle}</div>}
        <footer className="app-idb">
          <span className="app-idb-rule" aria-hidden="true" />
          {period && period.list.length > 0 && (
            <label className="app-period">
              <span>期次</span>
              <select value={period.selected ?? ''}
                      onChange={(e) => period.onPick(e.target.value)} aria-label="切换期次">
                {period.list.map((p) => (
                  <option key={p.period} value={p.period}>{p.period} · {approvalLabel(p.status)}</option>
                ))}
                {period.selected && !period.list.some((p) => p.period === period.selected) && (
                  <option value={period.selected}>{period.selected}</option>
                )}
              </select>
            </label>
          )}
          <div className="app-idb-row">
            {/* 全站唯一一份口径/来源/只读声明（原在顶栏 ⓘ；位置变了，内容一字未改）。 */}
            <Info label="口径、来源与只读声明">
              <p>① 数字只来自馆员维护的台账与派生产物，运行期大模型不进入数据路径；</p>
              <p>② 本系统是只读视图，不修改台账与报告；③ 预测章按「本期已选」的已保存选择执行，未列学科用 V1 推荐；④ 期次与状态以任务记录为准，未签发报告不可下载。</p>
              <p>来源：期内产物目录 · 运行档案 · 预测选模配置。</p>
              <p>分析报告属于内部资料，仅用于参赛，禁止外传。</p>
            </Info>
            {me ? <UserChip me={me} /> : (
              <span className="user-chip" aria-live="polite">
                <span className="user-chip-btn" aria-disabled="true">
                  <span className="av">？</span>
                  <span className="user-chip-name">{roleKnown ? '未登录' : '角色确认中…'}</span>
                </span>
              </span>
            )}
            {onSettings && (
              <button type="button" className="app-idb-set" title="设置（Ctrl + ,）"
                      aria-label="设置" onClick={onSettings}>
                <Icon name="gear" size={16} />
              </button>
            )}
          </div>
        </footer>
      </aside>

      {/* 订口把手：有形状的双竖线＋中段刻度，骑在金线上。拖＝调宽（232–420），
          一直向左拖＝收起；收起态向右拖回、双击/回车＝展开。 */}
      <div className="app-grip" {...rail.gripProps}>
        <i aria-hidden="true" />
      </div>
    </>
  )
}
