# KB 列表搜索栏改造 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 改造知识库列表页搜索栏，新增收藏筛选、类型、归属人、状态下拉框，同时实现后端收藏持久化

**Architecture:** 新增 `kb_favorites` 关联表 + `knowledge_bases.status` 字段；扩展 `GET /knowledge-bases` API 支持 `owner_id`/`status`/`is_favorite` 筛选；新增收藏/取消收藏端点；前端重写搜索栏为单行多条件筛选栏

**Tech Stack:** Python 3.11, FastAPI, SQLAlchemy 2.0 (async), Alembic, PostgreSQL, Vue 3 + TypeScript, Element Plus

## Global Constraints

- 所有 API 需要登录（JWT 鉴权）
- 前端使用 Composition API `<script setup lang="ts">`
- Element Plus 组件库，中文界面
- 搜索框 debounce 300ms，≥2 字符触发
- 筛选条件 AND 叠加，变化时重置 page=1
- 状态枚举: `PUBLISHING` / `FULLY_PUBLISHED` / `PARTIALLY_FAILED`
- 类型显示标签: DOCUMENT → "文档", FAQ 不变
- 迁移文件命名: `0003_<slug>.py`，`down_revision='0002'`

---

### Task 1: DB Migration — 新增 kb_favorites 表 + knowledge_bases.status 字段

**Files:**
- Create: `alembic/versions/0003_add_kb_status_and_favorites.py`

**Interfaces:**
- Produces: `kb_favorites` table (user_id, kb_id, created_at), `knowledge_bases.status` column (VARCHAR(20), default 'FULLY_PUBLISHED')

- [ ] **Step 1: Create migration file**

```python
"""add kb status and favorites

Revision ID: 0003
Revises: 0002
Create Date: 2026-07-30
"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = '0003'
down_revision: Union[str, None] = '0002'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # 1. knowledge_bases.status
    op.add_column('knowledge_bases',
        sa.Column('status', sa.String(length=20), nullable=False,
                  server_default=sa.text("'FULLY_PUBLISHED'")))

    # 2. kb_favorites table
    op.create_table('kb_favorites',
        sa.Column('user_id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('kb_id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('created_at', sa.DateTime(), server_default=sa.text('now()'), nullable=False),
        sa.PrimaryKeyConstraint('user_id', 'kb_id'),
        sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['kb_id'], ['knowledge_bases.id'], ondelete='CASCADE'),
    )


def downgrade() -> None:
    op.drop_table('kb_favorites')
    op.drop_column('knowledge_bases', 'status')
```

- [ ] **Step 2: Run migration**

```bash
cd services/kb-common && uv run alembic -c ../../alembic.ini upgrade head
```

- [ ] **Step 3: Commit**

```bash
git add alembic/versions/0003_add_kb_status_and_favorites.py
git commit -m "feat: db migration — kb_favorites table + knowledge_bases.status"
```

---

### Task 2: kb-common models — 添加 KbFavorite 模型 + KnowledgeBase.status

**Files:**
- Modify: `services/kb-common/kb_common/models.py`

**Interfaces:**
- Produces: `KbFavorite` SQLAlchemy model, `KnowledgeBase.status: Mapped[str]`

- [ ] **Step 1: Add KnowledgeBase.status and KbFavorite to models.py**

In `services/kb-common/kb_common/models.py`, add `status` to `KnowledgeBase` (after `es_index_name`):

```python
# In KnowledgeBase, after es_index_name line (~line 42):
    status: Mapped[str] = mapped_column(String(20), default="FULLY_PUBLISHED")  # PUBLISHING|FULLY_PUBLISHED|PARTIALLY_FAILED
```

Add `KbFavorite` class after the `KnowledgeBase` class definition (after line ~43):

```python
class KbFavorite(Base):
    __tablename__ = "kb_favorites"
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), primary_key=True)
    kb_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("knowledge_bases.id", ondelete="CASCADE"), primary_key=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
```

- [ ] **Step 2: Verify model imports correctly**

```bash
cd services/kb-common && uv run python -c "from kb_common.models import KnowledgeBase, KbFavorite; print('OK')"
```

- [ ] **Step 3: Commit**

```bash
git add services/kb-common/kb_common/models.py
git commit -m "feat: add KbFavorite model + KnowledgeBase.status field"
```

