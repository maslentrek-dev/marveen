import { describe, it, expect } from 'vitest'
import { stripGhostSuggestion, paneLooksIdle, detectPaneState } from '../pane-state.js'

const ESC = '\x1b'
const SEP = '─'.repeat(80)
const FOOTER = `  ⏵⏵ bypass permissions on (shift+tab to cycle) · ← for agents`

// Faithful reconstruction of the live `tmux capture-pane -e -p` taken on
// 2026-07-08 06:30 from picard-channels: the input box holds a DIM (SGR-2)
// queued-message line ("Szólj ha Geordi visszajött az első helyzetképpel").
// The readiness path read the pane through a PLAIN `-p` capture, which drops
// the intensity attribute, so this box classified 'typing' -> busy -- for 31
// hours (1888 consecutive busy deferrals), while the recovery layer's
// dim-stripped view saw an empty box and never intervened. Readiness must
// therefore evaluate the SAME dim-stripped view: this fixture pins that.
const DIM_QUEUED_BOX = [
  `⏺ Kész, elindítottam az auditot.`,
  '',
  `${ESC}[38;5;37m${SEP}${ESC}[39m`,
  `${ESC}[39m❯ ${ESC}[2mSzólj ha Geordi visszajött az első helyzetképpel${ESC}[0m`,
  `${ESC}[38;5;37m${SEP}${ESC}[39m`,
  FOOTER,
].join('\n')

// Same box but the text is REAL typed input (normal intensity): readiness
// must keep reading this as NOT idle -- injecting a prompt would clobber it.
const REAL_TYPED_BOX = [
  `⏺ Kész, elindítottam az auditot.`,
  '',
  `${ESC}[38;5;37m${SEP}${ESC}[39m`,
  `${ESC}[39m❯ ${ESC}[38;5;253mfél kész válasz amit valaki gépel${ESC}[39m`,
  `${ESC}[38;5;37m${SEP}${ESC}[39m`,
  FOOTER,
].join('\n')

describe('readiness through the dim-stripped view (2026-07-07 starvation regression)', () => {
  it('a dim queued/ghost line reads IDLE after the strip (schedulable)', () => {
    const stripped = stripGhostSuggestion(DIM_QUEUED_BOX)
    expect(detectPaneState(stripped)).toBe('idle')
    expect(paneLooksIdle(stripped)).toBe(true)
  })

  it('the SAME pane read WITHOUT the strip is what wedged the scheduler (documents the bug)', () => {
    // Simulate the old plain `-p` capture: ANSI gone, dim text kept as normal.
    const plainCapture = DIM_QUEUED_BOX.replace(new RegExp(`${ESC}\\[[0-9;]*m`, 'g'), '')
    expect(detectPaneState(plainCapture)).toBe('typing')
    expect(paneLooksIdle(plainCapture)).toBe(false)
  })

  it('REAL typed input still reads NOT idle through the stripped view', () => {
    const stripped = stripGhostSuggestion(REAL_TYPED_BOX)
    expect(detectPaneState(stripped)).toBe('typing')
    expect(paneLooksIdle(stripped)).toBe(false)
  })
})
