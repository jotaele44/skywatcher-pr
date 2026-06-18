import React, { useEffect } from "react";
import { X } from "lucide-react";

export default function SideDrawer({ open, onClose, title, subtitle, badges, children, footer }) {
  useEffect(() => {
    const onKey = (e) => e.key === "Escape" && onClose?.();
    if (open) window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [open, onClose]);

  if (!open) return null;
  return (
    <div className="fixed inset-0 z-50">
      <div className="absolute inset-0 bg-black/60 backdrop-blur-sm" onClick={onClose} />
      <div className="absolute right-0 top-0 flex h-full w-full max-w-xl flex-col border-l border-border bg-[hsl(218_32%_8%)] shadow-2xl">
        <div className="flex items-start justify-between gap-3 border-b border-border px-5 py-4">
          <div className="min-w-0">
            <h2 className="truncate text-lg font-bold text-foreground">{title}</h2>
            {subtitle && <p className="mt-0.5 truncate font-mono text-xs text-muted-foreground">{subtitle}</p>}
            {badges && <div className="mt-2 flex flex-wrap items-center gap-1.5">{badges}</div>}
          </div>
          <button
            onClick={onClose}
            className="flex h-8 w-8 shrink-0 items-center justify-center rounded-lg border border-border bg-secondary text-muted-foreground transition hover:text-foreground"
          >
            <X className="h-4 w-4" />
          </button>
        </div>
        <div className="flex-1 overflow-y-auto scrollbar-thin px-5 py-4">{children}</div>
        {footer && <div className="border-t border-border px-5 py-3">{footer}</div>}
      </div>
    </div>
  );
}

export function Field({ label, children, mono }) {
  return (
    <div className="space-y-0.5">
      <p className="text-[10px] font-semibold uppercase tracking-wider text-muted-foreground">{label}</p>
      <p className={`text-sm text-foreground/90 ${mono ? "font-mono" : ""}`}>{children ?? "—"}</p>
    </div>
  );
}

export function Section({ title, icon: Icon, children, action }) {
  return (
    <div className="mt-5 first:mt-0">
      <div className="mb-2 flex items-center justify-between">
        <div className="flex items-center gap-2">
          {Icon && <Icon className="h-4 w-4 text-primary" />}
          <h3 className="text-xs font-bold uppercase tracking-wider text-foreground/80">{title}</h3>
        </div>
        {action}
      </div>
      {children}
    </div>
  );
}

export function LinkChip({ onClick, label, sublabel }) {
  return (
    <button
      onClick={onClick}
      className="flex w-full items-center justify-between gap-2 rounded-lg border border-border bg-card px-3 py-2 text-left transition hover:border-primary/40 hover:bg-secondary"
    >
      <div className="min-w-0">
        <p className="truncate text-sm font-medium text-foreground">{label}</p>
        {sublabel && <p className="truncate font-mono text-[10px] text-muted-foreground">{sublabel}</p>}
      </div>
      <span className="shrink-0 text-[10px] font-semibold uppercase tracking-wide text-primary">Open →</span>
    </button>
  );
}