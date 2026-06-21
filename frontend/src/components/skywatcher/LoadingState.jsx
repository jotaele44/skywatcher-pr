import React from "react";
import { Radar } from "lucide-react";

export default function LoadingState({ label = "Loading diagnostic surface…" }) {
  return (
    <div className="flex flex-col items-center justify-center py-24 text-center">
      <Radar className="h-8 w-8 animate-spin text-primary" />
      <p className="mt-3 text-sm text-muted-foreground">{label}</p>
    </div>
  );
}