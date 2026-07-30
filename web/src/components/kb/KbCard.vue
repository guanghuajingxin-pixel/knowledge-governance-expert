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

<template>
  <el-card class="kb-card" shadow="hover" @click="open">
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