---

### Task 3: kb-api schemas — 更新 KbOut

**Files:**
- Modify: `services/kb-api/app/schemas.py`

**Interfaces:**
- Consumes: `KnowledgeBase.status`, `KbFavorite`
- Produces: `KbOut` with `status: str`, `is_favorite: bool`

- [ ] **Step 1: Update KbOut in schemas.py**

In `services/kb-api/app/schemas.py`, replace `KbOut`:

```python
class KbOut(KbIn):
    id: uuid.UUID
    owner_id: uuid.UUID
    created_at: datetime
    es_index_name: str
    status: str = "FULLY_PUBLISHED"
    document_count: int = 0
    owner_name: str = ""
    is_favorite: bool = False
    updated_at: datetime | None = None

    class Config:
        from_attributes = True
```

- [ ] **Step 2: Verify schema**

```bash
cd services/kb-api && uv run python -c "from app.schemas import KbOut; print(KbOut.model_fields.keys())"
```

- [ ] **Step 3: Commit**

```bash
git add services/kb-api/app/schemas.py
git commit -m "feat: KbOut schema — add status and is_favorite fields"
```

---

### Task 4: kb-api routes — 新增收藏端点 + 扩展 list_kb

**Files:**
- Modify: `services/kb-api/app/routes/knowledge_base.py`

**Interfaces:**
- Consumes: `KbFavorite` model, `KnowledgeBase.status`, updated `KbOut`
- Produces:
  - `POST /api/v1/knowledge-bases/{kb_id}/favorite` → `{"ok": True}`
  - `DELETE /api/v1/knowledge-bases/{kb_id}/favorite` → `{"ok": True}`
  - Extended `GET /api/v1/knowledge-bases` with params `owner_id`, `status`, `is_favorite`, narrowed `search`

- [ ] **Step 1: Add KbFavorite import and favorite endpoints**

In `services/kb-api/app/routes/knowledge_base.py`, update imports (line 5):

```python
from kb_common.models import KnowledgeBase, User, Document, KbFavorite
```

Add `exists` import for subquery (line 3):

No change needed — `exists` is not currently imported. Add it:

```python
from sqlalchemy import select, func, exists, and_
```

After the `create_kb` route (after line ~23), add favorite endpoints:

```python
@router.post("/{kb_id}/favorite")
async def add_favorite(kb_id: _uuid.UUID, u=Depends(get_current_user), s: AsyncSession = Depends(get_session)):
    kb = await s.get(KnowledgeBase, kb_id)
    if not kb:
        raise HTTPException(404, "知识库不存在")
    existing = await s.get(KbFavorite, (u.id, kb_id))
    if not existing:
        s.add(KbFavorite(user_id=u.id, kb_id=kb_id))
        await s.commit()
    return {"ok": True}


@router.delete("/{kb_id}/favorite")
async def remove_favorite(kb_id: _uuid.UUID, u=Depends(get_current_user), s: AsyncSession = Depends(get_session)):
    existing = await s.get(KbFavorite, (u.id, kb_id))
    if existing:
        await s.delete(existing)
        await s.commit()
    return {"ok": True}
```

- [ ] **Step 2: Extend list_kb route with new params and logic**

Replace the `list_kb` function signature and body:

