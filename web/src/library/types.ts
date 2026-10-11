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
  /** 完整数据拿到（两种角色同份，2026-10-11 起） */
  | { kind: 'full'; books: ShelfBook[] }
  /** 只有封面/目录/名词解释基础投影（完整数据取不到时的如实回落） */
  | { kind: 'preview'; books: ShelfBook[] }
  | { kind: 'login' }
  | { kind: 'forbidden' }
  | { kind: 'unavailable' }
  | { kind: 'invalid-data' }

/** 预测一行（被引 / 排名维度共用形状）。 */
export type ForecastRow = {
  en: string
  model: string
  mape: string
  prox: string
  t1: string
  t2: string
  t3: string
}

/** 学科大表一行（table2.csv 的展示投影）。 */
export type ShelfTableRow = {
  en: string
  cn: string
  papers?: number | null
  cites?: number | null
  cnci?: number | null
  top?: number | null
  thr?: number | null
  gap?: number | null
  prox?: string
  rank?: string
}

/** 服务器组装的完整书（管理员阅读「全内容」用；形状按需读，不做深校验）。 */
export type ShelfBookFull = {
  period?: string
  no?: number
  label?: string
  coverage?: string
  prev_label?: string
  rank_intl_now?: number | null
  rank_intl_delta?: number | null
  rank_cn_uni_now?: number | null
  top_papers_now?: number | null
  top_papers_delta?: number | null
  n_disc_1pct?: number | null
  n_assert_pass?: number | null
  n_assert_total?: number | null
  top3?: [string, number][]
  best_permille?: { discipline: string; prox_pct?: number | null; prox_prev_pct?: number | null } | null
  not_entered?: { discipline: string; prox_pct?: number | null; chg?: number | null }[]
  table?: ShelfTableRow[]
  forecast?: { rows?: ForecastRow[]; rows2?: ForecastRow[]; impl?: string; window?: string }
}

/** 一本书：预览三件套 +（管理员）完整数据。 */
export type ShelfBook = ShelfBookPreview & { period?: string; full?: ShelfBookFull }
