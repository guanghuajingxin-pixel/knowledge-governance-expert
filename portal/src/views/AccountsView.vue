<script setup lang="ts">
import { computed, nextTick, onMounted, reactive, ref, watch } from 'vue'
import {
  ElButton, ElCheckbox, ElDialog, ElDropdown, ElDropdownItem, ElDropdownMenu, ElEmpty,
  ElForm, ElFormItem, ElIcon, ElInput, ElMessage, ElMessageBox, ElOption, ElRadio, ElRadioGroup,
  ElSelect, ElTable, ElTableColumn, ElTag, ElTooltip, ElTree, vLoading,
} from 'element-plus'
import type { FormInstance, FormRules, TreeInstance } from 'element-plus'
import { Ellipsis, HelpCircle, Plus, RefreshCw } from '@lucide/vue'
import { accessToken, authConfig, identity } from '../auth/session'
import {
  createAccount, deleteAccount, listAccounts, resetPassword, updateAccount,
  updateMenuPermissions, type PortalAccount,
} from '../api/accounts'
import { listMenus, listRoles, type MenuNode, type PortalRole } from '../api/roles'

const SYSTEM_ROLE_CODES = ['super_admin', 'admin', 'editor', 'viewer'] as const
const MENU_OVERRIDE_HELP = '针对单个用户覆盖角色配置的菜单权限；「跟随角色」即取消覆盖，恢复使用角色配置'
const PASSWORD_HINT = '至少 12 位，须包含大写字母、小写字母和数字'
const PAGE_SIZE = 20

const accounts = ref<PortalAccount[]>([])
const roles = ref<PortalRole[]>([])
const menuGroups = ref<Array<{ key: string; label: string; children: MenuNode[] }>>([])
const groupKeys = computed(() => new Set(menuGroups.value.map(g => g.key)))
const loading = ref(false)
const searchInput = ref('')
const search = ref('')
const page = ref(1)
const hasMore = ref(false)

const isLocalMode = computed(() => authConfig.value?.provider === 'local')
const isSuperAdmin = computed(() => identity.value?.user.role === 'super_admin')
/** 系统角色固定顺序在前，自定义角色按创建时间跟后 */
const roleOptions = computed(() => roles.value
  .filter(role => role.code !== 'super_admin' || isSuperAdmin.value)
  .map(role => ({ value: role.code, label: role.name })))
const roleLabel = (code: string) => roles.value.find(r => r.code === code)?.name || code

function effectiveRole(row: PortalAccount): string {
  for (const code of SYSTEM_ROLE_CODES) if (row.roles.includes(code)) return code
  for (const role of row.roles) return role
  return ''
}

function isSelf(row: PortalAccount): boolean {
  return row.username === identity.value?.user.username
}

/** admin 不可改动 super_admin 账号（后端亦有护栏，这里提前禁用避免无效操作） */
function canWrite(row: PortalAccount): boolean {
  return isSuperAdmin.value || !row.roles.includes('super_admin')
}

async function load() {
  loading.value = true
  try {
    const token = await accessToken()
    const result = await listAccounts(token, { search: search.value, page: page.value, page_size: PAGE_SIZE })
    accounts.value = result.items
    hasMore.value = result.has_more
  } catch (error) {
    ElMessage.error(error instanceof Error ? error.message : '加载账号列表失败。')
  } finally {
    loading.value = false
  }
}

async function loadRoles() {
  try {
    const token = await accessToken()
    const [roleItems, menus] = await Promise.all([listRoles(token), listMenus(token)])
    roles.value = roleItems
    menuGroups.value = menus.groups
  } catch (error) {
    ElMessage.error(error instanceof Error ? error.message : '加载角色与菜单配置失败。')
  }
}

function applySearch() {
  search.value = searchInput.value.trim()
  page.value = 1
  void load()
}

function resetSearch() {
  if (!searchInput.value && !search.value) return
  searchInput.value = ''
  search.value = ''
  page.value = 1
  void load()
}

function goPage(next: number) {
  page.value = next
  void load()
}

function passwordValidator(_rule: unknown, value: string, callback: (error?: Error) => void) {
  if (!value) callback(new Error('请输入密码'))
  else if (value.length < 12 || !/[a-z]/.test(value) || !/[A-Z]/.test(value) || !/\d/.test(value)) callback(new Error(PASSWORD_HINT))
  else callback()
}

