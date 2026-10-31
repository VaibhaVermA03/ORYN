import { useMutation, useQueryClient } from '@tanstack/react-query'
import { AlertCircle, FileText, FileUp, RefreshCw, Search, Trash2 } from 'lucide-react'
import { useEffect, useId, useRef, useState, type DragEvent } from 'react'
import { Button } from '@/components/ui/Button'
import { ConfirmDialog } from '@/components/ui/Dialog'
import { Badge, Card, EmptyState, ErrorState, PageHeader, Skeleton } from '@/components/ui/feedback'
import { useToast } from '@/components/ui/Toast'
import { api, errorMessage } from '@/lib/api'
import { keys, useDocumentsQuery } from '@/lib/queries'
import type { DocumentItem, DocumentStatus, UploadResult } from '@/lib/types'
import { cn, formatBytes, formatRelative } from '@/lib/utils'
import { useWorkspace } from '@/workspace/WorkspaceContext'

export const ALLOWED_EXTENSIONS = ['.pdf', '.txt', '.docx']
const STAGES: DocumentStatus[] = ['uploaded', 'extracting', 'chunking', 'embedding', 'indexing', 'ready']

const STATUS_LABEL: Record<DocumentStatus, string> = {
  uploaded: 'Queued',
  extracting: 'Extracting text',
  chunking: 'Splitting',
  embedding: 'Embedding',
  indexing: 'Indexing',
  ready: 'Ready',
  failed: 'Failed',
  deleting: 'Deleting',
}

export function StatusBadge({ doc }: { doc: DocumentItem }) {
  const s = doc.status
  if (s === 'ready') return <Badge tone="success">{STATUS_LABEL[s]}</Badge>
  if (s === 'failed') return <Badge tone="danger">{STATUS_LABEL[s]}</Badge>
  if (s === 'deleting') return <Badge tone="neutral">{STATUS_LABEL[s]}</Badge>
  const step = Math.max(STAGES.indexOf(s), 0)
  return (
    <span className="inline-flex flex-col gap-1">
      <Badge tone="accent">{STATUS_LABEL[s]}</Badge>
      <span
        role="progressbar"
        aria-label={`Processing ${doc.filename}`}
        aria-valuemin={0}
        aria-valuemax={STAGES.length - 1}
        aria-valuenow={step}
        aria-valuetext={STATUS_LABEL[s]}
        className="block h-1 w-24 overflow-hidden rounded-full bg-surface-2"
      >
        <span className="block h-full rounded-full bg-accent-fg transition-all" style={{ width: `${(step / (STAGES.length - 1)) * 100}%` }} />
      </span>
    </span>
  )
}

function validExtension(name: string): boolean {
  const lower = name.toLowerCase()
  return ALLOWED_EXTENSIONS.some((e) => lower.endsWith(e))
}

