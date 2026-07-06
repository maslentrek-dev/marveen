import { describe, expect, it } from 'vitest'
import { readFileSync } from 'node:fs'
import { join } from 'node:path'
import {
  decideScheduleGiveupRestart,
  SCHEDULE_GIVEUP_RESTART_THRESHOLD,
  SCHEDULE_GIVEUP_WINDOW_MS,
} from '../web/schedule-runner.js'

// When a session is persistently wedged the scheduled resubmit will giveup
// repeatedly. Tracking consecutive giveups and escalating to a hard restart
// after THRESHOLD within WINDOW_MS caps the silence at ~a few minutes instead
// of waiting for the next manual intervention.

describe('decideScheduleGiveupRestart: consecutive giveup -> hard restart', () => {
  const T0 = 1_000_000_000_000
  const threshold = SCHEDULE_GIVEUP_RESTART_THRESHOLD
  const window = SCHEDULE_GIVEUP_WINDOW_MS

  it('does not restart on first giveup', () => {
    const r = decideScheduleGiveupRestart(0, T0, T0 + 1000, threshold, window)
    expect(r.shouldRestart).toBe(false)
    expect(r.nextCount).toBe(1)
  })

  it('does not restart below the threshold', () => {
    let state = { count: 0, windowStartMs: T0 }
    for (let i = 0; i < threshold - 1; i++) {
      const r = decideScheduleGiveupRestart(state.count, state.windowStartMs, T0 + (i + 1) * 60_000, threshold, window)
      expect(r.shouldRestart).toBe(false)
      state = { count: r.nextCount, windowStartMs: r.nextWindowStartMs }
    }
  })

  it('fires restart when threshold is reached within the window', () => {
    let r = decideScheduleGiveupRestart(0, T0, T0, threshold, window)
    for (let i = 1; i < threshold; i++) {
      r = decideScheduleGiveupRestart(r.nextCount, r.nextWindowStartMs, T0 + i * 60_000, threshold, window)
    }
    expect(r.shouldRestart).toBe(true)
    expect(r.nextCount).toBe(threshold)
  })

  it('resets the count when giveups are separated by more than the window', () => {
    const r1 = decideScheduleGiveupRestart(0, T0, T0, threshold, window)
    expect(r1.nextCount).toBe(1)
    const r2 = decideScheduleGiveupRestart(r1.nextCount, r1.nextWindowStartMs, T0 + window + 1, threshold, window)
    expect(r2.nextCount).toBe(1)
    expect(r2.shouldRestart).toBe(false)
  })

  it('exported constants satisfy the contract (threshold >= 2, window >= 5min)', () => {
    expect(SCHEDULE_GIVEUP_RESTART_THRESHOLD).toBeGreaterThanOrEqual(2)
    expect(SCHEDULE_GIVEUP_WINDOW_MS).toBeGreaterThanOrEqual(5 * 60 * 1000)
  })
})

describe('schedule-runner: giveup restart wiring in source', () => {
  const SRC = readFileSync(join(__dirname, '../web/schedule-runner.ts'), 'utf-8')

  it('imports hardRestartMarveenChannels and sendAlert from channel-monitor', () => {
    expect(SRC).toMatch(/hardRestartMarveenChannels/)
    expect(SRC).toMatch(/sendAlert/)
    expect(SRC).toMatch(/from '\.\/channel-monitor\.js'/)
  })

  it('calls hardRestartMarveenChannels when consecutive giveup threshold is reached', () => {
    expect(SRC).toMatch(/d\.shouldRestart/)
    expect(SRC).toMatch(/hardRestartMarveenChannels\(\)/)
  })

  it('resets giveup state on successful submit (action === none path)', () => {
    const noneBlock = SRC.slice(SRC.indexOf("action === 'none'"), SRC.indexOf("action === 'giveup'"))
    expect(noneBlock).toMatch(/scheduleGiveupState\.delete\(session\)/)
  })

  it('sends a Telegram alert before hard restart', () => {
    expect(SRC).toMatch(/sendAlert\(/)
    expect(SRC).toMatch(/hard restart/)
  })
})
