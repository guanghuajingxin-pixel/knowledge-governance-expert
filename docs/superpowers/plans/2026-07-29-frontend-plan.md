# 知识库管理后台 - 前端实现计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 构建 Vue 3 + Element Plus 知识库管理后台前端，覆盖知识库管理、文档管理、FAQ 管理、统一检索、权限管理五大模块，dev 模式使用 MSW mock 数据，可独立运行验证样式与功能。

**Architecture:** 单页应用（SPA）。Vite 构建，Vue Router 路由，Pinia 状态管理，Axios + MSW 双模式 API 层（`VITE_USE_MOCK=true` 走 MSW，否则走真实后端）。布局采用左侧深色导航 + 浅灰内容区的经典 Admin 布局，严格对齐 `风格参考/` 目录截图。

**Tech Stack:** Vue 3.4+ (Composition API + `<script setup>`)、TypeScript strict、Element Plus 2.x、`@element-plus/icons-vue`、Vite 5.x、Vue Router 4.x、Pinia、Axios、MSW（mock）、Vitest（单元测试）、pnpm。

## Global Constraints

- Node.js v24.18.0，pnpm 11.17.0（已安装）
- 前端代码位于 `web/` 目录
- TypeScript strict 模式开启，禁用 `any`（除 MSW handler 返回值可宽松）
- 所有组件使用 `<script setup lang="ts">` 语法
- 中文界面，文案使用中文常量（MVP 阶段不做 i18n）
- 配色严格使用 Element Plus 默认主题：primary `#409EFF`，sidebar `#263445`，content bg `#f5f7fa`
- API 路径前缀 `/api/v1`，与设计文档 API 表一致
- 每个任务结束必须 commit，commit message 使用 `feat:`/`fix:`/`chore:` 前缀
- 浏览器视觉验证：每个页面任务完成后，启动 dev server 截图或人工确认布局对齐参考截图

## Mock 数据策略

整个 API 层通过 `src/api/request.ts` 的 Axios 实例统一发请求。MSW（Mock Service Worker）在 `VITE_USE_MOCK=true` 时拦截所有 `/api/v1/*` 请求并返回 mock 数据。

- 优点：前端独立开发，不依赖后端；未来接后端只需设 `VITE_USE_MOCK=false`
- mock 数据集中在 `src/mocks/data/`，handler 集中在 `src/mocks/handlers/`
- 每个业务模块的 mock 数据与设计文档的数据模型一一对应

## File Structure

```
web/
├── index.html
├── package.json
├── pnpm-lock.yaml
├── tsconfig.json
├── tsconfig.node.json
├── vite.config.ts
├── env.d.ts
├── .env.development                # VITE_USE_MOCK=true, VITE_API_BASE_URL=/api/v1
├── .env.production                 # VITE_USE_MOCK=false
├── public/
│   └── mockServiceWorker.js        # MSW 生成
└── src/
    ├── main.ts                     # 应用入口：注册 ElementPlus、Pinia、Router、MSW
    ├── App.vue                     # 根组件，<router-view>
    ├── env.d.ts
    ├── vite-env.d.ts
    ├── router/
    │   └── index.ts                # 路由定义 + 守卫
    ├── stores/
    │   ├── user.ts                 # 用户状态（token、用户信息、角色）
    │   └── app.ts                  # 全局状态（侧边栏折叠）
    ├── api/
    │   ├── request.ts              # Axios 实例 + 请求/响应拦截器
    │   ├── auth.ts                 # 登录、用户信息、API Key
    │   ├── knowledge-base.ts       # 知识库 CRUD、目录
    │   ├── document.ts             # 文档上传、列表、切片
    │   ├── faq.ts                  # FAQ 知识库、条目
    │   └── search.ts               # 检索
    ├── mocks/
    │   ├── index.ts                # MSW 启动逻辑
    │   ├── browser.ts              # MSW worker setup
    │   ├── handlers/
    │   │   ├── index.ts            # 汇总所有 handler
    │   │   ├── auth.ts
    │   │   ├── knowledge-base.ts
    │   │   ├── document.ts
    │   │   ├── faq.ts
    │   │   └── search.ts
    │   └── data/
    │       ├── users.ts
    │       ├── knowledge-bases.ts
    │       ├── documents.ts
    │       ├── segments.ts
    │       ├── faq-entries.ts
    │       └── search-results.ts
    ├── types/
    │   ├── api.ts                  # 通用响应封装、分页
    │   ├── user.ts
    │   ├── knowledge-base.ts
    │   ├── document.ts
    │   ├── faq.ts
    │   └── search.ts
    ├── layouts/
    │   └── AppLayout.vue           # 整体布局：sidebar + header + content
    ├── components/
    │   ├── layout/
    │   │   ├── Sidebar.vue         # 左侧导航
    │   │   ├── Header.vue          # 顶栏：折叠按钮 + 面包屑 + 用户下拉
    │   │   └── Breadcrumb.vue      # 面包屑
    │   ├── kb/
    │   │   ├── KbCard.vue          # 知识库卡片
    │   │   ├── DirectoryTree.vue   # 目录树
    │   │   └── KbCreateDialog.vue  # 创建/编辑知识库弹窗
    │   ├── document/
    │   │   ├── UploadDialog.vue    # 文档上传弹窗
    │   │   └── SegmentList.vue     # 切片列表
    │   ├── faq/
    │   │   ├── FaqEntryDialog.vue  # Q&A 编辑弹窗
    │   │   └── FaqImportDialog.vue # 批量导入弹窗
    │   └── common/
    │       ├── StatusTag.vue       # 状态标签
    │       ├── PageContainer.vue   # 页面容器（标题+操作区+内容）
    │       └── SearchTraceDrawer.vue # 溯源抽屉
    ├── views/
    │   ├── login/index.vue
    │   ├── dashboard/index.vue
    │   ├── knowledge-base/
    │   │   ├── index.vue           # 卡片概览
    │   │   ├── detail.vue          # 文档列表 + 目录树
    │   │   └── document-preview.vue # 切片预览
    │   ├── faq/
    │   │   ├── index.vue           # FAQ 知识库列表
    │   │   └── detail.vue          # 问答明细
    │   ├── search/index.vue        # 统一检索
    │   └── admin/
    │       ├── users.vue
    │       └── api-keys.vue
    ├── utils/
    │   ├── format.ts               # 日期、文件大小格式化
    │   └── download.ts             # 下载辅助
    └── styles/
        ├── variables.scss          # Element Plus 主题变量
        └── global.scss             # 全局样式
```

---

### Task 1: 项目脚手架与基础配置

**Files:**
- Create: `web/package.json`
- Create: `web/vite.config.ts`
- Create: `web/tsconfig.json`
- Create: `web/tsconfig.node.json`
- Create: `web/index.html`
- Create: `web/env.d.ts`
- Create: `web/.env.development`
- Create: `web/.env.production`
- Create: `web/src/main.ts`
- Create: `web/src/App.vue`
- Create: `web/src/styles/variables.scss`
- Create: `web/src/styles/global.scss`
- Create: `web/.gitignore`

**Interfaces:**
- Consumes: nothing
- Produces: 可运行的 Vite + Vue 3 + TS + Element Plus 空项目，`pnpm dev` 启动后显示空白页

- [ ] **Step 1: 初始化项目目录与 package.json**

Create `web/package.json`:
```json
{
  "name": "kb-web",
  "version": "0.1.0",
  "private": true,
  "type": "module",
  "scripts": {
    "dev": "vite",
    "build": "vue-tsc -b && vite build",
    "preview": "vite preview",
    "test": "vitest",
    "test:run": "vitest run",
    "type-check": "vue-tsc --noEmit"
  },
  "dependencies": {
    "vue": "^3.4.21",
    "vue-router": "^4.3.0",
    "pinia": "^2.1.7",
    "element-plus": "^2.7.0",
    "@element-plus/icons-vue": "^2.3.1",
    "axios": "^1.6.8"
  },
  "devDependencies": {
    "@vitejs/plugin-vue": "^5.0.4",
    "typescript": "~5.4.0",
    "vite": "^5.2.0",
    "vue-tsc": "^2.0.6",
    "sass": "^1.75.0",
    "unplugin-auto-import": "^0.17.5",
    "unplugin-vue-components": "^0.26.0",
    "vitest": "^1.5.0",
    "@vue/test-utils": "^2.4.5",
    "jsdom": "^24.0.0",
    "msw": "^2.2.0"
  }
}
```

- [ ] **Step 2: 创建 Vite 配置**

Create `web/vite.config.ts`:
```typescript
import { defineConfig } from 'vite'
import vue from '@vitejs/plugin-vue'
import AutoImport from 'unplugin-auto-import/vite'
import Components from 'unplugin-vue-components/vite'
import { ElementPlusResolver } from 'unplugin-vue-components/resolvers'
import { fileURLToPath, URL } from 'node:url'

export default defineConfig({
  plugins: [
    vue(),
    AutoImport({
      resolvers: [ElementPlusResolver()],
      imports: ['vue', 'vue-router', 'pinia'],
      dts: 'src/auto-imports.d.ts',
    }),
    Components({
      resolvers: [ElementPlusResolver()],
      dts: 'src/components.d.ts',
    }),
  ],
  resolve: {
    alias: {
      '@': fileURLToPath(new URL('./src', import.meta.url)),
    },
  },
  server: {
    port: 3000,
    host: true,
  },
  css: {
    preprocessorOptions: {
      scss: {
        additionalData: `@use "@/styles/variables.scss" as *;`,
      },
    },
  },
  test: {
    environment: 'jsdom',
    globals: true,
  },
})
```

- [ ] **Step 3: 创建 TypeScript 配置**

Create `web/tsconfig.json`:
```json
{
  "compilerOptions": {
    "target": "ES2020",
    "useDefineForClassFields": true,
    "module": "ESNext",
    "lib": ["ES2020", "DOM", "DOM.Iterable"],
    "skipLibCheck": true,
    "moduleResolution": "bundler",
    "allowImportingTsExtensions": true,
    "resolveJsonModule": true,
    "isolatedModules": true,
    "noEmit": true,
    "jsx": "preserve",
    "strict": true,
    "noUnusedLocals": true,
    "noUnusedParameters": true,
    "noFallthroughCasesInSwitch": true,
    "baseUrl": ".",
    "paths": {
      "@/*": ["./src/*"]
    }
  },
  "include": ["src/**/*.ts", "src/**/*.d.ts", "src/**/*.tsx", "src/**/*.vue"],
  "references": [{ "path": "./tsconfig.node.json" }]
}
```

Create `web/tsconfig.node.json`:
```json
{
  "compilerOptions": {
    "composite": true,
    "skipLibCheck": true,
    "module": "ESNext",
    "moduleResolution": "bundler",
    "allowSyntheticDefaultImports": true
  },
  "include": ["vite.config.ts"]
}
```

- [ ] **Step 4: 创建环境变量与入口文件**

Create `web/.env.development`:
```
VITE_USE_MOCK=true
VITE_API_BASE_URL=/api/v1
```

Create `web/.env.production`:
```
VITE_USE_MOCK=false
VITE_API_BASE_URL=/api/v1
```

Create `web/index.html`:
```html
<!DOCTYPE html>
<html lang="zh-CN">
  <head>
    <meta charset="UTF-8" />
    <link rel="icon" type="image/svg+xml" href="/vite.svg" />
    <meta name="viewport" content="width=device-width, initial-scale=1.0" />
    <title>知识库管理平台</title>
  </head>
  <body>
    <div id="app"></div>
    <script type="module" src="/src/main.ts"></script>
  </body>
</html>
```

Create `web/env.d.ts`:
```typescript
/// <reference types="vite/client" />

interface ImportMetaEnv {
  readonly VITE_USE_MOCK: string
  readonly VITE_API_BASE_URL: string
}

interface ImportMeta {
  readonly env: ImportMetaEnv
}

declare module '*.vue' {
  import type { DefineComponent } from 'vue'
  const component: DefineComponent<{}, {}, any>
  export default component
}
```

Create `web/src/styles/variables.scss`:
```scss
// Element Plus 主题变量覆盖（参考截图配色）
$--color-primary: #409EFF;

// 覆盖 Element Plus 菜单暗色背景
$--menu-dark-bg-color: #263445;
```

Create `web/src/styles/global.scss`:
```scss
html, body, #app {
  height: 100%;
  margin: 0;
  padding: 0;
}

body {
  font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, 'Helvetica Neue', Arial, 'PingFang SC', 'Microsoft YaHei', sans-serif;
  background-color: #f5f7fa;
  color: #303133;
}

* {
  box-sizing: border-box;
}
```

Create `web/src/App.vue`:
```vue
<script setup lang="ts">
</script>

<template>
  <router-view />
</template>
```

Create `web/src/main.ts`:
```typescript
import { createApp } from 'vue'
import { createPinia } from 'pinia'
import ElementPlus from 'element-plus'
import 'element-plus/dist/index.css'
import zhCn from 'element-plus/es/locale/lang/zh-cn'
import * as ElementPlusIconsVue from '@element-plus/icons-vue'
import App from './App.vue'
import router from './router'
import './styles/global.scss'

const app = createApp(App)

for (const [key, component] of Object.entries(ElementPlusIconsVue)) {
  app.component(key, component)
}

app.use(createPinia())
app.use(router)
app.use(ElementPlus, { locale: zhCn })

app.mount('#app')
```

Create `web/.gitignore`:
```
node_modules
dist
dist-ssr
*.local
.DS_Store
src/auto-imports.d.ts
src/components.d.ts
```

- [ ] **Step 5: 安装依赖并启动验证**

Run:
```bash
cd /Users/hjx/Documents/01_Project/knowledge-base/web
pnpm install
pnpm dev
```
Expected: dev server 在 http://localhost:3000 启动，浏览器打开显示空白页（因为 router 尚未定义，会报路由警告，属正常）。按 Ctrl+C 停止。

- [ ] **Step 6: Commit**

```bash
cd /Users/hjx/Documents/01_Project/knowledge-base
git add web/
git commit -m "feat: scaffold Vue 3 + Element Plus + Vite project"
```

---

### Task 2: 路由、Pinia Store 与 Axios + MSW 基础

**Files:**
- Create: `web/src/types/api.ts`
- Create: `web/src/types/user.ts`
- Create: `web/src/api/request.ts`
- Create: `web/src/stores/user.ts`
- Create: `web/src/stores/app.ts`
- Create: `web/src/router/index.ts`
- Create: `web/src/mocks/browser.ts`
- Create: `web/src/mocks/index.ts`
- Create: `web/src/mocks/handlers/index.ts`
- Create: `web/src/mocks/handlers/auth.ts`
- Create: `web/src/mocks/data/users.ts`

**Interfaces:**
- Consumes: Task 1 的 Vite 项目
- Produces: `request<T>(config)` 函数、`useUserStore`、`useAppStore`、router（含登录守卫）、MSW mock 基础设施

- [ ] **Step 1: 定义通用 API 类型**

Create `web/src/types/api.ts`:
```typescript
export interface ApiResponse<T> {
  code: number
  message: string
  data: T
}

export interface PageResult<T> {
  items: T[]
  total: number
  page: number
  size: number
}

export interface PageQuery {
  page?: number
  size?: number
}
```

- [ ] **Step 2: 定义用户类型**

Create `web/src/types/user.ts`:
```typescript
export type UserRole = 'super_admin' | 'admin' | 'editor' | 'viewer'

export interface UserInfo {
  id: string
  username: string
  email: string
  role: UserRole
  is_active: boolean
  created_at: string
}

export interface LoginRequest {
  username: string
  password: string
}

export interface LoginResponse {
  access_token: string
  token_type: string
  user: UserInfo
}

export interface ApiKey {
  id: string
  name: string
  key_prefix: string
  is_active: boolean
  last_used_at: string | null
  created_at: string
}

export interface ApiKeyCreated extends ApiKey {
  raw_key: string
}
```

- [ ] **Step 3: 创建 Axios 实例与拦截器**

Create `web/src/api/request.ts`:
```typescript
import axios, { type AxiosInstance, type InternalAxiosRequestConfig } from 'axios'
import { ElMessage } from 'element-plus'
import { useUserStore } from '@/stores/user'

const service: AxiosInstance = axios.create({
  baseURL: import.meta.env.VITE_API_BASE_URL,
  timeout: 30000,
})

service.interceptors.request.use(
  (config: InternalAxiosRequestConfig) => {
    const userStore = useUserStore()
    if (userStore.token) {
      config.headers.Authorization = `Bearer ${userStore.token}`
    }
    return config
  },
  (error) => Promise.reject(error),
)

service.interceptors.response.use(
  (response) => response.data,
  (error) => {
    const message = error.response?.data?.message || error.message || '请求失败'
    if (error.response?.status === 401) {
      const userStore = useUserStore()
      userStore.logout()
      window.location.href = '/login'
    } else {
      ElMessage.error(message)
    }
    return Promise.reject(error)
  },
)

export default service
```

