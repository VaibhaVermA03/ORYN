import { act, render, screen } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { SLOW_START_NOTICE_MS, StartupScreen } from '@/components/ui/feedback'

describe('startup screen', () => {
  beforeEach(() => vi.useFakeTimers())
  afterEach(() => vi.useRealTimers())

  it('shows only the spinner at first, then explains the free-plan cold start if the wait is long', () => {
    render(<StartupScreen />)
    expect(screen.getByRole('status', { name: 'Checking your session' })).toBeInTheDocument()
    expect(screen.queryByText(/free plan/i)).not.toBeInTheDocument()

    act(() => {
      vi.advanceTimersByTime(SLOW_START_NOTICE_MS + 50)
    })
    expect(screen.getByText(/Waking up the server/i)).toBeInTheDocument()
    expect(screen.getByText(/Render.s free plan/i)).toBeInTheDocument()
  })

  it('never shows the notice if it is unmounted before the delay (fast, warm server)', () => {
    const { unmount } = render(<StartupScreen />)
    unmount()
    act(() => {
      vi.advanceTimersByTime(SLOW_START_NOTICE_MS * 2)
    })
    expect(screen.queryByText(/free plan/i)).not.toBeInTheDocument()
  })
})