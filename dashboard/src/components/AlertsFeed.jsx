import { useAlerts } from '@/lib/hooks'
import { Badge } from '@/components/ui/badge'
import { tierBadge, fmtDate } from '@/lib/format'
import { cn } from '@/lib/utils'
import { Bell } from 'lucide-react'

const KIND_TONE = {
  finance: 'text-amber-300',
  spatial: 'text-teal-300',
  anomaly: 'text-red-300',
  source: 'text-slate-400',
}

// Chronological watchlist / anomaly alerts feed.
export default function AlertsFeed() {
  const { data: alerts = [] } = useAlerts()

  return (
    <div className="h-full overflow-auto p-2 space-y-1.5">
      {alerts.map((a) => (
        <div key={a.id} className="flex items-start gap-3 rounded-md border border-slate-800 bg-slate-900 p-2.5">
          <Bell className={cn('h-4 w-4 mt-0.5 shrink-0', KIND_TONE[a.kind] ?? 'text-slate-400')} />
          <div className="min-w-0 flex-1">
            <div className="flex items-center gap-2">
              <Badge variant="outline" className={cn('text-[10px]', tierBadge(a.tier))}>{a.tier}</Badge>
              <span className="text-[11px] text-slate-500">{fmtDate(a.at)}</span>
              {a.investigation && <span className="text-[11px] text-slate-600">· {a.investigation}</span>}
            </div>
            <p className="text-sm text-slate-200 mt-0.5">{a.title}</p>
            {a.registration && <p className="text-[11px] text-sky-300 mt-0.5">reg {a.registration}</p>}
          </div>
        </div>
      ))}
      {alerts.length === 0 && <p className="text-center text-sm text-slate-500 py-8">No alerts</p>}
    </div>
  )
}
