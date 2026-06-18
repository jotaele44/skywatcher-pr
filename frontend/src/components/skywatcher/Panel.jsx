import React from "react";

export default function Panel({ title, icon: Icon, action, children, className = "", bodyClassName = "" }) {
  return (
    <div className={`rounded-xl border border-border bg-card ${className}`}>
      {(title || action) && (
        <div className="flex items-center justify-between gap-2 border-b border-border px-4 py-3">
          <div className="flex items-center gap-2">
            {Icon && <Icon className="h-4 w-4 text-primary" />}
            <h3 className="text-sm font-bold tracking-tight text-foreground">{title}</h3>
          </div>
          {action}
        </div>
      )}
      <div className={`p-4 ${bodyClassName}`}>{children}</div>
    </div>
  );
}