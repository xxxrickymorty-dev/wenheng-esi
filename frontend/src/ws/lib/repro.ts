/* 票 05（口径 A）· 出好了的**三件套**：从任务产物清单里挑出实产的三件。
   口径：报告初稿（Word）→ 对勘本 → 红件清单（Markdown），顺序固定；缺谁不凑；
   非这三件的产物（诊断报告/大表/预测回测…）不进这一排。
   （五稿写的「对照差异报告」是回测件，常规跑不产出——不进这一排。）

   纯函数：输入后端产物清单（GET /api/jobs/{id}/artifacts 的形状），输出链接排；
   前端不猜、不换算，只做挑选与排序。 */

export type JobArtifact = {
  key: string
  label: string
  name: string
  size?: number | null
  url: string
  primary?: boolean
}

export type TrioLink = { key: string; label: string; href: string; from: string }

/** 三件套的固定顺序与界面短名（长名放 title 上，不挤按钮）。 */
export const TRIO: readonly { key: string; label: string }[] = [
  { key: 'report', label: '报告初稿' },
  { key: 'collation', label: '对勘本' },
  { key: 'red_list', label: '红色件清单' },
]

export function trioLinks(artifacts: JobArtifact[]): TrioLink[] {
  const byKey = new Map(artifacts.map((a) => [a.key, a]))
  const out: TrioLink[] = []
  for (const t of TRIO) {
    const a = byKey.get(t.key)
    if (a && a.url) out.push({ key: t.key, label: t.label, href: a.url, from: a.label })
  }
  return out
}
