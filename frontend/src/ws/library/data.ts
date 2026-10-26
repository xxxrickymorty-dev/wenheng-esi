import { HttpError, req, type Me } from '../api'
import type {
  GlossaryEntry, ShelfBook, ShelfBookFull, ShelfLoadResult, ShelfBookPreview, ShelfStats,
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

function readFullScript(source: string): ShelfBookFull[] | null {
  const script = source.trim()
  if (!script.startsWith(DATA_PREFIX) || !script.endsWith(';')) return null

  let payload: unknown
  try {
    payload = JSON.parse(script.slice(DATA_PREFIX.length, -1)) as unknown
  } catch {
    return null
  }
  if (!isRecord(payload) || !Array.isArray(payload.books)) return null

  // 服务器组装的形状，字段在渲染处按需读；这里只筛掉非对象项。
  const books: ShelfBookFull[] = []
  for (const value of payload.books) {
    if (isRecord(value)) books.push(value as ShelfBookFull)
  }
  return books
}

/** 先确认当前账号；登录后一律读馆藏预览投影——管理员从工作区进陈列馆也看同一份
    （管理员完整数据在 `shelf/data.js`，暂未接前端）。 */
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

  // 两种角色（管理员/操作员）都再取服务器组装的完整数据——陈列馆全内容；
  // 完整数据取不到时退回预览三件套（如实回落，不假装有内容）。
  try {
    const fullResponse = await fetch('/app/shelf/data.js', {
      credentials: 'same-origin',
      headers: { Accept: 'application/javascript' },
      cache: 'no-store',
      signal,
    })
    if (fullResponse.ok && !fullResponse.redirected) {
      const fullBooks = readFullScript(await fullResponse.text())
      if (fullBooks) {
        const byPeriod = new Map<string, ShelfBookFull>()
        for (const full of fullBooks) {
          if (typeof full.period === 'string' && full.period) byPeriod.set(full.period, full)
        }
        return {
          kind: 'full',
          books: books.map((book) => {
            const full = book.period ? byPeriod.get(book.period) : undefined
            return full ? { ...book, full } : book
          }),
          ...(stats ? { stats } : {}),
        }
      }
    }
  } catch (error) {
    if (signal.aborted) throw error
  }
  return { kind: 'preview', books, ...(stats ? { stats } : {}) }
}
