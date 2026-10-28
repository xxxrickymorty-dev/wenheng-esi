/* 跨页双联工作台壳（rick 2026-10-25 过审；2026-10-26 起为 5180 的真壳）
   左页「会泽」深绿品牌面＝品牌/导航/本期身份/钤印位；右页「至公」纸面＝真工作区
   （web/src 全量迁入 ws/，ShellApp 承载全部真屏；期次/配色/身份收在壳内细条）。
   钤印位状态印与左栏身份行吃 ShellApp 上报的真值（period/status/task/acq）。
   样式：框架在 spread.css；工作区令牌与组件类在 ws/ws.css（.ws 作用域）。 */

import { useEffect, useRef, useState,
         type CSSProperties, type KeyboardEvent as ReactKeyboardEvent, type PointerEvent as ReactPointerEvent } from "react";
import "../spread.css";
import ShellApp, { type WsContext, type WsView } from "../ws/ShellApp";
import DialogPage from "../ws/dialog/DialogPage";

/* ── 状态印：印面与「状态印章·谱 20261025」逐字一致（正本在 web/src/StateSeal.tsx） ── */

type SealState = "merged" | "drafted" | "unsigned" | "signed" | "stale";

function SealFace({ state }: { state: SealState }) {
  const ground = state === "signed";
  const gold = state === "stale";
  const ink = gold ? "#8A6B2E" : state === "merged" || state === "drafted" ? "#264A35" : "#A82F22";
  const filter = ground ? "url(#sp-ink-rough-heavy)" : "url(#sp-ink-rough)";
  const frame = ground ? (
    <rect x="10" y="10" width="200" height="200" fill={ink} />
  ) : (
    <rect x="10" y="10" width="200" height="200" fill="none" stroke={ink}
      strokeWidth={state === "unsigned" ? 3.4 : 5}
      strokeDasharray={state === "unsigned" ? "14 9" : undefined} />
  );
  const inner = ground ? (
    <rect x="22" y="22" width="176" height="176" fill="none" stroke="#F5F3EC" strokeWidth="2.6" />
  ) : (
    <rect x="23" y="23" width="174" height="174" fill="none" stroke={ink}
      strokeWidth={state === "unsigned" ? 1.2 : 1.6} />
  );
  const chars: Array<[string, number, number]> =
    state === "merged" ? [["并", 64, 94], ["入", 156, 94], ["台", 64, 180], ["账", 156, 180]]
      : state === "drafted" ? [["已", 64, 94], ["出", 156, 94], ["稿", 110, 180]]
        : state === "unsigned" ? [["未", 64, 94], ["签", 156, 94], ["发", 110, 180]]
          : state === "stale" ? [["签", 64, 94], ["发", 156, 94], ["失", 64, 180], ["效", 156, 180]]
            : [["已", 64, 94], ["签", 156, 94], ["发", 110, 180]];
  return (
    <svg viewBox="0 0 220 220">
      <g filter={filter}>
        {frame}
        {inner}
        <g fontFamily="'Noto Serif SC','Source Han Serif SC','Songti SC',SimSun,serif"
           fontWeight={700} fontSize={56} textAnchor="middle"
           fill={ground ? "#F5F3EC" : ink}>
          {chars.map(([ch, x, y], i) => <text key={i} x={x} y={y}>{ch}</text>)}
        </g>
      </g>
    </svg>
  );
}

/* ── 左栏导航 × 视图元（标题/一句话；真值都在右联真屏里） ── */

const NAV: { key: WsView; label: string; m?: boolean; q?: boolean }[] = [
  { key: "workbench", label: "出报告" },
  { key: "report", label: "报告台" },
  { key: "analysis", label: "灵活报告" },
  { key: "ask", label: "问文衡" },
  { key: "ledger", label: "主 台 账", m: true },
  { key: "archive", label: "运行档案" },
  { key: "shelf", label: "陈列馆 ↗", q: true },
];

