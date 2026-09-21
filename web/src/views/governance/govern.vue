<script setup lang="ts">
import { onMounted, ref, computed } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ElMessage, ElMessageBox } from 'element-plus'
import KnowledgeGaps from './components/KnowledgeGaps.vue'
import { useUserStore } from '@/stores/user'
import {
  getStandards, createStandard, updateStandard, deleteStandard,
  getVersions, rollbackVersion, submitReview, approveStandard, rejectStandard,
  importStandardsFromDingtalk, searchDingtalkUsers,
  type StandardDoc, type StandardVersion, type StandardPayload, type DingtalkUser,
} from '@/api/governance'

const route = useRoute()
const router = useRouter()
const userStore = useUserStore()
const isAdmin = computed(() => ['super_admin', 'admin'].includes(userStore.userInfo?.role || ''))

const activeTab = ref('gaps')

// ===== 列表数据 =====
const standards = ref<StandardDoc[]>([])
const standardsLoading = ref(false)

async function loadStandards() {
  standardsLoading.value = true
  try {
    const res = await getStandards()
    if (res.error) {
      ElMessage.error(res.error)
      return
    }
    standards.value = res.items
  } finally {
    standardsLoading.value = false
  }
}

// 状态标签配色
const statusTag: Record<string, string> = {
  draft: 'info',
  reviewing: 'warning',
  published: 'success',
  rejected: 'danger',
}
const statusLabel: Record<string, string> = {
  draft: '草稿',
  reviewing: '审核中',
  published: '已发布',
  rejected: '已驳回',
}

// ===== 从钉钉导入（仅本地为空时提示） =====
async function handleImport() {
  try {
    await ElMessageBox.confirm('将从钉钉多维表《杰克知识管理规范》导入本地不存在的标准，是否继续？', '导入确认')
  } catch { return }
  const res = await importStandardsFromDingtalk()
  ElMessage.success(`导入完成，新增 ${res.imported} 条`)
  await loadStandards()
}

// ===== 编辑弹窗 =====
const editDialogVisible = ref(false)
const editingId = ref<string | null>(null)
const editForm = ref<StandardPayload>({
  doc_type: '', code: '', version: '', effective_date: '', link: '', maintainer: '',
})

function openCreate() {
  editingId.value = null
  editForm.value = { doc_type: '', code: '', version: '', effective_date: '', link: '', maintainer: '' }
  editDialogVisible.value = true
}

function openEdit(row: any) {
  editingId.value = row.id
  editForm.value = {
    doc_type: row.doc_type, code: row.code, version: row.version,
    effective_date: row.effective_date, link: row.link, maintainer: row.maintainer,
  }
  editDialogVisible.value = true
}

async function saveEdit() {
  if (!editForm.value.doc_type.trim()) {
    ElMessage.warning('请填写文档类型')
    return
  }
  try {
    if (editingId.value) {
      await updateStandard(editingId.value, editForm.value)
      ElMessage.success('已生成新版本（草稿）')
    } else {
      await createStandard(editForm.value)
      ElMessage.success('已创建')
    }
    editDialogVisible.value = false
    await loadStandards()
  } catch (e: any) {
    ElMessage.error(e?.response?.data?.detail || '保存失败')
  }
}

// ===== 删除 =====
async function handleDelete(row: any) {
  try {
    await ElMessageBox.confirm(`确定删除「${row.doc_type}」吗？所有历史版本将一并删除。`, '删除确认', { type: 'warning' })
  } catch { return }
  await deleteStandard(row.id)
  ElMessage.success('已删除')
  await loadStandards()
}

// ===== 历史记录弹窗 =====
const historyDialogVisible = ref(false)
const historyVersions = ref<StandardVersion[]>([])
const historyLoading = ref(false)

async function openHistory(row: any) {
  historyDialogVisible.value = true
  historyLoading.value = true
  try {
    const res = await getVersions(row.id)
    historyVersions.value = res.items
  } finally {
    historyLoading.value = false
  }
}

