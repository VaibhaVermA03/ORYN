import { screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it } from 'vitest'
import { App } from '@/App'
import { json, mockApi, renderApp, signedInRoutes } from './helpers'

describe('App shell', () => {
  it('shows an actionable error when workspaces fail to load', async () => {
    mockApi(signedInRoutes({ 'GET /workspaces': () => json({ error: { code: 'x', message: 'Down' } }, 500) }))
    renderApp(<App />, '/app/knowledge')
    expect(await screen.findByText('Could not load your workspaces')).toBeInTheDocument()
  })

  it('limits analytics to workspace admins', async () => {
    mockApi(signedInRoutes({ 'GET /workspaces': () => json([{ id: 'w1', name: 'Acme', description: null, role: 'member', created_at: 'x' }]) }))
    renderApp(<App />, '/app/analytics')
    expect(await screen.findByText('Analytics is limited to workspace admins')).toBeInTheDocument()
  })

  it('shows measured analytics and an honest empty evaluation state', async () => {
    mockApi(signedInRoutes({
      'GET /workspaces/w1/analytics': () => json({
        window_days: 30,
        documents: { total: 2, by_status: { ready: 2 }, indexed_chunks: 14, recent_failures: [] },
        usage: { queries_30d: 5, queries_7d: 2, active_users_30d: 1, conversations_total: 3, daily_queries: [{ date: '2026-01-01', queries: 5 }] },
        latency_ms: { samples: 0, avg_total: null, p50_total: null, p95_total: null, avg_retrieval: null, avg_rerank: null, avg_generation: null },
        reliability: { ok: 5, errors: 0, cancelled: 0, provider_errors: 0, provider_error_rate: 0, by_provider: {} },
        feedback: { up: 0, down: 0, with_comment: 0, satisfaction: null },
        evaluation: { runs: 0, latest: null },
      }),
      'GET /workspaces/w1/evaluations': () => json([]),
    }))
    renderApp(<App />, '/app/analytics')
    expect(await screen.findByText('Questions (30 days)')).toBeInTheDocument()
    expect(screen.getByText('No data')).toBeInTheDocument() // satisfaction with zero feedback is not shown as 0%
    expect(screen.getByText('No completed answers yet.')).toBeInTheDocument()
    expect(screen.getByText(/No evaluation runs yet/)).toBeInTheDocument()
  })

  it('asks before signing out; Cancel keeps the session', async () => {
    const { calls } = mockApi(signedInRoutes({
      'GET /workspaces/w1/documents': () => json({ items: [], total: 0, page: 1, page_size: 25 }),
      'POST /auth/logout': () => json(null, 204),
    }))
    renderApp(<App />, '/app/knowledge')
    await userEvent.click(await screen.findByRole('button', { name: /sign out/i }))
    const dialog = await screen.findByRole('alertdialog', { name: 'Sign out of ORYN?' })
    expect(dialog).toHaveTextContent('Do you want to sign out?')
    expect(calls.some((c) => c.path === '/auth/logout')).toBe(false) // nothing happens until confirmed
    await userEvent.click(within(dialog).getByRole('button', { name: 'Cancel' }))
    await waitFor(() => expect(screen.queryByRole('alertdialog')).not.toBeInTheDocument())
    expect(calls.some((c) => c.path === '/auth/logout')).toBe(false)
    expect(screen.getByRole('navigation', { name: 'Primary' })).toBeInTheDocument()
  })

  it('Escape also cancels the sign-out prompt', async () => {
    const { calls } = mockApi(signedInRoutes({ 'GET /workspaces/w1/documents': () => json({ items: [], total: 0, page: 1, page_size: 25 }) }))
    renderApp(<App />, '/app/knowledge')
    await userEvent.click(await screen.findByRole('button', { name: /sign out/i }))
    await screen.findByRole('alertdialog')
    await userEvent.keyboard('{Escape}')
    await waitFor(() => expect(screen.queryByRole('alertdialog')).not.toBeInTheDocument())
    expect(calls.some((c) => c.path === '/auth/logout')).toBe(false)
  })

  it('confirming signs out, clears the session and returns to login', async () => {
    const { calls } = mockApi(signedInRoutes({
      'GET /workspaces/w1/documents': () => json({ items: [], total: 0, page: 1, page_size: 25 }),
      'POST /auth/logout': () => json(null, 204),
    }))
    renderApp(<App />, '/app/knowledge')
    await userEvent.click(await screen.findByRole('button', { name: /sign out/i }))
    const dialog = await screen.findByRole('alertdialog')
    await userEvent.click(within(dialog).getByRole('button', { name: 'Sign out' }))
    expect(await screen.findByRole('heading', { name: 'Sign in' })).toBeInTheDocument()
    expect(calls.find((c) => c.path === '/auth/logout')!.headers.get('X-Requested-By')).toBe('oryn-web')
  })

  it('Settings > Sign out uses the same confirmation', async () => {
    const { calls } = mockApi(signedInRoutes({
      'GET /workspaces/w1/members': () => json([]),
      'POST /auth/logout': () => json(null, 204),
    }))
    renderApp(<App />, '/app/settings')
    await screen.findByRole('heading', { name: 'Settings' })
    const buttons = screen.getAllByRole('button', { name: /^sign out/i })
    await userEvent.click(buttons[buttons.length - 1]!)
    expect(await screen.findByRole('alertdialog')).toBeInTheDocument()
    expect(calls.some((c) => c.path === '/auth/logout')).toBe(false)
  })
})