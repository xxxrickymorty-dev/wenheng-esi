/* 报告外观四轴（2026-11-05）——这一份是「唯一真相」。
   馆员在设置里调的：报告模板 / 系统皮肤 / 报告皮肤 / 字体，全部从这里来。
   面板选项、色值、字族、存本机、挂到页面都集中在此，别处不再各写一份。

   四条轴的偏好都存进浏览器本机（localStorage），不发给后端、不影响别人；
   只有「报告皮肤」和「字体」「模板」会随生成请求带过去（后端要照着出报告）。
   系统皮肤纯前端，永远不下发。 */

/* ── 四轴的取值类型 ── */
export type TemplateId = 'A' | 'B' | 'C' | 'D' | 'E'
export type SkinId =
  | 'huize' | 'daiqing' | 'zhusha' | 'tenghuang' | 'piaolv' | 'wulan'
  | 'mohui' | 'qingshan' | 'taohua' | 'hetang' | 'qiushan' | 'yebo'
export type FontId = 'song' | 'hei' | 'kai' | 'fang' | 'li' | 'xing'

export type SkinGroup = '正色' | '节令' | '夜色'

/* ── 选项表：皮肤 ── */
export interface SkinOption {
  id: SkinId
  name: string
  group: SkinGroup
  /** 主色（报告纸主色、系统主壳强调色） */
  accent: string
  /** 次色 */
  accent2: string
  /** 浅染色块（卡片底） */
  tint: string
  /** 纸色（报告纸面） */
  paper: string
  /** 墨色（报告字色） */
  ink: string
  /** 主壳深底（顶栏／左壳） */
  chrome: string
  /** 主壳上的浅字（标题、导航） */
  light: string
  /** 金线色 */
  gold: string
  /** 印色（印章） */
  seal: string
}

export const SKINS: SkinOption[] = [
  { id: 'huize', name: '会泽绿', group: '正色',
    accent: '#143729', accent2: '#276B4C', tint: '#E8F1ED', paper: '#F5F3EC', ink: '#15222B',
    chrome: '#143729', light: '#F5F3EC', gold: '#B08E48', seal: '#8B1E1E' },
  { id: 'daiqing', name: '黛青', group: '正色',
    accent: '#2F5D62', accent2: '#447C7A', tint: '#E6EFED', paper: '#F5F3EC', ink: '#22261F',
    chrome: '#24494D', light: '#F5F3EC', gold: '#B08E48', seal: '#8B1E1E' },
  { id: 'zhusha', name: '朱砂', group: '正色',
    accent: '#8B1E1E', accent2: '#B73A2C', tint: '#F6E7D7', paper: '#F7F2E8', ink: '#2A1E1A',
    chrome: '#741919', light: '#F7F2E8', gold: '#B08E48', seal: '#8B1E1E' },
  { id: 'tenghuang', name: '藤黄', group: '正色',
    accent: '#C28C1A', accent2: '#D4A72C', tint: '#FBF3D7', paper: '#FAF5E6', ink: '#2E2718',
    chrome: '#6B5012', light: '#FAF5E6', gold: '#B08E48', seal: '#8B1E1E' },
  { id: 'piaolv', name: '缥绿', group: '正色',
    accent: '#5E8E7E', accent2: '#7DAF9F', tint: '#E9F2EF', paper: '#F4F6EE', ink: '#1F2A22',
    chrome: '#3C6155', light: '#F4F6EE', gold: '#B08E48', seal: '#8B1E1E' },
  { id: 'wulan', name: '雾蓝', group: '正色',
    accent: '#4A6B8A', accent2: '#6E8CA8', tint: '#E6EDF3', paper: '#F4F6F8', ink: '#1C2530',
    chrome: '#35506C', light: '#F4F6F8', gold: '#B08E48', seal: '#8B1E1E' },
  { id: 'mohui', name: '墨灰', group: '正色',
    accent: '#3C3C3F', accent2: '#666668', tint: '#EDEDEA', paper: '#F3F1EA', ink: '#1A1A1A',
    chrome: '#2E2E31', light: '#F3F1EA', gold: '#B08E48', seal: '#8B1E1E' },
  { id: 'qingshan', name: '青绿山水', group: '节令',
    accent: '#4E7E8C', accent2: '#6E8F6A', tint: '#E6EDEA', paper: '#F5F0E6', ink: '#2E3E42',
    chrome: '#375E69', light: '#F5F0E6', gold: '#B08E48', seal: '#8B1E1E' },
  { id: 'taohua', name: '桃花春水', group: '节令',
    accent: '#D6A5AB', accent2: '#A9C5C2', tint: '#F7EDEF', paper: '#F7F3EC', ink: '#4A4142',
    chrome: '#6B4A4D', light: '#F7F3EC', gold: '#B08E48', seal: '#8B1E1E' },
  { id: 'hetang', name: '荷塘清夏', group: '节令',
    accent: '#7E9A7D', accent2: '#A9C8C7', tint: '#E8F0EB', paper: '#F2F0EA', ink: '#2B3A31',
    chrome: '#4E6550', light: '#F2F0EA', gold: '#B08E48', seal: '#8B1E1E' },
  { id: 'qiushan', name: '秋山设色', group: '节令',
    accent: '#A56A43', accent2: '#7B4A36', tint: '#F2E6D6', paper: '#EAD9BF', ink: '#38332E',
    chrome: '#6B432A', light: '#EAD9BF', gold: '#B08E48', seal: '#8B1E1E' },
  { id: 'yebo', name: '夜泊清辉', group: '夜色',
    accent: '#C9A961', accent2: '#8FA3B0', tint: '#2A3138', paper: '#20262B', ink: '#ECE8DF',
    chrome: '#161C21', light: '#ECE8DF', gold: '#C9A961', seal: '#C0503F' },
]

