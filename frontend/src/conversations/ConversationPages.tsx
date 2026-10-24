import { useCallback, useEffect, useState } from 'react'
import { Link, useNavigate, useParams } from 'react-router'
import { useAuth } from '../auth/context'
import { Alert, Button, ButtonLink, Card, LoadingState } from '../components/ui'
import { conversationApi, type ConversationDetail, type ConversationPage } from './api'
import styles from './conversations.module.css'

const labels: Record<string, string> = { idle: 'No messages yet', pending: 'Waiting for response', completed: 'Answered', fallback: 'Fallback response', failed: 'Response failed', uncertain: 'Status uncertain', version_changed: 'Published version changed' }
const statusText: Record<string, string> = { pending: 'This response is still pending.', failed: 'The assistant response was not saved.', uncertain: 'The result could not be confirmed.', version_changed: 'The published assistant changed during this turn.' }

export function ConversationListPage() {
  const { id = '' } = useParams()
  const { store } = useAuth()
  const [data, setData] = useState<ConversationPage | null>(null)
  const [cursor, setCursor] = useState<string | undefined>()
  const [previous, setPrevious] = useState<string[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')
  const [attempt, setAttempt] = useState(0)
  const load = useCallback(async (signal: AbortSignal) => {
    try { const value = await conversationApi(store, id, signal).list(cursor); setError(''); setData(value) }
    catch (e) { if (!signal.aborted) setError(e instanceof Error ? e.message : 'Conversation history is unavailable.') }
    finally { if (!signal.aborted) setLoading(false) }
  }, [store, id, cursor])
  useEffect(() => {
    const c = new AbortController()
    queueMicrotask(() => { if (!c.signal.aborted) void load(c.signal) })
    return () => c.abort()
  }, [load, attempt])
  return <section className={styles.page}>
    <header className={styles.heading}><div><h1>Visitor conversations</h1><p>Messages received through the published widget, grouped by conversation.</p></div><ButtonLink variant="secondary" to={`/assistants/${encodeURIComponent(id)}/publish`}>Publishing</ButtonLink></header>
    {error && <Alert kind="error">{error}</Alert>}
    {loading ? <LoadingState label="Loading conversations…" /> : !error && data?.items.length === 0 ? <Card><h2>No visitor conversations yet</h2><p>New conversations appear here after a visitor starts a chat.</p></Card> : null}
    {data && data.items.length > 0 && <Card className={styles.list}><ul>{data.items.map(item => <li key={item.conversation_id}><Link to={`/assistants/${encodeURIComponent(id)}/conversations/${encodeURIComponent(item.conversation_id)}`}><span><strong>Conversation</strong><small>{new Date(item.last_activity_at ?? item.created_at).toLocaleString()}</small></span><span className={styles.meta}>{labels[item.latest_status] ?? 'Status unavailable'}{item.latest_published_version ? ` · v${item.latest_published_version}` : ''}</span></Link></li>)}</ul></Card>}
    {(data?.next_cursor || previous.length > 0) && <nav className={styles.paging} aria-label="Conversation pages"><Button variant="secondary" disabled={!previous.length || loading} onClick={() => { setLoading(true); setCursor(previous.at(-1)); setPrevious(v => v.slice(0, -1)) }}>Previous</Button><Button variant="secondary" disabled={!data?.next_cursor || loading} onClick={() => { if (data?.next_cursor) { setLoading(true); setPrevious(v => [...v, cursor ?? '']); setCursor(data.next_cursor) } }}>Next</Button></nav>}
    {error && <Button variant="secondary" onClick={() => { setLoading(true); setAttempt(v => v + 1) }}>Try again</Button>}
  </section>
}

export function ConversationDetailPage() {
  const { id = '', conversationId = '' } = useParams()
  const { store } = useAuth()
  const navigate = useNavigate()
  const [data, setData] = useState<ConversationDetail | null>(null)
  const [cursor, setCursor] = useState<string | undefined>()
  const [olderCursors, setOlderCursors] = useState<string[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')
  const [attempt, setAttempt] = useState(0)
  const load = useCallback(async (signal: AbortSignal) => {
    try { const value = await conversationApi(store, id, signal).detail(conversationId, cursor); setError(''); setData(value) }
    catch (e) { if (!signal.aborted) setError(e instanceof Error ? e.message : 'Conversation is unavailable.') }
    finally { if (!signal.aborted) setLoading(false) }
  }, [store, id, conversationId, cursor])
  useEffect(() => {
    const c = new AbortController()
    queueMicrotask(() => { if (!c.signal.aborted) void load(c.signal) })
    return () => c.abort()
  }, [load, attempt])
  return <section className={styles.page}>
    <header className={styles.heading}><div><h1>Conversation details</h1><p>Started {data ? new Date(data.created_at).toLocaleString() : '—'}</p></div><Button variant="secondary" onClick={() => navigate(`/assistants/${encodeURIComponent(id)}/conversations`)}>Back to history</Button></header>
    {error && <Alert kind="error">{error}</Alert>}{loading && <LoadingState label="Loading messages…" />}
    {!loading && data?.turns.length === 0 && <Card><p>No messages are available in this page.</p></Card>}
    {data && <ol className={styles.turns}>{data.turns.map((turn, index) => <li key={`${turn.user_created_at}-${index}`}>
      <Card className={styles.turn}><p className={styles.role}>Visitor · {new Date(turn.user_created_at).toLocaleString()}</p><p dir="auto">{turn.user_message}</p>
        {turn.assistant_message ? <><p className={styles.role}>Assistant{turn.assistant_created_at ? ` · ${new Date(turn.assistant_created_at).toLocaleString()}` : ''} · {labels[turn.status] ?? 'Answered'} · v{turn.published_version}</p><p dir="auto">{turn.assistant_message}</p></> : <Alert kind={turn.status === 'failed' || turn.status === 'uncertain' ? 'error' : 'info'}>{statusText[turn.status] ?? labels[turn.status] ?? 'No saved answer is available.'} · Published v{turn.published_version}</Alert>}
      </Card>
    </li>)}</ol>}
    {data?.next_cursor && <div className={styles.paging}><Button variant="secondary" disabled={loading} onClick={() => { setLoading(true); setOlderCursors(v => [...v, cursor ?? '']); setCursor(data.next_cursor ?? undefined) }}>Load older messages</Button></div>}
    {cursor && olderCursors.length > 0 && <Button variant="secondary" onClick={() => { setLoading(true); setCursor(olderCursors.at(-1)); setOlderCursors(v => v.slice(0, -1)) }}>Newer messages</Button>}
    {error && <Button variant="secondary" onClick={() => { setLoading(true); setAttempt(v => v + 1) }}>Try again</Button>}
    <Link to={`/assistants/${encodeURIComponent(id)}/publish`}>Publishing settings</Link>
  </section>
}
