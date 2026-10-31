import { useMutation, useQueryClient } from '@tanstack/react-query'
import { Check, Copy, MessageSquarePlus, Pencil, RotateCcw, SendHorizontal, Square, ThumbsDown, ThumbsUp, Trash2 } from 'lucide-react'
import { useCallback, useEffect, useMemo, useRef, useState, type FormEvent, type KeyboardEvent } from 'react'
import { useSearchParams } from 'react-router-dom'
import { Markdown } from '@/components/chat/Markdown'
import { SourceDrawer } from '@/components/chat/SourceDrawer'
import { Button } from '@/components/ui/Button'
import { ConfirmDialog, Modal } from '@/components/ui/Dialog'
import { Alert, EmptyState, ErrorState, Skeleton, Spinner } from '@/components/ui/feedback'
import { useToast } from '@/components/ui/Toast'
import { api, errorMessage } from '@/lib/api'
import { keys, useConversationQuery, useConversationsQuery } from '@/lib/queries'
import { streamChat } from '@/lib/sse'
import type { ChatEvent, ChatMessage, Conversation, Source } from '@/lib/types'
import { cn, formatRelative } from '@/lib/utils'
import { useWorkspace } from '@/workspace/WorkspaceContext'

export const SUGGESTIONS = [
  'Summarize the key points of my documents.',
  'What deadlines or dates are mentioned?',
  'Which documents mention pricing or costs?',
]

type Phase = 'idle' | 'retrieving' | 'generating'

const ERROR_TEXT: Record<string, string> = {
  rate_limited: 'You are sending messages too quickly. Please wait a moment.',
  stream_interrupted: 'The connection was interrupted before the answer finished.',
  provider_unavailable: 'An AI provider is temporarily unavailable. Please try again.',
}

function Citations({ sources, onOpen }: { sources: Source[]; onOpen: (s: Source) => void }) {
  if (sources.length === 0) return null
  return (
    <div className="mt-3">
      <p className="mb-1.5 text-xs font-medium text-muted">Sources</p>
      <ul className="flex flex-wrap gap-2">
        {sources.map((s) => (
          <li key={s.chunk_id}>
            <button
              type="button"
              onClick={() => onOpen(s)}
              className="flex max-w-[16rem] items-center gap-1.5 rounded-lg border border-line bg-surface px-2 py-1 text-xs hover:bg-surface-2 focus-visible:outline-2 focus-visible:outline-accent-fg"
              aria-label={`Open source ${s.index}: ${s.filename}${s.page_number ? `, page ${s.page_number}` : ''}`}
            >
              <span className="flex h-4 min-w-4 items-center justify-center rounded bg-accent-soft px-1 font-semibold text-accent-fg">{s.index}</span>
              <span className="truncate">{s.filename}</span>
              {s.page_number != null && <span className="shrink-0 text-muted">p.{s.page_number}</span>}
            </button>
          </li>
        ))}
      </ul>
    </div>
  )
}

