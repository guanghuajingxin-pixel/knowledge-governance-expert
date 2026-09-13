/** cron 表达式 ↔ 易读中文表述 的转换工具（五段式：分 时 日 月 周） */

const WEEK_NAMES = ['周日', '周一', '周二', '周三', '周四', '周五', '周六']

function pad(n: string): string {
  return n.padStart(2, '0')
}

function isNum(v: string): boolean {
  return /^\d+$/.test(v)
}

/** 将 cron 表达式转为易读表述，如「每日 02:00」「每周一 17:00」「工作日 09:00」 */
export function cronLabel(cron?: string | null): string {
  const expr = (cron || '').trim()
  if (!expr) return '未设置'
  const parts = expr.split(/\s+/)
  if (parts.length !== 5) return expr
  const [min, hour, dom, mon, dow] = parts

  // 每小时整点（如 0 * * * *）
  if (min === '0' && hour === '*' && dom === '*' && mon === '*' && dow === '*') return '每小时'

  if (dom !== '*' || mon !== '*') return expr // 涉及日/月的复杂表达式，原样展示

  const days = dow === '*' || (dow === '0' || dow === '7') ? null : dow
  const timeOf = (h: string, m: string) => `${pad(h)}:${pad(m)}`

  // 分钟列表：0 9,18 * * * → 每日 09:00、18:00
  const mins = min.split(',').filter(isNum)
  const hours = hour.split(',').filter(isNum)

  let dayPrefix = '每日'
  if (days) {
    if (days.includes('-')) {
      const [a, b] = days.split('-').map(Number)
      if (Number.isNaN(a) || Number.isNaN(b)) return expr
      if (a === 1 && b === 5) dayPrefix = '工作日'
      else dayPrefix = `每${WEEK_NAMES[a % 7]}至${WEEK_NAMES[b % 7]}`
    } else {
      const list = days.split(',').map((d) => Number(d))
      if (list.some(Number.isNaN)) return expr
      dayPrefix = `每${list.map((d) => WEEK_NAMES[d % 7]).join('、')}`
    }
  }

  // 常规：时:分 均为具体值
  if (hours.length && mins.length) {
    const times = hours.flatMap((h) => mins.map((m) => timeOf(h, m))).sort()
    return `${dayPrefix} ${times.join('、')}`
  }
  // 每小时第 N 分（如 30 * * * *）
  if (hour === '*' && mins.length === 1) return `每小时第 ${Number(mins[0])} 分`

  return expr
}
