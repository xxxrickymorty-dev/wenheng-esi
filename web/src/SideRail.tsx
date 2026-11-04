/* 左页 · 会泽（跨页书式的左页）——工作区与问文衡共用同一套侧栏。
   同一块品牌、同一组导航、同样的口径ⓘ与身份行：换页不换脸（静态稿 20261102 定）。
   宽度与收回态存本地偏好（两页同键）：翻页保持同一形态，读不到就用默认，绝不挡页面。
   两态（静态稿 20261104 rev2，commit 54777fed 落码）：展开（宽 side.w，
   232–420，默认 280）/ 完全收回（宽 0）。64px 图标轨整态删除——
   收回＝订口只剩 8px 细把手，悬停滑出预览（overlay，右页不回流），
   收展合一在一枚钮上：展开态骑在品牌印「衡」正下方（‹ 收起），
   收回态左缘贴金线探出（› 固定展开）。
   把手拖动照旧：拖＝调宽（232–420），向左拖过 160＝收回；
   收回态向右拖＝展开（固定）。点击归钮、拖拽归把手，两层不打架。
   窄窗（≤900px）自动完全收回（落点只有一个＝0）；由窄变宽不做任何事。 */

import { useCallback, useEffect, useRef, useState } from 'react'
import type { CSSProperties, KeyboardEvent as RKeyEvent,
              PointerEvent as RPointerEvent, ReactNode } from 'react'
import type { Me, Period } from './api'
import { Info } from './Info'
import { Icon } from './icons'
import { approvalLabel } from './lib/status'
import { UserChip } from './lib/UserChip'

export type SideNavItem = { key: string; label: string; href: string; icon: string; jump?: boolean }

/* 导航就这六项＋管理组两项，顺序即版式顺序——主区五屏在上、管理区两项在下。
   高校 ESI 报告自成一个静态入口（web/schools），不归工作区路由，故不参与高亮判断。
   2026-10-31 撤出的他校简报 / AI 问数不回来（能力已并入高校ESI报告与问文衡）；
   学科分析 2026-11-04 并入分析台（＝学科报告区，spec 2026-11-04），不再单列导航项。 */
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
/* 拖动收起点：展开态向左拖过这条线＝完全收回（静态稿 20261104）。 */
const SIDE_COLLAPSE_AT = 160
/* 本地偏好：键与形状不变（wenheng.side.v1 / { w, fold }）。
   2026-11-04 两态化：fold 的含义从「64px 图标轨」改为「完全收回（宽 0）」，
   旧偏好里的 fold:true 直接当「收回」读入——语义迁移，无需换键。 */
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
  /** 挂在页面根容器上：列宽变量与收回/预览态都由它一处声明 */
  rootProps: { 'data-fold'?: '1'; 'data-peek'?: '1'; style: CSSProperties }
  /** 挂在订口把手上（拖动＋收回态的悬停滑出） */
  gripProps: Record<string, unknown>
  /** 挂在侧栏本体上：收回态移出侧栏与把手条 → 撤预览 */
  onAsideLeave: (e: RPointerEvent<HTMLElement>) => void
}

