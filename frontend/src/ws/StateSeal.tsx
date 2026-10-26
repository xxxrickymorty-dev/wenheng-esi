/* 状态印（2026-10-25 rick 过审）：一状态一印面。
   墨绿干印＝机器做完的活（并入台账/已出稿）；虚框空印＝等人来定的局面（待核验/未签发）；
   朱砂满印＝签单落章；金印＝签后改稿失效。
   印面与 mockups/状态印章-谱（静态稿 20261025）逐字一致；毛边滤镜在 SealInkDefs（全站挂一次）。
   印泥是资产色，不随蓝绿主题变——和真实的章一样，蘸什么泥就是什么色。 */

import type { ReactElement } from 'react'

export type SealState = 'merged' | 'drafted' | 'unsigned' | 'signed' | 'stale'

type Face = {
  label: string
  svg: ReactElement
}

const SERIF = "'Noto Serif SC Variable','Noto Serif SC','Source Han Serif SC','Songti SC',SimSun,serif"

/** 界格式印面：外框＋内细框＋两行方阵（三字印末字居中）；ground＝朱砂满印（红底纸字） */
function FrameFace({ ink, dashed, ground, chars }: {
  ink: string
  dashed?: boolean
  ground?: boolean
  chars: [string, string, string] | [string, string, string, string]
}) {
  const filter = ground ? 'url(#ink-rough-heavy)' : 'url(#ink-rough)'
  const text = ground ? '#F5F3EC' : ink
  const frame = ground
    ? <rect x="10" y="10" width="200" height="200" fill={ink} />
    : <rect x="10" y="10" width="200" height="200" fill="none" stroke={ink}
        strokeWidth={dashed ? 3.4 : 5} strokeDasharray={dashed ? '14 9' : undefined} />
  const inner = ground
    ? <rect x="22" y="22" width="176" height="176" fill="none" stroke="#F5F3EC" strokeWidth="2.6" />
    : <rect x="23" y="23" width="174" height="174" fill="none" stroke={ink} strokeWidth={dashed ? 1.2 : 1.6} />
  const pos: Array<[number, number]> = chars.length === 4
    ? [[64, 94], [156, 94], [64, 180], [156, 180]]
    : [[64, 94], [156, 94], [110, 180]]
  return (
    <svg viewBox="0 0 220 220">
      <g filter={filter}>
        {frame}
        {inner}
        <g fontFamily={SERIF} fontWeight={700} fontSize={56} textAnchor="middle" fill={text}>
          {pos.map(([x, y], i) => <text key={i} x={x} y={y}>{chars[i]}</text>)}
        </g>
      </g>
    </svg>
  )
}

const FACES: Record<SealState, Face> = {
  merged: { label: '已并入台账印', svg: <FrameFace ink="#264A35" chars={['并', '入', '台', '账']} /> },
  drafted: { label: '已出稿印', svg: <FrameFace ink="#264A35" chars={['已', '出', '稿']} /> },
  unsigned: { label: '未签发印', svg: <FrameFace ink="#A82F22" dashed chars={['未', '签', '发']} /> },
  signed: { label: '已签发印', svg: <FrameFace ink="#A82F22" ground chars={['已', '签', '发']} /> },
  stale: { label: '签发失效印', svg: <FrameFace ink="#8A6B2E" chars={['签', '发', '失', '效']} /> },
}

/** 状态印：纸卡垫底＋印面（印感＝SVG 毛边＋微倾，零圆角、不加投影）。
    size 为卡边长（px，动态值走内联）；tilt 交替微倾避免一排印同角度；
    landing＝落章动效（签单成功那一刻放一次）。 */
export function StateSeal({ state, size = 96, tilt, landing = false, className }: {
  state: SealState
  size?: number
  tilt?: 'a' | 'b'
  landing?: boolean
  className?: string
}) {
  const f = FACES[state]
  const cls = ['sseal', tilt === 'a' ? 'sseal-a' : '', tilt === 'b' ? 'sseal-b' : '',
    landing ? 'landing' : '', className ?? ''].filter(Boolean).join(' ')
  return (
    <span className={cls} style={{ width: size, height: size }} role="img" aria-label={f.label}>
      {f.svg}
    </span>
  )
}

/** 印泥毛边滤镜——全站只需挂一次（App 里 Sprite 旁边）；印面经 url(#ink-rough) 引用。 */
export function SealInkDefs() {
  return (
    <svg className="sseal-defs" aria-hidden="true"><defs>
      <filter id="ink-rough" x="-6%" y="-6%" width="112%" height="112%">
        <feTurbulence type="fractalNoise" baseFrequency="1.6" numOctaves="2" seed="4" />
        <feDisplacementMap in="SourceGraphic" scale="2.4" />
      </filter>
      <filter id="ink-rough-heavy" x="-8%" y="-8%" width="116%" height="116%">
        <feTurbulence type="fractalNoise" baseFrequency="0.9" numOctaves="3" seed="11" />
        <feDisplacementMap in="SourceGraphic" scale="3.2" />
      </filter>
    </defs></svg>
  )
}
