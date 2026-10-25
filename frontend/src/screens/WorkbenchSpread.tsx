/* 跨页双联工作台壳（rick 2026-10-25 过审，本版接真数据）
   原稿：web/mockups/工作台壳-跨页左栏（静态稿 20261025）.html；数据层端点与 web/src 同一套
   （lib/api.ts，dev 经 vite 代理到 FastAPI）。
   红线：只做视图，数字必须能回溯到后端产物；哪一块没数据就整块写明「等什么」，不编数。
   真动作只有签单/撤回（ack 门＋两步确认）；生成/取数等写动作仍在各自真屏。 */

import { useEffect, useRef, useState, type CSSProperties } from "react";
import "../spread.css";
import {
  getMe, getPeriods, getPeriodDetail, getAcquisition, getWaterLevel, getFacts,
  getForecastBoard, getForecastChoice, getWorkbench, getArtifacts,
  signPeriod, revokePeriod, approvalLabel, taskLabel, humanSize, acqStateLabel,
  type Me, type Period, type PeriodDetail, type AcquisitionState, type WaterLevel,
  type Facts, type ForecastBoard, type ForecastChoice, type WorkbenchData, type Artifact,
} from "../lib/api";

type ScreenId = "acquire" | "pick" | "draft" | "review" | "archive" | "report";

const SCREENS: Record<ScreenId, { ov: string; title: string; crumb: string; stm: string; sub: string; cta: string }> = {
  acquire: { ov: "本期 · 第 一 站", title: "取数核验", crumb: "出报告 · 第 一 站", stm: "机器取数，人来核对。", cta: "去预测选模 →", sub: "取回的原始数据只进台账，不直接进报告。核对无误并入后，下一站才拿它选章节。" },
  pick: { ov: "本期 · 第 二 站", title: "预测选模", crumb: "出报告 · 第 二 站", stm: "模型替学科作答，人来定夺。", cta: "保存并去生成初稿 →", sub: "五个模型各自外推，V1 给推荐；改选要写理由。保存后，这一期出图与正文就按你的选择。" },
  draft: { ov: "本期 · 第 三 站", title: "生成初稿", crumb: "出报告 · 第 三 站", stm: "台账往前推一步，报告就有初稿。", cta: "去核验定稿 →", sub: "图、表、正文一次生成：数字只来自台账，正文只走句子骨架。初稿不是成品，签发前不可下载。" },
  review: { ov: "本期 · 第 四 站", title: "核验定稿", crumb: "出报告 · 第 四 站", stm: "机器保数字，取舍你来定。", cta: "提交签单 →", sub: "红件逐条过，人工项补齐，核对全绿才签。签单把这一版钉住，改一个字签发就失效。" },
  archive: { ov: "本期 · 第 五 站", title: "签发归档", crumb: "出报告 · 第 五 站", stm: "签发即归档，册架见。", cta: "去陈列馆看册 ↗", sub: "签单把这一版钉进档案：指纹记账、报告可下载、册架可翻。之后改内容＝重出＝新版本再签。" },
  report: { ov: "本期 · 成 品", title: "报告台", crumb: "报告台 · 成品展示", stm: "一期成册，逐格可追。", cta: "去核验定稿 →", sub: "报告里的每一个数字都能回到台账单元格；签发前只能是初稿，不可下载。" },
};

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

/* ── 数据装载 ───────────────────────────────────────────── */

function errNote(e: unknown, what: string): string {
  const he = e as { status?: number; body?: { error?: string; hint?: string } }
  if (he && typeof he.status === 'number') {
    if (he.status === 401) return '未登录或登录已过期——去 http://127.0.0.1:8080/login 登录后再来。'
    const b = he.body
    return b?.error ? `${what}：${b.error}${b.hint ? `（${b.hint}）` : ''}` : `${what}：服务返回 ${he.status}`
  }
  return `${what}：连不上服务（先起 FastAPI：uvicorn server.app:app --port 8080）`
}

type Load<T> = { v: T | null; err: string | null }
const OK = <T,>(v: T): Load<T> => ({ v, err: null })
const BAD = <T,>(e: unknown, what: string): Load<T> => ({ v: null, err: errNote(e, what) })

