import { zodResolver } from '@hookform/resolvers/zod'
import { useState, type ReactNode } from 'react'
import { useForm } from 'react-hook-form'
import { Link, useSearchParams } from 'react-router-dom'
import { z } from 'zod'
import { AuthShowcase } from '@/components/auth/AuthShowcase'
import { Logo } from '@/components/Logo'
import { Button } from '@/components/ui/Button'
import { Input } from '@/components/ui/Field'
import { Alert } from '@/components/ui/feedback'
import { useAuth } from '@/auth/AuthContext'
import { API_PREFIX, errorMessage } from '@/lib/api'

/** Messages for the `?error=` codes the backend's Google callback redirects with. */
export const GOOGLE_ERRORS: Record<string, string> = {
  access_denied: 'Google sign-in was cancelled.',
  google_error: 'Google returned an error. Please try again.',
  google_not_configured: 'Google sign-in is not configured on this server.',
  invalid_state: 'That sign-in attempt expired. Please try again.',
  invalid_nonce: 'That sign-in attempt could not be verified. Please try again.',
  invalid_id_token: 'Your Google identity could not be verified.',
  missing_code: 'Google did not complete the sign-in. Please try again.',
  code_rejected: 'Google rejected the sign-in. Please try again.',
  provider_unreachable: 'Could not reach Google. Please try again in a moment.',
  missing_email: 'Google did not share an email address.',
  email_unverified: 'Your Google email address is not verified.',
  account_exists:
    'An account with this email already exists. Sign in with your password, then link Google from Settings.',
  identity_in_use: 'That Google account is already linked to another ORYN account.',
  account_disabled: 'This account is disabled.',
  link_failed: 'Linking Google failed. Please try again from Settings.',
  rate_limited: 'Too many attempts. Please wait a minute and try again.',
}

function Shell({ title, subtitle, children, footer }: { title: string; subtitle: string; children: ReactNode; footer: ReactNode }) {
  return (
    // Phones and tablets: the single centred card (unchanged). lg and up: two equal columns, form | showcase.
    <div className="min-h-dvh bg-app text-ink lg:grid lg:grid-cols-2">
      <main className="flex min-h-dvh items-center justify-center px-4 py-10">
        <div className="w-full max-w-sm">
          <Logo className="mb-8 justify-center" />
          <div className="rounded-2xl border border-line bg-surface p-6 shadow-card">
            <h1 className="text-xl font-semibold">{title}</h1>
            <p className="mt-1 text-sm text-muted">{subtitle}</p>
            <div className="mt-6 space-y-4">{children}</div>
          </div>
          <p className="mt-5 text-center text-sm text-muted">{footer}</p>
        </div>
      </main>
      <AuthShowcase />
    </div>
  )
}

function GoogleButton() {
  return (
    <a
      href={`${API_PREFIX}/auth/google/login`}
      className="inline-flex h-10 w-full items-center justify-center gap-2 rounded-lg border border-line bg-surface text-sm font-medium shadow-card hover:bg-surface-2 focus-visible:outline-2 focus-visible:outline-accent-fg"
    >
      <svg aria-hidden viewBox="0 0 24 24" className="h-4 w-4">
        <path fill="#4285F4" d="M23.5 12.3c0-.8-.1-1.6-.2-2.3H12v4.5h6.5a5.6 5.6 0 0 1-2.4 3.6v3h3.9c2.3-2.1 3.5-5.2 3.5-8.8z" />
        <path fill="#34A853" d="M12 24c3.2 0 6-1.1 7.9-2.9l-3.9-3a7.1 7.1 0 0 1-10.6-3.7H1.4v3.1A12 12 0 0 0 12 24z" />
        <path fill="#FBBC05" d="M5.4 14.4a7.2 7.2 0 0 1 0-4.8V6.5H1.4a12 12 0 0 0 0 11l4-3.1z" />
        <path fill="#EA4335" d="M12 4.8c1.8 0 3.4.6 4.6 1.8l3.4-3.4A12 12 0 0 0 1.4 6.5l4 3.1A7.2 7.2 0 0 1 12 4.8z" />
      </svg>
      Continue with Google
    </a>
  )
}

