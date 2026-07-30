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

    <el-dialog :model-value="!!createdKey" title="API Key 已创建" width="480px" :close-on-click-modal="false" @update:model-value="(v: boolean) => { if (!v) createdKey = null }">
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
