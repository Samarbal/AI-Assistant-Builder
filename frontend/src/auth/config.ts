export function publicAuthConfig(env: Record<string, unknown>) {
  const url = String(env.VITE_SUPABASE_URL ?? '').trim()
  const key = String(env.VITE_SUPABASE_PUBLISHABLE_KEY ?? '').trim()
  if (!url && !key) return null
  const invalid = () => { throw new Error('Invalid public Auth configuration. Use an HTTPS project URL and a publishable or legacy anon key only.') }
  try {
    const parsed = new URL(url)
    if (parsed.protocol !== 'https:' || parsed.username || parsed.password || parsed.search || parsed.hash || !['', '/'].includes(parsed.pathname)) invalid()
  } catch { invalid() }
  if (!/^sb_publishable_[A-Za-z0-9_-]+$/.test(key)) {
    try {
      const part = key.split('.')[1]
      const payload = JSON.parse(atob(part.replace(/-/g, '+').replace(/_/g, '/')))
      if (key.split('.').length !== 3 || payload.role !== 'anon') invalid()
    } catch { invalid() }
  }
  return { url, key }
}
