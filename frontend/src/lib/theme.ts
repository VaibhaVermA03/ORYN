import { useCallback, useEffect, useState } from 'react'
import { safeStorage } from './utils'

export type Theme = 'light' | 'dark'
const KEY = 'oryn-theme'

function systemTheme(): Theme {
  return typeof window !== 'undefined' && window.matchMedia?.('(prefers-color-scheme: dark)').matches ? 'dark' : 'light'
}

function currentTheme(): Theme {
  const attr = document.documentElement.getAttribute('data-theme')
  return attr === 'dark' || attr === 'light' ? attr : systemTheme()
}

function apply(theme: Theme): void {
  document.documentElement.setAttribute('data-theme', theme)
}

/** The user's explicit choice is stored. Without one, the OS preference applies and follows OS changes.
 *  index.html sets data-theme before first paint; this hook keeps it in sync afterwards. */
export function useTheme(): { theme: Theme; toggle: () => void } {
  const [theme, setTheme] = useState<Theme>(currentTheme)

  useEffect(() => {
    const mq = window.matchMedia?.('(prefers-color-scheme: dark)')
    if (!mq) return
    const onChange = () => {
      const saved = safeStorage.get(KEY)
      if (saved === 'dark' || saved === 'light') return // an explicit choice wins over the OS
      const next = systemTheme()
      apply(next)
      setTheme(next)
    }
    mq.addEventListener('change', onChange)
    return () => mq.removeEventListener('change', onChange)
  }, [])

  const toggle = useCallback(() => {
    const next: Theme = currentTheme() === 'dark' ? 'light' : 'dark'
    apply(next)
    safeStorage.set(KEY, next)
    setTheme(next)
  }, [])

  return { theme, toggle }
}