```python
@router.get("")
async def list_kb(
    kb_type: str | None = Query(None),
    search: str | None = Query(None),
    owner_id: str | None = Query(None),
    status: str | None = Query(None),
    is_favorite: bool | None = Query(None),
    sort_by: str = Query("created_at"),
    sort_order: str = Query("desc"),
    page: int = Query(1, ge=1),
    size: int = Query(20, ge=1, le=100),
    u=Depends(get_current_user),
    s: AsyncSession = Depends(get_session),
):
    # 文档数量子查询
    doc_count_subq = (
        select(func.count(Document.id))
        .where(Document.kb_id == KnowledgeBase.id)
        .correlate(KnowledgeBase)
        .scalar_subquery()
        .label("document_count")
    )

    # 收藏子查询
    is_fav_subq = (
        select(func.count(KbFavorite.kb_id))
        .where(and_(KbFavorite.kb_id == KnowledgeBase.id, KbFavorite.user_id == u.id))
        .correlate(KnowledgeBase)
        .scalar_subquery()
        .label("is_favorite")
    )

    q = select(
        KnowledgeBase,
        User.username.label("owner_name"),
        doc_count_subq,
        is_fav_subq,
    ).join(User, KnowledgeBase.owner_id == User.id)

    if kb_type:
        q = q.where(KnowledgeBase.kb_type == kb_type)

    if search:
        pattern = f"%{search}%"
        q = q.where(KnowledgeBase.name.ilike(pattern))

    if owner_id == "me":
        q = q.where(KnowledgeBase.owner_id == u.id)

    if status:
        q = q.where(KnowledgeBase.status == status)

    if is_favorite:
        q = q.where(
            KnowledgeBase.id.in_(
                select(KbFavorite.kb_id).where(KbFavorite.user_id == u.id)
            )
        )

    # 排序
    allowed_sort = {"created_at", "name", "kb_type"}
    col = sort_by if sort_by in allowed_sort else "created_at"
    sort_col = getattr(KnowledgeBase, col)
    if sort_order == "asc":
        q = q.order_by(sort_col.asc())
    else:
        q = q.order_by(sort_col.desc())

    # 计数
    count_q = select(func.count()).select_from(q.subquery())
    total = (await s.execute(count_q)).scalar() or 0

    # 分页
    offset = (page - 1) * size
    q = q.offset(offset).limit(size)

    rows = (await s.execute(q)).all()

    items = []
    for kb, owner_name, doc_count, fav_flag in rows:
        items.append({
            "id": str(kb.id),
            "name": kb.name,
            "description": kb.description or "",
            "kb_type": kb.kb_type,
            "owner_id": str(kb.owner_id),
            "owner_name": owner_name or "",
            "chunk_strategy": kb.chunk_strategy,
            "chunk_size": kb.chunk_size,
            "chunk_overlap": kb.chunk_overlap,
            "delimiter": kb.delimiter,
            "embedding_model": kb.embedding_model,
            "es_index_name": kb.es_index_name,
            "status": kb.status or "FULLY_PUBLISHED",
            "is_favorite": bool(fav_flag),
            "document_count": doc_count or 0,
            "created_at": kb.created_at.isoformat() if kb.created_at else None,
            "updated_at": kb.created_at.isoformat() if kb.created_at else None,
        })

    return {"items": items, "total": total, "page": page, "size": size}
```

- [ ] **Step 3: Verify route imports are correct**

```bash
cd services/kb-api && uv run python -c "from app.routes.knowledge_base import router; print('OK')"
```

- [ ] **Step 4: Commit**

```bash
git add services/kb-api/app/routes/knowledge_base.py
git commit -m "feat: add favorite endpoints + extend list_kb with owner/status/favorite filters"
```

---

### Task 5: Frontend types — 更新 KnowledgeBase interface

**Files:**
- Modify: `web/src/types/knowledge-base.ts`

**Interfaces:**
- Produces: `KnowledgeBase` with `status: string`, `is_favorite: boolean`

- [ ] **Step 1: Update KnowledgeBase interface**

In `web/src/types/knowledge-base.ts`, update the `KnowledgeBase` interface (add after `es_index_name`):

```typescript
export interface KnowledgeBase {
  id: string
  name: string
  description: string
  kb_type: KbType
  owner_id: string
  owner_name?: string
  chunk_strategy: ChunkStrategy
  chunk_size: number
  chunk_overlap: number
  embedding_model: string
  es_index_name: string
  status: string
  is_favorite: boolean
  document_count?: number
  created_at: string
  updated_at?: string
}
```

- [ ] **Step 2: Verify types compile**

```bash
cd web && pnpm type-check
```

- [ ] **Step 3: Commit**

```bash
git add web/src/types/knowledge-base.ts
git commit -m "feat: add status and is_favorite to KnowledgeBase type"
```

---

### Task 6: Frontend API — 新增 favorite API + 扩展 KbListParams

**Files:**
- Modify: `web/src/api/knowledge-base.ts`

**Interfaces:**
- Consumes: updated `KnowledgeBase` type
- Produces: `favoriteKnowledgeBase(id)`, `unfavoriteKnowledgeBase(id)`, extended `KbListParams`

- [ ] **Step 1: Extend KbListParams and add favorite functions**