async function handleRollback(stdId: string, ver: any) {
  try {
    await ElMessageBox.confirm(`回滚到 V${ver.version_no}（${ver.doc_type}）？将生成新的草稿版本。`, '回滚确认')
  } catch { return }
  await rollbackVersion(stdId, ver.id)
  ElMessage.success('已回滚为新草稿版本')
  historyDialogVisible.value = false
  await loadStandards()
}

// ===== 提交审核弹窗（选择审批人） =====
const reviewDialogVisible = ref(false)
const reviewingId = ref<string | null>(null)
const reviewerQuery = ref('')
const reviewerOptions = ref<DingtalkUser[]>([])
const selectedReviewer = ref<DingtalkUser | null>(null)
const reviewSearching = ref(false)
let reviewSearchTimer: any = null

function openSubmitReview(row: any) {
  reviewingId.value = row.id
  selectedReviewer.value = null
  reviewerQuery.value = ''
  reviewerOptions.value = []
  reviewDialogVisible.value = true
}

function onReviewerQuery(q: string) {
  clearTimeout(reviewSearchTimer)
  if (!q.trim()) { reviewerOptions.value = []; return }
  reviewSearching.value = true
  reviewSearchTimer = setTimeout(async () => {
    try {
      const res = await searchDingtalkUsers(q)
      reviewerOptions.value = res.items
    } finally {
      reviewSearching.value = false
    }
  }, 300)
}

async function confirmSubmitReview() {
  if (!selectedReviewer.value) {
    ElMessage.warning('请选择审批人')
    return
  }
  if (!reviewingId.value) return
  try {
    const res = await submitReview(reviewingId.value, selectedReviewer.value.userid, selectedReviewer.value.name)
    if (res.message_error) {
      ElMessage.warning(`审核已提交，但钉钉消息发送失败：${res.message_error}`)
    } else {
      ElMessage.success(`已提交审核，钉钉卡片已发送给 ${selectedReviewer.value.name}`)
    }
    reviewDialogVisible.value = false
    await loadStandards()
  } catch (e: any) {
    ElMessage.error(e?.response?.data?.detail || '提交失败')
  }
}

// ===== 审批（通过/驳回）=====
async function handleApprove(row: any) {
  try {
    const { value: comment } = await ElMessageBox.prompt('请输入审批意见（可选）', '审核通过', { confirmButtonText: '通过' })
    await approveStandard(row.id, comment || '')
    ElMessage.success('已通过，文档已发布')
    await loadStandards()
  } catch (e: any) {
    if (e !== 'cancel') ElMessage.error(e?.response?.data?.detail || '操作失败')
  }
}

async function handleReject(row: any) {
  try {
    const { value } = await ElMessageBox.prompt('请输入驳回原因', '审核驳回', { confirmButtonText: '驳回', inputType: 'textarea' })
    if (!value?.trim()) { ElMessage.warning('请填写驳回原因'); return }
    await rejectStandard(row.id, value)
    ElMessage.success('已驳回')
    await loadStandards()
  } catch (e: any) {
    if (e !== 'cancel') ElMessage.error(e?.response?.data?.detail || '操作失败')
  }
}

// ===== 处理钉钉卡片跳转的审批参数 =====
onMounted(async () => {
  await loadStandards()
  const approveId = route.query.approve as string
  const action = route.query.action as string
  if (approveId && action) {
    const target = standards.value.find(s => s.id === approveId)
    if (target && target.status === 'reviewing') {
      try {
        if (action === 'approve') {
          await ElMessageBox.confirm(`确认通过「${target.doc_type}」的审核？`, '审核通过')
          await approveStandard(approveId, '')
          ElMessage.success('已通过，文档已发布')
        } else if (action === 'reject') {
          const { value } = await ElMessageBox.prompt('请输入驳回原因', '审核驳回', { inputType: 'textarea' })
          if (!value?.trim()) { ElMessage.warning('请填写驳回原因'); return }
          await rejectStandard(approveId, value)
          ElMessage.success('已驳回')
        }
        await loadStandards()
      } catch (e) { /* 用户取消 */ }
    }
    // 清除 URL 参数，避免刷新重复触发
    router.replace({ query: {} })
  }
})

