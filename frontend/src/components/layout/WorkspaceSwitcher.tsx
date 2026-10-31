import { Check, ChevronDown, Plus } from 'lucide-react'
import { useCallback, useEffect, useId, useRef, useState, type KeyboardEvent } from 'react'
import { useNavigate } from 'react-router-dom'
import { cn } from '@/lib/utils'
import { useWorkspace } from '@/workspace/WorkspaceContext'

/**
 * Header workspace picker.
 * - Trigger: fixed-width container; a long name is cut with an ellipsis.
 * - Panel: same look as the trigger. On small screens it spans the screen width (full names visible,
 *   wrapping if needed); from `sm` up it is exactly as wide as the trigger.
 * - Keyboard: Arrow keys / Home / End move, Enter or Space selects, Escape closes, Tab leaves.
 * - Last row: "Create new workspace" jumps to the create section on the Settings page.
 */
export function WorkspaceSwitcher({ className }: { className?: string }) {
  const { workspaces, workspace, select } = useWorkspace()
  const navigate = useNavigate()
  const uid = useId()
  const listId = `${uid}-list`
  const optionId = (i: number) => `${uid}-opt-${i}`

  const rootRef = useRef<HTMLDivElement>(null)
  const triggerRef = useRef<HTMLButtonElement>(null)
  const listRef = useRef<HTMLUListElement>(null)
  const createRef = useRef<HTMLButtonElement>(null)
  const [open, setOpen] = useState(false)
  const [active, setActive] = useState(0)

  const selectedIndex = Math.max(0, workspaces.findIndex((w) => w.id === workspace?.id))
  const count = workspaces.length

  const close = useCallback((refocus: boolean) => {
    setOpen(false)
    if (refocus) triggerRef.current?.focus()
  }, [])

  const openMenu = () => {
    setActive(selectedIndex)
    setOpen(true)
  }

  // Move focus into the panel when it opens.
  useEffect(() => {
    if (!open) return
    if (count > 0) listRef.current?.focus()
    else createRef.current?.focus()
  }, [open, count])

  // Close on outside pointer press, on focus leaving the component, and on Escape.
  // (Pointer + focusin instead of blur: Safari does not focus buttons on click, so blur would fire early.)
  useEffect(() => {
    if (!open) return
    const inside = (t: EventTarget | null) => !!rootRef.current && t instanceof Node && rootRef.current.contains(t)
    const onPointerDown = (e: PointerEvent) => {
      if (!inside(e.target)) setOpen(false)
    }
    const onFocusIn = (e: FocusEvent) => {
      if (!inside(e.target)) setOpen(false)
    }
    const onKey = (e: globalThis.KeyboardEvent) => {
      if (e.key === 'Escape') close(true)
    }
    document.addEventListener('pointerdown', onPointerDown)
    document.addEventListener('focusin', onFocusIn)
    document.addEventListener('keydown', onKey)
    return () => {
      document.removeEventListener('pointerdown', onPointerDown)
      document.removeEventListener('focusin', onFocusIn)
      document.removeEventListener('keydown', onKey)
    }
  }, [open, close])

  // Keep the highlighted option visible when the list scrolls.
  useEffect(() => {
    if (open && count > 0) document.getElementById(optionId(active))?.scrollIntoView({ block: 'nearest' })
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open, active, count])

  const choose = (i: number) => {
    const w = workspaces[i]
    if (w) select(w.id)
    close(true)
  }

  const onTriggerKey = (e: KeyboardEvent<HTMLButtonElement>) => {
    if (e.key === 'ArrowDown' || e.key === 'ArrowUp') {
      e.preventDefault()
      if (!open) openMenu()
    }
  }

  const onListKey = (e: KeyboardEvent<HTMLUListElement>) => {
    if (count === 0) return
    switch (e.key) {
      case 'ArrowDown':
        e.preventDefault()
        setActive((i) => (i + 1) % count)
        break
      case 'ArrowUp':
        e.preventDefault()
        setActive((i) => (i - 1 + count) % count)
        break
      case 'Home':
        e.preventDefault()
        setActive(0)
        break
      case 'End':
        e.preventDefault()
        setActive(count - 1)
        break
      case 'Enter':
      case ' ':
        e.preventDefault()
        choose(active)
        break
    }
  }

  const createNew = () => {
    setOpen(false)
    navigate('/app/settings#create-workspace')
  }

  const name = workspace?.name ?? 'No workspace'

  return (
    <div ref={rootRef} className={cn('relative min-w-0', className)}>
      <button
        ref={triggerRef}
        type="button"
        aria-haspopup="listbox"
        aria-expanded={open}
        aria-controls={open ? listId : undefined}
        aria-label={`Workspace: ${name}. Change workspace`}
        onClick={() => (open ? close(false) : openMenu())}
        onKeyDown={onTriggerKey}
        className="flex h-9 w-full items-center gap-2 rounded-lg border border-line bg-surface px-3 text-sm shadow-card transition-colors hover:bg-surface-2"
      >
        <span className="min-w-0 flex-1 truncate text-left font-medium">{name}</span>
        <ChevronDown aria-hidden className={cn('h-4 w-4 shrink-0 text-muted transition-transform duration-200', open && 'rotate-180')} />
      </button>

      {open && (
        <div
          className={cn(
            'z-50 overflow-hidden rounded-lg border border-line bg-surface text-sm shadow-pop animate-[oryn-in_0.12s_ease-out]',
            // phones: span the screen under the 3.5rem header; sm and up: exactly the trigger's width
            'fixed inset-x-4 top-[3.75rem] sm:absolute sm:inset-x-0 sm:top-full sm:mt-1.5',
          )}
        >
          <p className="px-3 pb-1 pt-2 text-xs font-medium text-muted">Workspaces</p>
          {count > 0 ? (
            <ul
              ref={listRef}
              id={listId}
              role="listbox"
              tabIndex={-1}
              aria-label="Workspaces"
              aria-activedescendant={optionId(active)}
              onKeyDown={onListKey}
              className="max-h-[min(18rem,60dvh)] overflow-y-auto p-1 focus:outline-none"
            >
              {workspaces.map((w, i) => {
                const selected = w.id === workspace?.id
                return (
                  <li
                    key={w.id}
                    id={optionId(i)}
                    role="option"
                    aria-selected={selected}
                    onClick={() => choose(i)}
                    onMouseMove={() => active !== i && setActive(i)}
                    className={cn(
                      'flex cursor-pointer items-start gap-2 rounded-md px-2 py-2',
                      i === active && 'bg-surface-2',
                      selected && 'font-medium',
                    )}
                  >
                    <span className="min-w-0 flex-1 break-words">{w.name}</span>
                    {selected && <Check aria-hidden className="mt-0.5 h-4 w-4 shrink-0 text-accent-fg" />}
                  </li>
                )
              })}
            </ul>
          ) : (
            <p className="px-3 pb-3 text-muted">You are not in a workspace yet.</p>
          )}
          <div className="border-t border-line p-1">
            <button
              ref={createRef}
              type="button"
              onClick={createNew}
              className="flex w-full items-center gap-2 rounded-md px-2 py-2 text-left font-medium transition-colors hover:bg-surface-2"
            >
              <Plus aria-hidden className="h-4 w-4 shrink-0 text-accent-fg" />
              Create new workspace
            </button>
          </div>
        </div>
      )}
    </div>
  )
}