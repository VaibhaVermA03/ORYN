import { Navigate, Outlet, useLocation } from 'react-router-dom'
import { FullPageSpinner } from '@/components/ui/feedback'
import { useAuth } from './AuthContext'

/** Route guard. This improves UX only; every API endpoint enforces authorization on the server. */
export function RequireAuth() {
  const { status } = useAuth()
  const location = useLocation()
  if (status === 'loading') return <FullPageSpinner label="Checking your session" />
  if (status === 'anonymous') {
    const next = encodeURIComponent(location.pathname + location.search)
    return <Navigate to={`/login?next=${next}`} replace />
  }
  return <Outlet />
}

export function RequireAdmin() {
  const { user } = useAuth()
  if (user?.role !== 'admin') return <Navigate to="/forbidden" replace />
  return <Outlet />
}

/** Keeps signed-in users away from /login and /signup. */
export function RedirectIfAuthed() {
  const { status } = useAuth()
  const params = new URLSearchParams(useLocation().search)
  if (status === 'loading') return <FullPageSpinner />
  if (status === 'authenticated') return <Navigate to={safeNext(params.get('next'))} replace />
  return <Outlet />
}

/** Only same-app relative paths are honoured, which prevents open redirects via ?next=. */
export function safeNext(next: string | null): string {
  if (!next || !next.startsWith('/') || next.startsWith('//') || next.includes('\\')) return '/app'
  return next
}
