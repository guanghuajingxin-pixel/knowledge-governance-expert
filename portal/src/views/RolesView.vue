<script setup lang="ts">
import { computed, nextTick, onMounted, reactive, ref, watch } from 'vue'
import {
  ElButton, ElDialog, ElDropdown, ElDropdownItem, ElDropdownMenu, ElEmpty,
  ElForm, ElFormItem, ElIcon, ElInput, ElMessage, ElMessageBox, ElRadio, ElRadioGroup,
  ElTable, ElTableColumn, ElTag, ElTooltip, ElTree, vLoading,
} from 'element-plus'
import type { FormInstance, FormRules, TreeInstance } from 'element-plus'
import { Ellipsis, HelpCircle, Plus, RefreshCw } from '@lucide/vue'
import { accessToken } from '../auth/session'
import { createRole, deleteRole, listMenus, listRoles, updateRole, type MenuNode, type PortalRole } from '../api/roles'

const CODE_PATTERN = /^[a-z][a-z0-9_]{1,49}$/
const CODE_HINT = '2-50 位，小写字母开头，可含数字与下划线'
const MENU_HELP = '配置后对用户立即生效于下次刷新或重新登录；系统角色可借此收窄可见菜单，自定义角色用户在应用内为查看者能力'
const SYSTEM_ROLE_CODES = ['super_admin', 'admin', 'editor', 'viewer']

const roles = ref<PortalRole[]>([])
const loading = ref(false)
const menuGroups = ref<Array<{ key: string; label: string; children: MenuNode[] }>>([])
/** 分组节点 key 集合：提交白名单时只保留叶子 key */
const groupKeys = computed(() => new Set(menuGroups.value.map(g => g.key)))

async function load() {
  loading.value = true
  try {
    const token = await accessToken()
    const [roleItems, menus] = await Promise.all([listRoles(token), listMenus(token)])
    roles.value = roleItems
    menuGroups.value = menus.groups
  } catch (error) {
    ElMessage.error(error instanceof Error ? error.message : '加载角色列表失败。')
  } finally {
    loading.value = false
  }
}

function flattenLeaves(nodes: MenuNode[]): MenuNode[] {
  return nodes.flatMap(node => node.children?.length ? flattenLeaves(node.children) : [node])
}

function menuSummary(role: PortalRole): string {
  if (role.menu_permissions === null) return '全部菜单'
  const leaves = flattenLeaves(menuGroups.value.flatMap(g => g.children))
    .filter(leaf => role.menu_permissions!.includes(leaf.key))
  return `已配置 ${leaves.length} 项`
}

/** ------------------------------------------------------------ 新建角色 */
const createVisible = ref(false)
const createSubmitting = ref(false)
const createFormRef = ref<FormInstance>()
const createTreeRef = ref<TreeInstance>()
const createForm = reactive({ code: '', name: '', description: '', mode: 'all' as 'all' | 'custom' })
const createRules: FormRules = {
  code: [
    { required: true, message: '请输入角色标识', trigger: 'blur' },
    { pattern: CODE_PATTERN, message: `角色标识须为${CODE_HINT}`, trigger: 'blur' },
  ],
  name: [{ required: true, message: '请输入角色名称', trigger: 'blur' }],
}

function openCreate() {
  Object.assign(createForm, { code: '', name: '', description: '', mode: 'all' })
  createVisible.value = true
  nextTick(() => createTreeRef.value?.setCheckedKeys([]))
}

async function submitCreate() {
  if (!await createFormRef.value?.validate().catch(() => false)) return
  let menuPermissions: string[] | null = null
  if (createForm.mode === 'custom') {
    menuPermissions = checkedLeafKeys(createTreeRef.value)
    if (!menuPermissions.length) {
      ElMessage.warning('自定义菜单权限至少勾选一个菜单')
      return
    }
  }
  createSubmitting.value = true
  try {
    const token = await accessToken()
    await createRole(token, {
      code: createForm.code.trim(),
      name: createForm.name.trim(),
      description: createForm.description.trim() || undefined,
      menu_permissions: menuPermissions,
    })
    ElMessage.success('角色已创建')
    createVisible.value = false
    void load()
  } catch (error) {
    ElMessage.error(error instanceof Error ? error.message : '创建角色失败。')
  } finally {
    createSubmitting.value = false
  }
}

