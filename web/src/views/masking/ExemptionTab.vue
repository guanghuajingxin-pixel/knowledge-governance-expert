<script setup lang="ts">
/**
 * 豁免管理：绑定人 + 范围 + 实体类型 + 有效期，到期自动失效。
 * 豁免后该用户在对应范围内检索/问答时，相关实体类型返回明文（实际访问走脱敏审计留痕）。
 */
import { ref, reactive, onMounted } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { Plus, Refresh, Delete } from '@element-plus/icons-vue'
import {
  listMaskingExemptions,
  createMaskingExemption,
  deleteMaskingExemption,
  type MaskingExemption,
  type EntityType,
  type ScopeType,
} from '@/api/masking'
import { getUsers } from '@/api/users'
import { listKnowledgeLibraries } from '@/api/knowledge-library'
import { listKnowledgeBases } from '@/api/knowledge-base'
import { ENTITY_TYPES, ENTITY_LABEL, ROLE_LABEL } from './constants'

const exemptions = ref<MaskingExemption[]>([])
const loading = ref(false)

const users = ref<{ id: string; username: string; role: string }[]>([])
const libraries = ref<{ id: number; name: string }[]>([])
const kbs = ref<{ id: string; name: string }[]>([])

const userName = (id: string) => users.value.find((u) => u.id === id)?.username || '未知用户'
const userRole = (id: string) => {
  const u = users.value.find((x) => x.id === id)
  return u ? ROLE_LABEL[u.role] || u.role : ''
}
const scopeText = (e: MaskingExemption): string => {
  if (e.scope_type === 'global') return '全局'
  if (e.scope_type === 'library')
    return `镜像：${libraries.value.find((l) => String(l.id) === e.scope_id)?.name || e.scope_id}`
  return `本地库：${kbs.value.find((k) => k.id === e.scope_id)?.name || e.scope_id}`
}
const entityText = (e: MaskingExemption): string =>
  e.entity_types?.length ? e.entity_types.map((t) => ENTITY_LABEL[t]).join('、') : '全部类型'

const isExpired = (e: MaskingExemption): boolean =>
  !!e.expires_at && new Date(e.expires_at).getTime() < Date.now()

async function loadExemptions() {
  loading.value = true
  try {
    exemptions.value = await listMaskingExemptions()
  } catch (e: any) {
    ElMessage.error('加载豁免列表失败：' + (e?.message || e))
  } finally {
    loading.value = false
  }
}

onMounted(async () => {
  loadExemptions()
  try {
    const [u, libs, kbPage] = await Promise.all([
      getUsers(1, 100),
      listKnowledgeLibraries(),
      listKnowledgeBases({ page: 1, size: 100 }),
    ])
    users.value = (u.items || []).map((x) => ({ id: x.id, username: x.username, role: x.role }))
    libraries.value = libs.map((l) => ({ id: l.id, name: l.name }))
    kbs.value = (kbPage.items || []).map((k) => ({ id: k.id, name: k.name }))
  } catch {
    // 下拉降级
  }
})

// ===== 新增 =====
const dialogVisible = ref(false)
const saving = ref(false)
const expiresEnabled = ref(false)

const form = reactive({
  user_id: '',
  scope_type: 'global',
  scope_id: '',
  entity_types: [] as string[],
  reason: '',
  expires_at: '' as string | Date,
})

function openAdd() {
  Object.assign(form, {
    user_id: '', scope_type: 'global', scope_id: '',
    entity_types: [], reason: '', expires_at: '',
  })
  expiresEnabled.value = false
  dialogVisible.value = true
}

