import { StatusBand, SectionHead, SectionLink, RelNote, PageFoot } from "../components/shell";
import { Tag, DataPanel, Button, GhostLink, Wrap, Grid2 } from "../components/data";
import { FlapDigits, FlapGroup, Gauge, MotionStyles } from "../components/devices";

const SOURCES: { name: string; sub: string; n: string; done: boolean }[] = [
  { name: "ESI 全球机构总表", sub: "Clarivate · 自动取数台", n: "1 张", done: true },
  { name: "22 学科机构表", sub: "ESI · 分学科", n: "22 张", done: true },
  { name: "全球·中国·云大学科汇总", sub: "ESI · 三口径", n: "1 张", done: true },
  { name: "云大 Top·高被引·热点论文明细", sub: "ESI · 论文清单", n: "1 张", done: true },
  { name: "三张阈值 · 三张基线", sub: "ESI · 阈值与基线", n: "6 张", done: true },
  { name: "InCites 分学科全球机构排名表", sub: "Clarivate · 22 张", n: "22 张", done: true },
  { name: "InCites 全球机构排名表", sub: "Clarivate · 总表", n: "1 张", done: false },
];

const CHECKS: { t: string; ok: boolean }[] = [
  { t: "期次号与目录号一致　202609 / 202609", ok: true },
  { t: "源表张数齐全　64 / 64", ok: true },
  { t: "云大口径可解析（全文搜 YUNNAN）", ok: true },
  { t: "阈值表三条线齐全", ok: true },
  { t: "论文明细行数与汇总一致", ok: true },
  { t: "InCites 全球机构排名表待核（历史 13 期口径不全）", ok: false },
];

