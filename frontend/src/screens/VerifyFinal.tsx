import { StatusBand, SectionHead, SectionLink, RelNote, PageFoot } from "../components/shell";
import { Tag, DataPanel, Button, GhostLink, Wrap, Grid2 } from "../components/data";
import { Stamp, StampBox, Seal } from "../components/devices";

const REVS: { t: string; sub: string; ok: boolean }[] = [
  { t: "数字与台账一致", sub: "预测 202609 / 实际输出 202609，逐格回读源表", ok: true },
  { t: "图册出齐", sub: "未进 1% 的八家各一图，共 8 幅", ok: true },
  { t: "正文口径与名词解释一致", sub: "全站一套说法，无技术术语", ok: true },
  { t: "章节齐全", sub: "10 / 11 章节，学院顶尖表本期不选", ok: true },
  { t: "InCites 全球机构排名表口径", sub: "历史 13 期口径不全，本期不影响正文", ok: false },
];

export function VerifyFinal() {
  return (
    <>
      <section className="bg-pine-400 pb-[44px] pt-[50px] text-pine-50">
        <div className="mx-auto grid max-w-[1280px] grid-cols-[minmax(0,1fr)_280px] items-center gap-[52px] px-[30px] max-[1040px]:grid-cols-1">
          <div>
            <div className="font-kai text-[11px] tracking-[.42em] text-pine-50/55">
              站 五 · 雲 南 大 學 圖 書 館 · 學 科 信 息 參 考
            </div>
            <h1 className="mt-[12px] font-serif text-[clamp(38px,5vw,64px)] leading-[1.08] tracking-[.04em]">
              核验定稿
            </h1>
            <p className="mt-[14px] max-w-[34ch] font-kai text-[15px] leading-[2.05] text-pine-50/82">
              复核无异议后签单，这一版才会被标记为「可交付」。签单之后才轮到「签发」二字。
            </p>
            <div className="mt-[15px] inline-block border border-red-100/50 px-[14px] py-[7px] font-kai text-[12.5px] tracking-[.14em] text-red-100">
              管 理 員 當 前 不 能 下 載 未 簽 發 的 初 稿
            </div>
            <div className="mt-[22px] flex flex-wrap items-center gap-[20px]">
              <Button variant="paper">盖 印 签 单 →</Button>
              <GhostLink>看详细过程</GhostLink>
            </div>
          </div>

          <Seal caption="鈐 印 後 即 為 可 交 付" />
        </div>
      </section>

      <StatusBand task="已完成" sign="未签发" right="第 39 期　·　2 0 2 6 0 9　·　屏 題 ＝ 站 名" />

      <section className="pt-[38px]">
        <Wrap>
          <Grid2>
            <div>
              <SectionHead
                kicker="複 核 清 單 · 五 項"
                title="核验清单"
                link={<SectionLink>看运行档案 →</SectionLink>}
              />
              <div className="mt-[6px]">
                {REVS.map((r) => (
                  <div
                    key={r.t}
                    className="grid grid-cols-[auto_minmax(0,1fr)_auto] items-baseline gap-[14px] border-b border-paper-100 py-[11px]"
                  >
                    <span
                      className={`mt-[7px] h-[8px] w-[8px] flex-none ${r.ok ? "bg-pine-200" : "bg-red-300"}`}
                    />
                    <div>
                      <div className="font-serif text-[15px] tracking-[.03em]">{r.t}</div>
                      <div className="mt-[3px] font-kai text-[11.5px] leading-[1.7] tracking-[.12em] text-ink-100">
                        {r.sub}
                      </div>
                    </div>
                    <Tag tone={r.ok ? "g" : "r"}>{r.ok ? "通 過" : "附 註"}</Tag>
                  </div>
                ))}
              </div>
              <RelNote>
                任务完成只代表机器跑完了。签单是人的动作，签完才变「已签发」。
                签发后若发现错，可撤回为「签发已失效」，改完再签。
              </RelNote>
            </div>

            <StampBox head="橡 皮 戳 · 三 枚 全 到 位" caption="三 枚 橡 皮 戳 · 本 期 已 鈐 三" onGreen>
              <Stamp shape="round" title={<>已 并 入<br />台 賬</>} date="09.13" onGreen />
              <Stamp shape="square" title="已 出 稿" date="10.13 15:03" onGreen />
              <Stamp shape="penta" title="復 核 通 過" date="10.16 09:40" onGreen />
            </StampBox>
          </Grid2>
        </Wrap>
      </section>

      <section className="pt-[38px]">
        <Wrap>
          <DataPanel
            pairs={[
              ["期 次", <><b>202609</b>　第 39 期</>],
              ["任 務", <>已完成</>],
              ["簽 發", <>未签发</>],
              ["複 核 項", <><b>5</b> 项 · 通过 4 · 附注 1</>],
              ["簽 單 人", <>卜 彤 · admin</>],
              ["產 物", <>7 件 · 約 24 頁</>],
            ]}
          />
        </Wrap>
      </section>

      <PageFoot left="雲 南 大 學 圖 書 館 · 學 科 信 息 參 考" right="站 五 / 五　·　核 驗 定 稿" />
    </>
  );
}
