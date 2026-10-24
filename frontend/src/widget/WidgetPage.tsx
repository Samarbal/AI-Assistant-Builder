import { useEffect, useRef, useState } from 'react'
import type { CSSProperties, FormEvent } from 'react'
import { useSearchParams } from 'react-router'
import styles from './widget.module.css'

type PublicAssistant = { name: string; colors: Record<string, string>; version: number }
type PublicAnswer = { message_id: string; answer: string; outcome: 'grounded' | 'fallback'; created_at: string; version: number }
type Turn = { question: string; answer: PublicAnswer }

function apiUrl(path: string) {
  const configured = import.meta.env.VITE_PUBLIC_API_ORIGIN as string | undefined
  const base = (configured || window.location.origin).replace(/\/$/, '')
  return `${base}${path}`
}
function detailError(payload: unknown, status: number) {
  const code = typeof payload === 'object' && payload !== null && 'detail' in payload
    ? (payload as { detail?: { code?: unknown } }).detail?.code : undefined
  if (code === 'public_chat_disabled') return 'Chat is temporarily unavailable. Please try again later.'
  if (code === 'demo_access_denied' || status === 404) return 'That demo access code is not available. Check it with your demo host.'
  if (status === 429) return 'Please wait a moment before sending another message.'
  if (status === 409) return 'This chat changed or is processing another request. Start a new chat to continue.'
  return 'The assistant could not complete this request. Please try again later.'
}
function isRtl(text: string) { return /[\u0590-\u08ff]/u.test(text) }

