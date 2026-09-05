# KB 列表搜索栏改造设计

**日期**: 2026-07-30
**分支**: feat/mvp
**状态**: 已确认

## 概述

改造知识库列表页面的搜索筛选栏，将当前简单的搜索框 + 工具栏升级为包含收藏筛选、类型、归属人、状态、搜索名称、视图切换的完整筛选栏，并实现对应的后端 API。

## 1. 数据模型变更

### 1.1 新增 `kb_favorites` 表

用户-知识库收藏多对多关联：

```sql
CREATE TABLE kb_favorites (
    user_id UUID NOT NULL REFERENCES users(id),
    kb_id   UUID NOT NULL REFERENCES knowledge_bases(id),
    created_at TIMESTAMP DEFAULT NOW(),
    PRIMARY KEY (user_id, kb_id)
);
```

### 1.2 `knowledge_bases` 新增 status 字段

```sql
ALTER TABLE knowledge_bases ADD COLUMN status VARCHAR(20) DEFAULT 'FULLY_PUBLISHED';
```

可选值：
- `PUBLISHING` — 发布中
- `FULLY_PUBLISHED` — 完全发布
- `PARTIALLY_FAILED` — 部分失败

## 2. 后端 API

### 2.1 收藏 API（新增）

| 方法 | 路由 | 说明 | 权限 |
|------|------|------|------|
| POST | `/api/v1/knowledge-bases/{kb_id}/favorite` | 收藏知识库 | 需要登录 |
| DELETE | `/api/v1/knowledge-bases/{kb_id}/favorite` | 取消收藏 | 需要登录 |

**POST favorite 逻辑**: INSERT INTO kb_favorites，重复收藏返回 200（幂等）。
**DELETE favorite 逻辑**: DELETE FROM kb_favorites，未收藏返回 200（幂等）。

### 2.2 列表查询扩展（修改现有）

**现有路由**: `GET /api/v1/knowledge-bases`

新增 query 参数：

| 参数 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| `owner_id` | string | — | `me` = 当前用户创建，不传 = 所有人 |
| `status` | string | — | `PUBLISHING` / `FULLY_PUBLISHED` / `PARTIALLY_FAILED` |
| `is_favorite` | bool | — | `true` = 仅返回当前用户收藏的 KB |
| `search` | string | — | 行为变更：仅搜索 name，不再搜索 description |

现有参数 `kb_type` 保持不变。

**查询逻辑变更**:
- `search`: 从 `name.ilike OR description.ilike` 改为仅 `name.ilike`
- `owner_id=me`: `WHERE kb.owner_id = current_user.id`
- `status`: `WHERE kb.status = :status`
- `is_favorite=true`: `WHERE kb.id IN (SELECT kb_id FROM kb_favorites WHERE user_id = current_user.id)`
- 所有筛选条件 AND 叠加

**返回字段变更**: KbOut schema 新增 `status` 字段，Response items 中 `status` 改为返回实际数据库值而非固定 `"正常"`。

### 2.3 列表返回新增字段

KbOut / 列表 items 新增：
- `is_favorite`: bool — 当前用户是否已收藏该 KB（通过 JOIN 或子查询获取）

## 3. 前端

### 3.1 搜索栏布局

搜索栏替换当前 `.search-wrap`（居中搜索框）+ `.toolbar`（按钮行）为单行筛选栏：

```
┌──────────────────────────────────────────────────────────────────────────┐
│ [+ 添加知识库]  ☐ 仅展示收藏  [类型 ▾] [归属人 ▾] [状态 ▾]  🔍 搜索...  [≡][▦] │
└──────────────────────────────────────────────────────────────────────────┘
```

**组件映射（Element Plus）：**

| 元素 | 组件 | 宽度 | Placeholder/Label |
|------|------|------|-------------------|
| 添加知识库 | `el-button` type="primary" | auto | + 添加知识库 |
| 仅展示收藏 | `el-checkbox` | auto | 仅展示收藏 |
| 类型 | `el-select` | 140px | 知识库类型（默认全部） |
| 归属人 | `el-select` | 140px | 归属人（默认所有人） |
| 状态 | `el-select` | 140px | 状态（默认全部） |
| 搜索框 | `el-input` | 220px | 搜索知识库名称 |
| 视图切换 | `el-radio-group` + `el-radio-button` | auto | 卡片 / 列表图标 |

**下拉选项：**

| 下拉 | 选项 |
|------|------|
| 类型 | 全部、文档、FAQ |
| 归属人 | 所有人、由我创建 |
| 状态 | 全部、发布中、完全发布、部分失败 |

**交互规则：**
- 所有下拉变化 → 重置 `page=1` → 触发 `fetchData`
- Checkbox 变化 → 重置 `page=1` → 触发 `fetchData`
- 搜索框 `debounce 300ms`，≥2 字符触发搜索，清空立即刷新
- 所有筛选条件 AND 叠加
- 视图切换仅影响展示样式，不触发 API 请求

### 3.2 文件变更清单

| 文件 | 变更 |
|------|------|
| `web/src/views/knowledge-base/index.vue` | 重写搜索栏模板 + script |
| `web/src/api/knowledge-base.ts` | 新增 favorite API + 扩展 `KbListParams` |
| `web/src/types/knowledge-base.ts` | `KnowledgeBase` 新增 `status`, `is_favorite` |
| `web/src/components/kb/KbCard.vue` | 卡片上显示收藏按钮 |

### 3.3 卡片收藏按钮

KbCard 右上角（more-btn 旁边）新增收藏星形按钮：
- 空心 ⭐ → 未收藏，点击收藏
- 实心 🌟 → 已收藏，点击取消收藏
- 调用 favorite / unfavorite API

## 4. 实施步骤概览

1. **DB migration** — 新增 `kb_favorites` 表 + `knowledge_bases.status` 字段
2. **kb-common models** — 添加 `KbFavorite` ORM 模型 + `KnowledgeBase.status`
3. **kb-api routes** — 新增 2 个收藏端点 + 扩展现有 `list_kb`
4. **kb-api schemas** — 更新 `KbOut` schema
5. **前端 types** — 更新 interface
6. **前端 API** — 新增 favorite API，扩展 list params
7. **前端 index.vue** — 重写搜索栏
8. **前端 KbCard** — 添加收藏按钮