export function AcquireCheck() {
  return (
    <>
      <MotionStyles />
      <section className="bg-pine-300 pb-[40px] pt-[46px] text-pine-50">
        <div className="mx-auto grid max-w-[1280px] grid-cols-[minmax(0,1fr)_auto] items-end gap-[48px] px-[30px] max-[1040px]:grid-cols-1">
          <div className="wh-reveal" style={{ animationDelay: "0ms" }}>
            <div className="font-kai text-[13px] tracking-[.42em] text-pine-50">
              站 一 · 雲 南 大 學 圖 書 館 · 學 科 信 息 參 考
            </div>
            <h1 className="mt-[12px] font-serif text-[clamp(38px,5vw,66px)] leading-[1.06] tracking-[.04em]">
              取数核验
            </h1>
            <p className="mt-[14px] max-w-[34ch] font-kai text-[15px] leading-[2.05] text-pine-50">
              机器先把当期原始数据取回来（取数），人再逐项核对（取数核验）。两步合在一屏。
            </p>
            <div className="mt-[24px] flex flex-wrap items-center gap-[20px]">
              <Button>开 始 取 数 →</Button>
              <GhostLink>看运行档案</GhostLink>
            </div>
          </div>

          <FlapGroup>
            <FlapDigits
              label="期 次 · 目 錄 號"
              pieces={[
                { kind: "d", v: "2" }, { kind: "d", v: "0" }, { kind: "d", v: "2" },
                { kind: "d", v: "6", tone: "gr" }, { kind: "d", v: "0", tone: "rd" }, { kind: "d", v: "9", tone: "rd" },
              ]}
            />
            <FlapDigits
              label="開 始 · 完 成" size="sm"
              pieces={[
                { kind: "d", v: "0", tone: "gr" }, { kind: "d", v: "7", tone: "gr" }, { kind: "colon" },
                { kind: "d", v: "5", tone: "gr" }, { kind: "d", v: "5", tone: "gr" }, { kind: "gap" },
                { kind: "d", v: "1" }, { kind: "d", v: "2" }, { kind: "colon" },
                { kind: "d", v: "4" }, { kind: "d", v: "0" },
              ]}
            />
            <FlapDigits
              label="數 據 份 數" size="sm"
              pieces={[
                { kind: "d", v: "6", tone: "gr" }, { kind: "d", v: "4", tone: "gr" },
                { kind: "gap" },
                { kind: "d", v: "6", tone: "gr" }, { kind: "d", v: "4", tone: "gr" },
              ]}
            />
          </FlapGroup>
        </div>
      </section>

      <StatusBand task="已完成" sign="未签发" right="第 39 期　·　2 0 2 6 0 9　·　屏 题 ＝ 站 名" />

      <section className="wh-reveal pt-[38px]" style={{ animationDelay: "60ms" }}>
        <Wrap>
          <Grid2>
            <div>
              <SectionHead
                kicker="数 据 来 源 · 两 个 台"
                title="取数清单"
                link={<SectionLink>看运行档案 →</SectionLink>}
              />
              <div className="mt-[6px]">
                {SOURCES.map((s) => (
                  <div
                    key={s.name}
                    className="grid grid-cols-[auto_minmax(0,1fr)_auto_auto] items-center gap-[14px] border-b border-paper-100 py-[11px]"
                  >
                    <div className="h-[26px] w-[26px] flex-none text-pine-200">
                      <svg viewBox="0 0 26 26" fill="none" stroke="currentColor" strokeWidth="1.5">
                        <rect x="3" y="5" width="20" height="16" />
                        <line x1="3" y1="10" x2="23" y2="10" />
                        <line x1="8" y1="15" x2="18" y2="15" />
                      </svg>
                    </div>
                    <div>
                      <div className="font-serif text-[15px] tracking-[.03em]">{s.name}</div>
                      <div className="mt-[2px] font-kai text-[11px] tracking-[.14em] text-ink-100">{s.sub}</div>
                    </div>
                    <div className="font-mono text-[11.5px] tracking-[.12em] text-ink-100">{s.n}</div>
                    <Tag tone={s.done ? "g" : "b"}>{s.done ? "已 取" : "待 核 驗"}</Tag>
                  </div>
                ))}
              </div>
              <RelNote>
                本屏取回的原始数据只进台账，不直接进报告。核对无误后按「核对并并入」并入台账，
                下一站才拿它选章节。缺一份就退回补取，不带病往下走。
              </RelNote>
            </div>

            <div>
              <div className="bg-paper-100 p-[20px_22px]">
                <div className="border-b border-paper-200 pb-[10px] font-kai text-[11.5px] tracking-[.36em] text-ink-100">
                  核 驗 項 · 取 數 核 驗
                </div>
                <ul className="mt-[12px] list-none p-0">
                  {CHECKS.map((c) => (
                    <li
                      key={c.t}
                      className={`flex gap-[11px] border-b border-paper-100 py-[8px] font-kai text-[12.5px] tracking-[.12em] ${
                        c.ok ? "text-ink-200" : "text-ink-100"
                      }`}
                    >
                      <span
                        className={`mt-[2px] h-[7px] w-[7px] flex-none ${c.ok ? "bg-pine-200" : "bg-red-300"}`}
                      />
                      <span>{c.t}</span>
                    </li>
                  ))}
                </ul>
              </div>

              <div className="mt-[18px]">
                <Gauge
                  head="取 數 完 成 度"
                  sub="第 3 9 期 · 2 0 2 6 0 9"
                  short
                  water={100}
                  threshold={100}
                  thresholdLabel="齐 全 线"
                  read="100%"
                  readLabel="6 4 / 6 4"
                />
              </div>
            </div>
          </Grid2>
        </Wrap>
      </section>

      <section className="wh-reveal pt-[38px]" style={{ animationDelay: "120ms" }}>
        <Wrap>
          <DataPanel
            pairs={[
              ["期 次", <><b>202609</b>　第 39 期</>],
              ["取 數 開 始", <>2026-09-28 07:55</>],
              ["取 數 完 成", <>2026-09-28 12:40</>],
              ["源 表 份 數", <><b>64 / 64</b></>],
              ["核 對 並 並 入", <>已并入台账</>],
              ["簽 發", <>未签发</>],
            ]}
          />
        </Wrap>
      </section>

      <PageFoot left="雲 南 大 學 圖 書 館 · 學 科 信 息 參 考" right="站 一 / 五　·　取 數 核 驗" />
    </>
  );
}
