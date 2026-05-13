'use client'

import { useAgentStore } from '@/stores/agentStore'

const CAUSES: { key: string; label: string }[] = [
  { key: 'billing_spike',       label: 'Billing Spike'        },
  { key: 'resource_exhaustion', label: 'Resource Exhaustion'  },
  { key: 'misconfiguration',    label: 'Misconfiguration'      },
  { key: 'dependency_failure',  label: 'Dependency Failure'   },
  { key: 'network_issue',       label: 'Network Issue'        },
  { key: 'security_event',      label: 'Security Event'       },
  { key: 'deployment_bug',      label: 'Deployment Bug'       },
]

const PRIORS: Record<string, number> = {
  billing_spike: 0.18, resource_exhaustion: 0.22, misconfiguration: 0.20,
  dependency_failure: 0.15, network_issue: 0.10, security_event: 0.08, deployment_bug: 0.07,
}

export function BayesianPanel() {
  const beliefs     = useAgentStore(s => s.bayesianBeliefs)
  const entropy     = useAgentStore(s => s.bayesianEntropy)
  const topCause    = useAgentStore(s => s.bayesianTopCause)
  const hasBeliefs  = Object.keys(beliefs).length > 0
  const display     = hasBeliefs ? beliefs : PRIORS
  const maxVal      = Math.max(...Object.values(display))

  // Certainty = 1 - normalised entropy
  const maxEntropy  = Math.log2(CAUSES.length)
  const certainty   = hasBeliefs && maxEntropy > 0
    ? Math.max(0, 1 - entropy / maxEntropy)
    : 0

  const sorted = [...CAUSES].sort(
    (a, b) => (display[b.key] ?? 0) - (display[a.key] ?? 0)
  )

  return (
    <div className="flex flex-col gap-3 bg-bg-surface rounded-xl border border-bg-border p-4 h-full">
      {/* Header */}
      <div className="flex items-center justify-between">
        <span className="text-[11px] font-mono text-txt-secondary tracking-widest uppercase">
          Bayesian Beliefs
        </span>
        <div className="flex items-center gap-1.5">
          <span className="text-[10px] font-mono text-txt-muted">H=</span>
          <span className="text-[10px] font-mono text-amber tabular-nums">{entropy.toFixed(2)}</span>
        </div>
      </div>

      {/* Leading hypothesis */}
      {topCause && (
        <div className="flex items-center gap-2 px-2.5 py-1.5 rounded-lg border"
          style={{ borderColor: '#00FF8833', background: '#00FF8808' }}>
          <div className="w-1.5 h-1.5 rounded-full bg-green shrink-0"
            style={{ boxShadow: '0 0 6px #00FF88' }} />
          <span className="text-[10px] font-mono text-txt-muted">leading: </span>
          <span className="text-[11px] font-mono text-green font-medium">
            {CAUSES.find(c => c.key === topCause)?.label ?? topCause}
          </span>
          <span className="ml-auto text-[10px] font-mono text-green tabular-nums">
            {((display[topCause] ?? 0) * 100).toFixed(0)}%
          </span>
        </div>
      )}

      {!hasBeliefs && (
        <p className="text-[10px] font-mono text-txt-muted italic">Showing priors — no evidence yet</p>
      )}

      {/* Belief bars */}
      <div className="flex flex-col gap-2 flex-1">
        {sorted.map(({ key, label }) => {
          const val    = display[key] ?? 0
          const isTop  = key === topCause
          const barPct = maxVal > 0 ? (val / maxVal) * 100 : val * 100
          const color  = isTop ? '#00FF88' : '#00D4FF'

          return (
            <div key={key} className="flex items-center gap-2">
              <span
                className="text-[10px] font-mono w-32 shrink-0 truncate"
                style={{ color: isTop ? '#00FF88' : '#7BA3BF' }}
              >
                {label}
              </span>
              <div className="flex-1 h-1.5 rounded-full bg-bg-border overflow-hidden">
                <div
                  className="h-full rounded-full transition-all duration-700 ease-out"
                  style={{
                    width:     `${barPct}%`,
                    background: color,
                    boxShadow:  isTop ? `0 0 6px ${color}` : 'none',
                  }}
                />
              </div>
              <span
                className="text-[10px] font-mono w-7 text-right tabular-nums shrink-0"
                style={{ color: isTop ? '#00FF88' : '#3A5570' }}
              >
                {(val * 100).toFixed(0)}
              </span>
            </div>
          )
        })}
      </div>

      {/* Certainty bar */}
      {hasBeliefs && (
        <div className="pt-2 border-t border-bg-border flex flex-col gap-1.5">
          <div className="flex items-center justify-between">
            <span className="text-[10px] font-mono text-txt-muted">Certainty</span>
            <span className="text-[10px] font-mono text-txt-secondary tabular-nums">
              {(certainty * 100).toFixed(0)}%
            </span>
          </div>
          <div className="h-1 rounded-full bg-bg-border overflow-hidden">
            <div
              className="h-full rounded-full transition-all duration-700"
              style={{
                width:      `${certainty * 100}%`,
                background: 'linear-gradient(90deg, #00D4FF, #00FF88)',
              }}
            />
          </div>
        </div>
      )}
    </div>
  )
}
