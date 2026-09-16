<script setup lang="ts">
import { ref, onMounted } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage, ElMessageBox } from 'element-plus'
import { Plus, ChatDotRound, MoreFilled } from '@element-plus/icons-vue'
import PageContainer from '@/components/common/PageContainer.vue'
import KbCreateDialog from '@/components/kb/KbCreateDialog.vue'
import { listKnowledgeBases, deleteKnowledgeBase } from '@/api/knowledge-base'
import type { KnowledgeBase } from '@/types/knowledge-base'

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
  <KbCreateDialog v-model="dialogVisible" fixed-type="FAQ" @success="fetchData" />
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
