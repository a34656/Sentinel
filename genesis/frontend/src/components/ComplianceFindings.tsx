'use client'

import { useState, useEffect } from 'react'
import { AlertTriangle, CheckCircle2, CircleDot } from 'lucide-react'
import { useAgentStore } from '@/stores/agentStore'

type FindingState = 'idle' | 'violation' | 'clean'

interface Finding {
  key:   string
  label: string
  state: FindingState
  count: number
}

const INITIAL_FINDINGS: Finding[] = [
  { key: 'iam',        label: 'IAM & Access Control', state: 'idle', count: 0 },
  { key: 'data',       label: 'Data Protection',      state: 'idle', count: 0 },
  { key: 'network',    label: 'Network Egress',        state: 'idle', count: 0 },
  { key: 'logging',    label: 'Logging & Audit',       state: 'idle', count: 0 },
  { key: 'encryption', label: 'Encryption at Rest',    state: 'idle', count: 0 },
]

// Keywords from feed rows that map to compliance categories
const KEY_TERMS: Record<string, string> = {
  iam:        'IAM',
  data:       'S3',
  network:    'egress',
  logging:    'log',
  encryption: 'KMS',
}

export function ComplianceFindings() {
  const feedRows = useAgentStore(s => s.feedRows)
  const status   = useAgentStore(s => s.status)
  const [findings, setFindings] = useState<Finding[]>(INITIAL_FINDINGS)

  // Derive findings from feed rows
  useEffect(() => {
    if (status === 'idle') {
      setFindings(INITIAL_FINDINGS)
      return
    }
    setFindings(prev => prev.map(f => {
      const term = KEY_TERMS[f.key]
      const matches = feedRows.filter(r =>
        r.message.toLowerCase().includes(term.toLowerCase())
      )
      if (matches.length === 0) return { ...f, state: 'idle', count: 0 }
      const hasViolation = matches.some(r => r.type === 'error' || r.type === 'warn')
      return {
        ...f,
        state: hasViolation ? 'violation' : 'clean',
        count: hasViolation ? matches.filter(r => r.type === 'error' || r.type === 'warn').length : 0,
      }
    }))
  }, [feedRows, status])

  const totalViolations = findings.reduce((s, f) => s + f.count, 0)
  const violationCats   = findings.filter(f => f.state === 'violation').length

  return (
    <div className="flex flex-col h-full bg-bg-surface rounded-xl border border-bg-border overflow-hidden">
      {/* Header */}
      <div className="flex items-center justify-between px-4 py-2.5 border-b border-bg-border shrink-0">
        <div className="flex items-center gap-2">
          <div
            className="w-1.5 h-1.5 rounded-full shrink-0"
            style={{
              background: violationCats > 0 ? '#FF4444' : '#3A5570',
              boxShadow:  violationCats > 0 ? '0 0 6px #FF4444' : 'none',
            }}
          />
          <span className="text-[11px] font-mono text-txt-secondary tracking-widest uppercase">
            Compliance Findings
          </span>
        </div>
        <span className="text-[10px] font-mono text-txt-muted tabular-nums">
          {totalViolations} violations · {violationCats}/5 categories
        </span>
      </div>

      {/* Grid */}
      <div className="flex flex-col flex-1 overflow-hidden p-3">
        <div className="grid flex-1 grid-cols-2 gap-2 sm:grid-cols-3">
          {findings.map(f => {
            const meta =
              f.state === 'violation'
                ? { ring: '#FF444433', bg: 'rgba(255,68,68,0.06)', text: '#FF4444', label: 'VIOLATION', Icon: AlertTriangle, glow: '0 0 16px rgba(255,68,68,0.2)' }
                : f.state === 'clean'
                  ? { ring: '#00FF8833', bg: 'rgba(0,255,136,0.05)', text: '#00FF88', label: 'CLEAN', Icon: CheckCircle2, glow: 'none' }
                  : { ring: '#1A2535',   bg: 'transparent',          text: '#3A5570', label: 'PENDING', Icon: CircleDot, glow: 'none' }

            const Icon = meta.Icon
            return (
              <div
                key={f.key}
                className="genesis-slide-up flex flex-col justify-between border rounded-lg p-3 transition-colors"
                style={{ borderColor: meta.ring, background: meta.bg, boxShadow: meta.glow }}
              >
                <div className="flex items-start justify-between">
                  <Icon className="h-4 w-4 shrink-0" style={{ color: meta.text }} />
                  {f.count > 0 && (
                    <span
                      className="border px-1.5 py-0.5 text-[10px] font-mono font-bold tabular-nums rounded"
                      style={{ borderColor: '#FF444660', background: '#FF44441A', color: '#FF4444' }}
                    >
                      ×{f.count}
                    </span>
                  )}
                </div>
                <div className="mt-2">
                  <div className="text-[11px] font-mono font-semibold text-txt-primary">{f.label}</div>
                  <div className="mt-0.5 text-[9px] font-mono uppercase tracking-widest" style={{ color: meta.text }}>
                    {meta.label}
                  </div>
                </div>
              </div>
            )
          })}
        </div>

        {/* Summary footer */}
        <div className="mt-3 flex items-center justify-between border-t border-bg-border pt-3 shrink-0">
          <span className="text-[10px] font-mono uppercase tracking-widest text-txt-muted">Summary</span>
          <span className="text-[12px] font-mono text-txt-primary">
            <span className="font-bold" style={{ color: '#FF4444' }}>{totalViolations} violations</span>
            <span className="text-txt-muted"> across </span>
            <span className="font-bold" style={{ color: '#FFB020' }}>{violationCats} categories</span>
          </span>
        </div>
      </div>
    </div>
  )
}