export function useSideRail(): SideRailState {
  /* 侧栏：宽度 + 收回（fold＝宽 0）。悬停预览（peek）是临时态，不写偏好。 */
  const [side, setSide] = useState(readSidePref)
  const [peek, setPeek] = useState(false)
  const drag = useRef<{ x: number; w: number; fold: boolean } | null>(null)
  useEffect(() => {
    try { localStorage.setItem(SIDE_KEY, JSON.stringify(side)) } catch { /* 存不下就算了 */ }
  }, [side])
  /* 窄窗自动收回（≤900px，2026-11-04 票 1；rev2 起落点只有一个＝宽 0）：
      跨进窄窗且当前展开 → 收回；由窄变宽不做任何事（用户偏好说了算）。
      加载时已在窄窗也照此办理——否则窄窗直开时侧栏以展开态挤住右页。
      置 state 即可，localStorage effect 照常存。 */
  useEffect(() => {
    const mq = window.matchMedia('(max-width: 900px)')
    const onNarrow = (e: MediaQueryListEvent) => {
      if (e.matches) setSide((s) => (s.fold ? s : { ...s, fold: true }))
    }
    if (mq.matches) {
      setSide((s) => (s.fold ? s : { ...s, fold: true }))
      setPeek(false)
    }
    mq.addEventListener('change', onNarrow)
    return () => mq.removeEventListener('change', onNarrow)
  }, [])
  /* Esc＝全局收回（静态稿）：展开态收回；收回态撤掉悬停预览。
      已被别处处理（defaultPrevented）的 Esc 不抢。 */
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key !== 'Escape' || e.defaultPrevented) return
      setPeek(false)
      setSide((s) => (s.fold ? s : { ...s, fold: true }))
    }
    document.addEventListener('keydown', onKey)
    return () => document.removeEventListener('keydown', onKey)
  }, [])
  const toggle = useCallback(() => {
    setPeek(false)
    setSide((s) => ({ ...s, fold: !s.fold }))
  }, [])
  const release = (e: RPointerEvent<HTMLDivElement>) => {
    try { e.currentTarget.releasePointerCapture(e.pointerId) } catch { /* 已经释放了 */ }
  }
  const onGripDown = (e: RPointerEvent<HTMLDivElement>) => {
    /* 收回态：把手上的点击归收展钮（钮骑在把手上），只有按在把手条上才算拖 */
    const t = e.target as Element | null
    if (side.fold && t?.closest('button')) return
    e.currentTarget.setPointerCapture(e.pointerId)
    drag.current = { x: e.clientX, w: side.w, fold: side.fold }
  }
  const onGripMove = (e: RPointerEvent<HTMLDivElement>) => {
    const d = drag.current
    if (!d) return
    const dx = e.clientX - d.x
    if (d.fold) {
      /* 完全收回态向右拖一点＝固定展开（和向左拖收回对称） */
      if (dx > 12) {
        drag.current = null
        release(e)
        setPeek(false)
        setSide((s) => ({ ...s, fold: false }))
      }
      return
    }
    const next = d.w + dx
    /* 一直向左拖，过了收起点就是「收起来」的意思 */
    if (next < SIDE_COLLAPSE_AT) {
      drag.current = null
      release(e)
      setPeek(false)
      setSide((s) => ({ ...s, fold: true }))
      return
    }
    const w = Math.min(SIDE_MAX, next)
    setSide((s) => (s.w === w ? s : { ...s, w }))
  }
  const onGripUp = (e: RPointerEvent<HTMLDivElement>) => {
    drag.current = null
    release(e)
  }
  /* 悬停滑出（仅收回态）：悬停把手条 → overlay 预览；移出（且不进侧栏本体）→ 撤。
     悬停意图用 closest 判（免传 ref）：从把手移进侧栏本体＝还想用，不撤。 */
  const onGripEnter = () => { if (side.fold) setPeek(true) }
  const onGripLeave = (e: RPointerEvent<HTMLDivElement>) => {
    if (!side.fold) return
    const rel = e.relatedTarget as Element | null
    if (rel?.closest('.app-page-l')) return
    setPeek(false)
  }
  const onAsideLeave = (e: RPointerEvent<HTMLElement>) => {
    if (!side.fold) return
    const rel = e.relatedTarget as Element | null
    if (rel?.closest('.app-grip')) return
    setPeek(false)
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
      'data-peek': side.fold && peek ? '1' : undefined,
      /* --app-lw＝右页看到的列宽（收回＝0，右页满宽；预览不改它＝右页不回流）；
         --side-w＝侧栏本体的自然宽度（收回态滑出预览用）。 */
      style: {
        '--app-lw': side.fold ? '0px' : `${side.w}px`,
        '--side-w': `${side.w}px`,
      } as CSSProperties,
    },
    gripProps: {
      role: 'separator',
      'aria-orientation': 'vertical',
      tabIndex: 0,
      'aria-label': side.fold
        ? '侧栏订口：悬停滑出预览，向右拖＝展开'
        : '拖动调整侧栏宽度，拖到最左完全收回',
      'aria-valuenow': side.fold ? 0 : side.w,
      'aria-valuemin': side.fold ? 0 : SIDE_MIN,
      'aria-valuemax': SIDE_MAX,
      title: side.fold ? '悬停滑出 · 向右拖＝展开' : '拖动调宽 · 拖到最左完全收回',
      onPointerDown: onGripDown,
      onPointerMove: onGripMove,
      onPointerUp: onGripUp,
      onPointerCancel: onGripUp,
      onPointerEnter: onGripEnter,
      onPointerLeave: onGripLeave,
      onKeyDown: onGripKey,
    },
    onAsideLeave,
  }
}

