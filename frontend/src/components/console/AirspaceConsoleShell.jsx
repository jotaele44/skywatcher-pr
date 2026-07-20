import React, { useCallback, useRef } from 'react';
import { getBasemap } from './BasemapRegistry';
import { resolveCapability } from './CapabilityGate';
import { ConsoleStatusPanel } from './ConsoleStatusPanel';
import { ConsoleToolbar } from './ConsoleToolbar';
import { AirspaceMap } from './AirspaceMap';
import { MapAttribution } from './MapAttribution';
import { MAP_CAPABILITY_IDS } from './consoleDefaults';
import { RuntimeUnavailable } from './RuntimeUnavailable';
import { useConsoleState } from './ConsoleStateContext';

export function AirspaceConsoleShell() {
  const adapterRef = useRef(null);
  const { state, dispatch } = useConsoleState();
  const basemap = getBasemap(state.activeBasemapId);
  const navigation = resolveCapability({
    capabilities: state.capabilities,
    capabilityId: MAP_CAPABILITY_IDS.navigation,
    runtimeReady: state.webglSupported !== false,
  });

  const setAdapter = useCallback((adapter) => {
    adapterRef.current = adapter;
  }, []);

  const resetViewport = useCallback((viewport) => {
    dispatch({ type: 'viewport/set', viewport });
    adapterRef.current?.setViewport(viewport, { duration: 350 });
  }, [dispatch]);

  const locate = useCallback((location) => {
    dispatch({ type: 'geolocation/status', status: 'ready', location });
    adapterRef.current?.showUserLocation(location);
  }, [dispatch]);

  if (!navigation.enabled) {
    return <RuntimeUnavailable title="Interactive console capability unavailable" reason={navigation.reason} />;
  }

  return (
    <div className="flex h-full min-h-0 flex-col bg-background" data-testid="airspace-console-shell">
      <ConsoleToolbar onResetViewport={resetViewport} onLocation={locate} />
      <div className="flex min-h-0 flex-1 flex-col md:flex-row">
        <ConsoleStatusPanel />
        <section className="min-h-[28rem] min-w-0 flex-1 md:min-h-0" aria-label="Map workspace">
          <AirspaceMap basemap={basemap} location={state.geolocation} onAdapterReady={setAdapter} />
        </section>
      </div>
      <MapAttribution attribution={basemap.attribution} />
    </div>
  );
}