async function handleSave() {
  if (!form.user_id) return ElMessage.warning('请选择豁免用户')
  if (form.scope_type !== 'global' && !form.scope_id) return ElMessage.warning('请选择豁免范围对象')
  saving.value = true
  try {
    await createMaskingExemption({
      user_id: form.user_id,
      scope_type: form.scope_type as ScopeType,
      scope_id: form.scope_type === 'global' ? '' : form.scope_id,
      entity_types: form.entity_types as EntityType[],
      reason: form.reason,
      expires_at: expiresEnabled.value && form.expires_at
        ? new Date(form.expires_at).toISOString()
        : null,
    })
    ElMessage.success('豁免已创建')
    dialogVisible.value = false
    loadExemptions()
  } catch (e: any) {
    ElMessage.error('创建失败：' + (e?.response?.data?.detail || e?.message || e))
  } finally {
    saving.value = false
  }
}

async function handleDelete(row: MaskingExemption) {
  try {
    await ElMessageBox.confirm(
      `确认撤销用户「${row.username || userName(row.user_id)}」的豁免？撤销后立即恢复脱敏管控。`,
      '撤销确认',
      { type: 'warning', confirmButtonText: '撤销', cancelButtonText: '取消' },
    )
    await deleteMaskingExemption(row.id)
    ElMessage.success('已撤销')
    loadExemptions()
  } catch {
    // 用户取消
  }
}

function fmtTime(iso: string | null): string {
  if (!iso) return '永久'
  const d = new Date(iso)
  return Number.isNaN(d.getTime()) ? iso : d.toLocaleString('zh-CN', { hour12: false })
}
</script>

<template>
  <div class="et-wrap">
    <div class="tab-intro">
      豁免绑定「人 + 范围 + 实体类型 + 有效期」，到期自动失效；被豁免的实体类型在该用户检索/问答时返回明文，
      每次明文访问均记录在「脱敏审计」。请谨慎授权，并定期复核到期时间。
    </div>
    <div class="tab-toolbar">
      <el-button :icon="Refresh" :loading="loading" @click="loadExemptions">刷新</el-button>
      <el-button type="primary" :icon="Plus" @click="openAdd">新增豁免</el-button>
    </div>

    <el-table :data="exemptions" v-loading="loading" stripe style="width: 100%"
      empty-text="暂无豁免，点击「新增豁免」创建">
      <el-table-column label="豁免用户" width="170" show-overflow-tooltip>
        <template #default="{ row }">
          <span class="u-name">{{ row.username || userName(row.user_id) }}</span>
          <span class="u-role">{{ userRole(row.user_id) }}</span>
        </template>
      </el-table-column>
      <el-table-column label="豁免范围" width="190" show-overflow-tooltip>
        <template #default="{ row }">
          <span class="muted">{{ scopeText(row as MaskingExemption) }}</span>
        </template>
      </el-table-column>
      <el-table-column label="豁免实体类型" min-width="180" show-overflow-tooltip>
        <template #default="{ row }">
          <span class="muted">{{ entityText(row as MaskingExemption) }}</span>
        </template>
      </el-table-column>
      <el-table-column prop="reason" label="事由" min-width="160" show-overflow-tooltip>
        <template #default="{ row }">
          <span class="muted">{{ row.reason || '—' }}</span>
        </template>
      </el-table-column>
      <el-table-column label="授权人" width="110" show-overflow-tooltip>
        <template #default="{ row }">
          <span class="muted">{{ row.granted_by || '—' }}</span>
        </template>
      </el-table-column>
      <el-table-column label="有效期至" width="165">
        <template #default="{ row }">
          <div class="exp-cell">
            <span class="muted">{{ fmtTime(row.expires_at) }}</span>
            <el-tag v-if="isExpired(row as MaskingExemption)" type="info" size="small" effect="plain">已失效</el-tag>
          </div>
        </template>
      </el-table-column>
      <el-table-column label="操作" width="90" fixed="right">
        <template #default="{ row }">
          <el-button link type="danger" :icon="Delete" size="small" @click="handleDelete(row as MaskingExemption)">撤销</el-button>
        </template>
      </el-table-column>
    </el-table>

    <el-dialog v-model="dialogVisible" title="新增豁免" width="560px" :close-on-click-modal="false">
      <el-form :model="form" label-width="100px" class="et-form">
        <el-form-item label="豁免用户" required>
          <el-select v-model="form.user_id" filterable placeholder="选择用户" style="width: 100%">
            <el-option v-for="u in users" :key="u.id" :label="`${u.username}（${ROLE_LABEL[u.role] || u.role}）`" :value="u.id" />
          </el-select>
        </el-form-item>
        <el-form-item label="豁免范围">
          <el-radio-group v-model="form.scope_type">
            <el-radio-button value="global">全局</el-radio-button>
            <el-radio-button value="library">知识库镜像</el-radio-button>
            <el-radio-button value="kb">本地知识库</el-radio-button>
          </el-radio-group>
          <el-select v-if="form.scope_type === 'library'" v-model="form.scope_id" filterable
            placeholder="选择知识库镜像" class="scope-select">
            <el-option v-for="l in libraries" :key="l.id" :label="l.name" :value="String(l.id)" />
          </el-select>
          <el-select v-if="form.scope_type === 'kb'" v-model="form.scope_id" filterable
            placeholder="选择本地知识库" class="scope-select">
            <el-option v-for="k in kbs" :key="k.id" :label="k.name" :value="k.id" />
          </el-select>
        </el-form-item>
        <el-form-item label="实体类型">
          <el-checkbox-group v-model="form.entity_types" class="inline-check">
            <el-checkbox v-for="t in ENTITY_TYPES" :key="t" :value="t">{{ ENTITY_LABEL[t] }}</el-checkbox>
          </el-checkbox-group>
          <div class="form-hint">不勾选 = 豁免全部实体类型（高风险，建议明确指定）</div>
        </el-form-item>
        <el-form-item label="事由">
          <el-input v-model="form.reason" type="textarea" :rows="2" maxlength="500"
            placeholder="说明豁免的业务理由，便于审计追溯" />
        </el-form-item>
        <el-form-item label="有效期">
          <div class="switch-line">
            <el-switch v-model="expiresEnabled" />
            <span class="switch-text" :class="{ off: !expiresEnabled }">{{ expiresEnabled ? '限期' : '永久' }}</span>
          </div>
          <el-date-picker v-if="expiresEnabled" v-model="form.expires_at" type="datetime"
            placeholder="选择到期时间" format="YYYY-MM-DD HH:mm" date-format="YYYY-MM-DD"
            time-format="HH:mm" class="exp-picker" />
          <div class="form-hint">到期后豁免自动失效；明文访问全程记录审计日志</div>
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="dialogVisible = false">取消</el-button>
        <el-button type="primary" :loading="saving" @click="handleSave">创建豁免</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<style scoped>
