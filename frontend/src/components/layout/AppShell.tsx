import { BarChart3, BookOpen, LogOut, Menu, MessagesSquare, Moon, PanelLeftClose, PanelLeftOpen, Settings, ShieldCheck, Sun, X } from 'lucide-react'
import { useCallback, useEffect, useRef, useState, type KeyboardEvent } from 'react'
import { NavLink, Outlet } from 'react-router-dom'
import { useAuth } from '@/auth/AuthContext'
import { Logo } from '@/components/Logo'
import { Button } from '@/components/ui/Button'
import { ErrorState, FullPageSpinner } from '@/components/ui/feedback'
import { useTheme } from '@/lib/theme'
import { cn, initials, safeStorage } from '@/lib/utils'
import { useWorkspace } from '@/workspace/WorkspaceContext'
import { SignOutConfirm } from './SignOutConfirm'
import { WorkspaceSwitcher } from './WorkspaceSwitcher'

const SIDEBAR_KEY = 'oryn-sidebar'

const nav = [
  { to: '/app/knowledge', label: 'Knowledge Base', icon: BookOpen },
  { to: '/app/assistant', label: 'AI Assistant', icon: MessagesSquare },
  { to: '/app/analytics', label: 'Analytics', icon: BarChart3 },
  { to: '/app/settings', label: 'Settings', icon: Settings },
]

function NavItems({ label, onNavigate }: { label: string; onNavigate?: () => void }) {
  const { user } = useAuth()
  const items = user?.role === 'admin' ? [...nav, { to: '/app/admin', label: 'Platform admin', icon: ShieldCheck }] : nav
  return (
    <nav aria-label={label} className="flex flex-col gap-1">
      {items.map(({ to, label: text, icon: Icon }) => (
        <NavLink
          key={to}
          to={to}
          onClick={onNavigate}
          className={({ isActive }) =>
            cn(
              'flex items-center gap-3 rounded-lg px-3 py-2 text-sm font-medium transition-colors',
              isActive ? 'bg-accent-soft text-accent-fg' : 'text-muted hover:bg-surface-2 hover:text-ink',
            )
          }
        >
          <Icon className="h-4 w-4" aria-hidden />
          {text}
        </NavLink>
      ))}
    </nav>
  )
}

function UserCard() {
  const { user } = useAuth()
  return (
    <div className="mt-auto flex items-center gap-3 rounded-lg border border-line p-2.5">
      <span aria-hidden className="flex h-8 w-8 shrink-0 items-center justify-center rounded-full bg-accent-soft text-xs font-semibold text-accent-fg">
        {initials(user?.display_name ?? '?')}
      </span>
      <span className="min-w-0 flex-1">
        <span className="block truncate text-[13px] font-medium">{user?.display_name}</span>
        <span className="block truncate text-xs text-muted">{user?.email}</span>
      </span>
    </div>
  )
}

const FOCUSABLE = 'a[href], button:not([disabled]):not([tabindex="-1"]), input, select, textarea, [tabindex]:not([tabindex="-1"])'

