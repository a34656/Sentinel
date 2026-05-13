'use client'

import { Zap } from 'lucide-react'

// Exactly 5 rehearsed prompts — never type freehand during demo
const PROMPTS = [
  {
    label: 'AWS Billing Spike',
    prompt: 'My AWS bill went up 40% overnight with no new deployments. Find the root cause and fix it.',
    color: '#FFB020',
    icon: '💸',
  },
  {
    label: 'Lambda 500 Errors',
    prompt: 'Lambda function /api/checkout is throwing 500 errors since the deploy 2 hours ago. Diagnose and remediate.',
    color: '#FF4444',
    icon: '🔴',
  },
  {
    label: 'RDS CPU Spike',
    prompt: 'RDS instance prod-db-01 CPU is at 98% for the last 90 minutes. Identify and resolve.',
    color: '#A855F7',
    icon: '📈',
  },
  {
    label: 'S3 Egress Surge',
    prompt: 'S3 egress costs tripled this week. Something is mass-downloading from our buckets. Investigate.',
    color: '#00D4FF',
    icon: '🪣',
  },
  {
    label: 'ECS Restart Loop',
    prompt: 'ECS service frontend-prod keeps restarting every 3 minutes. Find root cause and stop the loop.',
    color: '#00FF88',
    icon: '🔁',
  },
] as const

interface Props {
  onSelect: (prompt: string) => void
  disabled: boolean
}

export function DemoPrompts({ onSelect, disabled }: Props) {
  return (
    <div className="flex flex-col gap-2">
      <div className="flex items-center gap-2">
        <Zap size={10} className="text-amber" />
        <span className="text-[10px] font-mono text-txt-muted tracking-widest uppercase">
          Demo Prompts
        </span>
      </div>
      <div className="flex flex-col gap-1.5">
        {PROMPTS.map((p) => (
          <button
            key={p.label}
            onClick={() => onSelect(p.prompt)}
            disabled={disabled}
            className="flex items-center gap-2.5 px-3 py-2 rounded-lg text-left
                       bg-bg-elevated border border-bg-border
                       hover:border-bg-borderHover transition-all duration-200
                       disabled:opacity-30 disabled:cursor-not-allowed
                       group"
          >
            <span className="text-sm shrink-0">{p.icon}</span>
            <div className="flex flex-col gap-0.5 min-w-0 flex-1">
              <span
                className="text-[11px] font-mono font-medium"
                style={{ color: p.color }}
              >
                {p.label}
              </span>
              <span className="text-[10px] font-mono text-txt-muted line-clamp-1 leading-snug">
                {p.prompt.slice(0, 55)}…
              </span>
            </div>
            <span
              className="text-[10px] font-mono opacity-0 group-hover:opacity-100 transition-opacity shrink-0"
              style={{ color: p.color }}
            >
              ▶
            </span>
          </button>
        ))}
      </div>
    </div>
  )
}
