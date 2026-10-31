import { createContext, useCallback, useContext, useMemo, useState, type ReactNode } from 'react'
import { useWorkspacesQuery } from '@/lib/queries'
import type { Workspace } from '@/lib/types'
import { safeStorage } from '@/lib/utils'

interface WorkspaceContextValue {
  workspaces: Workspace[]
  workspace: Workspace | null
  isLoading: boolean
  error: Error | null
  refetch: () => void
  select: (id: string) => void
  /** True for workspace owners and admins (UI hint only; the server enforces it). */
  canManage: boolean
}

const WorkspaceContext = createContext<WorkspaceContextValue | null>(null)
const KEY = 'oryn-workspace'

export function WorkspaceProvider({ children }: { children: ReactNode }) {
  const query = useWorkspacesQuery()
  const [selectedId, setSelectedId] = useState<string | null>(() => safeStorage.get(KEY))

  const workspaces = useMemo(() => query.data ?? [], [query.data])
  const workspace = useMemo(
    () => workspaces.find((w) => w.id === selectedId) ?? workspaces[0] ?? null,
    [workspaces, selectedId],
  )

  const select = useCallback((id: string) => {
    setSelectedId(id)
    safeStorage.set(KEY, id)
  }, [])

  const value = useMemo<WorkspaceContextValue>(
    () => ({
      workspaces,
      workspace,
      isLoading: query.isLoading,
      error: query.error,
      refetch: () => void query.refetch(),
      select,
      canManage: workspace?.role === 'owner' || workspace?.role === 'admin',
    }),
    [workspaces, workspace, query, select],
  )
  return <WorkspaceContext.Provider value={value}>{children}</WorkspaceContext.Provider>
}

export function useWorkspace(): WorkspaceContextValue {
  const ctx = useContext(WorkspaceContext)
  if (!ctx) throw new Error('useWorkspace must be used inside <WorkspaceProvider>')
  return ctx
}