In `web/src/api/knowledge-base.ts`, update `KbListParams`:

```typescript
export interface KbListParams extends PageQuery {
  kb_type?: KbType
  search?: string
  owner_id?: string
  status?: string
  is_favorite?: boolean
  sort_by?: string
  sort_order?: 'asc' | 'desc'
}
```

Add favorite API functions after `deleteKnowledgeBase`:

```typescript
export function favoriteKnowledgeBase(id: string) {
  return request.post<unknown, { ok: boolean }>(`/knowledge-bases/${id}/favorite`)
}

export function unfavoriteKnowledgeBase(id: string) {
  return request.delete<unknown, { ok: boolean }>(`/knowledge-bases/${id}/favorite`)
}
```

- [ ] **Step 2: Verify API module compiles**

```bash
cd web && pnpm type-check
```

- [ ] **Step 3: Commit**

```bash
git add web/src/api/knowledge-base.ts
git commit -m "feat: add favorite/unfavorite API + extend KbListParams"
```

---

### Task 7: Frontend index.vue — 重写搜索栏为多条件筛选栏

**Files:**
- Modify: `web/src/views/knowledge-base/index.vue`

**Interfaces:**
- Consumes: updated `listKnowledgeBases`, `favoriteKnowledgeBase`, `unfavoriteKnowledgeBase`
- Produces: redesigned filter bar with checkbox, 3 selects, search input, radio button view toggle

- [ ] **Step 1: Rewrite script section**

Replace the `<script setup>` block in `web/src/views/knowledge-base/index.vue`:

```typescript
<script setup lang="ts">
import { ref, onMounted, computed } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage, ElMessageBox } from 'element-plus'
import { Plus, Search, Delete, Setting, ArrowDown } from '@element-plus/icons-vue'
import PageContainer from '@/components/common/PageContainer.vue'
import KbCard from '@/components/kb/KbCard.vue'
import KbCreateDialog from '@/components/kb/KbCreateDialog.vue'
import { listKnowledgeBases, deleteKnowledgeBase, favoriteKnowledgeBase, unfavoriteKnowledgeBase } from '@/api/knowledge-base'
import type { KnowledgeBase, KbType } from '@/types/knowledge-base'
import { formatDate } from '@/utils/format'

const router = useRouter()

// State
const list = ref<KnowledgeBase[]>([])
const loading = ref(false)
const dialogVisible = ref(false)

// Filters
const filterType = ref<KbType | ''>('')
const filterOwner = ref<string>('')
const filterStatus = ref<string>('')
const filterFavorite = ref(false)
const searchKeyword = ref('')
const viewMode = ref<'card' | 'table'>('card')
const page = ref(1)
const size = ref(20)
const total = ref(0)

const typeOptions = [
  { label: '全部', value: '' },
  { label: '文档', value: 'DOCUMENT' },
  { label: 'FAQ', value: 'FAQ' },
]

const ownerOptions = [
  { label: '所有人', value: '' },
  { label: '由我创建', value: 'me' },
]

const statusOptions = [
  { label: '全部', value: '' },
  { label: '发布中', value: 'PUBLISHING' },
  { label: '完全发布', value: 'FULLY_PUBLISHED' },
  { label: '部分失败', value: 'PARTIALLY_FAILED' },
]

// Debounce timer
let debounceTimer: ReturnType<typeof setTimeout> | null = null

// Fetch data
async function fetchData() {
  loading.value = true
  try {
    const params: any = {
      search: searchKeyword.value || undefined,
      kb_type: filterType.value || undefined,
      owner_id: filterOwner.value || undefined,
      status: filterStatus.value || undefined,
      is_favorite: filterFavorite.value || undefined,
      sort_by: 'created_at',
      sort_order: 'desc',
      page: page.value,
      size: size.value,
    }
    const res = await listKnowledgeBases(params)
    list.value = res.items
    total.value = res.total
  } finally {
    loading.value = false
  }
}

// Filter change → reset page + refetch
function onFilterChange() {
  page.value = 1
  fetchData()
}

// Search handlers
function onSearchInput() {
  if (debounceTimer) clearTimeout(debounceTimer)
  const kw = searchKeyword.value.trim()
  if (kw.length >= 2) {
    debounceTimer = setTimeout(() => {
      page.value = 1
      fetchData()
    }, 300)
  } else if (kw.length === 0) {
    page.value = 1
    debounceTimer = setTimeout(fetchData, 100)
  }
}

function onSearchClear() {
  searchKeyword.value = ''
  page.value = 1
  fetchData()
}

// Toggle favorite
async function toggleFavorite(kb: KnowledgeBase, event: Event) {
  event.stopPropagation()
  try {
    if (kb.is_favorite) {
      await unfavoriteKnowledgeBase(kb.id)
      kb.is_favorite = false
      ElMessage.success('已取消收藏')
    } else {
      await favoriteKnowledgeBase(kb.id)
      kb.is_favorite = true
      ElMessage.success('已收藏')
    }
  } catch {
    ElMessage.error('操作失败')
  }
}

// Pagination
function onPageChange(p: number) {
  page.value = p
  fetchData()
}

function onSizeChange(s: number) {
  size.value = s
  page.value = 1
  fetchData()
}

// Navigation
function openDetail(kb: KnowledgeBase) {
  if (kb.kb_type === 'FAQ') {
    router.push(`/faq/${kb.id}`)
  } else {
    router.push(`/knowledge-bases/${kb.id}`)
  }
}

function openSettings(kb: KnowledgeBase) {
  if (kb.kb_type === 'FAQ') {
    router.push(`/faq/${kb.id}`)
  } else {
    router.push(`/knowledge-bases/${kb.id}`)
  }
}

// Delete
async function handleDelete(kb: KnowledgeBase) {
  try {
    await ElMessageBox.confirm(
      `删除「${kb.name}」将同时删除其所有文档和索引，确认删除？`,
      '警告',
      { type: 'warning', confirmButtonText: '确认删除', cancelButtonText: '取消' },
    )
    await deleteKnowledgeBase(kb.id)
    ElMessage.success('删除成功')
    fetchData()
  } catch {
    // cancelled
  }
}

// Status tag
function getStatusType(status?: string): '' | 'success' | 'warning' | 'danger' | 'info' {
  if (!status || status === 'FULLY_PUBLISHED') return 'success'
  if (status === 'PUBLISHING') return 'warning'
  if (status === 'PARTIALLY_FAILED') return 'danger'
  return 'info'
}

function getStatusLabel(status?: string): string {
  const map: Record<string, string> = {
    PUBLISHING: '发布中',
    FULLY_PUBLISHED: '完全发布',
    PARTIALLY_FAILED: '部分失败',
  }
  return map[status || ''] || status || '正常'
}

onMounted(fetchData)
</script>
```

