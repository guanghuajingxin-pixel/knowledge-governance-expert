import { describe, it, expect } from 'vitest'
import { defaultSettings, settingsFromConfig, settingsToConfig, librarySettingsFromConfig,
  defaultRetrievalSettings, retrievalFromConfig, serializeDelimiters, parseDelimiters,
  DELIM_PROTOCOL_SEP } from '../index-settings'
import type { DocumentIndexConfig, ProcessingConfig } from '@/api/document-library'

const libProcessing = (over: Partial<ProcessingConfig> = {}): ProcessingConfig => ({
  chunk_method: 'naive', layout_recognize: 'DeepDOC', chunk_token_num: 512, delimiter: '\n。！？；',
  embedding_model: '', overlap: 25, replace_whitespace: false, remove_urls_emails: false,
  enable_children: false, children_delimiter: '\n', parent_mode: 'paragraph', children_chunk_token_num: 200,
  auto_keywords: 0, auto_questions: 0, ...over,
})

describe('settingsFromConfig', () => {
  it('未配置文档（config={}）从库级 naive 推导为 custom', () => {
    // 后端对未配置文档返回空对象 {}（truthy），不能误判为已配置导致 strategy=undefined
    const s = settingsFromConfig({} as DocumentIndexConfig, libProcessing())
    expect(s.strategy).toBe('custom')
  })

  it('未配置文档从库级 auto 推导为 auto', () => {
    const s = settingsFromConfig({} as DocumentIndexConfig, libProcessing({chunk_method: 'auto'}))
    expect(s.strategy).toBe('auto')
  })

  it('未配置文档从库级父子配置推导为 parent_child', () => {
    const s = settingsFromConfig({} as DocumentIndexConfig, libProcessing({enable_children: true}))
    expect(s.strategy).toBe('parent_child')
  })

  it('null config 同样走推导分支', () => {
    expect(settingsFromConfig(null, libProcessing()).strategy).toBe('custom')
    expect(settingsFromConfig(undefined, libProcessing({chunk_method: 'auto'})).strategy).toBe('auto')
  })

  it('已配置文档以保存的 strategy 为准', () => {
    const cfg: DocumentIndexConfig = {processing: libProcessing({chunk_method: 'auto'}), strategy: 'auto', enhancements: {}, type_rules: {}}
    const s = settingsFromConfig(cfg, libProcessing())
    expect(s.strategy).toBe('auto')
  })

  it('未配置文档从库级全量配置取 processing 推导（不继承库级 by_file_type）', () => {
    const libCfg: DocumentIndexConfig = {processing: libProcessing({chunk_method: 'naive'}), strategy: 'by_file_type', enhancements: {}, type_rules: {}}
    const s = settingsFromConfig({} as DocumentIndexConfig, libCfg)
    expect(s.strategy).toBe('custom')  // 文档视图按 processing 推导，scope=document 不展示按文件类型
  })
})

describe('librarySettingsFromConfig 库级回填', () => {
  it('全量配置完整还原策略视图（按文件类型 + 规则 + 增强）', () => {
    const cfg: DocumentIndexConfig = {
      processing: libProcessing({chunk_method: 'naive', chunk_token_num: 300, overlap: 40}),
      strategy: 'by_file_type',
      enhancements: {include_filename: false},
      type_rules: {pdf: {strategy: 'custom', chunk_token_num: 300, delimiter: '。', children_delimiter: '\n'}},
    }
    const s = librarySettingsFromConfig(cfg)
    expect(s.strategy).toBe('by_file_type')
    expect(s.chunk_token_num).toBe(300)
    expect(s.overlap).toBe(40)
    expect(s.type_rules.pdf.chunk_token_num).toBe(300)
    expect(s.enhancements.include_filename).toBe(false)
    expect(s.enhancements.auto_summary).toBe(true)  // 未配置项回落默认
  })

  it('旧库缺省 strategy 时按 processing 推导，空配置返回默认自动', () => {
    const legacy = {processing: libProcessing(), enhancements: {}, type_rules: {}} as DocumentIndexConfig
    expect(librarySettingsFromConfig(legacy).strategy).toBe('custom')
    const pc = {processing: libProcessing({enable_children: true}), enhancements: {}, type_rules: {}} as DocumentIndexConfig
    expect(librarySettingsFromConfig(pc).strategy).toBe('parent_child')
    expect(librarySettingsFromConfig(null).strategy).toBe('auto')
  })
})

