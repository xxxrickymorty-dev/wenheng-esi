/* taste P2 单测：内部键 → 中文映射（图册分组 / 对勘本分组）。
   守卫：① 常用键都有中文；② 未知键原样返回不吞；③ 映射结果不出现 `_` 前缀键与无空格英文。 */

import { describe, expect, it } from 'vitest'
import { chartGroupLabel, collationSectionLabel, disciplineCn, disciplineSlug } from './labels'

describe('图册分组映射 chartGroupLabel', () => {
  it('已知分组出中文（含英文原名括号位）', () => {
    expect(chartGroupLabel('_overview')).toBe('总览')
    expect(chartGroupLabel('AgriculturalSciences')).toBe('农业科学（Agricultural Sciences）')
    expect(chartGroupLabel('SocialSciencesgeneral')).toBe('社会科学（Social Sciences, general）')
  })

  it('未知分组原样返回（不假装认识）', () => {
    expect(chartGroupLabel('SomeUnknownGroup')).toBe('SomeUnknownGroup')
  })

  it('映射结果不出现 `_` 前缀键与无空格英文名', () => {
    for (const g of ['_overview', 'AgriculturalSciences', 'BiologyBiochemistry', 'Physics',
                     'ClinicalMedicine', 'EnvironmentEcology', 'MolecularBiologyGenetics']) {
      const label = chartGroupLabel(g)
      expect(label.startsWith('_'), g).toBe(false)
      // 无空格英文名（如 AgriculturalSciences）不得留在标签里；带空格的英文原名允许
      expect(/[A-Za-z][a-z]+[A-Z]/.test(label.replace(/（[^）]*）/, '')), g).toBe(false)
    }
  })

  it('slug 规则与 src/charts.py 的 _slug 一致', () => {
    expect(disciplineSlug('Biology & Biochemistry')).toBe('BiologyBiochemistry')
    expect(disciplineSlug('Social Sciences, general')).toBe('SocialSciencesgeneral')
    expect(disciplineSlug('Environment/Ecology')).toBe('EnvironmentEcology')
  })
})

describe('学科名映射 disciplineCn', () => {
  it('图册写法与他校简报写法都认得（两套表拼写不同）', () => {
    expect(disciplineCn('Environment/Ecology')).toBe('环境生态学')
    expect(disciplineCn('Environment Ecology')).toBe('环境生态学')   // panel() 的写法
    expect(disciplineCn('Social Sciences, General')).toBe('社会科学')
    expect(disciplineCn('Psychiatry Psychology')).toBe('精神病学与心理学')
  })

  it('表里没有的原样返回（不猜）', () => {
    expect(disciplineCn('Astrology')).toBe('Astrology')
  })
})

describe('对勘本分组映射 collationSectionLabel', () => {
  it('已知分组出中文（与 server/collation.py SECTIONS 对齐）', () => {
    expect(collationSectionLabel('cover')).toBe('封面')
    expect(collationSectionLabel('bigtable')).toBe('大表与表题')
    expect(collationSectionLabel('dcharts')).toBe('学科图表槽位')
  })

  it('未知分组原样返回', () => {
    expect(collationSectionLabel('mystery')).toBe('mystery')
  })
})
