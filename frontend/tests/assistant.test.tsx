import { screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it } from 'vitest'
import { App } from '@/App'
import { Markdown } from '@/components/chat/Markdown'
import type { ChatMessage, Source } from '@/lib/types'
import { ev, json, mockApi, renderApp, signedInRoutes, sseResponse } from './helpers'
import { render } from '@testing-library/react'

const SRC: Source = { index: 1, chunk_id: 'c1', document_id: 'd1', filename: 'policy.pdf', page_number: 4, excerpt: 'Refunds within 30 days.', truncated: false, score: 0.9 }
const empty = { items: [], total: 0, page: 1, page_size: 100 }
const msg = (over: Partial<ChatMessage>): ChatMessage => ({ id: 'm', role: 'assistant', content: '', status: 'complete', sources: [], insufficient_context: false, error_code: null, feedback: null, created_at: '2026-01-01T00:00:00Z', ...over })

const streamBody = [
  ev('status', { stage: 'started', conversation_id: 'conv1', message_id: 'm2', user_message_id: 'm1' }),
  ev('status', { stage: 'retrieving' }),
  ev('sources', { sources: [SRC], insufficient_context: false }),
  ev('status', { stage: 'generating' }),
  // split mid-event to exercise chunk boundaries
  'event: token\ndata: {"text":"Refunds take **30 ',
  'days** [1]."}\n\n',
  ev('done', { message_id: 'm2', conversation_id: 'conv1', insufficient_context: false, timings_ms: {} }),
]

