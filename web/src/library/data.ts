import { HttpError, getPeriods, req, type Me } from '../api'
import type {
  GlossaryEntry, ShelfBook, ShelfLoadResult, ShelfBookPreview, ShelfStats,
  TocEntry,
} from './types'

const DATA_PREFIX = 'window.WH_DATA = '

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null && !Array.isArray(value)
}

function isRoleResponse(value: unknown): value is Pick<Me, 'role'> {
  return isRecord(value) && (value.role === 'admin' || value.role === 'operator')
}

function readStrings(value: unknown): string[] | null {
  if (!Array.isArray(value) || !value.every((item) => typeof item === 'string')) return null
  return value
}

function readToc(value: unknown): TocEntry[] | null {
  if (!Array.isArray(value)) return null
  const entries: TocEntry[] = []
  for (const item of value) {
    if (!isRecord(item) || typeof item.title !== 'string') return null
    if (item.page !== undefined && typeof item.page !== 'string') return null
    const page = typeof item.page === 'string' && item.page.trim() ? item.page : undefined
    entries.push(page ? { title: item.title, page } : { title: item.title })
  }
  return entries
}

function readGlossary(value: unknown): GlossaryEntry[] | null {
  if (!Array.isArray(value)) return null
  const entries: GlossaryEntry[] = []
  for (const item of value) {
    if (!isRecord(item) || typeof item.term !== 'string' || typeof item.definition !== 'string') return null
    entries.push({ term: item.term, definition: item.definition })
  }
  return entries
}

function readBook(value: unknown): ShelfBook | null {
  if (!isRecord(value)) return null
  const cover = readStrings(value.cover)
  const toc = readToc(value.toc)
  const glossary = readGlossary(value.glossary)
  if (!cover || cover.length !== 4 || cover[0].trim() !== '' || cover[1] !== '学科信息参考'
      || !cover[2].trim() || !cover[3].trim() || !toc || !glossary) return null

  // 只把封面、目录和名词解释交给页面；期次号用于与完整数据按期次配对。
  const period = typeof value.period === 'string' && value.period ? value.period : undefined
  return { cover: [cover[0], cover[1], cover[2], cover[3]], toc, glossary,
           ...(period ? { period } : {}) }
}

/** 事实条盖章：一项一项验形状，缺了照给剩下的；但给了却形状不对就整条不要
    （宁可没有事实条，不可给错数）。整体不是对象、或一项数都没有，也按没有处理。 */
function readStats(value: unknown): ShelfStats | undefined {
  if (!isRecord(value)) return undefined
  const stats: ShelfStats = {}
  let present = false
  for (const key of [
    'monitored', 'topOnePercent', 'highlyCited', 'docSlots', 'selfChecks', 'pendingManual',
  ] as const) {
    const raw = value[key]
    if (raw === undefined) continue
    if (typeof raw !== 'number' || !Number.isFinite(raw)) return undefined
    stats[key] = raw
    present = true
  }
  const rawSource = value.source
  if (rawSource !== undefined) {
    if (typeof rawSource !== 'string' || !rawSource.trim()) return undefined
    stats.source = rawSource
    present = true
  }
  return present ? stats : undefined
}

function readPreviewScript(source: string): { books: ShelfBook[]; stats?: ShelfStats } | null {
  const script = source.trim()
  if (!script.startsWith(DATA_PREFIX) || !script.endsWith(';')) return null

  let payload: unknown
  try {
    payload = JSON.parse(script.slice(DATA_PREFIX.length, -1)) as unknown
  } catch {
    return null
  }
  if (!isRecord(payload) || payload.preview !== true || !Array.isArray(payload.books)) return null

  const books: ShelfBookPreview[] = []
  for (const value of payload.books) {
    const book = readBook(value)
    if (!book) return null
    books.push(book)
  }
  // 事实条是可选附件：形状不对就当没有，不影响书本身。
  return { books, stats: readStats(payload.stats) }
}

/** 先确认当前账号；登录后一律读馆藏预览投影——管理员从工作区进陈列馆也看同一份。
    2026-10-26：**不再预取 `shelf/data.js`**（109 KB，页面从不消费 `book.full`；
    `LibraryHome` 只用 period / cover[2] / stats）。此前它是首屏的串行前置请求，
    且 `cache:'no-store'` 每次刷新重下。实测屏蔽后页面照常渲染（对照实验见
    `wenheng/tmp/shelf_audit/exp_datajs.py`）。要恢复「管理员看全内容」，应先让页面
    真的用上 `full`，再按需（点开某册时）取，而不是整包预取。 */
export async function loadShelfPreviews(signal: AbortSignal): Promise<ShelfLoadResult> {
  let me: unknown
  try {
    me = await req<unknown>('/api/me', { signal })
  } catch (error) {
    if (signal.aborted) throw error
    if (error instanceof HttpError && error.status === 401) return { kind: 'login' }
    return { kind: 'unavailable' }
  }

  if (!isRoleResponse(me)) return { kind: 'unavailable' }

  /* 排期表与馆藏预览并行取：排期只用来算「末位待装帧」那几格，拿不到就不画，
     绝不能反过来拖慢首屏。762 B，与 preview.js 同时发出。 */
  const periodsPromise = getPeriods().catch(() => [])

  let response: Response
  try {
    response = await fetch('/app/shelf/preview.js', {
      credentials: 'same-origin',
      headers: { Accept: 'application/javascript' },
      cache: 'no-store',
      signal,
    })
  } catch (error) {
    if (signal.aborted) throw error
    return { kind: 'unavailable' }
  }

  if (response.status === 401 || (response.redirected && new URL(response.url).pathname === '/login')) {
    return { kind: 'login' }
  }
  if (response.status === 403) return { kind: 'forbidden' }
  if (!response.ok) return { kind: 'unavailable' }

  let script: string
  try {
    script = await response.text()
  } catch (error) {
    if (signal.aborted) throw error
    return { kind: 'unavailable' }
  }

  const preview = readPreviewScript(script)
  if (!preview) return { kind: 'invalid-data' }
  const { books, stats } = preview

  /* 末位「待装帧」（rick 2026-10-26 裁「方案 C」）：
     排期里已经建出来、但还没出过稿的期次（generated === false），且书架上确实没有它，
     就在末位补一个空书位。**只认排期表，不从上一期推算月份**——推出来的期次是编的。
     排期拿不到 → 一格空位都不画，宁少不假。 */
  const have = new Set(books.map((b) => b.period).filter((p): p is string => Boolean(p)))
  const pendingPeriods = (await periodsPromise)
    .filter((p) => p.generated === false && !have.has(p.period))
    .map((p) => p.period)

  return { kind: 'preview', books, ...(stats ? { stats } : {}),
           ...(pendingPeriods.length ? { pendingPeriods } : {}) }
}
