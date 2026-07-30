<script setup lang="ts">
import { ref, onMounted } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { Plus } from '@element-plus/icons-vue'
import PageContainer from '@/components/common/PageContainer.vue'
import { getUsers, createUser, updateUser, deleteUser } from '@/api/users'
import type { UserInfo, UserRole } from '@/types/user'
import { formatDate } from '@/utils/format'

const users = ref<UserInfo[]>([])
const loading = ref(false)
const total = ref(0)
const page = ref(1)
const size = ref(20)

const roleMap: Record<UserRole, { label: string; type: 'danger' | 'warning' | 'success' | 'info' }> = {
  super_admin: { label: '超级管理员', type: 'danger' },
  admin: { label: '管理员', type: 'warning' },
  editor: { label: '编辑者', type: 'success' },
  viewer: { label: '查看者', type: 'info' },
}

const roleOptions: { value: UserRole; label: string }[] = [
  { value: 'super_admin', label: '超级管理员' },
  { value: 'admin', label: '管理员' },
  { value: 'editor', label: '编辑者' },
  { value: 'viewer', label: '查看者' },
]

async function fetchData() {
  loading.value = true
  try {
    const res = await getUsers(page.value, size.value)
    users.value = res.items
    total.value = res.total
  } finally {
    loading.value = false
  }
}

function handlePageChange(p: number) {
  page.value = p
  fetchData()
}
function handleSizeChange(s: number) {
  size.value = s
  page.value = 1
  fetchData()
}

// 新建/编辑共用 dialog
const dialogVisible = ref(false)
const dialogMode = ref<'create' | 'edit'>('create')
const form = ref<{
  id?: string
  username: string
  password: string
  email: string
  role: UserRole
  is_active: boolean
}>({ username: '', password: '', email: '', role: 'viewer', is_active: true })

function openCreate() {
  dialogMode.value = 'create'
  form.value = { username: '', password: '', email: '', role: 'viewer', is_active: true }
  dialogVisible.value = true
}

function openEdit(row: UserInfo) {
  dialogMode.value = 'edit'
  form.value = {
    id: row.id,
    username: row.username,
    password: '',
    email: row.email || '',
    role: row.role,
    is_active: row.is_active,
  }
  dialogVisible.value = true
}

async function handleSubmit() {
  if (dialogMode.value === 'create') {
    if (!form.value.username.trim() || !form.value.password.trim()) {
      ElMessage.warning('用户名和密码不能为空')
      return
    }
    await createUser({
      username: form.value.username.trim(),
      password: form.value.password,
      email: form.value.email || undefined,
      role: form.value.role,
    })
    ElMessage.success('用户已创建')
  } else {
    const payload: Record<string, unknown> = {
      email: form.value.email || null,
      role: form.value.role,
      is_active: form.value.is_active,
    }
    if (form.value.password) payload.password = form.value.password
    await updateUser(form.value.id!, payload as Parameters<typeof updateUser>[1])
    ElMessage.success('用户已更新')
  }
  dialogVisible.value = false
  fetchData()
}

async function handleDelete(row: UserInfo) {
  await ElMessageBox.confirm(`确认删除用户「${row.username}」？删除后无法恢复。`, '警告', { type: 'warning' })
  await deleteUser(row.id)
  ElMessage.success('删除成功')
  fetchData()
}

onMounted(fetchData)
</script>

<template>
  <PageContainer title="用户管理">
    <template #actions>
      <el-button type="primary" :icon="Plus" @click="openCreate">新建用户</el-button>
    </template>
    <el-table :data="users" v-loading="loading" style="width: 100%">
      <el-table-column prop="username" label="用户名" width="150" />
      <el-table-column prop="email" label="邮箱" width="200" />
      <el-table-column label="角色" width="120">
        <template #default="{ row }">
          <el-tag :type="roleMap[row.role as UserRole].type" size="small">{{ roleMap[row.role as UserRole].label }}</el-tag>
        </template>
      </el-table-column>
      <el-table-column label="状态" width="100">
        <template #default="{ row }">
          <el-tag :type="row.is_active ? 'success' : 'info'" size="small">{{ row.is_active ? '启用' : '禁用' }}</el-tag>
        </template>
      </el-table-column>
      <el-table-column label="创建时间" width="180">
        <template #default="{ row }">{{ formatDate(row.created_at) }}</template>
      </el-table-column>
      <el-table-column label="操作" width="150" fixed="right">
        <template #default="{ row }">
          <el-button link type="primary" size="small" @click="openEdit(row as UserInfo)">编辑</el-button>
          <el-button link type="danger" size="small" @click="handleDelete(row as UserInfo)">删除</el-button>
        </template>
      </el-table-column>
    </el-table>

    <el-pagination
      style="margin-top: 16px; justify-content: flex-end;"
      :current-page="page"
      :page-size="size"
      :total="total"
      :page-sizes="[10, 20, 50]"
      layout="total, sizes, prev, pager, next"
      @current-change="handlePageChange"
      @size-change="handleSizeChange"
    />

    <el-dialog v-model="dialogVisible" :title="dialogMode === 'create' ? '新建用户' : '编辑用户'" width="480px">
      <el-form label-width="80px">
        <el-form-item label="用户名">
          <el-input v-model="form.username" :disabled="dialogMode === 'edit'" placeholder="登录用户名" />
        </el-form-item>
        <el-form-item label="密码">
          <el-input v-model="form.password" type="password" show-password
                    :placeholder="dialogMode === 'edit' ? '留空则不修改' : '登录密码'" />
        </el-form-item>
        <el-form-item label="邮箱">
          <el-input v-model="form.email" placeholder="可选" />
        </el-form-item>
        <el-form-item label="角色">
          <el-select v-model="form.role" style="width: 100%;">
            <el-option v-for="r in roleOptions" :key="r.value" :label="r.label" :value="r.value" />
          </el-select>
        </el-form-item>
        <el-form-item v-if="dialogMode === 'edit'" label="状态">
          <el-switch v-model="form.is_active" />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="dialogVisible = false">取消</el-button>
        <el-button type="primary" @click="handleSubmit">保存</el-button>
      </template>
    </el-dialog>
  </PageContainer>
</template>
