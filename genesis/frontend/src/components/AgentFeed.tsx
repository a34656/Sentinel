'use client'

import { useEffect, useRef } from 'react'
import { useAgentStore, type FeedRow } from '@/stores/agentStore'

const WORKER_COLORS: Record<string, string> = {
  master:           '#00D4FF',
  engineer:         '#00FF88',
  analyst:          '#FFB020',
  scout:            '#818CF8',
  policy_guard:     '#FF4444',
  memory_lookup:    '#A855F7',
  memory_store:     '#A855F7',
  scribe_read:      '#A855F7',
  scribe_write:     '#A855F7',
  report_generator: '#00FF88',
  system:           '#3A5570',
}

const TYPE_COLORS: Record<FeedRow['type'], string> = {
  info:    '#7BA3BF',
  success: '#00FF88',
  error:   '#FF4444',
  warn:    '#FFB020',
}

function WorkerBadge({ worker }: { worker: string }) {
  const color = WORKER_COLORS[worker] ?? '#7BA3BF'
  const label = worker.replace(/_/g, ' ').replace(/\b\w/g, c => c.toUpperCase())
  return (
    <span
      className="inline-flex items-center px-1.5 py-0.5 rounded text-[9px] font-mono font-medium shrink-0"
      style={{ color, background: color + '18', border: `1px solid ${color}33` }}
    >
      {label}
    </span>
  )
}

function Row({ row }: { row: FeedRow }) {
  const msgColor = TYPE_COLORS[row.type]
  return (
    <div className="log-row flex items-start gap-2.5 px-3 py-1.5 hover:bg-bg-elevated/60 rounded transition-colors group">
      {/* Timestamp */}
      <span className="text-[10px] font-mono text-txt-muted shrink-0 pt-0.5 tabular-nums w-16">
        {row.ts}
      </span>
      {/* Worker badge */}
      {row.worker !== 'system' && <WorkerBadge worker={row.worker} />}
      {/* Message */}
      <span
        className="text-[11px] font-mono leading-relaxed break-all"
        style={{ color: msgColor }}
      >
        {row.message}
      </span>
    </div>
  )
}

export function AgentFeed() {
  const feedRows  = useAgentStore(s => s.feedRows)
  const status    = useAgentStore(s => s.status)
  const isRunning = status === 'running'
  const bottomRef = useRef<HTMLDivElement>(null)

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: 'smooth' })
  }, [feedRows.length])

  return (
    <div className="flex flex-col h-full bg-bg-surface rounded-xl border border-bg-border overflow-hidden">
      {/* Header */}
      <div className="flex items-center justify-between px-4 py-2.5 border-b border-bg-border shrink-0">
        <div className="flex items-center gap-2">
          <div
            className="w-2 h-2 rounded-full"
            style={{
              background: isRunning ? '#00D4FF' : '#3A5570',
              boxShadow:  isRunning ? '0 0 8px #00D4FF' : 'none',
              animation:  isRunning ? 'pulseDot 1.8s ease-in-out infinite' : 'none',
            }}
          />
          <span className="text-[11px] font-mono text-txt-secondary tracking-widest uppercase">
            Live Agent Feed
          </span>
        </div>
        <span className="text-[10px] font-mono text-txt-muted tabular-nums">
          {feedRows.length} events
        </span>
      </div>

      {/* Rows */}
      <div className="flex-1 overflow-y-auto py-1">
        {feedRows.length === 0 ? (
          <div className="flex items-center justify-center h-full">
            <p className="text-[11px] font-mono text-txt-muted italic">
              Awaiting investigation…
            </p>
          </div>
        ) : (
          feedRows.map(row => <Row key={row.id} row={row} />)
        )}

        {/* Cursor */}
        {isRunning && (
          <div className="flex items-center gap-2.5 px-3 py-1.5">
            <span className="text-[10px] font-mono text-txt-muted w-16 tabular-nums">
              {new Date().toLocaleTimeString('en-GB', { hour12: false })}
            </span>
            <span className="text-[11px] font-mono text-cyan blink">▮</span>
          </div>
        )}

        <div ref={bottomRef} />
      </div>
    </div>
  )
}
