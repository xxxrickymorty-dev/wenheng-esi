/* 预测选模的两处纯逻辑（2026-10-16 从 App.tsx 抽出；预测台/生成台共用）：
   - 选择形状的等价比较（是不是同一套选择；只看 meta 里的路线 × 学科，未改＝空）；
   - 「报告还是旧的」判定与提示文案：已保存的选择 vs 上次出稿实际用的选择
     （**比值，不比时间**——时间格式/时区都无涉；没有出稿快照＝无法核实，不猜）。
   2026-11-05：选择里多了「进报告的两科」（顺序＝报告 1/2 号位），
   两科换了同样算「报告还是旧的」——不比的话，换了学科却提示「已生效」。 */

import type { ForecastChoiceApplied, ForecastChoiceEntry, ForecastMeta } from '../api-forecast'

export function sameForecastChoice(
  left: Record<string, Record<string, string>>,
  right: Record<string, Record<string, string>>,
  meta: ForecastMeta,
): boolean {
  return meta.routes.every((route) => meta.subjects.every((subject) =>
    (left[route.value]?.[subject] ?? '') === (right[route.value]?.[subject] ?? '')))
}

/** 两科同一对且同序（顺序决定报告 1/2 号位，所以不能当集合比） */
export function sameSubjects(left: string[], right: string[]): boolean {
  return left.length === right.length && left.every((s, i) => s === right[i])
}

/** 没保存过（空）＝用后端给的缺省两科（接近度前二）；保存过就照保存的 */
export function resolveSubjects(subjects: string[], meta: ForecastMeta | null): string[] {
  return subjects.length ? subjects : (meta?.default_subjects ?? [])
}

/** 保存用的规范化：只留改过的学科（空值不落盘） */
export function savedForecastChoice(
  choice: Record<string, Record<string, string>>,
  meta: ForecastMeta,
): Record<string, Record<string, string>> {
  const result: Record<string, Record<string, string>> = {}
  for (const route of meta.routes) {
    const bySubject: Record<string, string> = {}
    for (const subject of meta.subjects) {
      const model = choice[route.value]?.[subject]
      if (model) bySubject[subject] = model
    }
    result[route.value] = bySubject
  }
  return result
}

/** 路线短名：'路线1 · 总被引 / ESI前1%被引阈值' → '总被引'（预测台/生成台同源） */
export function shortRouteLabel(label: string): string {
  const head = label.split('/')[0] ?? label
  const parts = head.split('·')
  return (parts[parts.length - 1] ?? head).trim() || label
}

/** 「改选还没重出」：已保存的选择 ≠ 上次出稿实际用的选择。
    没有出稿快照（applied=null，如没出过稿或老期次）＝无法核实 → 不算旧（不显示提示）。
    老期次的快照没有 subjects 字段（老记录）＝不比这两科，只比模型。 */
export function forecastAppliedStale(
  entry: ForecastChoiceEntry | null,
  meta: ForecastMeta | null,
): boolean {
  if (!meta || !entry?.loaded || !entry.applied) return false
  if (!sameForecastChoice(entry.saved, entry.applied.choice, meta)) return true
  const appliedSubjects = entry.applied.subjects ?? []
  if (!appliedSubjects.length) return false          // 老快照没记两科：无法核实，不比
  return !sameSubjects(resolveSubjects(entry.savedSubjects, meta), appliedSubjects)
}

/** 提示条里列的改动：逐路线逐学科比值，人话给「学科 → 模型」；两科变了单列一条。 */
export function forecastAppliedDiffs(
  entry: ForecastChoiceEntry,
  meta: ForecastMeta,
): string[] {
  const applied: ForecastChoiceApplied['choice'] = entry.applied?.choice ?? {}
  const diffs: string[] = []
  for (const route of meta.routes) {
    const short = shortRouteLabel(route.label)
    for (const subject of meta.subjects) {
      const saved = entry.saved[route.value]?.[subject] ?? ''
      const used = applied[route.value]?.[subject] ?? ''
      if (saved !== used) diffs.push(`${short}：${subject} → ${saved || '恢复 V1 推荐'}`)
    }
  }
  const appliedSubjects = entry.applied?.subjects ?? []
  if (appliedSubjects.length
      && !sameSubjects(resolveSubjects(entry.savedSubjects, meta), appliedSubjects)) {
    diffs.push(`报告两科：${appliedSubjects.join('、')} → `
      + `${resolveSubjects(entry.savedSubjects, meta).join('、') || '缺省两科'}`)
  }
  return diffs
}
