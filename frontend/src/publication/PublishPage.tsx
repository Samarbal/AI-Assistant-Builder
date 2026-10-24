import { useCallback, useEffect, useState } from 'react'
import { Link, useParams } from 'react-router'
import { useAuth } from '../auth/context'
import { Alert, Badge, Button, Card, LoadingState } from '../components/ui'
import { publicationApi, type EmbedResult, type PublicationStatus } from './api'
import styles from './publish.module.css'

export function PublishPage() {
  const { id = '' } = useParams()
  const { store } = useAuth()
  const [status, setStatus] = useState<PublicationStatus | null>(null)
  const [embed, setEmbed] = useState<EmbedResult | null>(null)
  const [loading, setLoading] = useState(true)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const [notice, setNotice] = useState('')
  const [attempt, setAttempt] = useState(0)
  const load = useCallback(async (signal: AbortSignal) => {
    try {
      const api = publicationApi(store, id, signal)
      const value = await api.status()
      if (signal.aborted) return
      setError('')
      setStatus(value)
      setEmbed(null)
      if (value.published) setEmbed(await api.embed())
    } catch (e) { if (!signal.aborted) setError(e instanceof Error ? e.message : 'Could not load publication status.') }
    finally { if (!signal.aborted) setLoading(false) }
  }, [store, id])
  useEffect(() => {
    const controller = new AbortController()
    queueMicrotask(() => { if (!controller.signal.aborted) void load(controller.signal) })
    return () => controller.abort()
  }, [load, attempt])
  async function publish() {
    if (!status || busy) return
    setBusy(true); setError(''); setNotice('')
    const controller = new AbortController()
    try {
      await publicationApi(store, id, controller.signal).publish(status)
      setLoading(true)
      await load(controller.signal)
      setNotice('Your published version is active. The previous version remains available for recovery.')
    } catch (e) { setError(e instanceof Error ? e.message : 'Publishing failed safely. Refresh status before retrying.') }
    finally { setBusy(false) }
  }
  async function copy() {
    if (!embed) return
    try { await navigator.clipboard.writeText(embed.snippet); setNotice('Embed code copied.') }
    catch { setError('Clipboard access was blocked. Select and copy the embed code manually.') }
  }
  if (loading && !status) return <LoadingState label="Checking publication readiness…" />
  return <section className={styles.page}>
    <header className={styles.heading}><div><h1>Publish & embed</h1><p>Review the current draft, publish a snapshot, and add the widget to your website.</p></div><Badge>{status?.published ? `Published · v${status.version}` : 'Private draft'}</Badge></header>
    {error && <Alert kind="error">{error} <button className={styles.inline} onClick={() => { setLoading(true); setAttempt(v => v + 1) }}>Refresh status</button></Alert>}
    {notice && <Alert>{notice}</Alert>}
    {status && <>
      <Card className={styles.card}>
        <h2>Readiness</h2>
        <p>{status.readiness === 'ready' ? 'Knowledge is prepared for publishing.' : status.readiness === 'fallback_only' ? 'This assistant will use its configured fallback until knowledge is added.' : status.readiness === 'needs_preparation' ? 'Prepare all attached knowledge before publishing.' : status.readiness === 'processing' ? 'A knowledge file is still processing. Publishing is paused.' : 'A knowledge file failed. Remove or replace it before publishing.'}</p>
        <dl><div><dt>Current public version</dt><dd>{status.published ? `Version ${status.version}` : 'Not published'}</dd></div><div><dt>Draft changes</dt><dd>{status.has_changes ? 'Changes waiting to publish' : status.published ? 'No changes' : 'Ready for first publish'}</dd></div>{status.published_at && <div><dt>Last published</dt><dd><time dateTime={status.published_at}>{new Date(status.published_at).toLocaleString()}</time></dd></div>}</dl>
        <Alert>Publishing makes this assistant and its selected knowledge available to anyone with the widget. Public chat remains controlled by the server-side demo gate.</Alert>
        <div className={styles.actions}><Button busy={busy} disabled={!['ready', 'fallback_only'].includes(status.readiness) || (status.published && !status.has_changes)} onClick={() => void publish()}>{status.published ? 'Publish update' : 'Publish assistant'}</Button><Button variant="secondary" disabled={busy || loading} onClick={() => { setLoading(true); setAttempt(v => v + 1) }}>Refresh</Button></div>
      </Card>
      {status.published && embed && <Card className={styles.card}><h2>Website embed</h2><p>Copy this snippet into your site. It contains only the public assistant identifier, never your owner session or demo access code.</p><label className={styles.srOnly} htmlFor="embed-snippet">Embed code</label><textarea id="embed-snippet" readOnly value={embed.snippet} rows={3} spellCheck={false} /><Button variant="secondary" onClick={() => void copy()}>Copy embed code</Button></Card>}
    </>}
    <Card className={styles.card}><h2>Related pages</h2><div className={styles.links}><Link to={`/assistants/${encodeURIComponent(id)}/knowledge`}>Manage knowledge</Link><Link to={`/assistants/${encodeURIComponent(id)}/conversations`}>View visitor conversations</Link></div></Card>
  </section>
}
