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
    // 独立问答页：全屏复用问答视图（会话历史+问答区），供新窗口/钉钉 H5 微应用接入
    // hidden：不进侧边栏菜单（仅经新窗口按钮/独立地址/钉钉微应用进入）
    path: '/qa',
    name: 'StandaloneQA',
    component: () => import('@/views/chat/index.vue'),
    meta: { title: '智能问答', standalone: true, hidden: true },
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
        path: 'deap-agent',
        name: 'DeapAgent',
        component: () => import('@/views/deap-agent/index.vue'),
        meta: { title: 'DEAP智能问答', icon: 'Monitor', group: 'feature' },
      },
      {
        path: 'hiagent',
        name: 'HiAgent',
        component: () => import('@/views/embed-agent/index.vue'),
        props: { platform: 'hiagent' },
        meta: { title: 'HiAgent智能问答', icon: 'ChatDotRound', group: 'feature' },
      },
      {
        path: 'dify',
        name: 'DifyAgent',
        component: () => import('@/views/embed-agent/index.vue'),
        props: { platform: 'dify' },
        meta: { title: 'Dify智能问答', icon: 'ChatDotSquare', group: 'feature' },
      },
      {
        // 知识采集：页面已拆分为二级页（钉钉知识同步/本地上传），父级仅作分组，重定向到首个子页
        path: 'collection',
        name: 'Collection',
        redirect: '/knowledge-sources',
        meta: { title: '知识采集', icon: 'Download', group: 'feature' },
      },
      {
        // 知识加工：页面拆分为二级页（知识打标/解析引擎），父级仅作分组，重定向到首个子页
        path: 'process',
        name: 'Process',
        redirect: '/process/tagging',
        meta: { title: '知识加工', icon: 'Setting', group: 'feature' },
      },
      {
        // 知识打标：原「知识加工」页内容下沉为二级页（AI 打标 + 摘要生成 + 知识关系构建）
        path: 'process/tagging',
        name: 'ProcessTagging',
        component: () => import('@/views/governance/process.vue'),
        meta: { title: '知识打标', icon: 'CollectionTag', group: 'feature', parent: '/process', menuOrder: 1 },
      },
      {
        // 解析引擎：双页签（自定义解析 + MinerU WebUI iframe）
        path: 'process/engine',
        name: 'ProcessEngine',
        component: () => import('@/views/governance/ProcessEngine.vue'),
        meta: { title: '解析引擎', icon: 'Odometer', group: 'feature', parent: '/process', menuOrder: 2 },
      },
      {
        // 结构化处理：解析 JSON → 表结构/字段映射 → 预览 → 一键写入共享 PG(structured schema)
        path: 'process/structured',
        name: 'ProcessStructured',
        component: () => import('@/views/governance/StructuredProcess.vue'),
        meta: { title: '结构化处理', icon: 'Grid', group: 'feature', parent: '/process', menuOrder: 3 },
      },
      {
        // 知识应用：拆分为二级页（脱敏策略/知识库），父级仅作分组，重定向到首个子页
        path: 'apply',
        name: 'Apply',
        redirect: '/apply/masking',
        meta: { title: '知识应用', icon: 'Connection', group: 'feature' },
      },
      {
        // 脱敏策略：检索返回脱敏策略控制台（策略编排/敏感词典/豁免/审计/沙箱），仅管理员可管
        path: 'apply/masking',
        name: 'MaskingStrategy',
        component: () => import('@/views/masking/index.vue'),
        meta: { title: '脱敏策略', icon: 'Hide', group: 'feature', parent: '/apply', menuOrder: 1, roles: ['super_admin', 'admin'] },
      },
      {
        // 知识库：项目文档库 / 问答库 / DIFY 外部库 / RAGFLOW 外部库
        path: 'apply/knowledge-libraries',
        name: 'KnowledgeLibraries',
        component: () => import('@/views/knowledge-libraries/index.vue'),
        meta: { title: '知识库', icon: 'Collection', group: 'feature', parent: '/apply', menuOrder: 2, roles: ['super_admin', 'admin', 'editor'] },
      },
      {
        // 文档分段详情：文档库内点击文件名进入，门户页签独立打开
        path: 'apply/knowledge-libraries/:libId/documents/:docId',
        name: 'LibraryDocumentSegments',
        component: () => import('@/views/knowledge-libraries/DocumentSegments.vue'),
        meta: { title: '分段详情', hidden: true, roles: ['super_admin', 'admin', 'editor'] },
      },
      {
        // 检索测试（知识库级）：门户页签独立打开
        path: 'apply/knowledge-libraries/:libId/retrieval-test',
        name: 'LibraryRetrievalTest',
        component: () => import('@/views/knowledge-libraries/RetrievalTestPage.vue'),
        meta: { title: '检索测试', hidden: true, roles: ['super_admin', 'admin', 'editor'] },
      },
      {
        // 检索测试（文档级）：门户页签独立打开
        path: 'apply/knowledge-libraries/:libId/documents/:docId/retrieval-test',
        name: 'DocumentRetrievalTest',
        component: () => import('@/views/knowledge-libraries/RetrievalTestPage.vue'),
        meta: { title: '检索测试', hidden: true, roles: ['super_admin', 'admin', 'editor'] },
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
        // 知识源管理：原「知识中心」子菜单，知识中心页签迁入知识加工后挂到知识采集分组下
        path: 'knowledge-sources',
        name: 'KnowledgeSources',
        component: () => import('@/views/knowledge-sources/index.vue'),
        meta: { title: '知识源管理', icon: 'Connection', group: 'feature', parent: '/collection', menuOrder: 1, roles: ['super_admin', 'admin', 'editor'] },
      },
      {
        // 钉钉知识同步：原「知识采集」页钉钉页签下沉为二级页（定时同步 + 指定目录同步）
        path: 'collection/dingtalk',
        name: 'CollectionDingtalk',
        component: () => import('@/views/governance/collection/DingtalkSync.vue'),
        meta: { title: '钉钉知识同步', icon: 'Clock', group: 'feature', parent: '/collection', menuOrder: 2 },
      },
      {
        // 本地上传：原「知识采集」页上传页签下沉为二级页（本地文档手动上传到 Dify）
        path: 'collection/upload',
        name: 'CollectionUpload',
        component: () => import('@/views/governance/collection/ManualUpload.vue'),
        meta: { title: '本地上传', icon: 'Upload', group: 'feature', parent: '/collection', menuOrder: 3 },
      },
      {
        // 同步队列：知识同步过程的逐文档任务列表（待处理/处理中/已完成 + 失败任务重试）
        path: 'collection/queue',
        name: 'CollectionQueue',
        component: () => import('@/views/governance/collection/SyncQueue.vue'),
        meta: { title: '同步队列', icon: 'Tickets', group: 'feature', parent: '/collection', menuOrder: 4 },
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
        // 模型配置页已并入系统配置页（/model），旧地址重定向避免书签失效
        path: 'settings',
        redirect: '/model',
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
    // 独立页：钉钉内放行由视图免登；浏览器回登录页并记录回跳地址
    if (to.meta.standalone && /DingTalk/i.test(navigator.userAgent)) {
      next()
      return
    }
    next(to.meta.standalone ? `/login?redirect=${encodeURIComponent(to.fullPath)}` : '/login')
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