export function KnowledgeBasePage() {
  const { workspace } = useWorkspace()
  const ws = workspace?.id
  const qc = useQueryClient()
  const toast = useToast()
  const inputId = useId()
  const fileInput = useRef<HTMLInputElement>(null)
  const [dragging, setDragging] = useState(false)
  const [search, setSearch] = useState('')
  const [debounced, setDebounced] = useState('')
  const [status, setStatus] = useState('')
  const [page, setPage] = useState(1)
  const [toDelete, setToDelete] = useState<DocumentItem | null>(null)
  const [rejected, setRejected] = useState<{ filename: string; message: string }[]>([])

  useEffect(() => {
    const t = setTimeout(() => {
      setDebounced(search.trim())
      setPage(1)
    }, 300)
    return () => clearTimeout(t)
  }, [search])

  const docs = useDocumentsQuery(ws, debounced, status, page)

  const upload = useMutation({
    mutationFn: (files: File[]) => {
      const form = new FormData()
      files.forEach((f) => form.append('files', f))
      return api.upload<{ results: UploadResult[] }>(`/workspaces/${ws}/documents`, form)
    },
    onSuccess: ({ results }) => {
      const bad = results.filter((r) => !r.accepted).map((r) => ({ filename: r.filename, message: r.error?.message ?? 'Rejected' }))
      setRejected(bad)
      const ok = results.length - bad.length
      if (ok > 0) toast.success(`${ok} ${ok === 1 ? 'file' : 'files'} uploaded. Processing has started.`)
      if (ws) void qc.invalidateQueries({ queryKey: keys.documentsAll(ws) })
    },
    onError: (e) => toast.error(errorMessage(e, 'Upload failed.')),
  })

  const remove = useMutation({
    mutationFn: (id: string) => api.del(`/workspaces/${ws}/documents/${id}`),
    onSuccess: () => {
      toast.success('Document deleted.')
      setToDelete(null)
      if (ws) void qc.invalidateQueries({ queryKey: keys.documentsAll(ws) })
    },
    onError: (e) => toast.error(errorMessage(e, 'Could not delete the document.')),
  })

  const reindex = useMutation({
    mutationFn: (id: string) => api.post(`/workspaces/${ws}/documents/${id}/reindex`),
    onSuccess: () => {
      toast.info('Reprocessing started.')
      if (ws) void qc.invalidateQueries({ queryKey: keys.documentsAll(ws) })
    },
    onError: (e) => toast.error(errorMessage(e, 'Could not restart processing.')),
  })

  const handleFiles = (list: FileList | File[] | null) => {
    const files = Array.from(list ?? [])
    if (files.length === 0 || !ws) return
    const bad = files.filter((f) => !validExtension(f.name)).map((f) => ({ filename: f.name, message: 'Unsupported type. Use PDF, TXT or DOCX.' }))
    const good = files.filter((f) => validExtension(f.name))
    setRejected(bad)
    if (good.length > 0) upload.mutate(good)
  }

  const onDrop = (e: DragEvent) => {
    e.preventDefault()
    setDragging(false)
    handleFiles(e.dataTransfer.files)
  }

  if (!workspace) {
    return (
      <div className="p-6">
        <EmptyState title="No workspace yet" description="Create a workspace in Settings to start adding documents." />
      </div>
    )
  }

  const data = docs.data
  const totalPages = data ? Math.max(1, Math.ceil(data.total / data.page_size)) : 1
  const filtering = debounced !== '' || status !== ''

  return (
    <div className="mx-auto max-w-5xl space-y-6 p-4 sm:p-6">
      <PageHeader title="Knowledge Base" description={`Documents the assistant can cite in ${workspace.name}.`} />

      <div
        onDragOver={(e) => {
          e.preventDefault()
          setDragging(true)
        }}
        onDragLeave={() => setDragging(false)}
        onDrop={onDrop}
        className={cn(
          'flex flex-col items-center gap-2 rounded-xl border-2 border-dashed px-6 py-8 text-center transition-colors',
          dragging ? 'border-accent-fg bg-accent-soft' : 'border-line bg-surface',
        )}
      >
        <FileUp className="h-6 w-6 text-accent-fg" aria-hidden />
        <p className="text-sm font-medium">Drag and drop files here</p>
        <p className="text-xs text-muted">PDF, TXT or DOCX. Text is extracted and indexed for this workspace only.</p>
        <input
          id={inputId}
          ref={fileInput}
          type="file"
          multiple
          accept={ALLOWED_EXTENSIONS.join(',')}
          className="sr-only"
          aria-label="Choose files to upload"
          onChange={(e) => {
            handleFiles(e.target.files)
            e.target.value = ''
          }}
        />
        <Button variant="primary" loading={upload.isPending} onClick={() => fileInput.current?.click()}>
          Choose files
        </Button>
      </div>

      {rejected.length > 0 && (
        <div role="alert" className="rounded-lg border border-danger/30 bg-danger-soft p-3 text-sm text-danger">
          <p className="flex items-center gap-2 font-medium">
            <AlertCircle className="h-4 w-4" aria-hidden /> Some files were not uploaded
          </p>
          <ul className="mt-1 list-disc pl-6">
            {rejected.map((r, i) => (
              <li key={`${r.filename}-${i}`}>
                {r.filename}: {r.message}
              </li>
            ))}
          </ul>
        </div>
      )}

      <Card>
        <div className="flex flex-col gap-3 border-b border-line p-3 sm:flex-row sm:items-center">
          <div className="relative flex-1">
            <Search className="pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-muted" aria-hidden />
            <input
              type="search"
              aria-label="Search documents"
              placeholder="Search by filename"
              value={search}
              onChange={(e) => setSearch(e.target.value)}
              className="h-9 w-full rounded-lg border border-line bg-surface pl-9 pr-3 text-sm focus-visible:outline-2 focus-visible:outline-accent-fg"
            />
          </div>
          <select
            aria-label="Filter by status"
            value={status}
            onChange={(e) => {
              setStatus(e.target.value)
              setPage(1)
            }}
            className="h-9 rounded-lg border border-line bg-surface px-3 text-sm focus-visible:outline-2 focus-visible:outline-accent-fg"
          >
            <option value="">All statuses</option>
            {(['ready', 'failed', 'uploaded', 'extracting', 'chunking', 'embedding', 'indexing'] as DocumentStatus[]).map((s) => (
              <option key={s} value={s}>
                {STATUS_LABEL[s]}
              </option>
            ))}
          </select>
        </div>

        {docs.isLoading ? (
          <div className="space-y-2 p-4">
            {[0, 1, 2].map((i) => (
              <Skeleton key={i} className="h-10 w-full" />
            ))}
          </div>
        ) : docs.error ? (
          <ErrorState title="Could not load documents" message={errorMessage(docs.error)} onRetry={() => void docs.refetch()} />
        ) : data && data.items.length === 0 ? (
          <EmptyState
            icon={<FileText className="h-6 w-6" />}
            title={filtering ? 'No documents match' : 'No documents yet'}
            description={filtering ? 'Try a different search or filter.' : 'Upload a document to give the assistant something to answer from.'}
          />
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-left text-sm">
              <caption className="sr-only">Documents in this workspace</caption>
              <thead className="border-b border-line text-xs text-muted">
                <tr>
                  <th scope="col" className="px-4 py-2 font-medium">Name</th>
                  <th scope="col" className="px-4 py-2 font-medium">Status</th>
                  <th scope="col" className="hidden px-4 py-2 font-medium sm:table-cell">Size</th>
                  <th scope="col" className="hidden px-4 py-2 font-medium md:table-cell">Chunks</th>
                  <th scope="col" className="hidden px-4 py-2 font-medium md:table-cell">Added</th>
                  <th scope="col" className="px-4 py-2 text-right font-medium">Actions</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-line">
                {data?.items.map((d) => (
                  <tr key={d.id}>
                    <td className="max-w-[16rem] px-4 py-3">
                      <span className="block truncate font-medium">{d.filename}</span>
                      <span className="text-xs uppercase text-muted">{d.file_type}</span>
                      {d.status === 'failed' && d.error_summary && <span className="mt-0.5 block text-xs text-danger">{d.error_summary}</span>}
                    </td>
                    <td className="px-4 py-3">
                      <StatusBadge doc={d} />
                    </td>
                    <td className="hidden px-4 py-3 text-muted sm:table-cell">{formatBytes(d.size_bytes)}</td>
                    <td className="hidden px-4 py-3 text-muted md:table-cell">{d.status === 'ready' ? d.chunk_count : '—'}</td>
                    <td className="hidden px-4 py-3 text-muted md:table-cell">{formatRelative(d.created_at)}</td>
                    <td className="px-4 py-3">
                      <div className="flex justify-end gap-1">
                        {d.status === 'failed' && (
                          <Button size="icon" variant="ghost" aria-label={`Retry processing ${d.filename}`} onClick={() => reindex.mutate(d.id)}>
                            <RefreshCw className="h-4 w-4" />
                          </Button>
                        )}
                        <Button
                          size="icon"
                          variant="ghost"
                          aria-label={`Delete ${d.filename}`}
                          disabled={d.status === 'deleting'}
                          onClick={() => setToDelete(d)}
                        >
                          <Trash2 className="h-4 w-4" />
                        </Button>
                      </div>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}

        {data && data.total > data.page_size && (
          <div className="flex items-center justify-between border-t border-line px-4 py-2 text-sm">
            <span className="text-muted">
              Page {page} of {totalPages}
            </span>
            <div className="flex gap-2">
              <Button size="sm" disabled={page <= 1} onClick={() => setPage((p) => p - 1)}>
                Previous
              </Button>
              <Button size="sm" disabled={page >= totalPages} onClick={() => setPage((p) => p + 1)}>
                Next
              </Button>
            </div>
          </div>
        )}
      </Card>

      <ConfirmDialog
        open={toDelete !== null}
        onOpenChange={(o) => !o && setToDelete(null)}
        title="Delete this document?"
        description={`"${toDelete?.filename ?? ''}" and its indexed content will be permanently removed. Past answers that cited it keep their text but the source can no longer be opened.`}
        confirmLabel="Delete"
        loading={remove.isPending}
        onConfirm={() => {
          if (toDelete) remove.mutate(toDelete.id)
        }}
      />
    </div>
  )
}