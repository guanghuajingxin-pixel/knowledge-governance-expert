/** 系统角色码（自定义角色为任意小写 code，见门户角色管理） */
export type UserRole = 'super_admin' | 'admin' | 'editor' | 'viewer'

/** 钉钉身份绑定信息；用户未绑定钉钉时为 null */
export interface DingtalkBinding {
  dt_name: string
  dt_userid: string
  dt_unionid: string
  corp_id: string
  bound_at: string
}

export interface UserInfo {
  id: string
  username: string
  email: string
  /** 系统角色或自定义角色 code（自定义角色在应用内为查看者能力） */
  role: string
  is_active: boolean
  created_at: string
  /** 菜单权限：null/undefined = 未配置（全部菜单）；列表 = 白名单（菜单 key 即路由 path） */
  menu_permissions?: string[] | null
  /** 后端兼容字段：账户管理已上收门户，前端不再消费 */
  must_change_password?: boolean
  /** 钉钉绑定；未绑定为 null */
  dingtalk_binding?: DingtalkBinding | null
}

export interface LoginRequest {
  username: string
  password: string
}

export interface LoginResponse {
  access_token: string
  token_type: string
  user: UserInfo
}
