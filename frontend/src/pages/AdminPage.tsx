import { useState } from 'react'
import { Button } from '@/components/ui/Button'
import { Card, EmptyState, ErrorState, PageHeader, Skeleton } from '@/components/ui/feedback'
import { errorMessage } from '@/lib/api'
import { useAdminOverviewQuery, useAuditQuery } from '@/lib/queries'
import { formatDateTime, formatPercent } from '@/lib/utils'

export function AdminPage() {
  const overview = useAdminOverviewQuery()
  const [page, setPage] = useState(1)
  const audit = useAuditQuery('platform', page)
  const o = overview.data
  const totalPages = audit.data ? Math.max(1, Math.ceil(audit.data.total / audit.data.page_size)) : 1
  return (
    <div className="mx-auto max-w-5xl space-y-6 p-4 sm:p-6">
      <PageHeader title="Platform admin" description="Aggregate counts and audit events. No document content or per-user data is shown here." />
      {overview.isLoading ? (
        <Skeleton className="h-24 w-full" />
      ) : overview.error || !o ? (
        <ErrorState message={errorMessage(overview.error)} onRetry={() => void overview.refetch()} />
      ) : (
        <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
          {[
            ['Users', o.users],
            ['Workspaces', o.workspaces],
            ['Documents', o.documents.total],
            ['Questions (30 days)', o.queries_30d],
          ].map(([label, value]) => (
            <Card key={label as string} className="p-4">
              <p className="text-xs font-medium text-muted">{label}</p>
              <p className="mt-1 text-2xl font-semibold tabular-nums">{value}</p>
            </Card>
          ))}
          <Card className="p-4 sm:col-span-2 lg:col-span-4">
            <p className="text-xs font-medium text-muted">Error rate (30 days)</p>
            <p className="mt-1 text-2xl font-semibold tabular-nums">{o.error_rate_30d == null ? 'No data' : formatPercent(o.error_rate_30d, 1)}</p>
          </Card>
        </div>
      )}

      <Card>
        <h2 className="border-b border-line p-4 text-sm font-semibold">Audit events</h2>
        {audit.isLoading ? (
          <Skeleton className="m-4 h-24" />
        ) : audit.error ? (
          <ErrorState message={errorMessage(audit.error)} onRetry={() => void audit.refetch()} />
        ) : audit.data && audit.data.items.length === 0 ? (
          <EmptyState title="No audit events yet" />
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-left text-sm">
              <caption className="sr-only">Audit events</caption>
              <thead className="border-b border-line text-xs text-muted">
                <tr>
                  <th scope="col" className="px-4 py-2 font-medium">When</th>
                  <th scope="col" className="px-4 py-2 font-medium">Action</th>
                  <th scope="col" className="px-4 py-2 font-medium">Actor</th>
                  <th scope="col" className="hidden px-4 py-2 font-medium md:table-cell">Target</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-line">
                {audit.data?.items.map((e) => (
                  <tr key={e.id}>
                    <td className="whitespace-nowrap px-4 py-2 text-muted">{formatDateTime(e.created_at)}</td>
                    <td className="px-4 py-2 font-mono text-xs">{e.action}</td>
                    <td className="px-4 py-2">{e.actor_email ?? 'system'}</td>
                    <td className="hidden px-4 py-2 text-muted md:table-cell">{e.target_type ?? ''}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
        {audit.data && audit.data.total > audit.data.page_size && (
          <div className="flex items-center justify-between border-t border-line px-4 py-2 text-sm">
            <span className="text-muted">Page {page} of {totalPages}</span>
            <div className="flex gap-2">
              <Button size="sm" disabled={page <= 1} onClick={() => setPage((p) => p - 1)}>Previous</Button>
              <Button size="sm" disabled={page >= totalPages} onClick={() => setPage((p) => p + 1)}>Next</Button>
            </div>
          </div>
        )}
      </Card>
    </div>
  )
}
