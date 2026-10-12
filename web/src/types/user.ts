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
  role: UserRole
  is_active: boolean
  created_at: string
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
