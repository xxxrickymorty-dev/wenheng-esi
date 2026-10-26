/* 陈列馆 · 产线全景（回放态）——rick 2026-10-26 定：可视化工作流放到书架下面，
   「一期一册，是这么来的」四站图文讲完，真产线就在下面。
   只做回放（live 恒 false）：实时运行态在工作区的可视化工作流屏，陈列馆保持成品面气质。
   期次不跟工作区顶栏（本页没有顶栏）——书架五册 chips 自选，默认最新已出稿的一册。 */

import { useEffect, useState } from 'react'
import { Panorama } from '../Panorama'
import { getPeriodDetail, getPeriods, type Period, type PeriodDetail } from '../api'

type LibraryPanoProps = {
  /** 书架上的五册（与书架同一份 books，新→旧） */
  books: { period?: string }[]
}

export default function LibraryPano({ books }: LibraryPanoProps) {
  const chips = books.map((b) => b.period ?? '').filter(Boolean)
  const [period, setPeriod] = useState<string | null>(null)
  const [periods, setPeriods] = useState<Period[]>([])
  const [periodsErr, setPeriodsErr] = useState<string | null>(null)
  const [detail, setDetail] = useState<PeriodDetail | null>(null)

  useEffect(() => {
    let alive = true
    getPeriods()
      .then((ps) => {
        if (!alive) return
        setPeriods(ps)
        /* 默认册：书架里最新已出稿的一期——没出过稿的册没有产线可回放 */
        const pick = ps.find((p) => chips.includes(p.period) && p.generated) ?? ps[0] ?? null
        if (pick) setPeriod((cur) => cur ?? pick.period)
      })
      .catch(() => { if (alive) setPeriodsErr('期次列表没读到——登录后再来看，真值需要登录身份。') })
    return () => { alive = false }
    // chips 来自书架静态五册，不进依赖
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  useEffect(() => {
    if (!period) return
    let alive = true
    getPeriodDetail(period)
      .then((d) => { if (alive) setDetail(d) })
      .catch(() => { if (alive) setDetail(null) })
    return () => { alive = false }
  }, [period])

  const status = periods.find((p) => p.period === period)?.status ?? 'unsigned'

  return (
    <div className="lib-pano">
      <div className="lib-pano-head">
        <b className="lib-pano-title">产线全景 · 这一册的来历</b>
        <p className="lib-pano-deck">
          回放态：只讲已经发生的事——取数 · 并入 · 产线 · 质检 · 签发；
          任务实时运行在工作区的可视化工作流屏。
        </p>
        {chips.length > 0 && (
          <div className="lib-pano-chips" role="group" aria-label="选择要回放的册">
            {chips.map((p) => (
              <button key={p} type="button"
                      className={p === period ? 'is-on' : ''}
                      aria-pressed={p === period}
                      onClick={() => setPeriod(p)}>
                {p}
              </button>
            ))}
          </div>
        )}
        {periodsErr && <p className="lib-pano-hint">{periodsErr}</p>}
      </div>
      {period && (
        <Panorama period={period} periods={periods} detail={detail}
                  approvalStatus={status} live={false}
                  periodSwitchNote="期次用上方册签切换。" />
      )}
    </div>
  )
}
