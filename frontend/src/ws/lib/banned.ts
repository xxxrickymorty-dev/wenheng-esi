/* 界面禁用词（票 04；UX.md 第十节黑名单）。
   e2e（票 09）与人工检查共用这一份；**单一来源**——别在别处再抄一份列表。 */

export const BANNED_UI_TERMS: readonly string[] = [
  // 接口/实现细节
  '/api', '/healthz', 'sha256', 'require_admin',
  // 运行档案内部文件与事件
  'agent_events', 'state_history', '_superseded', 'Agent 轨迹', 'task_runs',
  // 演示后门与契约记号
  '?demo=', '契约 §', 'P0 #', 'P0#',
  // 工具名（一律翻译成人话）
  'run_parse', 'run_compute', 'run_forecast', 'run_charts', 'run_docx', 'inspect_ledger',
  'read_cell', 'run_backtest', 'scan_stale', 'apply_repair_rule', 'collect_artifacts',
  'run_college_stats', 'write_env_snapshot',
  // 导师明确禁用的称谓（对外一律写「云南大学图书馆」）
  '数字图书馆',
  // 内部词汇
  '断言', '机器断言',
  // 内部黑话与模型串（2026-10-15 UX 评估：一律翻译成人话）
  '盾', '规划后端', 'openai:', 'deepseek',
  // 裸 Markdown 记号（前端未渲染 Markdown 时不许露星号）
  '**',
]

/** 在给定文本里找出命中的禁用词（返回去重后的列表；干净文本返回 []）。 */
export function findBanned(text: string): string[] {
  const hits: string[] = []
  for (const term of BANNED_UI_TERMS) {
    if (text.includes(term) && !hits.includes(term)) hits.push(term)
  }
  return hits
}
