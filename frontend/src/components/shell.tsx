/**
 * 壳件 —— TopBar / StatusBand / SectionHead / PageFoot
 * 将来可整块搬走。用词按《全站-冗余收敛对照稿》定词表。
 */
import type { ReactNode } from "react";

/* ── TopBar 顶栏（含 5 站导航） ───────────────────────── */
export type Station = { id: string; name: string };

export const STATIONS: Station[] = [
  { id: "acquire", name: "取数核验" },
  { id: "chapter", name: "选章节" },
  { id: "pick", name: "预测选模" },
  { id: "draft", name: "生成初稿" },
  { id: "verify", name: "核验定稿" },
];

export function TopBar({
  current,
  onGo,
  right,
}: {
  current?: string;
  onGo?: (id: string) => void;
  right?: ReactNode;
}) {
  return (
    <header className="flex h-[60px] items-center gap-[22px] bg-pine-400 px-[30px]">
      <span className="font-serif text-[20px] tracking-[.18em] text-pine-50">文衡</span>
      <span className="font-kai text-[13px] leading-[1.55] tracking-[.22em] text-pine-50/80">
        雲 南 大 學 圖 書 館
        <br />
        學 科 信 息 參 考
      </span>
      <nav className="ml-[14px] flex gap-[2px]" aria-label="五站五屏">
        {STATIONS.map((s, i) => {
          const on = s.id === current;
          const idx = STATIONS.findIndex((x) => x.id === current);
          const done = idx > -1 && i < idx;
          return (
            <button
              key={s.id}
              onClick={() => onGo?.(s.id)}
              style={{ transition: "background-color 120ms linear" }}
              className={[
                "whitespace-nowrap rounded-none px-[14px] py-2 font-kai text-[12px] tracking-[.14em] active:bg-pine-50/15 wh-press",
                on
                  ? "bg-pine-50 font-bold text-pine-400"
                  : done
                    ? "text-pine-100"
                    : "text-pine-50/80",
              ].join(" ")}
            >
              {done ? "✓ " : `${i + 1} `}
              {s.name}
            </button>
          );
        })}
      </nav>
      <div className="ml-auto flex items-center gap-[16px] font-kai text-[13px] tracking-[.22em] text-pine-50/80">
        {right ?? (
          <>
            <span>出 报 告 ↖</span>
            <Palette />
          </>
        )}
      </div>
    </header>
  );
}

export function Palette() {
  return (
    <span className="inline-flex gap-[7px]">
      <i className="h-[12px] w-[22px] border border-pine-50/25 bg-pine-200" />
      <i className="h-[12px] w-[22px] border border-pine-50/25 bg-pine-400" />
    </span>
  );
}

/* ── StatusBand 状态带（任务 + 签发，全站两套词） ───────── */
export function StatusBand({
  task,
  sign,
  right,
}: {
  task: string;
  sign: string;
  right?: ReactNode;
}) {
  return (
    <div className="flex flex-wrap items-center gap-[20px] bg-pine-400 px-[30px] py-[15px] font-kai text-[12px] tracking-[.22em] text-pine-50">
      <span className="bg-pine-200 px-[13px] py-1 font-serif text-[13px] tracking-[.18em] text-[#08201A]">
        任务 · {task}
      </span>
      <span className="bg-pine-200 px-[13px] py-1 font-serif text-[13px] tracking-[.18em] text-pine-50">
        签发 · {sign}
      </span>
      <div className="ml-auto text-pine-50/60">{right}</div>
    </div>
  );
}

/* ── SectionHead 分节标题 ─────────────────────────── */
export function SectionHead({
  kicker,
  title,
  link,
}: {
  kicker: string;
  title: string;
  link?: ReactNode;
}) {
  return (
    <div className="flex flex-wrap items-baseline gap-[16px] border-b-2 border-ink-300 pb-[11px]">
      <h2 className="text-[22px] tracking-[.1em]">
        <span className="mb-[2px] block font-kai text-[10.5px] font-normal tracking-[.42em] text-ink-100">
          {kicker}
        </span>
        {title}
      </h2>
      {link ? <div className="ml-auto">{link}</div> : null}
    </div>
  );
}

export function SectionLink({ children }: { children: ReactNode }) {
  return (
    <a
      href="#"
      className="wh-press pb-[2px] font-kai text-[12.5px] tracking-[.18em] text-pine-300 shadow-[inset_0_-1px_0_var(--color-pine-300)] hover:text-pine-200 active:text-pine-400"
      style={{ transition: "color 120ms linear, box-shadow 120ms linear" }}
    >
      {children}
    </a>
  );
}

/* ── RelNote 与报告的关系 ─────────────────────────── */
export function RelNote({ children }: { children: ReactNode }) {
  return (
    <p className="mt-[18px] max-w-[92ch] font-kai text-[13px] leading-[2] tracking-[.12em] text-ink-100">
      <b className="font-serif font-bold tracking-[.16em] text-ink-200">與 報 告 的 關 係</b>
      {children}
    </p>
  );
}

/* ── PageFoot 页脚 ───────────────────────────────── */
export function PageFoot({ left, right }: { left: string; right?: ReactNode }) {
  return (
    <footer className="mt-[44px] flex flex-wrap justify-between gap-[16px] bg-ink-300 px-[30px] py-[22px] font-kai text-[13px] tracking-[.32em] text-pine-50/80">
      <div>
        <b className="mb-1 block font-serif text-[12.5px] tracking-[.22em] text-pine-50">文衡 · 汇</b>
        {left}
      </div>
      <div className="flex items-center gap-[11px]">
        <i className="h-[12px] w-[24px] bg-pine-200" />
        <i className="h-[12px] w-[24px] bg-pine-200" />
        <span>青 瓷 綠　·　唯 一 主 色</span>
      </div>
      <div>{right}</div>
    </footer>
  );
}
