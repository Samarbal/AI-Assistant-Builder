import { Link, NavLink, Outlet } from 'react-router'
import { Icon } from '../components/Icon'
import { Alert, Badge, Button, ButtonLink, Card, EmptyState } from '../components/ui'
import styles from './pages.module.css'

export function Overview({ assistants = false }: { assistants?: boolean }) {
  return <div className={styles.page}>
    <div className={styles.heading}><div><h1>{assistants ? 'Your assistants' : 'Dashboard'}</h1><p>Build, manage, and grow your AI assistants.</p></div>
      <ButtonLink to="/assistants/new"><Icon name="plus" />Create assistant</ButtonLink></div>
    <Alert>{assistants ? 'Signed in. Assistant data integration is planned for UI-04; no assistant data is loaded yet.' : 'Development preview — no account or assistant data is loaded here.'}</Alert>
    <EmptyState icon={<Icon name="emptyBot" />} title="Your first assistant is just a few steps away"
      action={<ButtonLink to="/assistants/new"><Icon name="plus" />Create assistant</ButtonLink>}>
      <p>Give your assistant a role, add your business knowledge, and make it your own.</p>
    </EmptyState>
    <section className={styles.guide} aria-labelledby="guide-title"><h2 id="guide-title">A little setup. A lot of possibility.</h2>
      <div className={styles.guideGrid}>
        <Card className={styles.guideCard}><Icon name="sliders" /><h3>Make it yours</h3><p>Choose a name, a role, and a tone that feels like your business.</p><span>Configure your assistant</span></Card>
        <Card className={styles.guideCard}><Icon name="files" /><h3>Teach it your business</h3><p>Add your PDF and DOCX files to bring your business knowledge together.</p><span>Add knowledge files</span></Card>
        <Card className={styles.guideCard}><Icon name="sparkles" /><h3>Test, then go live <Badge>Planned</Badge></h3><p>Playground and publishing will arrive in later phases.</p><Button variant="secondary" disabled>Publish & embed · Planned</Button></Card>
      </div>
    </section>
  </div>
}

export function Placeholder({ title, description, milestone, accountLink }: { title: string; description: string; milestone: string; accountLink?: 'login' | 'register' }) {
  return <div className={styles.page}><div className={styles.heading}><div><h1>{title}</h1><p>{description}</p></div><Badge>Preview</Badge></div>
    <EmptyState icon={<Icon name="emptyBot" />} title="The space is ready. The workflow comes next."
      action={<ButtonLink to="/assistants" variant="secondary">Back to dashboard</ButtonLink>}><p>{milestone}</p></EmptyState>
    {accountLink && <Link to={`/${accountLink}`}>{accountLink === 'login' ? 'View sign-in screen' : 'View registration screen'}</Link>}
  </div>
}

export function AssistantLayout() {
  return <div className={styles.page}><nav className={styles.tabs} aria-label="Assistant sections">
    <NavLink to="configuration" className={({ isActive }) => isActive ? styles.activeTab : ''}>Configuration</NavLink>
    <NavLink to="knowledge" className={({ isActive }) => isActive ? styles.activeTab : ''}>Knowledge</NavLink>
    <NavLink to="playground" className={({ isActive }) => isActive ? styles.activeTab : ''}>Playground</NavLink>
    <button disabled>Publish <Badge>Planned</Badge></button>
  </nav><Outlet /></div>
}
