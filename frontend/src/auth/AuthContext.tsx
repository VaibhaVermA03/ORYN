import { useQueryClient } from '@tanstack/react-query'
import { createContext, useCallback, useContext, useEffect, useMemo, useState, type ReactNode } from 'react'
import { request, refreshSession, setAccessToken, setAuthLostHandler } from '@/lib/api'
import type { AuthResponse, User } from '@/lib/types'

type Status = 'loading' | 'authenticated' | 'anonymous'

interface AuthContextValue {
  status: Status
  user: User | null
  login: (email: string, password: string) => Promise<void>
  signup: (input: { email: string; password: string; display_name: string }) => Promise<void>
  logout: () => Promise<void>
  setUser: (u: User) => void
}

const AuthContext = createContext<AuthContextValue | null>(null)

export function AuthProvider({ children }: { children: ReactNode }) {
  const [status, setStatus] = useState<Status>('loading')
  const [user, setUserState] = useState<User | null>(null)
  const queryClient = useQueryClient()

  const clear = useCallback(() => {
    setAccessToken(null)
    setUserState(null)
    setStatus('anonymous')
    queryClient.clear() // never leave one user's cached data around for the next sign-in
  }, [queryClient])

  const adopt = useCallback((res: AuthResponse) => {
    setAccessToken(res.access_token)
    setUserState(res.user)
    setStatus('authenticated')
  }, [])

  useEffect(() => {
    setAuthLostHandler(clear)
    let cancelled = false
    refreshSession()
      .then((res) => {
        if (cancelled) return
        if (res) adopt(res)
        else setStatus('anonymous')
      })
      .catch(() => {
        if (!cancelled) setStatus('anonymous')
      })
    return () => {
      cancelled = true
      setAuthLostHandler(null)
    }
  }, [adopt, clear])

  const login = useCallback(
    async (email: string, password: string) => {
      adopt(await request<AuthResponse>('/auth/login', { method: 'POST', body: { email, password }, anonymous: true, cookie: true }))
    },
    [adopt],
  )

  const signup = useCallback(
    async (input: { email: string; password: string; display_name: string }) => {
      adopt(await request<AuthResponse>('/auth/signup', { method: 'POST', body: input, anonymous: true, cookie: true }))
    },
    [adopt],
  )

  const logout = useCallback(async () => {
    try {
      await request<void>('/auth/logout', { method: 'POST', cookie: true, anonymous: true })
    } catch {
      /* the local session is cleared regardless; the server also expires it */
    }
    clear()
  }, [clear])

  const value = useMemo<AuthContextValue>(
    () => ({ status, user, login, signup, logout, setUser: setUserState }),
    [status, user, login, signup, logout],
  )
  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>
}

export function useAuth(): AuthContextValue {
  const ctx = useContext(AuthContext)
  if (!ctx) throw new Error('useAuth must be used inside <AuthProvider>')
  return ctx
}