- [ ] **Step 4: 创建 Pinia stores**

Create `web/src/stores/app.ts`:
```typescript
import { defineStore } from 'pinia'
import { ref } from 'vue'

export const useAppStore = defineStore('app', () => {
  const sidebarCollapsed = ref(false)

  function toggleSidebar() {
    sidebarCollapsed.value = !sidebarCollapsed.value
  }

  return { sidebarCollapsed, toggleSidebar }
})
```

Create `web/src/stores/user.ts`:
```typescript
import { defineStore } from 'pinia'
import { ref } from 'vue'
import type { UserInfo, LoginRequest, LoginResponse } from '@/types/user'
import { login as loginApi, getUserInfo } from '@/api/auth'

export const useUserStore = defineStore('user', () => {
  const token = ref<string>(localStorage.getItem('kb_token') || '')
  const userInfo = ref<UserInfo | null>(null)

  function setToken(t: string) {
    token.value = t
    localStorage.setItem('kb_token', t)
  }

  async function login(payload: LoginRequest) {
    const res: LoginResponse = await loginApi(payload)
    setToken(res.access_token)
    userInfo.value = res.user
    localStorage.setItem('kb_user', JSON.stringify(res.user))
    return res
  }

  async function fetchUserInfo() {
    const res = await getUserInfo()
    userInfo.value = res
    localStorage.setItem('kb_user', JSON.stringify(res))
    return res
  }

  function logout() {
    token.value = ''
    userInfo.value = null
    localStorage.removeItem('kb_token')
    localStorage.removeItem('kb_user')
  }

  function restoreUser() {
    const cached = localStorage.getItem('kb_user')
    if (cached) {
      userInfo.value = JSON.parse(cached)
    }
  }

  return { token, userInfo, setToken, login, fetchUserInfo, logout, restoreUser }
})
```

- [ ] **Step 5: 创建 auth API 函数（占位，Task 2 实际写入）**

Create `web/src/api/auth.ts`:
```typescript
import request from './request'
import type { UserInfo, LoginRequest, LoginResponse, ApiKey, ApiKeyCreated } from '@/types/user'

export function login(data: LoginRequest) {
  return request.post<unknown, LoginResponse>('/auth/login', data)
}

export function getUserInfo() {
  return request.get<unknown, UserInfo>('/users/me')
}

export function getApiKeys() {
  return request.get<unknown, ApiKey[]>('/auth/api-keys')
}

export function createApiKey(name: string) {
  return request.post<unknown, ApiKeyCreated>('/auth/api-keys', { name })
}

export function deleteApiKey(id: string) {
  return request.delete<unknown, void>(`/auth/api-keys/${id}`)
}
```

- [ ] **Step 6: 创建路由与守卫**

Create `web/src/router/index.ts`:
```typescript
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
```

- [ ] **Step 7: 创建 MSW 基础设施与 auth handler**

Create `web/src/mocks/browser.ts`:
```typescript
import { setupWorker } from 'msw/browser'
import { handlers } from './handlers'

export const worker = setupWorker(...handlers)
```

Create `web/src/mocks/index.ts`:
```typescript
export async function setupMock() {
  if (import.meta.env.VITE_USE_MOCK === 'true') {
    const { worker } = await import('./browser')
    await worker.start({
      onUnhandledRequest: 'bypass',
      serviceWorker: { url: `${import.meta.env.BASE_URL}mockServiceWorker.js` },
    })
  }
}
```

Create `web/src/mocks/handlers/index.ts`:
```typescript
import { authHandlers } from './auth'
import { kbHandlers } from './knowledge-base'
import { documentHandlers } from './document'
import { faqHandlers } from './faq'
import { searchHandlers } from './search'

export const handlers = [
  ...authHandlers,
  ...kbHandlers,
  ...documentHandlers,
  ...faqHandlers,
  ...searchHandlers,
]
```

- [ ] **Step 8: 创建 mock 用户数据与 auth handler**

Create `web/src/mocks/data/users.ts`:
```typescript
import type { UserInfo, ApiKey } from '@/types/user'

export const mockUsers: UserInfo[] = [
  {
    id: 'u-001',
    username: 'admin',
    email: 'admin@kb.com',
    role: 'super_admin',
    is_active: true,
    created_at: '2026-06-01T08:00:00Z',
  },
  {
    id: 'u-002',
    username: 'editor',
    email: 'editor@kb.com',
    role: 'editor',
    is_active: true,
    created_at: '2026-06-15T08:00:00Z',
  },
]

export const mockApiKeys: ApiKey[] = [
  {
    id: 'k-001',
    name: '生产环境调用',
    key_prefix: 'kb-a1b2c3',
    is_active: true,
    last_used_at: '2026-07-28T10:00:00Z',
    created_at: '2026-07-01T08:00:00Z',
  },
  {
    id: 'k-002',
    name: '测试环境',
    key_prefix: 'kb-d4e5f6',
    is_active: false,
    last_used_at: null,
    created_at: '2026-07-20T08:00:00Z',
  },
]
```

Create `web/src/mocks/handlers/auth.ts`:
```typescript
import { http, HttpResponse } from 'msw'
import { mockUsers, mockApiKeys } from '../data/users'

const base = '/api/v1'

export const authHandlers = [
  http.post(`${base}/auth/login`, async ({ request }) => {
    const body = (await request.json()) as { username: string; password: string }
    const user = mockUsers.find((u) => u.username === body.username)
    if (!user) {
      return HttpResponse.json({ code: 401, message: '用户名或密码错误', data: null }, { status: 401 })
    }
    return HttpResponse.json({
      access_token: 'mock-jwt-token-' + user.id,
      token_type: 'bearer',
      user,
    })
  }),

  http.get(`${base}/users/me`, ({ request }) => {
    const auth = request.headers.get('Authorization') || ''
    const id = auth.replace('mock-jwt-token-', '')
    const user = mockUsers.find((u) => u.id === id) || mockUsers[0]
    return HttpResponse.json(user)
  }),

  http.get(`${base}/auth/api-keys`, () => {
    return HttpResponse.json(mockApiKeys)
  }),

  http.post(`${base}/auth/api-keys`, async ({ request }) => {
    const body = (await request.json()) as { name: string }
    const newKey = {
      id: 'k-' + Date.now(),
      name: body.name,
      key_prefix: 'kb-' + Math.random().toString(36).slice(2, 8),
      is_active: true,
      last_used_at: null,
      created_at: new Date().toISOString(),
      raw_key: 'kb-' + Math.random().toString(36).slice(2, 14) + Math.random().toString(36).slice(2, 14),
    }
    return HttpResponse.json(newKey)
  }),

  http.delete(`${base}/auth/api-keys/:id`, ({ params }) => {
    const idx = mockApiKeys.findIndex((k) => k.id === params.id)
    if (idx >= 0) mockApiKeys.splice(idx, 1)
    return HttpResponse.json(null, { status: 204 })
  }),
]
```

- [ ] **Step 9: 创建临时占位视图（让路由能渲染）**

Create the following minimal placeholder views so `pnpm dev` does not error. Each is a minimal component:

`web/src/views/login/index.vue`:
```vue
<script setup lang="ts">
</script>
<template>
  <div class="login-placeholder">登录页占位</div>
</template>
<style scoped>
.login-placeholder { display: flex; align-items: center; justify-content: center; height: 100vh; font-size: 24px; }
</style>
```

Create the same minimal placeholder for: `web/src/views/dashboard/index.vue`, `web/src/views/knowledge-base/index.vue`, `web/src/views/knowledge-base/detail.vue`, `web/src/views/knowledge-base/document-preview.vue`, `web/src/views/faq/index.vue`, `web/src/views/faq/detail.vue`, `web/src/views/search/index.vue`, `web/src/views/admin/users.vue`, `web/src/views/admin/api-keys.vue`. Each contains:
```vue
<template>
  <div style="padding: 40px;">{{ pageTitle }}占位</div>
</template>
<script setup lang="ts">
const pageTitle = '页面'
</script>
```

- [ ] **Step 10: 创建 AppLayout 占位**

Create `web/src/layouts/AppLayout.vue` (minimal, Task 3 will flesh it out):
```vue
<script setup lang="ts">
</script>
<template>
  <router-view />
</template>
```

- [ ] **Step 11: 在 main.ts 启用 MSW 并安装 worker**

Update `web/src/main.ts` to await MSW setup before mounting. Modify the end of the file:
```typescript
import { setupMock } from './mocks'

async function bootstrap() {
  await setupMock()
  const app = createApp(App)
  for (const [key, component] of Object.entries(ElementPlusIconsVue)) {
    app.component(key, component)
  }
  app.use(createPinia())
  app.use(router)
  app.use(ElementPlus, { locale: zhCn })
  app.mount('#app')
}

bootstrap()
```

Generate the MSW service worker file:
```bash
cd /Users/hjx/Documents/01_Project/knowledge-base/web
pnpm msw init public/ --save
```

- [ ] **Step 12: 编写路由守卫单元测试**

Create `web/src/stores/__tests__/user.test.ts`:
```typescript
import { setActivePinia, createPinia } from 'pinia'
import { useUserStore } from '../user'

describe('useUserStore', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    localStorage.clear()
  })

  it('初始状态 token 为空', () => {
    const store = useUserStore()
    expect(store.token).toBe('')
    expect(store.userInfo).toBeNull()
  })

  it('setToken 持久化到 localStorage', () => {
    const store = useUserStore()
    store.setToken('abc123')
    expect(store.token).toBe('abc123')
    expect(localStorage.getItem('kb_token')).toBe('abc123')
  })

  it('logout 清除 token 和用户信息', () => {
    const store = useUserStore()
    store.setToken('abc123')
    store.userInfo = { id: '1', username: 'a', email: 'a@b.c', role: 'admin', is_active: true, created_at: '' }
    store.logout()
    expect(store.token).toBe('')
    expect(store.userInfo).toBeNull()
    expect(localStorage.getItem('kb_token')).toBeNull()
  })
})
```

- [ ] **Step 13: 运行测试验证**

Run:
```bash
cd /Users/hjx/Documents/01_Project/knowledge-base/web
pnpm test:run -- src/stores/__tests__/user.test.ts
```
Expected: 3 tests passed

- [ ] **Step 14: 启动 dev 验证 MSW 与路由**

Run:
```bash
pnpm dev
```
Expected: 打开 http://localhost:3000，未带 token 自动跳转 `/login`，显示「登录页占位」。停止 dev server。

- [ ] **Step 15: Commit**

```bash
cd /Users/hjx/Documents/01_Project/knowledge-base
git add web/
git commit -m "feat: add router, pinia stores, axios+msw api layer with auth mock"
```

---

### Task 3: 布局框架（侧边栏 + 顶栏 + 面包屑）

**Files:**
- Modify: `web/src/layouts/AppLayout.vue`
- Create: `web/src/components/layout/Sidebar.vue`
- Create: `web/src/components/layout/Header.vue`
- Create: `web/src/components/layout/Breadcrumb.vue`
- Create: `web/src/components/common/PageContainer.vue`
- Create: `web/src/components/common/StatusTag.vue`
- Create: `web/src/utils/format.ts`
- Modify: `web/src/router/index.ts`（为路由 meta 增加 icon）

**Interfaces:**
- Consumes: Task 2 的 router、useAppStore、useUserStore
- Produces: `AppLayout`（三段式布局）、`PageContainer`（页面容器）、`StatusTag`（状态标签）、`formatDate/formatFileSize` 工具函数

> 目标：对齐所有参考截图共有的布局——左侧深色导航栏（220px，可折叠到 64px），顶部白色 header（折叠按钮 + 面包屑 + 右侧用户头像下拉），内容区浅灰背景。

- [ ] **Step 1: 创建格式化工具函数**

Create `web/src/utils/format.ts`:
```typescript
export function formatDate(value: string | null | undefined): string {
  if (!value) return '-'
  const d = new Date(value)
  if (isNaN(d.getTime())) return '-'
  const pad = (n: number) => String(n).padStart(2, '0')
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())} ${pad(d.getHours())}:${pad(d.getMinutes())}`
}

