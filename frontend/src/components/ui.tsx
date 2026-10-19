import { useId, type ButtonHTMLAttributes, type InputHTMLAttributes, type ReactNode } from 'react'
import { Link, type LinkProps } from 'react-router'
import styles from './ui.module.css'

type Variant = 'primary' | 'secondary' | 'danger'
export function Button({ children, variant = 'primary', busy = false, disabled, type = 'button', ...props }:
  ButtonHTMLAttributes<HTMLButtonElement> & { variant?: Variant; busy?: boolean }) {
  return <button {...props} type={type} className={`${styles.button} ${styles[variant]} ${props.className ?? ''}`}
    disabled={disabled || busy} aria-busy={busy || undefined}>
    {busy && <span className={styles.spinner} aria-hidden="true" />}{children}
  </button>
}
export function ButtonLink({ variant = 'primary', ...props }: LinkProps & { variant?: Variant }) {
  return <Link {...props} className={`${styles.button} ${styles[variant]} ${props.className ?? ''}`} />
}
export function Badge({ children }: { children: ReactNode }) {
  return <span className={styles.badge}>{children}</span>
}
export function Card({ children, className = '' }: { children: ReactNode; className?: string }) {
  return <div className={`${styles.card} ${className}`}>{children}</div>
}
export function Alert({ children, kind = 'info' }: { children: ReactNode; kind?: 'info' | 'error' }) {
  return <div className={`${styles.alert} ${kind === 'error' ? styles.error : ''}`} role={kind === 'error' ? 'alert' : 'status'}>{children}</div>
}
export function TextField({ label, error, hint, id, ...props }:
  InputHTMLAttributes<HTMLInputElement> & { label: string; error?: string; hint?: string }) {
  const generatedId = useId()
  const inputId = id ?? generatedId
  const description = error ?? hint
  return <div className={styles.field}>
    <label htmlFor={inputId}>{label}</label>
    <input {...props} id={inputId} aria-invalid={!!error} aria-describedby={description ? `${inputId}-help` : undefined} />
    {description && <p id={`${inputId}-help`} className={error ? styles.fieldError : ''}>{description}</p>}
  </div>
}
export function EmptyState({ icon, title, children, action }: { icon: ReactNode; title: string; children: ReactNode; action?: ReactNode }) {
  return <Card className={styles.empty}><div className={styles.emptyIcon}>{icon}</div><h2>{title}</h2>
    <div className={styles.emptyCopy}>{children}</div>{action}</Card>
}
export function LoadingState({ label = 'Loading…' }: { label?: string }) {
  return <div role="status" className={styles.loading}><span className={styles.spinner} aria-hidden="true" />{label}</div>
}
