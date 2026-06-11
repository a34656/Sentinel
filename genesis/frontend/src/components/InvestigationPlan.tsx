'use client'

import { useState, useEffect, useRef, useMemo } from 'react'
import { CheckCircle2, XCircle, CircleDot, AlertTriangle } from 'lucide-react'
import { useAgentStore } from '@/stores/agentStore'

interface PlanData {
  plan:   string[]
  script: string
}

function colorize(line: string): React.ReactNode {
  if (line.trim().startsWith('#')) {
    return <span className="text-txt-muted">{line}</span>
  }
  const tokens: React.ReactNode[] = []
  const regex = /(\b(?:import|from|async|await|def|return|if|else|for|in)\b)|(\b(?:True|False|None)\b)|("[^"]*"|'[^']*')|(\b\d+\.?\d*\b)|(\b[a-zA-Z_][\w]*(?=\())/g
  let last = 0, key = 0
  let m: RegExpExecArray | null
  while ((m = regex.exec(line))) {
    if (m.index > last) tokens.push(<span key={key++}>{line.slice(last, m.index)}</span>)
    if      (m[1]) tokens.push(<span key={key++} style={{ color: '#a855f7' }}>{m[0]}</span>)
    else if (m[2]) tokens.push(<span key={key++} style={{ color: '#FFB020' }}>{m[0]}</span>)
    else if (m[3]) tokens.push(<span key={key++} style={{ color: '#00FF88' }}>{m[0]}</span>)
    else if (m[4]) tokens.push(<span key={key++} style={{ color: '#FFB020' }}>{m[0]}</span>)
    else if (m[5]) tokens.push(<span key={key++} style={{ color: '#00D4FF' }}>{m[0]}</span>)
    last = m.index + m[0].length
  }
  if (last < line.length) tokens.push(<span key={key++} className="text-txt-primary">{line.slice(last)}</span>)
  return <>{tokens}</>
}

