import { describe, expect, it } from 'vitest'
import { SseParser, toChatEvent } from '@/lib/sse'

const wire = 'event: token\ndata: {"text":"Hel"}\n\nevent: token\ndata: {"text":"lo"}\n\n: keep-alive\n\nevent: done\ndata: {"message_id":"m"}\n\n'

describe('SseParser', () => {
  it('parses whole input', () => {
    const evs = new SseParser().push(wire)
    expect(evs.map((e) => e.event)).toEqual(['token', 'token', 'done'])
  })

  it('gives identical results for every possible 2-way split of the input', () => {
    const expected = new SseParser().push(wire)
    for (let i = 0; i <= wire.length; i++) {
      const p = new SseParser()
      expect([...p.push(wire.slice(0, i)), ...p.push(wire.slice(i))]).toEqual(expected)
    }
  })

  it('handles one-character chunks and CRLF line endings', () => {
    const crlf = wire.replace(/\n/g, '\r\n')
    const p = new SseParser()
    const out = [...crlf].flatMap((c) => p.push(c))
    expect(out.map((e) => e.event)).toEqual(['token', 'token', 'done'])
    expect(JSON.parse(out[0]!.data)).toEqual({ text: 'Hel' })
  })

  it('joins multi-line data and ignores unknown fields', () => {
    const out = new SseParser().push('id: 7\nevent: x\ndata: a\ndata: b\n\n')
    expect(out).toEqual([{ event: 'x', data: 'a\nb' }])
  })

  it('discards an unterminated trailing event on flush', () => {
    const p = new SseParser()
    expect(p.push('event: token\ndata: {"text":"x"}\n')).toEqual([])
    expect(p.flush()).toEqual([])
  })

  it('toChatEvent ignores unknown events and invalid JSON', () => {
    expect(toChatEvent({ event: 'weird', data: '{}' })).toBeNull()
    expect(toChatEvent({ event: 'token', data: '{oops' })).toBeNull()
    expect(toChatEvent({ event: 'token', data: '{"text":"a"}' })).toEqual({ event: 'token', data: { text: 'a' } })
  })
})
