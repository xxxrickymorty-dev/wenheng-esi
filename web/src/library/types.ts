export type TocEntry = {
  title: string
  /** 报告目录里标注的页码；名词解释一行没有页码。 */
  page?: string
}

export type GlossaryEntry = {
  term: string
  definition: string
}

/** 访客页面只显示封面、目录和名词解释。 */
export type ShelfBookPreview = {
  cover: [string, string, string, string]
  toc: TocEntry[]
  glossary: GlossaryEntry[]
}

export type ShelfLoadResult =
  | { kind: 'admin' }
  | { kind: 'guest'; books: ShelfBookPreview[] }
  | { kind: 'login' }
  | { kind: 'forbidden' }
  | { kind: 'unavailable' }
  | { kind: 'invalid-data' }
