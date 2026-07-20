import React, { useEffect, useRef } from "react";
import maplibregl from "maplibre-gl";
import "maplibre-gl/dist/maplibre-gl.css";
import { createMapRuntime } from "@/console/mapRuntimeAdapter";

export default function MapRuntime({
  capabilityIndex,
  basemapId,
  viewport,
  selection,
  layerVisibility,
  onViewportChange,
  onSelectionChange,
  onRuntimeError,
  height = 560,
}) {
  const containerRef = useRef(null);
  const runtimeRef = useRef(null);
  const viewportRef = useRef(viewport);
  const selectionRef = useRef(selection);
  const layerVisibilityRef = useRef(layerVisibility);

  viewportRef.current = viewport;
  selectionRef.current = selection;
  layerVisibilityRef.current = layerVisibility;

  useEffect(() => {
    if (!containerRef.current) return undefined;
    try {
      runtimeRef.current = createMapRuntime({
        maplibregl,
        container: containerRef.current,
        capabilityIndex,
        basemapId,
        viewport: viewportRef.current,
        selection: selectionRef.current,
        layerVisibility: layerVisibilityRef.current,
        onViewportChange,
        onSelectionChange,
      });
    } catch (error) {
      onRuntimeError?.(error);
      return undefined;
    }

    const observer = typeof ResizeObserver === "undefined" ? null : new ResizeObserver(() => runtimeRef.current?.resize());
    if (observer) observer.observe(containerRef.current);

    return () => {
      observer?.disconnect();
      runtimeRef.current?.destroy();
      runtimeRef.current = null;
    };
  }, [basemapId, capabilityIndex, onRuntimeError, onSelectionChange, onViewportChange]);

  useEffect(() => {
    runtimeRef.current?.updateSelection(selection);
  }, [selection]);

  useEffect(() => {
    for (const [layerId, visible] of Object.entries(layerVisibility)) {
      runtimeRef.current?.setLayerVisibility(layerId, visible);
    }
  }, [layerVisibility]);

  return (
    <div className="relative overflow-hidden rounded-lg border border-border bg-[hsl(220_34%_5%)]" style={{ height }}>
      <div ref={containerRef} className="h-full w-full" aria-label="Interactive Puerto Rico airspace console map" />
      <div className="pointer-events-none absolute left-3 top-3 rounded border border-primary/30 bg-[hsl(220_34%_6%/0.92)] px-2 py-1 font-mono text-[9px] uppercase tracking-wider text-primary">
        Diagnostic map runtime
      </div>
    </div>
  );
}