- [ ] **Step 2: Rewrite template section**

Replace the `<template>` block from `<PageContainer>` opening to the pagination div. The template structure:

```html
<template>
  <PageContainer>
    <!-- Filter Bar -->
    <div class="filter-bar">
      <div class="filter-left">
        <el-button type="primary" :icon="Plus" @click="dialogVisible = true">添加知识库</el-button>
        <el-checkbox v-model="filterFavorite" label="仅展示收藏" @change="onFilterChange" />
        <el-select
          v-model="filterType"
          placeholder="知识库类型"
          style="width: 140px"
          clearable
          @change="onFilterChange"
        >
          <el-option v-for="opt in typeOptions" :key="opt.value" :label="opt.label" :value="opt.value" />
        </el-select>
        <el-select
          v-model="filterOwner"
          placeholder="归属人"
          style="width: 140px"
          clearable
          @change="onFilterChange"
        >
          <el-option v-for="opt in ownerOptions" :key="opt.value" :label="opt.label" :value="opt.value" />
        </el-select>
        <el-select
          v-model="filterStatus"
          placeholder="状态"
          style="width: 140px"
          clearable
          @change="onFilterChange"
        >
          <el-option v-for="opt in statusOptions" :key="opt.value" :label="opt.label" :value="opt.value" />
        </el-select>
      </div>
      <div class="filter-right">
        <el-input
          v-model="searchKeyword"
          placeholder="搜索知识库名称"
          style="width: 220px"
          clearable
          :prefix-icon="Search"
          @input="onSearchInput"
          @clear="onSearchClear"
        />
        <el-radio-group v-model="viewMode" class="view-toggle-radio">
          <el-radio-button value="card">
            <el-icon><Grid /></el-icon>
          </el-radio-button>
          <el-radio-button value="table">
            <el-icon><List /></el-icon>
          </el-radio-button>
        </el-radio-group>
      </div>
    </div>

    <!-- Card View -->
    <div v-if="viewMode === 'card'" v-loading="loading">
      <el-row v-if="list.length" :gutter="20">
        <el-col
          v-for="kb in list"
          :key="kb.id"
          :xs="24"
          :sm="12"
          :md="8"
          :lg="6"
          style="margin-bottom: 20px"
        >
          <KbCard :kb="kb" @delete="handleDelete(kb)" @toggle-favorite="toggleFavorite(kb, $event)" />
        </el-col>
      </el-row>
      <el-empty v-else description="暂无知识库" />
    </div>

    <!-- Table View -->
    <el-table
      v-else
      v-loading="loading"
      :data="list"
      stripe
      style="width: 100%"
      empty-text="暂无知识库"
    >
      <el-table-column label="知识库名称" min-width="180" prop="name">
        <template #default="{ row }: any">
          <el-link type="primary" @click="openDetail(row)">{{ row.name }}</el-link>
        </template>
      </el-table-column>
      <el-table-column label="描述" min-width="220" prop="description" show-overflow-tooltip>
        <template #default="{ row }: any">
          <span class="desc-text">{{ row.description || '暂无描述' }}</span>
        </template>
      </el-table-column>
      <el-table-column label="状态" width="110" prop="status">
        <template #default="{ row }: any">
          <el-tag :type="getStatusType(row.status)" size="small">{{ getStatusLabel(row.status) }}</el-tag>
        </template>
      </el-table-column>
      <el-table-column label="知识数量" width="100" prop="document_count">
        <template #default="{ row }: any">
          {{ row.document_count ?? 0 }}
        </template>
      </el-table-column>
      <el-table-column label="创建人" width="110" prop="owner_name">
        <template #default="{ row }: any">
          {{ row.owner_name || row.owner_id?.slice(0, 8) || '-' }}
        </template>
      </el-table-column>
      <el-table-column label="创建时间" width="170" prop="created_at">
        <template #default="{ row }: any">
          {{ formatDate(row.created_at) }}
        </template>
      </el-table-column>
      <el-table-column label="操作" width="200" fixed="right">
        <template #default="{ row }: any">
          <el-button
            :type="row.is_favorite ? 'warning' : 'default'"
            :icon="row.is_favorite ? StarFilled : Star"
            link
            size="small"
            @click="toggleFavorite(row, $event)"
          >
            {{ row.is_favorite ? '已收藏' : '收藏' }}
          </el-button>
          <el-button type="primary" link :icon="Setting" size="small" @click="openSettings(row)">
            设置
          </el-button>
          <el-button type="danger" link :icon="Delete" size="small" @click="handleDelete(row)">
            删除
          </el-button>
        </template>
      </el-table-column>
    </el-table>

    <!-- Pagination -->
    <div v-if="total > size" class="pagination-wrap">
      <el-pagination
        v-model:current-page="page"
        v-model:page-size="size"
        :total="total"
        :page-sizes="[10, 20, 50]"
        layout="total, sizes, prev, pager, next, jumper"
        @current-change="onPageChange"
        @size-change="onSizeChange"
      />
    </div>
  </PageContainer>

  <KbCreateDialog v-model="dialogVisible" @success="fetchData" />
</template>
```