describe('settingsToConfig 策略隔离', () => {
  it('auto：chunk_method=auto 且关闭父子', () => {
    const cfg = settingsToConfig({...defaultSettings(), strategy: 'auto'})
    expect(cfg.processing.chunk_method).toBe('auto')
    expect(cfg.processing.enable_children).toBe(false)
    expect(cfg.strategy).toBe('auto')
  })

  it('custom：用户参数真实透传，chunk_method 固定 naive（无分段方式选择）', () => {
    const cfg = settingsToConfig({...defaultSettings(), strategy: 'custom',
      chunk_token_num: 300, delimiter: '。', overlap: 40,
      preprocess: {replace_whitespace: true, remove_urls_emails: true}})
    expect(cfg.processing.chunk_method).toBe('naive')
    expect(cfg.processing.chunk_token_num).toBe(300)
    expect(cfg.processing.delimiter).toBe('。')
    expect(cfg.processing.overlap).toBe(40)
    expect(cfg.processing.replace_whitespace).toBe(true)
    expect(cfg.processing.remove_urls_emails).toBe(true)
    expect(cfg.processing.enable_children).toBe(false)
  })

  it('parent_child：naive + enable_children + 父块模式/子块配置', () => {
    const cfg = settingsToConfig({...defaultSettings(), strategy: 'parent_child', children_delimiter: '\n\n',
      parent_mode: 'fulltext', children_chunk_token_num: 300})
    expect(cfg.processing.chunk_method).toBe('naive')
    expect(cfg.processing.enable_children).toBe(true)
    expect(cfg.processing.children_delimiter).toBe('\n\n')
    expect(cfg.processing.parent_mode).toBe('fulltext')
    expect(cfg.processing.children_chunk_token_num).toBe(300)
    // 库级回填：父块模式与子块限长完整还原
    const restored = librarySettingsFromConfig(cfg)
    expect(restored.parent_mode).toBe('fulltext')
    expect(restored.children_chunk_token_num).toBe(300)
  })

  it('parent_child 旧配置缺省时父块模式回落段落、子块限长回落 200', () => {
    const legacy = {processing: libProcessing({enable_children: true}), strategy: 'parent_child',
      enhancements: {}, type_rules: {}} as DocumentIndexConfig
    const s = librarySettingsFromConfig(legacy)
    expect(s.parent_mode).toBe('paragraph')
    expect(s.children_chunk_token_num).toBe(200)
  })

  it('策略切换无残留：父子 → 自动后 enable_children 归零', () => {
    const pc = settingsToConfig({...defaultSettings(), strategy: 'parent_child'})
    const reopened = settingsFromConfig(pc, null)
    const auto = settingsToConfig({...reopened, strategy: 'auto'})
    expect(auto.processing.enable_children).toBe(false)
    expect(auto.processing.chunk_method).toBe('auto')
  })

  it('策略切换无残留：自动 → 自定义后 chunk_method 固定 naive', () => {
    const auto = settingsToConfig({...defaultSettings(), strategy: 'auto'})
    const reopened = settingsFromConfig(auto, null)
    const custom = settingsToConfig({...reopened, strategy: 'custom'})
    expect(custom.processing.chunk_method).toBe('naive')
    expect(custom.processing.enable_children).toBe(false)
  })
})

