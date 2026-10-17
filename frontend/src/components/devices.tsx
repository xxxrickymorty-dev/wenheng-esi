/**
 * 四件签名器件 —— FlapDigits / Gauge / Stamp / Seal
 * 前两件属「蓝·场」，后两件属「绿·器」。
 * 牌缝／刻度／戳框／印框是器物本身的结构，不是装饰线。
 */
import type { ReactNode } from "react";

/* ── ① FlapDigits 翻牌数字 ─────────────────────── */
export type FlapPiece =
  | { kind: "d"; v: string; tone?: "gr" | "rd" }
  | { kind: "colon" }
  | { kind: "gap" };

export function FlapDigits({
  label,
  pieces,
  size = "lg",
  align = "right",
}: {
  label: string;
  pieces: FlapPiece[];
  size?: "lg" | "sm";
  align?: "right" | "left";
}) {
  return (
    <div className={align === "right" ? "text-right" : "text-left"}>
      <div className="mb-[7px] font-kai text-[10px] tracking-[.36em] text-sea-50/55">{label}</div>
      <div className="flex gap-[5px]">
        {pieces.map((p, i) => {
          if (p.kind === "colon")
            return (
              <span
                key={i}
                className={`relative grid place-items-center bg-transparent font-mono text-sea-50/40 ${
                  size === "lg" ? "h-[50px] w-[14px] text-[20px]" : "h-[38px] w-[14px] text-[18px]"
                }`}
              >
                :
              </span>
            );
          if (p.kind === "gap")
            return (
              <span key={i} className={size === "lg" ? "w-[16px]" : "w-[16px]"} />
            );
          return (
            <span
              key={i}
              className={[
                "relative grid place-items-center bg-sea-400 font-mono font-bold tabular-nums",
                size === "lg" ? "h-[50px] w-[36px] text-[25px]" : "h-[38px] w-[27px] text-[18px]",
                "after:absolute after:left-0 after:right-0 after:top-1/2 after:h-[2px] after:bg-sea-300",
                p.tone === "gr" ? "text-pine-100" : p.tone === "rd" ? "text-[#E8917C]" : "text-sea-50",
              ].join(" ")}
            >
              {p.v}
            </span>
          );
        })}
      </div>
    </div>
  );
}

export function FlapGroup({ children }: { children: ReactNode }) {
  return (
    <div className="flex flex-col items-end gap-[15px] max-[1040px]:items-start">{children}</div>
  );
}

/* ── ② Gauge 水位标尺 ─────────────────────────── */
export function Gauge({
  head,
  sub,
  read,
  readLabel,
  water = 58,
  threshold,
  thresholdLabel,
  short,
  variant = "green",
}: {
  head: string;
  sub?: string;
  read?: string;
  readLabel?: string;
  water?: number;
  threshold?: number;
  thresholdLabel?: string;
  short?: boolean;
  variant?: "green" | "blue";
}) {
  const skin =
    variant === "green"
      ? "bg-pine-400 border-pine-50/20"
      : "bg-sea-400 border-sea-50/18";
  return (
    <div className={`border p-[18px_22px_20px] ${skin}`}>
      <div className="flex flex-wrap justify-between gap-[14px] font-kai text-[10px] tracking-[.32em] text-pine-50/60">
        <b className="font-serif text-[12px] tracking-[.18em] text-pine-50">{head}</b>
        {sub ? <span>{sub}</span> : null}
      </div>
      <div
        className={`relative mt-[13px] overflow-hidden border border-pine-50/15 bg-pine-400 ${
          short ? "h-[132px]" : "h-[196px]"
        }`}
      >
        {/* 刻度 */}
        <div className="absolute inset-0 z-[3] flex justify-between px-[3px]">
          {Array.from({ length: 13 }).map((_, i) => (
            <span
              key={i}
              className={`w-[1.5px] self-start ${
                i % 4 === 0 ? "h-[19px] bg-pine-50/50" : "h-[10px] bg-pine-50/25"
              }`}
            />
          ))}
        </div>
        {/* 水体 */}
        <div
          className="absolute bottom-0 left-0 right-0 border-t-2 border-pine-100 bg-pine-200"
          style={{ height: `${water}%` }}
        />
        {/* 阈值：警戒水位线 */}
        {threshold !== undefined ? (
          <div
            className="absolute left-0 right-0 z-[4] border-t-2 border-dashed border-red-300"
            style={{ bottom: `${threshold}%` }}
          >
            <span className="absolute right-[7px] top-[-21px] bg-pine-400 px-[8px] py-[2px] font-kai text-[9.5px] tracking-[.24em] text-red-100">
              {thresholdLabel}
            </span>
          </div>
        ) : null}
        {/* 读数 */}
        {read ? (
          <div className="absolute bottom-[10px] left-[13px] z-[5] font-mono text-[26px] tracking-[.1em] text-pine-50">
            {read}
            {readLabel ? (
              <small className="mt-[2px] block font-kai text-[9.5px] tracking-[.3em] text-pine-50/60">
                {readLabel}
              </small>
            ) : null}
          </div>
        ) : null}
      </div>
    </div>
  );
}

/* 表格里的接近度小水尺 */
export function Level({ pct }: { pct: number }) {
  return (
    <div className="flex min-w-[132px] items-center gap-[9px]">
      <div className="relative h-[7px] flex-1 bg-paper-100">
        <i className="absolute bottom-0 left-0 top-0 bg-sea-200" style={{ width: `${pct}%` }} />
        <span className="absolute -bottom-[4px] -top-[4px] right-0 w-[2px] bg-red-300" />
      </div>
      <span className="w-[36px] text-right font-mono text-[11px] tracking-[.08em] text-ink-100">
        {pct}%
      </span>
    </div>
  );
}