- [ ] **Step 3: Add icons import**

Update icon imports in the script — add `StarFilled`, `Star`, `Grid`, `List`:

```typescript
import { Plus, Search, Delete, Setting, StarFilled, Star, Grid, List } from '@element-plus/icons-vue'
```

- [ ] **Step 4: Rewrite style section**

Replace the `<style scoped>` block:

```css
<style scoped>
.filter-bar {
  display: flex;
  justify-content: space-between;
  align-items: center;
  flex-wrap: wrap;
  gap: 10px;
  margin-bottom: 16px;
}

.filter-left {
  display: flex;
  align-items: center;
  gap: 10px;
  flex-wrap: wrap;
}

.filter-right {
  display: flex;
  align-items: center;
  gap: 10px;
}

.view-toggle-radio {
  flex-shrink: 0;
}

.desc-text {
  color: #909399;
  font-size: 13px;
}

.pagination-wrap {
  display: flex;
  justify-content: flex-end;
  margin-top: 16px;
}
</style>
```

- [ ] **Step 5: Verify build**

```bash
cd web && pnpm type-check
```

- [ ] **Step 6: Commit**

```bash
git add web/src/views/knowledge-base/index.vue
git commit -m "feat: redesign KB list filter bar with type/owner/status/favorite/search"
```

