import { API_PREFIX, ApiError, getAccessToken, refreshSession } from './api'
import type { ChatEvent } from './types'

export interface RawSseEvent {
  event: string
  data: string
}

/** Incremental Server-Sent Events parser (WHATWG EventSource rules). It accepts arbitrary string
 *  chunks, including ones that split a line, a `\r\n` pair, or an event in the middle. */
export class SseParser {
  private buffer = ''
  private eventName = ''
  private dataLines: string[] = []

  push(chunk: string): RawSseEvent[] {
    this.buffer += chunk
    const out: RawSseEvent[] = []
    for (;;) {
      const m = /\r\n|\n|\r/.exec(this.buffer)
      if (!m) break
      // A lone "\r" at the very end may be the first half of "\r\n": wait for the next chunk.
      if (m[0] === '\r' && m.index === this.buffer.length - 1) break
      const line = this.buffer.slice(0, m.index)
      this.buffer = this.buffer.slice(m.index + m[0].length)
      const ev = this.consumeLine(line)
      if (ev) out.push(ev)
    }
    return out
  }

  /** Call when the stream ends. An event still pending without its blank line is discarded, as
   *  the SSE specification requires. */
  flush(): RawSseEvent[] {
    const out: RawSseEvent[] = []
    if (this.buffer.length > 0) {
      const ev = this.consumeLine(this.buffer.replace(/\r$/, ''))
      this.buffer = ''
      if (ev) out.push(ev)
    }
    this.eventName = ''
    this.dataLines = []
    return out
  }

  private consumeLine(line: string): RawSseEvent | null {
    if (line === '') {
      if (this.dataLines.length === 0) {
        this.eventName = ''
        return null
      }
      const ev = { event: this.eventName || 'message', data: this.dataLines.join('\n') }
      this.eventName = ''
      this.dataLines = []
      return ev
    }
    if (line.startsWith(':')) return null // comment / keep-alive
    const colon = line.indexOf(':')
    const field = colon === -1 ? line : line.slice(0, colon)
    let value = colon === -1 ? '' : line.slice(colon + 1)
    if (value.startsWith(' ')) value = value.slice(1)
    if (field === 'event') this.eventName = value
    else if (field === 'data') this.dataLines.push(value)
    return null
  }
}

const KNOWN = new Set(['status', 'sources', 'token', 'done', 'error'])

export function toChatEvent(raw: RawSseEvent): ChatEvent | null {
  if (!KNOWN.has(raw.event)) return null
  try {
    return { event: raw.event, data: JSON.parse(raw.data) } as ChatEvent
  } catch {
    return null
  }
}

export interface StreamChatArgs {
  workspaceId: string
  message: string
  conversationId?: string | null
  signal?: AbortSignal
  onEvent: (e: ChatEvent) => void
}

/** POST to the chat endpoint and dispatch each SSE event. Resolves once a terminal `done` or
 *  `error` event arrived. Aborting via `signal` resolves quietly. A connection that ends without a
 *  terminal event rejects with `stream_interrupted`. */
export async function streamChat({ workspaceId, message, conversationId, signal, onEvent }: StreamChatArgs): Promise<void> {
  const url = `${API_PREFIX}/workspaces/${workspaceId}/chat/stream`
  const send = () =>
    fetch(url, {
      method: 'POST',
      signal,
      headers: {
        'Content-Type': 'application/json',
        Accept: 'text/event-stream',
        ...(getAccessToken() ? { Authorization: `Bearer ${getAccessToken()}` } : {}),
      },
      body: JSON.stringify({ message, conversation_id: conversationId ?? null }),
    })

  let res: Response
  try {
    res = await send()
    if (res.status === 401) {
      if (!(await refreshSession())) throw new ApiError(401, 'unauthenticated', 'Your session has expired. Please sign in again.')
      res = await send()
    }
  } catch (e) {
    if (e instanceof DOMException && e.name === 'AbortError') return
    if (e instanceof ApiError) throw e
    throw new ApiError(0, 'network_error', 'Cannot reach the server. Check your connection and try again.')
  }

  if (!res.ok) {
    let code = 'http_error'
    let msg = `Request failed (${res.status}).`
    try {
      const body = (await res.json()) as { error?: { code?: string; message?: string } }
      code = body.error?.code ?? code
      msg = body.error?.message ?? msg
    } catch {
      /* ignore */
    }
    throw new ApiError(res.status, code, msg)
  }
  if (!res.body) throw new ApiError(0, 'stream_unsupported', 'This browser does not support streaming responses.')

  const reader = res.body.getReader()
  const decoder = new TextDecoder('utf-8')
  const parser = new SseParser()
  let terminal = false
  const dispatch = (events: RawSseEvent[]) => {
    for (const raw of events) {
      const ev = toChatEvent(raw)
      if (!ev) continue
      if (ev.event === 'done' || ev.event === 'error') terminal = true
      onEvent(ev)
    }
  }

  try {
    for (;;) {
      const { done, value } = await reader.read()
      if (done) break
      dispatch(parser.push(decoder.decode(value, { stream: true })))
    }
    dispatch(parser.push(decoder.decode()))
    dispatch(parser.flush())
  } catch (e) {
    if (e instanceof DOMException && e.name === 'AbortError') return
    throw new ApiError(0, 'stream_interrupted', 'The connection was interrupted before the answer finished.')
  } finally {
    reader.releaseLock?.()
  }
  if (!terminal && !signal?.aborted) {
    throw new ApiError(0, 'stream_interrupted', 'The connection was interrupted before the answer finished.')
  }
}
