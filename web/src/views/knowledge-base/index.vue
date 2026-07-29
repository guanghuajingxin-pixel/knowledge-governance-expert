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
