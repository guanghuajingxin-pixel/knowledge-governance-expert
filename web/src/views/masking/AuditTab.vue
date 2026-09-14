<script setup lang="ts">
/**
 * 脱敏审计：实际检索/问答时的脱敏命中、豁免、阻断记录。
 * 日志自身脱敏——只记规则标签与命中数量，不存原文敏感实体。
 */
import { ref, reactive, onMounted } from 'vue'
import { ElMessage } from 'element-plus'
import { Refresh, Search } from '@element-plus/icons-vue'
import {
  listMaskingLogs,
  type MaskingLog,
} from '@/api/masking'
import { ENTITY_LABEL, SCENE_LABEL, NODE_LABEL } from './constants'

const logs = ref<MaskingLog[]>([])
const total = ref(0)
const loading = ref(false)

const filters = reactive({
  scene: '',
  node: '',
  page: 1,
  pageSize: 20,
})

async function loadLogs() {
  loading.value = true
  try {
    const res = await listMaskingLogs({
      scene: filters.scene || undefined,
      node: filters.node || undefined,
      page: filters.page,
      page_size: filters.pageSize,
    })
    logs.value = res.items || []
    total.value = res.total || 0
  } catch (e: any) {
    ElMessage.error('加载审计日志失败：' + (e?.message || e))
  } finally {
    loading.value = false
  }
}

onMounted(loadLogs)

function sceneText(s: string): string {
  return SCENE_LABEL[s] || (s === 'sandbox' ? '沙箱' : s)
}

function nodeText(n: string): string {
  return NODE_LABEL[n] || n
}

function hitText(rule: string, entity: string): string {
  return `${rule}·${ENTITY_LABEL[entity as keyof typeof ENTITY_LABEL] || entity}`
}

function fmtTime(iso: string): string {
  if (!iso) return '—'
  const d = new Date(iso)
  return Number.isNaN(d.getTime()) ? iso : d.toLocaleString('zh-CN', { hour12: false })
}
</script>

<template>
  <div class="at-wrap">
    <div class="tab-intro">
      记录实际检索/问答链路中的脱敏行为：命中规则、脱敏数量、豁免与阻断；日志不含敏感原文，可放心用于治理复盘。
    </div>
    <div class="tab-toolbar">
      <el-select v-model="filters.scene" placeholder="全部场景" clearable class="filter-select" @change="filters.page = 1; loadLogs()">
        <el-option label="统一检索" value="search" />
        <el-option label="RAG 问答" value="chat" />
        <el-option label="沙箱预览" value="sandbox" />
      </el-select>
      <el-select v-model="filters.node" placeholder="全部节点" clearable class="filter-select" @change="filters.page = 1; loadLogs()">
        <el-option label="送LLM前" value="pre_llm" />
        <el-option label="输出后过滤" value="post_output" />
      </el-select>
      <el-button :icon="Refresh" :loading="loading" @click="loadLogs">刷新</el-button>
      <div class="toolbar-total">
        <el-icon><Search /></el-icon>
        共 {{ total }} 条记录
      </div>
    </div>

    <el-table :data="logs" v-loading="loading" stripe style="width: 100%"
      empty-text="暂无脱敏记录，实际检索/问答命中策略后自动写入">
      <el-table-column label="时间" width="165">
        <template #default="{ row }">
          <span class="muted">{{ fmtTime(row.created_at) }}</span>
        </template>
      </el-table-column>
      <el-table-column prop="username" label="用户" width="120" show-overflow-tooltip>
        <template #default="{ row }">
          <span>{{ row.username || '—' }}</span>
        </template>
      </el-table-column>
      <el-table-column label="场景" width="100">
        <template #default="{ row }">
          <el-tag size="small" effect="plain">{{ sceneText(row.scene) }}</el-tag>
        </template>
      </el-table-column>
      <el-table-column label="节点" width="110">
        <template #default="{ row }">
          <span class="muted">{{ nodeText(row.node) }}</span>
        </template>
      </el-table-column>
      <el-table-column prop="query" label="查询内容" min-width="180" show-overflow-tooltip>
        <template #default="{ row }">
          <span class="mono">{{ row.query || '—' }}</span>
        </template>
      </el-table-column>
      <el-table-column label="命中规则" min-width="220">
        <template #default="{ row }">
          <div class="hit-tags">
            <el-tag v-for="(h, i) in (row.rule_hits || []).slice(0, 4)" :key="i" size="small"
              :type="h.entity_type === 'custom' ? 'info' : 'warning'" effect="light">
              {{ hitText(h.rule, h.entity_type) }} ×{{ h.count }}
            </el-tag>
            <el-tooltip v-if="(row.rule_hits || []).length > 4" placement="top">
              <template #content>
                <div v-for="(h, i) in row.rule_hits" :key="i">{{ hitText(h.rule, h.entity_type) }} ×{{ h.count }}</div>
              </template>
              <el-tag size="small" type="info" effect="plain">+{{ row.rule_hits.length - 4 }}</el-tag>
            </el-tooltip>
            <span v-if="!(row.rule_hits || []).length" class="muted">—</span>
          </div>
        </template>
      </el-table-column>
      <el-table-column prop="masked_count" label="脱敏数" width="80" align="center" />
      <el-table-column label="结果" width="90">
        <template #default="{ row }">
          <el-tag v-if="row.blocked" type="danger" size="small" effect="light">阻断</el-tag>
          <el-tag v-else-if="row.exempted" type="success" size="small" effect="light">豁免放行</el-tag>
          <el-tag v-else type="info" size="small" effect="plain">已处理</el-tag>
        </template>
      </el-table-column>
    </el-table>

    <div class="pager">
      <el-pagination
        v-model:current-page="filters.page"
        v-model:page-size="filters.pageSize"
        :total="total"
        :page-sizes="[20, 50, 100]"
        layout="total, sizes, prev, pager, next"
        @current-change="loadLogs"
        @size-change="filters.page = 1; loadLogs()"
      />
    </div>
  </div>
</template>

<style scoped>
.at-wrap {
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
  align-items: center;
  gap: 10px;
}

.filter-select {
  width: 140px;
}

.toolbar-total {
  margin-left: auto;
  display: flex;
  align-items: center;
  gap: 6px;
  font-size: 13px;
  color: #909399;
}

.muted {
  color: #909399;
  font-size: 13px;
}

.mono {
  font-family: 'Menlo', 'Consolas', monospace;
  font-size: 12px;
}

.hit-tags {
  display: flex;
  flex-wrap: wrap;
  gap: 4px;
}

.pager {
  display: flex;
  justify-content: flex-end;
}
</style>