// 操作列可编辑状态：草稿/已驳回/已发布 可编辑（已发布编辑会生成新版本）
const canEdit = (row: any) => ['draft', 'rejected', 'published'].includes(row.status)
// 可提交审核：草稿/已驳回
const canSubmit = (row: any) => ['draft', 'rejected'].includes(row.status)
</script>

<template>
  <div class="kge-page">
    <el-tabs v-model="activeTab">
      <el-tab-pane label="知识缺口" name="gaps" lazy><KnowledgeGaps /></el-tab-pane>

      <!-- 治理标准 -->
      <el-tab-pane label="治理标准" name="standard">
        <el-card class="card" shadow="never">
          <template #header>
            <div class="card-header">
              <span>知识治理标准 <el-tag size="small" type="info">本地管理 · 版本审核</el-tag></span>
              <div class="src">
                <el-button size="small" @click="handleImport">从钉钉导入</el-button>
                <el-button size="small" type="primary" @click="openCreate">+ 新建标准</el-button>
                <el-button size="small" :loading="standardsLoading" @click="loadStandards">刷新</el-button>
              </div>
            </div>
          </template>
          <el-table :data="standards" v-loading="standardsLoading" style="width: 100%">
            <el-table-column prop="doc_type" label="文档类型" min-width="150" show-overflow-tooltip />
            <el-table-column prop="code" label="类型编号" width="170" show-overflow-tooltip />
            <el-table-column prop="version" label="版本号" width="90" />
            <el-table-column label="状态" width="100">
              <template #default="{ row }">
                <el-tag :type="(statusTag[row.status] || 'info') as any">{{ statusLabel[row.status] || row.status }}</el-tag>
              </template>
            </el-table-column>
            <el-table-column prop="effective_date" label="生效日期" width="110" />
            <el-table-column prop="maintainer" label="维护人" width="100" show-overflow-tooltip />
            <el-table-column label="规范链接" min-width="180">
              <template #default="{ row }">
                <el-link v-if="row.link" type="primary" :href="row.link" target="_blank" style="font-size: 12.5px">{{ row.link }}</el-link>
                <span v-else style="color: #c0c4cc">—</span>
              </template>
            </el-table-column>
            <el-table-column label="操作" width="180" fixed="right">
              <template #default="{ row }">
                <el-button v-if="canEdit(row)" type="primary" link size="small" @click="openEdit(row)">编辑</el-button>
                <el-button v-if="canSubmit(row)" type="success" link size="small" @click="openSubmitReview(row)">提交审核</el-button>
                <el-button type="primary" link size="small" @click="openHistory(row)">历史</el-button>
                <el-dropdown trigger="click" @command="(cmd: string) => cmd === 'delete' ? handleDelete(row) : (cmd === 'approve' ? handleApprove(row) : handleReject(row))">
                  <el-button link size="small">…</el-button>
                  <template #dropdown>
                    <el-dropdown-menu>
                      <el-dropdown-item v-if="row.status === 'reviewing' && isAdmin" command="approve">审核通过</el-dropdown-item>
                      <el-dropdown-item v-if="row.status === 'reviewing' && isAdmin" command="reject">审核驳回</el-dropdown-item>
                      <el-dropdown-item command="delete" style="color: #f56c6c">删除</el-dropdown-item>
                    </el-dropdown-menu>
                  </template>
                </el-dropdown>
              </template>
            </el-table-column>
          </el-table>
        </el-card>
      </el-tab-pane>
    </el-tabs>

    <!-- 编辑弹窗 -->
    <el-dialog v-model="editDialogVisible" :title="editingId ? '编辑标准（生成新版本）' : '新建标准'" width="560px">
      <el-form :model="editForm" label-width="90px">
        <el-form-item label="文档类型" required>
          <el-input v-model="editForm.doc_type" placeholder="如：管理制度类" />
        </el-form-item>
        <el-form-item label="类型编号">
          <el-input v-model="editForm.code" placeholder="如：DOC-20260905-0001" />
        </el-form-item>
        <el-form-item label="版本号">
          <el-input v-model="editForm.version" placeholder="如：V2.3" />
        </el-form-item>
        <el-form-item label="生效日期">
          <el-date-picker v-model="editForm.effective_date" type="date" value-format="YYYY-MM-DD" style="width: 100%" />
        </el-form-item>
        <el-form-item label="规范链接">
          <el-input v-model="editForm.link" placeholder="https://..." />
        </el-form-item>
        <el-form-item label="维护人">
          <el-input v-model="editForm.maintainer" placeholder="维护人姓名" />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="editDialogVisible = false">取消</el-button>
        <el-button type="primary" @click="saveEdit">保存</el-button>
      </template>
    </el-dialog>

    <!-- 历史记录弹窗 -->
    <el-dialog v-model="historyDialogVisible" title="历史版本" width="720px">
      <el-table :data="historyVersions" v-loading="historyLoading" style="width: 100%">
        <el-table-column prop="version_no" label="版本" width="70">
          <template #default="{ row }">V{{ row.version_no }}</template>
        </el-table-column>
        <el-table-column label="状态" width="90">
          <template #default="{ row }">
            <el-tag :type="(statusTag[row.status] || 'info') as any" size="small">{{ statusLabel[row.status] || row.status }}</el-tag>
          </template>
        </el-table-column>
        <el-table-column prop="doc_type" label="文档类型" min-width="120" show-overflow-tooltip />
        <el-table-column prop="version" label="版本号" width="80" />
        <el-table-column prop="created_by" label="创建人" width="90" />
        <el-table-column label="创建时间" width="150">
          <template #default="{ row }">{{ row.created_at?.replace('T', ' ').slice(0, 16) }}</template>
        </el-table-column>
        <el-table-column label="操作" width="80" fixed="right">
          <template #default="{ row }">
            <el-button v-if="row.id !== historyVersions[0]?.id" type="primary" link size="small" @click="handleRollback(row.standard_id, row)">回滚</el-button>
            <span v-else style="color: #c0c4cc">当前</span>
          </template>
        </el-table-column>
      </el-table>
      <div v-if="historyVersions[0]?.review_comment" class="review-comment">
        <b>最新审核意见：</b>{{ historyVersions[0].review_comment }}
      </div>
    </el-dialog>

    <!-- 提交审核弹窗 -->
    <el-dialog v-model="reviewDialogVisible" title="提交审核" width="480px">
      <el-form label-width="90px">
        <el-form-item label="审批人">
          <el-select
            v-model="selectedReviewer"
            filterable
            remote
            reserve-keyword
            placeholder="搜索钉钉用户"
            :remote-method="onReviewerQuery"
            :loading="reviewSearching"
            value-key="userid"
            style="width: 100%"
          >
            <el-option
              v-for="u in reviewerOptions"
              :key="u.userid"
              :label="u.name"
              :value="u"
            />
          </el-select>
        </el-form-item>
      </el-form>
      <div class="tip">提交后将向审批人发送钉钉卡片消息，审批人点击卡片即可完成审批。</div>
      <template #footer>
        <el-button @click="reviewDialogVisible = false">取消</el-button>
        <el-button type="primary" @click="confirmSubmitReview">提交审核</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<style scoped>
.card { margin-bottom: 16px; }
.card-header { display: flex; align-items: center; justify-content: space-between; }
.src { display: flex; align-items: center; gap: 8px; }
.tip { font-size: 12px; color: #909399; margin-top: -8px; }
.review-comment { margin-top: 12px; font-size: 13px; color: #606266; background: #f5f7fa; padding: 8px 12px; border-radius: 4px; }
</style>