.et-wrap {
  display: flex;
  flex-direction: column;
  gap: 12px;
}

.tab-intro {
  font-size: 13px;
  color: #909399;
  line-height: 1.6;
}

.tab-toolbar {
  display: flex;
  justify-content: flex-end;
  gap: 8px;
}

.tab-toolbar .el-button + .el-button {
  margin-left: 0;
}

.u-name {
  font-weight: 600;
  color: #303133;
  margin-right: 6px;
}

.u-role {
  font-size: 12px;
  color: #999;
}

.muted {
  color: #909399;
  font-size: 13px;
}

.exp-cell {
  display: flex;
  align-items: center;
  gap: 6px;
}

.inline-check {
  display: inline-flex;
  flex-wrap: wrap;
  column-gap: 4px;
}

.form-hint {
  font-size: 12px;
  color: #999;
  margin-top: 4px;
  width: 100%;
}

.scope-select {
  margin-left: 12px;
  width: 220px;
}

.switch-line {
  display: flex;
  align-items: center;
  gap: 8px;
}

.switch-text {
  font-size: 12px;
  color: var(--el-color-success);
}

.switch-text.off {
  color: var(--el-color-info);
}

.exp-picker {
  margin-left: 12px;
  width: 200px;
}

.et-form {
  padding: 0 8px;
}
</style>
