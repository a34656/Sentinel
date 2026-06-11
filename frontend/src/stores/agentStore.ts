/**
 * agentStore.ts — Zustand store. SSE event types match server.py exactly:
 *   { type: "init",     incident_id }
 *   { type: "step",     current_worker, step_log, confidence_score,
 *                       bayesian_beliefs, bayesian_entropy, bayesian_top_cause,
 *                       root_cause, notion_page_url, awaiting_human_approval,
 *                       fix_blocked_reason, final_report_path }
 *   { type: "complete", incident_id, root_cause, notion_page_url }
 *   { type: "killed" }
 *   { type: "error",    message }
 */

import { create } from 'zustand'

export type InvestigationStatus = 'idle' | 'running' | 'complete' | 'killed' | 'error'

export interface FeedRow {
  id:      number
  ts:      string
  worker:  string
  message: string
  type:    'info' | 'success' | 'error' | 'warn'
}

export interface IncidentSummary {
  incident_id: string
  prompt:      string
  status:      string
  confidence:  number
  root_cause:  string | null
  notion_url:  string | null
  started_at:  string
}

export interface AgentState {
  status:           InvestigationStatus
  incidentId:       string | null
  currentWorker:    string
  startedAt:        Date | null
  feedRows:         FeedRow[]
  confidenceScore:  number
  bayesianBeliefs:  Record<string, number>
  bayesianEntropy:  number
  bayesianTopCause: string | null
  rootCause:        string | null
  notionUrl:        string | null
  finalReportPath:  string | null
  awaitingApproval: boolean
  blockedReason:    string | null
  history:          IncidentSummary[]
  historyLoading:   boolean
  _abort:           AbortController | null

  startInvestigation: (prompt: string) => Promise<void>
  killInvestigation:  () => void
  approveAction:      () => void
  reset:              () => void
  loadHistory:        () => Promise<void>
}

let rowId = 0
function ts() { return new Date().toLocaleTimeString('en-GB', { hour12: false }) }
function row(worker: string, msg: string, type: FeedRow['type'] = 'info'): FeedRow {
  return { id: ++rowId, ts: ts(), worker, message: msg, type }
}
function rowType(worker: string, msg: string): FeedRow['type'] {
  if (worker === 'policy_guard')                         return 'error'
  if (msg.includes('✅') || msg.includes('succeeded'))  return 'success'
  if (msg.includes('❌') || msg.includes('failed'))     return 'error'
  if (msg.includes('⚠') || msg.includes('warn'))        return 'warn'
  if (worker === 'engineer' || worker === 'report_generator') return 'success'
  return 'info'
}

const BLANK = {
  status: 'idle' as InvestigationStatus,
  incidentId: null, currentWorker: '', startedAt: null,
  feedRows: [], confidenceScore: 0, bayesianBeliefs: {},
  bayesianEntropy: 0, bayesianTopCause: null,
  rootCause: null, notionUrl: null, finalReportPath: null,
  awaitingApproval: false, blockedReason: null,
  historyLoading: false, _abort: null,
}

