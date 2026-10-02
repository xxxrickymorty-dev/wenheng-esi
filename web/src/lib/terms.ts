/* 界面核心词（票 04）：**一词一义**，出处 GLOSSARY.md。
   UI 文案引用这里，不写字面量；替换批次见票 08。 */

export const TERMS = {
  /** 动作：签单（不写 签发/钤印/审批/放行） */
  signAction: '签单',
  signActionFull: '复核并签单',
  /** 状态（由 lib/status.ts 的 APPROVAL_LABEL 承载，此处仅作词表登记） */
  signed: '已签发',
  unsigned: '未签发',
  signStale: '签名已失效',
  /** 红件 */
  redList: '红色件清单',
  marginNote: '页边朱批',
  manual: '待人工',
  /** 对勘 */
  collation: '对勘本',
  collationNotes: '校记',
  /** 校验（不写 断言/体检单） */
  validation: '数据校验',
  /** 模型基线 */
  recommend: 'V1 推荐',
  /** 期次 */
  period: '期次',
  /** 图书馆访客体验：短标签与页面品牌（导师明确禁用「数字图书馆」） */
  library: '陈列馆',
  libraryBrand: '云南大学图书馆',
} as const

export type TermKey = keyof typeof TERMS
