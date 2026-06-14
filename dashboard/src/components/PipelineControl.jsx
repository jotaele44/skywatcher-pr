import { useState } from 'react'
import { Button } from '@/components/ui/button'
import { runPipeline } from '@/lib/api'
import { Play, AlertTriangle, Loader2 } from 'lucide-react'

// Optional: kick off the ingest pipeline. The run_all.py / query_llm.py scripts
// are not present in skywatcher-pr root, so the endpoint typically reports
// {available:false} — we render a clear disabled state rather than an error.
export default function PipelineControl() {
  const [state, setState] = useState({ status: 'idle' })

  async function go() {
    setState({ status: 'running' })
    const res = await runPipeline({})
    if (res?.available === false) setState({ status: 'unavailable' })
    else setState({ status: 'started', job: res?.job_id })
  }

  return (
    <div className="rounded-md border border-slate-800 bg-slate-900 p-3">
      <div className="flex items-center justify-between">
        <h4 className="text-sm font-medium text-slate-200">Ingest pipeline</h4>
        <Button size="sm" variant="outline" className="h-7" onClick={go} disabled={state.status === 'running'}>
          {state.status === 'running' ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <Play className="h-3.5 w-3.5" />}
          <span className="ml-1 text-xs">Run</span>
        </Button>
      </div>
      {state.status === 'unavailable' && (
        <p className="mt-2 flex items-start gap-1.5 text-xs text-amber-300/90">
          <AlertTriangle className="h-3.5 w-3.5 mt-0.5 shrink-0" />
          Pipeline scripts not installed in this repo — endpoint unavailable.
        </p>
      )}
      {state.status === 'started' && (
        <p className="mt-2 text-xs text-emerald-300">Started job {state.job ?? '(unknown id)'}.</p>
      )}
      {state.status === 'idle' && (
        <p className="mt-2 text-xs text-slate-500">Triggers <code className="text-slate-400">run_all.py</code> on the backend host.</p>
      )}
    </div>
  )
}
