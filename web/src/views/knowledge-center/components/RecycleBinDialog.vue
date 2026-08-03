<script setup lang="ts">
/**
 * 回收站弹窗
 */
import { ref, watch } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { WarningFilled } from '@element-plus/icons-vue'
import { fetchRecycleBin, restoreDocument, permanentDeleteDocument } from '@/api/knowledge-center'
import { formatDate } from '@/utils/format'
import type { TrashItem } from '@/types/knowledge-center'

const props = defineProps<{
  modelValue: boolean
}>()

const emit = defineEmits<{
  (e: 'update:modelValue', val: boolean): void
  (e: 'success'): void
}>()

const items = ref<TrashItem[]>([])
const total = ref(0)
const loading = ref(false)
const page = ref(1)
const size = ref(20)
const selectedIds = ref<string[]>([])

async function loadData() {
  loading.value = true
  try {
    const res = await fetchRecycleBin({ page: page.value, size: size.value })
    items.value = res.items
    total.value = res.total
  } finally {
    loading.value = false
  }
}

function handlePageChange(p: number) {
  page.value = p
  loadData()
}

function handleSizeChange(s: number) {
  size.value = s
  page.value = 1
  loadData()
}

async function handleRestore(id: string) {
  try {
    await restoreDocument(id)
    ElMessage.success('已恢复')
    emit('success')
    loadData()
  } catch {
    // handled by interceptor
  }
}

async function handleDelete(id: string) {
  try {
    await ElMessageBox.confirm('确认永久删除该知识？此操作不可恢复', '警告', {
      type: 'warning',
      confirmButtonText: '确认删除',
      cancelButtonText: '取消',
    })
    await permanentDeleteDocument(id)
    ElMessage.success('已永久删除')
    emit('success')
    loadData()
  } catch {
    // cancelled or error
  }
}

function handleSelectionChange(rows: TrashItem[]) {
  selectedIds.value = rows.map((r) => r.id)
}

watch(
  () => props.modelValue,
  (val) => {
    if (val) {
      page.value = 1
      loadData()
    }
  },
)
</script>

<template>
  <el-dialog
    :model-value="modelValue"
    title="回收站"
    width="900px"
    @update:model-value="emit('update:modelValue', $event)"
  >
    <!-- 提示 -->
    <div class="trash-hint">
      <el-icon :size="16" color="#e6a23c"><WarningFilled /></el-icon>
      <span>20 天后将自动清理回收站</span>
    </div>

    <!-- 表格 -->
    <el-table
      :data="items"
      v-loading="loading"
      style="width: 100%"
      size="small"
      stripe
      @selection-change="handleSelectionChange"
    >
      <el-table-column type="selection" width="40" />
      <el-table-column label="知识标题" min-width="200" prop="original_filename" show-overflow-tooltip />
      <el-table-column label="原始目录" width="160" prop="directory_name">
        <template #default="{ row }">
          {{ row.directory_name || '-' }}
        </template>
      </el-table-column>
      <el-table-column label="操作人" width="100" prop="operator_name">
        <template #default="{ row }">
          {{ row.operator_name || '-' }}
        </template>
      </el-table-column>
      <el-table-column label="操作时间" width="160">
        <template #default="{ row }">
          {{ formatDate(row.deleted_at) }}
        </template>
      </el-table-column>
      <el-table-column label="剩余过期时间(天)" width="130">
        <template #default="{ row }">
          <span :class="{ 'expire-soon': row.remaining_days <= 5 }">
            {{ row.remaining_days }}
          </span>
        </template>
      </el-table-column>
      <el-table-column label="操作" width="140" fixed="right">
        <template #default="{ row }">
          <el-button link type="primary" size="small" @click="handleRestore(row.id)">
            恢复
          </el-button>
          <el-button link type="danger" size="small" @click="handleDelete(row.id)">
            删除
          </el-button>
        </template>
      </el-table-column>
    </el-table>

    <!-- 分页 -->
    <div class="trash-pagination">
      <span class="total-hint">共 {{ total }} 条</span>
      <el-pagination
        v-if="total > size"
        v-model:current-page="page"
        v-model:page-size="size"
        :total="total"
        :page-sizes="[20, 50]"
        layout="sizes, prev, pager, next"
        size="small"
        @current-change="handlePageChange"
        @size-change="handleSizeChange"
      />
    </div>

    <template #footer>
      <el-button @click="emit('update:modelValue', false)">关闭</el-button>
    </template>
  </el-dialog>
</template>

<style scoped>
.trash-hint {
  display: flex;
  align-items: center;
  gap: 6px;
  padding: 10px 12px;
  background: #fdf6ec;
  border-radius: 4px;
  margin-bottom: 12px;
  font-size: 13px;
  color: #e6a23c;
}

.trash-pagination {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-top: 12px;
}

.total-hint {
  font-size: 13px;
  color: #909399;
}

.expire-soon {
  color: #f56c6c;
  font-weight: 600;
}
</style>