export function formatFileSize(bytes: number | null | undefined): string {
  if (bytes == null) return '-'
  if (bytes < 1024) return `${bytes} B`
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`
  if (bytes < 1024 * 1024 * 1024) return `${(bytes / 1024 / 1024).toFixed(1)} MB`
  return `${(bytes / 1024 / 1024 / 1024).toFixed(1)} GB`
}

export function formatNumber(n: number): string {
  return n.toLocaleString('zh-CN')
}
```

- [ ] **Step 2: 创建 StatusTag 组件**

Create `web/src/components/common/StatusTag.vue`:
```vue
<script setup lang="ts">
import { computed } from 'vue'

const props = defineProps<{ status: string }>()

const statusMap: Record<string, { type: 'success' | 'warning' | 'danger' | 'info'; text: string }> = {
  COMPLETED: { type: 'success', text: '已完成' },
  INDEXED: { type: 'success', text: '已索引' },
  PENDING: { type: 'info', text: '等待中' },
  QUEUED: { type: 'info', text: '排队中' },
  DRAFT: { type: 'info', text: '草稿' },
  PARSING: { type: 'warning', text: '解析中' },
  CHUNKING: { type: 'warning', text: '切片中' },
  EMBEDDING: { type: 'warning', text: '向量化中' },
  INDEXING: { type: 'warning', text: '索引中' },
  PROCESSING: { type: 'warning', text: '处理中' },
  FAILED: { type: 'danger', text: '失败' },
}

const config = computed(() => statusMap[props.status] || { type: 'info' as const, text: props.status })
</script>

<template>
  <el-tag :type="config.type" size="small" effect="light">{{ config.text }}</el-tag>
</template>
```

- [ ] **Step 3: 创建 PageContainer 组件**

Create `web/src/components/common/PageContainer.vue`:
```vue
<script setup lang="ts">
defineProps<{
  title?: string
}>()
</script>

<template>
  <div class="page-container">
    <div v-if="title || $slots.actions" class="page-header">
      <div class="page-title">{{ title }}</div>
      <div class="page-actions">
        <slot name="actions" />
      </div>
    </div>
    <div class="page-content">
      <slot />
    </div>
  </div>
</template>

<style scoped>
.page-container {
  padding: 20px;
}
.page-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 16px;
}
.page-title {
  font-size: 18px;
  font-weight: 600;
  color: #303133;
}
.page-content {
  background: #fff;
  border-radius: 4px;
  padding: 20px;
}
</style>
```

- [ ] **Step 4: 为路由增加 icon meta**

Modify `web/src/router/index.ts`：为每个需要显示在侧边栏的路由增加 `meta.icon`（Element Plus 图标组件名）。更新 children 数组中各路由的 meta：

Dashboard: `meta: { title: '工作台', icon: 'Odometer' }`
KnowledgeBases: `meta: { title: '知识库', icon: 'Collection' }`
FaqList: `meta: { title: '问答库', icon: 'ChatDotRound' }`
Search: `meta: { title: '统一检索', icon: 'Search' }`
AdminUsers: `meta: { title: '用户管理', icon: 'User', roles: ['super_admin', 'admin'] }`
AdminApiKeys: `meta: { title: 'API Key 管理', icon: 'Key' }`

详情页（KnowledgeBaseDetail、DocumentPreview、FaqDetail）不设 icon，不显示在侧边栏（通过 `meta.hidden: true` 标记）。

- [ ] **Step 5: 创建 Sidebar 组件**

Create `web/src/components/layout/Sidebar.vue`:
```vue
<script setup lang="ts">
import { useRoute, useRouter } from 'vue-router'
import { useAppStore } from '@/stores/app'
import * as Icons from '@element-plus/icons-vue'
import { computed } from 'vue'

const route = useRoute()
const router = useRouter()
const appStore = useAppStore()

const menuItems = computed(() =>
  router.getRoutes().filter(
    (r) => r.meta?.title && !r.meta?.hidden && r.name,
  ),
)

function isActive(path: string): boolean {
  return route.path === path || route.path.startsWith(path + '/')
}
</script>

<template>
  <div class="sidebar" :class="{ collapsed: appStore.sidebarCollapsed }">
    <div class="logo">
      <el-icon size="24" color="#fff"><Icons.Reading /></el-icon>
      <span v-show="!appStore.sidebarCollapsed" class="logo-text">知识库</span>
    </div>
    <el-menu
      :default-active="route.path"
      :collapse="appStore.sidebarCollapsed"
      background-color="#263445"
      text-color="#bfcbd9"
      active-text-color="#409EFF"
      router
    >
      <el-menu-item
        v-for="item in menuItems"
        :key="item.path"
        :index="item.path"
      >
        <el-icon><component :is="(Icons as any)[item.meta!.icon]" /></el-icon>
        <template #title>{{ item.meta!.title }}</template>
      </el-menu-item>
    </el-menu>
  </div>
</template>

<style scoped>
.sidebar {
  width: 220px;
  background: #263445;
  transition: width 0.3s;
  overflow: hidden;
}
.sidebar.collapsed {
  width: 64px;
}
.logo {
  height: 60px;
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 8px;
  color: #fff;
}
.logo-text {
  font-size: 18px;
  font-weight: 600;
  white-space: nowrap;
}
:deep(.el-menu) {
  border-right: none;
}
</style>
```

- [ ] **Step 6: 创建 Breadcrumb 组件**

Create `web/src/components/layout/Breadcrumb.vue`:
```vue
<script setup lang="ts">
import { useRoute } from 'vue-router'
import { computed } from 'vue'

const route = useRoute()

const crumbs = computed(() => {
  const matched = route.matched.filter((r) => r.meta?.title)
  return matched.map((r) => r.meta!.title as string)
})
</script>

<template>
  <el-breadcrumb separator="/">
    <el-breadcrumb-item v-for="(crumb, i) in crumbs" :key="i">{{ crumb }}</el-breadcrumb-item>
  </el-breadcrumb>
</template>
```

- [ ] **Step 7: 创建 Header 组件**

Create `web/src/components/layout/Header.vue`:
```vue
<script setup lang="ts">
import { useAppStore } from '@/stores/app'
import { useUserStore } from '@/stores/user'
import { useRouter } from 'vue-router'
import { Expand, Fold, ArrowDown } from '@element-plus/icons-vue'
import Breadcrumb from './Breadcrumb.vue'

const appStore = useAppStore()
const userStore = useUserStore()
const router = useRouter()

function handleCommand(command: string) {
  if (command === 'logout') {
    userStore.logout()
    router.push('/login')
  }
}
</script>

<template>
  <div class="header">
    <div class="header-left">
      <el-icon class="collapse-btn" size="20" @click="appStore.toggleSidebar()">
        <Fold v-if="!appStore.sidebarCollapsed" />
        <Expand v-else />
      </el-icon>
      <Breadcrumb />
    </div>
    <div class="header-right">
      <el-dropdown @command="handleCommand">
        <span class="user-info">
          <el-avatar :size="32" icon="UserFilled" />
          <span class="username">{{ userStore.userInfo?.username || '用户' }}</span>
          <el-icon><ArrowDown /></el-icon>
        </span>
        <template #dropdown>
          <el-dropdown-menu>
            <el-dropdown-item command="logout">退出登录</el-dropdown-item>
          </el-dropdown-menu>
        </template>
      </el-dropdown>
    </div>
  </div>
</template>

<style scoped>
.header {
  height: 60px;
  background: #fff;
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 0 20px;
  border-bottom: 1px solid #e6e6e6;
}
.header-left {
  display: flex;
  align-items: center;
  gap: 16px;
}
.collapse-btn {
  cursor: pointer;
}
.user-info {
  display: flex;
  align-items: center;
  gap: 8px;
  cursor: pointer;
}
.username {
  font-size: 14px;
}
</style>
```

- [ ] **Step 8: 实现 AppLayout 三段式布局**

Replace `web/src/layouts/AppLayout.vue`:
```vue
<script setup lang="ts">
import Sidebar from '@/components/layout/Sidebar.vue'
import Header from '@/components/layout/Header.vue'
</script>

<template>
  <div class="app-layout">
    <Sidebar />
    <div class="main-section">
      <Header />
      <div class="content-area">
        <router-view />
      </div>
    </div>
  </div>
</template>

<style scoped>
.app-layout {
  display: flex;
  height: 100vh;
}
.main-section {
  flex: 1;
  display: flex;
  flex-direction: column;
  overflow: hidden;
}
.content-area {
  flex: 1;
  overflow-y: auto;
  background: #f5f7fa;
}
</style>
```

- [ ] **Step 9: 视觉验证**

Run:
```bash
cd /Users/hjx/Documents/01_Project/knowledge-base/web
pnpm dev
```
Expected:
1. 浏览器打开 http://localhost:3000，跳转 `/login`（占位页）
2. 在地址栏手动改为 http://localhost:3000/dashboard —— 因无 token 会跳回 login。临时绕过：在浏览器 Console 执行 `localStorage.setItem('kb_token','mock-jwt-token-u-001'); localStorage.setItem('kb_user',JSON.stringify({id:'u-001',username:'admin',email:'a@b.c',role:'super_admin',is_active:true,created_at:''}))`，刷新后进入 dashboard
3. 确认看到左侧深色导航栏（工作台/知识库/问答库/统一检索/用户管理/API Key 管理）、顶部 header（折叠按钮 + 面包屑「工作台」+ 用户头像下拉）、浅灰内容区
4. 点击折叠按钮，侧边栏收起到 64px，再点展开
5. 对照参考截图确认布局一致，停止 dev server

- [ ] **Step 10: Commit**

```bash
cd /Users/hjx/Documents/01_Project/knowledge-base
git add web/
git commit -m "feat: implement app layout with sidebar, header, breadcrumb"
```

---

### Task 4: 登录页

**Files:**
- Modify: `web/src/views/login/index.vue`

**Interfaces:**
- Consumes: `useUserStore().login(username, password)`、router
- Produces: 登录页，输入用户名密码后跳转 dashboard

> 注意：mock 环境下用户名 `admin` 或 `editor`，密码任意非空字符串即可登录成功。

- [ ] **Step 1: 实现登录页**

Replace `web/src/views/login/index.vue`:
```vue
<script setup lang="ts">
import { reactive, ref } from 'vue'
import { useRouter } from 'vue-router'
import { useUserStore } from '@/stores/user'
import { ElMessage, type FormInstance, type FormRules } from 'element-plus'
import { User, Lock } from '@element-plus/icons-vue'

const router = useRouter()
const userStore = useUserStore()

const formRef = ref<FormInstance>()
const loading = ref(false)
const form = reactive({
  username: '',
  password: '',
})

const rules: FormRules = {
  username: [{ required: true, message: '请输入用户名', trigger: 'blur' }],
  password: [{ required: true, message: '请输入密码', trigger: 'blur' }],
}

async function handleLogin() {
  if (!formRef.value) return
  await formRef.value.validate(async (valid) => {
    if (!valid) return
    loading.value = true
    try {
      await userStore.login(form)
      ElMessage.success('登录成功')
      router.push('/dashboard')
    } catch {
      // 拦截器已处理错误提示
    } finally {
      loading.value = false
    }
  })
}
</script>

<template>
  <div class="login-page">
    <div class="login-card">
      <div class="login-header">
        <el-icon size="40" color="#409EFF"><Reading /></el-icon>
        <h2>知识库管理平台</h2>
      </div>
      <el-form
        ref="formRef"
        :model="form"
        :rules="rules"
        size="large"
        @keyup.enter="handleLogin"
      >
        <el-form-item prop="username">
          <el-input v-model="form.username" placeholder="用户名" :prefix-icon="User" />
        </el-form-item>
        <el-form-item prop="password">
          <el-input v-model="form.password" type="password" show-password placeholder="密码" :prefix-icon="Lock" />
        </el-form-item>
        <el-form-item>
          <el-button type="primary" :loading="loading" style="width: 100%" @click="handleLogin">
            登录
          </el-button>
        </el-form-item>
      </el-form>
      <div class="login-tip">Mock 模式：用户名 admin / editor，密码任意</div>
    </div>
  </div>
</template>

<style scoped>
.login-page {
  height: 100vh;
  display: flex;
  align-items: center;
  justify-content: center;
  background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
}
.login-card {
  width: 400px;
  padding: 40px;
  background: #fff;
  border-radius: 8px;
  box-shadow: 0 8px 24px rgba(0, 0, 0, 0.15);
}
.login-header {
  text-align: center;
  margin-bottom: 30px;
}
.login-header h2 {
  margin: 12px 0 0;
  color: #303133;
}
.login-tip {
  text-align: center;
  color: #909399;
  font-size: 12px;
  margin-top: 8px;
}
</style>
```

- [ ] **Step 2: 视觉验证**

Run `pnpm dev`，打开 http://localhost:3000/login：
1. 看到渐变背景 + 白色登录卡片 + 平台标题 + 用户名/密码输入框 + 登录按钮
2. 用户名输入 `admin`，密码输入 `123`，点击登录
3. 跳转到 `/dashboard`，进入布局框架
4. 停止 dev server

- [ ] **Step 3: Commit**

```bash
cd /Users/hjx/Documents/01_Project/knowledge-base
git add web/
git commit -m "feat: implement login page with form validation"
```

---

### Task 5: 知识库与文档类型定义 + Mock 数据

**Files:**
- Create: `web/src/types/knowledge-base.ts`
- Create: `web/src/types/document.ts`
- Create: `web/src/types/search.ts`
- Create: `web/src/api/knowledge-base.ts`
- Create: `web/src/api/document.ts`
- Create: `web/src/api/search.ts`
- Create: `web/src/mocks/data/knowledge-bases.ts`
- Create: `web/src/mocks/data/documents.ts`
- Create: `web/src/mocks/data/segments.ts`
- Create: `web/src/mocks/data/search-results.ts`
- Create: `web/src/mocks/handlers/knowledge-base.ts`
- Create: `web/src/mocks/handlers/document.ts`
- Create: `web/src/mocks/handlers/search.ts`

**Interfaces:**
- Consumes: Task 2 的 request、mock 基础设施
- Produces: 全部业务类型、API 函数、mock handler（知识库/文档/检索），后续页面直接调用

- [ ] **Step 1: 定义知识库类型**

Create `web/src/types/knowledge-base.ts`:
```typescript
export type KbType = 'DOCUMENT' | 'FAQ'
export type ChunkStrategy = 'FIXED_SIZE' | 'PARAGRAPH' | 'MARKDOWN_HEADER' | 'SENTENCE'

export interface KnowledgeBase {
  id: string
  name: string
  description: string
  kb_type: KbType
  owner_id: string
  chunk_strategy: ChunkStrategy
  chunk_size: number
  chunk_overlap: number
  embedding_model: string
  es_index_name: string
  document_count?: number
  created_at: string
  updated_at: string
}

export interface KbCreateRequest {
  name: string
  description?: string
  kb_type: KbType
  chunk_strategy?: ChunkStrategy
  chunk_size?: number
  chunk_overlap?: number
}

export interface Directory {
  id: string
  kb_id: string
  parent_id: string | null
  name: string
  sort_order: number
  created_at: string
  children?: Directory[]
}
```

- [ ] **Step 2: 定义文档与切片类型**

Create `web/src/types/document.ts`:
```typescript
export type DocStatus =
  | 'PENDING' | 'PARSING' | 'CHUNKING' | 'EMBEDDING'
  | 'INDEXING' | 'COMPLETED' | 'FAILED'

export interface Document {
  id: string
  kb_id: string
  directory_id: string | null
  filename: string
  original_filename: string
  file_type: string
  file_size: number
  storage_path: string
  status: DocStatus
  chunk_count: number
  error_message: string | null
  created_at: string
  updated_at: string
}

export interface Segment {
  id: string
  document_id: string
  faq_entry_id: string | null
  es_chunk_id: string
  chunk_index: number
  content: string
  content_hash: string
  token_count: number
  embedding_dim: number | null
  created_at: string
}
```

- [ ] **Step 3: 定义检索类型**

Create `web/src/types/search.ts`:
```typescript
export type SearchType = 'hybrid' | 'semantic' | 'keyword' | 'faq'
export type SourceType = 'DOCUMENT' | 'FAQ'

export interface SearchRequest {
  query: string
  kb_ids: string[]
  top_k?: number
  search_type?: SearchType
  filters?: {
    directory_ids?: string[]
    file_types?: string[]
  }
}

export interface SearchResult {
  chunk_id: string
  text: string
  score: number
  source_type: SourceType
  document_id: string
  document_title: string
  page_number: number | null
  total_chunks: number
  directory_path: string
  source_path: string
  preview_url: string
  preview_type: string
  content_hash: string
  faq_answer: string | null
}

export interface SearchResponse {
  results: SearchResult[]
  total: number
  took_ms: number
}
```

- [ ] **Step 4: 创建知识库 API 函数**

Create `web/src/api/knowledge-base.ts`:
```typescript
import request from './request'
import type { KnowledgeBase, KbCreateRequest, Directory, KbType } from '@/types/knowledge-base'
import type { PageQuery, PageResult } from '@/types/api'

export function listKnowledgeBases(params?: PageQuery & { kb_type?: KbType }) {
  return request.get<unknown, PageResult<KnowledgeBase>>('/knowledge-bases', { params })
}

export function getKnowledgeBase(id: string) {
  return request.get<unknown, KnowledgeBase>(`/knowledge-bases/${id}`)
}

export function createKnowledgeBase(data: KbCreateRequest) {
  return request.post<unknown, KnowledgeBase>('/knowledge-bases', data)
}

export function updateKnowledgeBase(id: string, data: Partial<KbCreateRequest>) {
  return request.put<unknown, KnowledgeBase>(`/knowledge-bases/${id}`, data)
}

export function deleteKnowledgeBase(id: string) {
  return request.delete<unknown, void>(`/knowledge-bases/${id}`)
}

export function getDirectoryTree(kbId: string) {
  return request.get<unknown, Directory[]>(`/knowledge-bases/${kbId}/directories`)
}

export function createDirectory(kbId: string, data: { name: string; parent_id: string | null }) {
  return request.post<unknown, Directory>(`/knowledge-bases/${kbId}/directories`, data)
}

export function updateDirectory(id: string, data: { name?: string; parent_id?: string | null }) {
  return request.put<unknown, Directory>(`/directories/${id}`, data)
}

export function deleteDirectory(id: string) {
  return request.delete<unknown, void>(`/directories/${id}`)
}
```

- [ ] **Step 5: 创建文档 API 函数**

Create `web/src/api/document.ts`:
```typescript
import request from './request'
import type { Document, Segment, DocStatus } from '@/types/document'
import type { PageQuery, PageResult } from '@/types/api'

export function listDocuments(params: PageQuery & { kb_id: string; directory_id?: string; status?: DocStatus }) {
  return request.get<unknown, PageResult<Document>>('/documents', { params })
}

export function getDocument(id: string) {
  return request.get<unknown, Document>(`/documents/${id}`)
}

export function uploadDocument(file: File, kbId: string, directoryId?: string) {
  const formData = new FormData()
  formData.append('file', file)
  formData.append('kb_id', kbId)
  if (directoryId) formData.append('directory_id', directoryId)
  return request.post<unknown, { document_id: string; job_id: string; status: string }>('/documents/upload', formData, {
    headers: { 'Content-Type': 'multipart/form-data' },
  })
}

export function deleteDocument(id: string) {
  return request.delete<unknown, void>(`/documents/${id}`)
}

export function getDocumentPreviewUrl(id: string) {
  return request.get<unknown, { preview_url: string; preview_type: string }>(`/documents/${id}/preview`)
}

export function getDocumentSegments(id: string, params: PageQuery) {
  return request.get<unknown, PageResult<Segment>>(`/documents/${id}/segments`, { params })
}

export function reprocessDocument(id: string) {
  return request.post<unknown, void>(`/documents/${id}/reprocess`)
}
```

- [ ] **Step 6: 创建检索 API 函数**

Create `web/src/api/search.ts`:
```typescript
import request from './request'
import type { SearchRequest, SearchResponse } from '@/types/search'

export function search(data: SearchRequest) {
  return request.post<unknown, SearchResponse>('/search', data)
}

export function getTrace(chunkId: string) {
  return request.get<unknown, unknown>(`/search/trace/${chunkId}`)
}
```

- [ ] **Step 7: 创建知识库 mock 数据**

Create `web/src/mocks/data/knowledge-bases.ts`:
```typescript
import type { KnowledgeBase, Directory } from '@/types/knowledge-base'

export const mockKnowledgeBases: KnowledgeBase[] = [
  {
    id: 'kb-001',
    name: '产品技术文档库',
    description: '包含所有产品的技术说明、API 文档和架构设计',
    kb_type: 'DOCUMENT',
    owner_id: 'u-001',
    chunk_strategy: 'PARAGRAPH',
    chunk_size: 512,
    chunk_overlap: 150,
    embedding_model: 'bge-m3',
    es_index_name: 'kb_kb-001',
    document_count: 28,
    created_at: '2026-06-01T08:00:00Z',
    updated_at: '2026-07-20T10:00:00Z',
  },
  {
    id: 'kb-002',
    name: '客户常见问题库',
    description: '客户高频问题与标准答案',
    kb_type: 'DOCUMENT',
    owner_id: 'u-001',
    chunk_strategy: 'PARAGRAPH',
    chunk_size: 512,
    chunk_overlap: 150,
    embedding_model: 'bge-m3',
    es_index_name: 'kb_kb-002',
    document_count: 12,
    created_at: '2026-06-10T08:00:00Z',
    updated_at: '2026-07-25T10:00:00Z',
  },
  {
    id: 'kb-003',
    name: '运维手册',
    description: '部署、监控、故障排查手册',
    kb_type: 'DOCUMENT',
    owner_id: 'u-002',
    chunk_strategy: 'MARKDOWN_HEADER',
    chunk_size: 768,
    chunk_overlap: 200,
    embedding_model: 'bge-m3',
    es_index_name: 'kb_kb-003',
    document_count: 8,
    created_at: '2026-06-20T08:00:00Z',
    updated_at: '2026-07-22T10:00:00Z',
  },
]

export const mockDirectories: Record<string, Directory[]> = {
  'kb-001': [
    {
      id: 'dir-001', kb_id: 'kb-001', parent_id: null, name: '架构设计', sort_order: 1, created_at: '2026-06-01T08:00:00Z',
      children: [
        { id: 'dir-011', kb_id: 'kb-001', parent_id: 'dir-001', name: '微服务', sort_order: 1, created_at: '2026-06-01T08:00:00Z' },
        { id: 'dir-012', kb_id: 'kb-001', parent_id: 'dir-001', name: '数据模型', sort_order: 2, created_at: '2026-06-01T08:00:00Z' },
      ],
    },
    { id: 'dir-002', kb_id: 'kb-001', parent_id: null, name: 'API 文档', sort_order: 2, created_at: '2026-06-02T08:00:00Z' },
    { id: 'dir-003', kb_id: 'kb-001', parent_id: null, name: '认证授权', sort_order: 3, created_at: '2026-06-03T08:00:00Z' },
  ],
}
```

- [ ] **Step 8: 创建文档 mock 数据**

Create `web/src/mocks/data/documents.ts`:
```typescript
import type { Document } from '@/types/document'

const statuses = ['COMPLETED', 'COMPLETED', 'PROCESSING', 'FAILED', 'COMPLETED'] as const

export const mockDocuments: Document[] = Array.from({ length: 28 }, (_, i) => ({
  id: `doc-${String(i + 1).padStart(3, '0')}`,
  kb_id: 'kb-001',
  directory_id: i % 3 === 0 ? 'dir-001' : i % 3 === 1 ? 'dir-002' : 'dir-003',
  filename: `document_${i + 1}.pdf`,
  original_filename: `产品手册第${i + 1}章.pdf`,
  file_type: i % 4 === 0 ? 'pdf' : i % 4 === 1 ? 'docx' : i % 4 === 2 ? 'md' : 'xlsx',
  file_size: 1024 * 1024 * (1 + (i % 5)),
  storage_path: `raw-docs/doc-${i + 1}.pdf`,
  status: statuses[i % statuses.length],
  chunk_count: 10 + (i % 20),
  error_message: i % 5 === 3 ? '解析超时' : null,
  created_at: `2026-06-${String((i % 28) + 1).padStart(2, '0')}T08:00:00Z`,
  updated_at: `2026-07-${String((i % 28) + 1).padStart(2, '0')}T10:00:00Z`,
}))
```

- [ ] **Step 9: 创建切片 mock 数据**

Create `web/src/mocks/data/segments.ts`:
```typescript
import type { Segment } from '@/types/document'

export function generateMockSegments(documentId: string, count: number = 12): Segment[] {
  return Array.from({ length: count }, (_, i) => ({
    id: `${documentId}-seg-${i + 1}`,
    document_id: documentId,
    faq_entry_id: null,
    es_chunk_id: `${documentId}_chunk_${i}`,
    chunk_index: i,
    content: `这是文档 ${documentId} 的第 ${i + 1} 个切片内容。知识库系统通过将长文档切分为多个语义片段，使得检索能够精准定位到相关段落。每个切片保留上下文信息，支持溯源到原始文档的具体位置。切片大小根据配置的策略动态调整，本切片使用的策略为段落切片，最大 token 数 512，重叠 150。`,
    content_hash: `sha256:${Math.random().toString(16).slice(2, 18)}`,
    token_count: 400 + (i % 120),
    embedding_dim: 1024,
    created_at: '2026-07-20T10:00:00Z',
  }))
}
```

- [ ] **Step 10: 创建检索结果 mock 数据**

Create `web/src/mocks/data/search-results.ts`:
```typescript
import type { SearchResult } from '@/types/search'

export const mockSearchResults: SearchResult[] = [
  {
    chunk_id: 'kb-001_doc-001_chunk_3',
    text: 'OAuth2 认证流程：客户端通过授权服务器获取 access_token，每次请求在 Header 携带 Bearer Token。服务端验证 token 有效性后返回受保护资源。',
    score: 0.94,
    source_type: 'DOCUMENT',
    document_id: 'doc-001',
    document_title: '认证授权指南 v2.1.pdf',
    page_number: 12,
    total_chunks: 45,
    directory_path: '认证授权 / OAuth2',
    source_path: 'http://localhost:9000/raw-docs/doc-001.pdf',
    preview_url: 'http://localhost:8012/onlinePreview?url=encoded_doc001',
    preview_type: 'pdf',
    content_hash: 'sha256:abc123',
    faq_answer: null,
  },
  {
    chunk_id: 'kb-001_doc-005_chunk_2',
    text: 'JWT（JSON Web Token）是一种无状态的认证方案，包含 Header、Payload、Signature 三部分。服务端无需存储 session，适合微服务架构。',
    score: 0.89,
    source_type: 'DOCUMENT',
    document_id: 'doc-005',
    document_title: '微服务安全设计.pdf',
    page_number: 8,
    total_chunks: 32,
    directory_path: '架构设计 / 微服务',
    source_path: 'http://localhost:9000/raw-docs/doc-005.pdf',
    preview_url: 'http://localhost:8012/onlinePreview?url=encoded_doc005',
    preview_type: 'pdf',
    content_hash: 'sha256:def456',
    faq_answer: null,
  },
  {
    chunk_id: 'kb-002_faq-003',
    text: '如何重置密码？',
    score: 0.86,
    source_type: 'FAQ',
    document_id: '',
    document_title: '',
    page_number: null,
    total_chunks: 1,
    directory_path: '账户问题',
    source_path: '',
    preview_url: '',
    preview_type: '',
    content_hash: 'sha256:ghi789',
    faq_answer: '用户可在登录页点击「忘记密码」，输入注册邮箱后系统会发送重置链接，链接有效期为 30 分钟。点击链接即可设置新密码。',
  },
]
```

- [ ] **Step 11: 创建知识库 mock handler**

Create `web/src/mocks/handlers/knowledge-base.ts`:
```typescript
import { http, HttpResponse } from 'msw'
import { mockKnowledgeBases, mockDirectories } from '../data/knowledge-bases'
import type { KbCreateRequest } from '@/types/knowledge-base'

const base = '/api/v1'

export const kbHandlers = [
  http.get(`${base}/knowledge-bases`, ({ request }) => {
    const url = new URL(request.url)
    const kbType = url.searchParams.get('kb_type')
    let items = mockKnowledgeBases
    if (kbType) items = items.filter((k) => k.kb_type === kbType)
    return HttpResponse.json({ items, total: items.length, page: 1, size: items.length })
  }),

  http.get(`${base}/knowledge-bases/:id`, ({ params }) => {
    const kb = mockKnowledgeBases.find((k) => k.id === params.id)
    if (!kb) return HttpResponse.json({ message: '未找到' }, { status: 404 })
    return HttpResponse.json(kb)
  }),

  http.post(`${base}/knowledge-bases`, async ({ request }) => {
    const body = (await request.json()) as KbCreateRequest
    const newKb = {
      ...body,
      id: 'kb-' + Date.now(),
      owner_id: 'u-001',
      es_index_name: 'kb_kb-' + Date.now(),
      document_count: 0,
      created_at: new Date().toISOString(),
      updated_at: new Date().toISOString(),
    }
    mockKnowledgeBases.push(newKb)
    return HttpResponse.json(newKb)
  }),

  http.put(`${base}/knowledge-bases/:id`, async ({ request, params }) => {
    const body = (await request.json()) as Partial<KbCreateRequest>
    const idx = mockKnowledgeBases.findIndex((k) => k.id === params.id)
    if (idx < 0) return HttpResponse.json({ message: '未找到' }, { status: 404 })
    mockKnowledgeBases[idx] = { ...mockKnowledgeBases[idx], ...body, updated_at: new Date().toISOString() }
    return HttpResponse.json(mockKnowledgeBases[idx])
  }),

  http.delete(`${base}/knowledge-bases/:id`, ({ params }) => {
    const idx = mockKnowledgeBases.findIndex((k) => k.id === params.id)
    if (idx >= 0) mockKnowledgeBases.splice(idx, 1)
    return HttpResponse.json(null, { status: 204 })
  }),

  http.get(`${base}/knowledge-bases/:id/directories`, ({ params }) => {
    const dirs = mockDirectories[params.id as string] || []
    return HttpResponse.json(dirs)
  }),

  http.post(`${base}/knowledge-bases/:id/directories`, async ({ request, params }) => {
    const body = (await request.json()) as { name: string; parent_id: string | null }
    const newDir = {
      id: 'dir-' + Date.now(),
      kb_id: params.id as string,
      parent_id: body.parent_id,
      name: body.name,
      sort_order: 99,
      created_at: new Date().toISOString(),
    }
    if (!mockDirectories[params.id as string]) mockDirectories[params.id as string] = []
    mockDirectories[params.id as string].push(newDir)
    return HttpResponse.json(newDir)
  }),
]
```

- [ ] **Step 12: 创建文档 mock handler**

Create `web/src/mocks/handlers/document.ts`:
```typescript
import { http, HttpResponse } from 'msw'
import { mockDocuments } from '../data/documents'
import { generateMockSegments } from '../data/segments'

const base = '/api/v1'

export const documentHandlers = [
  http.get(`${base}/documents`, ({ request }) => {
    const url = new URL(request.url)
    const kbId = url.searchParams.get('kb_id')
    const page = Number(url.searchParams.get('page') || 1)
    const size = Number(url.searchParams.get('size') || 10)
    let items = mockDocuments
    if (kbId) items = items.filter((d) => d.kb_id === kbId)
    const total = items.length
    const start = (page - 1) * size
    const paged = items.slice(start, start + size)
    return HttpResponse.json({ items: paged, total, page, size })
  }),

  http.get(`${base}/documents/:id`, ({ params }) => {
    const doc = mockDocuments.find((d) => d.id === params.id)
    if (!doc) return HttpResponse.json({ message: '未找到' }, { status: 404 })
    return HttpResponse.json(doc)
  }),

  http.post(`${base}/documents/upload`, async ({ request }) => {
    const formData = await request.formData()
    const file = formData.get('file') as File
    const newDoc = {
      id: 'doc-' + Date.now(),
      kb_id: formData.get('kb_id') as string,
      directory_id: (formData.get('directory_id') as string) || null,
      filename: file.name,
      original_filename: file.name,
      file_type: file.name.split('.').pop() || 'unknown',
      file_size: file.size,
      storage_path: `raw-docs/${file.name}`,
      status: 'PENDING',
      chunk_count: 0,
      error_message: null,
      created_at: new Date().toISOString(),
      updated_at: new Date().toISOString(),
    }
    mockDocuments.unshift(newDoc as any)
    return HttpResponse.json({ document_id: newDoc.id, job_id: 'job-' + Date.now(), status: 'PENDING' })
  }),

  http.delete(`${base}/documents/:id`, ({ params }) => {
    const idx = mockDocuments.findIndex((d) => d.id === params.id)
    if (idx >= 0) mockDocuments.splice(idx, 1)
    return HttpResponse.json(null, { status: 204 })
  }),

  http.get(`${base}/documents/:id/preview`, ({ params }) => {
    const doc = mockDocuments.find((d) => d.id === params.id)
    if (!doc) return HttpResponse.json({ message: '未找到' }, { status: 404 })
    return HttpResponse.json({
      preview_url: `http://localhost:8012/onlinePreview?url=encoded_${doc.id}`,
      preview_type: doc.file_type === 'pdf' ? 'pdf' : 'office',
    })
  }),

  http.get(`${base}/documents/:id/segments`, ({ request, params }) => {
    const url = new URL(request.url)
    const page = Number(url.searchParams.get('page') || 1)
    const size = Number(url.searchParams.get('size') || 10)
    const all = generateMockSegments(params.id as string, 12)
    const start = (page - 1) * size
    const paged = all.slice(start, start + size)
    return HttpResponse.json({ items: paged, total: all.length, page, size })
  }),
]
```

- [ ] **Step 13: 创建检索 mock handler**

Create `web/src/mocks/handlers/search.ts`:
```typescript
import { http, HttpResponse } from 'msw'
import { mockSearchResults } from '../data/search-results'