export function InvestigationPlan() {
  const status  = useAgentStore(s => s.status)

  const [planData,  setPlanData]  = useState<PlanData | null>(null)
  const [loading,   setLoading]   = useState(false)
  const [approved,  setApproved]  = useState(false)
  const [aborted,   setAborted]   = useState(false)

  // Track the prompt we already fetched a plan for — prevents re-fetching
  const fetchedForPrompt = useRef<string | null>(null)

  const activeLineRef = useRef<HTMLDivElement>(null)

  const scriptLines = useMemo(
    () => (planData?.script ?? '').split('\n'),
    [planData?.script]
  )

  // Reset when a new investigation starts (status goes idle → running)
  useEffect(() => {
    if (status === 'idle') {
      setPlanData(null)
      setLoading(false)
      setApproved(false)
      setAborted(false)
      fetchedForPrompt.current = null
    }
  }, [status])

  // Fetch plan ONCE when investigation starts — listen to agentStore for the prompt
  // We hook into startInvestigation by watching feedRows for the first entry that
  // carries the prompt, but the cleanest way is to expose the prompt from the store.
  // Since the store doesn't store the raw prompt, we intercept via a custom hook below.
  // Instead, we expose plan fetching as a function called from page.tsx via a ref — but
  // to keep this self-contained, we watch for status === 'running' and fetch once.
  const hasFetched = useRef(false)

  useEffect(() => {
    if (status !== 'running') return
    if (hasFetched.current) return
    if (loading) return

    hasFetched.current = true
    setLoading(true)

    // Get the prompt from the first feed row's message if available,
    // or just send a generic trigger — the backend will use the active incident context.
    // Actually /api/plan needs { prompt }, so we read it from the store's feedRows
    // which won't have it yet. We'll use a small delay and grab from the store directly.
    const promptFromStore = (() => {
      // The agentStore doesn't persist the raw prompt, but we can read it
      // from the component's parent via a data attribute set on submit.
      // Simplest fix: read window.__genesisPrompt set by page.tsx on submit.
      return (window as unknown as Record<string, string>).__genesisPrompt ?? ''
    })()

    fetch('/api/plan', {
      method:  'POST',
      headers: { 'Content-Type': 'application/json' },
      body:    JSON.stringify({ prompt: promptFromStore }),
    })
      .then(r => r.ok ? r.json() : null)
      .then(d => {
        if (d) setPlanData({ plan: d.plan ?? [], script: d.script ?? '' })
      })
      .catch(() => {/* backend offline — silent fail */})
      .finally(() => setLoading(false))
  }, [status, loading])

  // Reset hasFetched when status goes back to idle
  useEffect(() => {
    if (status === 'idle') hasFetched.current = false
  }, [status])

  const isApproved = approved
  const isAborted  = aborted
  const hasPlan    = (planData?.plan.length ?? 0) > 0

  const metaLabel = isApproved ? 'APPROVED' : isAborted ? 'ABORTED' : hasPlan ? 'PENDING APPROVAL' : '—'

  return (
    <div className="flex flex-col h-full bg-bg-surface rounded-xl border border-bg-border overflow-hidden">
      {/* Header */}
      <div className="flex items-center justify-between px-4 py-2.5 border-b border-bg-border shrink-0">
        <div className="flex items-center gap-2">
          <div
            className="w-1.5 h-1.5 rounded-full shrink-0"
            style={{
              background: isApproved ? '#00FF88' : isAborted ? '#FF4444' : hasPlan ? '#FFB020' : '#3A5570',
            }}
          />
          <span className="text-[11px] font-mono text-txt-secondary tracking-widest uppercase">
            {isApproved ? 'Script Execution' : 'Investigation Plan'}
          </span>
        </div>
        <span className="text-[10px] font-mono text-txt-muted uppercase tracking-widest">
          {metaLabel}
        </span>
      </div>

      {/* Body */}
      <div className="flex flex-col flex-1 overflow-hidden">

        {/* Pre-approval: plan list */}
        {!isApproved && !isAborted && (
          <>
            <ol className="flex-1 space-y-1.5 overflow-y-auto px-3 py-2.5">
              {loading ? (
                <div className="flex h-full items-center justify-center gap-2 text-[11px] font-mono text-txt-muted">
                  <CircleDot className="h-3 w-3 animate-pulse" />
                  Generating plan…
                </div>
              ) : !hasPlan ? (
                <div className="flex h-full items-center justify-center text-[11px] font-mono text-txt-muted italic">
                  {status === 'running' ? 'Fetching plan…' : 'Start an investigation to see the plan'}
                </div>
              ) : planData!.plan.map((step, i) => (
                <li key={i} className="flex items-start gap-2.5 rounded-lg border border-bg-border bg-bg-elevated px-3 py-2">
                  <span
                    className="flex h-5 w-5 flex-shrink-0 items-center justify-center rounded text-[10px] font-bold"
                    style={{ background: '#00D4FF12', color: '#00D4FF', border: '1px solid #00D4FF33' }}
                  >
                    {i + 1}
                  </span>
                  <span className="text-[11px] font-mono leading-relaxed text-txt-primary">{step}</span>
                </li>
              ))}
            </ol>

            {hasPlan && (
              <div className="grid grid-cols-2 gap-2 border-t border-bg-border p-2.5 shrink-0">
                <button
                  type="button"
                  onClick={() => setAborted(true)}
                  className="flex items-center justify-center gap-1.5 rounded-lg border py-2 text-[11px] font-mono font-bold uppercase tracking-widest transition hover:opacity-80"
                  style={{ borderColor: '#FF444455', background: '#FF444410', color: '#FF4444' }}
                >
                  <XCircle className="h-3.5 w-3.5" /> Abort
                </button>
                <button
                  type="button"
                  onClick={() => setApproved(true)}
                  className="flex items-center justify-center gap-1.5 rounded-lg border py-2 text-[11px] font-mono font-bold uppercase tracking-widest transition hover:opacity-90"
                  style={{ borderColor: '#00FF8855', background: '#00FF8815', color: '#00FF88' }}
                >
                  <CheckCircle2 className="h-3.5 w-3.5" /> Approve
                </button>
              </div>
            )}
          </>
        )}

        {/* Aborted */}
        {isAborted && (
          <div className="flex flex-1 flex-col items-center justify-center gap-2" style={{ color: '#FF4444' }}>
            <AlertTriangle className="h-6 w-6" />
            <div className="text-[11px] font-mono font-bold uppercase tracking-widest">Aborted</div>
          </div>
        )}

        {/* Approved: script view */}
        {isApproved && (
          <pre className="flex-1 overflow-auto bg-[#060a12] p-0 text-[11px] leading-relaxed">
            <code className="block py-1.5">
              {scriptLines.map((line, i) => (
                <div
                  key={i}
                  ref={i === 0 ? activeLineRef : undefined}
                  className="flex gap-3 px-3 opacity-90 hover:opacity-100"
                >
                  <span className="select-none w-6 text-right tabular-nums font-mono text-txt-muted shrink-0">
                    {String(i + 1).padStart(2, '0')}
                  </span>
                  <span className="flex-1 whitespace-pre font-mono">{colorize(line || ' ')}</span>
                </div>
              ))}
            </code>
          </pre>
        )}

      </div>
    </div>
  )
}
