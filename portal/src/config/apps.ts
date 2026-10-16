export const applications = [
  { id: 'knowledge', name: '知识治理专家', caption: '让企业知识成为生产力', description: '汇聚企业知识，检索可信答案', icon: 'BookOpen', url: import.meta.env.VITE_KNOWLEDGE_URL || '/kge/chat', permKey: 'portal.app.knowledge' },
  { id: 'evaluation', name: '智能体测评', caption: '让每一次回答更可靠', description: '管理测评数据，评估智能体表现', icon: 'FlaskConical', url: import.meta.env.VITE_EVALUATION_URL || '/evaluation/datasets', permKey: 'portal.app.evaluation' },
  { id: 'skillhub', name: 'SkillHub', caption: '让好用的能力随手可得', description: '发现、复用与共享智能体技能', icon: 'Blocks', url: import.meta.env.VITE_SKILLHUB_URL || '/skillhub/', permKey: 'portal.app.skillhub' },
] as const
export type AppId = typeof applications[number]['id']
export type PageId = 'home' | AppId | 'accounts' | 'roles'
/** 门户菜单权限 key：与小杰对话入口（不在菜单权限内时隐藏对话入口） */
export const HOME_PERM_KEY = 'portal.home'
export function pageFromHash(hash: string): PageId {
  const id = hash.replace(/^#\/?/, '')
  if (id === 'accounts' || id === 'roles') return id
  return applications.some(app => app.id === id) ? id as AppId : 'home'
}