const createVisible = ref(false)
const createSubmitting = ref(false)
const createFormRef = ref<FormInstance>()
const createForm = reactive({ username: '', name: '', email: '', role: 'viewer', password: '', temporary: true })
const createRules: FormRules = {
  username: [
    { required: true, message: '请输入账号', trigger: 'blur' },
    { pattern: /^\S+$/, message: '账号不能包含空格', trigger: 'blur' },
  ],
  name: [{ required: true, message: '请输入姓名', trigger: 'blur' }],
  email: [{ type: 'email', message: '邮箱格式不正确', trigger: 'blur' }],
  role: [{ required: true, message: '请选择角色', trigger: 'change' }],
  password: [{ required: true, validator: passwordValidator, trigger: 'blur' }],
}

function openCreate() {
  Object.assign(createForm, { username: '', name: '', email: '', role: 'viewer', password: '', temporary: true })
  createVisible.value = true
}

async function submitCreate() {
  if (!await createFormRef.value?.validate().catch(() => false)) return
  createSubmitting.value = true
  try {
    const token = await accessToken()
    await createAccount(token, {
      username: createForm.username.trim(),
      ...(isLocalMode.value ? {} : { name: createForm.name.trim() }),
      email: createForm.email.trim() || undefined,
      role: createForm.role,
      password: createForm.password,
      temporary: createForm.temporary,
    })
    ElMessage.success('账号已创建')
    createVisible.value = false
    void load()
  } catch (error) {
    ElMessage.error(error instanceof Error ? error.message : '创建账号失败。')
  } finally {
    createSubmitting.value = false
  }
}

const editVisible = ref(false)
const editSubmitting = ref(false)
const editFormRef = ref<FormInstance>()
const editTarget = ref<PortalAccount | null>(null)
const editForm = reactive({ name: '', email: '', role: 'viewer' })
const editRules: FormRules = {
  name: [{ required: true, message: '请输入姓名', trigger: 'blur' }],
  email: [{ type: 'email', message: '邮箱格式不正确', trigger: 'blur' }],
  role: [{ required: true, message: '请选择角色', trigger: 'change' }],
}

function openEdit(row: PortalAccount) {
  editTarget.value = row
  editForm.name = row.name
  editForm.email = row.email || ''
  editForm.role = effectiveRole(row) || 'viewer'
  editVisible.value = true
}

async function submitEdit() {
  if (!editTarget.value || !await editFormRef.value?.validate().catch(() => false)) return
  editSubmitting.value = true
  try {
    const token = await accessToken()
    await updateAccount(token, editTarget.value.id, {
      ...(isLocalMode.value ? {} : { name: editForm.name.trim() }),
      email: editForm.email.trim(),
      role: editForm.role,
    })
    ElMessage.success('账号已更新')
    editVisible.value = false
    void load()
  } catch (error) {
    ElMessage.error(error instanceof Error ? error.message : '更新账号失败。')
  } finally {
    editSubmitting.value = false
  }
}

const resetVisible = ref(false)
const resetSubmitting = ref(false)
const resetFormRef = ref<FormInstance>()
const resetTarget = ref<PortalAccount | null>(null)
const resetForm = reactive({ password: '', temporary: true })
const resetRules: FormRules = {
  password: [{ required: true, validator: passwordValidator, trigger: 'blur' }],
}

function openReset(row: PortalAccount) {
  resetTarget.value = row
  resetForm.password = ''
  resetForm.temporary = true
  resetVisible.value = true
}

async function submitReset() {
  if (!resetTarget.value || !await resetFormRef.value?.validate().catch(() => false)) return
  resetSubmitting.value = true
  try {
    const token = await accessToken()
    await resetPassword(token, resetTarget.value.id, {
      password: resetForm.password,
      temporary: resetForm.temporary,
    })
    ElMessage.success('密码已重置')
    resetVisible.value = false
  } catch (error) {
    ElMessage.error(error instanceof Error ? error.message : '重置密码失败。')
  } finally {
    resetSubmitting.value = false
  }
}

/** ------------------------------------------------------------ 菜单权限覆盖 */

const menusVisible = ref(false)
const menusSubmitting = ref(false)
const menusTarget = ref<PortalAccount | null>(null)
const menusTreeRef = ref<TreeInstance>()
const menusForm = reactive({ mode: 'follow' as 'follow' | 'custom' })
const menusOriginalKeys = ref<string[]>([])

function openMenus(row: PortalAccount) {
  menusTarget.value = row
  menusForm.mode = row.menu_permissions === null ? 'follow' : 'custom'
  menusOriginalKeys.value = row.menu_permissions ?? []
  menusVisible.value = true
}

watch(menusVisible, (open) => {
  if (open) nextTick(() => menusTreeRef.value?.setCheckedKeys(menusOriginalKeys.value))
  else menusTreeRef.value?.setCheckedKeys([])
})

