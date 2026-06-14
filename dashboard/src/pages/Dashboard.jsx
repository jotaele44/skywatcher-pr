import { useState } from 'react'
import { useSites, useEvents, useAnomalies, useEventTrack } from '@/lib/hooks'
import { Tabs, TabsList, TabsTrigger, TabsContent } from '@/components/ui/tabs'
import MapView from '@/components/MapView'
import SourcesHealthStrip from '@/components/SourcesHealthStrip'
import EventsTable from '@/components/EventsTable'
import AnomalyGrid from '@/components/AnomalyGrid'
import AlertsFeed from '@/components/AlertsFeed'
import FlightTrackReplay from '@/components/FlightTrackReplay'
import PipelineControl from '@/components/PipelineControl'
import RagChatPanel from '@/components/RagChatPanel'
import { Radar } from 'lucide-react'

export default function Dashboard() {
  const { data: sites = [] } = useSites()
  const { data: events = [] } = useEvents()
  const { data: anomalies = [] } = useAnomalies()

  const [tab, setTab] = useState('events')
  const [selected, setSelected] = useState(null) // selected event
  const [replayIdx, setReplayIdx] = useState(null) // null = show full track
  const [playing, setPlaying] = useState(false)

  const { data: track = [] } = useEventTrack(selected?.id)
  const visibleTrack = replayIdx == null ? track : track.slice(0, replayIdx)

  function selectEvent(e) {
    setSelected(e); setReplayIdx(null); setPlaying(false)
  }

  return (
    <div className="flex flex-col h-screen bg-slate-950 text-slate-200">
      {/* header */}
      <header className="flex items-center gap-2 px-4 py-2.5 border-b border-slate-800 bg-slate-900">
        <Radar className="h-5 w-5 text-sky-400" />
        <div>
          <h1 className="text-sm font-semibold text-slate-100 leading-none">Skywatcher-PR</h1>
          <p className="text-[11px] text-slate-500 mt-0.5">Puerto Rico airspace & infrastructure intelligence</p>
        </div>
      </header>

      <SourcesHealthStrip />

      {/* body: map + side panel */}
      <div className="flex flex-1 min-h-0">
        <div className="relative flex-1 min-w-0">
          <MapView
            sites={sites}
            anomalies={anomalies}
            track={visibleTrack}
            onSelectAnomaly={() => setTab('anomalies')}
          />
          <div className="pointer-events-none absolute bottom-2 left-2 rounded bg-slate-900/80 px-2 py-1 text-[11px] text-slate-400">
            {sites.length} sites · {anomalies.length} anomalies
          </div>
        </div>

        <aside className="w-[420px] shrink-0 border-l border-slate-800 bg-slate-950 flex flex-col min-h-0">
          <FlightTrackReplay
            event={selected}
            track={track}
            idx={replayIdx}
            setIdx={setReplayIdx}
            playing={playing}
            setPlaying={setPlaying}
            onClear={() => selectEvent(null)}
          />

          <Tabs value={tab} onValueChange={setTab} className="flex flex-col flex-1 min-h-0">
            <TabsList className="grid grid-cols-4 mx-2 mt-2 bg-slate-900">
              <TabsTrigger value="events" className="text-xs">Events</TabsTrigger>
              <TabsTrigger value="anomalies" className="text-xs">Anomalies</TabsTrigger>
              <TabsTrigger value="alerts" className="text-xs">Alerts</TabsTrigger>
              <TabsTrigger value="tools" className="text-xs">Tools</TabsTrigger>
            </TabsList>

            <TabsContent value="events" className="flex-1 min-h-0 mt-2">
              <EventsTable events={events} selectedId={selected?.id} onSelect={selectEvent} />
            </TabsContent>
            <TabsContent value="anomalies" className="flex-1 min-h-0 mt-2">
              <AnomalyGrid anomalies={anomalies} />
            </TabsContent>
            <TabsContent value="alerts" className="flex-1 min-h-0 mt-2">
              <AlertsFeed />
            </TabsContent>
            <TabsContent value="tools" className="flex-1 min-h-0 mt-2 overflow-auto p-2 space-y-3">
              <PipelineControl />
              <RagChatPanel />
            </TabsContent>
          </Tabs>
        </aside>
      </div>
    </div>
  )
}