/** 左页侧栏本体（含订口把手与收展钮）。`middle`＝页自有的中段（问文衡＝对话历史），
    插在导航与身份行之间，完全收回时随本体整块隐藏（滑出预览时照常显示）。
    齿轮钮常驻（2026-11-04 rick 定：设置中心是全站入口）；
    `onSettings`＝页面接的设置中心（useSettingsCenter 的 show，三页都接线）。 */
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
  /** 设置中心入口（useSettingsCenter 的 show）；三页（工作区/问文衡/高校ESI）都接 */
  onSettings?: () => void
}) {
  const { rail, active, me, roleKnown, period, middle, onSettings } = props
  const navHref = props.navHref ?? ((href: string) => href)
  const folded = rail.side.fold
  /* 收展钮（收展合一，静态稿 20261104 rev2）：一枚钮两个锚位——
     展开态在侧栏本体右上角（品牌印正下方、右缘与印对齐，‹ 收起），
     收回态挂到订口把手上（左缘贴金线探出，› 固定展开）。
     aria-expanded / aria-controls / 键盘可达保留。 */
  const ctrlRef = useRef<HTMLButtonElement>(null)
  /* 两态换挂（侧栏本体 ↔ 订口把手）后钮会重挂：点钮引起的换挂把焦点接回去，
     键盘不断线；Esc 等别的原因引起的换挂不抢焦点。 */
  const wantCtrlFocus = useRef(false)
  useEffect(() => {
    if (wantCtrlFocus.current) { wantCtrlFocus.current = false; ctrlRef.current?.focus() }
  }, [folded])
  const onCtrlClick = () => { wantCtrlFocus.current = true; rail.toggle() }
  return (
    <>
      <aside className={`app-page-l${middle ? ' has-mid' : ''}`}
             onPointerLeave={rail.onAsideLeave}>
        <i className="app-seal" aria-hidden="true">衡</i>
        {!folded && (
          <button ref={ctrlRef} className="app-ctrl" type="button"
                  onClick={onCtrlClick}
                  aria-expanded="true" aria-controls="app-nav"
                  aria-label="收起侧栏" title="收起侧栏">
            <Icon name="chev-left" size={16} />
            <span className="app-ctrl-tip" aria-hidden="true">收起</span>
          </button>
        )}
        <div className="app-lhead">
          <a className="app-brand" href={navHref('/app/')}>
            <b>文衡</b>
            <span>云南大学图书馆<br />学科信息参考</span>
          </a>
        </div>
        <nav className="app-nav" id="app-nav" aria-label="工作区">
          {SIDE_NAV.map((n) => (
            <a key={n.key} href={navHref(n.href)}
               aria-current={active === n.key ? 'page' : undefined}>
              <Icon name={n.icon} size={18} />
              <span className="app-nav-lbl">{n.label}</span>
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
            <button type="button" className="app-idb-set" title="设置（Ctrl + ,）"
                    aria-label="设置" onClick={onSettings}>
              <Icon name="gear" size={16} />
            </button>
          </div>
        </footer>
      </aside>

      {/* 订口把手：两态同一元素。展开态＝骑在金线上的双竖线，拖＝调宽（232–420），
          一直向左拖过 160＝完全收回；完全收回态＝8px 细把手，
          悬停＝滑出预览，向右拖＝固定展开，收展钮骑在其上。 */}
      <div className="app-grip" {...rail.gripProps}>
        <i aria-hidden="true" />
        {folded && (
          <button ref={ctrlRef} className="app-ctrl" type="button"
                  onClick={onCtrlClick}
                  aria-expanded="false" aria-controls="app-nav"
                  aria-label="固定展开侧栏" title="点击固定展开">
            <Icon name="chev-right" size={16} />
            <span className="app-ctrl-tip" aria-hidden="true">固定展开</span>
          </button>
        )}
      </div>
    </>
  )
}
