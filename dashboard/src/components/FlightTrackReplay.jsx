import { useEffect } from 'react'
import { Button } from '@/components/ui/button'
import { Slider } from '@/components/ui/slider'
import { Play, Pause, X, Plane } from 'lucide-react'
import { fmtDate } from '@/lib/format'

// Replay strip for the selected flight event. The visible polyline is drawn by
// MapView from the sliced track the Dashboard passes down; this controls the
// slice index. Degrades gracefully when the event has no ADS-B track points.
export default function FlightTrackReplay({ event, track = [], idx, setIdx, playing, setPlaying, onClear }) {
  const total = track.length
  const current = idx == null ? total : idx

  // simple playback: advance the index on a timer while `playing`
  useEffect(() => {
    if (!playing || total < 2) return
    const t = setInterval(() => {
      setIdx((v) => {
        const next = (v == null ? 0 : v) + 1
        if (next >= total) { setPlaying(false); return total }
        return next
      })
    }, 600)
    return () => clearInterval(t)
  }, [playing, total, setIdx, setPlaying])

  if (!event) return null

  const alts = track.map((p) => p.altitudeFt).filter((v) => v != null)
  const altRange = alts.length ? `${Math.min(...alts)}–${Math.max(...alts)} ft` : null

  return (
    <div className="border-b border-slate-800 bg-slate-900/80 p-3">
      <div className="flex items-center justify-between gap-2">
        <div className="flex items-center gap-2 min-w-0">
          <Plane className="h-4 w-4 text-sky-300 shrink-0" />
          <span className="text-sm text-slate-200 truncate">{event.callsign || event.label || event.id}</span>
        </div>
        <Button size="icon" variant="ghost" className="h-6 w-6" onClick={onClear}><X className="h-4 w-4" /></Button>
      </div>

      {total < 2 ? (
        <p className="text-xs text-slate-500 mt-2">
          No ADS-B track points for this event{event.kind === 'flight' ? '' : ` (kind: ${event.kind})`}.
          Track replay activates once <code className="text-slate-400">track_points</code> are ingested.
        </p>
      ) : (
        <>
          <div className="flex items-center gap-3 mt-2 text-[11px] text-slate-500">
            <span>{total} points</span>
            {altRange && <span>{altRange}</span>}
            <span>{fmtDate(track[0].at)} → {fmtDate(track[total - 1].at)}</span>
          </div>
          <div className="flex items-center gap-2 mt-2">
            <Button size="icon" variant="outline" className="h-7 w-7" onClick={() => setPlaying((p) => !p)}>
              {playing ? <Pause className="h-3.5 w-3.5" /> : <Play className="h-3.5 w-3.5" />}
            </Button>
            <Slider
              min={0} max={total} step={1} value={[current]}
              onValueChange={([v]) => { setPlaying(false); setIdx(v) }}
              className="flex-1"
            />
            <span className="text-[11px] text-slate-500 tabular-nums w-12 text-right">{current}/{total}</span>
          </div>
        </>
      )}
    </div>
  )
}
