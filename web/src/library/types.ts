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

/** 陈列馆首页事实条：服务端随预览数据盖章给出（取自最新一期流水线产物）。
    字段都可选——服务端缺哪项就省哪项；页面拿到 undefined 时自行回落。 */
export type ShelfStats = {
  /** 在监测的学科数 */
  monitored?: number
  /** 已进 ESI 全球前 1% 的学科数 */
  topOnePercent?: number
  /** 上榜论文数（热点∪高被引） */
  highlyCited?: number
  /** 数字出处，如「202609 期流水线产物（table2 与 overview_facts）」 */
  source?: string
}

export type ShelfLoadResult =
  /** 完整数据拿到（两种角色同份，2026-10-11 起） */
  | { kind: 'full'; books: ShelfBook[]; stats?: ShelfStats }
  /** 只有封面/目录/名词解释基础投影（完整数据取不到时的如实回落） */
  | { kind: 'preview'; books: ShelfBook[]; stats?: ShelfStats }
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

/** 报告正文块（2026-10-11 票 05：陈列馆册页「报告正文」用；服务端从 docx 提取）。 */
export type ReportCell = { text: string; imgs?: string[]; span?: number }
export type ReportBlock =
  | { t: 'h1'; text: string }
  | { t: 'h2'; text: string }
  | { t: 'p'; text: string }
  | { t: 'img'; rid: string; w_cm?: number; h_cm?: number }
  | { t: 'tbl'; rows: ReportCell[][] }

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
  /** 报告正文（h1/h2/p/img/tbl 块序列；缺件期次为空数组） */
  report_text?: ReportBlock[]
}

/** 一本书：预览三件套 +（管理员）完整数据。 */
export type ShelfBook = ShelfBookPreview & { period?: string; full?: ShelfBookFull }
