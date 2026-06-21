import React from "react";
import { Inbox } from "lucide-react";

export default function EmptyState({ icon: Icon = Inbox, title = "No records", message }) {
  return (
    <div className="flex flex-col items-center justify-center rounded-lg border border-dashed border-border bg-card/40 px-6 py-12 text-center">
      <div className="flex h-12 w-12 items-center justify-center rounded-full bg-secondary">
        <Icon className="h-5 w-5 text-muted-foreground" />
      </div>
      <p className="mt-3 text-sm font-semibold text-foreground">{title}</p>
      {message && <p className="mt-1 max-w-sm text-xs text-muted-foreground">{message}</p>}
    </div>
  );
}