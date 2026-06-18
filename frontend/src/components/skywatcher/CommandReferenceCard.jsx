import React, { useState } from "react";
import { Terminal, Copy, Check } from "lucide-react";

export default function CommandReferenceCard({ command, note }) {
  const [copied, setCopied] = useState(false);
  const copy = () => {
    navigator.clipboard?.writeText(command);
    setCopied(true);
    setTimeout(() => setCopied(false), 1500);
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
          className="flex shrink-0 items-center gap-1 rounded border border-border bg-secondary px-2 py-1 text-[10px] font-semibold uppercase tracking-wide text-muted-foreground transition hover:text-primary"
        >
          {copied ? <Check className="h-3 w-3 text-[hsl(142_70%_55%)]" /> : <Copy className="h-3 w-3" />}
          {copied ? "Copied" : "Copy"}
        </button>
      </div>
      {note && <p className="mt-1.5 pl-5 text-[10px] text-muted-foreground">{note}</p>}
    </div>
  );
}