import { screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it } from 'vitest'
import { App } from '@/App'
import type { DocumentItem } from '@/lib/types'
import { json, mockApi, renderApp, signedInRoutes } from './helpers'

const doc = (over: Partial<DocumentItem>): DocumentItem => ({
  id: 'd1', workspace_id: 'w1', filename: 'policy.pdf', title: 'policy', file_type: 'pdf', size_bytes: 2048, status: 'ready',
  error_summary: null, page_count: 3, chunk_count: 7, attempts: 1, created_at: '2026-01-01T00:00:00Z', updated_at: '2026-01-01T00:00:00Z', indexed_at: null, ...over,
})
const page = (items: DocumentItem[]) => json({ items, total: items.length, page: 1, page_size: 25 })

describe('Knowledge Base', () => {
  it('shows a real empty state when there are no documents', async () => {
    mockApi(signedInRoutes({ 'GET /workspaces/w1/documents': () => page([]) }))
    renderApp(<App />, '/app/knowledge')
    expect(await screen.findByText('No documents yet')).toBeInTheDocument()
  })

  it('lists documents with status, and shows processing progress and failure reasons', async () => {
    mockApi(signedInRoutes({
      'GET /workspaces/w1/documents': () => page([
        doc({}),
        doc({ id: 'd2', filename: 'big.docx', file_type: 'docx', status: 'embedding', chunk_count: 0 }),
        doc({ id: 'd3', filename: 'scan.pdf', status: 'failed', error_summary: 'No extractable text found' }),
      ]),
    }))
    renderApp(<App />, '/app/knowledge')
    expect(await screen.findByText('policy.pdf')).toBeInTheDocument()
    expect(screen.getByRole('progressbar', { name: 'Processing big.docx' })).toHaveAttribute('aria-valuetext', 'Embedding')
    expect(screen.getByText('No extractable text found')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Retry processing scan.pdf' })).toBeInTheDocument()
  })

  it('shows an error state with retry when the list cannot load', async () => {
    mockApi(signedInRoutes({ 'GET /workspaces/w1/documents': () => json({ error: { code: 'boom', message: 'Server exploded' } }, 500) }))
    renderApp(<App />, '/app/knowledge')
    expect(await screen.findByText('Could not load documents')).toBeInTheDocument()
  })

  it('uploads selected files and reports per-file rejections', async () => {
    const { calls } = mockApi(signedInRoutes({
      'GET /workspaces/w1/documents': () => page([]),
      'POST /workspaces/w1/documents': () => json({ results: [
        { filename: 'ok.txt', accepted: true, document: doc({ id: 'n', filename: 'ok.txt' }), error: null },
        { filename: 'dup.txt', accepted: false, document: null, error: { code: 'duplicate_document', message: 'This file was already uploaded.' } },
      ] }),
    }))
    renderApp(<App />, '/app/knowledge')
    const input = await screen.findByLabelText('Choose files to upload')
    await userEvent.upload(input, [new File(['a'], 'ok.txt', { type: 'text/plain' }), new File(['a'], 'dup.txt', { type: 'text/plain' })])
    expect(await screen.findByText(/dup\.txt: This file was already uploaded\./)).toBeInTheDocument()
    const post = calls.find((c) => c.method === 'POST' && c.path === '/workspaces/w1/documents')!
    expect(post.body).toBeInstanceOf(FormData)
    expect((post.body as FormData).getAll('files')).toHaveLength(2)
  })

  it('rejects unsupported file types in the browser without calling the API', async () => {
    const { calls } = mockApi(signedInRoutes({ 'GET /workspaces/w1/documents': () => page([]) }))
    renderApp(<App />, '/app/knowledge')
    const input = await screen.findByLabelText('Choose files to upload')
    // userEvent filters by `accept`; fire the change directly to exercise our own validation.
    const { fireEvent } = await import('@testing-library/react')
    fireEvent.change(input, { target: { files: [new File(['x'], 'run.exe')] } })
    expect(await screen.findByText(/run\.exe: Unsupported type/)).toBeInTheDocument()
    expect(calls.some((c) => c.method === 'POST' && c.path === '/workspaces/w1/documents')).toBe(false)
  })

  it('asks for confirmation before deleting, then deletes', async () => {
    let items = [doc({})]
    const { calls } = mockApi(signedInRoutes({
      'GET /workspaces/w1/documents': () => page(items),
      'DELETE /workspaces/w1/documents/d1': () => {
        items = []
        return json(null, 204)
      },
    }))
    renderApp(<App />, '/app/knowledge')
    await userEvent.click(await screen.findByRole('button', { name: 'Delete policy.pdf' }))
    const dialog = await screen.findByRole('alertdialog')
    expect(calls.some((c) => c.method === 'DELETE')).toBe(false)
    await userEvent.click(within(dialog).getByRole('button', { name: 'Delete' }))
    await waitFor(() => expect(calls.some((c) => c.method === 'DELETE')).toBe(true))
    expect(await screen.findByText('No documents yet')).toBeInTheDocument()
  })
})
