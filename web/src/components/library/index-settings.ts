/** 索引设置：文档级 / 知识库级共用的策略视图模型与转换逻辑。

策略视图（前端交互）与解析配置（后端 ProcessingConfig）的双向转换：
- auto         自动：chunk_method=auto，分段器内置分层瀑布（标题结构切分 → 递归长度
               修正 → 无结构文本统计兜底），chunk_token_num 作为目标长度
- custom       自定义：分段方式 + 分段标识数 + 分段标识符
- parent_child 父子分段：naive + enable_children + 子分段标识符
- by_file_type 按文件类型：type_rules 按扩展名覆盖，未命中的走 auto（仅知识库级）
*/
import type { DocumentIndexConfig, Enhancements, ProcessingConfig, TypeRule } from '@/api/document-library'

export type Strategy = 'auto' | 'custom' | 'parent_child' | 'by_file_type'

export interface IndexSettings {
  strategy: Strategy
  method: string
  chunk_token_num: number
  delimiter: string
  children_delimiter: string
  layout_recognize: string
  type_rules: Record<string, TypeRule>
  enhancements: Enhancements
}

export const METHODS = [
  {value: 'naive', label: '通用文档'}, {value: 'manual', label: '说明书'}, {value: 'paper', label: '论文'},
  {value: 'book', label: '书籍'}, {value: 'laws', label: '法律法规'}, {value: 'presentation', label: '演示文稿'},
  {value: 'table', label: '表格'}, {value: 'one', label: '整篇分段'}]

export const ENHANCEMENT_DEFAULTS: Enhancements = {
  include_filename: true, auto_summary: true, auto_questions: true, image_caption: true}

export const AUTO_DEFAULTS = {method: 'naive', chunk_token_num: 512, delimiter: '\n。！？；', children_delimiter: '\n'}

export function defaultSettings(): IndexSettings {
  return {strategy: 'auto', ...AUTO_DEFAULTS, layout_recognize: 'DeepDOC', type_rules: {}, enhancements: {...ENHANCEMENT_DEFAULTS}}
}

/** 已保存的文档配置优先；无配置时从库级 processing 推导（父子启用 → parent_child，auto 方法 → auto，否则 custom）。 */
export function settingsFromConfig(cfg?: DocumentIndexConfig | null, fallback?: ProcessingConfig | null): IndexSettings {
  const s = defaultSettings()
  const p = cfg?.processing || fallback
  if (p) {
    s.method = p.chunk_method === 'auto' ? 'naive' : p.chunk_method
    s.chunk_token_num = p.chunk_token_num
    s.delimiter = p.delimiter
    s.children_delimiter = p.children_delimiter || '\n'
    s.layout_recognize = p.layout_recognize || 'DeepDOC'
  }
  if (cfg) {
    s.strategy = cfg.strategy
    s.type_rules = cfg.type_rules || {}
    s.enhancements = {...ENHANCEMENT_DEFAULTS, ...(cfg.enhancements || {})}
  } else {
    s.strategy = p?.enable_children ? 'parent_child' : p?.chunk_method === 'auto' ? 'auto' : 'custom'
  }
  return s
}

/** 策略视图 → 解析配置：auto 映射 chunk_method=auto（分层瀑布由分段器内置实现，512/默认分隔符作为长度修正参数）；parent_child 固定 naive + enable_children。 */
export function settingsToConfig(s: IndexSettings): DocumentIndexConfig {
  const auto = s.strategy === 'auto'
  const processing: ProcessingConfig = {
    chunk_method: auto ? 'auto' : s.method,
    layout_recognize: s.layout_recognize || 'DeepDOC',
    chunk_token_num: auto ? 512 : s.chunk_token_num,
    delimiter: auto ? '\n。！？；' : s.delimiter,
    embedding_model: '',
    enable_children: s.strategy === 'parent_child',
    children_delimiter: s.children_delimiter,
    auto_keywords: 0,
    auto_questions: 0}
  return {processing, strategy: s.strategy, enhancements: {...s.enhancements}, type_rules: s.type_rules}
}