describe('分隔符协议序列化/回填（预设与自定义互斥）', () => {
  it('纯预设：序列化与旧格式（纯字符集）完全一致', () => {
    expect(serializeDelimiters(['zh_period', 'zh_excl', 'zh_quest'], '')).toBe('。！？')
    expect(serializeDelimiters(['nl'], '')).toBe('\n')
    expect(serializeDelimiters(['nl2'], '')).toBe('\n\n')
  })

  it('段落级与行级互斥：选 nl2 不序列化单换行', () => {
    expect(serializeDelimiters(['nl2', 'nl'], '')).toBe('\n\n')
  })

  it('自定义模式：仅序列化自定义字面分隔符（忽略预设勾选，互斥兜底）', () => {
    expect(serializeDelimiters(['custom'], '###')).toBe(DELIM_PROTOCOL_SEP + '###')
    expect(serializeDelimiters(['zh_period'], '###')).toBe(DELIM_PROTOCOL_SEP + '###')
    // 空白输入不产生自定义项（回落预设序列化）
    expect(serializeDelimiters(['zh_period'], '   ')).toBe('。')
  })

  it('协议串回填：进入纯自定义模式（预设勾选不保留）', () => {
    const r = parseDelimiters('。！？' + DELIM_PROTOCOL_SEP + '###')
    expect(r.sel).toEqual(['custom'])
    expect(r.custom).toBe('###')
  })

  it('旧格式回填：遗留自定义字符升级为自定义模式（预设勾选不保留）', () => {
    const r = parseDelimiters('。！###')
    expect(r.sel).toEqual(['custom'])
    expect(r.custom).toBe('###')
    // 再次保存：纯自定义协议串
    expect(serializeDelimiters(r.sel, r.custom)).toBe(DELIM_PROTOCOL_SEP + '###')
  })

  it('纯旧格式（无自定义遗留）回填为预设多选，不勾自定义', () => {
    const r = parseDelimiters('\n。！？；')
    expect(r.sel).toEqual(['nl', 'zh_period', 'zh_excl', 'zh_quest', 'zh_semicolon'])
    expect(r.sel).not.toContain('custom')
    expect(r.custom).toBe('')
  })

  it('自定义 round-trip 幂等：parse → serialize 还原原串', () => {
    const s = DELIM_PROTOCOL_SEP + '####'
    const r = parseDelimiters(s)
    expect(serializeDelimiters(r.sel, r.custom)).toBe(s)
  })

  it('配置回填透传协议串：settingsFromConfig → 组件进入自定义模式', () => {
    const cfg: DocumentIndexConfig = {processing: libProcessing({delimiter: '。' + DELIM_PROTOCOL_SEP + '###'}),
      strategy: 'custom', enhancements: {}, type_rules: {}}
    const s = settingsFromConfig(cfg, null)
    expect(s.delimiter).toBe('。' + DELIM_PROTOCOL_SEP + '###')
    const r = parseDelimiters(s.delimiter)
    expect(r.sel).toEqual(['custom'])
    expect(r.custom).toBe('###')
  })
})

describe('retrievalFromConfig 库级检索设置', () => {
  it('空配置回落默认（混合 + 权重 0.7 + top_k 8）', () => {
    const s = retrievalFromConfig(null)
    expect(s).toEqual(defaultRetrievalSettings())
    expect(s.mode).toBe('hybrid')
    expect(s.rerank).toBe(false)
    expect(s.vector_weight).toBe(0.7)
  })

  it('已存配置逐项覆盖（全文 + Rerank + 阈值）', () => {
    const s = retrievalFromConfig({mode: 'fulltext', rerank: true, rerank_model_id: 'abc',
      top_k: 20, score_threshold: 0.35})
    expect(s.mode).toBe('fulltext')
    expect(s.rerank).toBe(true)
    expect(s.rerank_model_id).toBe('abc')
    expect(s.top_k).toBe(20)
    expect(s.score_threshold).toBe(0.35)
    expect(s.vector_weight).toBe(0.7)  // 未配置项保持默认
  })
})