/** 按「正色 / 节令 / 夜色」分组的皮肤，面板照此分栏。 */
export const SKIN_GROUPS: { group: SkinGroup; items: SkinOption[] }[] = [
  { group: '正色', items: SKINS.filter((s) => s.group === '正色') },
  { group: '节令', items: SKINS.filter((s) => s.group === '节令') },
  { group: '夜色', items: SKINS.filter((s) => s.group === '夜色') },
]

/* ── 选项表：字体（六套「文衡字体」，系统与报告同吃一套）── */
export interface FontOption {
  id: FontId
  name: string
  /** 标题字族栈（本地字体，断网也能看） */
  title: string
  /** 正文字族栈 */
  body: string
  /** 楷/仿宋/隶/行楷略放大，让笔画不挤 */
  sizeAdj: string
}

export const FONTS: FontOption[] = [
  { id: 'song', name: '会泽宋',
    title: '"Noto Serif SC","Songti SC",SimSun,serif',
    body: '"Noto Serif SC","Songti SC",SimSun,serif', sizeAdj: '0px' },
  { id: 'hei', name: '现代黑',
    title: '"Microsoft YaHei","PingFang SC",SimHei,system-ui',
    body: '"Microsoft YaHei","PingFang SC",SimHei,system-ui', sizeAdj: '0px' },
  { id: 'kai', name: '滇楷',
    title: 'KaiTi,"Kaiti SC","STKaiti",var(--f-song)',
    body: 'KaiTi,"Kaiti SC","STKaiti",var(--f-song)', sizeAdj: '.8px' },
  { id: 'fang', name: '公文仿宋',
    title: 'FangSong,"STFangsong",SimFang,var(--f-song)',
    body: 'FangSong,"STFangsong",SimFang,var(--f-song)', sizeAdj: '.8px' },
  { id: 'li', name: '碑隶',
    title: 'LiSu,SimLi,"STLiti",var(--f-kai)',
    body: '"Noto Serif SC","Songti SC",SimSun,serif', sizeAdj: '.8px' },
  { id: 'xing', name: '行楷题',
    title: '"STXingkai","华文行楷",var(--f-fang)',
    body: 'FangSong,"STFangsong",SimFang,var(--f-song)', sizeAdj: '.9px' },
]

/* ── 选项表：报告模板（5 套）── */
export interface TemplateOption {
  id: TemplateId
  code: string
  name: string
}

export const TEMPLATES: TemplateOption[] = [
  { id: 'A', code: 'A', name: '会泽经折' },
  { id: 'B', code: 'B', name: '现有版式' },
  { id: 'C', code: 'C', name: '册页图录' },
  { id: 'D', code: 'D', name: '碑拓夜泊' },
  { id: 'E', code: 'E', name: '方志·双栏夹批' },
]

/* 旧版界面用的三选卡（测试与个别地方还引用这个名字），新六套的简表 */
export const FONT_CHOICES: { value: FontId; label: string }[] =
  FONTS.map((f) => ({ value: f.id, label: f.name }))

/* ── 本机存储键与缺省 ── */
export const TEMPLATE_KEY = 'wenheng.ui.template'
export const SKIN_SYS_KEY = 'wenheng.ui.skin.sys'
export const SKIN_RPT_KEY = 'wenheng.ui.skin.rpt'
/** 字体偏好键名保持旧值（前端字体，不解释给馆员看） */
export const FONT_KEY = 'wenheng.ui.font'

