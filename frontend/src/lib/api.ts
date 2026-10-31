import type { AuthResponse } from './types'

const API_BASE = ((import.meta.env.VITE_API_BASE_URL as string | undefined) ?? '').replace(/\/+$/, '')
export const API_PREFIX = `${API_BASE}/api/v1`

/** The short-lived access token lives only in memory: never in localStorage or sessionStorage. The
 *  long-lived refresh token is an HttpOnly cookie that JavaScript cannot read. */
let accessToken: string | null = null
let onAuthLost: (() => void) | null = null

export function setAccessToken(token: string | null): void {
  accessToken = token
}
export function getAccessToken(): string | null {
  return accessToken
}
export function setAuthLostHandler(fn: (() => void) | null): void {
  onAuthLost = fn
}

export class ApiError extends Error {
  readonly status: number
  readonly code: string
  readonly requestId: string | null

  constructor(status: number, code: string, message: string, requestId: string | null = null) {
    super(message)
    this.name = 'ApiError'
    this.status = status
    this.code = code
    this.requestId = requestId
  }
}

export function isApiError(e: unknown): e is ApiError {
  return e instanceof ApiError
}

export function errorMessage(e: unknown, fallback = 'Something went wrong. Please try again.'): string {
  return isApiError(e) ? e.message : e instanceof Error && e.message ? e.message : fallback
}

const CSRF_HEADERS = { 'X-Requested-By': 'oryn-web' }

async function toApiError(res: Response): Promise<ApiError> {
  let code = 'http_error'
  let message = `Request failed (${res.status}).`
  let requestId: string | null = res.headers.get('x-request-id')
  try {
    const body = (await res.json()) as { error?: { code?: string; message?: string; request_id?: string } }
    if (body.error) {
      code = body.error.code ?? code
      message = body.error.message ?? message
      requestId = body.error.request_id ?? requestId
    }
  } catch {
    /* non-JSON error body (proxy page, etc.): keep the generic message */
  }
  return new ApiError(res.status, code, message, requestId)
}

async function doFetch(input: string, init: RequestInit): Promise<Response> {
  try {
    return await fetch(input, init)
  } catch (e) {
    if (e instanceof DOMException && e.name === 'AbortError') throw e
    throw new ApiError(0, 'network_error', 'Cannot reach the server. Check your connection and try again.')
  }
}

let refreshInFlight: Promise<AuthResponse | null> | null = null

/** Exchange the refresh cookie for a new access token. Concurrent callers share one request, which
 *  matters because refresh tokens rotate on every use. Returns null when there is no valid session. */
export function refreshSession(): Promise<AuthResponse | null> {
  if (refreshInFlight) return refreshInFlight
  refreshInFlight = (async () => {
    try {
      const res = await doFetch(`${API_PREFIX}/auth/refresh`, {
        method: 'POST',
        credentials: 'include',
        headers: CSRF_HEADERS,
      })
      if (res.status === 401 || res.status === 403) {
        accessToken = null
        return null
      }
      if (!res.ok) throw await toApiError(res)
      const data = (await res.json()) as AuthResponse
      accessToken = data.access_token
      return data
    } finally {
      refreshInFlight = null
    }
  })()
  return refreshInFlight
}

interface RequestOptions {
  method?: 'GET' | 'POST' | 'PUT' | 'PATCH' | 'DELETE'
  body?: unknown
  form?: FormData
  signal?: AbortSignal
  /** Send the refresh cookie and CSRF header (auth endpoints only). */
  cookie?: boolean
  /** Skip the Authorization header and the 401 refresh-and-retry behaviour (login/signup). */
  anonymous?: boolean
}

export async function request<T>(path: string, opts: RequestOptions = {}): Promise<T> {
  const build = (): RequestInit => {
    const headers: Record<string, string> = {}
    if (!opts.anonymous && accessToken) headers.Authorization = `Bearer ${accessToken}`
    if (opts.cookie) Object.assign(headers, CSRF_HEADERS)
    let body: BodyInit | undefined
    if (opts.form) body = opts.form
    else if (opts.body !== undefined) {
      headers['Content-Type'] = 'application/json'
      body = JSON.stringify(opts.body)
    }
    return {
      method: opts.method ?? 'GET',
      headers,
      body,
      signal: opts.signal,
      credentials: opts.cookie ? 'include' : 'same-origin',
    }
  }

  let res = await doFetch(`${API_PREFIX}${path}`, build())
  if (res.status === 401 && !opts.anonymous && !opts.cookie) {
    const refreshed = await refreshSession()
    if (!refreshed) {
      onAuthLost?.()
      throw await toApiError(res)
    }
    res = await doFetch(`${API_PREFIX}${path}`, build())
  }
  if (!res.ok) throw await toApiError(res)
  if (res.status === 204) return undefined as T
  return (await res.json()) as T
}

export const api = {
  get: <T>(path: string, signal?: AbortSignal) => request<T>(path, { signal }),
  post: <T>(path: string, body?: unknown, signal?: AbortSignal) => request<T>(path, { method: 'POST', body, signal }),
  put: <T>(path: string, body?: unknown) => request<T>(path, { method: 'PUT', body }),
  patch: <T>(path: string, body?: unknown) => request<T>(path, { method: 'PATCH', body }),
  del: <T = void>(path: string) => request<T>(path, { method: 'DELETE' }),
  upload: <T>(path: string, form: FormData, signal?: AbortSignal) => request<T>(path, { method: 'POST', form, signal }),
}
