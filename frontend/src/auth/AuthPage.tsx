import { useEffect, useRef, useState, type FormEvent } from 'react'
import { Link, Navigate } from 'react-router'
import { Alert, Button, Card, LoadingState, TextField } from '../components/ui'
import { Icon } from '../components/Icon'
import { AuthUnavailable } from './AuthProvider'
import { useAuth } from './context'
import sparkles from '../assets/icons/auth-sparkles.svg'
import flower from '../assets/icons/auth-flower.svg'
import eye from '../assets/icons/auth-eye.svg'
import lock from '../assets/icons/auth-lock.svg'
import styles from './auth.module.css'

export function AuthPage({ mode }: { mode: 'login' | 'register' }) {
  const auth = useAuth()
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [visible, setVisible] = useState(false)
  const [validation, setValidation] = useState<{ email?: string; password?: string }>({})
  const [confirmation, setConfirmation] = useState(false)
  const message = useRef<HTMLDivElement>(null)
  const register = mode === 'register'
  useEffect(() => { document.title = `${register ? 'Create account' : 'Log in'} · AI Assistant Builder` }, [register])
  useEffect(() => { if (auth.error || confirmation || validation.email || validation.password) message.current?.focus() }, [auth.error, confirmation, validation])
  async function submit(event: FormEvent) {
    event.preventDefault()
    if (auth.busy) return
    const errors = {
      email: /^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(email.trim()) ? undefined : 'Enter a valid email address.',
      password: password.length ? undefined : 'Enter your password.',
    }
    setValidation(errors)
    if (errors.email || errors.password) return
    const result = await auth.authenticate(mode, email.trim(), password)
    setPassword('')
    setVisible(false)
    if (result.ok) setConfirmation(result.confirmation)
  }
  if (auth.session) return <Navigate to="/assistants" replace />
  return <div className={styles.layout}>
    <aside className={styles.welcome}>
      <Link to="/" className={styles.brand}><span><Icon name="brand" /></span>AI Assistant Builder</Link>
      <div className={styles.promise}>
        <div className={styles.eyebrow}><img src={sparkles} alt="" />A LITTLE AI. A LOT MORE HUMAN.</div>
        <h2>Great support starts with your knowledge.</h2>
        <p>Turn what you know into an assistant your customers will love. No code. No complicated setup.</p>
        <Card className={styles.sample}>
          <div className={styles.identity}><span><img src={flower} alt="" /></span><div><strong>Bloom Support</strong><p>Illustrative example · not a live chat</p></div></div>
          <p className={styles.question}>Can I return something if it’s not quite right?</p>
          <p className={styles.answer}>Of course! You have 30 days to return unused items in their original packaging. I can help you get started. 🌷</p>
          <small>Thoughtful answers. Powered by your business.</small>
        </Card>
      </div>
      <small>Built for businesses that care about their customers.</small>
    </aside>
    <main className={styles.access}>
      <div className={styles.accountPath}>{register ? 'Already have an account?' : 'New here?'} <Link to={register ? '/login' : '/register'}>{register ? 'Log in' : 'Create an account'}</Link></div>
      <div className={styles.formArea}>
        <div><h1>{register ? 'Create your workspace' : 'Welcome back'}</h1><p>{register ? 'Better customer support starts here.' : 'Log in to your AI workspace.'}</p></div>
        {auth.status === 'loading' ? <LoadingState label="Restoring your session…" /> : auth.status === 'unconfigured' ? <AuthUnavailable /> : <>
          <div ref={message} tabIndex={-1} className={styles.messages}>
            {auth.error && <Alert kind="error">{auth.error}</Alert>}
            {(validation.email || validation.password) && <Alert kind="error">Check the highlighted fields.</Alert>}
            {confirmation && <Alert>If confirmation is required, check your email for the next step, then return here to log in. No signed-in session was created.</Alert>}
          </div>
          {!confirmation && <form onSubmit={submit} noValidate className={styles.form}>
            <TextField label="Work email" name="email" type="email" autoComplete="email" required value={email} disabled={auth.busy} onChange={e => setEmail(e.target.value)} error={validation.email} />
            <div className={styles.password}>
              <TextField label="Password" name="password" type={visible ? 'text' : 'password'} autoComplete={register ? 'new-password' : 'current-password'} required value={password} disabled={auth.busy} onChange={e => setPassword(e.target.value)} error={validation.password} hint={register ? 'Use a strong, unique password. Your account security policy is checked on submission.' : undefined} />
              <button type="button" disabled={auth.busy} aria-label={visible ? 'Hide password' : 'Show password'} aria-pressed={visible} className={styles.eye} onClick={() => setVisible(!visible)}><img src={eye} alt="" /></button>
            </div>
            <Button type="submit" busy={auth.busy}>{auth.busy ? 'Please wait…' : register ? 'Create account' : 'Log in'}</Button>
          </form>}
          {confirmation && <Link to="/login">Return to log in</Link>}
        </>}
        <p className={styles.security}><img src={lock} alt="" />Account access is managed by Supabase Auth.</p>
      </div>
      <small className={styles.footer}>© 2026 AI Assistant Builder</small>
    </main>
  </div>
}