function AssistantMessage({
  m,
  live,
  phase,
  onOpenSource,
  onFeedback,
  onRetry,
}: {
  m: ChatMessage
  live: boolean
  phase: Phase
  onOpenSource: (s: Source) => void
  onFeedback: (m: ChatMessage, rating: 1 | -1) => void
  onRetry?: () => void
}) {
  const [copied, setCopied] = useState(false)
  const copy = async () => {
    try {
      await navigator.clipboard.writeText(m.content)
      setCopied(true)
      setTimeout(() => setCopied(false), 1500)
    } catch {
      /* clipboard may be unavailable (insecure context); ignore */
    }
  }
  const failed = m.status === 'failed'
  return (
    <article className="max-w-3xl" aria-label="Assistant message">
      {live && m.content === '' && (
        <p className="flex items-center gap-2 text-sm text-muted" role="status">
          <Spinner className="h-3.5 w-3.5" />
          {phase === 'retrieving' ? 'Searching your documents…' : 'Writing an answer…'}
        </p>
      )}
      {m.content !== '' && <Markdown text={m.content} />}
      {live && m.content !== '' && <span className="ml-0.5 inline-block h-4 w-1.5 animate-[oryn-pulse_1s_ease-in-out_infinite] rounded-sm bg-accent-fg align-middle" aria-hidden />}
      {m.status === 'cancelled' && <p className="mt-1 text-xs text-muted">Stopped.</p>}
      {failed && (
        <Alert tone="danger" className="mt-2">
          {ERROR_TEXT[m.error_code ?? ''] ?? 'The answer could not be completed.'}
        </Alert>
      )}
      <Citations sources={m.sources} onOpen={onOpenSource} />
      {!live && m.content !== '' && (
        <div className="mt-2 flex items-center gap-1">
          <Button size="icon" variant="ghost" aria-label={copied ? 'Copied' : 'Copy answer'} onClick={copy}>
            {copied ? <Check className="h-4 w-4 text-success" /> : <Copy className="h-4 w-4" />}
          </Button>
          <Button size="icon" variant="ghost" aria-label="Helpful" aria-pressed={m.feedback === 1} onClick={() => onFeedback(m, 1)}>
            <ThumbsUp className={cn('h-4 w-4', m.feedback === 1 && 'fill-current text-accent-fg')} />
          </Button>
          <Button size="icon" variant="ghost" aria-label="Not helpful" aria-pressed={m.feedback === -1} onClick={() => onFeedback(m, -1)}>
            <ThumbsDown className={cn('h-4 w-4', m.feedback === -1 && 'fill-current text-danger')} />
          </Button>
        </div>
      )}
      {!live && (failed || m.status === 'cancelled') && onRetry && (
        <Button size="sm" className="mt-2" icon={<RotateCcw className="h-3.5 w-3.5" />} onClick={onRetry}>
          Retry
        </Button>
      )}
    </article>
  )
}

