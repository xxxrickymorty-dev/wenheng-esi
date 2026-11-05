/* 统一图标：一套内联 SVG（24 视框 / 1.7 描边 / 圆头）。
   用 <use> 引用，改一处全局一致——图标字体与外链都不引（断网也要能用）。 */

const S = { fill: 'none', stroke: 'currentColor', strokeWidth: 1.7, strokeLinecap: 'round' as const, strokeLinejoin: 'round' as const }

function Sprite() {
  return (
    <svg width="0" height="0" className="abs" aria-hidden="true">
      <symbol id="i-check" viewBox="0 0 24 24"><path d="M20 6 9 17l-5-5" {...S} /></symbol>
      <symbol id="i-slash" viewBox="0 0 24 24"><path d="M6.5 18.5 17.5 5.5" {...S} /></symbol>
      <symbol id="i-play" viewBox="0 0 24 24"><path d="M7 4.5 19 12 7 19.5z" {...S} /></symbol>
      <symbol id="i-window" viewBox="0 0 24 24"><rect x="3.5" y="5" width="17" height="14" rx="1" {...S} /><path d="M3.5 9h17" {...S} /></symbol>
      <symbol id="i-stop" viewBox="0 0 24 24"><rect x="6" y="6" width="12" height="12" rx="1" {...S} /></symbol>
      <symbol id="i-alert" viewBox="0 0 24 24">
        <path d="M12 4 2.8 20h18.4z" {...S} />
        <path d="M12 10v4.5M12 17.4v.1" {...S} strokeWidth={1.9} />
      </symbol>
      <symbol id="i-clock" viewBox="0 0 24 24">
        <circle cx="12" cy="12" r="8.2" {...S} />
        <path d="M12 7.5V12l3 2" {...S} />
      </symbol>
      <symbol id="i-refresh" viewBox="0 0 24 24">
        <path d="M20 12a8 8 0 1 1-2.4-5.7M20 4v5h-5" {...S} />
      </symbol>
      <symbol id="i-doc" viewBox="0 0 24 24">
        <path d="M14 3H7a1 1 0 0 0-1 1v16a1 1 0 0 0 1 1h10a1 1 0 0 0 1-1V7zm0 0v4h4M9 13h6M9 17h6" {...S} />
      </symbol>
      <symbol id="i-list" viewBox="0 0 24 24">
        <path d="M8 6h12M8 12h12M8 18h12M4 6h.01M4 12h.01M4 18h.01" {...S} strokeWidth={1.9} />
      </symbol>
      <symbol id="i-seal" viewBox="0 0 24 24">
        <path d="M12 3 4 6v6c0 4.5 3.4 7.7 8 9 4.6-1.3 8-4.5 8-9V6z" {...S} />
        <path d="m8.5 12 2.5 2.5 4.5-4.5" {...S} />
      </symbol>
      <symbol id="i-chart" viewBox="0 0 24 24">
        <path d="M4 20V10m5 10V5m5 15v-7m5 7V8" {...S} strokeWidth={1.9} />
      </symbol>
      <symbol id="i-arrow" viewBox="0 0 24 24"><path d="m9 5 7 7-7 7" {...S} /></symbol>
      <symbol id="i-chev-left" viewBox="0 0 24 24"><path d="m15 5-7 7 7 7" {...S} /></symbol>
      <symbol id="i-chev-right" viewBox="0 0 24 24"><path d="m9 5 7 7-7 7" {...S} /></symbol>
      <symbol id="i-book" viewBox="0 0 24 24">
        <path d="M4 5.5A2.5 2.5 0 0 1 6.5 3H19v16H6.5A2.5 2.5 0 0 0 4 21zM4 5.5v15" {...S} />
      </symbol>
      <symbol id="i-trend" viewBox="0 0 24 24">
        <path d="M4 17.5 9.5 11l3.5 3L20 6" {...S} />
        <path d="M15.5 6H20v4.5" {...S} />
      </symbol>
      <symbol id="i-search" viewBox="0 0 24 24">
        <circle cx="11" cy="11" r="6.5" {...S} />
        <path d="m16 16 4.5 4.5" {...S} />
      </symbol>
      <symbol id="i-download" viewBox="0 0 24 24">
        <path d="M12 4v10.5m-4.5-4L12 15l4.5-4.5M5 19.5h14" {...S} />
      </symbol>
      <symbol id="i-chat" viewBox="0 0 24 24">
        <path d="M21 11.5a8.38 8.38 0 0 1-.9 3.8 8.5 8.5 0 0 1-7.6 4.7 8.38 8.38 0 0 1-3.8-.9L3 21l1.9-5.7a8.38 8.38 0 0 1-.9-3.8 8.5 8.5 0 0 1 4.7-7.6 8.38 8.38 0 0 1 3.8-.9h.5a8.48 8.48 0 0 1 8 8z" {...S} />
      </symbol>
      <symbol id="i-ledger" viewBox="0 0 24 24">
        <path d="M5 4h14v16H5zM5 9h14M5 14h14M5 19h14" {...S} />
      </symbol>
      <symbol id="i-archive" viewBox="0 0 24 24">
        <path d="M4 8h16v12H4zM3 3h18v5H3zM10 12h4" {...S} />
      </symbol>
      <symbol id="i-plus" viewBox="0 0 24 24"><path d="M12 5v14M5 12h14" {...S} /></symbol>
      <symbol id="i-gear" viewBox="0 0 24 24">
        <circle cx="12" cy="12" r="3" {...S} />
        <path d="M19.4 15a1.65 1.65 0 0 0 .33 1.82l.06.06a2 2 0 1 1-2.83 2.83l-.06-.06a1.65 1.65 0 0 0-1.82-.33 1.65 1.65 0 0 0-1 1.51V21a2 2 0 1 1-4 0v-.09A1.65 1.65 0 0 0 9 19.4a1.65 1.65 0 0 0-1.82.33l-.06.06a2 2 0 1 1-2.83-2.83l.06-.06a1.65 1.65 0 0 0 .33-1.82 1.65 1.65 0 0 0-1.51-1H3a2 2 0 1 1 0-4h.09A1.65 1.65 0 0 0 4.6 9a1.65 1.65 0 0 0-.33-1.82l-.06-.06a2 2 0 1 1 2.83-2.83l.06.06a1.65 1.65 0 0 0 1.82.33H9a1.65 1.65 0 0 0 1-1.51V3a2 2 0 1 1 4 0v.09a1.65 1.65 0 0 0 1 1.51 1.65 1.65 0 0 0 1.82-.33l.06-.06a2 2 0 1 1 2.83 2.83l-.06.06a1.65 1.65 0 0 0-.33 1.82V9a1.65 1.65 0 0 0 1.51 1H21a2 2 0 1 1 0 4h-.09a1.65 1.65 0 0 0-1.51 1z" {...S} />
      </symbol>
    </svg>
  )
}

export function Icon({ name, size = 20, className }: { name: string; size?: number; className?: string }) {
  return (
    <svg width={size} height={size} className={className} aria-hidden="true">
      <use href={`#i-${name}`} />
    </svg>
  )
}

export { Sprite }
