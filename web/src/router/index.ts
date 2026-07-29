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
    redirect: '/dashboard',
    children: [
      {
        path: 'dashboard',
        name: 'Dashboard',
        component: () => import('@/views/dashboard/index.vue'),
        meta: { title: '工作台' },
      },
      {
        path: 'knowledge-bases',
        name: 'KnowledgeBases',
        component: () => import('@/views/knowledge-base/index.vue'),
        meta: { title: '知识库' },
      },
      {
        path: 'knowledge-bases/:id',
        name: 'KnowledgeBaseDetail',
        component: () => import('@/views/knowledge-base/detail.vue'),
        meta: { title: '知识库详情' },
      },
      {
        path: 'knowledge-bases/:id/documents/:docId',
        name: 'DocumentPreview',
        component: () => import('@/views/knowledge-base/document-preview.vue'),
        meta: { title: '切片预览' },
      },
      {
        path: 'faq',
        name: 'FaqList',
        component: () => import('@/views/faq/index.vue'),
        meta: { title: '问答库' },
      },
      {
        path: 'faq/:id',
        name: 'FaqDetail',
        component: () => import('@/views/faq/detail.vue'),
        meta: { title: '问答明细' },
      },
      {
        path: 'search',
        name: 'Search',
        component: () => import('@/views/search/index.vue'),
        meta: { title: '统一检索' },
      },
      {
        path: 'admin/users',
        name: 'AdminUsers',
        component: () => import('@/views/admin/users.vue'),
        meta: { title: '用户管理', roles: ['super_admin', 'admin'] },
      },
      {
        path: 'admin/api-keys',
        name: 'AdminApiKeys',
        component: () => import('@/views/admin/api-keys.vue'),
        meta: { title: 'API Key 管理' },
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
    next('/dashboard')
    return
  }

  next()
})

function userInfoRole(userStore: ReturnType<typeof useUserStore>): string | null {
  return userStore.userInfo?.role || null
}

export default router
