import { SectionHead, SectionLink, RelNote } from "../components/shell";
import { DataTable, DataPanel, Button, GhostLink, Wrap, Grid2, type Col } from "../components/data";
import { FlapDigits, FlapGroup, Gauge, Stamp, StampBox, Seal } from "../components/devices";

type Pick = { subj: string; mdl: string; chosen: string; changed?: boolean };

const PICKS: Pick[] = [
  { subj: "免疫学", mdl: "季节性 ETS 模型", chosen: "SARIMA 模型", changed: true },
  { subj: "分子生物学与遗传学", mdl: "季节性 ETS 模型", chosen: "默 认" },
  { subj: "多学科", mdl: "Holt 趋势模型", chosen: "默 认" },
  { subj: "物理学", mdl: "经验贝叶斯状态空间模型", chosen: "默 认" },
  { subj: "神经科学与行为科学", mdl: "季节性 ETS 模型", chosen: "默 认" },
  { subj: "空间科学", mdl: "SARIMA 模型", chosen: "默 认" },
  { subj: "精神病学与心理学", mdl: "经验贝叶斯状态空间模型", chosen: "默 认" },
  { subj: "经济与商业", mdl: "SARIMA 模型", chosen: "默 认" },
];

const COLS: Col<Pick>[] = [
  {
    key: "subj",
    label: "潛 力 學 科",
    width: "28%",
    render: (r) => <span className="font-bold">{r.subj}</span>,
  },
  { key: "mdl", label: "V 1 推 薦", width: "32%", render: (r) => <span className="font-kai text-[13.5px] tracking-[.12em] text-ink-200">{r.mdl}</span> },
  {
    key: "chosen",
    label: "本 期 已 選",
    render: (r) =>
      r.changed ? (
        <span className="font-bold text-pine-300">
          {r.chosen}
          <span className="ml-[10px] inline-flex items-center gap-[6px] font-kai text-[11.5px] tracking-[.18em] text-sea-300">
            <i className="h-[7px] w-[7px] flex-none bg-sea-300" />
            已改选
          </span>
        </span>
      ) : (
        <span className="font-kai text-[13px] tracking-[.18em] text-ink-100">默 认</span>
      ),
  },
];

