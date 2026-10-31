import { Modal } from '@/components/ui/Dialog'
import { Skeleton } from '@/components/ui/feedback'
import { errorMessage } from '@/lib/api'
import { useChunkQuery } from '@/lib/queries'
import type { Source } from '@/lib/types'

/** Shows the full cited passage. Falls back to the stored excerpt if the document was deleted. */
export function SourceDrawer({ workspaceId, source, onClose }: { workspaceId: string; source: Source | null; onClose: () => void }) {
  const chunk = useChunkQuery(workspaceId, source?.chunk_id ?? null)
  return (
    <Modal
      open={source !== null}
      onOpenChange={(o) => !o && onClose()}
      variant="drawer"
      title={source ? `[${source.index}] ${source.filename}` : 'Source'}
      description={source?.page_number ? `Page ${source.page_number}` : undefined}
    >
      {source && (
        <div className="space-y-3 text-sm">
          {chunk.isLoading ? (
            <div className="space-y-2">
              <Skeleton className="h-4 w-full" />
              <Skeleton className="h-4 w-5/6" />
              <Skeleton className="h-4 w-4/6" />
            </div>
          ) : chunk.data ? (
            <p className="whitespace-pre-wrap leading-relaxed">{chunk.data.text}</p>
          ) : (
            <>
              <p className="rounded-lg bg-warn-soft px-3 py-2 text-xs text-warn">
                The full passage is unavailable{chunk.error ? ` (${errorMessage(chunk.error)})` : ''}. The document may have been deleted or re-indexed. Showing the saved excerpt.
              </p>
              <p className="whitespace-pre-wrap leading-relaxed">
                {source.excerpt}
                {source.truncated ? '…' : ''}
              </p>
            </>
          )}
        </div>
      )}
    </Modal>
  )
}
