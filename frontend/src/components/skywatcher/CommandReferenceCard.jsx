import React, { useEffect, useRef, useState } from "react";
import { Terminal, Copy, Check } from "lucide-react";

export default function CommandReferenceCard({ command, note = null }) {
  const [copied, setCopied] = useState(false);
  const [pending, setPending] = useState(false);
  const [error, setError] = useState('');
  const timer = useRef(null);
  useEffect(() => () => clearTimeout(timer.current), []);
  const copy = async () => {
    setPending(true);
    setCopied(false);
    setError('');
    clearTimeout(timer.current);
    try {
      if (!navigator.clipboard?.writeText) throw new Error('Clipboard unavailable');
      await navigator.clipboard.writeText(command);
      setCopied(true);
      timer.current = setTimeout(() => setCopied(false), 1500);
    } catch {
      setError('Copy failed. Select the command text to copy it manually, or retry.');
    } finally {
      setPending(false);
    }
  };
  return (
    <div className="rounded-lg border border-border bg-[hsl(220_30%_4%)] p-3">
      <div className="flex items-center gap-2">
        <Terminal className="h-3.5 w-3.5 shrink-0 text-primary" />
        <code className="flex-1 overflow-x-auto whitespace-nowrap font-mono text-xs text-foreground/90 scrollbar-thin">
          {command}
        </code>
        <button
          onClick={copy}
          type="button"
          disabled={pending}
          className="flex shrink-0 items-center gap-1 rounded border border-border bg-secondary px-2 py-1 text-[10px] font-semibold uppercase tracking-wide text-muted-foreground transition hover:text-primary"
        >
          {copied ? <Check className="h-3 w-3 text-[hsl(142_70%_55%)]" /> : <Copy className="h-3 w-3" />}
          {pending ? "Copying…" : copied ? "Copied" : "Copy"}
        </button>
      </div>
      {error && <p role="alert" className="mt-2 text-xs text-destructive">{error}</p>}
      {note && <p className="mt-1.5 pl-5 text-[10px] text-muted-foreground">{note}</p>}
    </div>
  );
}
