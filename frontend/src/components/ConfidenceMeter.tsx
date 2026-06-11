'use client'

import { useAgentStore } from '@/stores/agentStore'

export function ConfidenceMeter() {
  const score    = useAgentStore(s => s.confidenceScore)
  const status   = useAgentStore(s => s.status)
  const isActive = status === 'running'

  const pct  = Math.round(score * 100)
  const segs = 20
  const fill = Math.round(score * segs)

  const color =
    score >= 0.85 ? '#00FF88' :
    score >= 0.5  ? '#FFB020' :
    '#00D4FF'

  const label =
    score >= 0.85 ? 'CONCLUSIVE' :
    score >= 0.6  ? 'HIGH'       :
    score >= 0.4  ? 'MODERATE'   :
    score >= 0.15 ? 'LOW'        :
    'BUILDING'

  return (
    <div className="bg-bg-surface rounded-xl border border-bg-border p-4 flex flex-col gap-3">
      {/* Top row */}
      <div className="flex items-center justify-between">
        <span className="text-[11px] font-mono text-txt-secondary tracking-widest uppercase">
          Confidence
        </span>
        <div className="flex items-center gap-2">
          <span
            className="text-[10px] font-mono tracking-widest"
            style={{ color, textShadow: `0 0 8px ${color}66` }}
          >
            {label}
          </span>
          <span
            className="font-display text-2xl font-bold tabular-nums leading-none"
            style={{ color, textShadow: `0 0 12px ${color}55` }}
          >
            {pct}<span className="text-base">%</span>
          </span>
        </div>
      </div>

      {/* Segments */}
      <div className="flex gap-0.5">
        {Array.from({ length: segs }).map((_, i) => (
          <div
            key={i}
            className="h-2 flex-1 rounded-sm transition-all duration-500"
            style={{
              background: i < fill ? color : '#1A2535',
              opacity:    i < fill ? 1 : 0.35,
              boxShadow:  (i === fill - 1 && isActive) ? `0 0 8px ${color}` : 'none',
            }}
          />
        ))}
      </div>

      {/* Threshold line + labels */}
      <div className="relative flex items-end h-4">
        <div
          className="absolute flex flex-col items-center gap-0.5"
          style={{ left: '85%', transform: 'translateX(-50%)' }}
        >
          <div className="w-px h-2 bg-cyan opacity-30" />
          <span className="text-[8px] font-mono text-txt-muted tracking-wider whitespace-nowrap">
            AUTO-FIX
          </span>
        </div>
      </div>
    </div>
  )
}
