'use client'

import { useState, useRef } from 'react'
import { Send, RotateCcw, ExternalLink, CheckCircle2 } from 'lucide-react'
import { useAgentStore } from '@/stores/agentStore'
import { AgentFeed }       from '@/components/AgentFeed'
import { BayesianPanel }   from '@/components/BayesianPanel'
import { ConfidenceMeter } from '@/components/ConfidenceMeter'
import { UEBAPanel }       from '@/components/UEBAPanel'
import { KillSwitch }      from '@/components/KillSwitch'
import { IncidentHistory } from '@/components/IncidentHistory'
import { DemoPrompts }     from '@/components/DemoPrompts'
import { BackendStatus }   from '@/components/BackendStatus'

// ── Status dot ────────────────────────────────────────────────────────────────
function StatusDot() {
  const status      = useAgentStore(s => s.status)
  const worker      = useAgentStore(s => s.currentWorker)
  const incidentId  = useAgentStore(s => s.incidentId)

  const cfg = {
    idle:      { color: '#3A5570', label: 'STANDBY',      pulse: false },
    running:   { color: '#00D4FF', label: 'INVESTIGATING', pulse: true  },
    complete:  { color: '#00FF88', label: 'RESOLVED',      pulse: false },
    killed:    { color: '#FFB020', label: 'KILLED',        pulse: false },
    error:     { color: '#FF4444', label: 'ERROR',         pulse: false },
  }[status]

  return (
    <div className="flex items-center gap-3">
      <div className="flex items-center gap-2">
        <div className="w-2 h-2 rounded-full shrink-0"
          style={{
            background: cfg.color,
            boxShadow:  `0 0 6px ${cfg.color}`,
            animation:  cfg.pulse ? 'pulseDot 1.8s ease-in-out infinite' : 'none',
          }} />
        <span className="text-[11px] font-mono font-medium tracking-widest"
          style={{ color: cfg.color }}>
          {cfg.label}
        </span>
      </div>
      {incidentId && (
        <span className="text-[10px] font-mono text-txt-muted">
          {incidentId.slice(0, 8)}
        </span>
      )}
      {status === 'running' && worker && (
        <span className="text-[10px] font-mono text-txt-muted">
          → <span className="text-txt-secondary">{worker.replace(/_/g, ' ')}</span>
        </span>
      )}
    </div>
  )
}

// ── Prompt input ──────────────────────────────────────────────────────────────
function PromptBox() {
  const [value, setValue]   = useState('')
  const start               = useAgentStore(s => s.startInvestigation)
  const status              = useAgentStore(s => s.status)
  const isRunning           = status === 'running'
  const ref                 = useRef<HTMLTextAreaElement>(null)

  const submit = () => {
    const t = value.trim()
    if (!t || isRunning) return
    start(t)
    setValue('')
  }

  const loadPrompt = (p: string) => {
    setValue(p)
    ref.current?.focus()
  }

  return (
    <div className="flex flex-col gap-3">
      <div
        className="relative rounded-xl border transition-all duration-300"
        style={{
          borderColor: value ? '#00D4FF44' : '#1A2535',
          background:  '#0C1018',
          boxShadow:   value ? '0 0 0 1px #00D4FF11, 0 0 24px #00D4FF07' : 'none',
        }}
      >
        <textarea
          ref={ref}
          value={value}
          onChange={e => setValue(e.target.value)}
          onKeyDown={e => { if (e.key === 'Enter' && (e.metaKey || e.ctrlKey)) submit() }}
          disabled={isRunning}
          rows={3}
          placeholder="Describe the incident… (⌘↵ to submit)"
          className="w-full bg-transparent px-4 pt-3.5 pb-11 text-sm font-mono
                     text-txt-primary placeholder:text-txt-muted resize-none outline-none leading-relaxed"
        />
        <div className="absolute bottom-0 inset-x-0 flex items-center justify-between px-3 py-2 border-t border-bg-border">
          <span className="text-[10px] font-mono text-txt-muted">
            {value.length > 0 ? `${value.length} chars · ⌘↵` : 'Describe the incident'}
          </span>
          <button
            onClick={submit}
            disabled={!value.trim() || isRunning}
            className="flex items-center gap-1.5 px-4 py-1.5 rounded-lg text-[11px] font-mono font-medium
                       transition-all duration-200 disabled:opacity-30 disabled:cursor-not-allowed"
            style={{
              background: value.trim() ? '#00D4FF12' : 'transparent',
              border:     `1px solid ${value.trim() ? '#00D4FF44' : '#1A2535'}`,
              color:      value.trim() ? '#00D4FF' : '#3A5570',
              boxShadow:  value.trim() ? '0 0 10px #00D4FF18' : 'none',
            }}
          >
            <Send size={11} />
            Investigate
          </button>
        </div>
      </div>

      <DemoPrompts onSelect={loadPrompt} disabled={isRunning} />
    </div>
  )
}

