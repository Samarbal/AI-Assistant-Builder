import { useEffect, useRef, useState } from 'react'
import { useParams } from 'react-router'
import { useAuth } from '../auth/context'
import { Alert, Badge, Button, Card, LoadingState } from '../components/ui'
import { knowledgeApi, knowledgeError, KnowledgeError, MAX_FILES, validateFile, type KnowledgeFile } from './api'
import styles from './knowledge.module.css'
import uploadIcon from '../assets/icons/knowledge-upload.svg'
import fileIcon from '../assets/icons/knowledge-file.svg'
import downloadIcon from '../assets/icons/knowledge-download.svg'
import removeIcon from '../assets/icons/knowledge-remove.svg'
import readyIcon from '../assets/icons/knowledge-ready.svg'
import processingIcon from '../assets/icons/knowledge-processing.svg'
import failedIcon from '../assets/icons/knowledge-failed.svg'
import bookIcon from '../assets/icons/knowledge-book.svg'
import checkIcon from '../assets/icons/knowledge-check.svg'
import infoIcon from '../assets/icons/knowledge-info.svg'
import plusIcon from '../assets/icons/knowledge-plus.svg'

const states: Record<string, string> = { reserved: 'Waiting to process', processing: 'Processing', extracted: 'Text extracted', failed: 'Needs attention' }
const failures: Record<string, string> = {
  invalid_document: 'This document could not be read. Use an unencrypted PDF with selectable text or a valid DOCX.',
  storage_unavailable: 'File storage was unavailable.', processing_failed: 'Text extraction failed.', processing_timeout: 'Processing was interrupted or timed out.',
}
type SignedLink = { fileId: string; url: string; expiresAt: number }

function TemporaryDownload({ link }: { link: SignedLink }) {
  const [expired, setExpired] = useState(() => Date.now() >= link.expiresAt)
  useEffect(() => { const timer = setTimeout(() => setExpired(true), Math.max(0, link.expiresAt - Date.now())); return () => clearTimeout(timer) }, [link.expiresAt])
  return expired ? <p role="status">Download link expired. Select Download to request a new one.</p> : <p role="status"><a href={link.url} target="_blank" rel="noopener noreferrer" referrerPolicy="no-referrer" onClick={event => { if (Date.now() >= link.expiresAt) { event.preventDefault(); setExpired(true) } }}>Open private download</a> · Expires shortly. Do not share this link.</p>
}

export function KnowledgeFiles() {
  const { id } = useParams()
  return id ? <FileManager key={id} assistantId={id} /> : <Alert kind="error">Assistant not found.</Alert>
}

