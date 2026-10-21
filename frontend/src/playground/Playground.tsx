import { useEffect, useRef, useState } from 'react'
import type { FormEvent } from 'react'
import { Link, useParams } from 'react-router'
import { useAuth } from '../auth/context'
import { Alert, Badge, Button, Card, LoadingState } from '../components/ui'
import { PlaygroundError, playgroundApi, type PlaygroundAnswer } from './api'
import styles from './playground.module.css'

type Turn = { id: number; question: string; result: PlaygroundAnswer }

const isArabic = (value: string) => /[\u0600-\u06ff\u0750-\u077f\u08a0-\u08ff]/u.test(value)

export function Playground() {
  const { id = '' } = useParams()
  const { store } = useAuth()
  const [assistantLoad, setAssistantLoad] = useState<{ id: string; attempt: number; name?: string; error?: string } | null>(null)
  const [message, setMessage] = useState('')
  const [turns, setTurns] = useState<Turn[]>([])
  const [busy, setBusy] = useState(false)
  const [sendError, setSendError] = useState('')
  const [attempt, setAttempt] = useState(0)
  const [direction, setDirection] = useState<'ltr' | 'rtl'>('ltr')
  const controller = useRef<AbortController | null>(null)
  const chat = useRef<HTMLOListElement>(null)
  const locked = useRef(false)

  useEffect(() => {
    const active = new AbortController()
    controller.current = active
    void playgroundApi(store, id, active.signal).assistant().then(assistant => {
      if (!active.signal.aborted) {
        setAssistantLoad({ id, attempt, name: assistant.name })
      }
    }).catch(error => {
      if (!active.signal.aborted) {
        setAssistantLoad({ id, attempt, error: error instanceof PlaygroundError ? error.message : 'Could not load this assistant. Check your connection and try again.' })
      }
    })
    return () => active.abort()
  }, [id, store, attempt])

  useEffect(() => {
    chat.current?.lastElementChild?.scrollIntoView?.({ block: 'nearest', behavior: 'smooth' })
  }, [turns, busy])

  async function submit(event?: FormEvent) {
    event?.preventDefault()
    const question = message.trim()
    if (!question || question.length > 4000 || locked.current || !controller.current) return
    locked.current = true
    setBusy(true)
    setSendError('')
    try {
      const result = await playgroundApi(store, id, controller.current.signal).send(question)
      setTurns(current => [...current, { id: Date.now(), question, result }])
      setMessage('')
      if (isArabic(question) || isArabic(result.answer)) setDirection('rtl')
    } catch (error) {
      if (!controller.current.signal.aborted) {
        setSendError(error instanceof PlaygroundError ? error.message : 'The request timed out or the connection was interrupted. Your question is still here; you can retry.')
      }
    } finally {
      locked.current = false
      if (!controller.current?.signal.aborted) setBusy(false)
    }
  }

  function reset() { setTurns([]); setMessage(''); setSendError('') }

  const loaded = assistantLoad?.id === id && assistantLoad.attempt === attempt ? assistantLoad : null
  const name = loaded?.name ?? ''
  if (!loaded) return <LoadingState label="Loading assistant playground…" />
  if (loaded.error) return <section className={styles.page}><Alert kind="error">{loaded.error}</Alert><div className={styles.actions}><Button variant="secondary" onClick={() => setAttempt(value => value + 1)}>Try again</Button><Link to={`/assistants/${encodeURIComponent(id)}/configuration`}>Back to configuration</Link></div></section>

  return <section className={styles.page}>
    <header className={styles.heading}>
      <div><h1>Meet {name}</h1><p>Try a question to see how your saved draft responds.</p></div>
      <Button variant="secondary" onClick={reset} aria-label="Reset conversation" disabled={!turns.length && !message && !sendError}>↶ <span>Reset conversation</span></Button>
    </header>
    <ol className={styles.steps} aria-label="Assistant setup progress">
      <li><span aria-hidden="true">✓</span><span>Configure</span><b aria-hidden="true">›</b></li>
      <li><span aria-hidden="true">✓</span><span>Knowledge</span><b aria-hidden="true">›</b></li>
      <li aria-current="step"><span aria-hidden="true">3</span><span>Test</span><b aria-hidden="true">›</b></li>
      <li><span aria-hidden="true">4</span><span>Publish</span></li>
    </ol>
    <div className={styles.workspace}>
      <Card className={styles.chat}>
        <div className={styles.chatHeader}>
          <div className={styles.avatar} aria-hidden="true">{name.slice(0, 1).toLocaleUpperCase()}</div>
          <div className={styles.identity}><strong>{name}</strong><span>Draft assistant · Private test</span></div>
          <Badge>Test mode</Badge>
        </div>
        <p className={styles.privateNote}>Preview conversation · Only visible to you</p>
        <ol ref={chat} className={styles.messages} aria-label="Playground messages" aria-live="polite">
          {turns.length === 0 && !busy && <li className={styles.intro} dir={direction}>
            <p>Ask a question to test the assistant’s current configuration and knowledge.</p>
          </li>}
          {turns.map(turn => <li key={turn.id} className={styles.turn} data-testid="playground-turn">
            <div className={styles.userMessage} dir="auto"><p>{turn.question}</p></div>
            <div className={styles.assistantMessage} dir="auto">
              <p dir="auto" data-testid="playground-answer">{turn.result.answer}</p>
              {turn.result.outcome === 'fallback' && <span className={styles.fallback}>No relevant answer was found in the connected knowledge.</span>}
              {turn.result.citations.length > 0 && <ul className={styles.citations} aria-label="Answer sources">
                {turn.result.citations.map(citation => <li key={citation.chunk_id}>
                  <strong>{citation.filename}</strong><blockquote dir="auto">{citation.excerpt}</blockquote>
                </li>)}
              </ul>}
            </div>
          </li>)}
          {busy && <li className={styles.assistantMessage} role="status"><LoadingState label="Thinking…" /></li>}
        </ol>
        {sendError && <div className={styles.errorBox}><Alert kind="error">{sendError}</Alert><Button variant="secondary" onClick={() => void submit()}>Retry question</Button></div>}
        <form className={styles.composer} onSubmit={event => void submit(event)}>
          <label className={styles.srOnly} htmlFor="playground-message">Ask {name} a question</label>
          <textarea id="playground-message" value={message} maxLength={4000} rows={2} dir="auto" placeholder="Ask a question…" disabled={busy}
            onChange={event => setMessage(event.target.value)} onKeyDown={event => {
              if (event.key === 'Enter' && !event.shiftKey) { event.preventDefault(); void submit() }
            }} />
          <Button type="submit" busy={busy} disabled={!message.trim() || message.length > 4000} aria-label="Send question">↑</Button>
          <small>Independent test turn · AI responses can be wrong. Check important answers.</small>
        </form>
      </Card>
      <aside className={styles.guidance}>
        <Alert>Test mode · Only visible to you<br />Playground messages do not appear in visitor conversations.</Alert>
        <Card><h2>Try a question</h2><p>Ask about information in this assistant’s connected knowledge.</p><div className={styles.exampleQuestion}>For example: ask about a policy, product, or service.</div></Card>
        <Card><h2>Connected knowledge</h2><p>Answers include a source file and excerpt when relevant evidence is found. Unknown questions use the configured fallback.</p><Link to={`/assistants/${encodeURIComponent(id)}/knowledge`}>Manage knowledge →</Link></Card>
        <p className={styles.publishNote}>Publishing and website embedding are not available here yet.</p>
      </aside>
    </div>
  </section>
}
