import { AssistantList, AssistantEditor } from '../assistants/Assistants'
import { KnowledgeFiles } from '../knowledge/KnowledgeFiles'
import { Navigate, Route, Routes } from 'react-router'
import { Shell } from './Shell'
import { Overview, AssistantLayout } from '../pages/Pages'
import { RequireOwner } from '../auth/AuthProvider'
import { AuthPage } from '../auth/AuthPage'
import { Link } from 'react-router'

export function AppRoutes() {
  return <Routes>
    <Route path="/" element={<main style={{ padding: 32 }}><h1>AI Assistant Builder</h1><p>Public landing page coming later.</p><Link to="/login">Log in</Link></main>} />
    <Route path="login" element={<AuthPage key="login" mode="login" />} />
    <Route path="register" element={<AuthPage key="register" mode="register" />} />
    {import.meta.env.DEV && <Route path="dev/dashboard" element={<Shell preview />}><Route index element={<Overview />} /></Route>}
    <Route element={<RequireOwner />}><Route element={<Shell />}>
    <Route path="assistants" element={<AssistantList />} />
    <Route path="assistants/new" element={<AssistantEditor key="create" />} />
    <Route path="assistants/:id" element={<AssistantLayout />}>
      <Route index element={<Navigate to="configuration" replace />} />
      <Route path="configuration" element={<AssistantEditor key="edit" />} />
      <Route path="knowledge" element={<KnowledgeFiles />} />
    </Route>
    </Route></Route>
    <Route path="*" element={<main style={{ padding: 32 }}><h1>Page not found</h1><Link to="/assistants">Go to your dashboard</Link></main>} />
  </Routes>
}