function FileManager({ assistantId }: { assistantId: string }) {
  const { store } = useAuth()
  const [files, setFiles] = useState<KnowledgeFile[]>([])
  const [loading, setLoading] = useState(true)
  const [verified, setVerified] = useState(false)
  const [error, setError] = useState('')
  const [notice, setNotice] = useState('')
  const [selected, setSelected] = useState<File | null>(null)
  const [selectionError, setSelectionError] = useState('')
  const [busy, setBusy] = useState('')
  const [confirm, setConfirm] = useState<string | null>(null)
  const [link, setLink] = useState<SignedLink | null>(null)
  const input = useRef<HTMLInputElement>(null)
  const removeTrigger = useRef<HTMLButtonElement | null>(null)
  const filesHeading = useRef<HTMLHeadingElement>(null)
  const controller = useRef<AbortController | null>(null)
  const locked = useRef(false)

  useEffect(() => {
    const active = new AbortController(); controller.current = active
    void knowledgeApi(store, assistantId, active.signal).list().then(data => {
      if (!active.signal.aborted) { setFiles(data); setVerified(true) }
    }).catch(e => { if (!active.signal.aborted) setError(knowledgeError(e)) })
      .finally(() => { if (!active.signal.aborted) setLoading(false) })
    return () => active.abort()
  }, [assistantId, store])

  const disabled = loading || !!busy || !verified
  const full = files.length >= MAX_FILES
  function choose(list: FileList | null) {
    if (disabled || full) return
    setSelected(null); setSelectionError('')
    if (!list?.length) return
    if (list.length !== 1) { setSelectionError('Choose one file at a time.'); return }
    const validation = validateFile(list[0])
    if (validation) setSelectionError(validation)
    else setSelected(list[0])
  }
  async function run(action: 'refresh' | 'upload' | 'remove' | 'download', file?: KnowledgeFile) {
    if (locked.current || !controller.current || (action !== 'refresh' && disabled)) return
    if (action === 'upload' && (!selected || full)) return
    const active = controller.current
    const api = knowledgeApi(store, assistantId, active.signal)
    locked.current = true; setBusy(action); setError(''); setNotice(''); setLink(null)
    const started = Date.now()
    let removed = false
    try {
      if (action === 'upload') { await api.upload(selected!); if (!active.signal.aborted) { setSelected(null); if (input.current) input.current.value = ''; setNotice('File uploaded. Review its processing status below.') } }
      if (action === 'remove' && file) { await api.remove(file.id); removed = true; if (!active.signal.aborted) { setConfirm(null); setNotice('File removed from this assistant’s draft. You may upload a replacement.') } }
      if (action === 'download' && file) {
        const result = await api.download(file.id)
        const url = new URL(result.download_url)
        if (url.protocol !== 'https:' || url.username || url.password || !Number.isFinite(result.expires_in) || result.expires_in <= 0) throw new KnowledgeError('A safe download link could not be created. Try again.')
        if (!active.signal.aborted) setLink({ fileId: file.id, url: url.href, expiresAt: started + result.expires_in * 1000 })
      }
    } catch (e) { if (!active.signal.aborted) setError(knowledgeError(e)) }
    finally {
      // Upload/removal may have committed even if their response was lost. Never retry them automatically.
      if (action !== 'download' && !active.signal.aborted) {
        try { const data = await api.list(); if (!active.signal.aborted) { setFiles(data); setVerified(true) } }
        catch { if (!active.signal.aborted) { setVerified(false); setError(previous => `${previous ? `${previous} ` : ''}Could not refresh files. Refresh the list before another operation.`) } }
      }
      locked.current = false
      if (!active.signal.aborted) {
        setBusy('')
        if (removed) filesHeading.current?.focus()
      }
    }
  }

  return <section className={styles.page}>
    <header><h1>Knowledge files</h1><p>Teach it what you know. Add your business documents to this assistant’s draft.</p></header>
    <div className={styles.layout}><div className={styles.page}>
      <div className={styles.dropzone} onDragOver={event => event.preventDefault()} onDrop={event => { event.preventDefault(); choose(event.dataTransfer.files) }}>
        <span className={styles.uploadIcon}><img src={uploadIcon} alt="" /></span>
        <strong>Drop one file here, or browse files</strong><p>PDF or DOCX · Up to 5 files · 10 MB per file</p>
        <input ref={input} id="knowledge-upload" type="file" accept=".pdf,.docx,application/pdf,application/vnd.openxmlformats-officedocument.wordprocessingml.document" aria-label="Choose knowledge file" className={styles.fileInput} disabled={disabled || full} onChange={event => choose(event.target.files)} />
        <Button variant="secondary" disabled={disabled || full} onClick={() => input.current?.click()}><img src={plusIcon} alt="" />Browse files</Button>
        {selected && <><p className={styles.filename}>{selected.name}</p><Button disabled={disabled || full} busy={busy === 'upload'} onClick={() => void run('upload')}>Upload file</Button></>}
        {selectionError && <Alert kind="error">{selectionError}</Alert>}
        {full && <p>Five files attached. Remove a file before uploading another. Failed files also count.</p>}
      </div>
      {error && <Alert kind="error">{error}</Alert>}{notice && <Alert>{notice}</Alert>}
      {busy && <LoadingState label={busy === 'upload' ? 'Uploading and extracting text…' : busy === 'remove' ? 'Removing attachment…' : busy === 'download' ? 'Preparing private download…' : 'Refreshing files…'} />}
      <Card className={styles.card}><div className={styles.row}><h2 ref={filesHeading} tabIndex={-1}>Attached files</h2><Badge>{verified ? `${files.length} of 5 files` : 'List not confirmed'}</Badge><Button variant="secondary" disabled={loading || !!busy} onClick={() => void run('refresh')}>Refresh files</Button></div>
        {loading ? <LoadingState label="Loading knowledge files…" /> : verified && files.length === 0 ? <p>No knowledge files yet. Upload a PDF or DOCX to get started.</p> : null}
        {!verified && !loading && <p>File status is unavailable. Refresh before uploading, downloading or removing files.</p>}
        <ul className={styles.list}>{files.map(file => <li key={file.id} className={styles.file}>
          <div className={styles.row}><span className={styles.fileIcon}><img src={fileIcon} alt="" /></span><div className={styles.metadata}><h3>{file.original_filename}</h3><p>{file.file_format.toUpperCase()} · {(file.size_bytes / 1_000_000).toLocaleString(undefined, { maximumFractionDigits: 2 })} MB · <time dateTime={file.created_at}>{new Date(file.created_at).toLocaleString()}</time></p></div>
            <span className={`${styles.state} ${file.processing_state === 'extracted' ? styles.ready : file.processing_state === 'failed' ? styles.failed : styles.processing}`}><img src={file.processing_state === 'extracted' ? readyIcon : file.processing_state === 'failed' ? failedIcon : processingIcon} alt="" />{states[file.processing_state] ?? 'Status unavailable'}</span>
            <div className={styles.actions}><Button variant="secondary" disabled={disabled || file.processing_state !== 'extracted'} aria-label={`Download ${file.original_filename}`} onClick={() => void run('download', file)}><img src={downloadIcon} alt="" />Download</Button><Button variant="secondary" disabled={disabled} aria-label={`Remove ${file.original_filename}`} onClick={event => { removeTrigger.current = event.currentTarget; setConfirm(file.id); setLink(null) }}><img src={removeIcon} alt="" />Remove</Button></div>
          </div>
          {file.processing_state === 'failed' && <p className={styles.failure}>{failures[file.error_code ?? ''] ?? 'The file could not be processed.'} Remove this attachment, then upload a corrected file.</p>}
          {['reserved', 'processing'].includes(file.processing_state) && <p>Processing is not complete. Refresh to check its status. If it stays stuck, contact the workspace operator.</p>}
          {link?.fileId === file.id && <TemporaryDownload key={`${link.fileId}-${link.expiresAt}`} link={link} />}
          {confirm === file.id && <div className={styles.confirm} role="group" aria-label={`Confirm removal of ${file.original_filename}`}><p>Remove this file from the draft? Existing download links may work until they expire. This does not immediately erase the stored file.</p><div className={styles.actions}><Button variant="danger" busy={busy === 'remove'} disabled={disabled} onClick={() => void run('remove', file)}>Confirm removal</Button><Button variant="secondary" disabled={!!busy} onClick={() => { setConfirm(null); removeTrigger.current?.focus() }}>Cancel</Button></div></div>}
        </li>)}</ul>
        <p>Text extracted means the document was read successfully. AI retrieval and Playground are not available yet.</p>
      </Card>
    </div><aside className={styles.page}><Card className={styles.card}><h2>A good answer starts here</h2><img src={bookIcon} alt="" /><p>Start with the questions your customers ask most often.</p>{['Shipping times and delivery costs', 'Returns and refund policies', 'Product details and care tips'].map(text => <p key={text} className={styles.tip}><img src={checkIcon} alt="" />{text}</p>)}</Card><Alert><div className={styles.tip}><img src={infoIcon} alt="" /><div><strong>Your knowledge stays private</strong><p>Files are stored privately. Downloads require a temporary link. Scanned documents and OCR are not supported.</p></div></div></Alert></aside></div>
  </section>
}
