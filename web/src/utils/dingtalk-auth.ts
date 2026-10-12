// 登录回跳工具：仅保留站内相对路径白名单（原钉钉扫码登录工具已随统一门户迁移移除）
/** 仅接受站内相对路径，避免开放重定向 */
export function safeRedirect(value: unknown, fallback = '/chat'): string {
  return typeof value === 'string' && value.startsWith('/') && !value.startsWith('//') ? value : fallback
}