// ── Result card ───────────────────────────────────────────────────────────────
function ResultCard() {
  const status    = useAgentStore(s => s.status)
  const rootCause = useAgentStore(s => s.rootCause)
  const notionUrl = useAgentStore(s => s.notionUrl)
  const reset     = useAgentStore(s => s.reset)

  if (status !== 'complete') return null

  return (
    <div className="animate-slide-up rounded-xl border glow-green p-4 flex flex-col gap-3"
      style={{ borderColor: '#00FF8833', background: '#00FF8808' }}>
      <div className="flex items-center gap-2">
        <CheckCircle2 size={13} className="text-green" />
        <span className="text-[11px] font-mono text-green tracking-widest uppercase font-semibold">
          Resolved
        </span>
        <button onClick={reset} className="ml-auto flex items-center gap-1 text-[10px] font-mono
                 text-txt-muted hover:text-txt-secondary transition-colors">
          <RotateCcw size={9} /> New
        </button>
      </div>

      {rootCause && (
        <p className="text-sm font-mono text-txt-primary leading-relaxed">{rootCause}</p>
      )}

      {notionUrl && (
        <a href={notionUrl} target="_blank" rel="noopener noreferrer"
          className="inline-flex items-center gap-1.5 text-[11px] font-mono text-cyan/80
                     hover:text-cyan transition-colors">
          <ExternalLink size={11} />
          View Notion Post-Mortem
        </a>
      )}
    </div>
  )
}

// ── Main page ─────────────────────────────────────────────────────────────────
export default function DashboardPage() {
  const reset  = useAgentStore(s => s.reset)
  const status = useAgentStore(s => s.status)

  return (
    <div className="min-h-screen bg-bg-base flex flex-col overflow-hidden relative">
      {/* Grid background */}
      <div className="fixed inset-0 bg-grid pointer-events-none opacity-100" />
      {/* Ambient glow */}
      <div className="fixed top-0 left-1/3 w-[500px] h-[300px] pointer-events-none"
        style={{ background: 'radial-gradient(ellipse, #00D4FF06 0%, transparent 70%)', transform: 'translateY(-40%)' }} />

      {/* ── Top bar ─────────────────────────────────────────────────────────── */}
      <header className="relative z-10 flex items-center justify-between px-6 py-3.5 border-b border-bg-border bg-bg-base/90 backdrop-blur-sm shrink-0">
        <div className="flex items-center gap-4">
          {/* Logo */}
          <div className="flex items-center gap-2.5">
            <div className="w-7 h-7 relative">
              <div className="absolute inset-0 rounded border border-cyan/30"
                style={{ boxShadow: '0 0 10px #00D4FF22' }} />
              <div className="absolute inset-0 flex items-center justify-center">
                <span className="font-display text-xs font-bold text-cyan"
                  style={{ textShadow: '0 0 8px #00D4FF' }}>G</span>
              </div>
            </div>
            <div>
              <div className="font-display text-[15px] font-bold text-txt-primary tracking-tight leading-none">GENESIS</div>
              <div className="text-[8px] font-mono text-txt-muted tracking-widest leading-none mt-0.5">AUTONOMOUS SRE</div>
            </div>
          </div>

          <div className="w-px h-5 bg-bg-border" />
          <StatusDot />
        </div>

        <div className="flex items-center gap-3">
          <KillSwitch />
          {(status === 'complete' || status === 'killed' || status === 'error') && (
            <button onClick={reset}
              className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-[11px] font-mono
                         border border-bg-border text-txt-muted hover:border-bg-borderHover
                         hover:text-txt-secondary transition-all">
              <RotateCcw size={11} />
              New Investigation
            </button>
          )}
          <BackendStatus />
          <a href="http://localhost:8000/docs" target="_blank" rel="noopener noreferrer"
            className="text-[11px] font-mono text-txt-muted hover:text-txt-secondary transition-colors">
            API ↗
          </a>
        </div>
      </header>

      {/* ── Body ────────────────────────────────────────────────────────────── */}
      <div className="flex flex-1 overflow-hidden relative z-10">

        {/* LEFT — Input + Confidence + Bayesian */}
        <aside className="w-72 shrink-0 border-r border-bg-border bg-bg-surface/40 flex flex-col overflow-y-auto">
          <div className="flex flex-col gap-4 p-4">
            <PromptBox />
            <ConfidenceMeter />
            <div className="flex-1 min-h-[280px]">
              <BayesianPanel />
            </div>
          </div>
        </aside>

        {/* CENTER — Feed + UEBA + Result */}
        <main className="flex-1 flex flex-col overflow-hidden min-w-0">
          {/* UEBA alert — floats at top when active */}
          <div className="px-4 pt-4 empty:hidden">
            <UEBAPanel />
          </div>

          {/* Result card */}
          <div className="px-4 pt-3 empty:hidden">
            <ResultCard />
          </div>

          {/* Live feed — fills space */}
          <div className="flex-1 overflow-hidden p-4 pt-3">
            <AgentFeed />
          </div>

          {/* History — bottom */}
          <div className="px-4 pb-4 shrink-0">
            <IncidentHistory />
          </div>
        </main>

      </div>
    </div>
  )
}