export function WidgetPage() {
  const [params] = useSearchParams()
  const publicId = params.get('public_id') ?? ''
  const [accessCode, setAccessCode] = useState('')
  const [assistant, setAssistant] = useState<PublicAssistant | null>(null)
  const [conversationId, setConversationId] = useState('')
  const [conversationToken, setConversationToken] = useState('')
  const [message, setMessage] = useState('')
  const [turns, setTurns] = useState<Turn[]>([])
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const [starting, setStarting] = useState(false)
  const messagesRef = useRef<HTMLOListElement>(null)
  const primary = /^#[0-9a-f]{6}$/i.test(assistant?.colors?.primary ?? '') ? assistant!.colors.primary : '#635bff'

  useEffect(() => { messagesRef.current?.lastElementChild?.scrollIntoView?.({ block: 'nearest' }) }, [turns, busy])
  async function startChat(event: FormEvent) {
    event.preventDefault()
    if (starting || !publicId || !accessCode.trim()) return
    setStarting(true); setError('')
    try {
      const headers = { 'X-Demo-Access': accessCode.trim() }
      const profileResponse = await fetch(apiUrl(`/public/assistants/${encodeURIComponent(publicId)}`), { headers, cache: 'no-store' })
      if (!profileResponse.ok) throw new Error(detailError(await profileResponse.json().catch(() => null), profileResponse.status))
      const profile = await profileResponse.json() as PublicAssistant
      if (typeof profile.name !== 'string' || !Number.isInteger(profile.version) || !profile.colors || typeof profile.colors !== 'object') throw new Error('The assistant profile could not be loaded.')
      const response = await fetch(apiUrl(`/public/assistants/${encodeURIComponent(publicId)}/conversations`), {
        method: 'POST', headers: { ...headers, 'Content-Type': 'application/json' }, body: '{}', cache: 'no-store',
      })
      if (!response.ok) throw new Error(detailError(await response.json().catch(() => null), response.status))
      const conversation = await response.json() as { conversation_id: string; conversation_token: string }
      if (!conversation.conversation_id || !conversation.conversation_token) throw new Error('A secure chat session could not be started.')
      setAssistant(profile); setConversationId(conversation.conversation_id); setConversationToken(conversation.conversation_token)
    } catch (e) { setError(e instanceof Error ? e.message : 'Chat is unavailable. Please try again later.') }
    finally { setStarting(false) }
  }
  async function send(event: FormEvent) {
    event.preventDefault()
    const question = message.trim()
    if (!question || question.length > 4000 || busy || !conversationToken) return
    setBusy(true); setError('')
    const requestId = crypto.randomUUID()
    try {
      const response = await fetch(apiUrl(`/public/assistants/${encodeURIComponent(publicId)}/conversations/${encodeURIComponent(conversationId)}/messages`), {
        method: 'POST', headers: { 'Content-Type': 'application/json', 'X-Demo-Access': accessCode.trim(), 'X-Visitor-Token': conversationToken },
        body: JSON.stringify({ message: question, request_id: requestId }), cache: 'no-store',
      })
      const result = await response.json().catch(() => null)
      if (!response.ok) throw new Error(detailError(result, response.status))
      const answer = result as PublicAnswer
      if (typeof answer.answer !== 'string' || !['grounded', 'fallback'].includes(answer.outcome)) throw new Error('The assistant returned an invalid response.')
      setTurns(current => [...current, { question, answer }]); setMessage('')
    } catch (e) { setError(e instanceof Error ? e.message : 'The assistant could not complete this request.') }
    finally { setBusy(false) }
  }
  function close() {
    if (window.parent === window || !document.referrer) return
    try { window.parent.postMessage({ type: 'assistant-widget-close' }, new URL(document.referrer).origin) }
    catch { /* No referrer means there is no embedding parent to notify. */ }
  }

  if (!publicId) return <main className={styles.widget} role="alert">This chat link is incomplete.</main>
  if (!assistant) return <main className={styles.widget}>
    <header className={styles.header}><span className={styles.brandMark} aria-hidden="true">✦</span><div><strong>Private demo chat</strong><small>Access is limited to approved testers.</small></div><button className={styles.close} aria-label="Close chat" onClick={close}>×</button></header>
    <form className={styles.access} onSubmit={event => void startChat(event)}>
      <h1>Enter demo access code</h1><p>The code is sent securely to the demo service and is kept only in this chat frame while open.</p>
      <label htmlFor="demo-access">Demo access code</label><input id="demo-access" type="password" autoComplete="off" value={accessCode} onChange={event => setAccessCode(event.target.value)} maxLength={512} required />
      {error && <p className={styles.error} role="alert">{error}</p>}
      <button className={styles.primary} style={{ backgroundColor: primary }} disabled={starting}>{starting ? 'Connecting…' : 'Start chat'}</button>
    </form>
    <footer>Private demo · Your access code is not stored in this browser.</footer>
  </main>
  return <main className={styles.widget} style={{ '--widget-primary': primary } as CSSProperties}>
    <header className={styles.header}><span className={styles.brandMark} aria-hidden="true">{assistant.name.slice(0, 1).toLocaleUpperCase()}</span><div><strong>{assistant.name}</strong><small>Published assistant · version {assistant.version}</small></div><button className={styles.close} aria-label="Close chat" onClick={close}>×</button></header>
    <ol className={styles.messages} aria-label="Chat messages" aria-live="polite" ref={messagesRef}>
      {!turns.length && <li className={styles.hint}>Ask a question about this assistant’s knowledge.</li>}
      {turns.map((turn, index) => <li key={`${turn.answer.message_id}-${index}`} className={styles.turn}>
        <p className={styles.question} dir="auto">{turn.question}</p><div className={styles.answer} dir={isRtl(turn.answer.answer) ? 'rtl' : 'auto'}>{turn.answer.answer}{turn.answer.outcome === 'fallback' && <small className={styles.fallback}>This is the assistant’s configured fallback.</small>}</div>
      </li>)}
      {busy && <li className={styles.loading} role="status">Thinking…</li>}
    </ol>
    {error && <p className={styles.error} role="alert">{error}</p>}
    <form className={styles.composer} onSubmit={event => void send(event)}>
      <label htmlFor="widget-message" className={styles.srOnly}>Message {assistant.name}</label>
      <textarea id="widget-message" value={message} onChange={event => setMessage(event.target.value)} maxLength={4000} rows={2} dir="auto" placeholder="Ask a question…" disabled={busy} />
      <button className={styles.primary} disabled={busy || !message.trim()} aria-label="Send message">{busy ? '…' : 'Send'}</button>
    </form>
    <footer>Responses may be incorrect. Check important information independently.</footer>
  </main>
}
