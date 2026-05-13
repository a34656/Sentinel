'use client'

import { useEffect } from 'react'
import { ExternalLink, RefreshCw, Clock } from 'lucide-react'
import { useAgentStore } from '@/stores/agentStore'

const STATUS_COLORS: Record<string, string> = {
  complete:   '#00FF88',
  running:    '#00D4FF',
  killed:     '#FFB020',
  error:      '#FF4444',
  terminated: '#FFB020',
}

export function IncidentHistory() {
  const history        = useAgentStore(s => s.history)
  const historyLoading = useAgentStore(s => s.historyLoading)
  const loadHistory    = useAgentStore(s => s.loadHistory)

  useEffect(() => { loadHistory() }, [loadHistory])

  return (
    <div className="bg-bg-surface rounded-xl border border-bg-border overflow-hidden flex flex-col">
      {/* Header */}
      <div className="flex items-center justify-between px-4 py-2.5 border-b border-bg-border shrink-0">
        <div className="flex items-center gap-2">
          <Clock size={11} className="text-txt-muted" />
          <span className="text-[11px] font-mono text-txt-secondary tracking-widest uppercase">
            Incident History
          </span>
        </div>
        <button
          onClick={loadHistory}
          disabled={historyLoading}
          className="p-1 rounded hover:bg-bg-elevated transition-colors disabled:opacity-40"
        >
          <RefreshCw size={11} className={`text-txt-muted ${historyLoading ? 'animate-spin' : ''}`} />
        </button>
      </div>

      {/* Table */}
      <div className="overflow-x-auto overflow-y-auto max-h-64">
        {history.length === 0 ? (
          <div className="flex items-center justify-center py-8">
            <p className="text-[11px] font-mono text-txt-muted italic">
              {historyLoading ? 'Loading…' : 'No past incidents'}
            </p>
          </div>
        ) : (
          <table className="w-full text-left border-collapse">
            <thead>
              <tr className="border-b border-bg-border">
                {['ID', 'Status', 'Conf.', 'Root Cause', 'Post-Mortem'].map(h => (
                  <th key={h} className="px-3 py-2 text-[10px] font-mono text-txt-muted uppercase tracking-wider whitespace-nowrap">
                    {h}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {history.map((inc, i) => {
                const statusColor = STATUS_COLORS[inc.status] ?? '#7BA3BF'
                return (
                  <tr
                    key={inc.incident_id ?? i}
                    className="border-b border-bg-border/50 hover:bg-bg-elevated/50 transition-colors"
                  >
                    {/* ID */}
                    <td className="px-3 py-2 text-[10px] font-mono text-txt-muted tabular-nums whitespace-nowrap">
                      {inc.incident_id?.slice(0, 8) ?? '—'}
                    </td>
                    {/* Status */}
                    <td className="px-3 py-2">
                      <span
                        className="text-[10px] font-mono capitalize"
                        style={{ color: statusColor }}
                      >
                        {inc.status}
                      </span>
                    </td>
                    {/* Confidence */}
                    <td className="px-3 py-2">
                      <span
                        className="text-[11px] font-mono tabular-nums"
                        style={{ color: inc.confidence > 0.7 ? '#00FF88' : '#FFB020' }}
                      >
                        {(inc.confidence * 100).toFixed(0)}%
                      </span>
                    </td>
                    {/* Root cause */}
                    <td className="px-3 py-2 max-w-[200px]">
                      <span className="text-[11px] font-mono text-txt-secondary line-clamp-1">
                        {inc.root_cause ?? <span className="text-txt-muted italic">—</span>}
                      </span>
                    </td>
                    {/* Notion link */}
                    <td className="px-3 py-2">
                      {inc.notion_url ? (
                        <a
                          href={inc.notion_url}
                          target="_blank"
                          rel="noopener noreferrer"
                          className="inline-flex items-center gap-1 text-[10px] font-mono text-cyan/70
                                     hover:text-cyan transition-colors"
                        >
                          <ExternalLink size={9} />
                          View
                        </a>
                      ) : (
                        <span className="text-[10px] font-mono text-txt-muted">—</span>
                      )}
                    </td>
                  </tr>
                )
              })}
            </tbody>
          </table>
        )}
      </div>
    </div>
  )
}
