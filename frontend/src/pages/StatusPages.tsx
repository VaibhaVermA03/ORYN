import { Component, type ErrorInfo, type ReactNode } from 'react'
import { Link } from 'react-router-dom'
import { Logo } from '@/components/Logo'
import { Button } from '@/components/ui/Button'

function Screen({ code, title, message, children }: { code: string; title: string; message: string; children?: ReactNode }) {
  return (
    <main className="flex min-h-dvh flex-col items-center justify-center gap-3 bg-app px-6 text-center text-ink">
      <Logo className="mb-6" />
      <p className="text-sm font-medium text-accent-fg">{code}</p>
      <h1 className="text-2xl font-semibold">{title}</h1>
      <p className="max-w-md text-sm text-muted">{message}</p>
      <div className="mt-4 flex gap-2">{children}</div>
    </main>
  )
}

const home = (
  <Link
    to="/app"
    className="inline-flex h-10 items-center rounded-lg bg-accent px-4 text-sm font-medium text-on-accent hover:bg-accent-hover focus-visible:outline-2 focus-visible:outline-accent-fg"
  >
    Go to ORYN
  </Link>
)

export function NotFoundPage() {
  return <Screen code="404" title="Page not found" message="The page you are looking for does not exist or has moved.">{home}</Screen>
}

export function ForbiddenPage() {
  return <Screen code="403" title="You do not have access" message="Your account does not have permission to view this page.">{home}</Screen>
}

export function ServiceErrorPage({ onRetry }: { onRetry?: () => void }) {
  return (
    <Screen code="Error" title="Something went wrong" message="An unexpected error occurred. Your data is safe. Try again, or reload the page.">
      <Button variant="primary" onClick={onRetry ?? (() => window.location.reload())}>
        Try again
      </Button>
    </Screen>
  )
}

export class ErrorBoundary extends Component<{ children: ReactNode }, { failed: boolean }> {
  override state = { failed: false }
  static getDerivedStateFromError() {
    return { failed: true }
  }
  override componentDidCatch(error: Error, info: ErrorInfo) {
    console.error('Unhandled UI error', error, info.componentStack)
  }
  override render() {
    return this.state.failed ? <ServiceErrorPage onRetry={() => window.location.reload()} /> : this.props.children
  }
}