---

### Task 8: KbCard — 添加收藏按钮

**Files:**
- Modify: `web/src/components/kb/KbCard.vue`

**Interfaces:**
- Consumes: `KnowledgeBase` with `is_favorite`
- Emits: `toggle-favorite` event (parent handles API call)

- [ ] **Step 1: Update KbCard script**

In `web/src/components/kb/KbCard.vue`, update the `<script setup>` block:

```typescript
<script setup lang="ts">
import { Document, ChatDotRound, StarFilled, Star, Delete, FolderOpened, MoreFilled } from '@element-plus/icons-vue'
import { useRouter } from 'vue-router'
import type { KnowledgeBase } from '@/types/knowledge-base'
import { formatDate } from '@/utils/format'

const props = defineProps<{ kb: KnowledgeBase }>()
const emit = defineEmits<{
  (e: 'delete', id: string): void
  (e: 'toggle-favorite', event: Event): void
}>()
const router = useRouter()

function open() {
  if (props.kb.kb_type === 'FAQ') {
    router.push(`/faq/${props.kb.id}`)
  } else {
    router.push(`/knowledge-bases/${props.kb.id}`)
  }
}
</script>
```

- [ ] **Step 2: Update template — add star button in card header**

Replace the `.kb-card-header` div:

```html
<div class="kb-card-header">
  <el-icon size="32" :color="kb.kb_type === 'FAQ' ? '#67c23a' : '#409EFF'">
    <ChatDotRound v-if="kb.kb_type === 'FAQ'" />
    <Document v-else />
  </el-icon>
  <div class="header-actions">
    <el-icon
      class="star-btn"
      :class="{ 'is-favorite': kb.is_favorite }"
      :color="kb.is_favorite ? '#e6a23c' : '#909399'"
      @click.stop="emit('toggle-favorite', $event)"
    >
      <StarFilled v-if="kb.is_favorite" />
      <Star v-else />
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
</div>
```

- [ ] **Step 3: Update styles**

Add to the `<style scoped>` block:

```css
.header-actions {
  display: flex;
  align-items: center;
  gap: 4px;
}

.star-btn {
  cursor: pointer;
  font-size: 18px;
  transition: color 0.2s;
}
.star-btn:hover {
  color: #e6a23c !important;
}
```

- [ ] **Step 4: Verify build**

```bash
cd web && pnpm type-check
```

- [ ] **Step 5: Commit**

```bash
git add web/src/components/kb/KbCard.vue
git commit -m "feat: add favorite star button to KbCard"
```

---

### Task 9: E2E verification — smoke test

**Files:**
- None (manual verification)

- [ ] **Step 1: Start backend services**

```bash
# Terminal 1: API
cd services/kb-api && uv run uvicorn app.main:app --reload --port 8000
```

- [ ] **Step 2: Start frontend**

```bash
# Terminal 2
cd web && pnpm dev
```

- [ ] **Step 3: Verify filters work**

在浏览器中打开 KB 列表页，验证：
1. 「知识库类型」下拉切换 → 列表过滤正确
2. 「归属人」选择「由我创建」→ 只显示当前用户创建的 KB
3. 「状态」下拉选择各状态 → 过滤正确
4. 「仅展示收藏」checkbox 勾选 → 只显示已收藏 KB（初始为空）
5. 搜索框输入 KB 名称 → debounce 后正确过滤
6. 卡片上星形按钮 → 点击收藏/取消收藏，状态正确切换
7. 表格视图中的收藏按钮 → 功能正常
8. 视图切换 radio → 卡片/列表切换正常
9. 翻页 → 分页正常
10. 多个筛选条件叠加 → AND 逻辑正确

- [ ] **Step 4: Commit if no fixes needed, otherwise fix then commit**
```
