import { useMemo, useState } from 'react'
import {
  Table, TableHeader, TableBody, TableRow, TableHead, TableCell,
} from '@/components/ui/table'
import { Badge } from '@/components/ui/badge'
import {
  Select, SelectTrigger, SelectValue, SelectContent, SelectItem,
} from '@/components/ui/select'
import { tierBadge, fmtDate } from '@/lib/format'
import { cn } from '@/lib/utils'

const KIND_TONE = {
  flight: 'bg-sky-500/15 text-sky-300 border-sky-500/30',
  contract: 'bg-amber-500/15 text-amber-300 border-amber-500/30',
  imagery: 'bg-teal-500/15 text-teal-300 border-teal-500/30',
  report: 'bg-violet-500/15 text-violet-300 border-violet-500/30',
  outage: 'bg-red-500/15 text-red-300 border-red-500/30',
}

// Mixed event log (kinds: flight / contract / imagery / report / outage).
// Row click selects an event; flight rows drive the track-replay panel.
export default function EventsTable({ events = [], selectedId, onSelect }) {
  const [kind, setKind] = useState('all')

  const kinds = useMemo(
    () => ['all', ...Array.from(new Set(events.map((e) => e.kind)))],
    [events],
  )
  const rows = kind === 'all' ? events : events.filter((e) => e.kind === kind)

  return (
    <div className="flex flex-col h-full">
      <div className="flex items-center justify-between gap-2 p-2">
        <span className="text-xs text-slate-400">{rows.length} events</span>
        <Select value={kind} onValueChange={setKind}>
          <SelectTrigger className="h-7 w-[140px] text-xs"><SelectValue /></SelectTrigger>
          <SelectContent>
            {kinds.map((k) => (
              <SelectItem key={k} value={k} className="text-xs capitalize">{k}</SelectItem>
            ))}
          </SelectContent>
        </Select>
      </div>
      <div className="flex-1 overflow-auto">
        <Table>
          <TableHeader className="sticky top-0 bg-slate-900">
            <TableRow className="hover:bg-transparent border-slate-800">
              <TableHead className="text-slate-400">Kind</TableHead>
              <TableHead className="text-slate-400">When</TableHead>
              <TableHead className="text-slate-400">Detail</TableHead>
              <TableHead className="text-slate-400">Reg</TableHead>
              <TableHead className="text-slate-400">Tier</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {rows.map((e) => (
              <TableRow
                key={e.id}
                onClick={() => onSelect?.(e)}
                className={cn(
                  'cursor-pointer border-slate-800',
                  selectedId === e.id ? 'bg-sky-500/10' : 'hover:bg-slate-800/50',
                )}
              >
                <TableCell>
                  <Badge variant="outline" className={cn('text-[10px] capitalize', KIND_TONE[e.kind] ?? 'border-slate-600 text-slate-300')}>
                    {e.kind}
                  </Badge>
                </TableCell>
                <TableCell className="text-xs text-slate-400 whitespace-nowrap">{fmtDate(e.at)}</TableCell>
                <TableCell className="text-xs text-slate-200 max-w-[180px] truncate">
                  {e.callsign || e.label || e.refId || '—'}
                </TableCell>
                <TableCell className="text-xs text-slate-400">{e.registration || '—'}</TableCell>
                <TableCell>
                  <Badge variant="outline" className={cn('text-[10px]', tierBadge(e.tier))}>{e.tier}</Badge>
                </TableCell>
              </TableRow>
            ))}
            {rows.length === 0 && (
              <TableRow><TableCell colSpan={5} className="text-center text-sm text-slate-500 py-8">No events</TableCell></TableRow>
            )}
          </TableBody>
        </Table>
      </div>
    </div>
  )
}
