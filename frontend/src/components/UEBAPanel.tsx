'use client'

import { ShieldAlert, CheckCircle2, XCircle, AlertTriangle } from 'lucide-react'
import { useAgentStore } from '@/stores/agentStore'

export function UEBAPanel() {
  const awaiting     = useAgentStore(s => s.awaitingApproval)
  const reason       = useAgentStore(s => s.blockedReason)
  const approve      = useAgentStore(s => s.approveAction)
  const incidentId   = useAgentStore(s => s.incidentId)

  if (!awaiting) return null

  const handleDeny = () => {
    // Deny = kill the investigation
    if (incidentId) {
      fetch(`/api/incident/${incidentId}/kill`, { method: 'POST' }).catch(() => {})
    }
    useAgentStore.getState().reset()
  }

  return (
    <div className="animate-slide-up rounded-xl border glow-red overflow-hidden"
      style={{ borderColor: '#FF444444', background: '#FF444408' }}>

      {/* Header bar */}
      <div className="flex items-center gap-2.5 px-4 py-2.5 border-b"
        style={{ borderColor: '#FF444422', background: '#FF44440A' }}>
        <ShieldAlert size={14} className="text-red shrink-0" />
        <span className="text-[11px] font-mono font-semibold text-red tracking-widest uppercase">
          Policy Guard — Action Blocked
        </span>
        <div className="ml-auto flex gap-1">
          {[0, 0.25, 0.5].map(delay => (
            <div key={delay} className="w-1.5 h-1.5 rounded-full bg-red animate-pulse-dot"
              style={{ animationDelay: `${delay}s` }} />
          ))}
        </div>
      </div>

      {/* Body */}
      <div className="px-4 py-3 flex flex-col gap-3">
        <div className="flex items-start gap-2.5">
          <AlertTriangle size={13} className="text-amber shrink-0 mt-0.5" />
          <p className="text-[11px] font-mono text-txt-secondary leading-relaxed">
            {reason ?? 'A destructive operation was detected. Human approval required before Genesis can proceed.'}
          </p>
        </div>

        <div className="flex gap-2">
          <button
            onClick={approve}
            className="flex items-center gap-1.5 px-4 py-1.5 rounded-lg text-[11px] font-mono font-medium
                       transition-all duration-200 glow-green"
            style={{
              background:   '#00FF8812',
              border:       '1px solid #00FF8844',
              color:        '#00FF88',
            }}
          >
            <CheckCircle2 size={12} />
            Approve &amp; Continue
          </button>
          <button
            onClick={handleDeny}
            className="flex items-center gap-1.5 px-4 py-1.5 rounded-lg text-[11px] font-mono
                       transition-all duration-200"
            style={{
              background: '#FF444410',
              border:     '1px solid #FF444433',
              color:      '#FF4444',
            }}
          >
            <XCircle size={12} />
            Deny &amp; Stop
          </button>
        </div>
      </div>
    </div>
  )
}
