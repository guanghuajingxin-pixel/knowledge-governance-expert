<script setup lang="ts">
import { ref, onMounted } from 'vue'
import PageContainer from '@/components/common/PageContainer.vue'
import { mockUsers } from '@/mocks/data/users'
import type { UserInfo, UserRole } from '@/types/user'
import { formatDate } from '@/utils/format'

const users = ref<UserInfo[]>([])

const roleMap: Record<UserRole, { label: string; type: 'danger' | 'warning' | 'success' | 'info' }> = {
  super_admin: { label: '超级管理员', type: 'danger' },
  admin: { label: '管理员', type: 'warning' },
  editor: { label: '编辑者', type: 'success' },
  viewer: { label: '查看者', type: 'info' },
}

onMounted(() => {
  users.value = [...mockUsers]
})
</script>

<template>
  <PageContainer title="用户管理">
    <el-table :data="users" style="width: 100%">
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
    </el-table>
  </PageContainer>
</template>