const base = '/api/v1'

export const searchHandlers = [
  http.post(`${base}/search`, async () => {
    return HttpResponse.json({
      results: mockSearchResults,
      total: mockSearchResults.length,
      took_ms: 145,
    })
  }),

  http.get(`${base}/search/trace/:chunkId`, ({ params }) => {
    const result = mockSearchResults.find((r) => r.chunk_id === params.chunkId)
    if (!result) return HttpResponse.json({ message: '未找到' }, { status: 404 })
    return HttpResponse.json(result)
  }),
]
```

- [ ] **Step 14: 验证类型与 mock 编译**

Run:
```bash
cd /Users/hjx/Documents/01_Project/knowledge-base/web
pnpm type-check
```
Expected: 无类型错误

- [ ] **Step 15: Commit**

```bash
cd /Users/hjx/Documents/01_Project/knowledge-base
git add web/
git commit -m "feat: add knowledge-base, document, search types with mock data and handlers"
```

---

### Task 6: 工作台首页 + 知识库卡片概览

**Files:**
- Modify: `web/src/views/dashboard/index.vue`
- Modify: `web/src/views/knowledge-base/index.vue`
- Create: `web/src/components/kb/KbCard.vue`
- Create: `web/src/components/kb/KbCreateDialog.vue`

**Interfaces:**
- Consumes: `listKnowledgeBases`、`createKnowledgeBase`、`deleteKnowledgeBase`、router
- Produces: 工作台统计卡片、知识库卡片网格（对齐「知识库卡片风格.png」）

> 对齐参考：`知识库卡片风格.png`--顶部页面标题 + 「添加知识库」按钮，下方卡片网格（每行 3-4 个），每张卡片含图标、名称、描述、文档数、创建时间、hover 阴影。

- [ ] **Step 1: 实现 KbCard 组件**

Create `web/src/components/kb/KbCard.vue`:
```vue
<script setup lang="ts">
import { Document, ChatDotRound, FolderOpened } from '@element-plus/icons-vue'
import { useRouter } from 'vue-router'
import type { KnowledgeBase } from '@/types/knowledge-base'
import { formatDate } from '@/utils/format'

const props = defineProps<{ kb: KnowledgeBase }>()
const emit = defineEmits<{ (e: 'delete', id: string): void }>()
const router = useRouter()

function open() {
  if (props.kb.kb_type === 'FAQ') {
    router.push(`/faq/${props.kb.id}`)
  } else {
    router.push(`/knowledge-bases/${props.kb.id}`)
  }
}
</script>

<template>
  <el-card class="kb-card" shadow="hover" @click="open">
    <div class="kb-card-header">
      <el-icon size="32" :color="kb.kb_type === 'FAQ' ? '#67c23a' : '#409EFF'">
        <ChatDotRound v-if="kb.kb_type === 'FAQ'" />
        <Document v-else />
      </el-icon>
      <el-dropdown trigger="click" @click.stop>
        <el-icon class="more-btn"><MoreFilled /></el-icon>
        <template #dropdown>
          <el-dropdown-menu>
            <el-dropdown-item @click="open">
              <el-icon><FolderOpened /></el-icon> 进入
            </el-dropdown-item>
            <el-dropdown-item divided @click="emit('delete', kb.id)">
              <el-icon color="#f56c6c"><Delete /></el-icon>
              <span style="color:#f56c6c">删除</span>
            </el-dropdown-item>
          </el-dropdown-menu>
        </template>
      </el-dropdown>
    </div>
    <div class="kb-name">{{ kb.name }}</div>
    <div class="kb-desc">{{ kb.description || '暂无描述' }}</div>
    <div class="kb-meta">
      <span class="meta-item">
        <el-icon><Document /></el-icon>
        {{ kb.document_count || 0 }} 个文档
      </span>
      <span class="meta-item">{{ formatDate(kb.created_at) }}</span>
    </div>
  </el-card>
