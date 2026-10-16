/* 数据里的英语目录名/分组键 → 界面中文标签（taste P2，2026-10-16）。
   为什么在前端做：产物目录名与分组键是**数据事实**（英文 slug），界面上屏前译成中文——
   不改产物、不改接口。slug 规则与 `src/charts.py` 的 `_slug` 一致：删掉所有非字母数字字符。 */

/** ESI 学科英文名 → 中文名（口径同 `src/parse_ledger.py` 的 DISCIPLINES_CN）。 */
const DISCIPLINES: [string, string][] = [
  ['Agricultural Sciences', '农业科学'],
  ['Biology & Biochemistry', '生物学与生物化学'],
  ['Chemistry', '化学'],
  ['Clinical Medicine', '临床医学'],
  ['Computer Science', '计算机科学'],
  ['Economics & Business', '经济与商业'],
  ['Engineering', '工程学'],
  ['Environment/Ecology', '环境生态学'],
  ['Geosciences', '地球科学'],
  ['Immunology', '免疫学'],
  ['Materials Science', '材料科学'],
  ['Mathematics', '数学'],
  ['Microbiology', '微生物学'],
  ['Molecular Biology & Genetics', '分子生物学与遗传学'],
  ['Multidisciplinary', '多学科'],
  ['Neuroscience & Behavior', '神经系统科学与行为学'],
  ['Pharmacology & Toxicology', '药理学与毒理学'],
  ['Physics', '物理学'],
  ['Plant & Animal Science', '植物与动物学'],
  ['Psychiatry/Psychology', '精神病学与心理学'],
  ['Social Sciences, general', '社会科学'],
  ['Space Science', '空间科学'],
]

/** 与 `src/charts.py` 的 `_slug` 同一条规则（图册目录名就是它压出来的）。 */
export function disciplineSlug(en: string): string {
  return en.replace(/[^A-Za-z0-9]+/g, '')
}

/** 图册分组（`out/<期次>/charts/` 的子目录名）→ 界面标签；`_overview`＝总览；未知原样。 */
const CHART_GROUP_CN: Record<string, string> = Object.fromEntries([
  ['_overview', '总览'],
  ...DISCIPLINES.map(([en, cn]): [string, string] => [disciplineSlug(en), `${cn}（${en}）`]),
])

export function chartGroupLabel(group: string): string {
  return CHART_GROUP_CN[group] ?? group
}

/** 对勘本分组（`red_slots` 的槽位段键）→ 界面标签；名字与 `server/collation.py` SECTIONS 对齐。 */
const COLLATION_SECTION_CN: Record<string, string> = {
  cover: '封面',
  overview: '概述正文',
  trend: '发展趋势',
  situation: '学科态势',
  bigtable: '大表与表题',
  dcharts: '学科图表槽位',
  top: '顶尖论文',
  forecast: '预测回测',
  province: '云南省对比',
  charts: '概览图槽位',
  other: '其他槽位',
}

export function collationSectionLabel(section: string): string {
  return COLLATION_SECTION_CN[section] ?? section
}
