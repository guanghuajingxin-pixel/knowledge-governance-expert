import { createRouter, createWebHistory, type RouteRecordRaw } from 'vue-router'
import { ElMessage } from 'element-plus'
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
        meta: { title: '智能问答', icon: 'MessageCircle', group: 'feature' },
      },
      {
        path: 'deap-agent',
        name: 'DeapAgent',
        component: () => import('@/views/deap-agent/index.vue'),
        meta: { title: 'DEAP智能问答', icon: 'BotMessageSquare', group: 'feature' },
      },
      {
        path: 'hiagent',
        name: 'HiAgent',
        component: () => import('@/views/embed-agent/index.vue'),
        props: { platform: 'hiagent' },
        meta: { title: 'HiAgent智能问答', icon: 'MessagesSquare', group: 'feature' },
      },
      {
        path: 'dify',
        name: 'DifyAgent',
        component: () => import('@/views/embed-agent/index.vue'),
        props: { platform: 'dify' },
        meta: { title: 'Dify智能问答', icon: 'Workflow', group: 'feature' },
      },
      {
        // 知识采集：页面已拆分为二级页（知识源管理/知识中心/同步队列），父级仅作分组，重定向到首个子页
        path: 'collection',
        name: 'Collection',
        redirect: '/knowledge-sources',
        meta: { title: '知识采集', icon: 'Import', group: 'feature' },
      },
      {
        // 知识应用：拆分为二级页（脱敏策略/知识库），父级仅作分组，重定向到首个子页
        path: 'apply',
        name: 'Apply',
        redirect: '/apply/masking',
        meta: { title: '知识应用', icon: 'Blocks', group: 'feature' },
      },
      {
        // 脱敏策略：检索返回脱敏策略控制台（策略编排/敏感词典/豁免/审计/沙箱），仅管理员可管
        path: 'apply/masking',
        name: 'MaskingStrategy',
        component: () => import('@/views/masking/index.vue'),
        meta: { title: '脱敏策略', icon: 'EyeOff', group: 'feature', parent: '/apply', menuOrder: 1, roles: ['super_admin', 'admin'] },
      },
      {
        // 知识库：项目文档库 / 物料库 / 问答库
        path: 'apply/knowledge-libraries',
        name: 'KnowledgeLibraries',
        component: () => import('@/views/knowledge-libraries/index.vue'),
        meta: { title: '知识库', icon: 'Library', group: 'feature', parent: '/apply', menuOrder: 2, roles: ['super_admin', 'admin', 'editor'] },
      },
      {
        // 知识库详情：点击具体知识库以独立门户页签打开，不覆盖知识库列表页签
        path: 'apply/knowledge-libraries/:libId',
        name: 'KnowledgeLibraryDetail',
        component: () => import('@/views/knowledge-libraries/DocumentLibraries.vue'),
        props: (route) => ({ openLibId: Number(route.params.libId) }),
        meta: { title: '知识库详情', hidden: true, roles: ['super_admin', 'admin', 'editor'] },
      },
      {
        // Wiki 库详情：页面/原料双视图，从 Wiki 库列表点击进入，门户页签独立打开
        path: 'apply/knowledge-libraries/:libId/wiki',
        name: 'WikiLibraryDetail',
        component: () => import('@/views/knowledge-libraries/WikiLibraryDetail.vue'),
        props: (route) => ({ libId: Number(route.params.libId) }),
        meta: { title: 'Wiki 库详情', hidden: true, roles: ['super_admin', 'admin', 'editor'] },
      },
      {
        // Wiki 页面阅读：wikilink 跳转/溯源入口，门户页签独立打开
        path: 'apply/knowledge-libraries/:libId/wiki/pages/:pageId',
        name: 'WikiPageView',
        component: () => import('@/views/knowledge-libraries/WikiPageView.vue'),
        props: (route) => ({ libId: Number(route.params.libId), pageId: String(route.params.pageId) }),
        meta: { title: 'Wiki 页面', hidden: true, roles: ['super_admin', 'admin', 'editor'] },
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
        // 解析原文（文档级）：从分段页「新页面查看」进入，门户页签独立打开
        path: 'apply/knowledge-libraries/:libId/documents/:docId/parsed-content',
        name: 'DocumentParsedContent',
        component: () => import('@/views/knowledge-libraries/ParsedContentPage.vue'),
        meta: { title: '解析原文', hidden: true, roles: ['super_admin', 'admin', 'editor'] },
      },
      {
        // 知识运营：分组容器（运营看板/问答明细/知识纠错），父级仅作分组，重定向到首个子页
        path: 'operate',
        name: 'Operate',
        redirect: '/operate/dashboard',
        meta: { title: '知识运营', icon: 'ChartLine', group: 'feature' },
      },
      {
        // 运营看板：原「知识运营」页签独立为二级页
        path: 'operate/dashboard',
        name: 'OperateDashboard',
        component: () => import('@/views/governance/operate/Dashboard.vue'),
        meta: { title: '运营看板', icon: 'ChartLine', group: 'feature', parent: '/operate', menuOrder: 1 },
      },
      {
        // 问答明细：原「知识运营」页签独立为二级页
        path: 'operate/qa',
        name: 'OperateQa',
        component: () => import('@/views/governance/operate/QaDetails.vue'),
        meta: { title: '问答明细', icon: 'MessagesSquare', group: 'feature', parent: '/operate', menuOrder: 2 },
      },
      {
        // 知识纠错：原「知识运营」页签独立为二级页
        path: 'operate/corrections',
        name: 'OperateCorrections',
        component: () => import('@/views/governance/operate/Corrections.vue'),
        meta: { title: '知识纠错', icon: 'Pencil', group: 'feature', parent: '/operate', menuOrder: 3 },
      },
      {
        // 知识治理：分组容器（知识缺口/入库审核），父级仅作分组，重定向到首个子页
        path: 'govern',
        name: 'Govern',
        redirect: '/govern/gaps',
        meta: { title: '知识治理', icon: 'ShieldCheck', group: 'feature' },
      },
      {
        // 知识缺口：原「知识治理」页下沉为子页（知识缺口 + 治理标准页签）
        path: 'govern/gaps',
        name: 'GovernGaps',
        component: () => import('@/views/governance/govern.vue'),
        meta: { title: '知识缺口', icon: 'ChartLine', group: 'feature', parent: '/govern', menuOrder: 1 },
      },
      {
        // 入库审核：钉钉知识入库审核（列表内完成审核）
        path: 'govern/review',
        name: 'GovernReview',
        component: () => import('@/views/governance/process.vue'),
        meta: { title: '入库审核', icon: 'BadgeCheck', group: 'feature', parent: '/govern', menuOrder: 2 },
      },
      {
        // 解析引擎：双页签（自定义解析 + MinerU WebUI iframe），挂到知识采集分组下
        path: 'process/engine',
        name: 'ProcessEngine',
        component: () => import('@/views/governance/ProcessEngine.vue'),
        meta: { title: '解析引擎', icon: 'Gauge', group: 'feature', parent: '/collection', menuOrder: 4 },
      },
      {
        // 知识源管理：原「知识中心」子菜单，挂到知识采集分组下
        path: 'knowledge-sources',
        name: 'KnowledgeSources',
        component: () => import('@/views/knowledge-sources/index.vue'),
        meta: { title: '知识源管理', icon: 'Plug', group: 'feature', parent: '/collection', menuOrder: 1, roles: ['super_admin', 'admin', 'editor'] },
      },
      {
        // 知识中心：跨文档库聚合所有来源的知识源文档（标题/标签/来源系统/更新人/更新与过期时间），
        // 钉钉来源标记「钉钉+知识库名称」且标题可跳转钉钉知识库
        path: 'collection/knowledge-center',
        name: 'CollectionKnowledgeCenter',
        component: () => import('@/views/governance/collection/KnowledgeCenter.vue'),
        meta: { title: '知识中心', icon: 'FolderOpen', group: 'feature', parent: '/collection', menuOrder: 2 },
      },
      {
        // 同步队列：知识同步过程的逐文档任务列表（待处理/处理中/已完成 + 失败任务重试）
        path: 'collection/queue',
        name: 'CollectionQueue',
        component: () => import('@/views/governance/collection/SyncQueue.vue'),
        meta: { title: '同步队列', icon: 'ListTodo', group: 'feature', parent: '/collection', menuOrder: 3 },
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
        meta: { title: '智能体配置', icon: 'Bot', roles: ['super_admin', 'admin'], group: 'config' },
      },

      // ===== 平台管理 =====
      {
        path: 'settings/api-keys',
        name: 'PlatformApiKeys',
        component: () => import('@/views/settings/api-keys.vue'),
        meta: { title: 'API Key', icon: 'KeyRound', roles: ['super_admin', 'admin'], group: 'config' },
      },

      // ===== 原有路由（保留，隐藏导航） =====
      {
        path: 'knowledge-bases',
        name: 'KnowledgeBases',
        component: () => import('@/views/knowledge-base/index.vue'),
        meta: { title: '知识库', icon: 'Library', hidden: true },
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
        meta: { title: '问答库', icon: 'MessagesSquare', hidden: true },
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

/** 菜单注册表（与后端 menu_registry 对齐，key 即路由 path）；hidden 详情路由继承最长匹配前缀 */
const MENU_PATH_KEYS = [
  '/chat', '/deap-agent', '/hiagent', '/dify',
  '/knowledge-sources', '/collection/knowledge-center', '/collection/queue',
  '/apply/masking', '/apply/knowledge-libraries',
  '/operate/dashboard', '/operate/qa', '/operate/corrections',
  '/govern/gaps', '/govern/review',
  '/model', '/agent-config', '/settings/api-keys',
]

function menuKeyFor(path: string): string | null {
  if (MENU_PATH_KEYS.includes(path)) return path
  const matched = MENU_PATH_KEYS
    .filter(key => path.startsWith(key + '/'))
    .sort((a, b) => b.length - a.length)[0]
  return matched || null
}

router.beforeEach((to, _from, next) => {
  const userStore = useUserStore()
  userStore.restoreUser()

  if (to.meta.public) {
    next()
    return
  }

  if (!userStore.token) {
    next(to.meta.standalone ? `/login?redirect=${encodeURIComponent(to.fullPath)}` : '/login')
    return
  }

  const roles = to.meta.roles as string[] | undefined
  if (roles && userInfoRole(userStore) && !roles.includes(userInfoRole(userStore) as string)) {
    next('/chat')
    return
  }

  // 菜单权限白名单（null/undefined = 未配置不限制；super_admin 后端恒为 null）
  const menus = userStore.userInfo?.menu_permissions
  if (Array.isArray(menus)) {
    const key = menuKeyFor(to.path)
    if (key && !menus.includes(key)) {
      const fallback = menus.find(m => m.startsWith('/')) || '/chat'
      if (to.path !== fallback) {
        ElMessage.warning('当前账号无该菜单的访问权限')
        next(fallback)
        return
      }
    }
  }

  next()
})

function userInfoRole(userStore: ReturnType<typeof useUserStore>): string | null {
  return userStore.userInfo?.role || null
}

export default router
