/* 图表画布：进视口才初始化（一册 100+ 张，全量即初始化会卡）、随容器宽自适应、
   卸载时销毁。option 由调用方 useMemo 出——这里不做任何数值加工。 */

import { useEffect, useRef, useState } from 'react'
import * as echarts from 'echarts'
import type { EChartsOption } from 'echarts'

function useInView(ref: React.RefObject<HTMLDivElement | null>): boolean {
  const [inView, setInView] = useState(false)
  useEffect(() => {
    const el = ref.current
    if (!el || inView) return
    const io = new IntersectionObserver((es) => {
      if (es.some((e) => e.isIntersecting)) {
        setInView(true)
        io.disconnect()
      }
    }, { rootMargin: '200px' })
    io.observe(el)
    return () => io.disconnect()
  }, [ref, inView])
  return inView
}

export function ChartFigure({ option, height = 230, ariaLabel }: {
  option: EChartsOption
  height?: number
  ariaLabel: string
}) {
  const ref = useRef<HTMLDivElement>(null)
  const inView = useInView(ref)
  const [failed, setFailed] = useState(false)
  useEffect(() => {
    if (!inView || !ref.current || failed) return
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
  }, [inView, option, failed])
  return (
    <div ref={ref} className="gal-chart" style={{ height }}
         role="img" aria-label={ariaLabel}>
      {!inView && <span className="gal-chart-hint">图表在进入视野时绘制</span>}
      {failed && <span className="gal-chart-hint">这张图暂时画不出来，可看原图</span>}
    </div>
  )
}
