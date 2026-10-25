/* 跨页双联工作台壳（rick 2026-10-25 过审稿的整体搬入）
   原稿：web/mockups/工作台壳-跨页左栏（静态稿 20261025）.html —— 左页「会泽」深绿品牌面 /
   右页「至公」纸面工作面，订口金线；钤印位＝纸卡垫底＋状态印（随屏与签发态换面）。
   本屏是设计效果预览：三屏内容与静态稿同字同数（演示数据，未接 /api）；
   过审后才是接真数据、替掉 lab 旧顶栏那一层。
   样式在 spread.css，全部收在 .sp-spread 作用域下，不碰 lab 其他屏。 */

import { useState, type CSSProperties } from "react";
import "../spread.css";

const SERIF = "'Noto Serif SC','Source Han Serif SC','Songti SC',SimSun,serif";

type ScreenId = "acquire" | "pick" | "draft" | "review" | "archive" | "report";

const SCREENS: Record<
  ScreenId,
  {
    ov: string; title: string; crumb: string; stm: string; sub: string;
    cta: string; alt: string; task: string; sign: string; count: string;
  }
> = {
  acquire: {
    ov: "本期 · 第 一 站", title: "取数核验", crumb: "出报告 · 第 一 站",
    stm: "机器取数，人来核对。",
    sub: "取回的原始数据只进台账，不直接进报告。核对无误并入后，下一站才拿它选章节。",
    cta: "去预测选模 →", alt: "看运行档案",
    task: "已完成", sign: "未签发", count: "64 / 64",
  },
  pick: {
    ov: "本期 · 第 二 站", title: "预测选模", crumb: "出报告 · 第 二 站",
    stm: "模型替学科作答，人来定夺。",
    sub: "五个模型各自外推，V1 给推荐；改选要写理由。保存后，这一期出图与正文就按你的选择。",
    cta: "保存并去生成初稿 →", alt: "看五家全图",
    task: "已完成", sign: "未签发", count: "五家已保存",
  },
  draft: {
    ov: "本期 · 第 三 站", title: "生成初稿", crumb: "出报告 · 第 三 站",
    stm: "台账往前推一步，报告就有初稿。",
    sub: "图、表、正文一次生成：数字只来自台账，正文只走句子骨架。初稿不是成品，签发前不可下载。",
    cta: "去核验定稿 →", alt: "看可视化工作流",
    task: "已完成", sign: "未签发", count: "10-13 15:03",
  },
  report: {
    ov: "本期 · 成 品", title: "报告台", crumb: "报告台 · 成品展示",
    stm: "一期成册，逐格可追。",
    sub: "报告里的每一个数字都能回到台账单元格；签发前只能是初稿，不可下载。",
    cta: "去核验定稿 →", alt: "看图册",
    task: "已完成", sign: "未签发", count: "第 39 期",
  },
  review: {
    ov: "本期 · 第 四 站", title: "核验定稿", crumb: "出报告 · 第 四 站",
    stm: "机器保数字，取舍你来定。",
    sub: "红件逐条过，人工项补齐，核对全绿才签。签单把这一版钉住，改一个字签发就失效。",
    cta: "提交签单 →", alt: "看红件清单",
    task: "进行中", sign: "未签发", count: "54 项",
  },
  archive: {
    ov: "本期 · 第 五 站", title: "签发归档", crumb: "出报告 · 第 五 站",
    stm: "签发即归档，册架见。",
    sub: "签单把这一版钉进档案：指纹记账、报告可下载、册架可翻。之后改内容＝重出＝新版本再签。",
    cta: "去陈列馆看册 ↗", alt: "看运行档案",
    task: "已完成", sign: "已签发", count: "可下载",
  },
};

/* ── 状态印：印面与「状态印章·谱 20261025」逐字一致（正本在 web/src/StateSeal.tsx） ── */

type SealState = "merged" | "drafted" | "unsigned" | "signed";

function SealFace({ state }: { state: SealState }) {
  const ground = state === "signed";
  const ink = state === "merged" || state === "drafted" ? "#264A35" : "#A82F22";
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
          : [["已", 64, 94], ["签", 156, 94], ["发", 110, 180]];
  return (
    <svg viewBox="0 0 220 220">
      <g filter={filter}>
        {frame}
        {inner}
        <g fontFamily={SERIF} fontWeight={700} fontSize={56} textAnchor="middle"
           fill={ground ? "#F5F3EC" : ink}>
          {chars.map(([ch, x, y], i) => <text key={i} x={x} y={y}>{ch}</text>)}
        </g>
      </g>
    </svg>
  );
}