/* ── ③ Stamp 橡皮戳 ───────────────────────────── */
export function Stamp({
  shape,
  title,
  date,
  pending,
  onGreen,
}: {
  shape: "round" | "square" | "penta";
  title: ReactNode;
  date: string;
  pending?: boolean;
  onGreen?: boolean;
}) {
  const color = onGreen
    ? shape === "round"
      ? "text-[#A8D4B8]"
      : shape === "square"
        ? "text-pine-100"
        : "text-red-100"
    : shape === "round"
      ? "text-pine-200"
      : shape === "square"
        ? "text-pine-300"
        : "text-red-300";

  const textColor = onGreen
    ? shape === "penta"
      ? "text-[#5A1D12]"
      : "text-pine-400"
    : shape === "penta"
      ? "text-red-ink"
      : "text-pine-400";

  const rot = shape === "round" ? "-rotate-6" : shape === "square" ? "rotate-3" : "-rotate-3";

  return (
    <div className={`relative h-[112px] w-[112px] flex-none ${rot} ${color} ${pending ? "opacity-[.42]" : ""}`}>
      <svg viewBox="0 0 132 132" className="block h-full w-full overflow-visible">
        <defs>
          <filter id={`ink-${shape}-${title}`}>
            <feTurbulence type="fractalNoise" baseFrequency="1.3" numOctaves="2" seed="4" />
            <feDisplacementMap in="SourceGraphic" scale="2.4" />
          </filter>
        </defs>
        <g filter={`url(#ink-${shape}-${title})`}>
          {shape === "round" ? (
            <>
              <circle cx="66" cy="66" r="58" fill="none" stroke="currentColor" strokeWidth="4.5" />
              <circle cx="66" cy="66" r="49" fill="none" stroke="currentColor" strokeWidth="1.5" />
            </>
          ) : shape === "square" ? (
            <>
              <rect x="8" y="8" width="116" height="116" fill="none" stroke="currentColor" strokeWidth="4.5" />
              <rect x="17" y="17" width="98" height="98" fill="none" stroke="currentColor" strokeWidth="1.5" />
            </>
          ) : (
            <>
              <polygon
                points="66,8 122,42 108,108 24,108 10,42"
                fill="none"
                stroke="currentColor"
                strokeWidth="4.5"
              />
              <polygon
                points="66,20 112,47 101,98 31,98 20,47"
                fill="none"
                stroke="currentColor"
                strokeWidth="1.5"
              />
            </>
          )}
        </g>
      </svg>
      <div
        className={`absolute inset-0 flex flex-col items-center justify-center p-[10px] text-center ${textColor}`}
      >
        <span className="font-serif text-[11.5px] font-bold leading-[1.35] tracking-[.08em]">{title}</span>
        <span className="mt-[5px] font-mono text-[10.5px] tracking-[.12em]">{date}</span>
      </div>
    </div>
  );
}

export function StampBox({
  head,
  caption,
  children,
  onGreen,
}: {
  head: string;
  caption: string;
  children: ReactNode;
  onGreen?: boolean;
}) {
  return (
    <div
      className={`px-[22px] pb-[18px] pt-[22px] text-center ${
        onGreen ? "bg-pine-300 text-pine-50" : "bg-paper-100"
      }`}
    >
      <div
        className={`border-b pb-[11px] font-kai text-[10.5px] tracking-[.36em] ${
          onGreen ? "border-pine-50/20 text-pine-50/60" : "border-paper-50 text-ink-100"
        }`}
      >
        {head}
      </div>
      <div className="mt-[18px] flex flex-wrap items-center justify-center gap-[18px]">{children}</div>
      <div
        className={`mt-[16px] font-kai text-[11px] tracking-[.32em] ${
          onGreen ? "text-pine-50/60" : "text-ink-100"
        }`}
      >
        {caption}
      </div>
    </div>
  );
}

/* ── ④ Seal 至公天下 钤印 ─────────────────────── */
export function Seal({ caption }: { caption?: string }) {
  return (
    <div className="flex flex-col items-center gap-[14px]">
      <div className="h-[224px] w-[224px] -rotate-8 max-[1040px]:h-[190px] max-[1040px]:w-[190px]">
        <svg viewBox="0 0 212 212" className="block h-full w-full overflow-visible" aria-label="至公天下 钤印">
          <defs>
            <filter id="seal-ink">
              <feTurbulence type="fractalNoise" baseFrequency="1.1" numOctaves="2" seed="21" />
              <feDisplacementMap in="SourceGraphic" scale="3" />
            </filter>
          </defs>
          <g filter="url(#seal-ink)">
            <rect x="7" y="7" width="198" height="198" fill="#B23A2B" />
            <rect x="21" y="21" width="170" height="170" fill="none" stroke="#DFEDE6" strokeWidth="3.2" />
          </g>
          <g
            fontFamily="'Noto Serif SC','Songti SC',serif"
            fontWeight="700"
            fontSize="58"
            textAnchor="middle"
            fill="#DFEDE6"
            letterSpacing="4"
          >
            <text x="72" y="90">至</text>
            <text x="152" y="90">公</text>
            <text x="72" y="164">天</text>
            <text x="152" y="164">下</text>
          </g>
          <line x1="106" y1="26" x2="106" y2="186" stroke="#DFEDE6" strokeWidth="1.6" opacity=".5" />
          <line x1="26" y1="106" x2="186" y2="106" stroke="#DFEDE6" strokeWidth="1.6" opacity=".5" />
        </svg>
      </div>
      {caption ? (
        <div className="text-center font-kai text-[11px] tracking-[.36em] text-pine-50/60">{caption}</div>
      ) : null}
    </div>
  );
}
