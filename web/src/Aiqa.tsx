/* AI 问数工作台（?view=aiqa）。
   问一句 → 后端把问题变成白名单查询（SQLite 只读）→ 人话回答 + ECharts 图。
   数字一律来自后端；本组件只做展示与图型切换，不做任何换算。 */

import { useCallback, useEffect, useRef, useState } from 'react'
import * as echarts from 'echarts'
import { req, type ApiError } from './api'

type AiqaMeta = {
  period: string
  built_at: string
  n_facts: number
  disciplines: { discipline: string; discipline_cn: string }[]
  metrics: { metric: string; metric_cn: string; better: string }[]
  periods: string[]
}

type ChartData = {
  kind: string
  title: string
  categories: (string | number)[]
  series: { name: string; data: (number | null)[] }[]
}

type AskResult = {
  question: string
  plan: { specs: Record<string, unknown>[]; origin: string; note: string }
  answer: string
  chart: { kind: string; title: string }
  chart_data: ChartData
  record_id: number
  elapsed_ms: number
}

/** 本地开发用问题示例（馆员视角的人话） */
const SAMPLES = [
  '化学的总被引趋势',
  '202607 论文数前 5 名',
  '物理学最新国际排名',
  '整体概况',
  '化学和数学的顶尖论文对比',
]

