<script setup lang="ts">
/**
 * 预览沙箱：模拟查询 + 模拟角色 → 真实检索 → 原始片段 vs 脱敏后上下文对比。
 * 不调用 LLM，展示命中规则与逐片段明细，用于策略上线前验证。
 */
import { ref, reactive, onMounted } from 'vue'
import { ElMessage } from 'element-plus'
import { VideoPlay } from '@element-plus/icons-vue'
import {
  maskingSandbox,
  type SandboxResult,
  type MaskScene,
} from '@/api/masking'
import { listKnowledgeLibraries } from '@/api/knowledge-library'
import { listKnowledgeBases } from '@/api/knowledge-base'
import { ROLE_OPTIONS, SCENE_OPTIONS, ENTITY_LABEL } from './constants'

const libraries = ref<{ id: number; name: string }[]>([])
const kbs = ref<{ id: string; name: string }[]>([])

const form = reactive({
  query: '',
  mock_role: 'viewer',
  scene: 'search',
  top_k: 6,
  kb_ids: [] as string[],
  library_ids: [] as number[],
})

const running = ref(false)
const result = ref<SandboxResult | null>(null)

onMounted(async () => {
  try {
    const [libs, kbPage] = await Promise.all([
      listKnowledgeLibraries(),
      listKnowledgeBases({ page: 1, size: 100 }),
    ])
    libraries.value = libs.map((l) => ({ id: l.id, name: l.name }))
    kbs.value = (kbPage.items || []).map((k) => ({ id: k.id, name: k.name }))
  } catch {
    // 选库降级为空（后端退化为无作用域过滤）
  }
})

async function run() {
  if (!form.query.trim()) return ElMessage.warning('请输入模拟查询')
  running.value = true
  result.value = null
  try {
    result.value = await maskingSandbox({
      query: form.query.trim(),
      mock_role: form.mock_role,
      scene: form.scene as MaskScene,
      top_k: form.top_k,
      kb_ids: form.kb_ids,
      library_ids: form.library_ids,
    })
  } catch (e: any) {
    ElMessage.error('沙箱运行失败：' + (e?.response?.data?.detail || e?.message || e))
  } finally {
    running.value = false
  }
}

const sourceTag: Record<string, string> = { local: '本地', dify: 'Dify', ragflow: 'RAGFlow' }

function detailFor(i: number) {
  return result.value?.detail?.find((d) => d.index === i)
}

function hitLabel(rule: string, entity: string): string {
  return `${rule}·${ENTITY_LABEL[entity as keyof typeof ENTITY_LABEL] || entity}`
}
</script>

