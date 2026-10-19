import { useEffect, useRef } from 'react'
import { Link, NavLink, Outlet, useLocation } from 'react-router'
import { Icon, type IconName } from '../components/Icon'
import { Badge, Button } from '../components/ui'
import styles from './shell.module.css'
import { useAuth } from '../auth/context'

function Navigation({ mobile = false, onNavigate }: { mobile?: boolean; onNavigate?: () => void }) {
  const links: { to: string; label: string; icon: IconName }[] = [
    { to: '/assistants', label: mobile ? 'Home' : 'Dashboard', icon: mobile ? 'homeMobile' : 'dashboard' },
    { to: '/assistants/new', label: 'New assistant', icon: mobile ? 'botMobile' : 'bot' },
  ]
  return <nav aria-label={mobile ? 'Mobile primary' : 'Primary'} className={mobile ? styles.bottomNav : styles.nav}>
    {links.map(link => <NavLink key={link.to} to={link.to} end onClick={onNavigate}
      className={({ isActive }) => `${styles.navItem} ${isActive ? styles.active : ''}`}>
      <Icon name={link.icon} /><span>{link.label}</span>
    </NavLink>)}
    <button className={styles.navItem} disabled><Icon name={mobile ? 'sparklesMobile' : 'sparkles'} /><span>Playground</span><Badge>Planned</Badge></button>
    <button className={styles.navItem} disabled><Icon name={mobile ? 'messagesMobile' : 'messages'} /><span>{mobile ? 'Inbox' : 'Conversations'}</span><Badge>Planned</Badge></button>
  </nav>
}

function Brand() {
  return <Link to="/assistants" className={styles.brand}><span className={styles.brandIcon}><Icon name="brand" /></span><span>AI Assistant Builder</span></Link>
}

export function Shell({ preview = false }: { preview?: boolean }) {
  const auth = useAuth()
  const location = useLocation()
  const dialog = useRef<HTMLDialogElement>(null)
  const menuButton = useRef<HTMLButtonElement>(null)
  const main = useRef<HTMLElement>(null)
  const initialPath = useRef(location.pathname)
  function closeMenu() { dialog.current?.close(); menuButton.current?.focus() }

  useEffect(() => {
    if (initialPath.current !== location.pathname) {
      main.current?.focus()
      initialPath.current = location.pathname
    }
    const pageTitle = location.pathname === '/' ? 'Dashboard' : location.pathname.startsWith('/assistants') ? 'Assistants' : 'Account'
    document.title = `${pageTitle} · AI Assistant Builder`
    window.scrollTo(0, 0)
  }, [location.pathname])

  useEffect(() => {
    const desktop = window.matchMedia('(min-width: 768px)')
    const dismiss = () => { if (desktop.matches && dialog.current?.open) { dialog.current.close(); main.current?.focus() } }
    desktop.addEventListener('change', dismiss)
    return () => desktop.removeEventListener('change', dismiss)
  }, [])

  return <div className={styles.layout}>
    <a className="skip-link" href="#main-content">Skip to content</a>
    <aside className={styles.sidebar}>
      <Brand />
      <div className={styles.workspace}><span className={styles.workspaceIcon}>AB</span><div><strong>Your workspace</strong><p>Assistant Builder</p></div></div>
      <Navigation />
      <div className={styles.sidebarFooter}><Badge>{preview ? 'UI preview' : 'Owner workspace'}</Badge><p>Build your assistant.<br />Make it your own.</p>{preview ? <Link to="/login">Log in</Link> : <Button variant="secondary" busy={auth.busy} onClick={() => void auth.logout()}>Log out</Button>}</div>
    </aside>
    <div className={styles.body}>
      <header className={styles.topbar}>
        <button ref={menuButton} className={styles.menuButton} aria-label="Open navigation" aria-haspopup="dialog" onClick={() => dialog.current?.showModal()}><Icon name="menu" /></button>
        <div className={styles.breadcrumb}><span>Workspace</span><span aria-hidden="true">/</span><strong>{location.pathname === '/' ? 'Dashboard' : location.pathname.startsWith('/assistants') ? 'Assistants' : 'Account'}</strong></div>
        {preview ? <Badge>UI preview</Badge> : <Button variant="secondary" busy={auth.busy} onClick={() => void auth.logout()}>Log out</Button>}
      </header>
      <main ref={main} id="main-content" tabIndex={-1} className={styles.content}><Outlet /></main>
    </div>
    <Navigation mobile />
    <dialog ref={dialog} className={styles.drawer} aria-labelledby="navigation-title" onKeyDown={event => {
      if (event.key !== 'Tab') return
      const controls = event.currentTarget.querySelectorAll<HTMLElement>('a[href], button:not(:disabled)')
      const first = controls[0]
      const last = controls[controls.length - 1]
      if (event.shiftKey && document.activeElement === first) { event.preventDefault(); last?.focus() }
      else if (!event.shiftKey && document.activeElement === last) { event.preventDefault(); first?.focus() }
    }} onClick={event => { if (event.target === event.currentTarget) closeMenu() }}>
      <div className={styles.drawerContent}><div className={styles.drawerHeader}><h2 id="navigation-title">Your workspace</h2><Button variant="secondary" onClick={closeMenu}>Close</Button></div>
        <Navigation onNavigate={closeMenu} />{preview ? <><Link to="/login" onClick={closeMenu}>Log in</Link><p>Development preview. No account data is loaded.</p></> : <Button variant="secondary" busy={auth.busy} onClick={() => { closeMenu(); void auth.logout() }}>Log out</Button>}
      </div>
    </dialog>
  </div>
}
