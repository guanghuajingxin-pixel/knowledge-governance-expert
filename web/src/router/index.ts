import { createRouter, createWebHistory, type RouteRecordRaw } from 'vue-router'
import { useUserStore } from '@/stores/user'

const routes: RouteRecordRaw[] = [
  {
    path: '/login',
    name: 'Login',
    component: () => import('@/views/login/index.vue'),
    meta: { public: true },
  },
  {
    path: '/',
    component: () => import('@/layouts/AppLayout.vue'),
    redirect: '/chat',
    children: [
      // ===== 知识治理专家 · 七大模块 =====
      {
        path: 'chat',
        name: 'Chat',
        component: () => import('@/views/chat/index.vue'),
        meta: { title: '智能问答', icon: 'ChatLineRound', group: 'feature' },
      },
      {
        path: 'hiagent',
        name: 'HiAgent',
        component: () => import('@/views/hiagent/index.vue'),
        meta: { title: 'HiAgent智能问答', icon: 'ChatDotRound', group: 'feature' },
      },
      {
        path: 'collection',
        name: 'Collection',
        component: () => import('@/views/governance/collection.vue'),
        meta: { title: '知识采集', icon: 'Download', group: 'feature' },
      },
      {
        path: 'process',
        name: 'Process',
        component: () => import('@/views/governance/process.vue'),
        meta: { title: '知识加工', icon: 'Setting', group: 'feature' },
      },
      {
        path: 'apply',
        name: 'Apply',
        component: () => import('@/views/governance/apply.vue'),
        meta: { title: '知识应用', icon: 'Connection', group: 'feature' },
      },
      {
        path: 'operate',
        name: 'Operate',
        component: () => import('@/views/governance/operate/index.vue'),
        meta: { title: '知识运营', icon: 'DataLine', group: 'feature' },
      },
      {
        path: 'govern',
        name: 'Govern',
        component: () => import('@/views/governance/govern.vue'),
        meta: { title: '知识治理', icon: 'Stamp', group: 'feature' },
      },
      {
        path: 'knowledge-center',
        name: 'KnowledgeCenter',
        component: () => import('@/views/knowledge-center/index.vue'),
        meta: { title: '知识中心', icon: 'Reading', group: 'feature' },
      },
      {
        path: 'knowledge-sources',
        name: 'KnowledgeSources',
        component: () => import('@/views/knowledge-sources/index.vue'),
        meta: { title: '知识源管理', icon: 'Connection', group: 'feature', parent: '/knowledge-center', roles: ['super_admin', 'admin', 'editor'] },
      },
      {
        path: 'model',
        name: 'Model',
        component: () => import('@/views/governance/model.vue'),
        meta: { title: '系统配置', icon: 'Cpu', group: 'config' },
      },
      {
        path: 'agent-config',
        name: 'AgentConfig',
        component: () => import('@/views/agent/config.vue'),
        meta: { title: '智能体配置', icon: 'MagicStick', roles: ['super_admin', 'admin'], group: 'config' },
      },

      // ===== 平台管理 =====
      {
        path: 'admin/users',
        name: 'AdminUsers',
        component: () => import('@/views/admin/users.vue'),
        meta: { title: '用户管理', icon: 'User', roles: ['super_admin', 'admin'], group: 'admin' },
      },

      // ===== 原有路由（保留，隐藏导航） =====
      {
        path: 'knowledge-bases',
        name: 'KnowledgeBases',
        component: () => import('@/views/knowledge-base/index.vue'),
        meta: { title: '知识库', icon: 'Collection', hidden: true },
      },
      {
        path: 'knowledge-bases/:id',
        name: 'KnowledgeBaseDetail',
        component: () => import('@/views/knowledge-base/detail.vue'),
        meta: { title: '知识库详情', hidden: true },
      },
      {
        path: 'knowledge-bases/:id/documents/:docId',
        name: 'DocumentPreview',
        component: () => import('@/views/knowledge-base/document-preview.vue'),
        meta: { title: '切片预览', hidden: true },
      },
      {
        path: 'faq',
        name: 'FaqList',
        component: () => import('@/views/faq/index.vue'),
        meta: { title: '问答库', icon: 'ChatDotRound', hidden: true },
      },
      {
        path: 'faq/:id',
        name: 'FaqDetail',
        component: () => import('@/views/faq/detail.vue'),
        meta: { title: '问答明细', hidden: true },
      },
      {
        path: 'search',
        name: 'Search',
        component: () => import('@/views/search/index.vue'),
        meta: { title: '统一检索', icon: 'Search', hidden: true },
      },
      {
        path: 'settings',
        name: 'Settings',
        component: () => import('@/views/settings/index.vue'),
        meta: { title: '模型配置', icon: 'Setting', roles: ['super_admin', 'admin'], hidden: true },
      },
    ],
  },
  {
    path: '/:pathMatch(.*)*',
    name: 'NotFound',
    component: () => import('@/views/login/index.vue'),
    meta: { public: true },
  },
]

const router = createRouter({
  history: createWebHistory(),
  routes,
})

router.beforeEach((to, _from, next) => {
  const userStore = useUserStore()
  userStore.restoreUser()

  if (to.meta.public) {
    next()
    return
  }

  if (!userStore.token) {
    next('/login')
    return
  }

  const roles = to.meta.roles as string[] | undefined
  if (roles && userInfoRole(userStore) && !roles.includes(userInfoRole(userStore) as string)) {
    next('/chat')
    return
  }

  next()
})

function userInfoRole(userStore: ReturnType<typeof useUserStore>): string | null {
  return userStore.userInfo?.role || null
}

export default router
