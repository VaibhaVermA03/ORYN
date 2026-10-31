import { useQuery } from '@tanstack/react-query'
import { api } from './api'
import type {
  AdminOverview,
  Analytics,
  AuditPage,
  ChunkDetail,
  ConversationDetail,
  ConversationPage,
  DocumentPage,
  EvalRun,
  EvalRunDetail,
  Member,
  Workspace,
} from './types'

export const keys = {
  workspaces: ['workspaces'] as const,
  members: (ws: string) => ['members', ws] as const,
  documents: (ws: string, q: string, status: string, page: number) => ['documents', ws, q, status, page] as const,
  documentsAll: (ws: string) => ['documents', ws] as const,
  conversations: (ws: string) => ['conversations', ws] as const,
  conversation: (ws: string, id: string) => ['conversation', ws, id] as const,
  chunk: (ws: string, id: string) => ['chunk', ws, id] as const,
  analytics: (ws: string) => ['analytics', ws] as const,
  evalRuns: (ws: string) => ['eval-runs', ws] as const,
  evalRun: (ws: string, id: string) => ['eval-run', ws, id] as const,
  audit: (scope: string, page: number) => ['audit', scope, page] as const,
  adminOverview: ['admin-overview'] as const,
}

export const useWorkspacesQuery = () => useQuery({ queryKey: keys.workspaces, queryFn: () => api.get<Workspace[]>('/workspaces') })

export const useMembersQuery = (ws: string | undefined) =>
  useQuery({ queryKey: keys.members(ws ?? ''), queryFn: () => api.get<Member[]>(`/workspaces/${ws}/members`), enabled: !!ws })

const PROCESSING = new Set(['uploaded', 'extracting', 'chunking', 'embedding', 'indexing', 'deleting'])

/** Polls every 2 s while any document on the page is still being processed. */
export const useDocumentsQuery = (ws: string | undefined, q: string, status: string, page: number) =>
  useQuery({
    queryKey: keys.documents(ws ?? '', q, status, page),
    enabled: !!ws,
    queryFn: () => {
      const p = new URLSearchParams({ page: String(page), page_size: '25' })
      if (q) p.set('q', q)
      if (status) p.set('status', status)
      return api.get<DocumentPage>(`/workspaces/${ws}/documents?${p}`)
    },
    refetchInterval: (query) => (query.state.data?.items.some((d) => PROCESSING.has(d.status)) ? 2000 : false),
  })

export const useConversationsQuery = (ws: string | undefined) =>
  useQuery({
    queryKey: keys.conversations(ws ?? ''),
    enabled: !!ws,
    queryFn: () => api.get<ConversationPage>(`/workspaces/${ws}/conversations?page_size=100`),
  })

export const useConversationQuery = (ws: string | undefined, id: string | null) =>
  useQuery({
    queryKey: keys.conversation(ws ?? '', id ?? ''),
    enabled: !!ws && !!id,
    queryFn: () => api.get<ConversationDetail>(`/workspaces/${ws}/conversations/${id}`),
  })

export const useChunkQuery = (ws: string | undefined, id: string | null) =>
  useQuery({
    queryKey: keys.chunk(ws ?? '', id ?? ''),
    enabled: !!ws && !!id,
    staleTime: Infinity,
    queryFn: () => api.get<ChunkDetail>(`/workspaces/${ws}/chunks/${id}`),
  })

export const useAnalyticsQuery = (ws: string | undefined, enabled: boolean) =>
  useQuery({
    queryKey: keys.analytics(ws ?? ''),
    enabled: !!ws && enabled,
    queryFn: () => api.get<Analytics>(`/workspaces/${ws}/analytics`),
  })

export const useEvalRunsQuery = (ws: string | undefined, enabled: boolean) =>
  useQuery({
    queryKey: keys.evalRuns(ws ?? ''),
    enabled: !!ws && enabled,
    queryFn: () => api.get<EvalRun[]>(`/workspaces/${ws}/evaluations`),
    refetchInterval: (q) => (q.state.data?.some((r) => r.status === 'running') ? 3000 : false),
  })

export const useEvalRunQuery = (ws: string | undefined, id: string | null) =>
  useQuery({
    queryKey: keys.evalRun(ws ?? '', id ?? ''),
    enabled: !!ws && !!id,
    queryFn: () => api.get<EvalRunDetail>(`/workspaces/${ws}/evaluations/${id}`),
    refetchInterval: (q) => (q.state.data?.status === 'running' ? 3000 : false),
  })

export const useAuditQuery = (scope: 'platform' | string, page: number, enabled = true) =>
  useQuery({
    queryKey: keys.audit(scope, page),
    enabled,
    queryFn: () =>
      api.get<AuditPage>(
        scope === 'platform' ? `/admin/audit-events?page=${page}&page_size=25` : `/workspaces/${scope}/audit-events?page=${page}&page_size=25`,
      ),
  })

export const useAdminOverviewQuery = () => useQuery({ queryKey: keys.adminOverview, queryFn: () => api.get<AdminOverview>('/admin/overview') })
