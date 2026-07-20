import React, { useEffect, useRef } from 'react';
import 'maplibre-gl/dist/maplibre-gl.css';
import { MapRuntimeAdapter } from './MapRuntimeAdapter';
import { probeWebGL } from './WebGLCapabilityProbe';
import { RuntimeUnavailable } from './RuntimeUnavailable';
import { useConsoleState } from './ConsoleStateContext';

const defaultAdapterFactory = () => new MapRuntimeAdapter();

export function AirspaceMap({ basemap, location, onAdapterReady, adapterFactory = defaultAdapterFactory }) {
  const containerRef = useRef(null);
  const adapterRef = useRef(null);
  const { state, dispatch } = useConsoleState();
  const initialViewportRef = useRef(state.viewport);

  useEffect(() => {
    const probe = probeWebGL();
    if (!probe.supported) {
      dispatch({ type: 'runtime/status', status: 'unavailable', error: probe.reason, webglSupported: false });
      return undefined;
    }

    const adapter = adapterFactory();
    adapterRef.current = adapter;
    onAdapterReady?.(adapter);
    dispatch({ type: 'runtime/status', status: 'initializing', webglSupported: true });

    try {
      adapter.create({
        container: containerRef.current,
        style: basemap.style,
        viewport: initialViewportRef.current,
        onViewportChange: (viewport) => dispatch({ type: 'viewport/set', viewport }),
        onReady: () => dispatch({ type: 'runtime/status', status: 'ready', webglSupported: true }),
        onError: (error) => dispatch({ type: 'runtime/status', status: 'error', error: error.message, webglSupported: true }),
      });
    } catch (error) {
      dispatch({ type: 'runtime/status', status: 'error', error: error.message, webglSupported: true });
    }

    return () => {
      adapter.destroy();
      adapterRef.current = null;
      onAdapterReady?.(null);
    };
  }, [adapterFactory, basemap.style, dispatch, onAdapterReady]);

  useEffect(() => {
    if (location && adapterRef.current) adapterRef.current.showUserLocation(location);
  }, [location]);

  if (state.webglSupported === false || state.runtimeStatus === 'unavailable') {
    return <RuntimeUnavailable reason="This browser did not provide a usable WebGL context." />;
  }

  return (
    <div className="relative h-full min-h-0 w-full bg-[hsl(220_34%_4%)]" data-testid="airspace-map-region">
      <div ref={containerRef} className="absolute inset-0" data-testid="maplibre-container" />
      {state.runtimeStatus === 'initializing' && (
        <div className="pointer-events-none absolute left-3 top-3 rounded-md border border-border bg-background/90 px-3 py-2 text-xs text-muted-foreground shadow-lg">
          Initializing local map runtime…
        </div>
      )}
    </div>
  );
}
