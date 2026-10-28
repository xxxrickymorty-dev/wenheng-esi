/* 图表画布：进入视口附近才初始化（一册 100+ 张，全量即初始化会卡）、
   随容器宽自适应、卸载时销毁。option 由调用方 useMemo 出——这里不做任何数值加工。
   判定双保险：挂载时先按几何位置算一次（嵌入式/离屏渲染里 IntersectionObserver
   可能永远不出帧），差着再用 IO 兜底。 */

import { useEffect, useRef, useState } from 'react'
import * as echarts from 'echarts'
import type { EChartsOption } from 'echarts'

function useNearViewport(ref: React.RefObject<HTMLDivElement | null>): boolean {
  const [near, setNear] = useState(false)
  useEffect(() => {
    const el = ref.current
    if (!el || near) return
    const r = el.getBoundingClientRect()
    if (r.top < window.innerHeight + 300 && r.bottom > -300) {
      setNear(true)
      return
    }
    const io = new IntersectionObserver((es) => {
      if (es.some((e) => e.isIntersecting)) {
        setNear(true)
        io.disconnect()
      }
    }, { rootMargin: '300px' })
    io.observe(el)
    return () => io.disconnect()
  }, [ref, near])
  return near
}

export function ChartFigure({ option, height = 230, ariaLabel, fallbackSrc }: {
  option: EChartsOption
  height?: number
  ariaLabel: string
  /** 画不出来时露的原图（审核台用：正文里的图不许开天窗） */
  fallbackSrc?: string
}) {
  const ref = useRef<HTMLDivElement>(null)
  const near = useNearViewport(ref)
  const [failed, setFailed] = useState(false)
  useEffect(() => {
    if (!near || !ref.current || failed) return
    let chart: echarts.ECharts | null = null
    try {
      chart = echarts.init(ref.current)
      chart.setOption(option)
    } catch {
      setFailed(true)                       // 画不出来就露占位，不让整册塌掉
      return
    }
    const ro = new ResizeObserver(() => chart?.resize())
    ro.observe(ref.current)
    return () => { ro.disconnect(); chart?.dispose() }
  }, [near, option, failed])
  return (
    <div ref={ref} className="gal-chart" style={{ height }}
         role="img" aria-label={ariaLabel}>
      {!near && <span className="gal-chart-hint">图表在进入视野时绘制</span>}
      {failed && (fallbackSrc
        ? <img src={fallbackSrc} alt={ariaLabel} />
        : <span className="gal-chart-hint">这张图暂时画不出来，可看原图</span>)}
    </div>
  )
}
