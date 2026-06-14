import { useHealth, useSources } from '@/lib/hooks'
import { Badge } from '@/components/ui/badge'
import { statusMeta, tierBadge } from '@/lib/format'
import { Activity, Database } from 'lucide-react'

// Top strip: backend health + live source status pills.
export default function SourcesHealthStrip() {
  const { data: health } = useHealth()
  const { data: sources = [] } = useSources()

  const up = health?.status === 'ok' && health?.integrity_ok
  const online = sources.filter((s) => s.status === 'online').length

  return (
    <div className="flex items-center gap-3 px-4 py-2 border-b border-slate-800 bg-slate-900/60 overflow-x-auto">
      <div className="flex items-center gap-2 shrink-0">
        <span className={`inline-flex h-2.5 w-2.5 rounded-full ${up ? 'bg-emerald-400' : 'bg-red-400'} ${up ? 'animate-pulse' : ''}`} />
        <span className="text-sm font-medium text-slate-200">
          Backend {up ? 'online' : 'down'}
        </span>
        {health?.db_exists && (
          <span className="hidden sm:inline-flex items-center gap-1 text-xs text-slate-400">
            <Database className="h-3 w-3" /> {health.table_count} tables
          </span>
        )}
      </div>

      <div className="h-5 w-px bg-slate-800 shrink-0" />

      <div className="flex items-center gap-1.5 text-xs text-slate-400 shrink-0">
        <Activity className="h-3.5 w-3.5" /> {online}/{sources.length} sources
      </div>

      <div className="flex items-center gap-2">
        {sources.map((s) => {
          const sm = statusMeta(s.status)
          return (
            <div key={s.id} className="flex items-center gap-1.5 rounded-md border border-slate-800 bg-slate-900 px-2 py-1 shrink-0">
              <span className={`h-1.5 w-1.5 rounded-full ${sm.dot}`} />
              <span className="text-xs text-slate-300 whitespace-nowrap">{s.name}</span>
              <Badge variant="outline" className={`text-[10px] px-1 py-0 ${tierBadge(s.tier)}`}>{s.tier}</Badge>
            </div>
          )
        })}
      </div>
    </div>
  )
}
