/* 分析台（工作区 4）——灵活报告查看 / 润色（证据面）。
   票 07（2026-10-10）：「问文衡」对话框已并入对话前门（一个前门、两意图）——
   这里不再放输入框与问答；灵活报告仍在此查看、润色、对照规则稿。
   生成台 / 取数台 / 审核台 / 运行档案 / 陈列馆不动。 */

import { Flexible } from './Flexible'

export function Analysis({ period, canEdit }: { period: string | null; canEdit: boolean }) {
  return <Flexible period={period} canEdit={canEdit} />
}