async function submitMenus() {
  if (!menusTarget.value) return
  let menuPermissions: string[] | null
  if (menusForm.mode === 'follow') {
    menuPermissions = null
  } else {
    menuPermissions = (menusTreeRef.value?.getCheckedKeys() as string[] || [])
      .filter(key => !groupKeys.value.has(key))
    if (!menuPermissions.length) {
      ElMessage.warning('自定义菜单权限至少勾选一个菜单')
      return
    }
  }
  menusSubmitting.value = true
  try {
    const token = await accessToken()
    await updateMenuPermissions(token, menusTarget.value.id, { menu_permissions: menuPermissions })
    ElMessage.success(menusForm.mode === 'follow' ? '已恢复跟随角色' : '菜单权限已更新')
    menusVisible.value = false
    void load()
  } catch (error) {
    ElMessage.error(error instanceof Error ? error.message : '更新菜单权限失败。')
  } finally {
    menusSubmitting.value = false
  }
}

/** ------------------------------------------------------------ 停用 / 删除 */

async function toggleEnabled(row: PortalAccount) {
  if (row.enabled) {
    const confirmed = await ElMessageBox.confirm(`停用后「${row.username}」将立即无法登录，确认停用？`, '停用账号', {
      type: 'warning', confirmButtonText: '停用', cancelButtonText: '取消',
    }).then(() => true, () => false)
    if (!confirmed) return
  }
  try {
    const token = await accessToken()
    await updateAccount(token, row.id, { enabled: !row.enabled })
    ElMessage.success(row.enabled ? '账号已停用' : '账号已启用')
    void load()
  } catch (error) {
    ElMessage.error(error instanceof Error ? error.message : '操作失败。')
  }
}

async function removeAccount(row: PortalAccount) {
  const confirmed = await ElMessageBox.confirm(`删除后「${row.username}」将无法恢复，确认删除？`, '删除账号', {
    type: 'warning', confirmButtonText: '删除', cancelButtonText: '取消',
  }).then(() => true, () => false)
  if (!confirmed) return
  try {
    const token = await accessToken()
    await deleteAccount(token, row.id)
    ElMessage.success('账号已删除')
    if (accounts.value.length === 1 && page.value > 1) page.value -= 1
    void load()
  } catch (error) {
    ElMessage.error(error instanceof Error ? error.message : '删除账号失败。')
  }
}

async function handleMore(command: string | number | object, row: PortalAccount) {
  if (command === 'menus') openMenus(row)
  else if (command === 'toggle') await toggleEnabled(row)
  else if (command === 'delete') await removeAccount(row)
}

onMounted(() => { void load(); void loadRoles() })
</script>