function checkedLeafKeys(tree: TreeInstance | undefined): string[] {
  if (!tree) return []
  return (tree.getCheckedKeys() as string[]).filter(key => !groupKeys.value.has(key))
}

/** ------------------------------------------------------------ 编辑角色 */
const editVisible = ref(false)
const editSubmitting = ref(false)
const editFormRef = ref<FormInstance>()
const editTreeRef = ref<TreeInstance>()
const editTarget = ref<PortalRole | null>(null)
const editForm = reactive({ name: '', description: '', mode: 'all' as 'all' | 'custom' })
const editRules: FormRules = {
  name: [{ required: true, message: '请输入角色名称', trigger: 'blur' }],
}
/** 编辑弹窗打开时菜单树回显的原始叶子 key（未改动时不重复提交） */
const editOriginalKeys = ref<string[]>([])

function isSystemRole(role: PortalRole): boolean {
  return role.is_system || SYSTEM_ROLE_CODES.includes(role.code)
}

function openEdit(role: PortalRole) {
  editTarget.value = role
  editForm.name = role.name
  editForm.description = role.description
  const leaves = role.menu_permissions === null ? null : role.menu_permissions
  editForm.mode = leaves === null ? 'all' : 'custom'
  editOriginalKeys.value = leaves ?? []
  editVisible.value = true
}

/** 弹窗打开后回显菜单树勾选（树用 v-show 保持挂载，切换 radio 不丢已勾选状态） */
watch(editVisible, (open) => {
  if (open) nextTick(() => editTreeRef.value?.setCheckedKeys(editOriginalKeys.value))
})

async function submitEdit() {
  if (!editTarget.value || !await editFormRef.value?.validate().catch(() => false)) return
  const role = editTarget.value
  let menuPermissions: string[] | null
  if (editForm.mode === 'all') {
    menuPermissions = null
  } else {
    menuPermissions = checkedLeafKeys(editTreeRef.value)
    if (!menuPermissions.length) {
      ElMessage.warning('自定义菜单权限至少勾选一个菜单')
      return
    }
  }
  const body: { name?: string; description?: string | null; menu_permissions?: string[] | null } = {}
  if (!isSystemRole(role)) {
    body.name = editForm.name.trim()
    body.description = editForm.description.trim()
  }
  if (JSON.stringify(menuPermissions) !== JSON.stringify(role.menu_permissions ?? null)) {
    body.menu_permissions = menuPermissions
  }
  if (!Object.keys(body).length) {
    editVisible.value = false
    return
  }
  editSubmitting.value = true
  try {
    const token = await accessToken()
    await updateRole(token, role.id, body)
    ElMessage.success('角色已更新')
    editVisible.value = false
    void load()
  } catch (error) {
    ElMessage.error(error instanceof Error ? error.message : '更新角色失败。')
  } finally {
    editSubmitting.value = false
  }
}

/** ------------------------------------------------------------ 删除角色 */
async function removeRole(role: PortalRole) {
  const confirmed = await ElMessageBox.confirm(
    `删除后使用「${role.name}」的用户将失去该角色，确认删除？`, '删除角色',
    { type: 'warning', confirmButtonText: '删除', cancelButtonText: '取消' },
  ).then(() => true, () => false)
  if (!confirmed) return
  try {
    const token = await accessToken()
    await deleteRole(token, role.id)
    ElMessage.success('角色已删除')
    void load()
  } catch (error) {
    ElMessage.error(error instanceof Error ? error.message : '删除角色失败。')
  }
}

