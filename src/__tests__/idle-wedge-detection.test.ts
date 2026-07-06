import { describe, expect, it } from 'vitest'
import { decideIdleWedgeAction } from '../web/channel-monitor.js'

// Root cause of the 2026-07-05 7.5h undetected freeze:
// - stuck-tool-call-watcher: "idle prompt, skip" (correct for its scope)
// - keepalive-stale shortcut: "plugin alive, skip" (over-broad)
// Together they produced a "all healthy" signal while the TUI had stopped
// processing prompts. An IDLE session + live plugin + 45+ min stale keepalive
// is the idle-wedge fingerprint -- the scheduled keepalive task (~6min cycle)
// WOULD have freshened the file if the TUI were processing prompts.

const STALE_18 = 18 * 60 * 1000
const STALE_45 = 45 * 60 * 1000
const GRACE_15 = 15 * 60 * 1000

const BASE = {
  pluginAlive: true,
  stalenessThresholdMs: STALE_18,
  idleWedgeThresholdMs: STALE_45,
  respawnGraceMs: GRACE_15,
  msSinceLastRespawn: null,
}

describe('decideIdleWedgeAction: idle-wedge detection via keepalive + plugin-alive', () => {
  it('skips when plugin is not alive (normal staleness path handles it)', () => {
    expect(decideIdleWedgeAction({ ...BASE, pluginAlive: false, keepaliveAgeMs: 60 * 60 * 1000, paneState: 'idle' })).toBe('skip')
  })

  it('skips when keepalive is fresh (under normal threshold)', () => {
    expect(decideIdleWedgeAction({ ...BASE, keepaliveAgeMs: 10 * 60 * 1000, paneState: 'idle' })).toBe('skip')
  })

  it('skips when keepalive is null (file not yet written)', () => {
    expect(decideIdleWedgeAction({ ...BASE, keepaliveAgeMs: null, paneState: 'idle' })).toBe('skip')
  })

  it('skips when pane is busy even if keepalive is very stale (long turn)', () => {
    expect(decideIdleWedgeAction({ ...BASE, keepaliveAgeMs: 60 * 60 * 1000, paneState: 'busy' })).toBe('skip')
  })

  it('skips when pane is typing even if keepalive is very stale', () => {
    expect(decideIdleWedgeAction({ ...BASE, keepaliveAgeMs: 60 * 60 * 1000, paneState: 'typing' })).toBe('skip')
  })

  it('skips when inside post-respawn grace window', () => {
    expect(decideIdleWedgeAction({ ...BASE, keepaliveAgeMs: 60 * 60 * 1000, paneState: 'idle', msSinceLastRespawn: 5 * 60 * 1000 })).toBe('skip')
  })

  it('warns when stale 18-45min + idle (developing, not yet confirmed)', () => {
    expect(decideIdleWedgeAction({ ...BASE, keepaliveAgeMs: 25 * 60 * 1000, paneState: 'idle' })).toBe('warn')
    expect(decideIdleWedgeAction({ ...BASE, keepaliveAgeMs: STALE_45 - 1, paneState: 'idle' })).toBe('warn')
  })

  it('warns for unknown pane state in the developing range', () => {
    expect(decideIdleWedgeAction({ ...BASE, keepaliveAgeMs: 30 * 60 * 1000, paneState: 'unknown' })).toBe('warn')
  })

  it('warns for null pane state in the developing range (fail-open)', () => {
    expect(decideIdleWedgeAction({ ...BASE, keepaliveAgeMs: 30 * 60 * 1000, paneState: null })).toBe('warn')
  })

  it('respawns when stale >= 45min + idle (confirmed idle-wedge)', () => {
    expect(decideIdleWedgeAction({ ...BASE, keepaliveAgeMs: STALE_45, paneState: 'idle' })).toBe('respawn')
    expect(decideIdleWedgeAction({ ...BASE, keepaliveAgeMs: 7.5 * 60 * 60 * 1000, paneState: 'idle' })).toBe('respawn')
  })

  it('respawns for the exact 7.5h freeze scenario (idle + live plugin + 7.5h stale)', () => {
    const freezeScenario = {
      pluginAlive: true,
      keepaliveAgeMs: 7.5 * 60 * 60 * 1000,
      stalenessThresholdMs: STALE_18,
      idleWedgeThresholdMs: STALE_45,
      paneState: 'idle' as const,
      msSinceLastRespawn: null,
      respawnGraceMs: GRACE_15,
    }
    expect(decideIdleWedgeAction(freezeScenario)).toBe('respawn')
  })

  it('respawns outside grace window even after a recent respawn when wedge is confirmed', () => {
    expect(decideIdleWedgeAction({ ...BASE, keepaliveAgeMs: STALE_45, paneState: 'idle', msSinceLastRespawn: GRACE_15 + 1 })).toBe('respawn')
  })
})