<template>
  <section class="accounts-page" aria-label="用户管理">
    <div class="accounts-wrap">
      <header class="accounts-header">
        <div>
          <h2>用户管理</h2>
          <p>{{ isLocalMode ? '管理企业账号、角色分配与菜单权限' : '统一管理门户账号、角色分配与菜单权限' }}</p>
        </div>
        <div class="header-actions">
          <el-tooltip content="刷新列表">
            <el-button :icon="RefreshCw" :loading="loading" aria-label="刷新列表" @click="load" />
          </el-tooltip>
          <el-button type="primary" :icon="Plus" @click="openCreate">新增账号</el-button>
        </div>
      </header>

      <div class="filter-bar">
        <el-input
          v-model="searchInput"
          :placeholder="isLocalMode ? '搜索账号 / 邮箱' : '搜索账号 / 姓名 / 邮箱'"
          clearable style="width: 260px" aria-label="搜索账号"
          @keyup.enter="applySearch" @clear="applySearch"
        />
        <div class="filter-actions">
          <el-button @click="applySearch">查询</el-button>
          <el-button @click="resetSearch">重置</el-button>
        </div>
      </div>

      <el-table v-loading="loading" :data="accounts" border aria-label="账号列表">
        <el-table-column prop="username" label="账号" min-width="150" show-overflow-tooltip />
        <el-table-column v-if="!isLocalMode" prop="name" label="姓名" min-width="110" show-overflow-tooltip />
        <el-table-column label="邮箱" min-width="200" show-overflow-tooltip>
          <template #default="{ row }">
            <span v-if="row.email">{{ row.email }}</span>
            <span v-else class="muted">—</span>
          </template>
        </el-table-column>
        <el-table-column label="角色" width="140">
          <template #default="{ row }">
            <template v-if="effectiveRole(row as PortalAccount)">
              <el-tag type="info" effect="plain">{{ roleLabel(effectiveRole(row as PortalAccount)) }}</el-tag>
              <el-tag v-if="(row as PortalAccount).menu_permissions !== null" class="custom-tag" size="small" effect="plain">自定义</el-tag>
            </template>
            <span v-else class="muted">未授权</span>
          </template>
        </el-table-column>
        <el-table-column label="状态" width="90">
          <template #default="{ row }">
            <el-tag :type="row.enabled ? 'success' : 'info'" effect="plain">{{ row.enabled ? '启用' : '停用' }}</el-tag>
          </template>
        </el-table-column>
        <el-table-column label="操作" width="190" fixed="right">
          <template #default="{ row }">
            <el-button link type="primary" size="small" :disabled="!canWrite(row as PortalAccount)" @click="openEdit(row as PortalAccount)">编辑</el-button>
            <el-button link type="primary" size="small" :disabled="!canWrite(row as PortalAccount)" @click="openReset(row as PortalAccount)">重置密码</el-button>
            <el-dropdown
              trigger="click" placement="bottom-end" popper-class="accounts-menu"
              @command="(command: string | number | object) => handleMore(command, row as PortalAccount)"
            >
              <el-button link size="small" aria-label="更多操作">
                <el-icon><Ellipsis /></el-icon>
              </el-button>
              <template #dropdown>
                <el-dropdown-menu>
                  <el-dropdown-item command="menus">菜单权限{{ (row as PortalAccount).menu_permissions !== null ? '（自定义）' : '' }}</el-dropdown-item>
                  <el-dropdown-item v-if="!isSelf(row as PortalAccount)" command="toggle">{{ row.enabled ? '停用账号' : '启用账号' }}</el-dropdown-item>
                  <el-dropdown-item v-if="!isSelf(row as PortalAccount)" command="delete" divided class="danger-action">删除账号</el-dropdown-item>
                </el-dropdown-menu>
              </template>
            </el-dropdown>
          </template>
        </el-table-column>
        <template #empty>
          <el-empty :description="search ? '没有符合搜索条件的账号' : '暂无账号，点击「新增账号」创建'" />
        </template>
      </el-table>

      <footer class="pagination-row">
        <span class="page-info">第 {{ page }} 页</span>
        <div class="pager-buttons">
          <el-button size="small" :disabled="page <= 1" @click="goPage(page - 1)">上一页</el-button>
          <el-button size="small" :disabled="!hasMore" @click="goPage(page + 1)">下一页</el-button>
        </div>
      </footer>
    </div>

    <el-dialog v-model="createVisible" title="新增账号" width="min(480px, 92vw)"
               :close-on-click-modal="false" :show-close="!createSubmitting" :close-on-press-escape="!createSubmitting">
      <el-form ref="createFormRef" :model="createForm" :rules="createRules" label-width="88px">
        <el-form-item label="账号" prop="username">
          <el-input v-model="createForm.username" maxlength="100" placeholder="登录账号，如 zhangsan" />
        </el-form-item>
        <el-form-item v-if="!isLocalMode" label="姓名" prop="name">
          <el-input v-model="createForm.name" maxlength="100" placeholder="真实姓名，便于识别" />
        </el-form-item>
        <el-form-item label="邮箱" prop="email">
          <el-input v-model="createForm.email" maxlength="200" placeholder="选填" />
        </el-form-item>
        <el-form-item label="角色" prop="role">
          <el-select v-model="createForm.role" style="width: 100%">
            <el-option v-for="option in roleOptions" :key="option.value" :value="option.value" :label="option.label" />
          </el-select>
        </el-form-item>
        <el-form-item label="初始密码" prop="password">
          <el-input v-model="createForm.password" type="password" show-password autocomplete="new-password" :placeholder="PASSWORD_HINT" />
        </el-form-item>
        <el-form-item label-width="88px">
          <el-checkbox v-model="createForm.temporary">首次登录须修改密码</el-checkbox>
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="createVisible = false">取消</el-button>
        <el-button type="primary" :loading="createSubmitting" @click="submitCreate">创建账号</el-button>
      </template>
    </el-dialog>

    <el-dialog v-model="editVisible" :title="`编辑账号 · ${editTarget?.username || ''}`" width="min(480px, 92vw)"
               :close-on-click-modal="false" :show-close="!editSubmitting" :close-on-press-escape="!editSubmitting">
      <el-form ref="editFormRef" :model="editForm" :rules="editRules" label-width="88px">
        <el-form-item v-if="!isLocalMode" label="姓名" prop="name">
          <el-input v-model="editForm.name" maxlength="100" />
        </el-form-item>
        <el-form-item label="邮箱" prop="email">
          <el-input v-model="editForm.email" maxlength="200" placeholder="留空表示清除邮箱" />
        </el-form-item>
        <el-form-item label="角色" prop="role">
          <el-select v-model="editForm.role" style="width: 100%" :disabled="editTarget ? isSelf(editTarget) : false">
            <el-option v-for="option in roleOptions" :key="option.value" :value="option.value" :label="option.label" />
          </el-select>
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="editVisible = false">取消</el-button>
        <el-button type="primary" :loading="editSubmitting" @click="submitEdit">保存修改</el-button>
      </template>
    </el-dialog>

    <el-dialog v-model="resetVisible" :title="`重置密码 · ${resetTarget?.username || ''}`" width="min(480px, 92vw)"
               :close-on-click-modal="false" :show-close="!resetSubmitting" :close-on-press-escape="!resetSubmitting">
      <el-form ref="resetFormRef" :model="resetForm" :rules="resetRules" label-width="88px">
        <el-form-item label="新密码" prop="password">
          <el-input v-model="resetForm.password" type="password" show-password autocomplete="new-password" :placeholder="PASSWORD_HINT" />
        </el-form-item>
        <el-form-item>
          <el-checkbox v-model="resetForm.temporary">首次登录须修改密码</el-checkbox>
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="resetVisible = false">取消</el-button>
        <el-button type="primary" :loading="resetSubmitting" @click="submitReset">重置密码</el-button>
      </template>
    </el-dialog>

    <el-dialog v-model="menusVisible" :title="`菜单权限 · ${menusTarget?.username || ''}`" width="min(560px, 92vw)"
               :close-on-click-modal="false" :show-close="!menusSubmitting" :close-on-press-escape="!menusSubmitting">
      <el-form label-width="88px">
        <el-form-item>
          <template #label>权限模式<el-tooltip :content="MENU_OVERRIDE_HELP"><el-icon class="label-help"><HelpCircle /></el-icon></el-tooltip></template>
          <div class="menu-editor">
            <el-radio-group v-model="menusForm.mode">
              <el-radio value="follow">跟随角色</el-radio>
              <el-radio value="custom">自定义选择</el-radio>
            </el-radio-group>
            <div v-show="menusForm.mode === 'custom'" class="menu-tree">
              <el-tree ref="menusTreeRef" :data="menuGroups" node-key="key" show-checkbox
                       default-expand-all :props="{ label: 'label', children: 'children' }"
                       aria-label="菜单权限选择树" />
            </div>
          </div>
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="menusVisible = false">取消</el-button>
        <el-button type="primary" :loading="menusSubmitting" @click="submitMenus">保存权限</el-button>
      </template>
    </el-dialog>
  </section>