export const DEFAULT_TEMPLATE: TemplateId = 'A'
export const DEFAULT_SKIN: SkinId = 'huize'
export const DEFAULT_FONT: FontId = 'song'

/* ── 本机读写（读不到本机就当这次会话内有效，不报错打断馆员）── */
function readRaw(key: string): string | null {
  try { return localStorage.getItem(key) } catch { return null }
}
function writeRaw(key: string, value: string): void {
  try { localStorage.setItem(key, value) } catch { /* 本机存不下＝本次会话内有效 */ }
}

const SKIN_IDS: string[] = SKINS.map((s) => s.id)
const TEMPLATE_IDS: string[] = TEMPLATES.map((t) => t.id)

/* ── 归一：读到的旧值/不认得的值都回落到缺省 ── */
/** 模板：不认得回 A */
export function normalizeTemplate(raw: string | null): TemplateId {
  return raw && TEMPLATE_IDS.includes(raw) ? (raw as TemplateId) : DEFAULT_TEMPLATE
}
/** 皮肤：不认得回会泽绿 */
export function normalizeSkin(raw: string | null): SkinId {
  return raw && SKIN_IDS.includes(raw) ? (raw as SkinId) : DEFAULT_SKIN
}
/** 字体：老版本存过 serif/sans/kai，对应到新六套；其余回会泽宋 */
export function normalizeFont(raw: string | null): FontId {
  if (raw === 'song' || raw === 'hei' || raw === 'kai' || raw === 'fang' || raw === 'li' || raw === 'xing') {
    return raw
  }
  if (raw === 'serif') return 'song'
  if (raw === 'sans') return 'hei'
  return 'song'
}

/* ── 四轴各自读写 ── */
export function readTemplate(): TemplateId { return normalizeTemplate(readRaw(TEMPLATE_KEY)) }
export function writeTemplate(id: TemplateId): void { writeRaw(TEMPLATE_KEY, id) }

export function readSkinSys(): SkinId { return normalizeSkin(readRaw(SKIN_SYS_KEY)) }
export function writeSkinSys(id: SkinId): void { writeRaw(SKIN_SYS_KEY, id) }

export function readSkinRpt(): SkinId { return normalizeSkin(readRaw(SKIN_RPT_KEY)) }
export function writeSkinRpt(id: SkinId): void { writeRaw(SKIN_RPT_KEY, id) }

export function readFont(): FontId { return normalizeFont(readRaw(FONT_KEY)) }
export function writeFont(id: FontId): void { writeRaw(FONT_KEY, id) }

/* ── 把偏好挂到页面（副作用）──
   系统皮肤挂到 <html data-skin-sys>（缺省「会泽绿」也常挂，让 appearance.css
   的会泽绿规则稳定覆盖，不和 tokens.css 的缺省绿打架）；
   字体挂到 <html data-font>（缺省会泽宋＝删属性，走 CSS 缺省，见 applyFontChoice）；
   报告皮肤不挂 <html>（它是生成时传给后端、并在设置里预览用的，见 ModelPanel）。 */
export function applySystemSkin(id: SkinId): void {
  document.documentElement.dataset.skinSys = id
}
export function applyFontChoice(choice: FontId): void {
  if (choice === DEFAULT_FONT) delete document.documentElement.dataset.font
  else document.documentElement.dataset.font = choice
}
/** 字体应用别名（与 applyFontChoice 同义），方便按语义调用。 */
export function applyFont(choice: FontId): void { applyFontChoice(choice) }

/** 旧接口名保留：读存储值归一（兼容老值 serif/sans/kai）。 */
export function fontChoiceFromStorage(raw: string | null): FontId {
  return normalizeFont(raw)
}

/* ── 一键读出全部四轴（设置弹层挂载时调用，确保不打开设置也生效）── */
export interface AppearancePrefs {
  template: TemplateId
  skinSys: SkinId
  skinRpt: SkinId
  font: FontId
}
export function readAppearance(): AppearancePrefs {
  return {
    template: readTemplate(),
    skinSys: readSkinSys(),
    skinRpt: readSkinRpt(),
    font: readFont(),
  }
}

/* ── 生成请求带的三件套（系统皮肤永远不下发）── */
export interface AppearanceRequest {
  template: TemplateId
  skin_rpt: SkinId
  font: FontId
}
export function readAppearanceForRequest(): AppearanceRequest {
  const a = readAppearance()
  return { template: a.template, skin_rpt: a.skinRpt, font: a.font }
}