describe('Assistant', () => {
  it('shows suggestions in the empty state and streams an answer with a citation', async () => {
    const { calls } = mockApi(signedInRoutes({
      'GET /workspaces/w1/conversations': () => json(empty),
      'POST /workspaces/w1/chat/stream': () => sseResponse(streamBody),
      'GET /workspaces/w1/conversations/conv1': () => json({
        conversation: { id: 'conv1', title: 'Refund policy', created_at: 'x', updated_at: 'x' },
        messages: [msg({ id: 'm1', role: 'user', content: 'What is the refund window?' }), msg({ id: 'm2', content: 'Refunds take **30 days** [1].', sources: [SRC] })],
      }),
    }))
    renderApp(<App />, '/app/assistant')
    await userEvent.type(await screen.findByLabelText('Ask a question'), 'What is the refund window?{Enter}')
    expect(await screen.findByText('30 days')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: /Open source 1: policy\.pdf, page 4/ })).toBeInTheDocument()
    const post = calls.find((c) => c.path === '/workspaces/w1/chat/stream')!
    expect(post.body).toMatchObject({ message: 'What is the refund window?', conversation_id: null })
    expect(post.headers.get('Authorization')).toBe('Bearer t')
  })

  it('opens the full source passage in a drawer', async () => {
    mockApi(signedInRoutes({
      'GET /workspaces/w1/conversations': () => json({ ...empty, items: [{ id: 'conv1', title: 'Refund policy', created_at: 'x', updated_at: '2026-01-01T00:00:00Z' }] }),
      'GET /workspaces/w1/conversations/conv1': () => json({
        conversation: { id: 'conv1', title: 'Refund policy', created_at: 'x', updated_at: 'x' },
        messages: [msg({ content: 'Answer [1]', sources: [SRC] })],
      }),
      'GET /workspaces/w1/chunks/c1': () => json({ chunk_id: 'c1', document_id: 'd1', filename: 'policy.pdf', page_number: 4, chunk_index: 2, text: 'FULL PASSAGE: refunds within 30 days of purchase.' }),
    }))
    renderApp(<App />, '/app/assistant?c=conv1')
    await userEvent.click(await screen.findByRole('button', { name: /Open source 1/ }))
    expect(await screen.findByText(/FULL PASSAGE/)).toBeInTheDocument()
    expect(screen.getByRole('dialog')).toHaveAccessibleName(/policy\.pdf/)
  })

  it('falls back to the saved excerpt when the source chunk is gone', async () => {
    mockApi(signedInRoutes({
      'GET /workspaces/w1/conversations': () => json(empty),
      'GET /workspaces/w1/conversations/conv1': () => json({
        conversation: { id: 'conv1', title: 't', created_at: 'x', updated_at: 'x' },
        messages: [msg({ content: 'Answer [1]', sources: [SRC] })],
      }),
      'GET /workspaces/w1/chunks/c1': () => json({ error: { code: 'not_found', message: 'Not found' } }, 404),
    }))
    renderApp(<App />, '/app/assistant?c=conv1')
    await userEvent.click(await screen.findByRole('button', { name: /Open source 1/ }))
    expect(await screen.findByText(/full passage is unavailable/i)).toBeInTheDocument()
    expect(screen.getByText(/Refunds within 30 days\./)).toBeInTheDocument()
  })

  it('sends feedback, and clicking the same rating again removes it', async () => {
    let fb: 1 | null = null
    const { calls } = mockApi(signedInRoutes({
      'GET /workspaces/w1/conversations': () => json(empty),
      'GET /workspaces/w1/conversations/conv1': () => json({
        conversation: { id: 'conv1', title: 't', created_at: 'x', updated_at: 'x' },
        messages: [msg({ id: 'm9', content: 'Hello there', feedback: fb })],
      }),
      'PUT /workspaces/w1/messages/m9/feedback': () => { fb = 1; return json(null, 204) },
      'DELETE /workspaces/w1/messages/m9/feedback': () => { fb = null; return json(null, 204) },
    }))
    renderApp(<App />, '/app/assistant?c=conv1')
    const up = await screen.findByRole('button', { name: 'Helpful' })
    await userEvent.click(up)
    await waitFor(() => expect(screen.getByRole('button', { name: 'Helpful' })).toHaveAttribute('aria-pressed', 'true'))
    expect(calls.find((c) => c.method === 'PUT')!.body).toEqual({ rating: 1 })
    await userEvent.click(screen.getByRole('button', { name: 'Helpful' }))
    await waitFor(() => expect(calls.some((c) => c.method === 'DELETE')).toBe(true))
  })

  it('renders a stream error as a failed message with retry, not as an answer', async () => {
    mockApi(signedInRoutes({
      'GET /workspaces/w1/conversations': () => json(empty),
      'POST /workspaces/w1/chat/stream': () => sseResponse([
        ev('status', { stage: 'started', conversation_id: 'c2', message_id: 'mm', user_message_id: 'uu' }),
        ev('error', { code: 'provider_unavailable', message: 'x', retryable: true }),
      ]),
      'GET /workspaces/w1/conversations/c2': () => json({
        conversation: { id: 'c2', title: 't', created_at: 'x', updated_at: 'x' },
        messages: [msg({ id: 'uu', role: 'user', content: 'Q' }), msg({ id: 'mm', status: 'failed', error_code: 'provider_unavailable' })],
      }),
    }))
    renderApp(<App />, '/app/assistant')
    await userEvent.type(await screen.findByLabelText('Ask a question'), 'Q{Enter}')
    expect(await screen.findByText(/temporarily unavailable/i)).toBeInTheDocument()
    expect(screen.getByRole('button', { name: /Retry/ })).toBeInTheDocument()
  })

  it('lists conversation history and offers rename and delete', async () => {
    mockApi(signedInRoutes({
      'GET /workspaces/w1/conversations': () => json({ ...empty, items: [{ id: 'c1', title: 'Quarterly numbers', created_at: 'x', updated_at: '2026-01-01T00:00:00Z' }] }),
    }))
    renderApp(<App />, '/app/assistant')
    expect(await screen.findByText('Quarterly numbers')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Rename Quarterly numbers' })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Delete Quarterly numbers' })).toBeInTheDocument()
  })
})

describe('Markdown safety', () => {
  it('does not render raw HTML, scripts, javascript: links or images from model output', () => {
    const { container } = render(<Markdown text={'<script>alert(1)</script><img src=x onerror=alert(1)>\n\n[bad](javascript:alert(1)) and [ok](https://example.com)\n\n![pic](https://evil.example/x.png)'} />)
    expect(container.querySelector('script')).toBeNull()
    expect(container.querySelector('img')).toBeNull()
    const links = Array.from(container.querySelectorAll('a'))
    expect(links.map((a) => a.getAttribute('href'))).toEqual(['https://example.com'])
    expect(links[0]).toHaveAttribute('rel', expect.stringContaining('noopener'))
  })
})