</template>

<style scoped lang="scss">
.accounts-page { flex: 1; min-height: 0; overflow-y: auto; padding: 24px 32px 32px; }
.accounts-wrap { max-width: 1080px; margin: 0 auto; display: flex; flex-direction: column; gap: 16px; }
.accounts-header { display: flex; justify-content: space-between; align-items: flex-end; gap: 16px;
  h2 { margin: 0; font-size: 20px; color: var(--el-text-color-primary); }
  p { margin: 6px 0 0; font-size: 12px; color: var(--el-text-color-secondary); } }
.header-actions { display: flex; align-items: center; gap: 4px; flex-shrink: 0; }
.filter-bar { display: flex; align-items: center; gap: 12px; }
.filter-actions { margin-left: auto; }
.muted { color: var(--el-text-color-placeholder); }
.custom-tag { margin-left: 6px; }
.pagination-row { display: flex; align-items: center; justify-content: flex-end; gap: 12px; }
.page-info { font-size: 12px; color: var(--el-text-color-secondary); }
.pager-buttons { display: flex; gap: 8px; }
.label-help { margin-left: 4px; font-size: 14px; color: var(--el-text-color-secondary); cursor: help; vertical-align: -2px; }
.menu-editor { width: 100%; display: flex; flex-direction: column; gap: 8px; }
.menu-tree { border: 1px solid var(--el-border-color-lighter); border-radius: 6px; padding: 8px; max-height: 260px; overflow: auto; }
</style>
<style lang="scss">
/* 下拉弹层挂在 body 下，需全局样式 */
.accounts-menu .danger-action { color: var(--el-color-danger); }
.accounts-menu .danger-action:not(.is-disabled):hover { background: var(--el-color-danger-light-9); color: var(--el-color-danger); }
</style>