export function AssistantPage() {
  const { workspace } = useWorkspace()
  const ws = workspace?.id
  const qc = useQueryClient()
  const toast = useToast()
  const [params, setParams] = useSearchParams()
  const activeId = params.get('c')
  const conversations = useConversationsQuery(ws)
  const detail = useConversationQuery(ws, activeId)

  const [local, setLocal] = useState<ChatMessage[] | null>(null) // optimistic/streaming transcript
  const [phase, setPhase] = useState<Phase>('idle')
  const [draft, setDraft] = useState('')
  const [source, setSource] = useState<Source | null>(null)
  const [renaming, setRenaming] = useState<Conversation | null>(null)
  const [renameValue, setRenameValue] = useState('')
  const [deleting, setDeleting] = useState<Conversation | null>(null)
  const abortRef = useRef<AbortController | null>(null)
  const bottomRef = useRef<HTMLDivElement>(null)
  const lastQuestion = useRef('')
  const streaming = phase !== 'idle'

  // Server transcript is the source of truth whenever we are not mid-stream.
  const messages = useMemo<ChatMessage[]>(() => local ?? detail.data?.messages ?? [], [local, detail.data])

  useEffect(() => {
    bottomRef.current?.scrollIntoView?.({ block: 'end' })
  }, [messages, phase])

  // Switching workspace or conversation drops any local transcript and stops a running stream.
  useEffect(() => {
    abortRef.current?.abort()
    setLocal(null)
    setPhase('idle')
  }, [ws, activeId])

  useEffect(() => () => abortRef.current?.abort(), [])

  const send = useCallback(
    async (text: string) => {
      const question = text.trim()
      if (!question || !ws || streaming) return
      lastQuestion.current = question
      const now = new Date().toISOString()
      const userMsg: ChatMessage = { id: `u-${Date.now()}`, role: 'user', content: question, status: 'complete', sources: [], insufficient_context: false, error_code: null, feedback: null, created_at: now }
      const asstMsg: ChatMessage = { id: `a-${Date.now()}`, role: 'assistant', content: '', status: 'streaming', sources: [], insufficient_context: false, error_code: null, feedback: null, created_at: now }
      setLocal([...(detail.data?.messages ?? []), userMsg, asstMsg])
      setDraft('')
      setPhase('retrieving')
      const ctrl = new AbortController()
      abortRef.current = ctrl
      let conversationId = activeId
      const asstId = { current: asstMsg.id }
      const patchAssistant = (fn: (m: ChatMessage) => ChatMessage) =>
        setLocal((cur) => (cur ? cur.map((m) => (m.id === asstId.current ? fn(m) : m)) : cur))

      const onEvent = (e: ChatEvent) => {
        if (e.event === 'status') {
          if (e.data.stage === 'started') {
            conversationId = e.data.conversation_id
            const prev = asstId.current
            const next = e.data.message_id
            asstId.current = next
            setLocal((cur) => (cur ? cur.map((m) => (m.id === prev ? { ...m, id: next } : m)) : cur))
          } else setPhase(e.data.stage)
        } else if (e.event === 'sources') {
          patchAssistant((m) => ({ ...m, sources: e.data.sources, insufficient_context: e.data.insufficient_context }))
        } else if (e.event === 'token') {
          setPhase('generating')
          patchAssistant((m) => ({ ...m, content: m.content + e.data.text }))
        } else if (e.event === 'error') {
          patchAssistant((m) => ({ ...m, status: 'failed', error_code: e.data.code }))
        } else {
          patchAssistant((m) => ({ ...m, status: 'complete' }))
        }
      }

      try {
        await streamChat({ workspaceId: ws, message: question, conversationId: activeId, signal: ctrl.signal, onEvent })
      } catch (err) {
        patchAssistant((m) => ({ ...m, status: 'failed', error_code: (err as { code?: string }).code ?? 'stream_interrupted' }))
      } finally {
        if (ctrl.signal.aborted) patchAssistant((m) => ({ ...m, status: 'cancelled' }))
        setPhase('idle')
        abortRef.current = null
        void qc.invalidateQueries({ queryKey: keys.conversations(ws) })
        if (conversationId) {
          if (conversationId !== activeId) setParams({ c: conversationId }, { replace: true })
          else {
            await qc.invalidateQueries({ queryKey: keys.conversation(ws, conversationId) })
            setLocal(null)
          }
        }
      }
    },
    [ws, streaming, detail.data, activeId, qc, setParams],
  )

  const stop = () => abortRef.current?.abort()

  const onSubmit = (e: FormEvent) => {
    e.preventDefault()
    void send(draft)
  }
  const onKey = (e: KeyboardEvent<HTMLTextAreaElement>) => {
    if (e.key === 'Enter' && !e.shiftKey && !e.nativeEvent.isComposing) {
      e.preventDefault()
      void send(draft)
    }
  }

  const feedback = useMutation({
    mutationFn: ({ m, rating }: { m: ChatMessage; rating: 1 | -1 }) =>
      m.feedback === rating ? api.del(`/workspaces/${ws}/messages/${m.id}/feedback`) : api.put(`/workspaces/${ws}/messages/${m.id}/feedback`, { rating }),
    onSuccess: () => {
      if (ws && activeId) void qc.invalidateQueries({ queryKey: keys.conversation(ws, activeId) })
    },
    onError: (e) => toast.error(errorMessage(e, 'Could not save feedback.')),
  })

  const rename = useMutation({
    mutationFn: ({ id, title }: { id: string; title: string }) => api.patch(`/workspaces/${ws}/conversations/${id}`, { title }),
    onSuccess: () => {
      setRenaming(null)
      if (ws) void qc.invalidateQueries({ queryKey: keys.conversations(ws) })
    },
    onError: (e) => toast.error(errorMessage(e, 'Could not rename the conversation.')),
  })

  const remove = useMutation({
    mutationFn: (id: string) => api.del(`/workspaces/${ws}/conversations/${id}`),
    onSuccess: (_d, id) => {
      setDeleting(null)
      if (id === activeId) setParams({}, { replace: true })
      if (ws) void qc.invalidateQueries({ queryKey: keys.conversations(ws) })
    },
    onError: (e) => toast.error(errorMessage(e, 'Could not delete the conversation.')),
  })

  if (!workspace) {
    return (
      <div className="p-6">
        <EmptyState title="No workspace yet" description="Create a workspace in Settings to start asking questions." />
      </div>
    )
  }

  const items = conversations.data?.items ?? []

  return (
    <div className="flex h-full min-h-0">
      <aside aria-label="Conversations" className="hidden w-64 shrink-0 flex-col border-r border-line bg-chrome lg:flex">
        <div className="p-3">
          <Button className="w-full" icon={<MessageSquarePlus className="h-4 w-4" />} onClick={() => setParams({}, { replace: true })} disabled={streaming}>
            New conversation
          </Button>
        </div>
        <div className="min-h-0 flex-1 overflow-y-auto px-2 pb-3">
          {conversations.isLoading ? (
            <div className="space-y-2 p-1">
              {[0, 1, 2].map((i) => (
                <Skeleton key={i} className="h-8 w-full" />
              ))}
            </div>
          ) : conversations.error ? (
            <ErrorState title="Could not load history" message={errorMessage(conversations.error)} onRetry={() => void conversations.refetch()} />
          ) : items.length === 0 ? (
            <p className="px-3 py-6 text-center text-xs text-muted">No conversations yet.</p>
          ) : (
            <ul>
              {items.map((c) => (
                <li key={c.id} className="group relative">
                  <button
                    type="button"
                    onClick={() => setParams({ c: c.id })}
                    disabled={streaming}
                    aria-current={c.id === activeId ? 'page' : undefined}
                    className={cn(
                      'flex w-full flex-col rounded-lg px-3 py-2 pr-16 text-left text-sm hover:bg-surface-2 disabled:opacity-60',
                      c.id === activeId && 'bg-accent-soft',
                    )}
                  >
                    <span className="truncate font-medium">{c.title}</span>
                    <span className="text-xs text-muted">{formatRelative(c.updated_at)}</span>
                  </button>
                  <div className="absolute right-1 top-1.5 hidden gap-0.5 group-focus-within:flex group-hover:flex">
                    <Button
                      size="icon"
                      variant="ghost"
                      className="h-7 w-7"
                      aria-label={`Rename ${c.title}`}
                      onClick={() => {
                        setRenaming(c)
                        setRenameValue(c.title)
                      }}
                    >
                      <Pencil className="h-3.5 w-3.5" />
                    </Button>
                    <Button size="icon" variant="ghost" className="h-7 w-7" aria-label={`Delete ${c.title}`} onClick={() => setDeleting(c)}>
                      <Trash2 className="h-3.5 w-3.5" />
                    </Button>
                  </div>
                </li>
              ))}
            </ul>
          )}
        </div>
      </aside>

      <section className="flex min-w-0 flex-1 flex-col" aria-label="Chat">
        <div className="min-h-0 flex-1 overflow-y-auto px-4 py-6 sm:px-8" aria-live="polite" aria-busy={streaming}>
          {activeId && detail.isLoading && local === null ? (
            <div className="mx-auto max-w-3xl space-y-4">
              <Skeleton className="h-10 w-2/3" />
              <Skeleton className="h-24 w-full" />
            </div>
          ) : activeId && detail.error && local === null ? (
            <ErrorState title="Could not open this conversation" message={errorMessage(detail.error)} onRetry={() => void detail.refetch()} />
          ) : messages.length === 0 ? (
            <div className="mx-auto flex max-w-xl flex-col items-center gap-4 pt-16 text-center">
              <h1 className="text-xl font-semibold">Ask about {workspace.name}</h1>
              <p className="text-sm text-muted">Answers are drawn only from the documents in this workspace, with sources you can open.</p>
              <div className="flex flex-wrap justify-center gap-2">
                {SUGGESTIONS.map((s) => (
                  <button
                    key={s}
                    type="button"
                    onClick={() => void send(s)}
                    className="rounded-full border border-line bg-surface px-3 py-1.5 text-sm hover:bg-surface-2 focus-visible:outline-2 focus-visible:outline-accent-fg"
                  >
                    {s}
                  </button>
                ))}
              </div>
            </div>
          ) : (
            <div className="mx-auto max-w-3xl space-y-6">
              {messages.map((m, i) =>
                m.role === 'user' ? (
                  <div key={m.id} className="flex justify-end">
                    <p className="max-w-[85%] whitespace-pre-wrap rounded-2xl rounded-br-md bg-accent px-4 py-2.5 text-sm text-on-accent">{m.content}</p>
                  </div>
                ) : (
                  <AssistantMessage
                    key={m.id}
                    m={m}
                    live={streaming && i === messages.length - 1}
                    phase={phase}
                    onOpenSource={setSource}
                    onFeedback={(msg, rating) => feedback.mutate({ m: msg, rating })}
                    onRetry={i === messages.length - 1 ? () => void send(lastQuestion.current || (messages[i - 1]?.content ?? '')) : undefined}
                  />
                ),
              )}
              <div ref={bottomRef} />
            </div>
          )}
        </div>

        <form onSubmit={onSubmit} className="border-t border-line bg-surface p-3 sm:px-8">
          <div className="mx-auto flex max-w-3xl items-end gap-2">
            <label htmlFor="chat-input" className="sr-only">
              Ask a question
            </label>
            <textarea
              id="chat-input"
              value={draft}
              onChange={(e) => setDraft(e.target.value)}
              onKeyDown={onKey}
              rows={1}
              maxLength={4000}
              placeholder="Ask a question about your documents"
              className="max-h-40 min-h-10 flex-1 resize-none rounded-lg border border-line bg-surface px-3 py-2 text-sm focus-visible:outline-2 focus-visible:outline-accent-fg"
            />
            {streaming ? (
              <Button type="button" onClick={stop} icon={<Square className="h-3.5 w-3.5 fill-current" />}>
                Stop
              </Button>
            ) : (
              <Button type="submit" variant="primary" disabled={draft.trim() === ''} icon={<SendHorizontal className="h-4 w-4" />}>
                Send
              </Button>
            )}
          </div>
        </form>
      </section>

      {ws && <SourceDrawer workspaceId={ws} source={source} onClose={() => setSource(null)} />}

      <Modal open={renaming !== null} onOpenChange={(o) => !o && setRenaming(null)} title="Rename conversation">
        <form
          className="space-y-4"
          onSubmit={(e) => {
            e.preventDefault()
            if (renaming && renameValue.trim()) rename.mutate({ id: renaming.id, title: renameValue.trim() })
          }}
        >
          <label className="block text-[13px] font-medium" htmlFor="rename-input">
            Title
          </label>
          <input
            id="rename-input"
            value={renameValue}
            maxLength={200}
            onChange={(e) => setRenameValue(e.target.value)}
            className="h-10 w-full rounded-lg border border-line bg-surface px-3 text-sm focus-visible:outline-2 focus-visible:outline-accent-fg"
          />
          <div className="flex justify-end gap-2">
            <Button onClick={() => setRenaming(null)}>Cancel</Button>
            <Button type="submit" variant="primary" loading={rename.isPending} disabled={renameValue.trim() === ''}>
              Save
            </Button>
          </div>
        </form>
      </Modal>

      <ConfirmDialog
        open={deleting !== null}
        onOpenChange={(o) => !o && setDeleting(null)}
        title="Delete this conversation?"
        description="The conversation and its messages will be permanently deleted."
        confirmLabel="Delete"
        loading={remove.isPending}
        onConfirm={() => {
          if (deleting) remove.mutate(deleting.id)
        }}
      />
    </div>
  )
}