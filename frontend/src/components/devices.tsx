/**
 * 四件签名器件 —— FlapDigits / Gauge / Stamp / Seal
 * 四件均属「绿·器」：青瓷绿为全站唯一主色，蓝已退场。
 * 牌缝／刻度／戳框／印框是器物本身的结构，不是装饰线。
 */
import { type ReactNode, useEffect, useState } from "react";

/* ── 动效：关键帧 + 降级（仅本文件内聚，不碰共享样式） ──────────
 * 手感＝铅字落进字盘，咔嗒。弹簧刚度 380 / 阻尼 14 ≈ 250ms 缓动。
 * 过冲跟着面积走：翻牌小件 10–20%；标尺／戳印大件 ≤1–2%（这里用 ease-out 不回弹）。
 * 印章/钤印落章是记忆点，允许 .5s，曲线 cubic-bezier(.22,.9,.28,1)（与 ws.css 的 sseal-land 一致）。
 */
function usePrefersReduced() {
  const [reduced, setReduced] = useState(
    typeof window !== "undefined" && window.matchMedia
      ? window.matchMedia("(prefers-reduced-motion: reduce)").matches
      : false,
  );
  useEffect(() => {
    if (typeof window === "undefined" || !window.matchMedia) return;
    const mq = window.matchMedia("(prefers-reduced-motion: reduce)");
    const onChange = () => setReduced(mq.matches);
    mq.addEventListener?.("change", onChange);
    return () => mq.removeEventListener?.("change", onChange);
  }, []);
  return reduced;
}

export function MotionStyles() {
  return (
    <style>{`
@keyframes wh-flap{0%{transform:rotateX(-92deg);opacity:0}55%{opacity:1}100%{transform:rotateX(0deg);opacity:1}}
@keyframes wh-stamp{0%{transform:translateY(-18px);opacity:0}100%{transform:translateY(0);opacity:1}}
@keyframes wh-seal{0%{transform:translateY(-8px);opacity:0}100%{transform:translateY(0);opacity:1}}
@keyframes wh-reveal{0%{opacity:0;transform:translateY(10px)}100%{opacity:1;transform:translateY(0)}}
.wh-flap{animation:wh-flap .25s cubic-bezier(.3,1.5,.5,1) both;transform-origin:center}
.wh-stamp{animation:wh-stamp .5s cubic-bezier(.22,.9,.28,1) both}
.wh-seal{animation:wh-seal .5s cubic-bezier(.22,.9,.28,1) both}
.wh-reveal{animation:wh-reveal .4s cubic-bezier(.22,.9,.28,1) both}
@media (prefers-reduced-motion: reduce){
  .wh-flap,.wh-stamp,.wh-seal,.wh-reveal,.wh-gauge,.wh-level,.wh-press{
    animation:none !important;transition:none !important
  }
}`}</style>
  );
}

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
      <div className="mb-[7px] font-kai text-[13px] tracking-[.36em] text-pine-50/80">{label}</div>
      <div className="flex gap-[5px]">
        {pieces.map((p, i) => {
          if (p.kind === "colon")
            return (
              <span
                key={i}
                className={`relative grid place-items-center bg-transparent font-mono text-pine-50/40 ${
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
              style={{ perspective: "240px" }}
              className={[
                "relative grid place-items-center bg-pine-400 font-mono font-bold tabular-nums",
                size === "lg" ? "h-[50px] w-[36px] text-[25px]" : "h-[38px] w-[27px] text-[18px]",
                "after:absolute after:left-0 after:right-0 after:top-1/2 after:h-[2px] after:bg-pine-300",
                p.tone === "gr" ? "text-pine-100" : p.tone === "rd" ? "text-[#E8917C]" : "text-pine-50",
              ].join(" ")}
            >
              {/* key 跟随数值：数值变化即重挂，触发翻牌；变化时牌面绕 2px 牌缝翻过去 */}
              <span
                key={`${i}-${p.v}`}
                className="wh-flap inline-block"
                style={{ animationDelay: `${Math.min(i, 12) * 38}ms` }}
              >
                {p.v}
              </span>
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
      : "bg-pine-400 border-pine-50/18";

  // 水面涨落：挂载时从 0 涨上来；water 变化时平滑过渡（涨/落都是水，不是开关）
  const reduced = usePrefersReduced();
  const [fill, setFill] = useState(reduced ? water : 0);
  useEffect(() => {
    const id = requestAnimationFrame(() => setFill(water));
    return () => cancelAnimationFrame(id);
  }, [water, reduced]);

  return (
    <div className={`border p-[18px_22px_20px] ${skin}`}>
      <div className="flex flex-wrap justify-between gap-[14px] font-kai text-[13px] tracking-[.32em] text-pine-50/80">
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
          className="wh-gauge absolute bottom-0 left-0 right-0 border-t-2 border-pine-100 bg-pine-200"
          style={{ height: `${fill}%`, transition: "height .5s cubic-bezier(.22,.9,.28,1)" }}
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
  const reduced = usePrefersReduced();
  const [w, setW] = useState(reduced ? pct : 0);
  useEffect(() => {
    const id = requestAnimationFrame(() => setW(pct));
    return () => cancelAnimationFrame(id);
  }, [pct, reduced]);

  return (
    <div className="flex min-w-[132px] items-center gap-[9px]">
      <div className="relative h-[7px] flex-1 bg-paper-100">
        <i
          className="wh-level absolute bottom-0 left-0 top-0 bg-pine-200"
          style={{ width: `${w}%`, transition: "width .45s cubic-bezier(.4,0,.2,1)" }}
        />
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
      {/* 落章：橡皮戳压落下来（旋转保留在外层，落章动在里层，不破坏倾斜与毛边滤镜） */}
      <div className="wh-stamp block h-full w-full">
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
        className={`border-b pb-[11px] font-kai text-[13px] tracking-[.36em] ${
          onGreen ? "border-pine-50/20 text-pine-50/80" : "border-paper-50 text-ink-100"
        }`}
      >
        {head}
      </div>
      <div className="mt-[18px] flex flex-wrap items-center justify-center gap-[18px]">{children}</div>
      <div
        className={`mt-[16px] font-kai text-[13px] tracking-[.32em] ${
          onGreen ? "text-pine-50/80" : "text-ink-100"
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
        {/* 压印：钤印压落纸面（倾斜保留在外层，压印动在里层，不破坏毛边滤镜） */}
        <div className="wh-seal block h-full w-full">
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
      </div>
      {caption ? (
        <div className="text-center font-kai text-[13px] tracking-[.36em] text-pine-50/80">{caption}</div>
      ) : null}
    </div>
  );
}
