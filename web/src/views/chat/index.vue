<script setup lang="ts">
import { ref, onMounted } from 'vue'
import { ChatLineRound } from '@element-plus/icons-vue'
import PageContainer from '@/components/common/PageContainer.vue'
import SearchTraceDrawer from '@/components/common/SearchTraceDrawer.vue'
import { chat } from '@/api/chat'
import { listKnowledgeBases } from '@/api/knowledge-base'
import type { SearchResult } from '@/types/search'
import type { KnowledgeBase } from '@/types/knowledge-base'

const query = ref('')
const selectedKbIds = ref<string[]>([])
const topK = ref(5)
const kbOptions = ref<KnowledgeBase[]>([])

const answer = ref('')
const citations = ref<SearchResult[]>([])
const loading = ref(false)
const hasAsked = ref(false)

const drawerVisible = ref(false)
const selectedResult = ref<SearchResult | null>(null)

onMounted(async () => {
  const res = await listKnowledgeBases({ kb_type: 'DOCUMENT' })
  kbOptions.value = res.items
  selectedKbIds.value = res.items.map((k) => k.id)
})

async function handleAsk() {
  if (!query.value.trim() || selectedKbIds.value.length === 0) return
  loading.value = true
  hasAsked.value = true
  try {
    const res = await chat({
      query: query.value,
      kb_ids: selectedKbIds.value,
      top_k: topK.value,
    })
    answer.value = res.answer
    citations.value = res.citations || []
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
  <PageContainer title="RAG 问答">
    <div class="chat-panel">
      <div class="chat-input-row">
        <el-input
          v-model="query"
          size="large"
          type="textarea"
          :autosize="{ minRows: 2, maxRows: 5 }"
          placeholder="输入你的问题，将基于知识库生成带引用的回答..."
          @keyup.ctrl.enter="handleAsk"
        />
        <el-button type="primary" size="large" :loading="loading" :icon="ChatLineRound" @click="handleAsk">提问</el-button>
      </div>
      <div class="chat-filters">
        <el-select v-model="selectedKbIds" multiple collapse-tags collapse-tags-tooltip placeholder="选择知识库" style="width: 360px;">
          <el-option v-for="kb in kbOptions" :key="kb.id" :label="kb.name" :value="kb.id" />
        </el-select>
        <span class="filter-label">引用数量</span>
        <el-input-number v-model="topK" :min="1" :max="20" size="default" />
        <span class="filter-hint">Ctrl + Enter 快速提问</span>
      </div>
    </div>

    <div class="result-section" v-loading="loading">
      <template v-if="hasAsked && !loading">
        <div class="answer-card">
          <div class="section-title">回答</div>
          <div class="answer-text">{{ answer || '（未生成回答）' }}</div>
        </div>
        <div class="citations-card" v-if="citations.length">
          <div class="section-title">引用来源（{{ citations.length }}）</div>
          <div class="citation-list">
            <div v-for="(c, i) in citations" :key="c.chunk_id || i" class="citation-item">
              <div class="citation-index">[{{ i + 1 }}]</div>
              <div class="citation-body">
                <div class="citation-meta">
                  <el-tag size="small" :type="c.source_type === 'FAQ' ? 'success' : 'primary'">
                    {{ c.source_type === 'FAQ' ? 'FAQ' : '文档' }}
                  </el-tag>
                  <span class="doc-title">{{ c.document_title || '未知文档' }}</span>
                  <span v-if="c.page_number" class="page-info">第 {{ c.page_number }} 页</span>
                </div>
                <div class="citation-preview">{{ c.text }}</div>
              </div>
              <el-button link type="primary" size="small" @click="showTrace(c)">溯源</el-button>
            </div>
          </div>
        </div>
        <el-empty v-else description="无引用来源" />
      </template>
      <el-empty v-else-if="!hasAsked" description="输入问题后点击「提问」开始问答" />
    </div>
  </PageContainer>
  <SearchTraceDrawer v-model="drawerVisible" :result="selectedResult" />
</template>

<style scoped>
.chat-panel { background: #fff; padding: 20px; border-radius: 4px; margin-bottom: 16px; }
.chat-input-row { display: flex; gap: 12px; margin-bottom: 16px; align-items: flex-start; }
.chat-input-row .el-button { height: 40px; }
.chat-filters { display: flex; align-items: center; gap: 12px; flex-wrap: wrap; }
.filter-label { font-size: 14px; color: #606266; }
.filter-hint { font-size: 12px; color: #c0c4cc; margin-left: auto; }
.result-section { background: #fff; border-radius: 4px; padding: 20px; min-height: 200px; }
.section-title { font-size: 15px; font-weight: 600; color: #303133; margin-bottom: 12px; }
.answer-card { margin-bottom: 20px; }
.answer-text { font-size: 14px; line-height: 1.8; color: #303133; white-space: pre-wrap; word-break: break-word; }
.citation-list { display: flex; flex-direction: column; gap: 10px; }
.citation-item { display: flex; gap: 10px; padding: 12px; border: 1px solid #ebeef5; border-radius: 4px; }
.citation-index { font-weight: 600; color: #409EFF; flex-shrink: 0; }
.citation-body { flex: 1; min-width: 0; }
.citation-meta { display: flex; align-items: center; gap: 8px; margin-bottom: 6px; flex-wrap: wrap; }
.doc-title { font-size: 13px; color: #303133; font-weight: 500; }
.page-info { font-size: 12px; color: #909399; }
.citation-preview { font-size: 13px; color: #606266; line-height: 1.6; display: -webkit-box; -webkit-line-clamp: 2; -webkit-box-orient: vertical; overflow: hidden; }
</style>
