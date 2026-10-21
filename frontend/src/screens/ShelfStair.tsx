/**
 * 陈列馆 · 书阶（实验）
 * ------------------------------------------------------------------
 * 一级一册：五册从 202601 起，正好是最近发布的五期。
 * 页面本身滚动（不是内层套一个滚轮区），所以鼠标滚轮、触控板、
 * 右侧刻度、键盘 ↑↓ 走的是同一份进度。
 *
 * 书＝书脊（正视）+ 顶面（斜切）；不做真三维——离线、投影都稳。
 */
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { StairParticles, STEP } from "./StairParticles";
import "../stair.css";

type Book = { period: string; no: number; label: string };

/** 固定五期 01–09；楼梯从 202601 起。 */
const BOOKS: Book[] = [
  { period: "202601", no: 35, label: "2026 年 第 1 期" },
  { period: "202603", no: 36, label: "2026 年 第 2 期" },
  { period: "202605", no: 37, label: "2026 年 第 3 期" },
  { period: "202607", no: 38, label: "2026 年 第 4 期" },
  { period: "202609", no: 39, label: "2026 年 第 5 期" },
];

const LAST = BOOKS[BOOKS.length - 1];

export function ShelfStair() {
  const root = useRef<HTMLDivElement>(null);
  const [p, setP] = useState(0);
  const [opened, setOpened] = useState(false);
  const [fit, setFit] = useState(1);
  const reduce = useMemo(
    () => typeof matchMedia !== "undefined" && matchMedia("(prefers-reduced-motion: reduce)").matches,
    [],
  );

  const stops = BOOKS.length + 1; // 五级 + 门
  const stop = Math.min(stops - 1, Math.round(p * (stops - 1)));
  const atTop = p > 0.9;
  const current = BOOKS[Math.min(BOOKS.length - 1, stop)];

  const progressOf = useCallback(() => {
    const el = root.current;
    if (!el) return 0;
    const top = el.offsetTop;
    const span = el.offsetHeight - window.innerHeight;
    if (span <= 0) return 0;
    return Math.min(1, Math.max(0, (window.scrollY - top) / span));
  }, []);

  const jump = useCallback(
    (ratio: number) => {
      const el = root.current;
      if (!el) return;
      const top = el.offsetTop + ratio * (el.offsetHeight - window.innerHeight);
      window.scrollTo({ top, behavior: reduce ? "auto" : "smooth" });
    },
    [reduce],
  );

  useEffect(() => {
    const onScroll = () => setP(progressOf());
    const onKey = (e: KeyboardEvent) => {
      const step = 1 / (stops - 1);
      if (e.key === "ArrowDown") { e.preventDefault(); jump(Math.min(1, p + step)); }
      if (e.key === "ArrowUp") { e.preventDefault(); jump(Math.max(0, p - step)); }
      if (e.key === "Home") { e.preventDefault(); jump(0); }
      if (e.key === "End") { e.preventDefault(); jump(1); }
    };
    const onResize = () => {
      onScroll();
      const rail = window.innerWidth <= 860 ? 64 : 208;
      setFit(Math.min(1, (window.innerWidth - rail - 40) / 880));
    };
    window.addEventListener("scroll", onScroll, { passive: true });
    window.addEventListener("resize", onResize);
    window.addEventListener("keydown", onKey);
    onResize();
    return () => {
      window.removeEventListener("scroll", onScroll);
      window.removeEventListener("resize", onResize);
      window.removeEventListener("keydown", onKey);
    };
  }, [p, jump, stops, progressOf]);

  /* 相机：以门为原点推近——越往上越近，门始终在梯顶那一角 */
  const s = fit * (reduce ? 1 : 1 + p * 0.18);

  return (
    <div className="stair-root" ref={root}>
      <div className="stair-stage">
        <div className="stair-head">
          <span className="stair-kik">陈 列 馆 · 馆 藏 A 区 01</span>
          <h1>一册一册，循流而上。</h1>
        </div>

        <div
          className="stair-world"
          style={{ transform: `scale(${s})` }}
        >
          <StairParticles
            books={BOOKS.length}
            active={stop < BOOKS.length ? stop : -1}
          />
          {BOOKS.map((b, i) => (
            <button
              key={b.period}
              type="button"
              className={`stair-label${i === stop ? " is-on" : ""}`}
              style={{
                left: STEP.padX + i * STEP.w + 6,
                top: STEP.padY - i * STEP.rise - 30,
              }}
              onClick={() => jump(i / (stops - 1))}
              aria-label={`第 ${i + 1} 册，总第 ${b.no} 期，${b.label}`}
            >
              <b>{b.period}</b>
              <i>总第 {b.no} 期</i>
            </button>
          ))}

          <button
            type="button"
            className={`stair-label door${atTop ? " is-on" : ""}`}
            style={{
              left: STEP.padX + BOOKS.length * STEP.w - 150,
              top: STEP.padY - BOOKS.length * STEP.rise - 46,
            }}
            onClick={() => (atTop ? setOpened(true) : jump(1))}
            aria-label={atTop ? "推门进阅览室" : "走到梯顶"}
          >
            <b>阅览室</b>
            <i>推门 →</i>
          </button>
        </div>

        <p className="stair-note">滚动上行 · 点书脊跳级 · 右侧刻度可点也可拖</p>
      </div>

      {/* 右栏：跟着屏幕，不随页面滚走 */}
      <aside className="stair-rail" aria-label="第几级">
        <div className="rail-head">
          <span>{stop === stops - 1 ? "梯 顶" : `第 ${stop + 1} 级`}</span>
          <b>{current?.period}</b>
        </div>

        <div className="rail-ticks">
          <button
            type="button"
            className={`tick top${atTop ? " is-on" : ""}`}
            onClick={() => jump(1)}
            aria-label="到梯顶"
          >
            <i />
            <span>顶</span>
          </button>
          {[...BOOKS].reverse().map((b, r) => {
            const i = BOOKS.length - 1 - r;
            return (
              <button
                key={b.period}
                type="button"
                className={`tick${i === stop ? " is-on" : ""}${i < stop ? " is-past" : ""}`}
                onClick={() => jump(i / (stops - 1))}
                aria-label={`到第 ${i + 1} 级 ${b.period}`}
                aria-pressed={i === stop}
              >
                <i />
                <span>{b.no}</span>
              </button>
            );
          })}
        </div>

        <div className="rail-foot">
          <button type="button" className="rail-cta" onClick={() => jump(1)}>
            到 顶 →
          </button>
        </div>
      </aside>

      {opened && (
        <div className="stair-veil" role="dialog" aria-label="阅览室">
          <div className="veil-card">
            <span className="stair-kik">阅 览 室 · 第 {LAST.no} 期</span>
            <h2>{LAST.label}</h2>
            <p>
              门后是这本刊的封面、目录与名词解释。<br />
              正文数值不出馆——要看全文，请进工作区。
            </p>
            <div className="veil-acts">
              <a className="veil-primary" href="/app/shelf/" onClick={(e) => e.preventDefault()}>
                翻开这一册
              </a>
              <button type="button" onClick={() => setOpened(false)}>退 回 书 阶</button>
            </div>
            <p className="veil-note">实验稿：这里将来直接接现有翻书器，不做第二套阅读器。</p>
          </div>
        </div>
      )}
    </div>
  );
}
