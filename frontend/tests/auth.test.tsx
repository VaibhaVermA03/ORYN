import { screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it } from 'vitest'
import { safeNext } from '@/auth/RequireAuth'
import { App } from '@/App'
import { GOOGLE_ERRORS, signupSchema } from '@/pages/AuthPages'
import { USER, json, mockApi, renderApp, signedInRoutes } from './helpers'

const anonymous = { 'POST /auth/refresh': () => json({ error: { code: 'unauthenticated', message: 'no' } }, 401) }

describe('route protection', () => {
  it('redirects anonymous users from /app to the login page', async () => {
    mockApi({ ...anonymous })
    renderApp(<App />, '/app/knowledge')
    expect(await screen.findByRole('heading', { name: 'Sign in' })).toBeInTheDocument()
  })

  it('keeps non-admins out of the platform admin route', async () => {
    mockApi(signedInRoutes({ 'GET /workspaces/w1/documents': () => json({ items: [], total: 0, page: 1, page_size: 25 }) }))
    renderApp(<App />, '/app/admin')
    expect(await screen.findByRole('heading', { name: 'You do not have access' })).toBeInTheDocument()
  })

  it('shows the not-found page for unknown routes', async () => {
    mockApi({ ...anonymous })
    renderApp(<App />, '/nope')
    expect(await screen.findByRole('heading', { name: 'Page not found' })).toBeInTheDocument()
  })

  it('safeNext only allows same-app relative paths', () => {
    expect(safeNext('/app/settings')).toBe('/app/settings')
    expect(safeNext('//evil.com')).toBe('/app')
    expect(safeNext('https://evil.com')).toBe('/app')
    expect(safeNext('/\\evil.com')).toBe('/app')
    expect(safeNext(null)).toBe('/app')
  })
})

describe('login form', () => {
  it('validates before calling the API', async () => {
    const { calls } = mockApi({ ...anonymous })
    renderApp(<App />, '/login')
    await userEvent.click(await screen.findByRole('button', { name: 'Sign in' }))
    expect(await screen.findByText('Enter your email')).toBeInTheDocument()
    expect(screen.getByText('Enter your password')).toBeInTheDocument()
    expect(calls.some((c) => c.path === '/auth/login')).toBe(false)
  })

  it('shows the server error and does not leak which field was wrong', async () => {
    mockApi({ ...anonymous, 'POST /auth/login': () => json({ error: { code: 'invalid_credentials', message: 'Incorrect email or password.' } }, 401) })
    renderApp(<App />, '/login')
    await userEvent.type(await screen.findByLabelText('Email'), 'a@example.com')
    await userEvent.type(screen.getByLabelText('Password'), 'whatever-pass1')
    await userEvent.click(screen.getByRole('button', { name: 'Sign in' }))
    expect(await screen.findByText('Incorrect email or password.')).toBeInTheDocument()
  })

  it('signs in, sends the CSRF header, and lands in the app', async () => {
    let signedIn = false
    const { calls } = mockApi({
      'POST /auth/refresh': () => (signedIn ? json({ access_token: 't', token_type: 'bearer', expires_in: 900, user: USER }) : json({ error: { code: 'unauthenticated', message: 'no' } }, 401)),
      'POST /auth/login': () => {
        signedIn = true
        return json({ access_token: 't', token_type: 'bearer', expires_in: 900, user: USER })
      },
      'GET /workspaces': () => json([]),
    })
    renderApp(<App />, '/login')
    await userEvent.type(await screen.findByLabelText('Email'), 'a@example.com')
    await userEvent.type(screen.getByLabelText('Password'), 'correct-horse1')
    await userEvent.click(screen.getByRole('button', { name: 'Sign in' }))
    await waitFor(() => expect(screen.getByRole('navigation', { name: 'Primary' })).toBeInTheDocument())
    const login = calls.find((c) => c.path === '/auth/login')!
    expect(login.headers.get('X-Requested-By')).toBe('oryn-web')
    expect(login.headers.get('Authorization')).toBeNull()
  })

  it('maps Google callback error codes to readable messages', async () => {
    mockApi({ ...anonymous })
    renderApp(<App />, '/login?error=account_exists')
    expect(await screen.findByText(GOOGLE_ERRORS.account_exists!)).toBeInTheDocument()
  })

  it('falls back to a generic message for unknown Google error codes', async () => {
    mockApi({ ...anonymous })
    renderApp(<App />, '/login?error=something_new')
    expect(await screen.findByText('Google sign-in failed. Please try again.')).toBeInTheDocument()
  })

  it('links the Google button to the backend OAuth start URL', async () => {
    mockApi({ ...anonymous })
    renderApp(<App />, '/login')
    const link = await screen.findByRole('link', { name: /continue with google/i })
    expect(link).toHaveAttribute('href', expect.stringMatching(/\/api\/v1\/auth\/google\/login$/))
  })
})

describe('signup validation', () => {
  it('mirrors the server password policy', () => {
    const ok = { display_name: 'A', email: 'a@example.com' }
    expect(signupSchema.safeParse({ ...ok, password: 'short1!' }).success).toBe(false)
    expect(signupSchema.safeParse({ ...ok, password: 'onlylettersonly' }).success).toBe(false)
    expect(signupSchema.safeParse({ ...ok, password: 'long-enough-1' }).success).toBe(true)
  })

  it('shows field errors in the form', async () => {
    mockApi({ ...anonymous })
    renderApp(<App />, '/signup')
    await userEvent.type(await screen.findByLabelText('Name'), 'Asha')
    await userEvent.type(screen.getByLabelText('Email'), 'not-an-email')
    await userEvent.type(screen.getByLabelText('Password'), 'short')
    await userEvent.click(screen.getByRole('button', { name: 'Create account' }))
    expect(await screen.findByText('Enter a valid email address')).toBeInTheDocument()
    expect(screen.getByText('At least 10 characters')).toBeInTheDocument()
  })
})

describe('auth page layout', () => {
  it('renders the desktop showcase panel on login and signup, hidden from small screens by CSS classes', async () => {
    mockApi({ ...anonymous })
    const { unmount } = renderApp(<App />, '/login')
    const panel = await screen.findByRole('complementary', { name: 'About ORYN' })
    expect(panel.className).toContain('hidden')
    expect(panel.className).toContain('lg:flex')
    expect(within(panel).getByRole('heading', { name: /Ask your documents/ })).toBeInTheDocument()
    // the sign-in form is still the single h1 / main landmark
    expect(screen.getAllByRole('heading', { level: 1 })).toHaveLength(1)
    expect(screen.getAllByRole('main')).toHaveLength(1)
    unmount()
    mockApi({ ...anonymous })
    renderApp(<App />, '/signup')
    expect(await screen.findByRole('complementary', { name: 'About ORYN' })).toBeInTheDocument()
  })

  it('does not present the illustration as real data', async () => {
    mockApi({ ...anonymous })
    renderApp(<App />, '/login')
    const panel = await screen.findByRole('complementary', { name: 'About ORYN' })
    expect(panel).toHaveTextContent('Example')
    expect(panel.textContent).not.toMatch(/\d+\s?%|\d+\s?(users|customers|companies)/i)
  })
})