export function WorkbenchSpread() {
  const [cur, setCur] = useState<ScreenId>("acquire");
  const [lw, setLw] = useState("28%");

  /* 期次：?period= 优先，否则期次列表第一个（新→旧） */
  const [periods, setPeriods] = useState<Load<Period[]>>({ v: null, err: null });
  const [period, setPeriod] = useState<string | null>(null);
  const [me, setMe] = useState<Me | null | undefined>(undefined);

  const [detail, setDetail] = useState<Load<PeriodDetail>>({ v: null, err: null });
  const [acq, setAcq] = useState<Load<AcquisitionState>>({ v: null, err: null });
  const [water, setWater] = useState<Load<WaterLevel>>({ v: null, err: null });
  const [facts, setFacts] = useState<Load<Facts>>({ v: null, err: null });
  const [board, setBoard] = useState<Load<ForecastBoard>>({ v: null, err: null });
  const [choice, setChoice] = useState<Load<ForecastChoice>>({ v: null, err: null });
  const [wb, setWb] = useState<Load<WorkbenchData>>({ v: null, err: null });
  const [arts, setArts] = useState<Load<Artifact[]>>({ v: null, err: null });

  /* 签单卡局部状态 */
  const [known, setKnown] = useState(false);
  const [note, setNote] = useState("");
  const [busy, setBusy] = useState<null | 'sign' | 'revoke'>(null);
  const [msg, setMsg] = useState<{ ok: boolean; text: string } | null>(null);
  const [armed, setArmed] = useState(false);
  const [land, setLand] = useState(false);

  useEffect(() => {
    getMe().then((m) => setMe(m)).catch(() => setMe(null));
  }, []);

  const loadPeriods = () => {
    getPeriods()
      .then((ps) => {
        setPeriods(OK(ps));
        setPeriod((curP) => curP ?? new URLSearchParams(location.search).get('period') ?? (ps.find((x) => x.generated) ?? ps[0])?.period ?? null);
      })
      .catch((e) => setPeriods(BAD<Period[]>(e, '期次列表')));
  };
  useEffect(loadPeriods, []);

  const hasPeriod = period != null && /^\d{6}$/.test(period);
  useEffect(() => {
    if (!hasPeriod || !period) return;
    let alive = true;
    getPeriodDetail(period).then((v) => alive && setDetail(OK(v))).catch((e) => alive && setDetail(BAD<PeriodDetail>(e, '单期详情')));
    getAcquisition(period).then((v) => alive && setAcq(OK(v))).catch((e) => alive && setAcq(BAD<AcquisitionState>(e, '取数台')));
    getWaterLevel(period).then((v) => alive && setWater(OK(v))).catch((e) => alive && setWater(BAD<WaterLevel>(e, '学科矩阵')));
    getFacts(period).then((v) => alive && setFacts(OK(v))).catch((e) => alive && setFacts(BAD<Facts>(e, '事实卡')));
    getForecastBoard(period).then((v) => alive && setBoard(OK(v))).catch((e) => alive && setBoard(BAD<ForecastBoard>(e, '预测看板')));
    getForecastChoice(period).then((v) => alive && setChoice(OK(v))).catch((e) => alive && setChoice(BAD<ForecastChoice>(e, '选模记录')));
    getWorkbench(period).then((v) => alive && setWb(OK(v))).catch((e) => alive && setWb(BAD<WorkbenchData>(e, '工作台记录')));
    getArtifacts(period).then((v) => alive && setArts(OK(v))).catch((e) => alive && setArts(BAD<Artifact[]>(e, '产物清单')));
    return () => { alive = false };
  }, [period, hasPeriod]);

  /* 真状态是唯一事实源；签单/撤回后重拉期次列表，状态翻面带上落章动效 */
  const periodRow: Period | null = periods.v?.find((p) => p.period === period) ?? null;
  const status = periodRow?.status ?? 'unsigned';
  const signed = status === 'signed';
  const prevStatus = useRef(status);
  useEffect(() => {
    const just = prevStatus.current !== status && (status === 'signed' || status === 'stale');
    prevStatus.current = status;
    if (!just) return;
    setLand(true);
    const t = window.setTimeout(() => setLand(false), 650);
    return () => window.clearTimeout(t);
  }, [status]);

  /* ── 派生读数 ── */
  const av = acq.v?.totals?.verified ?? detail.v?.acquisition?.verified ?? null;
  const ae = acq.v?.totals?.expected ?? detail.v?.acquisition?.expected ?? null;
  const acqDone = av != null && ae != null && av === ae;
  const merged = detail.v?.acquisition?.copy === 'merged' || !!acq.v?.copy?.merged_at;
  const lastJob = detail.v?.lastJob ?? null;
  const lastAt = lastJob?.created_at ? lastJob.created_at.slice(5, 16).replace('T', ' ') : '';
  const inCount = water.v?.rows.filter((r) => r.state === 'in').length ?? null;
  const nField = wb.v?.todo_fill.length ?? 0;
  const nFilled = wb.v?.n_filled ?? 0;
  const nDoubt = wb.v?.n_doubt ?? 0;
  const primaryDoc = arts.v?.find((a) => a.primary) ?? null;
  const docx = arts.v?.find((a) => a.name?.endsWith('.docx')) ?? primaryDoc;
  const routeKey = board.v ? Object.keys(board.v.routes)[0] : null;
  const boardRows = routeKey ? board.v!.routes[routeKey] : [];
  const applied = choice.v?.applied ?? null;

  const conf = SCREENS[cur];

  /* 印随站换面：机器站（取数/选模）=并入台账干印；生成初稿站=已出稿干印；
     核验定稿/报告台/归档=按真签发态（未签=虚框，签后=满印，失效=金印）。 */
  const sealState: SealState =
    cur === "draft" ? "drafted"
      : cur === "acquire" || cur === "pick" ? "merged"
        : status === 'stale' ? "stale"
          : signed ? "signed" : "unsigned";

  const sign = () => {
    if (!period || busy || signed) return;
    setBusy('sign');
    setMsg(null);
    signPeriod(period, { known, note: note.trim() || undefined })
      .then((r) => {
        setBusy(null);
        setMsg({ ok: true, text: `已签单（状态 ${approvalLabel(r.status)}）。这一版已锁定，报告可下载。` });
        loadPeriods();
      })
      .catch((e) => { setBusy(null); setMsg({ ok: false, text: errNote(e, '签单') }); });
  };
  const doRevoke = () => {
    if (!period || busy) return;
    if (!armed) { setArmed(true); return; }
    setArmed(false);
    setBusy('revoke');
    setMsg(null);
    revokePeriod(period, note.trim() || undefined)
      .then((r) => {
        setBusy(null);
        setMsg({ ok: true, text: `已撤回（状态 ${approvalLabel(r.status)}）。历史保留，可追溯。` });
        loadPeriods();
      })
      .catch((e) => { setBusy(null); setMsg({ ok: false, text: errNote(e, '撤回') }); });
  };

  /* 沿 CTA 走完整站；核验定稿的签单动作在签单卡里完成（ack 门在那边） */
  const ctaGo = () => {
    if (cur === "acquire") setCur("pick");
    else if (cur === "pick") setCur("draft");
    else if (cur === "draft" || cur === "report") setCur("review");
    else if (cur === "review") {
      if (signed) setCur("archive");
      else document.getElementById('sp-sign')?.scrollIntoView({ behavior: 'smooth', block: 'center' });
    }
    /* archive 的「去陈列馆」＝ lab 陈列馆屏 */
  };

  const STEPS: Array<{ k: ScreenId; lb: string; ms: string; cls: string }> = [
    { k: "acquire", lb: "取数核验", ms: av != null && ae != null ? `${av} / ${ae}` : "未完成", cls: acqDone ? "done" : "now" },
    { k: "pick", lb: "预测选模", ms: choice.v?.at ? "已保存" : "未保存", cls: choice.v?.at ? "done" : "now" },
    { k: "draft", lb: "生成初稿", ms: detail.v?.steps?.generate ? (lastAt || "已出稿") : "未出稿", cls: detail.v?.steps?.generate ? "done" : "now" },
    { k: "review", lb: "核验定稿", ms: signed ? "已签发 · 可下载" : status === 'stale' ? "待重签 · 内容改过" : "待提交签单", cls: signed ? "done" : "now" },
    { k: "archive", lb: "签发归档", ms: signed ? "已归档 · 册架见" : "未开始", cls: signed ? "done" : "" },
  ];
  const doneN = STEPS.filter((t) => t.cls === "done").length;

  return (
    <div className="sp-spread" style={{ "--lw": lw } as CSSProperties}>

      {/* 印泥毛边滤镜（本屏私有，避开 lab 其他屏的同名 id） */}
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

      {/* 左页 · 会泽 */}
      <aside className="page-l">
        <div className="bm"><b>文衡</b><span>云南大学图书馆<br />学科信息参考</span></div>
        <nav className="nav" aria-label="工作区">
          <a href="#spread" onClick={(e) => { e.preventDefault(); setCur("acquire"); }}
             aria-current={cur === "acquire" ? "page" : undefined}>出报告</a>
          <a href="#spread" onClick={(e) => { e.preventDefault(); setCur("report"); }}
             aria-current={cur === "report" ? "page" : undefined}>报告台</a>
          <a href="#spread" onClick={(e) => e.preventDefault()}>灵活报告</a>
          <a href="#spread" onClick={(e) => e.preventDefault()}>问文衡</a>
          <a className="m" href="#spread" onClick={(e) => e.preventDefault()}>主 台 账</a>
          <a href="#spread" onClick={(e) => e.preventDefault()}>运行档案</a>
          <a className="q" href="#spread" onClick={(e) => e.preventDefault()}>陈列馆 ↗</a>
        </nav>
        <div className="hero-l">
          <p className="ov">{conf.ov}</p>
          <h1>{conf.title}</h1>
          <p className="vol">
            <span className="b">{detail.v?.label ?? (detail.v?.no != null ? `第 ${detail.v.no} 期` : "第 — 期")}</span>
            <span className="c">{detail.v?.window ? `数据截至 ${detail.v.window}` : periods.err ? "期次待定" : "—"}</span>
          </p>
          <div className="rule" />
          <p className="stm">{conf.stm}</p>
          <p className="sub">{conf.sub}</p>
          <div className="acts">
            <button className="btn" type="button" onClick={ctaGo}>
              {cur === "review" && signed ? "去签发归档 →"
                : cur === "review" ? "到下方签单卡签单 ↓" : conf.cta}
            </button>
            <a className="ghost" href="#spread" onClick={(e) => e.preventDefault()}>
              {cur === "report" ? "看图册" : cur === "review" ? "看红件清单" : "看运行档案"}
            </a>
          </div>
          <div className="state">
            <div className="s"><span className="k">任 务</span><span className="v">{taskLabel(lastJob?.status) || "—"}</span></div>
            <div className="s"><span className="k">签 发</span><span className="v">{approvalLabel(status)}</span></div>
            <div className="s"><span className="k">取 数</span><span className="v">{av != null && ae != null ? `${av} / ${ae}` : "—"}</span></div>
          </div>
        </div>
        <div className="footline">
          <span>会 泽 百 家 · 至 公 天 下</span>
          <span>{me ? `${me.name} · ${me.role === "admin" ? "管理员" : "操作员"}` : "未登录"}</span>
        </div>
      </aside>

      {/* 钤印位：纸卡垫底＋状态印（随站与真签发态换面） */}
      <div className="sealbox" id="sp-seal" aria-hidden="true">
        <div key={sealState} className={land ? "landing" : undefined}>
          <SealFace state={sealState} />
        </div>
      </div>

      {/* 右页 · 至公 */}
      <section className="page-r">
        <div className="rtop">
          <span>{conf.crumb}</span>
          <span>·</span>
          {periods.v && periods.v.length > 0 ? (
            <select className="sp-sel" value={period ?? ""} aria-label="期次"
                    onChange={(e) => setPeriod(e.target.value)}>
              {periods.v.map((p) => (
                <option key={p.period} value={p.period}>
                  {p.period}{p.status !== "unsigned" ? ` · ${approvalLabel(p.status)}` : ""}
                </option>
              ))}
            </select>
          ) : <span>{period ?? "——————"}</span>}
          <div className="r">
            <span className="density" role="group" aria-label="左栏宽度">
              {([["34%", "宽松"], ["28%", "紧凑"], ["24%", "极窄"]] as const).map(([v, name]) => (
                <button key={v} type="button" onClick={() => setLw(v)}
                        aria-pressed={lw === v ? "true" : "false"}>{name}</button>
              ))}
            </span>
            <a href="#shelf" title="并行实验目录里的陈列馆屏">陈列馆 ↗</a>
          </div>
        </div>

        <div className="steps" aria-label="出报告工序">
          <div className="pt" aria-hidden="true" />
          <div className="pr" aria-hidden="true" style={{ width: `${(doneN / 5) * 100}%` }} />
          {STEPS.map((t) => (
            <button key={t.k} type="button"
                    className={`st ${t.cls}${t.k === cur ? " here" : ""}`}
                    onClick={() => { if (t.k !== "archive" || signed) setCur(t.k); }}
                    aria-disabled={t.k === "archive" && !signed ? "true" : undefined}
                    title={t.k === "archive" && !signed ? "签发后开放" : `去${t.lb}站`}>
              <span className="lb">{t.lb}</span>
              <span className="ms">{t.ms}</span>
            </button>
          ))}
        </div>

        {/* 屏一 · 取数核验（真源：/acquisition） */}
        <div className="screen" hidden={cur !== "acquire"}>
          <div className="body">
            {acq.err ? <p className="sp-note">{acq.err}</p> : (
              <div className="roster">
                <div className="rh">
                  <h2>取数清单</h2>
                  <span className="n">{acq.v?.groups?.length ?? "—"} 个 台</span>
                  <span className="r">当期取数台 × 馆内核对</span>
                </div>
                <div className="rows">
                  <div className="rr head"><span>台 表</span><span>出 处</span><span className="num">份 数</span><span className="stt">状 态</span></div>
                  {(acq.v?.groups ?? []).map((g, i) => {
                    const st = acqStateLabel(g.state);
                    return (
                      <div className="rr" key={i}>
                        <span className="nm">{g.title ?? "—"}</span>
                        <span className="tx">{g.source ?? "—"}</span>
                        <span className="num">{g.files?.length ?? g.verified ?? "—"} 份</span>
                        <span className={`stt${st === "已取" ? "" : " wait"}`}>{st}</span>
                      </div>
                    );
                  })}
                  {(acq.v?.groups?.length ?? 0) === 0 && (
                    <div className="rr"><span className="nm">—</span><span className="tx">还没有取数记录</span><span className="num">—</span><span className="stt wait">—</span></div>
                  )}
                </div>
                <p className="roster-foot">
                  已 取 {av ?? "—"} / {ae ?? "—"}
                  {merged ? ` · 已并入台账${acq.v?.copy?.merged_at ? `（${acq.v.copy.merged_at.slice(0, 16).replace("T", " ")}）` : ""}` : " · 未并入"}
                  {acq.v?.mode === "readonly" ? " · 往期档案只读" : ""}
                </p>
              </div>
            )}
            <div className="grid2">
              <div>
                <div className="h3"><b>数据体检</b><span>断言单随出稿生成</span></div>
                {facts.v ? (
                  <div className="chk">
                    <div className="c"><span className="bx">{facts.v.assertions.fail ? "!" : "✓"}</span><span><span className="t">数字防护断言</span><span className="d">共 {facts.v.assertions.total} 条</span></span><span className={`s${facts.v.assertions.fail ? " wait" : ""}`}>{facts.v.assertions.fail ? `${facts.v.assertions.fail} 条不符` : "全过"}</span></div>
                    <div className="c"><span className="bx">{(facts.v.missing?.length ?? 0) ? "!" : "✓"}</span><span><span className="t">数据缺口</span><span className="d">{(facts.v.missing?.length ?? 0) ? facts.v.missing.slice(0, 2).join("；") : "无缺口"}</span></span><span className={`s${(facts.v.missing?.length ?? 0) ? " wait" : ""}`}>{facts.v.missing?.length ?? 0} 条</span></div>
                  </div>
                ) : <p className="sp-note">{facts.err ?? "还没出稿——体检单在出稿后生成。"}</p>}
              </div>
              <div>
                <div className="h3"><b>本期数据</b><span>以任务记录为准</span></div>
                <div className="kv">
                  <div><span className="k">期次</span><span>{period ?? "—"}{detail.v?.no != null ? ` · 第 ${detail.v.no} 期` : ""}</span></div>
                  <div><span className="k">数据截至</span><span>{detail.v?.window ?? "—"}</span></div>
                  <div><span className="k">最近任务</span><span>{lastJob ? `${taskLabel(lastJob.status)} · ${lastAt}` : "—"}</span></div>
                  <div><span className="k">核对并入</span><span>{merged ? "已并入台账" : "未并入"}</span></div>
                </div>
                <div className="h3 h3-mt"><b>合并文件</b><span>台账母本</span></div>
                <p className="fname">{acq.v?.copy?.path ? (acq.v.copy.path.split(/[\\/]/).pop() ?? "—") : "—"}</p>
                <p className="fmtime">{merged ? (acq.v?.copy?.merged_at ? `并入于 ${acq.v.copy.merged_at.slice(0, 16).replace("T", " ")}` : "已并入台账") : acq.v?.copy?.built_at ? `建副本于 ${acq.v.copy.built_at.slice(0, 16).replace("T", " ")}` : "还没有合并副本"}</p>
              </div>
            </div>
            <p className="rel"><b>与报告的关系</b>　本期取回的原始数据只进台账，不直接进报告。核对无误并入台账，下一站才拿它选章节；缺一份就阻滞取补，不得越站往下走。</p>
          </div>
        </div>

        {/* 屏二 · 预测选模（真源：/forecast-board + /forecast-choice） */}
        <div className="screen" hidden={cur !== "pick"}>
          <div className="body">
            {board.err ? <p className="sp-note">{board.err}</p> : (
              <div className="roster">
                <div className="rh">
                  <h2>本期选模</h2>
                  <span className="n">{boardRows.length} 学科{routeKey ? ` · ${routeKey}` : ""}</span>
                  <span className="r">V1 推荐 × 馆员定夺</span>
                </div>
                <div className="rows">
                  <div className="rr head"><span>潜 力 学 科</span><span>本 期 已 选</span><span className="num">接 近 度</span><span className="stt">来 源</span></div>
                  {boardRows.map((r) => {
                    const picked = routeKey ? choice.v?.choice?.[routeKey]?.[r.subject] : undefined;
                    const appliedModel = routeKey ? applied?.choice?.[routeKey]?.[r.subject] : undefined;
                    const changed = picked != null && appliedModel != null && picked !== appliedModel;
                    return (
                      <div className="rr" key={r.subject}>
                        <span className="nm">{r.subject}</span>
                        <span className="tx">{r.model || "—"}</span>
                        <span className="num">{r.prox != null ? `${r.prox}%` : "—"}</span>
                        <span className={`stt${changed ? " wait" : ""}`}>{changed ? "已改选" : choice.v?.at ? "默认" : "—"}</span>
                      </div>
                    );
                  })}
                  {boardRows.length === 0 && (
                    <div className="rr"><span className="nm">—</span><span className="tx">看板还没生成</span><span className="num">—</span><span className="stt">—</span></div>
                  )}
                </div>
                <p className="roster-foot">看 板 · {board.v?.window ?? "—"} · 改选与理由存台账，重新生成才写进报告</p>
              </div>
            )}
            <div className="grid2">
              <div>
                <div className="h3"><b>选模从哪来</b><span>三 步</span></div>
                <div className="chk">
                  <div className="c"><span className="bx">✓</span><span><span className="t">五家模型各自外推两个出榜期</span><span className="d">管线自动，人人一样</span></span><span className="s">完成</span></div>
                  <div className="c"><span className="bx">✓</span><span><span className="t">V1 按历史回测误差给推荐</span><span className="d">回测口径见预测台</span></span><span className="s">完成</span></div>
                  <div className="c"><span className="bx">✓</span><span><span className="t">馆员可改选并备注理由</span><span className="d">改选动作在预测台</span></span><span className="s">{choice.v?.at ? "已保存" : "未保存"}</span></div>
                </div>
              </div>
              <div>
                <div className="h3"><b>保存记录</b><span>以台账记录为准</span></div>
                <div className="kv">
                  <div><span className="k">保存人</span><span>{choice.v?.by ?? "—"}</span></div>
                  <div><span className="k">保存时间</span><span>{choice.v?.at ? choice.v.at.slice(0, 16).replace("T", " ") : "—"}</span></div>
                  <div><span className="k">已选条目</span><span>{choice.v ? Object.values(choice.v.choice).reduce((n, m) => n + Object.keys(m).length, 0) : "—"}</span></div>
                  <div><span className="k">出稿快照</span><span>{applied ? `出稿已用（${applied.snapshot_at.slice(0, 16).replace("T", " ")}）` : "还没出稿"}</span></div>
                </div>
                <div className="h3 h3-mt"><b>生效时机</b><span>当 期 生 效</span></div>
                <p className="fname">{applied ? "本次出稿已按这版选择出图与正文。" : "保存后即为本期选定；重新生成才写进报告。"}</p>
                <p className="fmtime">改选不改正台账数字，只改预测用哪只模型。</p>
              </div>
            </div>
            <p className="rel"><b>与报告的关系</b>　选模决定潜力学科的图与正文按哪个模型出；已保存的选择 ≠ 报告已用的选择，重新生成后才更新。</p>
          </div>
        </div>

        {/* 屏三 · 生成初稿（真源：detail + choice + lastJob） */}
        <div className="screen" hidden={cur !== "draft"}>
          <div className="body">
            <div className="roster">
              <div className="rh">
                <h2>生成节点</h2>
                <span className="n">三 步 走</span>
                <span className="r">以任务记录为准</span>
              </div>
              <div className="rows">
                <div className="rr head"><span>节 点</span><span>读 数</span><span className="num">完 成</span><span className="stt">状 态</span></div>
                <div className="rr"><span className="nm">取数核验</span><span className="tx">{merged ? "已并入台账" : "未并入"}</span><span className="num">{av != null && ae != null ? `${av} / ${ae}` : "—"}</span><span className={`stt${acqDone ? "" : " wait"}`}>{acqDone ? "完成" : "进行中"}</span></div>
                <div className="rr"><span className="nm">预测选模</span><span className="tx">{choice.v?.by ? `由 ${choice.v.by} 保存` : "还没保存"}</span><span className="num">{choice.v?.at ? choice.v.at.slice(5, 16).replace("T", " ") : "—"}</span><span className={`stt${choice.v?.at ? "" : " wait"}`}>{choice.v?.at ? "完成" : "进行中"}</span></div>
                <div className="rr"><span className="nm">生成初稿</span><span className="tx">{lastJob ? taskLabel(lastJob.status) : "还没发车"}</span><span className="num">{lastAt || "—"}</span><span className={`stt${detail.v?.steps?.generate ? "" : " wait"}`}>{detail.v?.steps?.generate ? "完成" : lastJob ? taskLabel(lastJob.status) : "未开始"}</span></div>
              </div>
              <p className="roster-foot">重 出 会 撤 下 当 前 成 品（旧 稿 可 回 滚）· 生 成 动 作 在 生 成 台</p>
            </div>
            <div className="grid2">
              <div>
                <div className="h3"><b>本期读数</b><span>{water.v ? `矩阵快照 ${water.v.snapshot?.slice(0, 10) ?? ""}` : "出 稿 即 定"}</span></div>
                <div className="kv">
                  <div><span className="k">学科在监测</span><span>{water.v ? water.v.rows.length : "—"}</span></div>
                  <div><span className="k">已进前 1%</span><span>{inCount ?? "—"}</span></div>
                  <div><span className="k">顶尖论文</span><span>{facts.v ? facts.v.facts.top_papers_now : "—"}</span></div>
                  <div><span className="k">数字防护</span><span>{facts.v ? `${facts.v.assertions.total} 条断言` : "—"}</span></div>
                </div>
              </div>
              <div>
                <div className="h3"><b>这次生成用了</b><span>记 录 如 实</span></div>
                <div className="kv">
                  <div><span className="k">任务</span><span>{lastJob ? taskLabel(lastJob.status) : "—"}</span></div>
                  <div><span className="k">最近发车</span><span>{lastAt || "—"}</span></div>
                  <div><span className="k">报告文件</span><span>{docx ? docx.name : "还没出稿"}</span></div>
                  <div><span className="k">产物</span><span>{arts.v ? `${arts.v.length} 件` : "—"}</span></div>
                </div>
                <div className="h3 h3-mt"><b>初稿的处境</b><span>{approvalLabel(status)}</span></div>
                <p className="fname">{signed ? "这一版已签发，报告可下载。" : "初稿不可下载；核对全绿并签单后才算成品。"}</p>
                <p className="fmtime">重出会撤下当前成品——旧稿先归档，可回滚可追溯。</p>
              </div>
            </div>
            <p className="rel"><b>与报告的关系</b>　初稿里的每一个数字都能回溯到台账单元格；正文只走句子骨架，不存在模型顺手算的数。签发前它只是草稿。</p>
          </div>
        </div>

        {/* 屏四 · 报告台（真源：water + facts + artifacts） */}
        <div className="screen" hidden={cur !== "report"}>
          <div className="issue">
            <h2>{detail.v?.label ?? (detail.v?.no != null ? `第 ${detail.v.no} 期` : period ?? "—")}</h2>
            <span className="when">{period ?? "—"}{detail.v?.window ? ` · 数据截至 ${detail.v.window}` : ""}</span>
            <span className="tag">{approvalLabel(status)}</span>
          </div>
          <div className="nums">
            <div className="n"><div className="k">学 科 在 监 测</div><div className="v">{water.v ? water.v.rows.length : "—"}</div></div>
            <div className="n"><div className="k">已 进 前 1 %</div><div className="v">{inCount ?? "—"}</div></div>
            <div className="n"><div className="k">顶 尖 论 文</div><div className="v">{facts.v ? facts.v.facts.top_papers_now : "—"}</div></div>
          </div>
          <div className="body">
            <div className="grid2">
              <div>
                <div className="h3"><b>本期产物</b><span>{arts.v ? `${arts.v.length} 件` : "—"}</span><span className="r">{signed ? "已签发 · 可下载" : "未签发 · 不可下载"}</span></div>
                <div className="toc-list">
                  {(arts.v ?? []).slice(0, 8).map((a) => (
                    <div className="l" key={a.key}>
                      <span className="no">{a.primary ? "主" : "·"}</span>
                      <span>{a.label || a.name}</span>
                      <span className="pg">{humanSize(a.size)}</span>
                    </div>
                  ))}
                  {(arts.v?.length ?? 0) === 0 && <p className="sp-note">{arts.err ?? "还没出稿——产物在生成后出现在这里。"}</p>}
                </div>
                <p className="fig-note">读数来自学科矩阵与事实卡；目录与图册在报告屏展开，这里只列产物。</p>
              </div>
              <div>
                <div className="h3"><b>签单前后</b><span>这 一 版 的 处 境</span></div>
                <div className="kv">
                  <div><span className="k">数字防护</span><span>{facts.v ? `${facts.v.assertions.total} 条 · 不符 ${facts.v.assertions.fail}` : "—"}</span></div>
                  <div><span className="k">待人工</span><span>{wb.v ? `${nField} 处（已填 ${nFilled}）` : "—"}</span></div>
                  <div><span className="k">存疑</span><span>{wb.v ? `${nDoubt} 处` : "—"}</span></div>
                  <div><span className="k">签发</span><span>{approvalLabel(status)}{signed ? " · 可下载" : " · 初稿不可下载"}</span></div>
                </div>
                {docx && signed ? (
                  <a className="sp-dl" href={docx.url}>下载报告（Word）↓</a>
                ) : (
                  <p className="sp-note">签发后这里出现报告 Word 的下载入口{docx ? `（已识别 ${docx.name}）` : ""}。</p>
                )}
              </div>
            </div>
            <p className="rel"><b>与报告的关系</b>　报告屏只读展示成品；要改内容请到「出报告」的核验定稿站，写动作只在那里发生。</p>
          </div>
        </div>

        {/* 屏五 · 核验定稿（签单/撤回＝真动作，ack 门在卡里） */}
        <div className="screen" hidden={cur !== "review"}>
          <div className="rv">
            <div>
              <div className="preview">
                <div className="ph"><b>核对读数</b><span>逐 格 可 追</span></div>
                <div className="doc">
                  {facts.v ? (
                    <>
                      <p className="h">数字防护</p>
                      <p>{facts.v.assertions.total} 条断言，{facts.v.assertions.fail ? `${facts.v.assertions.fail} 条不符——看校验说明。` : "全部通过。"}</p>
                      <p className="h">可追溯</p>
                      <p>{wb.v?.traceable ? `${wb.v.traceable.n} 个数字里 ${wb.v.traceable.with_source} 个有出处。` : "—"}</p>
                      <p className="h">待人工与存疑</p>
                      <p>待人工 {nField} 处（已填 {nFilled}）、存疑 {nDoubt} 处。</p>
                      {(facts.v.missing?.length ?? 0) > 0 && (<><p className="h">数据缺口</p><p>{facts.v.missing.join("；")}</p></>)}
                    </>
                  ) : <p>{facts.err ?? "读数还没就绪。"}</p>}
                </div>
                <p className="sp-note">全文逐格试排在「web 工作区 · 审核台」；本屏下一步接入。</p>
              </div>
            </div>
            <div>
              <div className="sign" id="sp-sign">
                <div className="sh">签 单</div>
                <ul>
                  <li><span className="k">报告版本</span><span className="v">{docx ? docx.name : "还没出稿"}</span></li>
                  <li><span className="k">待 人 工</span><span className="v">{nField ? `${nField} 处 · 已填 ${nFilled}` : "0 处"}</span></li>
                  <li><span className="k">存 疑</span><span className="v">{nDoubt ? `${nDoubt} 处` : "0 处"}</span></li>
                  <li><span className="k">签发状态</span><span className="v">{approvalLabel(status)}</span></li>
                  <li><span className="k">指 纹</span><span className="v">签单时生成</span></li>
                </ul>
                <label className="sp-ack">
                  <input type="checkbox" checked={known} disabled={!!busy || signed}
                         onChange={(e) => setKnown(e.target.checked)} />
                  <span>我已逐项看过待人工 {nField} 处、存疑 {nDoubt} 处，同意放行。</span>
                </label>
                <textarea className="sp-noteinput" aria-label="签单批注（可选）" rows={2}
                          value={note} onChange={(e) => setNote(e.target.value)}
                          placeholder="批注（可选）：这一版为什么可以签单、还有哪些已知问题"
                          disabled={!!busy || signed} />
                <p className="note">
                  签下这一版，指纹随稿件一起记账；再改一个字，签发即失效，需要重签。
                  {status === "stale" && " 这一版内容改过，签发已失效——确认无误后重新签单。"}
                  {signed && (
                    <a href="#spread" className="revoke"
                       onClick={(e) => { e.preventDefault(); doRevoke(); }}>
                      {armed ? "再点一次确认撤回" : "撤回签发"}
                    </a>
                  )}
                </p>
                <button className="go" type="button" onClick={sign}
                        disabled={!me || !!busy || signed || (nField > 0 && !known)}>
                  {busy === "sign" ? "正在签单……" : signed ? "已 签 发 · 这 一 版 已 锁 定" : "签 单 并 锁 定"}
                </button>
                {busy === "revoke" && <p className="sp-note">正在撤回……</p>}
                {!me && <p className="sp-note">未登录——签单要在登录后进行。</p>}
                {msg && <p className={msg.ok ? "sp-msg ok" : "sp-msg bad"} role="status">{msg.text}</p>}
              </div>
            </div>
          </div>
        </div>

        {/* 屏六 · 签发归档（真源：status + artifacts） */}
        <div className="screen" hidden={cur !== "archive"}>
          <div className="body">
            <div className="roster">
              <div className="rh">
                <h2>归档台账</h2>
                <span className="n">一 期 一 册</span>
                <span className="r">签 发 后 自 动 记 账</span>
              </div>
              <div className="rows">
                <div className="rr head"><span>凭 据</span><span>说 明</span><span className="num">时 点</span><span className="stt">状 态</span></div>
                <div className="rr"><span className="nm">签发指纹</span><span className="tx">随稿件一起记账；改动即失效</span><span className="num">{lastAt || "—"}</span><span className={`stt${signed ? "" : " wait"}`}>{signed ? "已记账" : "未签发"}</span></div>
                <div className="rr"><span className="nm">报告 Word</span><span className="tx">{docx ? docx.name : "还没出稿"}</span><span className="num">{docx ? humanSize(docx.size) : "—"}</span><span className={`stt${signed ? "" : " wait"}`}>{signed ? "可下载" : "未签发不可下载"}</span></div>
                <div className="rr"><span className="nm">册架</span><span className="tx"><a href="#shelf" className="revoke">陈列馆 · 去翻这一期册 →</a></span><span className="num">—</span><span className={`stt${signed ? "" : " wait"}`}>{signed ? "已上架" : "未上架"}</span></div>
                <div className="rr"><span className="nm">运行档案</span><span className="tx">任务、比对、红件全程留痕（真屏待接）</span><span className="num">—</span><span className="stt dim">—</span></div>
              </div>
              <p className="roster-foot">归 档 之 后 内 容 不 再 改 动 · 改 内 容 ＝ 重 出 ＝ 新 版 本 再 签</p>
            </div>
            <div className="grid2">
              <div>
                <div className="h3"><b>这一版的印</b><span>{approvalLabel(status)}</span></div>
                <div className="chk">
                  <div className="c"><span className="bx">{signed ? "✓" : "!"}</span><span><span className="t">{approvalLabel(status)}</span><span className="d">{me ? `${me.name} · 本页签单即真签单` : "登录后签单"}</span></span><span className={`s${signed ? "" : " wait"}`}>{signed ? "满印" : "待签"}</span></div>
                  <div className="c"><span className="bx">{signed ? "✓" : "!"}</span><span><span className="t">指纹随稿件记账</span><span className="d">再改一个字，签发即失效</span></span><span className={`s${signed ? "" : " wait"}`}>{signed ? "已记账" : "未记账"}</span></div>
                  <div className="c"><span className="bx">✓</span><span><span className="t">册架可翻</span><span className="d">并行实验目录 · 陈列馆屏</span></span><span className="s">可达</span></div>
                </div>
              </div>
              <div>
                <div className="h3"><b>如果之后要改</b><span>三 条 路</span></div>
                <div className="kv">
                  <div><span className="k">小改文字</span><span>核验定稿就地改 · 重签</span></div>
                  <div><span className="k">换模型重出</span><span>预测选模改选 · 重新生成</span></div>
                  <div><span className="k">旧版回看</span><span>运行档案 · 旧签发失效留痕</span></div>
                  <div><span className="k">下载</span><span>{signed ? "报告 Word · 已可下载" : "未签发 · 暂不可下载"}</span></div>
                </div>
              </div>
            </div>
            <p className="rel"><b>与报告的关系</b>　归档不是终点：每一期的印、指纹与留痕让任何一版都能说清「这是怎么来的」——可审计、可交接、可复现。</p>
          </div>
        </div>
      </section>
    </div>
  );
}