async function handleMore(command: string | number | object, role: PortalRole) {
  if (command === 'delete') await removeRole(role)
}

onMounted(() => { void load() })
</script>

<template>
  <section class="roles-page" aria-label="角色管理">
    <div class="roles-wrap">
      <header class="roles-header">
        <div>
          <h2>角色管理</h2>
          <p>创建自定义角色并配置菜单权限；系统角色仅可调整菜单权限</p>
        </div>
        <div class="header-actions">
          <el-tooltip content="刷新列表">
            <el-button :icon="RefreshCw" :loading="loading" aria-label="刷新列表" @click="load" />
          </el-tooltip>
          <el-button type="primary" :icon="Plus" @click="openCreate">新建角色</el-button>
        </div>
      </header>

      <el-table v-loading="loading" :data="roles" border aria-label="角色列表">
        <el-table-column prop="name" label="角色名称" min-width="130" show-overflow-tooltip />
        <el-table-column prop="code" label="角色标识" width="150" show-overflow-tooltip />
        <el-table-column label="描述" min-width="180" show-overflow-tooltip>
          <template #default="{ row }">
            <span v-if="row.description">{{ row.description }}</span>
            <span v-else class="muted">—</span>
          </template>
        </el-table-column>
        <el-table-column label="菜单权限" width="120">
          <template #default="{ row }">
            <el-tag v-if="row.menu_permissions === null" type="info" effect="plain">全部菜单</el-tag>
            <span v-else>{{ menuSummary(row as PortalRole) }}</span>
          </template>
        </el-table-column>
        <el-table-column label="类型" width="90">
          <template #default="{ row }">
            <el-tag :type="isSystemRole(row as PortalRole) ? 'success' : 'info'" effect="plain">
              {{ isSystemRole(row as PortalRole) ? '系统' : '自定义' }}
            </el-tag>
          </template>
        </el-table-column>
        <el-table-column prop="user_count" label="用户数" width="80" />
        <el-table-column label="操作" width="130" fixed="right">
          <template #default="{ row }">
            <el-button link type="primary" size="small" @click="openEdit(row as PortalRole)">编辑</el-button>
            <el-dropdown trigger="click" placement="bottom-end" popper-class="roles-menu"
                         @command="(command: string | number | object) => handleMore(command, row as PortalRole)">
              <el-button link size="small" aria-label="更多操作">
                <el-icon><Ellipsis /></el-icon>
              </el-button>
              <template #dropdown>
                <el-dropdown-menu>
                  <el-dropdown-item v-if="!isSystemRole(row as PortalRole)" command="delete" divided class="danger-action">删除角色</el-dropdown-item>
                </el-dropdown-menu>
              </template>
            </el-dropdown>
          </template>
        </el-table-column>
        <template #empty>
          <el-empty description="暂无角色，点击「新建角色」创建" />
        </template>
      </el-table>
    </div>

    <el-dialog v-model="createVisible" title="新建角色" width="min(560px, 92vw)"
               :close-on-click-modal="false" :show-close="!createSubmitting" :close-on-press-escape="!createSubmitting">
      <el-form ref="createFormRef" :model="createForm" :rules="createRules" label-width="88px">
        <el-form-item label="角色标识" prop="code">
          <el-input v-model="createForm.code" maxlength="50" :placeholder="CODE_HINT" />
        </el-form-item>
        <el-form-item label="角色名称" prop="name">
          <el-input v-model="createForm.name" maxlength="100" placeholder="展示名称，如 市场只读" />
        </el-form-item>
        <el-form-item label="描述">
          <el-input v-model="createForm.description" maxlength="500" placeholder="选填" />
        </el-form-item>
        <el-form-item prop="mode">
          <template #label>菜单权限<el-tooltip :content="MENU_HELP"><el-icon class="label-help"><HelpCircle /></el-icon></el-tooltip></template>
          <div class="menu-editor">
            <el-radio-group v-model="createForm.mode">
              <el-radio value="all">全部菜单</el-radio>
              <el-radio value="custom">自定义选择</el-radio>
            </el-radio-group>
            <div v-show="createForm.mode === 'custom'" class="menu-tree">
              <el-tree ref="createTreeRef" :data="menuGroups" node-key="key" show-checkbox
                       default-expand-all :props="{ label: 'label', children: 'children' }"
                       aria-label="菜单权限选择树" />
            </div>
          </div>
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="createVisible = false">取消</el-button>
        <el-button type="primary" :loading="createSubmitting" @click="submitCreate">创建角色</el-button>
      </template>
    </el-dialog>

    <el-dialog v-model="editVisible" :title="`编辑角色 · ${editTarget?.name || ''}`" width="min(560px, 92vw)"
               :close-on-click-modal="false" :show-close="!editSubmitting" :close-on-press-escape="!editSubmitting">
      <el-form ref="editFormRef" :model="editForm" :rules="editRules" label-width="88px">
        <el-form-item label="角色标识">
          <el-input :model-value="editTarget?.code" disabled />
        </el-form-item>
        <el-form-item label="角色名称" prop="name">
          <el-input v-model="editForm.name" maxlength="100" :disabled="editTarget ? isSystemRole(editTarget) : false" />
        </el-form-item>
        <el-form-item label="描述">
          <el-input v-model="editForm.description" maxlength="500" :disabled="editTarget ? isSystemRole(editTarget) : false"
                    :placeholder="editTarget && isSystemRole(editTarget) ? '系统角色的描述不可修改' : '选填'" />
        </el-form-item>
        <el-form-item prop="mode">
          <template #label>菜单权限<el-tooltip :content="MENU_HELP"><el-icon class="label-help"><HelpCircle /></el-icon></el-tooltip></template>
          <div class="menu-editor">
            <el-radio-group v-model="editForm.mode">
              <el-radio value="all">全部菜单</el-radio>
              <el-radio value="custom">自定义选择</el-radio>
            </el-radio-group>
            <div v-show="editForm.mode === 'custom'" class="menu-tree">
              <el-tree ref="editTreeRef" :data="menuGroups" node-key="key" show-checkbox
                       default-expand-all :props="{ label: 'label', children: 'children' }"
                       aria-label="菜单权限选择树" />
            </div>
          </div>
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="editVisible = false">取消</el-button>
        <el-button type="primary" :loading="editSubmitting" @click="submitEdit">保存修改</el-button>
      </template>
    </el-dialog>
  </section>