export function OutReport() {
  return (
    <>
      {/* 蓝场：题头 ＋ ① 翻牌 */}
      <section className="bg-sea-300 pb-[46px] pt-[52px] text-sea-50">
        <div className="mx-auto grid max-w-[1280px] grid-cols-[minmax(0,1fr)_auto] items-end gap-[56px] px-[30px] max-[1040px]:grid-cols-1">
          <div>
            <div className="font-kai text-[11px] tracking-[.42em] text-sea-50/55">
              雲 南 大 學 圖 書 館 · 學 科 信 息 參 考 · 出 報 告
            </div>
            <h1 className="mt-[12px] font-serif text-[clamp(40px,5.4vw,72px)] leading-[1.06] tracking-[.04em]">
              本期报告已就绪
            </h1>
            <p className="mt-[15px] max-w-[32ch] font-kai text-[15px] leading-[2.05] text-sea-50/80">
              阈值即水位线。复核后签单，这一版才会被标记为「可交付」。任务结束不代表报告合格或已签发。
            </p>
            <div className="mt-[26px] flex flex-wrap items-center gap-[22px]">
              <Button>复 核 并 签 单 →</Button>
              <GhostLink>看详细过程</GhostLink>
            </div>
          </div>

          <FlapGroup>
            <FlapDigits
              label="班 次 · 車 次"
              pieces={[
                { kind: "d", v: "2" },
                { kind: "d", v: "0" },
                { kind: "d", v: "2" },
                { kind: "d", v: "6", tone: "gr" },
                { kind: "d", v: "0", tone: "rd" },
                { kind: "d", v: "9", tone: "rd" },
              ]}
            />
            <FlapDigits
              label="發 車 · 到 站"
              size="sm"
              pieces={[
                { kind: "d", v: "0", tone: "gr" },
                { kind: "d", v: "7", tone: "gr" },
                { kind: "colon" },
                { kind: "d", v: "5", tone: "gr" },
                { kind: "d", v: "5", tone: "gr" },
                { kind: "gap" },
                { kind: "d", v: "1" },
                { kind: "d", v: "5" },
                { kind: "colon" },
                { kind: "d", v: "0" },
                { kind: "d", v: "3" },
              ]}
            />
            <FlapDigits
              label="第 期 · 目 錄 號"
              size="sm"
              pieces={[
                { kind: "d", v: "3" },
                { kind: "d", v: "9" },
                { kind: "gap" },
                { kind: "d", v: "2" },
                { kind: "d", v: "0" },
                { kind: "d", v: "2" },
                { kind: "d", v: "6" },
                { kind: "d", v: "0" },
                { kind: "d", v: "9" },
              ]}
            />
          </FlapGroup>
        </div>
      </section>

      {/* 绿器：② 水位 ＋ 四道工序 */}
      <section className="bg-pine-300 pt-[42px] text-pine-50">
        <div className="mx-auto grid max-w-[1280px] grid-cols-[minmax(0,.92fr)_minmax(0,1.08fr)] items-center gap-[52px] px-[30px] max-[1040px]:grid-cols-1">
          <div>
            <div className="font-kai text-[11px] tracking-[.42em] text-pine-50/55">
              水 位 標 尺 · 接 近 度
            </div>
            <h2 className="mt-[11px] font-serif text-[clamp(26px,3.2vw,40px)] leading-[1.24] tracking-[.03em]">
              阈值即水位线，
              <br />
              本期读数 0.78。
            </h2>
            <p className="mt-[13px] max-w-[30ch] font-kai text-[14px] leading-[2] text-pine-50/78">
              翠湖之畔，滇池淼淼。ESI 前 1% 被引阈值是警戒水位，八家潜力学科各是一根水尺。
            </p>
          </div>

          <Gauge
            head="本 期 水 位"
            sub="第 3 9 期 · 2 0 2 6 0 9"
            water={58}
            threshold={80}
            thresholdLabel="ESI 前 1% 閾 值"
            read="0.78"
            readLabel="本 期 讀 數"
          />
        </div>

        <div className="mx-auto grid max-w-[1280px] grid-cols-4 pb-[40px] pt-[36px]">
          {[
            { k: "一 段 · 立", v: "下载数据核验", m: "64 / 64 完成", w: 100, s: "" },
            { k: "二 段 · 擇", v: "选择章节", m: "按大纲全选", w: 100, s: "" },
            { k: "三 段 · 成", v: "生成初稿", m: "10-13 15:03 已出稿", w: 72, s: "now" },
            { k: "四 段 · 合", v: "核验与定稿", m: "待复核签单", w: 0, s: "todo" },
          ].map((st, i) => (
            <div
              key={st.k}
              className={`pr-[22px] ${i ? "border-l border-pine-50/20 pl-[22px]" : ""}`}
            >
              <div className="mb-[15px] h-[6px] bg-pine-50/20">
                <i
                  className={`block h-full ${
                    st.s === "now" ? "bg-red-100" : st.s === "todo" ? "" : "bg-pine-100"
                  }`}
                  style={{ width: `${st.w}%` }}
                />
              </div>
              <div className="font-kai text-[10.5px] tracking-[.36em] text-pine-50/50">{st.k}</div>
              <div
                className={`mt-[8px] font-serif text-[clamp(18px,2.1vw,25px)] leading-[1.28] tracking-[.03em] ${
                  st.s === "now" ? "text-red-100" : st.s === "todo" ? "text-pine-50/40" : ""
                }`}
              >
                {st.v}
              </div>
              <div className="mt-[7px] font-mono text-[11px] tracking-[.12em] text-pine-50/55">
                {st.m}
              </div>
            </div>
          ))}
        </div>
      </section>

      {/* ③ 橡皮戳 ＋ 数据 */}
      <section className="pt-[38px]">
        <Wrap>
          <Grid2>
            <StampBox head="橡 皮 戳 · 本 期 蓋 章 進 度" caption="三 枚 橡 皮 戳 · 本 期 已 鈐 二">
              <Stamp shape="round" title={<>已 并 入<br />台 賬</>} date="09.13" />
              <Stamp shape="square" title="已 出 稿" date="10.13 15:03" />
              <Stamp shape="penta" title="復 核 通 過" date="PENDING" pending />
            </StampBox>

            <DataPanel
              pairs={[
                ["期 次", <><b>202609</b>　第 39 期</>],
                ["預 測 / 實 際", <>202609 / 202609</>],
                ["下 載 數 據", <><b>64 / 64</b></>],
                ["核 對 並 並 入", <>已并入台账</>],
                ["台 賬 文 件", <>云大全学科排名、阈值动态检测表.xlsx</>],
                ["最 後 修 改", <>2026 年 9 月 28 日 07:55</>],
                ["生 成 初 稿", <>2026-10-13 15:03</>],
                ["任 務", <>已完成</>],
              ]}
            />
          </Grid2>
        </Wrap>
      </section>

      {/* 签单区：④ 钤印 */}
      <section className="mt-[48px] bg-pine-400 pb-[48px] pt-[52px] text-pine-50">
        <div className="mx-auto grid max-w-[1280px] grid-cols-[minmax(0,1fr)_260px] items-center gap-[52px] px-[30px] max-[1040px]:grid-cols-1">
          <div>
            <div className="font-kai text-[11px] tracking-[.42em] text-pine-50/55">
              復 核 並 簽 單
            </div>
            <h2 className="mt-[12px] font-serif text-[clamp(30px,3.9vw,52px)] leading-[1.14] tracking-[.04em]">
              复核后签单，
              <br />
              这一版即可交付。
            </h2>
            <p className="mt-[14px] max-w-[34ch] font-kai text-[14.5px] leading-[2.05] text-pine-50/80">
              任务结束不代表报告合格或已签发。复核无异议后签单，这一版才会被标记为「可交付」。
            </p>
            <div className="mt-[16px] inline-block border border-red-100/50 px-[14px] py-[7px] font-kai text-[12.5px] tracking-[.14em] text-red-100">
              管 理 員 當 前 不 能 下 載 未 簽 發 的 初 稿
            </div>
            <div className="mt-[24px] flex flex-wrap items-center gap-[22px]">
              <Button variant="paper">盖 印 签 单 →</Button>
              <GhostLink>看详细过程</GhostLink>
            </div>
          </div>

          <Seal caption="鈐 印 後 即 為 可 交 付" />
        </div>
      </section>

      {/* 选模表 */}
      <section className="pt-[52px]">
        <Wrap>
          <SectionHead
            kicker="八 家 · 選 模 表"
            title="本期选模"
            link={<SectionLink>去预测台看图改选 →</SectionLink>}
          />
          <div className="mb-[4px] mt-[16px] flex gap-[26px] font-kai text-[13px] tracking-[.14em] text-ink-100">
            <span className="border-b-2 border-pine-300 pb-[7px] font-bold text-ink-300">
              路线1 · 总被引 / ESI 前 1% 被引阈值
            </span>
            <span>路线2 · 国内排名 / 国内前 1% 机构数</span>
          </div>
          <DataTable cols={COLS} rows={PICKS} rowKey={(r) => r.subj} />
          <div className="flex flex-wrap justify-between gap-[14px] pb-[4px] pt-[14px] font-kai text-[12px] tracking-[.22em] text-ink-100">
            <span>已 保 存 · admin · 2026-10-16 12:12</span>
            <span>
              改 選 請 至　<b className="font-serif tracking-[.14em] text-ink-300">預 測 台</b>
            </span>
          </div>
          <RelNote>
            任务启动时固定读取本期已保存选择。重出后，未进 1% 的学科都会按你的选择出图（进本期图册），
            报告正文用接近度前二；所选模型若无法运行，仍按现有规则回退 V1 推荐并留下提醒。
          </RelNote>
        </Wrap>
      </section>
    </>
  );
}
