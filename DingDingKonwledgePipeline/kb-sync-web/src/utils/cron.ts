export const PRESET_DESC: Record<string, string> = {
  '0 2 * * *': '每天 02:00',
  '0 8 * * *': '每天 08:00',
  '0 9 * * 1': '每周一 09:00',
  '0 */6 * * *': '每 6 小时',
}

export function cronDesc(cron: string): string {
  const v = cron.trim()
  const m = v.match(/^(\*|\d+|\*\/\d+)\s+(\*|\d+|\*\/\d+)\s+\*\s+\*\s+(\*|[0-7])$/)
  if (!m) return '格式：分 时 日 月 周（如 30 3 * * *）'
  const [, min, hour, week] = m
  const mh = hour === '*' ? '每小时' : hour === '*/6' ? '每 6 小时' : `每天 ${String(hour).padStart(2, '0')}:${min === '0' ? '00' : String(min).padStart(2, '0')}`
  const wd = week && week !== '*' ? ` · 周${week === '1' ? '一' : week === '0' || week === '7' ? '日' : week}` : ''
  return `${mh}${wd}`
}