export function Aiqa() {
  const [meta, setMeta] = useState<AiqaMeta | null>(null)
  const [metaErr, setMetaErr] = useState<ApiError | null>(null)
  const [question, setQuestion] = useState('')
  const [busy, setBusy] = useState(false)
  const [result, setResult] = useState<AskResult | null>(null)
  const [err, setErr] = useState<ApiError | null>(null)
  const [chartKind, setChartKind] = useState<'auto' | 'bar' | 'pie' | 'line'>('auto')
  const chartRef = useRef<HTMLDivElement | null>(null)
  const instRef = useRef<echarts.ECharts | null>(null)

  useEffect(() => {
    req<AiqaMeta>('/api/aiqa/meta')
      .then((m) => { setMeta(m); setMetaErr(null) })
      .catch((e: ApiError) => setMetaErr(e))
  }, [])

  const ask = useCallback(async (q: string) => {
    const text = q.trim()
    if (!text || busy) return
    setBusy(true)
    setErr(null)
    try {
      const r = await req<AskResult>('/api/aiqa/ask', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ question: text }),
      })
      setResult(r)
      setChartKind('auto')
    } catch (e) {
      setErr(e as ApiError)
      setResult(null)
    } finally {
      setBusy(false)
    }
  }, [busy])

  /* 图型：人选了就用人的；没选就按后端建议 */
  const effectiveKind = (): string => {
    if (!result) return ''
    if (chartKind !== 'auto') return chartKind
    return result.chart.kind === 'table' ? 'table' : result.chart.kind
  }

  /* ECharts 渲染（主题色取自站内令牌；无数据不画） */
  useEffect(() => {
    if (!result || !chartRef.current) return
    const kind = effectiveKind()
    if (kind === 'table' || !result.chart_data.series.length) return
    const cd = result.chart_data
    const styles = getComputedStyle(document.documentElement)
    const ink = styles.getPropertyValue('--ink').trim() || '#15222B'
    const accent = styles.getPropertyValue('--zhu').trim() || '#26483B'
    const line = styles.getPropertyValue('--line').trim() || '#D6D0C0'
    const inst = instRef.current ?? echarts.init(chartRef.current)
    instRef.current = inst
    if (kind === 'pie') {
      inst.setOption({
        textStyle: { color: ink },
        tooltip: { trigger: 'item' },
        legend: { bottom: 0, textStyle: { color: ink } },
        series: [{
          type: 'pie', radius: ['35%', '68%'],
          data: cd.categories.map((c, i) => ({ name: String(c), value: cd.series[0].data[i] })),
          label: { color: ink },
        }],
      }, true)
    } else if (kind === 'line') {
      inst.setOption({
        textStyle: { color: ink },
        tooltip: { trigger: 'axis' },
        grid: { left: 70, right: 24, top: 30, bottom: 40 },
        xAxis: { type: 'category', data: cd.categories,
                 axisLine: { lineStyle: { color: line } },
                 axisLabel: { color: ink } },
        yAxis: { type: 'value', splitLine: { lineStyle: { color: line } },
                 axisLabel: { color: ink } },
        series: cd.series.map((s) => ({
          type: 'line', name: s.name, data: s.data,
          itemStyle: { color: accent }, lineStyle: { color: accent, width: 2 },
          symbolSize: 5,
        })),
      }, true)
    } else {
      inst.setOption({
        textStyle: { color: ink },
        tooltip: { trigger: 'axis' },
        grid: { left: 70, right: 24, top: 30, bottom: 60 },
        xAxis: { type: 'category', data: cd.categories,
                 axisLine: { lineStyle: { color: line } },
                 axisLabel: { color: ink, rotate: cd.categories.length > 8 ? 30 : 0 } },
        yAxis: { type: 'value', splitLine: { lineStyle: { color: line } },
                 axisLabel: { color: ink } },
        series: cd.series.map((s) => ({
          type: 'bar', name: s.name, data: s.data,
          itemStyle: { color: accent },
        })),
      }, true)
    }
    const onResize = () => inst.resize()
    window.addEventListener('resize', onResize)
    return () => window.removeEventListener('resize', onResize)
  }, [result, chartKind])  // eslint-disable-line react-hooks/exhaustive-deps

  useEffect(() => () => { instRef.current?.dispose(); instRef.current = null }, [])

  const kind = result ? effectiveKind() : ''
  const showChart = result && kind !== 'table' && result.chart_data.series.length > 0
  const isLine = kind === 'line'

  return (
    <section className="aiqa">
      <div className="aiqa-head">
        <div>
          <h2 className="sec-title">AI 问数</h2>
          <p className="hint">
            用一句话查台账数据。数字只来自数据库，可回溯；数据库
            {meta ? <>当前覆盖 <b>{meta.period}</b> 期、{meta.n_facts.toLocaleString()} 条数据</> : '尚未就绪'}。
          </p>
        </div>
        {meta && (
          <div className="aiqa-facts hint-num">
            <span>{meta.period}</span>
            <span>{meta.n_facts.toLocaleString()} 条</span>
            <span>{meta.disciplines.length} 学科</span>
          </div>
        )}
      </div>

      {metaErr && (
        <div className="banner bad mt-0">
          <span className="ico">!</span>
          <span><b className="title">{metaErr.error || '问数数据库还没建好'}</b>
            <ul><li>{metaErr.hint || '请在服务器上构建数据库后再试。'}</li></ul>
          </span>
        </div>
      )}

      <form className="aiqa-ask" onSubmit={(e) => { e.preventDefault(); void ask(question) }}>
        <input
          value={question}
          onChange={(e) => setQuestion(e.target.value)}
          placeholder="例如：化学的总被引趋势、202607 论文数前 5 名"
          aria-label="问题"
          disabled={busy || !!metaErr}
        />
        <button type="submit" disabled={busy || !question.trim() || !!metaErr}>
          {busy ? '查询中…' : '提问'}
        </button>
      </form>

      <div className="aiqa-samples" aria-label="示例问题">
        {SAMPLES.map((s) => (
          <button key={s} type="button" className="aiqa-chip"
                  disabled={busy}
                  onClick={() => { setQuestion(s); void ask(s) }}>
            {s}
          </button>
        ))}
      </div>

      {err && (
        <div className="banner bad">
          <span className="ico">!</span>
          <span><b className="title">{err.error || '查询失败'}</b>
            {err.hint && <ul><li>{err.hint}</li></ul>}
          </span>
        </div>
      )}

      {result && (
        <div className="aiqa-result">
          <div className="aiqa-answer">
            <span className="aiqa-q">问：{result.question}</span>
            {result.answer.split('\n').map((line, i) => <p key={i}>{line}</p>)}
            <p className="aiqa-meta hint">
              耗时 {result.elapsed_ms} ms · 查询方式 {result.plan.origin === 'model' ? '模型规划' : '规则规划'}
              {result.record_id >= 0 ? ` · 留痕 #${result.record_id}` : ''}
            </p>
          </div>

          {showChart && (
            <div className="aiqa-chart">
              <div className="aiqa-chart-head">
                <b>{result.chart_data.title || '图表'}</b>
                <span className="skin-switch" role="group" aria-label="切换图型">
                  <button type="button" aria-pressed={chartKind === 'auto'}
                          onClick={() => setChartKind('auto')}>建议</button>
                  <button type="button" aria-pressed={chartKind === 'bar'}
                          onClick={() => setChartKind('bar')}>柱状</button>
                  {!isLine && (
                    <button type="button" aria-pressed={chartKind === 'pie'}
                            onClick={() => setChartKind('pie')}>饼图</button>
                  )}
                  <button type="button" aria-pressed={chartKind === 'line'}
                          onClick={() => setChartKind('line')}>折线</button>
                </span>
              </div>
              <div ref={chartRef} className="aiqa-canvas" aria-label="数据图表" />
            </div>
          )}

          {kind === 'table' && result.chart_data.series.length === 0 && (
            <div className="aiqa-table-note hint">这轮结果是文字/单值，没有可画的图。</div>
          )}
        </div>
      )}

      {!result && !err && !busy && (
        <div className="pending-box">
          输入问题，或点上面的示例试一下。
        </div>
      )}
    </section>
  )
}