export function AppShell() {
  const { isLoading, error, refetch } = useWorkspace()
  const { theme, toggle } = useTheme()
  const [signOutOpen, setSignOutOpen] = useState(false)

  const [drawerOpen, setDrawerOpen] = useState(false) // phones: slide-in navigation
  const [collapsed, setCollapsed] = useState(() => safeStorage.get(SIDEBAR_KEY) === 'collapsed') // md+: collapsible sidebar
  const menuButtonRef = useRef<HTMLButtonElement>(null)
  const closeButtonRef = useRef<HTMLButtonElement>(null)
  const panelRef = useRef<HTMLDivElement>(null)
  const wasOpen = useRef(false)

  const closeDrawer = useCallback(() => setDrawerOpen(false), [])

  const toggleSidebar = () => {
    setCollapsed((c) => {
      const next = !c
      safeStorage.set(SIDEBAR_KEY, next ? 'collapsed' : 'open')
      return next
    })
  }

  // Drawer: focus the close button when it opens, give focus back to the menu button when it closes.
  useEffect(() => {
    if (drawerOpen) {
      wasOpen.current = true
      closeButtonRef.current?.focus()
    } else if (wasOpen.current) {
      wasOpen.current = false
      menuButtonRef.current?.focus()
    }
  }, [drawerOpen])

  // Drawer: Escape closes it; it also closes if the window grows to desktop width.
  useEffect(() => {
    if (!drawerOpen) return
    const onKey = (e: globalThis.KeyboardEvent) => {
      if (e.key === 'Escape') setDrawerOpen(false)
    }
    document.addEventListener('keydown', onKey)
    const mq = window.matchMedia?.('(min-width: 768px)')
    const onChange = () => mq?.matches && setDrawerOpen(false)
    mq?.addEventListener('change', onChange)
    return () => {
      document.removeEventListener('keydown', onKey)
      mq?.removeEventListener('change', onChange)
    }
  }, [drawerOpen])

  // Keep Tab inside the open drawer.
  const trapTab = (e: KeyboardEvent<HTMLDivElement>) => {
    if (e.key !== 'Tab' || !panelRef.current) return
    const items = Array.from(panelRef.current.querySelectorAll<HTMLElement>(FOCUSABLE))
    const first = items[0]
    const last = items[items.length - 1]
    if (!first || !last) return
    if (e.shiftKey && document.activeElement === first) {
      e.preventDefault()
      last.focus()
    } else if (!e.shiftKey && document.activeElement === last) {
      e.preventDefault()
      first.focus()
    }
  }

  return (
    <div className="flex h-dvh overflow-hidden bg-app text-ink">
      <a href="#main" className="skip-link">
        Skip to content
      </a>

      {/* Everything behind the open phone drawer is inert (no focus, no clicks, hidden from screen readers). */}
      <div className="contents" inert={drawerOpen}>
        {/* Desktop sidebar. Collapsing animates the width, so the page content slides left/right with it. */}
        <aside
          id="app-sidebar"
          inert={collapsed}
          className={cn(
            'hidden shrink-0 overflow-hidden border-line bg-chrome transition-[width,visibility] duration-300 ease-out md:block',
            collapsed ? 'invisible w-0' : 'w-60 border-r',
          )}
        >
          <div className="flex h-full w-60 flex-col p-4">
            <Logo className="mb-6 px-2" />
            <NavItems label="Primary" />
            <UserCard />
          </div>
        </aside>

        <div className="flex min-w-0 flex-1 flex-col">
          <header className="relative z-30 flex h-14 shrink-0 items-center gap-2 border-b border-line bg-chrome px-3 sm:px-4">
            <Button
              ref={menuButtonRef}
              variant="ghost"
              size="icon"
              className="md:hidden"
              aria-label="Open navigation menu"
              aria-expanded={drawerOpen}
              aria-controls="mobile-nav"
              onClick={() => setDrawerOpen(true)}
            >
              <Menu className="h-5 w-5" />
            </Button>
            <Button
              variant="ghost"
              size="icon"
              className="hidden md:inline-flex"
              aria-label={collapsed ? 'Expand sidebar' : 'Collapse sidebar'}
              aria-expanded={!collapsed}
              aria-controls="app-sidebar"
              onClick={toggleSidebar}
            >
              {collapsed ? <PanelLeftOpen className="h-5 w-5" /> : <PanelLeftClose className="h-5 w-5" />}
            </Button>
            {collapsed && <Logo className="mr-1 hidden md:inline-flex" />}

            {/* Narrow on phones (name is cut with an ellipsis), fixed 16rem from sm up. */}
            <WorkspaceSwitcher className="max-w-[9.5rem] flex-1 sm:w-64 sm:max-w-none sm:flex-none" />

            <div className="ml-auto flex items-center gap-1">
              <div className="group relative">
                <Button
                  variant="ghost"
                  size="icon"
                  onClick={toggle}
                  aria-label={theme === 'dark' ? 'Switch to light mode' : 'Switch to dark mode'}
                >
                  {theme === 'dark' ? <Sun className="h-4 w-4" /> : <Moon className="h-4 w-4" />}
                </Button>
                {/* Desktop hover / keyboard-focus hint. aria-hidden: the button's own label is what is announced. */}
                <span
                  aria-hidden
                  className="pointer-events-none absolute right-0 top-full z-50 mt-2 hidden whitespace-nowrap rounded-md bg-ink px-2.5 py-1.5 text-xs font-medium text-app opacity-0 shadow-pop transition-opacity delay-150 duration-150 group-hover:opacity-100 group-has-[:focus-visible]:opacity-100 md:block"
                >
                  {theme === 'dark' ? 'Switch to light mode' : 'Switch to dark mode'}
                </span>
              </div>
              <Button variant="ghost" size="sm" onClick={() => setSignOutOpen(true)} icon={<LogOut className="h-4 w-4" />}>
                <span className="hidden sm:inline">Sign out</span>
                <span className="sr-only sm:hidden">Sign out</span>
              </Button>
            </div>
          </header>

          <main id="main" tabIndex={-1} className="min-h-0 flex-1 overflow-y-auto focus:outline-none">
            {isLoading ? (
              <FullPageSpinner label="Loading workspaces" />
            ) : error ? (
              <ErrorState title="Could not load your workspaces" message={error.message} onRetry={refetch} />
            ) : (
              <Outlet />
            )}
          </main>
        </div>
      </div>

      <SignOutConfirm open={signOutOpen} onOpenChange={setSignOutOpen} />

      {/* Phone drawer: always mounted so it can animate both ways (slides in from the left, back out to the left).
          While closed it is invisible and inert. Opening makes it visible immediately (so focus can move into it);
          closing waits 300 ms (the slide-out) before hiding it. */}
      <div
        id="mobile-nav"
        role={drawerOpen ? 'dialog' : undefined}
        aria-modal={drawerOpen ? true : undefined}
        aria-label={drawerOpen ? 'Navigation menu' : undefined}
        inert={!drawerOpen}
        onKeyDown={trapTab}
        className={cn('fixed inset-0 z-40 transition-[visibility] duration-0 md:hidden', drawerOpen ? 'visible delay-0' : 'invisible delay-300')}
      >
        <button
          type="button"
          tabIndex={-1}
          aria-label="Close navigation menu"
          onClick={closeDrawer}
          className={cn('absolute inset-0 bg-black/50 transition-opacity duration-300 ease-out', drawerOpen ? 'opacity-100' : 'opacity-0')}
        />
        <div
          ref={panelRef}
          className={cn(
            'absolute inset-y-0 left-0 flex w-72 max-w-[85%] flex-col border-r border-line bg-chrome p-4 shadow-pop',
            'transition-transform duration-300 ease-out will-change-transform',
            drawerOpen ? 'translate-x-0' : '-translate-x-full',
          )}
        >
          <div className="mb-6 flex items-center justify-between px-2">
            <Logo />
            <Button ref={closeButtonRef} variant="ghost" size="icon" aria-label="Close navigation menu" onClick={closeDrawer}>
              <X className="h-4 w-4" />
            </Button>
          </div>
          <NavItems label="Mobile navigation" onNavigate={closeDrawer} />
          <UserCard />
        </div>
      </div>
    </div>
  )
}