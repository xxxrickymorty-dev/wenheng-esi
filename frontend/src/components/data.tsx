/**
 * 数据件 —— Tag / Button / DataTable / DataPanel
 * 状态词只两套：任务（进行中/已完成/未开始）＋ 签发（未签发/已签发/签发已失效）。
 */
import type { ReactNode } from "react";

/* ── Tag 状态签 ─────────────────────────────────── */
export type TagTone = "g" | "b" | "r";

export function Tag({ tone = "g", children }: { tone?: TagTone; children: ReactNode }) {
  const map = {
    /* 实色底 + 实色字：半透明底叠在不同父背景上会算出不确定的对比度，标签不该碰运气 */
    g: "bg-pine-50 text-[#143D31]",
    b: "bg-pine-50 text-[#143D31]",
    r: "bg-[#F4DDD7] text-[#8B2A1E]",
  } as const;
  return (
    <span
      className={`inline-block whitespace-nowrap px-[10px] py-[3px] font-kai text-[11.5px] tracking-[.18em] ${map[tone]}`}
    >
      {children}
    </span>
  );
}

/* ── Button / Link ──────────────────────────────── */
export function Button({
  variant = "solid",
  children,
  onClick,
}: {
  variant?: "solid" | "paper";
  children: ReactNode;
  onClick?: () => void;
}) {
  const cls =
    variant === "paper"
      ? "bg-pine-50 text-pine-400 hover:bg-white border border-pine-200 active:bg-pine-100"
      : "bg-pine-200 text-[#08201A] hover:bg-[#3A9069] border-none active:bg-pine-300";
  return (
    <button
      onClick={onClick}
      style={{ transition: "background-color 120ms linear" }}
      className={`${cls} wh-press rounded-none px-[28px] py-[13px] font-serif text-[15px] font-bold tracking-[.14em]`}
    >
      {children}
    </button>
  );
}

export function GhostLink({ children }: { children: ReactNode }) {
  return (
    <a
      href="#"
      style={{ transition: "color 120ms linear, box-shadow 120ms linear" }}
      className="wh-press pb-[3px] font-kai text-[13px] tracking-[.18em] text-pine-50 shadow-[inset_0_-1px_0_var(--color-pine-50)] hover:text-white hover:shadow-[inset_0_-1px_0_white] active:text-white active:shadow-[inset_0_-1px_0_white]"
    >
      {children}
    </a>
  );
}

/* ── DataTable 数据表 ───────────────────────────── */
export type Col<T> = {
  key: string;
  label: string;
  width?: string;
  render: (row: T) => ReactNode;
};

export function DataTable<T>({
  cols,
  rows,
  rowKey,
  isNow,
}: {
  cols: Col<T>[];
  rows: T[];
  rowKey: (row: T) => string;
  isNow?: (row: T) => boolean;
}) {
  return (
    <table className="w-full border-collapse">
      <thead>
        <tr>
          {cols.map((c) => (
            <th
              key={c.key}
              style={c.width ? { width: c.width } : undefined}
              className="border-b border-ink-300 pb-[10px] pr-[14px] pt-[13px] text-left font-kai text-[11.5px] font-normal tracking-[.32em] text-ink-100 last:pr-0"
            >
              {c.label}
            </th>
          ))}
        </tr>
      </thead>
      <tbody>
        {rows.map((row) => (
          <tr key={rowKey(row)} className={isNow?.(row) ? "bg-pine-200/10" : ""}>
            {cols.map((c) => (
              <td
                key={c.key}
                className="border-b border-paper-100 py-[12px] pr-[14px] font-serif text-[15px] tracking-[.03em] last:pr-0 [&:last-child]:border-b-0"
              >
                {c.render(row)}
              </td>
            ))}
          </tr>
        ))}
      </tbody>
    </table>
  );
}

/* ── DataPanel 数据面板 ─────────────────────────── */
export function DataPanel({ pairs }: { pairs: [string, ReactNode][] }) {
  return (
    <div>
      <div className="border-b-2 border-ink-300 pb-[11px] font-kai text-[11.5px] tracking-[.42em] text-ink-100">
        本 期 數 據
      </div>
      <dl className="mt-[6px] grid grid-cols-3 gap-x-[32px] max-[1040px]:grid-cols-2">
        {pairs.map(([k, v]) => (
          <div
            key={k}
            className="flex justify-between gap-[12px] border-b border-paper-100 py-[10px] font-kai text-[12.5px]"
          >
            <dt className="whitespace-nowrap tracking-[.16em] text-ink-100">{k}</dt>
            <dd className="text-right [&>b]:font-serif [&>b]:text-[16px] [&>b]:tracking-[.04em]">{v}</dd>
          </div>
        ))}
      </dl>
    </div>
  );
}

/* ── SmallWays 布局工具 ─────────────────────────── */
export function Wrap({ children }: { children: ReactNode }) {
  return <div className="mx-auto max-w-[1280px] px-[30px]">{children}</div>;
}

export function Grid2({ children }: { children: ReactNode }) {
  return (
    <div className="grid grid-cols-[minmax(0,1.15fr)_minmax(0,.85fr)] items-start gap-[48px] max-[1040px]:grid-cols-1">
      {children}
    </div>
  );
}
