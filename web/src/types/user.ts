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
  /** 下次登录必须设置新密码（钉钉首次建档 / 管理员重置密码后为 true） */
  must_change_password?: boolean
  /** 钉钉绑定；未绑定为 null（列表接口需带 include_binding=true 才返回） */
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
  /** true 表示首次登录（无本地密码），前端须跳设密页 */
  must_set_password?: boolean
}

/** 钉钉登录渠道：h5 = 钉钉工作台内免登，qr = PC 浏览器扫码 */
export type DingtalkLoginChannel = 'h5' | 'qr'