function Divider() {
  return (
    <div className="flex items-center gap-3 text-xs text-muted" role="separator">
      <span className="h-px flex-1 bg-line" />
      or
      <span className="h-px flex-1 bg-line" />
    </div>
  )
}

const loginSchema = z.object({
  email: z.string().trim().min(1, 'Enter your email').pipe(z.email('Enter a valid email address')),
  password: z.string().min(1, 'Enter your password'),
})
type LoginValues = z.infer<typeof loginSchema>

export function LoginPage() {
  const { login } = useAuth()
  const [params] = useSearchParams()
  const [formError, setFormError] = useState<string | null>(null)
  const code = params.get('error')
  const googleError = code ? (GOOGLE_ERRORS[code] ?? 'Google sign-in failed. Please try again.') : null
  const {
    register,
    handleSubmit,
    formState: { errors, isSubmitting },
  } = useForm<LoginValues>({ resolver: zodResolver(loginSchema) })

  const onSubmit = handleSubmit(async (v) => {
    setFormError(null)
    try {
      await login(v.email, v.password)
    } catch (e) {
      setFormError(errorMessage(e, 'Could not sign in. Please try again.'))
    }
  })

  return (
    <Shell
      title="Sign in"
      subtitle="Welcome back to ORYN."
      footer={
        <>
          New to ORYN?{' '}
          <Link to="/signup" className="font-medium text-accent-fg hover:underline">
            Create an account
          </Link>
        </>
      }
    >
      {googleError && <Alert tone="danger">{googleError}</Alert>}
      {formError && <Alert tone="danger">{formError}</Alert>}
      <form onSubmit={onSubmit} noValidate className="space-y-4">
        <Input label="Email" type="email" autoComplete="email" error={errors.email?.message} {...register('email')} />
        <Input label="Password" type="password" autoComplete="current-password" error={errors.password?.message} {...register('password')} />
        <Button type="submit" variant="primary" className="w-full" loading={isSubmitting}>
          Sign in
        </Button>
      </form>
      <Divider />
      <GoogleButton />
    </Shell>
  )
}

// Mirrors backend validate_password_strength for early feedback; the server remains authoritative.
export const signupSchema = z.object({
  display_name: z.string().trim().min(1, 'Enter your name').max(120, 'At most 120 characters'),
  email: z.string().trim().min(1, 'Enter your email').pipe(z.email('Enter a valid email address')),
  password: z
    .string()
    .min(10, 'At least 10 characters')
    .max(128, 'At most 128 characters')
    .refine((p) => /[A-Za-z]/.test(p) && /[\d\W_]/.test(p), 'Include letters and at least one number or symbol'),
})
type SignupValues = z.infer<typeof signupSchema>

export function SignupPage() {
  const { signup } = useAuth()
  const [formError, setFormError] = useState<string | null>(null)
  const {
    register,
    handleSubmit,
    formState: { errors, isSubmitting },
  } = useForm<SignupValues>({ resolver: zodResolver(signupSchema) })

  const onSubmit = handleSubmit(async (v) => {
    setFormError(null)
    try {
      await signup(v)
    } catch (e) {
      setFormError(errorMessage(e, 'Could not create your account. Please try again.'))
    }
  })

  return (
    <Shell
      title="Create your account"
      subtitle="Start a private knowledge workspace."
      footer={
        <>
          Already have an account?{' '}
          <Link to="/login" className="font-medium text-accent-fg hover:underline">
            Sign in
          </Link>
        </>
      }
    >
      {formError && <Alert tone="danger">{formError}</Alert>}
      <form onSubmit={onSubmit} noValidate className="space-y-4">
        <Input label="Name" autoComplete="name" error={errors.display_name?.message} {...register('display_name')} />
        <Input label="Email" type="email" autoComplete="email" error={errors.email?.message} {...register('email')} />
        <Input
          label="Password"
          type="password"
          autoComplete="new-password"
          hint="At least 10 characters, with a number or symbol."
          error={errors.password?.message}
          {...register('password')}
        />
        <Button type="submit" variant="primary" className="w-full" loading={isSubmitting}>
          Create account
        </Button>
      </form>
      <Divider />
      <GoogleButton />
    </Shell>
  )
}