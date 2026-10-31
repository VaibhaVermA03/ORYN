import { useMutation, useQueryClient } from '@tanstack/react-query'
import { useState, type ReactNode } from 'react'
import { z } from 'zod'
import { Button } from '@/components/ui/Button'
import { Modal } from '@/components/ui/Dialog'
import { Alert, Badge, Card, EmptyState, ErrorState, PageHeader, Skeleton } from '@/components/ui/feedback'
import { useToast } from '@/components/ui/Toast'
import { api, errorMessage } from '@/lib/api'
import { keys, useAnalyticsQuery, useEvalRunQuery, useEvalRunsQuery } from '@/lib/queries'
import type { EvalRun, EvaluationMetrics } from '@/lib/types'
import { formatDateTime, formatMs, formatPercent } from '@/lib/utils'
import { useAuth } from '@/auth/AuthContext'
import { useWorkspace } from '@/workspace/WorkspaceContext'

function Stat({ label, value, hint }: { label: string; value: ReactNode; hint?: string }) {
  return (
    <Card className="p-4">
      <p className="text-xs font-medium text-muted">{label}</p>
      <p className="mt-1 text-2xl font-semibold tabular-nums">{value}</p>
      {hint && <p className="mt-0.5 text-xs text-muted">{hint}</p>}
    </Card>
  )
}