export function WorkbenchSpread() {
  const [cur, setCur] = useState<ScreenId>("acquire");
  const [signed, setSigned] = useState(false);
  const [land, setLand] = useState(false);
  const [lw, setLw] = useState("28%");
  const conf = SCREENS[cur];
  /* 印随屏换面：机器站（取数/选模）=并入台账干印；生成初稿站=已出稿干印；
     核验定稿=未签发虚框，签后=满印；签发归档=满印。 */
  const sealState: SealState =
    cur === "draft" ? "drafted"
      : cur === "review" ? (signed ? "signed" : "unsigned")
        : cur === "archive" ? "signed"
          : "merged";

  const sign = () => {
    if (signed) return;
    setSigned(true);
    setLand(true);
    window.setTimeout(() => setLand(false), 650);
  };

  /* 沿 CTA 走完整站：一按一站；核验定稿按了先签、签完再去归档 */
  const ctaGo = () => {
    if (cur === "acquire") setCur("pick");
    else if (cur === "pick") setCur("draft");
    else if (cur === "draft" || cur === "report") setCur("review");
    else if (cur === "review") { if (signed) setCur("archive"); else sign(); }
    /* archive 的「去陈列馆」是演示外链，此处不动 */
  };

  /* 工序条＝五站，可点跳站；签后末两站换话 */
  const STEPS: Array<{ k: ScreenId; lb: string; ms: string; cls: string }> = [
    { k: "acquire", lb: "取数核验", ms: "64 / 64", cls: "done" },
    { k: "pick", lb: "预测选模", ms: "五家已保存", cls: "done" },
    { k: "draft", lb: "生成初稿", ms: "10-13 15:03", cls: "done" },
    { k: "review", lb: "核验定稿", ms: "待提交签单", cls: signed ? "done" : "now" },
    { k: "archive", lb: "签发归档", ms: "未开始", cls: "" },
  ];

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
          <p className="vol"><span className="b">第 39 期</span><span className="c">二零二六年九月</span></p>
          <div className="rule" />
          <p className="stm">{conf.stm}</p>
          <p className="sub">{conf.sub}</p>
          <div className="acts">
            {/* CTA 接通全流程动线：取数→选模→初稿→核验→签单→归档；报告台→核验定稿 */}
            <button className="btn" type="button" onClick={ctaGo}>
              {cur === "review" && signed ? "去签发归档 →" : conf.cta}
            </button>
            <a className="ghost" href="#spread" onClick={(e) => e.preventDefault()}>{conf.alt}</a>
          </div>
          <div className="state">
            <div className="s"><span className="k">任 务</span><span className="v">{conf.task}</span></div>
            <div className="s"><span className="k">签 发</span><span className="v">{signed ? "已签发" : conf.sign}</span></div>
            <div className="s"><span className="k">取 数</span><span className="v">{conf.count}</span></div>
          </div>
        </div>
        <div className="footline">
          <span>会 泽 百 家 · 至 公 天 下</span>
          <span>admin · 管理员</span>
        </div>
      </aside>

      {/* 钤印位：纸卡垫底＋状态印（随屏换：取数=并入台账；签发态=未签发↔已签发） */}
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
          <span>202609</span>
          <div className="r">
            <span className="density" role="group" aria-label="左栏宽度">
              {([["34%", "宽松"], ["28%", "紧凑"], ["24%", "极窄"]] as const).map(([v, name]) => (
                <button key={v} type="button" onClick={() => setLw(v)}
                        aria-pressed={lw === v ? "true" : "false"}>{name}</button>
              ))}
            </span>
            <a href="#spread" onClick={(e) => e.preventDefault()}>陈列馆 ↗</a>
          </div>
        </div>

        <div className="steps" aria-label="出报告工序">
          <div className="pt" aria-hidden="true" />
          <div className="pr" aria-hidden="true" style={{ width: signed ? "100%" : "75%" }} />
          {STEPS.map((t) => (
            <button key={t.k} type="button"
                    className={`st ${t.cls}${t.k === cur ? " here" : ""}`}
                    onClick={() => { if (t.k !== "archive" || signed) setCur(t.k); }}
                    aria-disabled={t.k === "archive" && !signed ? "true" : undefined}
                    title={t.k === "archive" && !signed ? "签发后开放" : `去${t.lb}站`}>
              <span className="lb">{t.lb}</span>
              <span className="ms">{signed && t.k === "review" ? "已签发 · 可下载"
                : signed && t.k === "archive" ? "已归档 · 册架见" : t.ms}</span>
            </button>
          ))}
        </div>

        {/* 屏一 · 取数核验 */}
        <div className="screen" hidden={cur !== "acquire"}>
          <div className="body">
            <div className="roster">
              <div className="rh">
                <h2>取数清单</h2>
                <span className="n">九 个 台 · 八 表</span>
                <span className="r">当期取数台 × 馆内核对</span>
              </div>
              <div className="rows">
                <div className="rr head"><span>台 表</span><span>出 处</span><span className="num">张 数</span><span className="stt">状 态</span></div>
                <div className="rr"><span className="nm">ESI 全球机构总表</span><span className="tx">Clarivate · 自动取数台</span><span className="num">1 张</span><span className="stt">已取</span></div>
                <div className="rr"><span className="nm">22 学科机构表</span><span className="tx">ESI · 分学科</span><span className="num">22 张</span><span className="stt">已取</span></div>
                <div className="rr"><span className="nm">全球·中国-云大学科汇总</span><span className="tx">ESI · 三口径</span><span className="num">1 张</span><span className="stt">已取</span></div>
                <div className="rr"><span className="nm">云大 Top·高被引热点论文明细</span><span className="tx">ESI · 论文清单</span><span className="num">1 张</span><span className="stt">已取</span></div>
                <div className="rr"><span className="nm">三张阈值、三张基线</span><span className="tx">ESI · 阈值与基线</span><span className="num">6 张</span><span className="stt">已取</span></div>
                <div className="rr"><span className="nm">InCites 分学科全球机构排名表</span><span className="tx">Clarivate · 22 张</span><span className="num">22 张</span><span className="stt">已取</span></div>
                <div className="rr"><span className="nm">InCites 全球-中国·云大 22 学科汇总</span><span className="tx">InCites · 三口径</span><span className="num">1 张</span><span className="stt">已取</span></div>
                <div className="rr off"><span className="nm">InCites 全球机构排名表</span><span className="tx">InCites · 名录</span><span className="num">1 张</span><span className="stt wait">待核验</span></div>
              </div>
              <p className="roster-foot">
                已 取 7 / 8 · 六十四份清单齐全 · 缺一份就阻滞取补
              </p>
            </div>

            <div className="grid2">
              <div>
                <div className="h3"><b>校验项</b><span>六 条</span></div>
                <div className="chk">
                  <div className="c"><span className="bx">✓</span><span><span className="t">期次号与目录号一致</span><span className="d">202609 / 202609</span></span><span className="s">通过</span></div>
                  <div className="c"><span className="bx">✓</span><span><span className="t">源表张数齐全</span><span className="d">64 / 64</span></span><span className="s">通过</span></div>
                  <div className="c"><span className="bx">✓</span><span><span className="t">云大口径可解析</span><span className="d">全文化 · YUNNAN</span></span><span className="s">通过</span></div>
                  <div className="c"><span className="bx">✓</span><span><span className="t">阈值表三条线齐全</span><span className="d">1‰ · 1% · 10%</span></span><span className="s">通过</span></div>
                  <div className="c"><span className="bx">✓</span><span><span className="t">论文明细行数与汇总一致</span><span className="d">291 条明细</span></span><span className="s">通过</span></div>
                  <div className="c"><span className="bx wait">!</span><span><span className="t">InCites 全球机构排名表待核</span><span className="d">历史 13 期口径不全</span></span><span className="s wait">待核</span></div>
                </div>
              </div>
              <div>
                <div className="h3"><b>本期数据</b><span>以任务记录为准</span></div>
                <div className="kv">
                  <div><span className="k">期次</span><span>202609 · 第 39 期</span></div>
                  <div><span className="k">预测 / 输出</span><span>202609 / 202609</span></div>
                  <div><span className="k">取数开始</span><span>2026-09-28 07:55</span></div>
                  <div><span className="k">取数完成</span><span>2026-09-28 12:40</span></div>
                  <div><span className="k">落表份数</span><span>64 / 64</span></div>
                  <div><span className="k">核对并入</span><span>已并入台账</span></div>
                </div>
                <div className="h3 h3-mt"><b>合并文件</b><span>台账母本</span></div>
                <p className="fname">云大全学科排名、阈值动态检测表.xlsx</p>
                <p className="fmtime">最后修改 2026-09-28 07:55</p>
              </div>
            </div>

            <p className="rel"><b>与报告的关系</b>　本期取回的原始数据只进台账，不直接进报告。核对无误并入台账，下一站才拿它选章节；缺一份就阻滞取补，不得越站往下走。</p>
          </div>
        </div>

        {/* 屏二 · 预测选模 */}
        <div className="screen" hidden={cur !== "pick"}>
          <div className="body">
            <div className="roster">
              <div className="rh">
                <h2>本期选模</h2>
                <span className="n">五 学 科 · 两 条 路 线</span>
                <span className="r">V1 推荐 × 馆员定夺</span>
              </div>
              <div className="rows">
                <div className="rr head"><span>潜 力 学 科</span><span>V 1 推 荐</span><span className="num">本 期 已 选</span><span className="stt">来 源</span></div>
                <div className="rr"><span className="nm">免疫学</span><span className="tx">季节性 ETS 模型</span><span className="num">SARIMA 模型</span><span className="stt wait">已改选</span></div>
                <div className="rr"><span className="nm">分子生物学与遗传学</span><span className="tx">季节性 ETS 模型</span><span className="num">同推荐</span><span className="stt">默认</span></div>
                <div className="rr"><span className="nm">多 学 科</span><span className="tx">Holt 趋势模型</span><span className="num">同推荐</span><span className="stt">默认</span></div>
                <div className="rr"><span className="nm">物 理 学</span><span className="tx">经验贝叶斯状态空间</span><span className="num">同推荐</span><span className="stt">默认</span></div>
                <div className="rr"><span className="nm">神经科学与行为科学</span><span className="tx">季节性 ETS 模型</span><span className="num">同推荐</span><span className="stt">默认</span></div>
              </div>
              <p className="roster-foot">路 线 1 · 总 被 引 / ESI 前 1% 被 引 阈 值 · 改 选 已 备 注 理 由</p>
            </div>
            <div className="grid2">
              <div>
                <div className="h3"><b>选模从哪来</b><span>三 步</span></div>
                <div className="chk">
                  <div className="c"><span className="bx">✓</span><span><span className="t">五家模型各自外推两个出榜期</span><span className="d">外推窗口 202611 · 202701</span></span><span className="s">完成</span></div>
                  <div className="c"><span className="bx">✓</span><span><span className="t">V1 按历史回测误差给推荐</span><span className="d">近 12 期回测 · 误差最小</span></span><span className="s">完成</span></div>
                  <div className="c"><span className="bx">✓</span><span><span className="t">馆员改选并备注理由</span><span className="d">免疫学 → SARIMA · 季节稳健</span></span><span className="s">已保存</span></div>
                </div>
              </div>
              <div>
                <div className="h3"><b>保存记录</b><span>以台账记录为准</span></div>
                <div className="kv">
                  <div><span className="k">路线</span><span>路线 1 · 总被引</span></div>
                  <div><span className="k">模型</span><span>五 家</span></div>
                  <div><span className="k">改选</span><span>1 处（免疫学）</span></div>
                  <div><span className="k">保存</span><span>admin · 10-11 09:12</span></div>
                </div>
                <div className="h3 h3-mt"><b>生效时机</b><span>当 期 生 效</span></div>
                <p className="fname">保存后即为本期选定；重新生成才写进报告。</p>
                <p className="fmtime">改选不改正台账数字，只改预测用哪只模型。</p>
              </div>
            </div>
            <p className="rel"><b>与报告的关系</b>　选模决定潜力学科的图与正文按哪个模型出；已保存的选择 ≠ 报告已用的选择，重新生成后才更新。</p>
          </div>
        </div>

        {/* 屏三 · 生成初稿 */}
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
                <div className="rr"><span className="nm">取数核验</span><span className="tx">已并入台账</span><span className="num">64 / 64</span><span className="stt">完成</span></div>
                <div className="rr"><span className="nm">预测选模</span><span className="tx">五家已保存 · 1 处改选</span><span className="num">第 39 期</span><span className="stt">完成</span></div>
                <div className="rr"><span className="nm">生成初稿</span><span className="tx">图 108 张 · 正文六章</span><span className="num">10-13 15:03</span><span className="stt">完成</span></div>
              </div>
              <p className="roster-foot">本 期 用 时 3 分 42 秒 · 重 出 会 撤 下 当 前 成 品（旧 稿 可 回 滚）</p>
            </div>
            <div className="grid2">
              <div>
                <div className="h3"><b>本期读数</b><span>出 稿 即 定</span></div>
                <div className="kv">
                  <div><span className="k">学科在监测</span><span>22</span></div>
                  <div><span className="k">已进前 1%</span><span>14</span></div>
                  <div><span className="k">热点 · 高被引</span><span>291</span></div>
                  <div><span className="k">正文用模型</span><span>阻尼 Holt 等五家</span></div>
                </div>
              </div>
              <div>
                <div className="h3"><b>这次生成用了</b><span>记 录 如 实</span></div>
                <div className="kv">
                  <div><span className="k">取数</span><span>64 / 64 已并入</span></div>
                  <div><span className="k">选模</span><span>路线 1 · 1 处改选</span></div>
                  <div><span className="k">开始 / 完成</span><span>10-13 15:03 · 15:07</span></div>
                  <div><span className="k">产物</span><span>报告 docx · 图 108 张</span></div>
                </div>
                <div className="h3 h3-mt"><b>初稿的处境</b><span>未 签 发</span></div>
                <p className="fname">初稿不可下载；核对全绿并签单后才算成品。</p>
                <p className="fmtime">重出会撤下当前成品——旧稿先归档，可回滚可追溯。</p>
              </div>
            </div>
            <p className="rel"><b>与报告的关系</b>　初稿里的每一个数字都能回溯到台账单元格；正文只走句子骨架，不存在模型顺手算的数。签发前它只是草稿。</p>
          </div>
        </div>

        {/* 屏四 · 报告台 */}
        <div className="screen" hidden={cur !== "report"}>
          <div className="issue">
            <h2>第 39 期</h2>
            <span className="when">二零二六年九月 · 202609</span>
            <span className="tag" id="sp-sign-tag">{signed ? "已 签 发" : "未 签 发"}</span>
          </div>
          <div className="nums">
            <div className="n"><div className="k">学 科 在 监 测</div><div className="v">22</div></div>
            <div className="n"><div className="k">已 进 前 1 %</div><div className="v">14</div></div>
            <div className="n"><div className="k">热 点 · 高 被 引</div><div className="v">291</div></div>
          </div>
          <div className="body">
            <div className="grid2">
              <div>
                <div className="h3"><b>目 录</b><span>成 册 版 式</span><span className="r">六 章</span></div>
                <div className="toc-list">
                  <div className="l"><span className="no">一</span><span>概述</span><span className="pg">P. 1</span></div>
                  <div className="l"><span className="no">二</span><span>我校学科发展情况</span><span className="pg">P. 2</span></div>
                  <div className="l"><span className="no">三</span><span>我校潜力学科趋势预测</span><span className="pg">P. 26</span></div>
                  <div className="l"><span className="no">四</span><span>云南省主要高校学科发展基本情况</span><span className="pg">P. 28</span></div>
                  <div className="l"><span className="no">五</span><span>我校顶尖论文清单</span><span className="pg">P. 30</span></div>
                  <div className="l"><span className="no">附</span><span>名词解释</span><span className="pg" /></div>
                </div>
              </div>
              <div>
                <div className="h3"><b>图 表</b><span>按学科分组</span><span className="r">108 张</span></div>
                <div className="figlist" aria-hidden="true">
                  {Array.from({ length: 16 }, (_, i) => <i key={i} />)}
                </div>
                <p className="fig-note">
                  逐学科进榜与接近度 · 点缩略图看大图，图上数字可回溯到台账单元格。
                </p>
              </div>
            </div>
            <div className="h3 h3-mt2"><b>签单前后</b><span>这 一 版 的 处 境</span></div>
            <div className="kv">
              <div><span className="k">核对项</span><span>54 项全绿</span></div>
              <div><span className="k">红件</span><span>715 条</span></div>
              <div><span className="k">待人工</span><span>7 处</span></div>
              <div><span className="k">签发</span><span>{signed ? "已签发 · 可下载" : "未签发 · 初稿不可下载"}</span></div>
            </div>
          </div>
        </div>

        {/* 屏五 · 核验定稿 */}
        <div className="screen" hidden={cur !== "review"}>
          <div className="rv">
            <div>
              <div className="preview">
                <div className="ph"><b>第 39 期 · 初稿</b><span>逐 格 可 追</span></div>
                <div className="doc">
                  <p className="h">二　我校学科发展情况</p>
                  <p>本期有 14 个学科进入 ESI 全球前 1%，较上期新增 1 个。材料科学接近度 96.3%，为最接近入围的学科。</p>
                  <p className="h">三　我校潜力学科趋势预测</p>
                  <p>按本期所选模型（阻尼 Holt）外推，未来两个出榜期最可能入围的是化学与工程学。</p>
                  <p className="h">四　云南省主要高校学科发展基本情况</p>
                  <p>省内有 6 所高校进入 ESI 榜单，云南大学在 22 个学科中有 14 个进榜。</p>
                </div>
              </div>
            </div>
            <div>
              <div className="sign">
                <div className="sh">签 单</div>
                <ul>
                  <li><span className="k">核 对 项</span><span className="v">54 / 54 通过</span></li>
                  <li><span className="k">红 件</span><span className="v bad">715 条待处理</span></li>
                  <li><span className="k">待 人 工</span><span className="v bad">7 处</span></li>
                  <li><span className="k">回 写 台 账</span><span className="v">未执行</span></li>
                  <li><span className="k">指 纹</span><span className="v">签单时生成</span></li>
                </ul>
                <p className="note">
                  签下这一版，指纹随稿件一起记账；再改一个字，签发即失效，需要重签。
                  {signed && (
                    <a href="#spread" className="revoke"
                       onClick={(e) => { e.preventDefault(); setSigned(false); }}>撤回签发（演示）</a>
                  )}
                </p>
                <button className="go" type="button" onClick={sign} disabled={signed}>
                  {signed ? "已 签 发 · 这 一 版 已 锁 定" : "签 单 并 锁 定"}
                </button>
              </div>
            </div>
          </div>
        </div>

        {/* 屏六 · 签发归档 */}
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
                <div className="rr"><span className="nm">签发指纹</span><span className="tx">随稿件一起记账；改动即失效</span><span className="num">09-28 14:20</span><span className="stt">已记账</span></div>
                <div className="rr"><span className="nm">报告 Word</span><span className="tx">报告_202609_第39期.docx</span><span className="num">—</span><span className="stt">可下载</span></div>
                <div className="rr"><span className="nm">册架</span><span className="tx">陈列馆 · 第 39 期册</span><span className="num">—</span><span className="stt">已上架</span></div>
                <div className="rr"><span className="nm">运行档案</span><span className="tx">任务、比对、红件全程留痕</span><span className="num">—</span><span className="stt">已归档</span></div>
              </div>
              <p className="roster-foot">归 档 之 后 内 容 不 再 改 动 · 改 内 容 ＝ 重 出 ＝ 新 版 本 再 签</p>
            </div>
            <div className="grid2">
              <div>
                <div className="h3"><b>这一版的印</b><span>已 钤</span></div>
                <div className="chk">
                  <div className="c"><span className="bx">✓</span><span><span className="t">已签发</span><span className="d">admin · 2026-09-28 14:20</span></span><span className="s">满印</span></div>
                  <div className="c"><span className="bx">✓</span><span><span className="t">指纹随稿件记账</span><span className="d">再改一个字，签发即失效</span></span><span className="s">已记账</span></div>
                  <div className="c"><span className="bx">✓</span><span><span className="t">册架可翻</span><span className="d">陈列馆 · 册序列</span></span><span className="s">已上架</span></div>
                </div>
              </div>
              <div>
                <div className="h3"><b>如果之后要改</b><span>三 条 路</span></div>
                <div className="kv">
                  <div><span className="k">小改文字</span><span>核验定稿就地改 · 重签</span></div>
                  <div><span className="k">换模型重出</span><span>预测选模改选 · 重新生成</span></div>
                  <div><span className="k">旧版回看</span><span>运行档案 · 旧签发失效留痕</span></div>
                  <div><span className="k">下载</span><span>报告 Word · 已可下载</span></div>
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
