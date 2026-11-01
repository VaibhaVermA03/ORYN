import { AlertTriangle, CheckCircle2, Info, Loader2 } from 'lucide-react'
import { useEffect, useState, type ReactNode } from 'react'
import { Logo } from '@/components/Logo'
import { cn } from '@/lib/utils'

export function Spinner({ className, label }: { className?: string; label?: string }) {
  return (
    <span role={label ? 'status' : undefined} aria-label={label} className="inline-flex">
      <Loader2 aria-hidden className={cn('h-5 w-5 animate-[oryn-spin_0.8s_linear_infinite]', className)} />
    </span>
  )
}

export function Skeleton({ className }: { className?: string }) {
  return <div aria-hidden className={cn('animate-[oryn-pulse_1.6s_ease-in-out_infinite] rounded-md bg-surface-2', className)} />
}

type Tone = 'neutral' | 'accent' | 'success' | 'warn' | 'danger'
const tones: Record<Tone, string> = {
  neutral: 'bg-surface-2 text-muted',
  accent: 'bg-accent-soft text-accent-fg',
  success: 'bg-success-soft text-success',
  warn: 'bg-warn-soft text-warn',
  danger: 'bg-danger-soft text-danger',
}

export function Badge({ tone = 'neutral', children, className }: { tone?: Tone; children: ReactNode; className?: string }) {
  return (
    <span className={cn('inline-flex items-center gap-1 rounded-full px-2 py-0.5 text-xs font-medium', tones[tone], className)}>
      {children}
    </span>
  )
}

export function Card({ className, children }: { className?: string; children: ReactNode }) {
  return <section className={cn('rounded-xl border border-line bg-surface shadow-card', className)}>{children}</section>
}

export function EmptyState({ icon, title, description, action }: { icon?: ReactNode; title: string; description?: string; action?: ReactNode }) {
  return (
    <div className="flex flex-col items-center justify-center gap-2 px-6 py-12 text-center">
      {icon && <div aria-hidden className="mb-1 flex h-11 w-11 items-center justify-center rounded-full bg-surface-2 text-muted">{icon}</div>}
      <h3 className="text-[15px] font-semibold text-ink">{title}</h3>
      {description && <p className="max-w-sm text-sm text-muted">{description}</p>}
      {action && <div className="mt-2">{action}</div>}
    </div>
  )
}

export function ErrorState({ title = 'Something went wrong', message, onRetry }: { title?: string; message?: string; onRetry?: () => void }) {
  return (
    <div role="alert" className="flex flex-col items-center gap-2 px-6 py-10 text-center">
      <div aria-hidden className="flex h-11 w-11 items-center justify-center rounded-full bg-danger-soft text-danger">
        <AlertTriangle className="h-5 w-5" />
      </div>
      <h3 className="text-[15px] font-semibold">{title}</h3>
      {message && <p className="max-w-md text-sm text-muted">{message}</p>}
      {onRetry && (
        <button onClick={onRetry} className="mt-2 rounded-lg border border-line bg-surface px-3 py-1.5 text-sm font-medium hover:bg-surface-2">
          Try again
        </button>
      )}
    </div>
  )
}

const alertStyles = {
  info: { cls: 'bg-accent-soft text-ink border-accent-fg/30', Icon: Info },
  success: { cls: 'bg-success-soft text-ink border-success/30', Icon: CheckCircle2 },
  warn: { cls: 'bg-warn-soft text-ink border-warn/30', Icon: AlertTriangle },
  danger: { cls: 'bg-danger-soft text-ink border-danger/30', Icon: AlertTriangle },
} as const

export function Alert({ tone = 'info', children, className }: { tone?: keyof typeof alertStyles; children: ReactNode; className?: string }) {
  const { cls, Icon } = alertStyles[tone]
  return (
    <div role={tone === 'danger' ? 'alert' : 'status'} className={cn('flex items-start gap-2.5 rounded-lg border px-3 py-2.5 text-sm', cls, className)}>
      <Icon aria-hidden className="mt-0.5 h-4 w-4 shrink-0" />
      <div className="min-w-0">{children}</div>
    </div>
  )
}

export function PageHeader({ title, description, actions }: { title: string; description?: string; actions?: ReactNode }) {
  return (
    <div className="mb-6 flex flex-wrap items-start justify-between gap-3">
      <div className="min-w-0">
        <h1 className="text-xl font-semibold tracking-tight">{title}</h1>
        {description && <p className="mt-1 max-w-2xl text-sm text-muted">{description}</p>}
      </div>
      {actions && <div className="flex items-center gap-2">{actions}</div>}
    </div>
  )
}

export function FullPageSpinner({ label = 'Loading' }: { label?: string }) {
  return (
    <div className="flex h-full min-h-screen items-center justify-center text-muted">
      <Spinner className="h-6 w-6" label={label} />
    </div>
  )
}

/** How long the app waits before explaining a slow start. A warm server answers well before this. */
export const SLOW_START_NOTICE_MS = 2500

/**
 * Full-page screen shown while the app checks the session. The backend runs on Render's free plan, which
 * puts the server to sleep when idle, so the first request after a quiet period can take about a minute.
 * If the wait goes past SLOW_START_NOTICE_MS, a short explanation fades in so people know it is not broken.
 */
export function StartupScreen({ label = 'Checking your session' }: { label?: string }) {
  const [slow, setSlow] = useState(false)
  useEffect(() => {
    const t = window.setTimeout(() => setSlow(true), SLOW_START_NOTICE_MS)
    return () => window.clearTimeout(t)
  }, [])

  return (
    <div className="flex min-h-dvh flex-col items-center justify-center gap-6 bg-app px-6 text-center text-ink">
      <Logo />
      <Spinner className="h-6 w-6 text-accent-fg" label={label} />
      <div aria-live="polite" className="min-h-28 max-w-sm">
        {slow && (
          <div className="animate-[oryn-rise_0.4s_ease-out] rounded-xl border border-line bg-surface px-4 py-3 text-left shadow-card">
            <p className="text-sm font-semibold">Waking up the server&hellip;</p>
            <p className="mt-1 text-[13px] leading-relaxed text-muted">
              This project is deployed on Render&rsquo;s free plan, which puts the server to sleep when it is idle. The first load can
              take up to a minute. After that, everything is fast. Thanks for your patience!
            </p>
          </div>
        )}
      </div>
    </div>
  )
}