</template>

<style scoped lang="scss">
.roles-page { flex: 1; min-height: 0; overflow-y: auto; padding: 24px 32px 32px; }
.roles-wrap { max-width: 1080px; margin: 0 auto; display: flex; flex-direction: column; gap: 16px; }
.roles-header { display: flex; justify-content: space-between; align-items: flex-end; gap: 16px;
  h2 { margin: 0; font-size: 20px; color: var(--el-text-color-primary); }
  p { margin: 6px 0 0; font-size: 12px; color: var(--el-text-color-secondary); } }
.header-actions { display: flex; align-items: center; gap: 4px; flex-shrink: 0; }
.muted { color: var(--el-text-color-placeholder); }
.label-help { margin-left: 4px; font-size: 14px; color: var(--el-text-color-secondary); cursor: help; vertical-align: -2px; }
.menu-editor { width: 100%; display: flex; flex-direction: column; gap: 8px; }
.menu-tree { border: 1px solid var(--el-border-color-lighter); border-radius: 6px; padding: 8px; max-height: 260px; overflow: auto; }
</style>
<style lang="scss">
/* 下拉弹层挂在 body 下，需全局样式 */
.roles-menu .danger-action { color: var(--el-color-danger); }
.roles-menu .danger-action:not(.is-disabled):hover { background: var(--el-color-danger-light-9); color: var(--el-color-danger); }
</style>
