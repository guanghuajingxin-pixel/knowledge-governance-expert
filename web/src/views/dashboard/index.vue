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
