'use client'

import { useEffect, useState } from 'react'

type ConnState = 'checking' | 'connected' | 'disconnected'

export function BackendStatus() {
  const [state, setState] = useState<ConnState>('checking')
  const [info,  setInfo ] = useState<{ active_runs?: number } | null>(null)

  const check = async () => {
    try {
      // Backend exposes GET /health (not /api/health) — proxied via next.config.js rewrite
      const res = await fetch('/health', { signal: AbortSignal.timeout(3000) })
      if (res.ok) {
        const d = await res.json()
        setState('connected')
        setInfo(d)
      } else {
        setState('disconnected')
      }
    } catch {
      setState('disconnected')
    }
  }

  // Poll every 10s
  useEffect(() => {
    check()
    const t = setInterval(check, 10_000)
    return () => clearInterval(t)
  }, [])

  const cfg = {
    checking:     { color: '#FFB020', label: 'Checking…',  pulse: true  },
    connected:    { color: '#00FF88', label: 'Backend OK', pulse: false },
    disconnected: { color: '#FF4444', label: 'No Backend', pulse: false },
  }[state]

  return (
    <div className="flex items-center gap-1.5 group relative">
      <div
        className="w-1.5 h-1.5 rounded-full shrink-0"
        style={{
          background: cfg.color,
          boxShadow:  `0 0 5px ${cfg.color}`,
          animation:  cfg.pulse ? 'pulseDot 1.5s ease-in-out infinite' : 'none',
        }}
      />
      <span className="text-[10px] font-mono" style={{ color: cfg.color }}>
        {cfg.label}
        {state === 'connected' && info?.active_runs != null && info.active_runs > 0 && (
          <span className="text-txt-muted"> · {info.active_runs} active</span>
        )}
      </span>

      {/* Tooltip on hover */}
      {state === 'disconnected' && (
        <div className="absolute right-0 top-full mt-2 w-64 p-3 rounded-lg border border-bg-border bg-bg-elevated
                        text-[10px] font-mono text-txt-secondary leading-relaxed z-50
                        opacity-0 group-hover:opacity-100 transition-opacity pointer-events-none">
          <div className="text-red font-semibold mb-1">Backend not running</div>
          Start it with:
          <div className="mt-1.5 p-1.5 rounded bg-bg-base text-cyan break-all">
            cd genesis<br />
            uvicorn api.server:app --reload --port 8000
          </div>
        </div>
      )}
    </div>
  )
}
