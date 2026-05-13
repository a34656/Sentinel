'use client'

import { useState } from 'react'
import { Square } from 'lucide-react'
import { useAgentStore } from '@/stores/agentStore'

export function KillSwitch() {
  const status = useAgentStore(s => s.status)
  const kill   = useAgentStore(s => s.killInvestigation)
  const [confirming, setConfirming] = useState(false)

  if (status !== 'running') return null

  const handleClick = () => {
    if (!confirming) {
      setConfirming(true)
      setTimeout(() => setConfirming(false), 2500) // auto-reset
      return
    }
    kill()
    setConfirming(false)
  }

  return (
    <button
      onClick={handleClick}
      className="flex items-center gap-2 px-4 py-2 rounded-lg font-mono font-semibold
                 text-sm transition-all duration-200 active:scale-95"
      style={{
        background:   confirming ? '#FF4444' : '#FF444415',
        border:       `1px solid ${confirming ? '#FF4444' : '#FF444455'}`,
        color:        confirming ? '#fff' : '#FF4444',
        boxShadow:    confirming ? '0 0 20px #FF444488' : '0 0 0 1px #FF444422',
        animation:    confirming ? 'pulseDot 0.8s ease-in-out infinite' : 'none',
      }}
    >
      <Square size={13} fill={confirming ? 'currentColor' : 'none'} />
      {confirming ? 'Click again to confirm kill' : '■ Kill Investigation'}
    </button>
  )
}
