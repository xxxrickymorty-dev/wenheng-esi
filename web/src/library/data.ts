import { HttpError, req, type Me } from '../api'
import type { GlossaryEntry, ShelfBookPreview, ShelfLoadResult, TocEntry } from './types'

const DATA_PREFIX = 'window.WH_DATA = '

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null && !Array.isArray(value)
}

function isRoleResponse(value: unknown): value is Pick<Me, 'role'> {
  return isRecord(value) && (value.role === 'admin' || value.role === 'guest')
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

function readBook(value: unknown): ShelfBookPreview | null {
  if (!isRecord(value)) return null
  const cover = readStrings(value.cover)
  const toc = readToc(value.toc)
  const glossary = readGlossary(value.glossary)
  if (!cover || cover.length !== 4 || cover[0].trim() !== '' || cover[1] !== '学科信息参考'
      || !cover[2].trim() || !cover[3].trim() || !toc || !glossary) return null

  // 只把封面、目录和名词解释交给页面；其他内容不会进入页面数据。
  return { cover: [cover[0], cover[1], cover[2], cover[3]], toc, glossary }
}

function readPreviewScript(source: string): ShelfBookPreview[] | null {
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

  const books = readPreviewScript(script)
  return books ? { kind: 'guest', books } : { kind: 'invalid-data' }
}
