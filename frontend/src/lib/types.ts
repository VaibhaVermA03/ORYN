// Types mirroring the backend API (backend/app/schemas). Keep in sync with docs/API.md.

export interface User {
  id: string
  email: string
  display_name: string
  role: 'user' | 'admin'
  email_verified: boolean
  has_password: boolean
  google_linked: boolean
}

export interface AuthResponse {
  access_token: string
  token_type: 'bearer'
  expires_in: number
  user: User
}

export type WorkspaceRole = 'owner' | 'admin' | 'member'

export interface Workspace {
  id: string
  name: string
  description: string | null
  role: WorkspaceRole
  created_at: string
}

export interface Member {
  user_id: string
  email: string
  display_name: string
  role: WorkspaceRole
  joined_at: string
}

export type DocumentStatus =
  | 'uploaded'
  | 'extracting'
  | 'chunking'
  | 'embedding'
  | 'indexing'
  | 'ready'
  | 'failed'
  | 'deleting'

export interface DocumentItem {
  id: string
  workspace_id: string
  filename: string
  title: string
  file_type: 'pdf' | 'txt' | 'docx'
  size_bytes: number
  status: DocumentStatus
  error_summary: string | null
  page_count: number | null
  chunk_count: number
  attempts: number
  created_at: string
  updated_at: string
  indexed_at: string | null
}

export interface DocumentPage {
  items: DocumentItem[]
  total: number
  page: number
  page_size: number
}

export interface UploadResult {
  filename: string
  accepted: boolean
  document: DocumentItem | null
  error: { code: string; message: string } | null
}

export interface Source {
  index: number
  chunk_id: string
  document_id: string
  filename: string
  page_number: number | null
  excerpt: string
  truncated: boolean
  score: number | null
}

export interface ChunkDetail {
  chunk_id: string
  document_id: string
  filename: string
  page_number: number | null
  chunk_index: number
  text: string
}

export interface Conversation {
  id: string
  title: string
  created_at: string
  updated_at: string
}

export type MessageStatus = 'complete' | 'streaming' | 'cancelled' | 'failed'

export interface ChatMessage {
  id: string
  role: 'user' | 'assistant'
  content: string
  status: MessageStatus
  sources: Source[]
  insufficient_context: boolean
  error_code: string | null
  feedback: 1 | -1 | null
  created_at: string
}

export interface ConversationDetail {
  conversation: Conversation
  messages: ChatMessage[]
}

export interface ConversationPage {
  items: Conversation[]
  total: number
  page: number
  page_size: number
}

// ---- SSE protocol (see backend/app/services/rag_service.py)
export type ChatEvent =
  | { event: 'status'; data: { stage: 'started'; conversation_id: string; message_id: string; user_message_id: string } }
  | { event: 'status'; data: { stage: 'retrieving' | 'generating' } }
  | { event: 'sources'; data: { sources: Source[]; insufficient_context: boolean } }
  | { event: 'token'; data: { text: string } }
  | {
      event: 'done'
      data: {
        message_id: string
        conversation_id: string
        insufficient_context: boolean
        timings_ms: Record<string, number>
      }
    }
  | { event: 'error'; data: { code: string; message: string; retryable: boolean } }

// ---- Analytics
export interface MetricStat {
  mean: number | null
  n: number
}

export interface EvaluationMetrics {
  context_precision?: MetricStat
  context_recall?: MetricStat
  hit_rate?: MetricStat
  faithfulness?: MetricStat
  answer_relevance?: MetricStat
  answer_correctness?: MetricStat
  retrieval_ms?: MetricStat
  rerank_ms?: MetricStat
  generation_ms?: MetricStat
  total_ms?: MetricStat
  _summary?: { samples: number; succeeded: number; failed: number; abstained: number }
}

export interface Analytics {
  window_days: number
  documents: {
    total: number
    by_status: Record<string, number>
    indexed_chunks: number
    recent_failures: { id: string; filename: string; error_summary: string | null; updated_at: string }[]
  }
  usage: {
    queries_30d: number
    queries_7d: number
    active_users_30d: number
    conversations_total: number
    daily_queries: { date: string; queries: number }[]
  }
  latency_ms: {
    samples: number
    avg_total: number | null
    p50_total: number | null
    p95_total: number | null
    avg_retrieval: number | null
    avg_rerank: number | null
    avg_generation: number | null
  }
  reliability: {
    ok: number
    errors: number
    cancelled: number
    provider_errors: number
    provider_error_rate: number | null
    by_provider: Record<string, number>
  }
  feedback: { up: number; down: number; with_comment: number; satisfaction: number | null }
  evaluation: {
    runs: number
    latest: {
      id: string
      dataset_name: string
      sample_count: number
      metrics: EvaluationMetrics
      created_at: string
    } | null
  }
}

export interface EvalRun {
  id: string
  workspace_id: string
  dataset_name: string
  status: 'running' | 'completed' | 'failed'
  sample_count: number
  config: Record<string, unknown>
  metrics: EvaluationMetrics
  error_summary: string | null
  created_at: string
  finished_at: string | null
  disclaimer: string
}

export interface EvalResult {
  id: string
  question: string
  ground_truth: string | null
  answer: string | null
  contexts: { filename: string; page_number: number | null; score: number | null; text: string }[]
  metrics: Record<string, number | null>
  error: string | null
}

export interface EvalRunDetail extends EvalRun {
  results: EvalResult[]
}

export interface AuditEvent {
  id: string
  action: string
  actor_email: string | null
  workspace_id: string | null
  target_type: string | null
  target_id: string | null
  details: Record<string, unknown> | null
  ip_address: string | null
  created_at: string
}

export interface AuditPage {
  items: AuditEvent[]
  total: number
  page: number
  page_size: number
}

export interface AdminOverview {
  window_days: number
  users: number
  workspaces: number
  documents: { total: number; by_status: Record<string, number> }
  queries_30d: number
  error_rate_30d: number | null
}
