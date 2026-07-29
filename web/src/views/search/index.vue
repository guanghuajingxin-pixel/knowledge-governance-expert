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
            <el-button link type="primary" size="small" @click="showTrace(row as SearchResult)">溯源</el-button>
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
