import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render } from '@testing-library/react'
import type { ReactElement } from 'react'
import { MemoryRouter } from 'react-router-dom'
import { vi } from 'vitest'
import { AuthProvider } from '@/auth/AuthContext'
import { ToastProvider } from '@/components/ui/Toast'
import type { User, Workspace } from '@/lib/types'

export const USER: User = { id: 'u1', email: 'a@example.com', display_name: 'Asha', role: 'user', email_verified: true, has_password: true, google_linked: false }
export const WORKSPACE: Workspace = { id: 'w1', name: 'Acme', description: null, role: 'owner', created_at: '2026-01-01T00:00:00Z' }

export const json = (body: unknown, status = 200) =>
  new Response(status === 204 ? null : JSON.stringify(body), { status, headers: { 'Content-Type': 'application/json' } })

type Handler = (req: { url: string; method: string; body: unknown; headers: Headers }) => Response | Promise<Response>
export interface Call { method: string; path: string; body: unknown; headers: Headers }

/** Routes fetch by "METHOD /path-without-api-prefix" (exact match on path, query ignored). Unmatched calls fail loudly. */
export function mockApi(routes: Record<string, Handler>) {
  const calls: Call[] = []
  const fn = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    const url = new URL(String(input), 'http://localhost')
    const method = (init?.method ?? 'GET').toUpperCase()
    const path = url.pathname.replace(/^\/api\/v1/, '')
    let body: unknown = init?.body
    if (typeof body === 'string') {
      try { body = JSON.parse(body) } catch { /* keep string */ }
    }
    const headers = new Headers(init?.headers)
    calls.push({ method, path, body, headers })
    const h = routes[`${method} ${path}`]
    if (!h) throw new Error(`Unmocked request: ${method} ${path}`)
    return h({ url: url.toString(), method, body, headers })
  })
  vi.stubGlobal('fetch', fn)
  return { calls, fn }
}

export const signedInRoutes = (extra: Record<string, Handler> = {}): Record<string, Handler> => ({
  'POST /auth/refresh': () => json({ access_token: 't', token_type: 'bearer', expires_in: 900, user: USER }),
  'GET /workspaces': () => json([WORKSPACE]),
  ...extra,
})

export function renderApp(ui: ReactElement, route = '/') {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false, gcTime: 0 } } })
  return render(
    <QueryClientProvider client={client}>
      <MemoryRouter initialEntries={[route]}>
        <ToastProvider>
          <AuthProvider>{ui}</AuthProvider>
        </ToastProvider>
      </MemoryRouter>
    </QueryClientProvider>,
  )
}

export function sseResponse(chunks: string[], status = 200) {
  const enc = new TextEncoder()
  const stream = new ReadableStream<Uint8Array>({
    start(c) {
      for (const ch of chunks) c.enqueue(enc.encode(ch))
      c.close()
    },
  })
  return new Response(stream, { status, headers: { 'Content-Type': 'text/event-stream' } })
}

export const ev = (event: string, data: unknown) => `event: ${event}\ndata: ${JSON.stringify(data)}\n\n`