</template>

<style scoped>
.kb-card {
  cursor: pointer;
  transition: all 0.3s;
}
.kb-card:hover {
  transform: translateY(-2px);
}
.kb-card-header {
  display: flex;
  justify-content: space-between;
  align-items: flex-start;
}
.more-btn {
  cursor: pointer;
  color: #909399;
  font-size: 18px;
}
.kb-name {
  font-size: 16px;
  font-weight: 600;
  color: #303133;
  margin: 12px 0 8px;
}
.kb-desc {
  font-size: 13px;
  color: #909399;
  line-height: 1.5;
  height: 40px;
  overflow: hidden;
  display: -webkit-box;
  -webkit-line-clamp: 2;
  -webkit-box-orient: vertical;
}
.kb-meta {
  display: flex;
  justify-content: space-between;
  margin-top: 16px;
  padding-top: 12px;
  border-top: 1px solid #f0f0f0;
  font-size: 12px;
  color: #909399;
}
.meta-item {
  display: flex;
  align-items: center;
  gap: 4px;
}
</style>
```

- [ ] **Step 2: 实现 KbCreateDialog 组件**

Create `web/src/components/kb/KbCreateDialog.vue`:
```vue
<script setup lang="ts">
import { reactive, ref, watch } from 'vue'
import { ElMessage, type FormInstance, type FormRules } from 'element-plus'
import { createKnowledgeBase, updateKnowledgeBase } from '@/api/knowledge-base'
import type { KnowledgeBase, KbCreateRequest, ChunkStrategy } from '@/types/knowledge-base'

const props = defineProps<{
  modelValue: boolean
  editingKb?: KnowledgeBase | null
}>()
const emit = defineEmits<{
  (e: 'update:modelValue', val: boolean): void
  (e: 'success'): void
}>()

const formRef = ref<FormInstance>()
const loading = ref(false)
const form = reactive<KbCreateRequest>({
  name: '',
  description: '',
  kb_type: 'DOCUMENT',
  chunk_strategy: 'PARAGRAPH',
  chunk_size: 512,
  chunk_overlap: 150,
})

const strategies: { label: string; value: ChunkStrategy }[] = [
  { label: '固定大小切片', value: 'FIXED_SIZE' },
  { label: '段落切片', value: 'PARAGRAPH' },
  { label: 'Markdown 标题切片', value: 'MARKDOWN_HEADER' },
  { label: '句子切片', value: 'SENTENCE' },
]

const rules: FormRules = {
  name: [{ required: true, message: '请输入知识库名称', trigger: 'blur' }],
  kb_type: [{ required: true, message: '请选择类型', trigger: 'change' }],
}

watch(() => props.modelValue, (val) => {
  if (val) {
    if (props.editingKb) {
      Object.assign(form, {
        name: props.editingKb.name,
        description: props.editingKb.description,
        kb_type: props.editingKb.kb_type,
        chunk_strategy: props.editingKb.chunk_strategy,
        chunk_size: props.editingKb.chunk_size,
        chunk_overlap: props.editingKb.chunk_overlap,
      })
    } else {
      Object.assign(form, { name: '', description: '', kb_type: 'DOCUMENT', chunk_strategy: 'PARAGRAPH', chunk_size: 512, chunk_overlap: 150 })
    }
  }
})

async function handleSubmit() {
  if (!formRef.value) return
  await formRef.value.validate(async (valid) => {
    if (!valid) return
    loading.value = true
    try {
      if (props.editingKb) {
        await updateKnowledgeBase(props.editingKb.id, form)
        ElMessage.success('更新成功')
      } else {
        await createKnowledgeBase(form)
        ElMessage.success('创建成功')
      }
      emit('success')
      emit('update:modelValue', false)
    } finally {
      loading.value = false
    }
  })
}
</script>

<template>
  <el-dialog
    :model-value="modelValue"
    :title="editingKb ? '编辑知识库' : '创建知识库'"
    width="520px"
    @update:model-value="emit('update:modelValue', $event)"
  >
    <el-form ref="formRef" :model="form" :rules="rules" label-width="100px">
      <el-form-item label="名称" prop="name">
        <el-input v-model="form.name" placeholder="请输入知识库名称" />
      </el-form-item>
      <el-form-item label="描述">
        <el-input v-model="form.description" type="textarea" :rows="3" placeholder="可选" />
      </el-form-item>
      <el-form-item label="类型" prop="kb_type">
        <el-radio-group v-model="form.kb_type" :disabled="!!editingKb">
          <el-radio value="DOCUMENT">文档知识库</el-radio>
          <el-radio value="FAQ">FAQ 知识库</el-radio>
        </el-radio-group>
      </el-form-item>
      <el-form-item label="切片策略" v-if="form.kb_type === 'DOCUMENT'">
        <el-select v-model="form.chunk_strategy" style="width: 100%">
          <el-option v-for="s in strategies" :key="s.value" :label="s.label" :value="s.value" />
        </el-select>
      </el-form-item>
      <el-form-item label="切片大小" v-if="form.kb_type === 'DOCUMENT'">
        <el-input-number v-model="form.chunk_size" :min="50" :max="2000" :step="50" />
      </el-form-item>
      <el-form-item label="重叠大小" v-if="form.kb_type === 'DOCUMENT'">
        <el-input-number v-model="form.chunk_overlap" :min="0" :max="500" :step="10" />
      </el-form-item>
    </el-form>
    <template #footer>
      <el-button @click="emit('update:modelValue', false)">取消</el-button>
      <el-button type="primary" :loading="loading" @click="handleSubmit">确定</el-button>
    </template>
  </el-dialog>
</template>
```

- [ ] **Step 3: 实现知识库卡片概览页**

Replace `web/src/views/knowledge-base/index.vue`:
```vue
<script setup lang="ts">
import { ref, onMounted } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { Plus } from '@element-plus/icons-vue'
import PageContainer from '@/components/common/PageContainer.vue'
import KbCard from '@/components/kb/KbCard.vue'
import KbCreateDialog from '@/components/kb/KbCreateDialog.vue'
import { listKnowledgeBases, deleteKnowledgeBase } from '@/api/knowledge-base'
import type { KnowledgeBase } from '@/types/knowledge-base'

const list = ref<KnowledgeBase[]>([])
const loading = ref(false)
const dialogVisible = ref(false)

async function fetchData() {
  loading.value = true
  try {
    const res = await listKnowledgeBases()
    list.value = res.items
  } finally {
    loading.value = false
  }
}

async function handleDelete(id: string) {
  await ElMessageBox.confirm('删除知识库将同时删除其所有文档和索引，确认删除？', '警告', { type: 'warning' })
  await deleteKnowledgeBase(id)
  ElMessage.success('删除成功')
  fetchData()
}

onMounted(fetchData)
</script>

<template>
  <PageContainer title="知识库">
    <template #actions>
      <el-button type="primary" :icon="Plus" @click="dialogVisible = true">添加知识库</el-button>
    </template>
    <div v-loading="loading">
      <el-row :gutter="20" v-if="list.length">
        <el-col :xs="24" :sm="12" :md="8" :lg="6" v-for="kb in list" :key="kb.id" style="margin-bottom: 20px;">
          <KbCard :kb="kb" @delete="handleDelete" />
        </el-col>
      </el-row>
      <el-empty v-else description="暂无知识库，点击右上角创建" />
    </div>
  </PageContainer>
  <KbCreateDialog v-model="dialogVisible" @success="fetchData" />
</template>
```

- [ ] **Step 4: 实现工作台首页**

Replace `web/src/views/dashboard/index.vue`:
```vue
<script setup lang="ts">
import { ref, onMounted } from 'vue'
import { useRouter } from 'vue-router'
import { Document, ChatDotRound, Search, Collection } from '@element-plus/icons-vue'
import PageContainer from '@/components/common/PageContainer.vue'
import { listKnowledgeBases } from '@/api/knowledge-base'

const router = useRouter()
const stats = ref({ docKbCount: 0, faqKbCount: 0, totalDocs: 0 })

const cards = ref([
  { title: '文档知识库', icon: Collection, color: '#409EFF', route: '/knowledge-bases', key: 'docKbCount' as const },
  { title: 'FAQ 知识库', icon: ChatDotRound, color: '#67c23a', route: '/faq', key: 'faqKbCount' as const },
  { title: '文档总数', icon: Document, color: '#e6a23c', route: '/knowledge-bases', key: 'totalDocs' as const },
  { title: '统一检索', icon: Search, color: '#909399', route: '/search', key: null },
])

onMounted(async () => {
  const res = await listKnowledgeBases()
  stats.value.docKbCount = res.items.filter((k) => k.kb_type === 'DOCUMENT').length
  stats.value.faqKbCount = res.items.filter((k) => k.kb_type === 'FAQ').length
  stats.value.totalDocs = res.items.reduce((sum, k) => sum + (k.document_count || 0), 0)
})
</script>

<template>
  <PageContainer title="工作台">
    <el-row :gutter="20">
      <el-col :xs="24" :sm="12" :md="6" v-for="card in cards" :key="card.title" style="margin-bottom: 20px;">
        <el-card shadow="hover" class="stat-card" @click="router.push(card.route)">
          <div class="stat-icon" :style="{ background: card.color }">
            <el-icon size="28" color="#fff"><component :is="card.icon" /></el-icon>
          </div>
          <div class="stat-info">
            <div class="stat-value">{{ card.key ? stats[card.key] : '-' }}</div>
            <div class="stat-title">{{ card.title }}</div>
          </div>
        </el-card>
      </el-col>
    </el-row>
  </PageContainer>
</template>

<style scoped>
.stat-card {
  cursor: pointer;
  display: flex;
}
.stat-card :deep(.el-card__body) {
  display: flex;
  align-items: center;
  gap: 16px;
  width: 100%;
}
.stat-icon {
  width: 56px;
  height: 56px;
  border-radius: 8px;
  display: flex;
  align-items: center;
  justify-content: center;
}
.stat-value {
  font-size: 28px;
  font-weight: 600;
  color: #303133;
}
.stat-title {
  font-size: 14px;
  color: #909399;
  margin-top: 4px;
}
</style>
```

- [ ] **Step 5: 视觉验证**

Run `pnpm dev`，登录后：
1. 工作台显示 4 个统计卡片（文档知识库 3、FAQ 0、文档总数 48、统一检索）
2. 点击侧边栏「知识库」，看到 3 张知识库卡片网格，每张含图标、名称、描述、文档数、时间
3. 点击「添加知识库」弹出创建对话框，填写表单后提交，卡片列表刷新
4. 卡片右上角「...」下拉「删除」，确认后删除
5. 对照 `知识库卡片风格.png` 确认布局一致，停止 dev server

- [ ] **Step 6: Commit**

```bash
cd /Users/hjx/Documents/01_Project/knowledge-base
git add web/
git commit -m "feat: implement dashboard and knowledge-base card grid overview"
```

---

### Task 7: 文档型知识库详情（文档列表 + 目录树 + 上传）

**Files:**
- Modify: `web/src/views/knowledge-base/detail.vue`
- Create: `web/src/components/kb/DirectoryTree.vue`
- Create: `web/src/components/document/UploadDialog.vue`

**Interfaces:**
- Consumes: `getKnowledgeBase`、`listDocuments`、`getDirectoryTree`、`uploadDocument`、`deleteDocument`、`getDocumentPreviewUrl`
- Produces: 知识库详情页（左侧目录树 + 右侧文档表格 + 上传弹窗），对齐「列表风格.png」

> 对齐参考：`列表风格.png`--左侧目录树（可展开折叠），右侧文档表格（文件名、大小、状态、切片数、时间、操作列），顶部「上传文档」按钮。

- [ ] **Step 1: 实现 DirectoryTree 组件**

Create `web/src/components/kb/DirectoryTree.vue`:
```vue
<script setup lang="ts">
import { ref, watch, onMounted } from 'vue'
import { ElMessage } from 'element-plus'
import { Plus, FolderAdd } from '@element-plus/icons-vue'
import { getDirectoryTree, createDirectory } from '@/api/knowledge-base'
import type { Directory } from '@/types/knowledge-base'

const props = defineProps<{ kbId: string }>()
const emit = defineEmits<{ (e: 'select', directoryId: string | null): void }>()

const treeData = ref<Directory[]>([])
const loading = ref(false)
const defaultProps = { label: 'name', children: 'children' }
const selectedId = ref<string | null>(null)
const showAddInput = ref(false)
const newDirName = ref('')
const addingToParent = ref<string | null>(null)

async function fetchTree() {
  loading.value = true
  try {
    treeData.value = await getDirectoryTree(props.kbId)
  } finally {
    loading.value = false
  }
}

function handleNodeClick(data: Directory) {
  selectedId.value = data.id
  emit('select', data.id)
}

function selectAll() {
  selectedId.value = null
  emit('select', null)
}

async function addDirectory(parentId: string | null) {
  addingToParent.value = parentId
  showAddInput.value = true
  newDirName.value = ''
}

async function confirmAdd() {
  if (!newDirName.value.trim()) return
  await createDirectory(props.kbId, { name: newDirName.value, parent_id: addingToParent.value })
  ElMessage.success('目录已创建')
  showAddInput.value = false
  fetchTree()
}

onMounted(fetchTree)
watch(() => props.kbId, fetchTree)
</script>

<template>
  <div class="directory-tree" v-loading="loading">
    <div class="tree-header">
      <span>目录</span>
      <el-icon class="add-icon" @click="addDirectory(null)"><Plus /></el-icon>
    </div>
    <el-input
      v-if="showAddInput"
      v-model="newDirName"
      size="small"
      placeholder="目录名称"
      @keyup.enter="confirmAdd"
      @blur="showAddInput = false"
    />
    <el-tree
      :data="treeData"
      :props="defaultProps"
      node-key="id"
      highlight-current
      @node-click="handleNodeClick"
    >
      <template #default="{ data }">
        <span class="tree-node">
          <el-icon><Folder /></el-icon>
          <span class="node-label">{{ data.name }}</span>
          <el-icon class="node-add" @click.stop="addDirectory(data.id)"><Plus /></el-icon>
        </span>
      </template>
    </el-tree>
    <div class="all-docs" :class="{ active: !selectedId }" @click="selectAll">
      <el-icon><FolderOpened /></el-icon>
      <span>全部文档</span>
    </div>
  </div>
</template>

