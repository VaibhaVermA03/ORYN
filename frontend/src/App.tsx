import { Navigate, Route, Routes } from 'react-router-dom'
import { RedirectIfAuthed, RequireAdmin, RequireAuth } from '@/auth/RequireAuth'
import { AppShell } from '@/components/layout/AppShell'
import { AdminPage } from '@/pages/AdminPage'
import { AnalyticsPage } from '@/pages/AnalyticsPage'
import { AssistantPage } from '@/pages/AssistantPage'
import { LoginPage, SignupPage } from '@/pages/AuthPages'
import { KnowledgeBasePage } from '@/pages/KnowledgeBasePage'
import { SettingsPage } from '@/pages/SettingsPage'
import { ForbiddenPage, NotFoundPage } from '@/pages/StatusPages'
import { WorkspaceProvider } from '@/workspace/WorkspaceContext'

export function App() {
  return (
    <Routes>
      <Route element={<RedirectIfAuthed />}>
        <Route path="/login" element={<LoginPage />} />
        <Route path="/signup" element={<SignupPage />} />
      </Route>

      <Route element={<RequireAuth />}>
        <Route
          path="/app"
          element={
            <WorkspaceProvider>
              <AppShell />
            </WorkspaceProvider>
          }
        >
          <Route index element={<Navigate to="knowledge" replace />} />
          <Route path="knowledge" element={<KnowledgeBasePage />} />
          <Route path="assistant" element={<AssistantPage />} />
          <Route path="analytics" element={<AnalyticsPage />} />
          <Route path="settings" element={<SettingsPage />} />
          <Route element={<RequireAdmin />}>
            <Route path="admin" element={<AdminPage />} />
          </Route>
        </Route>
      </Route>

      <Route path="/" element={<Navigate to="/app" replace />} />
      <Route path="/forbidden" element={<ForbiddenPage />} />
      <Route path="*" element={<NotFoundPage />} />
    </Routes>
  )
}