function DailyChart({ data }: { data: { date: string; queries: number }[] }) {
  const max = Math.max(1, ...data.map((d) => d.queries))
  const total = data.reduce((a, d) => a + d.queries, 0)
  if (total === 0) return <p className="py-8 text-center text-sm text-muted">No questions asked in this period yet.</p>
  return (
    <figure>
      <div className="flex h-32 items-end gap-1" role="img" aria-label={`Questions per day over the last ${data.length} days, ${total} in total`}>
        {data.map((d) => (
          <div key={d.date} className="group relative flex-1" title={`${d.date}: ${d.queries}`}>
            <div className="w-full rounded-t bg-accent-fg/80 group-hover:bg-accent-fg" style={{ height: `${Math.max(2, (d.queries / max) * 100)}%` }} />
          </div>
        ))}
      </div>
      <figcaption className="mt-2 flex justify-between text-xs text-muted">
        <span>{data[0]?.date}</span>
        <span>{data[data.length - 1]?.date}</span>
      </figcaption>
      <table className="sr-only">
        <caption>Questions per day</caption>
        <tbody>
          {data.map((d) => (
            <tr key={d.date}>
              <th scope="row">{d.date}</th>
              <td>{d.queries}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </figure>
  )
}

const METRIC_LABELS: [keyof EvaluationMetrics, string, 'pct' | 'ms'][] = [
  ['context_precision', 'Context precision', 'pct'],
  ['context_recall', 'Context recall', 'pct'],
  ['hit_rate', 'Hit rate', 'pct'],
  ['faithfulness', 'Faithfulness (LLM-judged)', 'pct'],
  ['answer_relevance', 'Answer relevance (LLM-judged)', 'pct'],
  ['answer_correctness', 'Answer correctness (LLM-judged)', 'pct'],
  ['total_ms', 'Total latency', 'ms'],
]

export function MetricsTable({ metrics }: { metrics: EvaluationMetrics }) {
  const rows = METRIC_LABELS.filter(([k]) => metrics[k] !== undefined)
  if (rows.length === 0) return <p className="text-sm text-muted">No metrics were computed for this run.</p>
  return (
    <table className="w-full text-sm">
      <thead className="text-left text-xs text-muted">
        <tr>
          <th scope="col" className="py-1 font-medium">Metric</th>
          <th scope="col" className="py-1 font-medium">Mean</th>
          <th scope="col" className="py-1 font-medium">Samples (n)</th>
        </tr>
      </thead>
      <tbody className="divide-y divide-line">
        {rows.map(([k, label, kind]) => {
          const m = metrics[k] as { mean: number | null; n: number }
          return (
            <tr key={k}>
              <th scope="row" className="py-1.5 pr-3 text-left font-normal">{label}</th>
              <td className="py-1.5 tabular-nums">{m.mean == null ? 'n/a' : kind === 'pct' ? formatPercent(m.mean, 1) : formatMs(m.mean)}</td>
              <td className="py-1.5 tabular-nums text-muted">{m.n}</td>
            </tr>
          )
        })}
      </tbody>
    </table>
  )
}

const datasetSchema = z.object({
  name: z.string().min(1).max(200),
  samples: z
    .array(
      z.object({
        question: z.string().min(1).max(2000),
        ground_truth: z.string().max(4000).nullish(),
        relevant_documents: z.array(z.string()).max(20).nullish(),
      }),
    )
    .min(1, 'Add at least one sample')
    .max(50, 'At most 50 samples per run'),
})

const EXAMPLE = JSON.stringify(
  { name: 'My test set', samples: [{ question: 'What is the refund window?', ground_truth: '30 days', relevant_documents: ['policy.pdf'] }] },
  null,
  2,
)

function RunEvaluation({ ws, onClose }: { ws: string; onClose: () => void }) {
  const [text, setText] = useState(EXAMPLE)
  const [judge, setJudge] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const qc = useQueryClient()
  const toast = useToast()
  const start = useMutation({
    mutationFn: (dataset: unknown) => api.post<EvalRun>(`/workspaces/${ws}/evaluations`, { dataset, judge }),
    onSuccess: () => {
      toast.success('Evaluation started.')
      void qc.invalidateQueries({ queryKey: keys.evalRuns(ws) })
      onClose()
    },
    onError: (e) => setError(errorMessage(e)),
  })
  const submit = () => {
    setError(null)
    let parsed: unknown
    try {
      parsed = JSON.parse(text)
    } catch {
      setError('That is not valid JSON.')
      return
    }
    const r = datasetSchema.safeParse(parsed)
    if (!r.success) {
      setError(r.error.issues[0]?.message ?? 'Invalid dataset.')
      return
    }
    start.mutate(r.data)
  }
  return (
    <div className="space-y-3">
      <p className="text-xs text-muted">
        Provide your own questions. Precision, recall and hit rate need <code>relevant_documents</code> (filenames); correctness needs <code>ground_truth</code>.
      </p>
      <label htmlFor="eval-json" className="sr-only">Evaluation dataset JSON</label>
      <textarea
        id="eval-json"
        value={text}
        onChange={(e) => setText(e.target.value)}
        rows={12}
        spellCheck={false}
        className="w-full rounded-lg border border-line bg-surface p-3 font-mono text-xs focus-visible:outline-2 focus-visible:outline-accent-fg"
      />
      <label className="flex items-center gap-2 text-sm">
        <input type="checkbox" checked={judge} onChange={(e) => setJudge(e.target.checked)} />
        Also run LLM-judged metrics (extra OpenAI calls and cost)
      </label>
      {error && <Alert tone="danger">{error}</Alert>}
      <div className="flex justify-end gap-2">
        <Button onClick={onClose}>Cancel</Button>
        <Button variant="primary" loading={start.isPending} onClick={submit}>
          Start run
        </Button>
      </div>
    </div>
  )
}

function RunDetail({ ws, id }: { ws: string; id: string }) {
  const run = useEvalRunQuery(ws, id)
  if (run.isLoading) return <Skeleton className="h-24 w-full" />
  if (run.error || !run.data) return <ErrorState message={errorMessage(run.error)} onRetry={() => void run.refetch()} />
  const r = run.data
  return (
    <div className="space-y-3 text-sm">
      <p className="text-xs text-muted">{r.disclaimer}</p>
      {r.status === 'failed' && <Alert tone="danger">{r.error_summary ?? 'The run failed.'}</Alert>}
      {r.status === 'running' && <Alert tone="info">Running… this page updates automatically.</Alert>}
      <MetricsTable metrics={r.metrics} />
      {r.metrics._summary && (
        <p className="text-xs text-muted">
          {r.metrics._summary.succeeded} of {r.metrics._summary.samples} samples succeeded, {r.metrics._summary.failed} failed, {r.metrics._summary.abstained} abstained.
        </p>
      )}
      <ul className="divide-y divide-line">
        {r.results.map((x) => (
          <li key={x.id} className="py-2">
            <p className="font-medium">{x.question}</p>
            {x.error ? <p className="text-xs text-danger">{x.error}</p> : <p className="line-clamp-2 text-xs text-muted">{x.answer}</p>}
          </li>
        ))}
      </ul>
    </div>
  )
}

export function AnalyticsPage() {
  const { workspace, canManage } = useWorkspace()
  const { user } = useAuth()
  const ws = workspace?.id
  const allowed = canManage || user?.role === 'admin'
  const a = useAnalyticsQuery(ws, allowed)
  const runs = useEvalRunsQuery(ws, allowed)
  const [runOpen, setRunOpen] = useState(false)
  const [openRun, setOpenRun] = useState<string | null>(null)

  if (!workspace) return <div className="p-6"><EmptyState title="No workspace yet" description="Create a workspace in Settings first." /></div>
  if (!allowed)
    return (
      <div className="p-6">
        <EmptyState title="Analytics is limited to workspace admins" description="Ask an owner or admin of this workspace for access." />
      </div>
    )

  const d = a.data
  return (
    <div className="mx-auto max-w-5xl space-y-6 p-4 sm:p-6">
      <PageHeader title="Analytics" description={`Measured activity in ${workspace.name} over the last ${d?.window_days ?? 30} days.`} />
      {a.isLoading ? (
        <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
          {[0, 1, 2, 3].map((i) => <Skeleton key={i} className="h-24" />)}
        </div>
      ) : a.error || !d ? (
        <ErrorState title="Could not load analytics" message={errorMessage(a.error)} onRetry={() => void a.refetch()} />
      ) : (
        <>
          <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
            <Stat label="Questions (30 days)" value={d.usage.queries_30d} hint={`${d.usage.queries_7d} in the last 7 days`} />
            <Stat label="Active users (30 days)" value={d.usage.active_users_30d} />
            <Stat label="Documents" value={d.documents.total} hint={`${d.documents.indexed_chunks} indexed chunks`} />
            <Stat label="Answer feedback" value={d.feedback.satisfaction == null ? 'No data' : formatPercent(d.feedback.satisfaction)} hint={`${d.feedback.up} helpful, ${d.feedback.down} not helpful`} />
          </div>

          <Card className="p-4">
            <h2 className="mb-3 text-sm font-semibold">Questions per day</h2>
            <DailyChart data={d.usage.daily_queries} />
          </Card>

          <div className="grid gap-4 lg:grid-cols-2">
            <Card className="p-4">
              <h2 className="mb-3 text-sm font-semibold">Latency</h2>
              {d.latency_ms.samples === 0 ? (
                <p className="text-sm text-muted">No completed answers yet.</p>
              ) : (
                <dl className="grid grid-cols-2 gap-y-2 text-sm">
                  <dt className="text-muted">Median (p50)</dt><dd className="tabular-nums">{formatMs(d.latency_ms.p50_total)}</dd>
                  <dt className="text-muted">p95</dt><dd className="tabular-nums">{formatMs(d.latency_ms.p95_total)}</dd>
                  <dt className="text-muted">Avg retrieval</dt><dd className="tabular-nums">{formatMs(d.latency_ms.avg_retrieval)}</dd>
                  <dt className="text-muted">Avg rerank</dt><dd className="tabular-nums">{formatMs(d.latency_ms.avg_rerank)}</dd>
                  <dt className="text-muted">Avg generation</dt><dd className="tabular-nums">{formatMs(d.latency_ms.avg_generation)}</dd>
                  <dt className="text-muted">Samples</dt><dd className="tabular-nums">{d.latency_ms.samples}</dd>
                </dl>
              )}
            </Card>
            <Card className="p-4">
              <h2 className="mb-3 text-sm font-semibold">Reliability</h2>
              <dl className="grid grid-cols-2 gap-y-2 text-sm">
                <dt className="text-muted">Successful</dt><dd className="tabular-nums">{d.reliability.ok}</dd>
                <dt className="text-muted">Errors</dt><dd className="tabular-nums">{d.reliability.errors}</dd>
                <dt className="text-muted">Cancelled</dt><dd className="tabular-nums">{d.reliability.cancelled}</dd>
                <dt className="text-muted">Provider error rate</dt><dd className="tabular-nums">{d.reliability.provider_error_rate == null ? 'n/a' : formatPercent(d.reliability.provider_error_rate, 1)}</dd>
              </dl>
              {Object.keys(d.reliability.by_provider).length > 0 && (
                <p className="mt-2 text-xs text-muted">
                  By provider: {Object.entries(d.reliability.by_provider).map(([k, v]) => `${k} ${v}`).join(', ')}
                </p>
              )}
            </Card>
          </div>

          <Card className="p-4">
            <h2 className="mb-3 text-sm font-semibold">Document processing</h2>
            <div className="flex flex-wrap gap-2">
              {Object.entries(d.documents.by_status).map(([k, v]) => (
                <Badge key={k} tone={k === 'failed' ? 'danger' : k === 'ready' ? 'success' : 'neutral'}>{k}: {v}</Badge>
              ))}
              {d.documents.total === 0 && <p className="text-sm text-muted">No documents uploaded yet.</p>}
            </div>
            {d.documents.recent_failures.length > 0 && (
              <ul className="mt-3 space-y-1 text-sm">
                {d.documents.recent_failures.map((f) => (
                  <li key={f.id}><span className="font-medium">{f.filename}</span> <span className="text-danger">{f.error_summary ?? 'Failed'}</span></li>
                ))}
              </ul>
            )}
          </Card>
        </>
      )}

      <Card className="p-4">
        <div className="mb-3 flex items-center justify-between gap-2">
          <h2 className="text-sm font-semibold">Evaluation runs</h2>
          <Button size="sm" variant="primary" onClick={() => setRunOpen(true)}>New evaluation</Button>
        </div>
        {runs.isLoading ? (
          <Skeleton className="h-16 w-full" />
        ) : runs.error ? (
          <ErrorState message={errorMessage(runs.error)} onRetry={() => void runs.refetch()} />
        ) : (runs.data ?? []).length === 0 ? (
          <p className="text-sm text-muted">No evaluation runs yet. Scores only exist once you run one on your own dataset.</p>
        ) : (
          <ul className="divide-y divide-line">
            {runs.data?.map((r) => (
              <li key={r.id} className="flex items-center justify-between gap-3 py-2 text-sm">
                <span className="min-w-0">
                  <span className="block truncate font-medium">{r.dataset_name}</span>
                  <span className="text-xs text-muted">{formatDateTime(r.created_at)} · {r.sample_count} samples</span>
                </span>
                <span className="flex items-center gap-2">
                  <Badge tone={r.status === 'completed' ? 'success' : r.status === 'failed' ? 'danger' : 'accent'}>{r.status}</Badge>
                  <Button size="sm" onClick={() => setOpenRun(r.id)}>View</Button>
                </span>
              </li>
            ))}
          </ul>
        )}
      </Card>

      {ws && (
        <>
          <Modal open={runOpen} onOpenChange={setRunOpen} title="New evaluation run">
            <RunEvaluation ws={ws} onClose={() => setRunOpen(false)} />
          </Modal>
          <Modal open={openRun !== null} onOpenChange={(o) => !o && setOpenRun(null)} title="Evaluation results" variant="drawer">
            {openRun && <RunDetail ws={ws} id={openRun} />}
          </Modal>
        </>
      )}
    </div>
  )
}