import { useMemo, useState } from 'react'
import { Card, CardHeader, CardTitle, CardContent } from '@/components/ui/card'
import { Badge } from '@/components/ui/badge'
import {
  Select, SelectTrigger, SelectValue, SelectContent, SelectItem,
} from '@/components/ui/select'
import {
  Sheet, SheetContent, SheetHeader, SheetTitle, SheetDescription,
} from '@/components/ui/sheet'
import { bandMeta } from '@/lib/format'
import { cn } from '@/lib/utils'

// Anomaly cards, filterable by severity band. Click opens a detail sheet with
// factors / linked contracts / linked events / contradictions.
export default function AnomalyGrid({ anomalies = [] }) {
  const [band, setBand] = useState('all')
  const [open, setOpen] = useState(null)

  const bands = useMemo(
    () => ['all', ...Array.from(new Set(anomalies.map((a) => a.band)))],
    [anomalies],
  )
  const rows = band === 'all' ? anomalies : anomalies.filter((a) => a.band === band)

  return (
    <div className="flex flex-col h-full">
      <div className="flex items-center justify-between gap-2 p-2">
        <span className="text-xs text-slate-400">{rows.length} anomalies</span>
        <Select value={band} onValueChange={setBand}>
          <SelectTrigger className="h-7 w-[130px] text-xs"><SelectValue /></SelectTrigger>
          <SelectContent>
            {bands.map((b) => (
              <SelectItem key={b} value={b} className="text-xs">{b === 'all' ? 'All bands' : bandMeta(b).label}</SelectItem>
            ))}
          </SelectContent>
        </Select>
      </div>

      <div className="flex-1 overflow-auto p-2 space-y-2">
        {rows.map((a) => {
          const bm = bandMeta(a.band)
          return (
            <Card
              key={a.id}
              onClick={() => setOpen(a)}
              className="cursor-pointer bg-slate-900 border-slate-800 hover:border-slate-700 transition-colors"
            >
              <CardHeader className="p-3 pb-1">
                <div className="flex items-start justify-between gap-2">
                  <CardTitle className="text-sm font-medium text-slate-100 leading-snug">{a.title}</CardTitle>
                  <Badge variant="outline" className={cn('shrink-0 text-[10px]', bm.badge)}>{bm.label}</Badge>
                </div>
              </CardHeader>
              <CardContent className="p-3 pt-1">
                <p className="text-xs text-slate-400 line-clamp-2">{a.summary}</p>
                <div className="mt-2 flex items-center gap-3 text-[11px] text-slate-500">
                  <span>score {a.score?.toFixed?.(2) ?? a.score}</span>
                  <span>{a.factors?.length ?? 0} factors</span>
                  <span>{a.contracts?.length ?? 0} contracts</span>
                  {a.contradictions?.length ? <span className="text-amber-400">{a.contradictions.length} contradiction(s)</span> : null}
                </div>
              </CardContent>
            </Card>
          )
        })}
        {rows.length === 0 && <p className="text-center text-sm text-slate-500 py-8">No anomalies</p>}
      </div>

      <Sheet open={!!open} onOpenChange={(o) => !o && setOpen(null)}>
        <SheetContent className="bg-slate-950 border-slate-800 text-slate-200 w-full sm:max-w-md overflow-y-auto">
          {open && (
            <>
              <SheetHeader>
                <div className="flex items-center gap-2">
                  <Badge variant="outline" className={cn('text-[10px]', bandMeta(open.band).badge)}>{bandMeta(open.band).label}</Badge>
                  <span className="text-xs text-slate-500">score {open.score} · confidence {open.confidence}</span>
                </div>
                <SheetTitle className="text-slate-100 text-left">{open.title}</SheetTitle>
                <SheetDescription className="text-slate-400 text-left">{open.summary}</SheetDescription>
              </SheetHeader>

              <div className="mt-4 space-y-4 text-sm">
                {open.factors?.length > 0 && (
                  <Section title="Factors">
                    {open.factors.map((f, i) => (
                      <div key={i} className="flex gap-2">
                        <Badge variant="outline" className="text-[10px] border-slate-700 text-slate-300 shrink-0">{f.tag}</Badge>
                        <span className="text-slate-400 text-xs">{f.note}</span>
                      </div>
                    ))}
                  </Section>
                )}
                {open.contracts?.length > 0 && (
                  <Section title="Linked contracts">
                    <div className="flex flex-wrap gap-1">
                      {open.contracts.map((c) => <code key={c} className="text-[11px] bg-slate-900 border border-slate-800 rounded px-1.5 py-0.5 text-amber-300">{c}</code>)}
                    </div>
                  </Section>
                )}
                {open.events?.length > 0 && (
                  <Section title="Linked events">
                    <div className="flex flex-wrap gap-1">
                      {open.events.map((c) => <code key={c} className="text-[11px] bg-slate-900 border border-slate-800 rounded px-1.5 py-0.5 text-sky-300">{c}</code>)}
                    </div>
                  </Section>
                )}
                {open.contradictions?.length > 0 && (
                  <Section title="Contradictions">
                    {open.contradictions.map((c, i) => <p key={i} className="text-xs text-amber-300/90">{c}</p>)}
                  </Section>
                )}
              </div>
            </>
          )}
        </SheetContent>
      </Sheet>
    </div>
  )
}

function Section({ title, children }) {
  return (
    <div className="space-y-1.5">
      <h4 className="text-[11px] uppercase tracking-wide text-slate-500">{title}</h4>
      {children}
    </div>
  )
}