const VIEW_META: Record<string, { ov: string; title: string; stm: string }> = {
  workbench: { ov: "本期 · 出报告", title: "工作台", stm: "台账往前推一步，报告就有初稿。" },
  acquire: { ov: "本期 · 第 一 站", title: "取数核验", stm: "机器取数，人来核对。" },
  pick: { ov: "本期 · 选 模", title: "预测选模", stm: "模型替学科作答，人来定夺。" },
  forecast: { ov: "本期 · 选 模", title: "预测台", stm: "五家各答一遍，误差最小者上。" },
  review: { ov: "本期 · 第 四 站", title: "核验定稿", stm: "机器保数字，取舍你来定。" },
  report: { ov: "本期 · 成 品", title: "报告台", stm: "一期成册，逐格可追。" },
  red: { ov: "报告 · 下 钻", title: "红色件清单", stm: "逐条看，逐条清。" },
  charts: { ov: "报告 · 下 钻", title: "图 册", stm: "一百零八张，图图有出处。" },
  reading: { ov: "报告 · 下 钻", title: "阅 稿", stm: "正文与数字同屏。" },
  trace: { ov: "报告 · 下 钻", title: "逐格溯源", stm: "点一格，回台账。" },
  pano: { ov: "工作区 · 产 线", title: "可视化工作流", stm: "把已有状态摆到空间里。" },
  analysis: { ov: "工作区 · 篇 章", title: "灵活报告", stm: "指定学科，即时成篇。" },
  ask: { ov: "工作区 · 对 话", title: "问文衡", stm: "工作台里能查的，这里都能问。" },
  ledger: { ov: "管理 · 源 头", title: "主 台 账", stm: "一本台账，全部源头。" },
  archive: { ov: "管理 · 留 痕", title: "运行档案", stm: "每一步都留痕，每一步都能回去看。" },
  heal: { ov: "管理 · 沙 盘", title: "自愈沙盘", stm: "断了自愈，全程可看。" },
  migrate: { ov: "管理 · 沙 盘", title: "换馆沙盘", stm: "换一台馆，照搬即走。" },
  shelf: { ov: "成 品 馆", title: "陈列馆", stm: "一年六期，一期一册。" },
};

/* 左栏宽度与收起（2026-10-28 rick：左栏可收回可拖动，参考 DeepSeek Harness 侧栏）：
   拖动条在订口上（hover 亮金线），18–40% 连续调宽、双击回默认、方向键微调；
   收起后左页合成「书脊」（竖排品牌＋展开钮）——合上左页，翻开即回。
   密度三档保留为快捷档：拖到非档位＝自定义（三档全不亮）。
   宽度与收起态都记进 localStorage——视图偏好无保存仪式，但也不该每次重调。 */
const LW_KEY = "wenheng-spread-lw";
const FOLD_KEY = "wenheng-spread-folded";
const LW_MIN = 18;
const LW_MAX = 40;

function initialLw(): string {
  try {
    const v = localStorage.getItem(LW_KEY);
    if (v) {
      const n = parseFloat(v);
      if (n >= LW_MIN && n <= LW_MAX) return `${Math.round(n)}%`;
    }
  } catch { /* 浏览器不允许读取时用默认 */ }
  return "28%";
}

function initialFolded(): boolean {
  try { return localStorage.getItem(FOLD_KEY) === "1"; } catch { return false; }
}

