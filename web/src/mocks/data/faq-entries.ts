import type { FaqEntry } from '@/types/faq'

const questions = [
  { q: '如何重置密码？', a: '用户可在登录页点击「忘记密码」，输入注册邮箱后系统发送重置链接，链接有效期 30 分钟，点击即可设置新密码。', k: ['密码', '重置', '找回'] },
  { q: '系统支持哪些文件格式？', a: '支持 PDF、Word(.docx)、PPT(.pptx)、Excel(.xlsx)、Markdown、TXT、HTML 等格式文档导入。', k: ['文件', '格式', '导入'] },
  { q: '如何创建知识库？', a: '在知识库页面点击「添加知识库」，填写名称、描述，选择类型（文档/FAQ）和切片策略后提交即可。', k: ['创建', '知识库'] },
  { q: '检索结果如何溯源？', a: '每个检索结果附带来源文档、页码、目录路径和内容 hash，可点击预览或下载原文件验证。', k: ['溯源', '检索', '验证'] },
  { q: 'API Key 如何申请？', a: '管理员在「API Key 管理」页面创建，生成后仅显示一次原始 key，请妥善保存。', k: ['API', 'Key', '申请'] },
  { q: '支持多大规模的文档？', a: '单文档建议不超过 100MB，超过建议拆分上传。系统会自动切片处理。', k: ['文档', '大小', '限制'] },
  { q: '如何批量导入 FAQ？', a: '准备 CSV 或 Excel 文件，包含问题和答案两列（可选关键词列），在问答明细页点击「批量导入」上传。', k: ['批量', '导入', 'FAQ'] },
  { q: '权限角色有哪些？', a: 'super_admin（超级管理员）、admin（管理员）、editor（编辑者）、viewer（查看者）四种角色，权限递减。', k: ['权限', '角色'] },
]

export const mockFaqEntries: FaqEntry[] = questions.map((item, i) => ({
  id: `faq-${String(i + 1).padStart(3, '0')}`,
  kb_id: 'faq-kb-001',
  directory_id: null,
  question: item.q,
  answer: item.a,
  keywords: item.k,
  source_document_id: null,
  category_tags: ['常见问题'],
  view_count: Math.floor(Math.random() * 500),
  helpful_count: Math.floor(Math.random() * 200),
  status: i % 4 === 3 ? 'DRAFT' : 'INDEXED',
  created_at: `2026-07-${String(i + 1).padStart(2, '0')}T08:00:00Z`,
  updated_at: `2026-07-${String(i + 5).padStart(2, '0')}T10:00:00Z`,
}))

export const mockFaqKb = {
  id: 'faq-kb-001',
  name: '产品使用 FAQ',
  description: '产品使用的常见问题与标准答案',
  kb_type: 'FAQ' as const,
  owner_id: 'u-001',
  chunk_strategy: 'PARAGRAPH' as const,
  chunk_size: 512,
  chunk_overlap: 150,
  embedding_model: 'bge-m3',
  es_index_name: 'kb_faq-kb-001',
  document_count: 8,
  created_at: '2026-06-15T08:00:00Z',
  updated_at: '2026-07-28T10:00:00Z',
}
