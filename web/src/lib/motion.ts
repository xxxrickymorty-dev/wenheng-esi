/* 动效层接线（taste P4，2026-10-16）——与 index.css 的 .m-* 层配对。
   预置隐藏只在 html.m-js（index.html 内联脚本先于渲染加上）时生效；
   本模块接线成功加 html.m-ready（2.5 秒兜底便不再强制展开），失败/无 IO 加 html.m-done
   ——任何情况内容都出得来（"脚本失败不藏内容"）。
   只动 transform / opacity；reduced-motion 在 CSS 里全降级。
   用法：静态块接线一次（App 换屏时重跑，元素级幂等）；会随数据不断新生的容器
   （如灵活报告栏内正文）在每次内容更新后对已有节点补接，已接过的不会重放。 */

let io: IntersectionObserver | null = null

function getIO(): IntersectionObserver | null {
  if (typeof IntersectionObserver === 'undefined') return null
  if (!io) {
    io = new IntersectionObserver((entries) => {
      for (const e of entries) {
        if (e.isIntersecting) {
          const el = e.target as HTMLElement
          el.classList.add('m-in')
          io!.unobserve(el)
          /* 出场后清场：入场是一次性的，不动元素原有过渡（如 .entry 的悬停描边）。
             1400ms 覆盖最慢的错峰（560ms 延迟＋500ms 时长）＋余量。 */
          window.setTimeout(() => {
            el.classList.remove('m-enter', 'm-in', 'm-left', 'm-right')
            el.style.transitionDelay = ''
          }, 1400)
        }
      }
    }, { rootMargin: '0px 0px -4% 0px', threshold: 0.04 })
  }
  return io
}

/** 给单个元素接线（幂等）。side＝入场方向（灵活报告两栏用）；delayMs＝错峰（仅首屏元素用）。 */
export function wireEnter(el: HTMLElement, opts: { delayMs?: number; side?: 'left' | 'right' } = {}) {
  const doc = document.documentElement
  try {
    const ob = getIO()
    if (!ob) { doc.classList.add('m-done'); return }
    if (el.dataset.mWired) return
    el.dataset.mWired = '1'
    el.classList.add('m-enter')
    if (opts.side) el.classList.add(opts.side === 'left' ? 'm-left' : 'm-right')
    if (opts.delayMs && el.getBoundingClientRect().top < (window.innerHeight || 900) * 0.92) {
      el.style.transitionDelay = `${opts.delayMs}ms`
    }
    ob.observe(el)
    doc.classList.add('m-ready')
  } catch {
    doc.classList.add('m-done')
  }
}

/** 给 scope 内匹配的元素按 DOM 顺序批量接线（step＝每级错峰毫秒）。 */
export function wireAll(scope: ParentNode | null, selector: string, step = 0) {
  if (!scope) return
  Array.from(scope.querySelectorAll<HTMLElement>(selector)).forEach((el, i) => {
    wireEnter(el, { delayMs: step ? Math.min(i, 8) * step : 0 })
  })
}