export function WorkbenchSpread() {
  const [lw, setLw] = useState(initialLw);
  const [folded, setFolded] = useState(initialFolded);
  const [dragging, setDragging] = useState(false);
  const [cur, setCur] = useState<WsView>("workbench");
  const [ctx, setCtx] = useState<WsContext | null>(null);
  const [land, setLand] = useState(false);
  const prevStatus = useRef<string>("unsigned");
  const spreadRef = useRef<HTMLDivElement | null>(null);
  const resizerRef = useRef<HTMLDivElement | null>(null);

  /* 偏好持久化：拖完/收完即记，下次开机还是这个样子 */
  useEffect(() => {
    try { localStorage.setItem(LW_KEY, lw); } catch { /* 忽略 */ }
  }, [lw]);
  useEffect(() => {
    try { localStorage.setItem(FOLD_KEY, folded ? "1" : "0"); } catch { /* 忽略 */ }
  }, [folded]);

  /* 拖动：down 时同步挂 window 监听、up 时同步摘——
     不依赖 React 状态提交时序（极快点放也不会把 dragging 卡在 true）。
     步进 1%——即时生效，无保存按钮。 */
  const onResizeStart = (e: ReactPointerEvent<HTMLDivElement>) => {
    e.preventDefault();
    try { resizerRef.current?.setPointerCapture(e.pointerId); } catch { /* 合成/异常指针不影响拖动 */ }
    const move = (ev: PointerEvent) => {
      const el = spreadRef.current;
      if (!el) return;
      const r = el.getBoundingClientRect();
      const pct = Math.round(Math.min(LW_MAX, Math.max(LW_MIN, ((ev.clientX - r.left) / r.width) * 100)));
      setLw(`${pct}%`);
    };
    const up = () => {
      window.removeEventListener("pointermove", move);
      window.removeEventListener("pointerup", up);
      window.removeEventListener("pointercancel", up);
      setDragging(false);
    };
    window.addEventListener("pointermove", move);
    window.addEventListener("pointerup", up);
    window.addEventListener("pointercancel", up);
    setDragging(true);
  };
  const onResizeKeyDown = (e: ReactKeyboardEvent<HTMLDivElement>) => {
    const now = parseFloat(lw);
    if (e.key === "ArrowLeft") { e.preventDefault(); setLw(`${Math.max(LW_MIN, Math.round(now) - 1)}%`); }
    if (e.key === "ArrowRight") { e.preventDefault(); setLw(`${Math.min(LW_MAX, Math.round(now) + 1)}%`); }
  };

  /* 问文衡常驻徽标 + 右抽屉（2026-10-28 rick 裁「B 为主、A 为展开态」）：
     徽标每一站右页角常驻；抽屉小问不离站，「整页 ↗」＝左栏 ask 视图（A 案）。 */
  const [askOpen, setAskOpen] = useState(false);
  const [askBusy, setAskBusy] = useState(false);

  /* 陈列馆＝独立展示面（rick 2026-10-26）：不套工作区壳——左页、钤印位、右页顶条一律不画，
     右页独占整幅。左栏只留给工作区（本期四站、报告台、台账这些「事」）。 */
  const bare = cur === "shelf";

  /* 进出陈列馆时版式换栏，滚动位置一律归零（否则会落在书架中段或半屏工作台） */
  const wasBare = useRef(false);
  useEffect(() => {
    if (bare || wasBare.current) window.scrollTo(0, 0);
    wasBare.current = bare;
  }, [bare]);

  /* 真签发态翻面的那一刻落章（ShellApp 上报的 status 是唯一事实源） */
  useEffect(() => {
    const st = ctx?.status ?? "unsigned";
    const just = prevStatus.current !== st && (st === "signed" || st === "stale");
    prevStatus.current = st;
    if (!just) return;
    setLand(true);
    const t = window.setTimeout(() => setLand(false), 650);
    return () => window.clearTimeout(t);
  }, [ctx?.status]);

  const meta = VIEW_META[cur] ?? { ov: "文 衡 · 工 作 区", title: cur, stm: "" };
  const status = ctx?.status ?? "unsigned";
  /* 印随站换面＋印随签发态（交互稿方案一 20261028 rick 审）：
     取数/选模＝机器站，恒干印「并入台账」；其余站随真签发态——
     已签发＝朱满印、签发失效＝金印、未出稿未签发＝朱虚框、已出稿未签发＝墨绿干印。
     （原「印随站」把 workbench 钉死在已出稿，换期时印不跟期次走——按交互稿改。） */
  const sealState: SealState =
    cur === "acquire" || cur === "pick" ? "merged"
      : status === "stale" ? "stale"
        : status === "signed" ? "signed"
          : ctx?.generated === false ? "unsigned" : "drafted";

  return (
    <div ref={spreadRef}
         className={`sp-spread${bare ? " solo" : ""}${folded ? " folded" : ""}${dragging ? " dragging" : ""}`}
         style={{ "--lw": lw } as CSSProperties}>

      {/* 印泥毛边滤镜（跨页壳私有 id；工作区屏用 ws/ShellApp 里那套） */}
      <svg className="sp-defs" aria-hidden="true"><defs>
        <filter id="sp-ink-rough" x="-6%" y="-6%" width="112%" height="112%">
          <feTurbulence type="fractalNoise" baseFrequency="1.6" numOctaves="2" seed="4" />
          <feDisplacementMap in="SourceGraphic" scale="2.4" />
        </filter>
        <filter id="sp-ink-rough-heavy" x="-8%" y="-8%" width="116%" height="116%">
          <feTurbulence type="fractalNoise" baseFrequency="0.9" numOctaves="3" seed="11" />
          <feDisplacementMap in="SourceGraphic" scale="3.2" />
        </filter>
      </defs></svg>

      {/* 左页 · 会泽：只在工作区出——陈列馆是成品展示面，不套壳。
          收起时合成书脊（竖排品牌＋展开钮），宽度记忆在 localStorage。 */}
      {!bare && (folded ? (
        <aside className="sp-spine">
          <button type="button" className="sp-spine-open" aria-label="展开左栏"
                  aria-expanded="false" title="展开左栏"
                  onClick={() => setFolded(false)}>»</button>
          <span className="sp-spine-t" aria-hidden="true">文衡 · 学科信息参考</span>
        </aside>
      ) : (
        <aside className="page-l">
          <div className="bm"><b>文衡</b><span>云南大学图书馆<br />学科信息参考</span></div>
          {/* 期次签/身份签的槽位：内容由 ShellApp portal 渲染（2026-10-28
              rick 裁「删顶部栏」——期次选择与管理员搬左栏，其余删）。
              折叠时本栏被书脊替换，两签随栏暂隐，展开即回。 */}
          <div id="pl-sig-slot" className="pl-slot" />
          <nav className="nav" aria-label="工作区">
            {NAV.map((n) => (
              <a key={n.key} href={`#${n.key}`}
                 className={n.m ? "m" : n.q ? "q" : undefined}
                 aria-current={cur === n.key ? "page" : undefined}
                 onClick={(e) => { e.preventDefault(); setCur(n.key) }}>
                {n.label}
              </a>
            ))}
          </nav>
          <div className="hero-l">
            <p className="ov">{meta.ov}</p>
            <h1>{meta.title}</h1>
            <p className="vol">
              <span className="b">{ctx?.label ?? (ctx?.period ?? "——————")}</span>
              <span className="c">{ctx?.window ? `数据截至 ${ctx.window}` : ctx ? "—" : "正在连接服务…"}</span>
            </p>
            <div className="rule" />
            <p className="stm">{meta.stm}</p>
            <div className="state">
              <div className="s"><span className="k">任 务</span><span className="v">{ctx?.task ?? "—"}</span></div>
              <div className="s"><span className="k">签 发</span><span className="v">
                {status === "signed" ? "已签发" : status === "stale" ? "签发已失效" : "未签发"}
              </span></div>
              <div className="s"><span className="k">取 数</span><span className="v">{ctx?.acq ?? "—"}</span></div>
            </div>
          </div>
          <div id="pl-user-slot" className="pl-slot pl-slot-user" />
          <div className="footline">
            <span>会 泽 百 家 · 至 公 天 下</span>
            <span>并 行 实 验 · 随 时 可 能 删 除</span>
          </div>
        </aside>
      ))}

      {/* 拖动条：订口上的可抓握条（参考 DeepSeek Harness 侧栏）——
          hover/focus 亮金线；按住左右拖＝连续调宽（18–40%，步进 1%）；
          双击回默认 28%；左右方向键微调；顶部小把手＝合上左页。
          收起后本条与钤印一并收掉，书脊上的展开钮负责翻回。 */}
      {!bare && !folded && (
        <div ref={resizerRef}
             className="sp-resizer" role="separator" aria-orientation="vertical"
             aria-label="拖动调整左栏宽度；双击回到默认宽度"
             aria-valuenow={Math.round(parseFloat(lw))} aria-valuemin={LW_MIN} aria-valuemax={LW_MAX}
             aria-valuetext={`左栏宽度 ${lw}`}
             tabIndex={0}
             onPointerDown={onResizeStart}
             onDoubleClick={() => setLw("28%")}
             onKeyDown={onResizeKeyDown}>
          <button type="button" className="sp-fold-btn" aria-label="收起左栏"
                  aria-expanded="true" title="收起左栏"
                  onClick={() => setFolded(true)}>‹</button>
        </div>
      )}

      {/* 钤印位：纸卡垫底＋状态印（随站与真签发态换面）——钤在左栏订口，壳不在就不钤 */}
      {!bare && !folded && (
        <div className="sealbox" id="sp-seal" aria-hidden="true">
          <div key={sealState} className={land ? "landing" : undefined}>
            <SealFace state={sealState} />
          </div>
        </div>
      )}

      {/* 右页 · 至公：真工作区（web/src 全量迁入 ws/，视图由左栏驱动）；
          2026-10-28 起右页页眉＝签条页眉（方案一交互稿：期次签/ⓘ/身份/密度
          都在 ShellApp 的壳内细条，rtop 撤除——屏题在左栏 hero，期次在期次签，
          两处不再重复）。陈列馆独占整幅，只留一条回工作区的浮标。 */}
      <section className="page-r">
        {bare && (
          <button type="button" className="back-home" onClick={() => setCur("workbench")}>
            ←　回 工 作 区
          </button>
        )}
        <div className="ws-host">
          <ShellApp view={cur} onNavigate={setCur} onContext={setCtx} />
        </div>

        {/* 常驻徽标：每一站右页角（陈列馆 solo 是成品展示面，不出）；答复中＝朱点 */}
        {!bare && (
          <button type="button" className={`sp-fab${askBusy ? " busy" : ""}`}
                  aria-label="问文衡" onClick={() => setAskOpen(true)}>
            问<span className="dot" aria-hidden="true" />
          </button>
        )}
        {/* 右抽屉：只盖右页，左栏与钤印位不动；DialogPage drawer 紧凑态 */}
        {!bare && askOpen && (
          <aside className="sp-drawer" aria-label="问文衡抽屉">
            <header className="sp-drawer-h">
              <span className="sp-drawer-seal" aria-hidden="true">问</span>
              <span className="tt"><b>问文衡</b><i>工 作 区 · 对 话</i></span>
              <span className="slot">期次 <b>{ctx?.period ?? "——————"}</b></span>
              <button type="button" className="sp-drawer-x"
                      onClick={() => { setAskOpen(false); setCur("ask") }}>整页 ↗</button>
              <button type="button" className="sp-drawer-x" aria-label="收起"
                      onClick={() => setAskOpen(false)}>✕</button>
            </header>
            <div className="dlg-host">
              <DialogPage variant="drawer" onBusyChange={setAskBusy} />
            </div>
          </aside>
        )}
      </section>
    </div>
  );
}