export const useAgentStore = create<AgentState>((set, get) => ({
  ...BLANK,
  history: [],

  startInvestigation: async (prompt: string) => {
    get()._abort?.abort()
    const abort = new AbortController()
    set({
      ...BLANK,
      history:   get().history,
      status:    'running',
      startedAt: new Date(),
      _abort:    abort,
      feedRows:  [row('system', `▶ "${prompt.slice(0, 90)}${prompt.length > 90 ? '…' : ''}"`)],
    })

    console.debug('[Genesis] Starting investigation:', prompt.slice(0, 80))

    try {
      const res = await fetch('/api/incident', {
        method:  'POST',
        headers: { 'Content-Type': 'application/json' },
        body:    JSON.stringify({ prompt }),
        signal:  abort.signal,
      })

      console.debug('[Genesis] Fetch response:', res.status, res.statusText)

      if (!res.ok || !res.body) {
        console.error('[Genesis] HTTP error — backend returned', res.status)
        set(s => ({ status: 'error', feedRows: [...s.feedRows, row('system', `HTTP ${res.status} — is the backend running on port 8000?`, 'error')] }))
        return
      }

      const reader  = res.body.getReader()
      const decoder = new TextDecoder()
      let   buf     = ''

      console.debug('[Genesis] SSE stream opened, reading chunks…')

      while (true) {
        const { done, value } = await reader.read()
        if (done) {
          console.debug('[Genesis] SSE stream closed (done=true)')
          break
        }
        const chunk = decoder.decode(value, { stream: true })
        console.debug('[Genesis] SSE raw chunk:', chunk)
        buf += chunk
        const lines = buf.split('\n')
        buf = lines.pop() ?? ''
        for (const line of lines) {
          if (!line.startsWith('data: ')) continue
          try {
            const parsed = JSON.parse(line.slice(6))
            console.debug('[Genesis] SSE parsed event:', parsed)
            processEvent(parsed, set, get)
          } catch (parseErr) {
            console.warn('[Genesis] SSE parse error on line:', line, parseErr)
          }
        }
      }

      console.debug('[Genesis] Stream complete')
    } catch (err: unknown) {
      if (err instanceof Error && err.name === 'AbortError') {
        console.debug('[Genesis] Stream aborted by user (kill/reset)')
        return
      }
      const msg = err instanceof Error ? err.message : String(err)
      console.error('[Genesis] Fetch/stream error:', msg)
      const isConnRefused = msg.includes('fetch') || msg.includes('connect') || msg.includes('network')
      set(s => ({
        status:   'error',
        feedRows: [...s.feedRows, row('system',
          isConnRefused
            ? '❌ Cannot connect to backend. Start it: cd genesis && uvicorn api.server:app --reload --port 8000'
            : `❌ ${msg}`,
          'error'
        )],
      }))
    }
  },

  killInvestigation: () => {
    const { incidentId, _abort } = get()
    _abort?.abort()
    if (incidentId) fetch(`/api/incident/${incidentId}/kill`, { method: 'POST' }).catch(() => {})
    set(s => ({
      status:   'killed',
      _abort:   null,
      feedRows: [...s.feedRows, row('system', '■ Kill signal sent', 'warn')],
    }))
  },

  approveAction: () => {
    const { incidentId } = get()
    if (incidentId) fetch(`/api/incident/${incidentId}/approve`, { method: 'POST' }).catch(() => {})
    set({ awaitingApproval: false, blockedReason: null })
  },

  reset: () => {
    get()._abort?.abort()
    set({ ...BLANK, history: get().history })
  },

  loadHistory: async () => {
    set({ historyLoading: true })
    try {
      const res = await fetch('/api/incidents?limit=20')
      if (res.ok) {
        const d = await res.json()
        set({ history: d.incidents ?? [] })
      }
    } catch { /* backend offline is fine */ }
    finally { set({ historyLoading: false }) }
  },
}))

// ── SSE event processor ───────────────────────────────────────────────────────
type SetFn = (s: Partial<AgentState> | ((s: AgentState) => Partial<AgentState>)) => void
type GetFn = () => AgentState

function processEvent(ev: Record<string, unknown>, set: SetFn, get: GetFn) {
  switch (ev.type) {

    case 'init':
      set({ incidentId: ev.incident_id as string })
      break

    case 'step': {
      const worker   = (ev.current_worker as string) ?? 'unknown'
      const logs     = (ev.step_log      as string[]) ?? []
      const newRows  = logs.map(msg => row(worker, msg, rowType(worker, msg)))

      // UEBA: policy_guard blocked something
      const isBlocked = (ev.awaiting_human_approval as boolean) === true

      set((s: AgentState) => ({
        currentWorker:    worker || s.currentWorker,
        confidenceScore:  (ev.confidence_score  as number)            ?? s.confidenceScore,
        bayesianBeliefs:  Object.keys((ev.bayesian_beliefs as object) ?? {}).length > 0
                            ? ev.bayesian_beliefs as Record<string, number>
                            : s.bayesianBeliefs,
        bayesianEntropy:  (ev.bayesian_entropy   as number)  ?? s.bayesianEntropy,
        bayesianTopCause: (ev.bayesian_top_cause as string)  ?? s.bayesianTopCause,
        // Accumulate root_cause + notion_url as they arrive in steps
        rootCause:        (ev.root_cause    as string | null) ?? s.rootCause,
        notionUrl:        (ev.notion_page_url as string | null) ?? s.notionUrl,
        finalReportPath:  (ev.final_report_path as string | null) ?? s.finalReportPath,
        awaitingApproval: isBlocked,
        blockedReason:    isBlocked
          ? ((ev.fix_blocked_reason as string) ?? s.blockedReason)
          : s.blockedReason,
        feedRows: newRows.length > 0 ? [...s.feedRows, ...newRows] : s.feedRows,
      }))
      break
    }

    case 'complete':
      set((s: AgentState) => ({
        status:    'complete',
        // complete event also carries root_cause + notion_page_url from server
        rootCause: (ev.root_cause      as string | null) ?? s.rootCause,
        notionUrl: (ev.notion_page_url as string | null) ?? s.notionUrl,
        feedRows:  [...s.feedRows, row('system', '✅ Investigation complete', 'success')],
      }))
      // Refresh history after a new one completes
      setTimeout(() => get().loadHistory(), 1000)
      break

    case 'killed':
      set((s: AgentState) => ({
        status:   'killed',
        feedRows: [...s.feedRows, row('system', '■ Investigation killed', 'warn')],
      }))
      break

    case 'error':
      set((s: AgentState) => ({
        status:   'error',
        feedRows: [...s.feedRows, row('system', `❌ ${(ev.message as string) ?? 'Unknown error'}`, 'error')],
      }))
      break
  }
}