<template>
  <div class="sb-wrap">
    <div class="tab-intro">
      以指定角色真实执行检索（不调 LLM），对比「原始召回片段」与「脱敏后上下文」，展示命中规则；
      用于策略上线前验证不同角色看到的内容差异。
    </div>

    <!-- 模拟表单 -->
    <div class="sb-form">
      <el-input v-model="form.query" placeholder="输入模拟查询，如：张三的客户联系方式和薪酬" clearable
        class="sb-query" @keyup.enter="run">
        <template #prepend>模拟查询</template>
      </el-input>
      <el-select v-model="form.mock_role" class="sb-role">
        <el-option v-for="r in ROLE_OPTIONS" :key="r.value" :label="`角色：${r.label}`" :value="r.value" />
      </el-select>
      <el-radio-group v-model="form.scene" class="sb-scene">
        <el-radio-button v-for="s in SCENE_OPTIONS" :key="s.value" :value="s.value">{{ s.label }}</el-radio-button>
      </el-radio-group>
      <el-button type="primary" :icon="VideoPlay" :loading="running" @click="run">运行预览</el-button>
    </div>
    <div class="sb-scope">
      <el-select v-model="form.kb_ids" multiple collapse-tags collapse-tags-tooltip filterable
        placeholder="限定本地知识库（不选 = 全部）" clearable class="sb-select">
        <el-option v-for="k in kbs" :key="k.id" :label="k.name" :value="k.id" />
      </el-select>
      <el-select v-model="form.library_ids" multiple collapse-tags collapse-tags-tooltip filterable
        placeholder="限定知识库镜像（不选 = 全部）" clearable class="sb-select">
        <el-option v-for="l in libraries" :key="l.id" :label="l.name" :value="l.id" />
      </el-select>
      <el-input-number v-model="form.top_k" :min="1" :max="15" controls-position="right" class="sb-topk" />
      <span class="sb-topk-label">召回条数</span>
    </div>

    <!-- 结果 -->
    <template v-if="result">
      <el-alert v-if="!result.masking_active" type="info" :closable="false"
        :title="result.note || '当前配置下无生效策略，返回内容未脱敏'" show-icon />
      <el-alert v-else type="success" :closable="false" show-icon>
        <template #title>
          脱敏生效：命中策略 {{ result.policies_applied.join('、') || '—' }}，
          共脱敏 {{ result.masked_count }} 处
          <template v-if="result.exempted_types?.length">
            ；豁免类型：{{ result.exempted_types.map((t) => ENTITY_LABEL[t as keyof typeof ENTITY_LABEL] || t).join('、') }}
          </template>
        </template>
      </el-alert>
      <el-alert v-if="result.local_error || result.dify_error || result.ragflow_error" type="warning"
        :closable="false" show-icon
        :title="[result.local_error, result.dify_error, result.ragflow_error].filter(Boolean).join('；')" />

      <!-- 命中规则汇总 -->
      <div v-if="result.summary?.length" class="sb-summary">
        <span class="summary-label">命中规则：</span>
        <el-tag v-for="(h, i) in result.summary" :key="i" size="small"
          :type="h.entity_type === 'custom' ? 'info' : 'warning'" effect="light" class="summary-tag">
          {{ hitLabel(h.rule, h.entity_type) }} ×{{ h.count }}
        </el-tag>
      </div>

      <!-- 原始 vs 脱敏 对比 -->
      <div v-if="result.raw.length" class="sb-compare">
        <div class="compare-head">
          <span class="col-title">原始召回片段（{{ result.raw.length }} 条）</span>
          <span class="col-title">脱敏后上下文（用户视角）</span>
        </div>
        <div v-for="(raw, i) in result.raw" :key="i" class="compare-row">
          <div class="frag-card raw">
            <div class="frag-title">
              <span class="frag-name">{{ raw.document_title || '—' }}</span>
              <el-tag size="small" effect="plain" type="info">{{ sourceTag[raw.source || ''] || raw.source }}</el-tag>
            </div>
            <div class="frag-content">{{ raw.content }}</div>
          </div>
          <div class="frag-card masked" :class="{ rejected: detailFor(i)?.rejected }">
            <div class="frag-title">
              <span class="frag-name">{{ result.masked[i]?.document_title || '—' }}</span>
              <template v-if="detailFor(i)">
                <el-tag v-if="detailFor(i)!.rejected" type="danger" size="small" effect="light">已拒绝返回</el-tag>
                <el-tag v-for="(h, j) in detailFor(i)!.hits" :key="j" type="warning" size="small" effect="light">
                  {{ hitLabel(h.rule, h.entity_type) }} ×{{ h.count }}
                </el-tag>
              </template>
            </div>
            <div v-if="detailFor(i)?.rejected" class="frag-content rejected-text">
              该片段命中「拒绝返回」动作，不进入送LLM上下文与检索结果。
            </div>
            <div v-else class="frag-content">{{ result.masked[i]?.content }}</div>
          </div>
        </div>
      </div>
      <el-empty v-else-if="!running" description="未召回任何片段，可调整查询词或作用域后重试" />
    </template>
    <el-empty v-else-if="!running" description="输入查询并点击「运行预览」，查看不同角色看到的脱敏效果" />
  </div>
</template>

<style scoped>
.sb-wrap {
  display: flex;
  flex-direction: column;
  gap: 12px;
}

.tab-intro {
  font-size: 13px;
  color: #909399;
  line-height: 1.6;
}

.sb-form {
  display: flex;
  align-items: center;
  gap: 10px;
}

.sb-query {
  flex: 1;
  min-width: 0;
}

.sb-role {
  width: 150px;
  flex-shrink: 0;
}

.sb-scene {
  flex-shrink: 0;
}

.sb-scope {
  display: flex;
  align-items: center;
  gap: 10px;
}

.sb-select {
  width: 280px;
}

.sb-topk {
  width: 110px;
  margin-left: auto;
}

.sb-topk-label {
  font-size: 13px;
  color: #909399;
}

.sb-summary {
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  gap: 6px;
}

.summary-label {
  font-size: 13px;
  color: #666;
}

.summary-tag {
  margin-right: 2px;
}

/* 对比区 */
.sb-compare {
  display: flex;
  flex-direction: column;
  gap: 10px;
}

.compare-head {
  display: flex;
  gap: 10px;
}

.col-title {
  flex: 1;
  font-size: 13px;
  font-weight: 600;
  color: #606266;
}

.compare-row {
  display: flex;
  gap: 10px;
}

.frag-card {
  flex: 1;
  min-width: 0;
  background: #fff;
  border-radius: 8px;
  padding: 10px 12px;
  box-shadow: 0 1px 3px rgba(0, 0, 0, 0.04);
  display: flex;
  flex-direction: column;
  gap: 6px;
}

.frag-card.raw {
  border-left: 3px solid var(--el-color-info);
}

.frag-card.masked {
  border-left: 3px solid var(--el-color-success);
}

.frag-card.rejected {
  border-left-color: var(--el-color-danger);
}

.frag-title {
  display: flex;
  align-items: center;
  gap: 6px;
  flex-wrap: wrap;
}

.frag-name {
  font-size: 13px;
  font-weight: 600;
  color: #303133;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.frag-content {
  font-size: 13px;
  color: #606266;
  line-height: 1.6;
  white-space: pre-wrap;
  word-break: break-all;
  max-height: 160px;
  overflow: auto;
}

.rejected-text {
  color: var(--el-color-danger);
}
</style>
