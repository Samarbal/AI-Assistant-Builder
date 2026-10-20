import { useEffect, useRef, useState } from 'react'
import { useNavigate, useParams } from 'react-router'
import { useAuth } from '../auth/context'
import { Alert, Badge, Button, ButtonLink, Card, LoadingState, TextField } from '../components/ui'
import { assistantApi, type Assistant, type Configuration } from './api'
import styles from './assistants.module.css'

const empty: Configuration = { name: '', role: '', response_style: '', tone: '', fallback_message: '', colors: {} }
const fields = [ ['name', 'Assistant name', 120], ['role', 'Role', 500], ['response_style', 'Response style', 100], ['tone', 'Tone of voice', 100], ['fallback_message', 'Fallback message', 500] ] as const
const message = (error: unknown) => error instanceof Error && error.message !== 'Failed to fetch' ? error.message : 'Connection failed. Your input is preserved. Check the assistant list before retrying a save.'

export function AssistantList() {
  const { store } = useAuth()
  const [items, setItems] = useState<Assistant[] | null>(null)
  const [error, setError] = useState('')
  const [attempt, setAttempt] = useState(0)
  useEffect(() => {
    const controller = new AbortController()
    void assistantApi(store, controller.signal).list().then(data => { if (!controller.signal.aborted) setItems(data) }).catch(e => { if (!controller.signal.aborted) setError(message(e)) })
    return () => controller.abort()
  }, [store, attempt])
  return <section className={styles.page}><header className={styles.heading}><div><h1>Your assistants</h1><p>Build, manage, and grow your AI assistants.</p></div><ButtonLink to="/assistants/new">Create assistant</ButtonLink></header>
    {error ? <><Alert kind="error">{error}</Alert><Button onClick={() => { setError(''); setItems(null); setAttempt(attempt + 1) }}>Try again</Button></> : !items ? <LoadingState label="Loading assistants…" /> : items.length === 0 ? <Card><h2>Create your first assistant</h2><p>Give it a purpose and a voice that feels like your business.</p></Card> : <div className={styles.grid}>{items.map(item => <Card key={item.id}><Badge>{item.state}</Badge><h2>{item.name}</h2><p>{item.role}</p><ButtonLink variant="secondary" to={`/assistants/${item.id}/configuration`}>Configure {item.name}</ButtonLink></Card>)}</div>}
  </section>
}

export function AssistantEditor() {
  const { id } = useParams()
  return <Editor key={id ?? 'new'} />
}
function Editor() {
  const { id } = useParams()
  const { store } = useAuth()
  const navigate = useNavigate()
  const [data, setData] = useState<Configuration>(empty)
  const [original, setOriginal] = useState<Configuration>(empty)
  const [loading, setLoading] = useState(!!id)
  const [error, setError] = useState('')
  const [saved, setSaved] = useState(false)
  const [busy, setBusy] = useState(false)
  const locked = useRef(false)
  const controller = useRef<AbortController | null>(null)
  useEffect(() => {
    const active = new AbortController(); controller.current = active
    if (id) void assistantApi(store, active.signal).get(id).then(value => {
      if (!active.signal.aborted) { const config = { name: value.name, role: value.role, response_style: value.response_style, tone: value.tone, fallback_message: value.fallback_message, colors: value.colors }; setData(config); setOriginal(config); setLoading(false) }
    }).catch(e => { if (!active.signal.aborted) setError(message(e)) })
    return () => active.abort()
  }, [id, store])
  const dirty = JSON.stringify(data) !== JSON.stringify(original)
  if (loading) return error ? <Alert kind="error">{error}</Alert> : <LoadingState label="Loading configuration…" />
  return <section className={styles.page}><header className={styles.heading}><div><h1>{id ? 'Assistant configuration' : 'Create an assistant'}</h1><p>Give your assistant a clear purpose and a personality that feels like you.</p></div><Badge>{dirty ? 'Unsaved changes' : 'Draft'}</Badge></header>
    <div className={styles.editor}><form className={styles.page} onSubmit={async event => {
      event.preventDefault(); if (locked.current || !controller.current) return
      locked.current = true; setBusy(true); setError(''); setSaved(false)
      const active = controller.current
      try {
        const api = assistantApi(store, active.signal)
        const changes = Object.fromEntries(Object.entries(data).filter(([key, value]) => JSON.stringify(value) !== JSON.stringify(original[key as keyof Configuration])))
        const result = id ? await api.update(id, changes) : await api.create(data)
        if (!active.signal.aborted) { setOriginal(data); setSaved(true); if (!id) navigate(`/assistants/${result.id}/configuration`, { replace: true }) }
      } catch (e) { if (!active.signal.aborted) setError(message(e)) }
      finally { locked.current = false; if (!active.signal.aborted) setBusy(false) }
    }}>
      <Card><div className={styles.page}><h2>Assistant basics & voice</h2>{fields.map(([key, label, limit]) => <TextField key={key} label={label} value={data[key]} required maxLength={limit} disabled={busy} onChange={event => { setSaved(false); setData({ ...data, [key]: event.target.value }) }} hint={key === 'fallback_message' ? 'Used when sufficient business knowledge cannot be found.' : undefined} />)}</div></Card>
      <Card><h2>Brand colors</h2><div className={styles.grid}>{(['primary', 'accent'] as const).map(key => <TextField key={key} label={`${key === 'primary' ? 'Primary' : 'Accent'} color`} type="color" className={styles.colorPicker} value={/^#[0-9a-f]{6}$/i.test(data.colors[key] ?? '') ? data.colors[key] : '#635bff'} hint="Select the swatch to choose a color." disabled={busy} onChange={event => { const colors = { ...data.colors }; if (event.target.value) colors[key] = event.target.value; else delete colors[key]; setData({ ...data, colors }); setSaved(false) }} />)}</div></Card>
      {error && <Alert kind="error">{error}</Alert>}{saved && <Alert>Draft saved.</Alert>}
      <div className={styles.heading}><ButtonLink variant="secondary" to="/assistants">Back to assistants</ButtonLink><Button type="submit" busy={busy} disabled={!!id && !dirty}>{id ? 'Save changes' : 'Create assistant'}</Button></div>
    </form><aside><Card><h2>A first look</h2><Badge>Appearance preview</Badge><h3>{data.name || 'Your assistant'}</h3><p>{data.fallback_message || 'Your fallback message will appear here.'}</p><p>Interactive testing will be available in a later phase.</p></Card></aside></div>
  </section>
}
