export function fmtTime(s?: string | null): string {
  if (!s) return '—'
  let t = s
  if (!/Z$|[+-]\d\d:\d\d$/.test(t)) t += 'Z'
  const d = new Date(t)
  if (isNaN(d.getTime())) return s
  const p = (n: number) => String(n).padStart(2, '0')
  return `${d.getFullYear()}-${p(d.getMonth() + 1)}-${p(d.getDate())} ${p(d.getHours())}:${p(d.getMinutes())}:${p(d.getSeconds())}`
}

export function fmtShort(s?: string | null): string {
  if (!s) return '—'
  let t = s
  if (!/Z$|[+-]\d\d:\d\d$/.test(t)) t += 'Z'
  const d = new Date(t)
  if (isNaN(d.getTime())) return s
  const p = (n: number) => String(n).padStart(2, '0')
  return `${p(d.getMonth() + 1)}-${p(d.getDate())} ${p(d.getHours())}:${p(d.getMinutes())}`
}