<style scoped>
.directory-tree { width: 240px; border-right: 1px solid #e6e6e6; padding: 12px; }
.tree-header { display: flex; justify-content: space-between; align-items: center; margin-bottom: 12px; font-weight: 600; }
.add-icon { cursor: pointer; color: #409EFF; }
.tree-node { display: flex; align-items: center; gap: 4px; flex: 1; }
.node-label { flex: 1; }
.node-add { cursor: pointer; color: #409EFF; opacity: 0; }
.tree-node:hover .node-add { opacity: 1; }
.all-docs { display: flex; align-items: center; gap: 6px; padding: 6px 8px; cursor: pointer; border-radius: 4px; margin-top: 8px; }
.all-docs.active { background: #ecf5ff; color: #409EFF; }
</style>
```

- [ ] **Step 2: 实现 UploadDialog 组件**

Create `web/src/components/document/UploadDialog.vue`:
```vue
<script setup lang="ts">
import { ref, watch } from 'vue'
import { ElMessage } from 'element-plus'
import { UploadFilled } from '@element-plus/icons-vue'
import type { UploadProps } from 'element-plus'
import { uploadDocument } from '@/api/document'

const props = defineProps<{
  modelValue: boolean
  kbId: string
  directoryId?: string | null
}>()
const emit = defineEmits<{
  (e: 'update:modelValue', val: boolean): void
  (e: 'success'): void
}>()

const fileList = ref<any[]>([])

const handleChange: UploadProps['onChange'] = async (file) => {
  if (file.status === 'ready') {
    try {
      await uploadDocument(file.raw as File, props.kbId, props.directoryId || undefined)
      ElMessage.success(`${file.name} 上传成功，正在后台处理`)
      emit('success')
    } catch {
      ElMessage.error(`${file.name} 上传失败`)
    }
  }
}

watch(() => props.modelValue, (val) => {
  if (!val) fileList.value = []
})
</script>

<template>
  <el-dialog
    :model-value="modelValue"
    title="上传文档"
    width="480px"
    @update:model-value="emit('update:modelValue', $event)"
  >
    <el-upload
      v-model:file-list="fileList"
      drag
      :auto-upload="true"
      :show-file-list="true"
      :on-change="handleChange"
      accept=".pdf,.docx,.pptx,.xlsx,.md,.txt,.html"
    >
      <el-icon class="el-icon--upload"><UploadFilled /></el-icon>
      <div class="el-upload__text">将文件拖到此处，或<em>点击上传</em></div>
      <template #tip>
        <div class="el-upload__tip">支持 PDF / Word / PPT / Excel / Markdown / TXT / HTML</div>
      </template>
    </el-upload>
  </el-dialog>
</template>
```

- [ ] **Step 3: 实现知识库详情页**

Replace `web/src/views/knowledge-base/detail.vue`:
```vue
<script setup lang="ts">
import { ref, onMounted } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ElMessage, ElMessageBox } from 'element-plus'
import { Plus, Refresh } from '@element-plus/icons-vue'
import PageContainer from '@/components/common/PageContainer.vue'
import DirectoryTree from '@/components/kb/DirectoryTree.vue'
import UploadDialog from '@/components/document/UploadDialog.vue'
import StatusTag from '@/components/common/StatusTag.vue'
import { getKnowledgeBase } from '@/api/knowledge-base'
import { listDocuments, deleteDocument, getDocumentPreviewUrl, reprocessDocument } from '@/api/document'
import type { KnowledgeBase } from '@/types/knowledge-base'
import type { Document } from '@/types/document'
import { formatFileSize, formatDate } from '@/utils/format'

const route = useRoute()
const router = useRouter()
const kbId = route.params.id as string

const kb = ref<KnowledgeBase | null>(null)
const documents = ref<Document[]>([])
const total = ref(0)
const page = ref(1)
const size = ref(10)
const loading = ref(false)
const selectedDirectory = ref<string | null>(null)
const uploadVisible = ref(false)

async function fetchKb() {
  kb.value = await getKnowledgeBase(kbId)
}

async function fetchDocuments() {
  loading.value = true
  try {
    const res = await listDocuments({
      kb_id: kbId,
      directory_id: selectedDirectory.value || undefined,
      page: page.value,
      size: size.value,
    })
    documents.value = res.items
    total.value = res.total
  } finally {
    loading.value = false
  }
}

function handleDirectorySelect(dirId: string | null) {
  selectedDirectory.value = dirId
  page.value = 1
  fetchDocuments()
}

function handlePageChange(p: number) {
  page.value = p
  fetchDocuments()
}

async function handleDelete(id: string) {
  await ElMessageBox.confirm('确认删除该文档及其所有切片和索引？', '警告', { type: 'warning' })
  await deleteDocument(id)
  ElMessage.success('删除成功')
  fetchDocuments()
}

async function handlePreview(id: string) {
  const res = await getDocumentPreviewUrl(id)
  window.open(res.preview_url, '_blank')
}

async function handleReprocess(id: string) {
  await reprocessDocument(id)
  ElMessage.success('已提交重新处理')
  fetchDocuments()
}

function goSegments(docId: string) {
  router.push(`/knowledge-bases/${kbId}/documents/${docId}`)
}

onMounted(() => {
  fetchKb()
  fetchDocuments()
})
</script>

<template>
  <PageContainer :title="kb?.name || '知识库详情'">
    <template #actions>
      <el-button :icon="Refresh" @click="fetchDocuments">刷新</el-button>
      <el-button type="primary" :icon="Plus" @click="uploadVisible = true">上传文档</el-button>
    </template>
    <div class="detail-layout">
      <DirectoryTree :kb-id="kbId" @select="handleDirectorySelect" />
      <div class="doc-section">
        <el-table :data="documents" v-loading="loading" style="width: 100%">
          <el-table-column prop="original_filename" label="文件名" min-width="200" show-overflow-tooltip />
          <el-table-column prop="file_type" label="类型" width="80" />
          <el-table-column label="大小" width="100">
            <template #default="{ row }">{{ formatFileSize(row.file_size) }}</template>
          </el-table-column>
          <el-table-column label="状态" width="100">
            <template #default="{ row }"><StatusTag :status="row.status" /></template>
          </el-table-column>
          <el-table-column prop="chunk_count" label="切片数" width="80" />
          <el-table-column label="创建时间" width="160">
            <template #default="{ row }">{{ formatDate(row.created_at) }}</template>
          </el-table-column>
          <el-table-column label="操作" width="220" fixed="right">
            <template #default="{ row }">
              <el-button link type="primary" size="small" @click="goSegments(row.id)">切片</el-button>
              <el-button link type="primary" size="small" @click="handlePreview(row.id)">预览</el-button>
              <el-button link type="warning" size="small" @click="handleReprocess(row.id)">重处理</el-button>
              <el-button link type="danger" size="small" @click="handleDelete(row.id)">删除</el-button>
            </template>
          </el-table-column>
        </el-table>
        <el-pagination
          v-if="total > size"
          class="pagination"
          background
          layout="total, prev, pager, next"
          :total="total"
          :page-size="size"
          :current-page="page"
          @current-change="handlePageChange"
        />
      </div>
    </div>
  </PageContainer>
  <UploadDialog v-model="uploadVisible" :kb-id="kbId" :directory-id="selectedDirectory" @success="fetchDocuments" />
</template>

<style scoped>
.detail-layout { display: flex; gap: 16px; }
.doc-section { flex: 1; }
.pagination { margin-top: 16px; justify-content: flex-end; }
</style>
```

- [ ] **Step 4: 视觉验证**

Run `pnpm dev`，登录后从知识库卡片进入详情页：
1. 顶部标题为知识库名称，右侧「刷新」「上传文档」按钮
2. 左侧目录树（架构设计/API 文档/认证授权），可展开、点击筛选
3. 右侧文档表格，含文件名、类型、大小、状态标签、切片数、时间、操作列
4. 点击「上传文档」弹出拖拽上传弹窗
5. 点击「切片」跳转切片预览页；「预览」打开新窗口；「重处理」「删除」生效
6. 对照 `列表风格.png` 确认布局一致，停止 dev server

- [ ] **Step 5: Commit**

```bash
cd /Users/hjx/Documents/01_Project/knowledge-base
git add web/
git commit -m "feat: implement knowledge-base detail with directory tree and document table"
```

---

### Task 8: 文档切片预览

**Files:**
- Modify: `web/src/views/knowledge-base/document-preview.vue`

**Interfaces:**
- Consumes: `getDocument`、`getDocumentSegments`
- Produces: 切片预览页，对齐「列表风格2.png」

> 对齐参考：`列表风格2.png`--顶部文档信息（文件名、状态、切片数），下方 Tab 或列表展示每个切片内容、索引、token 数、hash。

- [ ] **Step 1: 实现切片预览页**

Replace `web/src/views/knowledge-base/document-preview.vue`:
```vue
<script setup lang="ts">
import { ref, onMounted } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ArrowLeft } from '@element-plus/icons-vue'
import PageContainer from '@/components/common/PageContainer.vue'
import StatusTag from '@/components/common/StatusTag.vue'
import { getDocument, getDocumentSegments } from '@/api/document'
import type { Document, Segment } from '@/types/document'
import { formatFileSize, formatDate } from '@/utils/format'

const route = useRoute()
const router = useRouter()
const docId = route.params.docId as string
const kbId = route.params.id as string

const doc = ref<Document | null>(null)
const segments = ref<Segment[]>([])
const total = ref(0)
const page = ref(1)
const size = ref(10)
const loading = ref(false)

async function fetchDoc() {
  doc.value = await getDocument(docId)
}

async function fetchSegments() {
  loading.value = true
  try {
    const res = await getDocumentSegments(docId, { page: page.value, size: size.value })
    segments.value = res.items
    total.value = res.total
  } finally {
    loading.value = false
  }
}

function handlePageChange(p: number) {
  page.value = p
  fetchSegments()
}

onMounted(() => {
  fetchDoc()
  fetchSegments()
})
</script>

<template>
  <PageContainer :title="doc?.original_filename || '切片预览'">
    <template #actions>
      <el-button :icon="ArrowLeft" @click="router.push(`/knowledge-bases/${kbId}`)">返回</el-button>
    </template>
    <div v-if="doc" class="doc-info">
      <el-descriptions :column="4" border size="small">
        <el-descriptions-item label="文件名">{{ doc.original_filename }}</el-descriptions-item>
        <el-descriptions-item label="类型">{{ doc.file_type }}</el-descriptions-item>
        <el-descriptions-item label="大小">{{ formatFileSize(doc.file_size) }}</el-descriptions-item>
        <el-descriptions-item label="状态"><StatusTag :status="doc.status" /></el-descriptions-item>
        <el-descriptions-item label="切片数">{{ doc.chunk_count }}</el-descriptions-item>
        <el-descriptions-item label="创建时间">{{ formatDate(doc.created_at) }}</el-descriptions-item>
        <el-descriptions-item label="错误信息" :span="2">{{ doc.error_message || '无' }}</el-descriptions-item>
      </el-descriptions>
    </div>
    <div class="segment-list" v-loading="loading" style="margin-top: 16px;">
      <div v-for="seg in segments" :key="seg.id" class="segment-item">
        <div class="seg-header">
          <span class="seg-index">#{{ seg.chunk_index + 1 }}</span>
          <span class="seg-meta">token: {{ seg.token_count }}</span>
          <span class="seg-meta">hash: {{ seg.content_hash.slice(0, 16) }}...</span>
        </div>
        <div class="seg-content">{{ seg.content }}</div>
      </div>
    </div>
    <el-pagination
      v-if="total > size"
      class="pagination"
      background
      layout="total, prev, pager, next"
      :total="total"
      :page-size="size"
      :current-page="page"
      @current-change="handlePageChange"
    />
  </PageContainer>
</template>

<style scoped>
.doc-info { background: #fafafa; padding: 16px; border-radius: 4px; }
.segment-item { border: 1px solid #ebeef5; border-radius: 4px; margin-bottom: 12px; overflow: hidden; }
.seg-header { display: flex; align-items: center; gap: 12px; padding: 8px 16px; background: #f5f7fa; border-bottom: 1px solid #ebeef5; }
.seg-index { font-weight: 600; color: #409EFF; }
.seg-meta { font-size: 12px; color: #909399; }
.seg-content { padding: 16px; font-size: 14px; line-height: 1.8; color: #303133; white-space: pre-wrap; }
.pagination { margin-top: 16px; justify-content: flex-end; }
</style>
```

- [ ] **Step 2: 视觉验证**

Run `pnpm dev`，登录后进入知识库详情，点击某文档的「切片」：
1. 顶部文档信息表（文件名、类型、大小、状态、切片数、时间、错误信息）
2. 下方切片列表，每项含索引、token 数、hash 摘要、内容
3. 分页正常
4. 对照 `列表风格2.png` 确认布局一致，停止 dev server

- [ ] **Step 3: Commit**

```bash
cd /Users/hjx/Documents/01_Project/knowledge-base
git add web/
git commit -m "feat: implement document segment preview page"
```

---

### Task 9: FAQ 知识库（类型 + Mock + 列表 + 问答明细）

**Files:**
- Create: `web/src/types/faq.ts`
- Create: `web/src/api/faq.ts`
- Create: `web/src/mocks/data/faq-entries.ts`
- Create: `web/src/mocks/handlers/faq.ts`
- Modify: `web/src/mocks/handlers/index.ts`（已有，无需改动，Task 2 已引入）
- Create: `web/src/components/faq/FaqEntryDialog.vue`
- Create: `web/src/components/faq/FaqImportDialog.vue`
- Modify: `web/src/views/faq/index.vue`
- Modify: `web/src/views/faq/detail.vue`

**Interfaces:**
- Consumes: `listKnowledgeBases(kb_type=FAQ)`、`listFaqEntries`、`createFaqEntry`、`updateFaqEntry`、`deleteFaqEntry`、`importFaqEntries`
- Produces: FAQ 知识库列表 + 问答明细页（表格 + 行内编辑 + 批量导入），对齐「问答明细风格.png」「知识库列表风格.png」

> 对齐参考：`问答明细风格.png`--问答明细表格（问题、答案、关键词、状态、操作），支持行内编辑；`知识库列表风格.png`--FAQ 知识库列表。

- [ ] **Step 1: 定义 FAQ 类型**

Create `web/src/types/faq.ts`:
```typescript
export type FaqStatus = 'DRAFT' | 'PENDING' | 'INDEXED' | 'FAILED'

export interface FaqEntry {
  id: string
  kb_id: string
  directory_id: string | null
  question: string
  answer: string
  keywords: string[]
  source_document_id: string | null
  category_tags: string[]
  view_count: number
  helpful_count: number
  status: FaqStatus
  created_at: string
  updated_at: string
}

export interface FaqEntryCreateRequest {
  question: string
  answer: string
  keywords?: string[]
  category_tags?: string[]
  directory_id?: string | null
}
```

- [ ] **Step 2: 创建 FAQ API 函数**

Create `web/src/api/faq.ts`:
```typescript
import request from './request'
import type { FaqEntry, FaqEntryCreateRequest } from '@/types/faq'
import type { PageQuery, PageResult } from '@/types/api'

export function listFaqEntries(kbId: string, params?: PageQuery & { status?: string; keyword?: string }) {
  return request.get<unknown, PageResult<FaqEntry>>(`/faq/knowledge-bases/${kbId}/entries`, { params })
}

export function createFaqEntry(kbId: string, data: FaqEntryCreateRequest) {
  return request.post<unknown, FaqEntry>(`/faq/knowledge-bases/${kbId}/entries`, data)
}

export function updateFaqEntry(id: string, data: Partial<FaqEntryCreateRequest>) {
  return request.put<unknown, FaqEntry>(`/faq/entries/${id}`, data)
}

export function deleteFaqEntry(id: string) {
  return request.delete<unknown, void>(`/faq/entries/${id}`)
}

export function importFaqEntries(kbId: string, file: File) {
  const formData = new FormData()
  formData.append('file', file)
  return request.post<unknown, { imported: number; failed: number }>(`/faq/knowledge-bases/${kbId}/entries/batch`, formData, {
    headers: { 'Content-Type': 'multipart/form-data' },
  })
}
```

- [ ] **Step 3: 创建 FAQ mock 数据**

Create `web/src/mocks/data/faq-entries.ts`:
```typescript
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
```

- [ ] **Step 4: 创建 FAQ mock handler**

Create `web/src/mocks/handlers/faq.ts`:
```typescript
import { http, HttpResponse } from 'msw'
import { mockFaqEntries, mockFaqKb } from '../data/faq-entries'
import { mockKnowledgeBases } from '../data/knowledge-bases'
import type { FaqEntryCreateRequest } from '@/types/faq'

const base = '/api/v1'

export const faqHandlers = [
  http.get(`${base}/faq/knowledge-bases`, () => {
    const faqKbs = mockKnowledgeBases.filter((k) => k.kb_type === 'FAQ')
    if (faqKbs.length === 0) {
      mockKnowledgeBases.push(mockFaqKb as any)
    }
    const items = mockKnowledgeBases.filter((k) => k.kb_type === 'FAQ')
    return HttpResponse.json({ items, total: items.length, page: 1, size: items.length })
  }),

  http.get(`${base}/faq/knowledge-bases/:id`, ({ params }) => {
    const kb = mockKnowledgeBases.find((k) => k.id === params.id)
    if (!kb) return HttpResponse.json({ message: '未找到' }, { status: 404 })
    return HttpResponse.json(kb)
  }),

  http.get(`${base}/faq/knowledge-bases/:id/entries`, ({ request, params }) => {
    const url = new URL(request.url)
    const page = Number(url.searchParams.get('page') || 1)
    const size = Number(url.searchParams.get('size') || 10)
    const keyword = url.searchParams.get('keyword')
    let items = mockFaqEntries.filter((e) => e.kb_id === params.id)
    if (keyword) items = items.filter((e) => e.question.includes(keyword) || e.answer.includes(keyword))
    const total = items.length
    const start = (page - 1) * size
    return HttpResponse.json({ items: items.slice(start, start + size), total, page, size })
  }),

  http.post(`${base}/faq/knowledge-bases/:id/entries`, async ({ request, params }) => {
    const body = (await request.json()) as FaqEntryCreateRequest
    const newEntry = {
      ...body,
      id: 'faq-' + Date.now(),
      kb_id: params.id as string,
      source_document_id: null,
      view_count: 0,
      helpful_count: 0,
      status: 'PENDING',
      created_at: new Date().toISOString(),
      updated_at: new Date().toISOString(),
    }
    mockFaqEntries.unshift(newEntry as any)
    return HttpResponse.json(newEntry)
  }),

  http.put(`${base}/faq/entries/:id`, async ({ request, params }) => {
    const body = (await request.json()) as Partial<FaqEntryCreateRequest>
    const idx = mockFaqEntries.findIndex((e) => e.id === params.id)
    if (idx < 0) return HttpResponse.json({ message: '未找到' }, { status: 404 })
    mockFaqEntries[idx] = { ...mockFaqEntries[idx], ...body, updated_at: new Date().toISOString() }
    return HttpResponse.json(mockFaqEntries[idx])
  }),

  http.delete(`${base}/faq/entries/:id`, ({ params }) => {
    const idx = mockFaqEntries.findIndex((e) => e.id === params.id)
    if (idx >= 0) mockFaqEntries.splice(idx, 1)
    return HttpResponse.json(null, { status: 204 })
  }),

  http.post(`${base}/faq/knowledge-bases/:id/entries/batch`, async ({ request }) => {
    const formData = await request.formData()
    const file = formData.get('file') as File
    return HttpResponse.json({ imported: 10, failed: 0 })
  }),
]
```

- [ ] **Step 5: 实现 FaqEntryDialog 组件**

Create `web/src/components/faq/FaqEntryDialog.vue`:
```vue
<script setup lang="ts">
import { reactive, ref, watch } from 'vue'
import { ElMessage, type FormInstance, type FormRules } from 'element-plus'
import { createFaqEntry, updateFaqEntry } from '@/api/faq'
import type { FaqEntry, FaqEntryCreateRequest } from '@/types/faq'

const props = defineProps<{
  modelValue: boolean
  kbId: string
  editingEntry?: FaqEntry | null
}>()
const emit = defineEmits<{
  (e: 'update:modelValue', val: boolean): void
  (e: 'success'): void
}>()

const formRef = ref<FormInstance>()
const loading = ref(false)
const form = reactive<FaqEntryCreateRequest>({
  question: '',
  answer: '',
  keywords: [],
  category_tags: [],
})

const rules: FormRules = {
  question: [{ required: true, message: '请输入问题', trigger: 'blur' }],
  answer: [{ required: true, message: '请输入答案', trigger: 'blur' }],
}

watch(() => props.modelValue, (val) => {
  if (val) {
    if (props.editingEntry) {
      Object.assign(form, {
        question: props.editingEntry.question,
        answer: props.editingEntry.answer,
        keywords: [...props.editingEntry.keywords],
        category_tags: [...props.editingEntry.category_tags],
      })
    } else {
      Object.assign(form, { question: '', answer: '', keywords: [], category_tags: [] })
    }
  }
})

async function handleSubmit() {
  if (!formRef.value) return
  await formRef.value.validate(async (valid) => {
    if (!valid) return
    loading.value = true
    try {
      if (props.editingEntry) {
        await updateFaqEntry(props.editingEntry.id, form)
        ElMessage.success('更新成功')
      } else {
        await createFaqEntry(props.kbId, form)
        ElMessage.success('创建成功')
      }
      emit('success')
      emit('update:modelValue', false)
    } finally {
      loading.value = false
    }
  })
}
</script>

<template>
  <el-dialog
    :model-value="modelValue"
    :title="editingEntry ? '编辑问答' : '新增问答'"
    width="560px"
    @update:model-value="emit('update:modelValue', $event)"
  >
    <el-form ref="formRef" :model="form" :rules="rules" label-width="80px">
      <el-form-item label="问题" prop="question">
        <el-input v-model="form.question" type="textarea" :rows="2" placeholder="请输入问题" />
      </el-form-item>
      <el-form-item label="答案" prop="answer">
        <el-input v-model="form.answer" type="textarea" :rows="4" placeholder="请输入答案" />
      </el-form-item>
      <el-form-item label="关键词">
        <el-select v-model="form.keywords" multiple filterable allow-create default-first-option style="width: 100%" placeholder="输入后回车">
        </el-select>
      </el-form-item>
      <el-form-item label="分类标签">
        <el-select v-model="form.category_tags" multiple filterable allow-create default-first-option style="width: 100%" placeholder="输入后回车">
        </el-select>
      </el-form-item>
    </el-form>
    <template #footer>
      <el-button @click="emit('update:modelValue', false)">取消</el-button>
      <el-button type="primary" :loading="loading" @click="handleSubmit">确定</el-button>
    </template>
  </el-dialog>
</template>
```

- [ ] **Step 6: 实现 FaqImportDialog 组件**

Create `web/src/components/faq/FaqImportDialog.vue`:
```vue
<script setup lang="ts">
import { ref, watch } from 'vue'
import { ElMessage } from 'element-plus'
import { UploadFilled } from '@element-plus/icons-vue'
import type { UploadProps } from 'element-plus'
import { importFaqEntries } from '@/api/faq'

const props = defineProps<{
  modelValue: boolean
  kbId: string
}>()
const emit = defineEmits<{
  (e: 'update:modelValue', val: boolean): void
  (e: 'success'): void
}>()

const fileList = ref<any[]>([])

const handleChange: UploadProps['onChange'] = async (file) => {
  if (file.status === 'ready') {
    try {
      const res = await importFaqEntries(props.kbId, file.raw as File)
      ElMessage.success(`导入完成：成功 ${res.imported} 条，失败 ${res.failed} 条`)
      emit('success')
      emit('update:modelValue', false)
    } catch {
      ElMessage.error('导入失败')
    }
  }
}

watch(() => props.modelValue, (val) => {
  if (!val) fileList.value = []
})
</script>

<template>
  <el-dialog
    :model-value="modelValue"
    title="批量导入问答"
    width="480px"
    @update:model-value="emit('update:modelValue', $event)"
  >
    <el-alert title="文件格式说明" type="info" :closable="false" style="margin-bottom: 16px;">
      CSV 或 Excel 文件，第一列「问题」，第二列「答案」，第三列可选「关键词」（逗号分隔）。
    </el-alert>
    <el-upload
      v-model:file-list="fileList"
      drag
      :auto-upload="true"
      :show-file-list="true"
      :on-change="handleChange"
      accept=".csv,.xlsx,.xls"
    >
      <el-icon class="el-icon--upload"><UploadFilled /></el-icon>
      <div class="el-upload__text">将文件拖到此处，或<em>点击上传</em></div>
      <template #tip>
        <div class="el-upload__tip">支持 .csv / .xlsx / .xls</div>
      </template>
    </el-upload>
  </el-dialog>
</template>
```

- [ ] **Step 7: 实现 FAQ 知识库列表页**

Replace `web/src/views/faq/index.vue`:
```vue
<script setup lang="ts">
import { ref, onMounted } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage, ElMessageBox } from 'element-plus'
import { Plus, ChatDotRound } from '@element-plus/icons-vue'
import PageContainer from '@/components/common/PageContainer.vue'
import KbCreateDialog from '@/components/kb/KbCreateDialog.vue'
import { listKnowledgeBases, deleteKnowledgeBase } from '@/api/knowledge-base'
import type { KnowledgeBase } from '@/types/knowledge-base'
import { formatDate } from '@/utils/format'

const router = useRouter()
const list = ref<KnowledgeBase[]>([])
const loading = ref(false)
const dialogVisible = ref(false)

async function fetchData() {
  loading.value = true
  try {
    const res = await listKnowledgeBases({ kb_type: 'FAQ' })
    list.value = res.items
  } finally {
    loading.value = false
  }
}

function openDetail(id: string) {
  router.push(`/faq/${id}`)
}

async function handleDelete(id: string) {
  await ElMessageBox.confirm('确认删除该 FAQ 知识库？', '警告', { type: 'warning' })
  await deleteKnowledgeBase(id)
  ElMessage.success('删除成功')
  fetchData()
}

onMounted(fetchData)
</script>

<template>
  <PageContainer title="问答库">
    <template #actions>
      <el-button type="primary" :icon="Plus" @click="dialogVisible = true">添加问答库</el-button>
    </template>
    <div v-loading="loading">
      <el-row :gutter="20" v-if="list.length">
        <el-col :xs="24" :sm="12" :md="8" :lg="6" v-for="kb in list" :key="kb.id" style="margin-bottom: 20px;">
          <el-card shadow="hover" class="faq-card" @click="openDetail(kb.id)">
            <div class="card-header">
              <el-icon size="32" color="#67c23a"><ChatDotRound /></el-icon>
            </div>
            <div class="kb-name">{{ kb.name }}</div>
            <div class="kb-desc">{{ kb.description || '暂无描述' }}</div>
            <div class="kb-meta">
              <span>{{ kb.document_count || 0 }} 条问答</span>
              <el-dropdown trigger="click" @click.stop>
                <el-icon class="more-btn"><MoreFilled /></el-icon>
                <template #dropdown>
                  <el-dropdown-menu>
                    <el-dropdown-item @click="openDetail(kb.id)">进入</el-dropdown-item>
                    <el-dropdown-item divided style="color:#f56c6c" @click="handleDelete(kb.id)">删除</el-dropdown-item>
                  </el-dropdown-menu>
                </template>
              </el-dropdown>
            </div>
          </el-card>
        </el-col>
      </el-row>
      <el-empty v-else description="暂无问答库" />
    </div>
  </PageContainer>
  <KbCreateDialog v-model="dialogVisible" @success="fetchData" />
</template>

<style scoped>
.faq-card { cursor: pointer; transition: all 0.3s; }
.faq-card:hover { transform: translateY(-2px); }
.card-header { margin-bottom: 12px; }
.kb-name { font-size: 16px; font-weight: 600; color: #303133; margin-bottom: 8px; }
.kb-desc { font-size: 13px; color: #909399; height: 40px; overflow: hidden; display: -webkit-box; -webkit-line-clamp: 2; -webkit-box-orient: vertical; }
.kb-meta { display: flex; justify-content: space-between; align-items: center; margin-top: 16px; padding-top: 12px; border-top: 1px solid #f0f0f0; font-size: 12px; color: #909399; }
.more-btn { cursor: pointer; font-size: 16px; }
</style>
```

- [ ] **Step 8: 实现 FAQ 问答明细页**

Replace `web/src/views/faq/detail.vue`:
```vue
<script setup lang="ts">
import { ref, onMounted } from 'vue'
import { useRoute } from 'vue-router'
import { ElMessage, ElMessageBox } from 'element-plus'
import { Plus, Upload, ArrowLeft } from '@element-plus/icons-vue'
import { useRouter } from 'vue-router'
import PageContainer from '@/components/common/PageContainer.vue'
import StatusTag from '@/components/common/StatusTag.vue'
import FaqEntryDialog from '@/components/faq/FaqEntryDialog.vue'
import FaqImportDialog from '@/components/faq/FaqImportDialog.vue'
import { getKnowledgeBase } from '@/api/knowledge-base'
import { listFaqEntries, deleteFaqEntry } from '@/api/faq'
import type { KnowledgeBase } from '@/types/knowledge-base'
import type { FaqEntry } from '@/types/faq'
import { formatDate } from '@/utils/format'

const route = useRoute()
const router = useRouter()
const kbId = route.params.id as string

const kb = ref<KnowledgeBase | null>(null)
const entries = ref<FaqEntry[]>([])
const total = ref(0)
const page = ref(1)
const size = ref(10)
const loading = ref(false)
const keyword = ref('')
const dialogVisible = ref(false)
const importVisible = ref(false)
const editingEntry = ref<FaqEntry | null>(null)

async function fetchKb() {
  kb.value = await getKnowledgeBase(kbId)
}

async function fetchEntries() {
  loading.value = true
  try {
    const res = await listFaqEntries(kbId, { page: page.value, size: size.value, keyword: keyword.value || undefined })
    entries.value = res.items
    total.value = res.total
  } finally {
    loading.value = false
  }
}

function handleSearch() {
  page.value = 1
  fetchEntries()
}

function handleAdd() {
  editingEntry.value = null
  dialogVisible.value = true
}

function handleEdit(row: FaqEntry) {
  editingEntry.value = row
  dialogVisible.value = true
}

async function handleDelete(id: string) {
  await ElMessageBox.confirm('确认删除该问答？', '警告', { type: 'warning' })
  await deleteFaqEntry(id)
  ElMessage.success('删除成功')
  fetchEntries()
}

function handlePageChange(p: number) {
  page.value = p
  fetchEntries()
}

onMounted(() => {
  fetchKb()
  fetchEntries()
})
</script>

<template>
  <PageContainer :title="kb?.name || '问答明细'">
    <template #actions>
      <el-button :icon="ArrowLeft" @click="router.push('/faq')">返回</el-button>
      <el-button :icon="Upload" @click="importVisible = true">批量导入</el-button>
      <el-button type="primary" :icon="Plus" @click="handleAdd">新增问答</el-button>
    </template>
    <div class="search-bar" style="margin-bottom: 16px;">
      <el-input v-model="keyword" placeholder="搜索问题或答案" style="width: 300px;" clearable @keyup.enter="handleSearch" @clear="handleSearch" />
      <el-button type="primary" @click="handleSearch" style="margin-left: 8px;">搜索</el-button>
    </div>
    <el-table :data="entries" v-loading="loading" style="width: 100%">
      <el-table-column type="index" label="#" width="50" />
      <el-table-column prop="question" label="问题" min-width="200" show-overflow-tooltip />
      <el-table-column prop="answer" label="答案" min-width="300" show-overflow-tooltip />
      <el-table-column label="关键词" width="180">
        <template #default="{ row }">
          <el-tag v-for="k in row.keywords" :key="k" size="small" style="margin: 2px;">{{ k }}</el-tag>
        </template>
      </el-table-column>
      <el-table-column label="状态" width="90">
        <template #default="{ row }"><StatusTag :status="row.status" /></template>
      </el-table-column>
      <el-table-column prop="view_count" label="浏览" width="70" />
      <el-table-column label="更新时间" width="150">
        <template #default="{ row }">{{ formatDate(row.updated_at) }}</template>
      </el-table-column>
      <el-table-column label="操作" width="140" fixed="right">
        <template #default="{ row }">
          <el-button link type="primary" size="small" @click="handleEdit(row)">编辑</el-button>
          <el-button link type="danger" size="small" @click="handleDelete(row.id)">删除</el-button>
        </template>
      </el-table-column>
    </el-table>
    <el-pagination
      v-if="total > size"
      class="pagination"
      background
      layout="total, prev, pager, next"
      :total="total"
      :page-size="size"
      :current-page="page"
      @current-change="handlePageChange"
    />
  </PageContainer>
  <FaqEntryDialog v-model="dialogVisible" :kb-id="kbId" :editing-entry="editingEntry" @success="fetchEntries" />
  <FaqImportDialog v-model="importVisible" :kb-id="kbId" @success="fetchEntries" />
</template>

<style scoped>
.pagination { margin-top: 16px; justify-content: flex-end; }
</style>
```

- [ ] **Step 9: 视觉验证**

Run `pnpm dev`，登录后：
1. 侧边栏「问答库」-- 看到 FAQ 知识库卡片（产品使用 FAQ，8 条问答）
2. 点击进入问答明细-- 表格含序号、问题、答案、关键词标签、状态、浏览数、更新时间、操作
3. 顶部搜索框搜索问题，点击「新增问答」弹窗创建，点击行「编辑」弹窗编辑，「删除」确认删除
4. 点击「批量导入」弹出导入弹窗
5. 对照 `问答明细风格.png` 和 `知识库列表风格.png` 确认布局一致，停止 dev server

- [ ] **Step 10: Commit**

```bash
cd /Users/hjx/Documents/01_Project/knowledge-base
git add web/
git commit -m "feat: implement FAQ knowledge base list and entry detail with import"
```

---

### Task 10: 统一检索页（结果表 + 溯源抽屉）

**Files:**
- Modify: `web/src/views/search/index.vue`
- Create: `web/src/components/common/SearchTraceDrawer.vue`

**Interfaces:**
- Consumes: `search`、`listKnowledgeBases`、`getTrace`
- Produces: 统一检索页，输入查询、选择知识库、查看结果、点击溯源打开抽屉

> 检索流程：输入框 + 知识库多选 + 检索类型选择，结果表格展示文本、来源类型标签、文档标题、目录路径、评分、溯源按钮；点击溯源打开右侧抽屉显示完整溯源信息（文档、页码、预览链接、hash）。

- [ ] **Step 1: 实现 SearchTraceDrawer 组件**

Create `web/src/components/common/SearchTraceDrawer.vue`:
```vue
<script setup lang="ts">
import type { SearchResult } from '@/types/search'
import { formatDate } from '@/utils/format'

const props = defineProps<{
  modelValue: boolean
  result: SearchResult | null
}>()
const emit = defineEmits<{ (e: 'update:modelValue', val: boolean): void }>()
</script>

<template>
  <el-drawer
    :model-value="modelValue"
    title="检索结果溯源"
    size="420px"
    @update:model-value="emit('update:modelValue', $event)"
  >
    <div v-if="result" class="trace-content">
      <el-descriptions :column="1" border>
        <el-descriptions-item label="来源类型">
          <el-tag :type="result.source_type === 'FAQ' ? 'success' : 'primary'" size="small">
            {{ result.source_type === 'FAQ' ? 'FAQ 匹配' : '文档检索' }}
          </el-tag>
        </el-descriptions-item>
        <el-descriptions-item label="内容">{{ result.text }}</el-descriptions-item>
        <el-descriptions-item label="文档标题" v-if="result.document_title">{{ result.document_title }}</el-descriptions-item>
        <el-descriptions-item label="所在页码" v-if="result.page_number">第 {{ result.page_number }} 页</el-descriptions-item>
        <el-descriptions-item label="目录路径">{{ result.directory_path || '-' }}</el-descriptions-item>
        <el-descriptions-item label="切片序号" v-if="result.total_chunks">{{ result.chunk_id.split('_').pop() }} / {{ result.total_chunks }}</el-descriptions-item>
        <el-descriptions-item label="相关度评分">{{ (result.score * 100).toFixed(1) }}%</el-descriptions-item>
        <el-descriptions-item label="内容 Hash">{{ result.content_hash }}</el-descriptions-item>
        <el-descriptions-item label="FAQ 答案" v-if="result.faq_answer">{{ result.faq_answer }}</el-descriptions-item>
      </el-descriptions>
      <div class="trace-actions" v-if="result.preview_url || result.source_path">
        <el-button v-if="result.preview_url" type="primary" @click="window.open(result.preview_url, '_blank')">
          在线预览原文
        </el-button>
        <el-button v-if="result.source_path" @click="window.open(result.source_path, '_blank')">
          下载原文件
        </el-button>
      </div>
    </div>
  </el-drawer>
</template>

<script lang="ts">
// window 访问
declare global { interface Window { open: (url?: string, target?: string) => Window | null } }
</script>

<style scoped>
.trace-content { padding: 0; }
.trace-actions { margin-top: 16px; display: flex; gap: 8px; }
</style>
```

- [ ] **Step 2: 实现统一检索页**

Replace `web/src/views/search/index.vue`:
```vue
<script setup lang="ts">
import { ref, onMounted } from 'vue'
import { Search } from '@element-plus/icons-vue'
import PageContainer from '@/components/common/PageContainer.vue'
import SearchTraceDrawer from '@/components/common/SearchTraceDrawer.vue'
import { search } from '@/api/search'
import { listKnowledgeBases } from '@/api/knowledge-base'
import type { SearchRequest, SearchResult, SearchType } from '@/types/search'
import type { KnowledgeBase } from '@/types/knowledge-base'

const query = ref('')
const selectedKbIds = ref<string[]>([])
const searchType = ref<SearchType>('hybrid')
const topK = ref(10)
const results = ref<SearchResult[]>([])
const tookMs = ref(0)
const loading = ref(false)
const hasSearched = ref(false)
const kbOptions = ref<KnowledgeBase[]>([])
const drawerVisible = ref(false)
const selectedResult = ref<SearchResult | null>(null)

const typeOptions: { label: string; value: SearchType }[] = [
  { label: '混合检索（语义+关键字）', value: 'hybrid' },
  { label: '语义检索', value: 'semantic' },
  { label: '关键字检索', value: 'keyword' },
  { label: 'FAQ 匹配', value: 'faq' },
]

onMounted(async () => {
  const res = await listKnowledgeBases()
  kbOptions.value = res.items
  selectedKbIds.value = res.items.map((k) => k.id)
})

async function handleSearch() {
  if (!query.value.trim() || selectedKbIds.value.length === 0) return
  loading.value = true
  hasSearched.value = true
  try {
    const req: SearchRequest = {
      query: query.value,
      kb_ids: selectedKbIds.value,
      top_k: topK.value,
      search_type: searchType.value,
    }
    const res = await search(req)
    results.value = res.results
    tookMs.value = res.took_ms
  } finally {
    loading.value = false
  }
}

function showTrace(result: SearchResult) {
  selectedResult.value = result
  drawerVisible.value = true
}
</script>

<template>
  <PageContainer title="统一检索">
    <div class="search-panel">
      <div class="search-input-row">
        <el-input
          v-model="query"
          size="large"
          placeholder="输入检索内容..."
          :prefix-icon="Search"
          @keyup.enter="handleSearch"
        />
        <el-button type="primary" size="large" :loading="loading" @click="handleSearch">检索</el-button>
      </div>
      <div class="search-filters">
        <el-select v-model="selectedKbIds" multiple collapse-tags collapse-tags-tooltip placeholder="选择知识库" style="width: 360px;">
          <el-option v-for="kb in kbOptions" :key="kb.id" :label="kb.name" :value="kb.id" />
        </el-select>
        <el-select v-model="searchType" style="width: 220px;">
          <el-option v-for="t in typeOptions" :key="t.value" :label="t.label" :value="t.value" />
        </el-select>
        <span class="filter-label">返回数量</span>
        <el-input-number v-model="topK" :min="1" :max="50" size="default" />
      </div>
    </div>
    <div class="result-section" v-loading="loading">
      <div v-if="hasSearched && !loading" class="result-meta">
        共找到 {{ results.length }} 条结果，耗时 {{ tookMs }}ms
      </div>
      <el-table v-if="results.length" :data="results" style="width: 100%; margin-top: 12px;">
        <el-table-column label="内容" min-width="400">
          <template #default="{ row }">
            <div class="result-text">{{ row.text }}</div>
            <div v-if="row.faq_answer" class="faq-answer">答：{{ row.faq_answer }}</div>
          </template>
        </el-table-column>
        <el-table-column label="来源" width="100">
          <template #default="{ row }">
            <el-tag :type="row.source_type === 'FAQ' ? 'success' : 'primary'" size="small">
              {{ row.source_type === 'FAQ' ? 'FAQ' : '文档' }}
            </el-tag>
          </template>
        </el-table-column>
        <el-table-column prop="document_title" label="文档标题" width="180" show-overflow-tooltip />
        <el-table-column prop="directory_path" label="目录路径" width="160" show-overflow-tooltip />
        <el-table-column label="评分" width="80">
          <template #default="{ row }">{{ (row.score * 100).toFixed(0) }}%</template>
        </el-table-column>
        <el-table-column label="操作" width="90" fixed="right">
          <template #default="{ row }">
            <el-button link type="primary" size="small" @click="showTrace(row)">溯源</el-button>
          </template>
        </el-table-column>
      </el-table>
      <el-empty v-else-if="hasSearched && !loading" description="未找到相关结果" />
    </div>
  </PageContainer>
  <SearchTraceDrawer v-model="drawerVisible" :result="selectedResult" />
</template>

<style scoped>
.search-panel { background: #fff; padding: 20px; border-radius: 4px; margin-bottom: 16px; }
.search-input-row { display: flex; gap: 12px; margin-bottom: 16px; }
.search-filters { display: flex; align-items: center; gap: 12px; flex-wrap: wrap; }
.filter-label { font-size: 14px; color: #606266; }
.result-meta { font-size: 13px; color: #909399; }
.result-text { font-size: 14px; line-height: 1.6; color: #303133; }
.faq-answer { font-size: 13px; color: #67c23a; margin-top: 6px; }
</style>
```

- [ ] **Step 3: 视觉验证**

Run `pnpm dev`，登录后进入「统一检索」：
1. 顶部大输入框 + 检索按钮，下方知识库多选、检索类型、返回数量
2. 输入「如何认证」点击检索，显示 3 条结果（文档+FAQ），含内容、来源标签、文档标题、目录路径、评分、溯源按钮
3. 点击「溯源」打开右侧抽屉，显示来源类型、内容、文档标题、页码、目录路径、评分、hash、预览/下载按钮
4. 停止 dev server

- [ ] **Step 4: Commit**

```bash
cd /Users/hjx/Documents/01_Project/knowledge-base
git add web/
git commit -m "feat: implement unified search page with traceability drawer"
```

---

### Task 11: 用户管理与 API Key 管理

**Files:**
- Modify: `web/src/views/admin/users.vue`
- Modify: `web/src/views/admin/api-keys.vue`

**Interfaces:**
- Consumes: `getUserInfo`（用户管理 mock）、`getApiKeys`、`createApiKey`、`deleteApiKey`、`useUserStore`
- Produces: 用户列表表格、API Key 管理表格（创建后仅显示一次原始 key）

- [ ] **Step 1: 实现用户管理页**

Replace `web/src/views/admin/users.vue`:
```vue
<script setup lang="ts">
import { ref, onMounted } from 'vue'
import PageContainer from '@/components/common/PageContainer.vue'
import { mockUsers } from '@/mocks/data/users'
import type { UserInfo, UserRole } from '@/types/user'
import { formatDate } from '@/utils/format'

const users = ref<UserInfo[]>([])

const roleMap: Record<UserRole, { label: string; type: 'danger' | 'warning' | 'success' | 'info' }> = {
  super_admin: { label: '超级管理员', type: 'danger' },
  admin: { label: '管理员', type: 'warning' },
  editor: { label: '编辑者', type: 'success' },
  viewer: { label: '查看者', type: 'info' },
}

onMounted(() => {
  users.value = [...mockUsers]
})
</script>

<template>
  <PageContainer title="用户管理">
    <el-table :data="users" style="width: 100%">
      <el-table-column prop="username" label="用户名" width="150" />
      <el-table-column prop="email" label="邮箱" width="200" />
      <el-table-column label="角色" width="120">
        <template #default="{ row }">
          <el-tag :type="roleMap[row.role as UserRole].type" size="small">{{ roleMap[row.role as UserRole].label }}</el-tag>
        </template>
      </el-table-column>
      <el-table-column label="状态" width="100">
        <template #default="{ row }">
          <el-tag :type="row.is_active ? 'success' : 'info'" size="small">{{ row.is_active ? '启用' : '禁用' }}</el-tag>
        </template>
      </el-table-column>
      <el-table-column label="创建时间" width="180">
        <template #default="{ row }">{{ formatDate(row.created_at) }}</template>
      </el-table-column>
    </el-table>
  </PageContainer>
</template>
```

- [ ] **Step 2: 实现 API Key 管理页**

Replace `web/src/views/admin/api-keys.vue`:
```vue
<script setup lang="ts">
import { ref, onMounted } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { Plus, CopyDocument } from '@element-plus/icons-vue'
import PageContainer from '@/components/common/PageContainer.vue'
import { getApiKeys, createApiKey, deleteApiKey } from '@/api/auth'
import type { ApiKey } from '@/types/user'
import { formatDate } from '@/utils/format'

const apiKeys = ref<ApiKey[]>([])
const loading = ref(false)
const createVisible = ref(false)
const newName = ref('')
const createdKey = ref<string | null>(null)

async function fetchData() {
  loading.value = true
  try {
    apiKeys.value = await getApiKeys()
  } finally {
    loading.value = false
  }
}

async function handleCreate() {
  if (!newName.value.trim()) return
  const res = await createApiKey(newName.value)
  createdKey.value = res.raw_key
  createVisible.value = false
  newName.value = ''
  ElMessage.success('API Key 已创建')
  fetchData()
}

async function handleDelete(id: string) {
  await ElMessageBox.confirm('确认删除该 API Key？删除后无法恢复。', '警告', { type: 'warning' })
  await deleteApiKey(id)
  ElMessage.success('删除成功')
  fetchData()
}

function copyKey() {
  if (createdKey.value) {
    navigator.clipboard.writeText(createdKey.value)
    ElMessage.success('已复制到剪贴板')
  }
}

onMounted(fetchData)
</script>

<template>
  <PageContainer title="API Key 管理">
    <template #actions>
      <el-button type="primary" :icon="Plus" @click="createVisible = true">创建 API Key</el-button>
    </template>
    <el-table :data="apiKeys" v-loading="loading" style="width: 100%">
      <el-table-column prop="name" label="名称" width="180" />
      <el-table-column prop="key_prefix" label="Key 前缀" width="150" />
      <el-table-column label="状态" width="100">
        <template #default="{ row }">
          <el-tag :type="row.is_active ? 'success' : 'info'" size="small">{{ row.is_active ? '启用' : '已禁用' }}</el-tag>
        </template>
      </el-table-column>
      <el-table-column label="最后使用" width="180">
        <template #default="{ row }">{{ formatDate(row.last_used_at) }}</template>
      </el-table-column>
      <el-table-column label="创建时间" width="180">
        <template #default="{ row }">{{ formatDate(row.created_at) }}</template>
      </el-table-column>
      <el-table-column label="操作" width="100" fixed="right">
        <template #default="{ row }">
          <el-button link type="danger" size="small" @click="handleDelete(row.id)">删除</el-button>
        </template>
      </el-table-column>
    </el-table>

    <el-dialog v-model="createVisible" title="创建 API Key" width="420px">
      <el-form>
        <el-form-item label="名称">
          <el-input v-model="newName" placeholder="如：生产环境调用" />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="createVisible = false">取消</el-button>
        <el-button type="primary" @click="handleCreate">创建</el-button>
      </template>
    </el-dialog>

    <el-dialog v-model="!!createdKey" title="API Key 已创建" width="480px" :close-on-click-modal="false">
      <el-alert type="warning" :closable="false" style="margin-bottom: 16px;">
        此 Key 仅显示一次，请立即复制保存，关闭后无法再次查看。
      </el-alert>
      <el-input :model-value="createdKey || ''" readonly>
        <template #append>
          <el-button :icon="CopyDocument" @click="copyKey">复制</el-button>
        </template>
      </el-input>
      <template #footer>
        <el-button type="primary" @click="createdKey = null">我已保存</el-button>
      </template>
    </el-dialog>
  </PageContainer>
</template>
```

- [ ] **Step 3: 视觉验证**

Run `pnpm dev`，登录后：
1. 「用户管理」-- 表格显示 admin/editor 两个用户，角色标签（超级管理员红色、编辑者绿色）、状态、创建时间
2. 「API Key 管理」-- 表格显示 2 个 key，点击「创建 API Key」弹窗输入名称，提交后弹出 key 展示弹窗（仅一次），可复制
3. 删除 key 确认后生效
4. 停止 dev server

- [ ] **Step 4: Commit**

```bash
cd /Users/hjx/Documents/01_Project/knowledge-base
git add web/
git commit -m "feat: implement user management and API key management pages"
```

---

## Self-Review

**1. Spec coverage**（对照设计文档前端章节）：
- 工作台 → Task 6 ✓
- 知识库卡片概览 → Task 6 ✓
- 知识库详情（文档列表+目录树）→ Task 7 ✓
- 文档切片预览 → Task 8 ✓
- FAQ 知识库列表 → Task 9 ✓
- FAQ 问答明细 → Task 9 ✓
- 统一检索 → Task 10 ✓
- 溯源 → Task 10 ✓
- 用户管理 → Task 11 ✓
- API Key 管理 → Task 11 ✓
- 布局（侧边栏+顶栏+面包屑）→ Task 3 ✓
- 配色约束（#409EFF / #263445 / #f5f7fa）→ Task 1 variables.scss + Task 3 Sidebar ✓
- kkFileView 预览 → Task 7 预览按钮（调用 preview_url，浏览器打开）✓
- 登录 + RBAC 路由守卫 → Task 4 + Task 2 ✓

**2. Placeholder scan**: 无 TBD/TODO，所有步骤含完整代码。占位视图在 Task 2 Step 9 明确为临时占位，后续 Task 全部替换。

**3. Type consistency**:
- `KnowledgeBase`、`Document`、`Segment`、`FaqEntry`、`SearchResult` 类型在 types/ 定义后，API 函数与 mock handler、页面组件统一引用，字段名一致（如 `chunk_count`、`document_count`、`source_type`、`faq_answer`）。
- API 函数签名跨任务一致：`listKnowledgeBases`、`getKnowledgeBase`、`listDocuments`、`search`、`listFaqEntries` 等。
- `useUserStore().login` 在 Task 2 定义、Task 4 调用，签名一致。

**4. Mock 真实性**: 所有 mock 数据字段与设计文档数据模型一一对应，前端切 `VITE_USE_MOCK=false` 后可直接对接后端同一套 API 路径。

---

## Execution Handoff

Plan complete and saved to `docs/superpowers/plans/2026-07-29-frontend-plan.md`. Two execution options:

**1. Subagent-Driven (recommended)** - 每个 Task 派发独立 subagent 执行，任务间有 review 检查点，迭代快

**2. Inline Execution** - 在当前会话中按任务批量执行，带检查点 review

建议选择 **1**，因为前端任务彼此独立（各页面组件），适合并行 subagent；但 Task 1-3 是基础，必须先串行完成。你倾向哪种方式？
