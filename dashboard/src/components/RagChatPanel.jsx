import { useRef, useState } from 'react'
import ReactMarkdown from 'react-markdown'
import { Button } from '@/components/ui/button'
import { Textarea } from '@/components/ui/textarea'
import { streamRagQuery } from '@/lib/api'
import { Send, Loader2 } from 'lucide-react'

// Optional: streaming RAG query over the corpus. /rag/query shells out to
// query_llm.py which is absent in skywatcher-pr root, so errors are expected —
// we surface them inline instead of crashing.
export default function RagChatPanel() {
  const [q, setQ] = useState('')
  const [answer, setAnswer] = useState('')
  const [status, setStatus] = useState('idle') // idle | streaming | error | done
  const abortRef = useRef(null)

  function ask() {
    if (!q.trim()) return
    setAnswer(''); setStatus('streaming')
    abortRef.current = streamRagQuery(
      { query: q, top_k: 5 },
      {
        onToken: (t) => setAnswer((a) => a + t),
        onDone: () => setStatus('done'),
        onError: () => setStatus('error'),
      },
    )
  }

  return (
    <div className="rounded-md border border-slate-800 bg-slate-900 p-3 space-y-2">
      <h4 className="text-sm font-medium text-slate-200">Ask the corpus (RAG)</h4>
      <Textarea
        value={q} onChange={(e) => setQ(e.target.value)}
        placeholder="e.g. Which contracts converge near Roosevelt Roads?"
        className="min-h-[60px] text-xs bg-slate-950 border-slate-800"
      />
      <Button size="sm" className="h-7 w-full" onClick={ask} disabled={status === 'streaming'}>
        {status === 'streaming' ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <Send className="h-3.5 w-3.5" />}
        <span className="ml-1 text-xs">Ask</span>
      </Button>
      {status === 'error' && (
        <p className="text-xs text-amber-300/90">RAG endpoint unavailable (query_llm.py not installed).</p>
      )}
      {answer && (
        <div className="prose prose-invert prose-sm max-w-none text-xs text-slate-300 border-t border-slate-800 pt-2">
          <ReactMarkdown>{answer}</ReactMarkdown>
        </div>
      )}
    </div>
  )
}
