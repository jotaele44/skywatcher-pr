import React, { useEffect } from 'react';
import { render, screen } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';

vi.mock('@/components/console/AirspaceMap', () => ({
  AirspaceMap: ({ onAdapterReady }) => {
    useEffect(() => {
      const adapter = { setViewport: vi.fn(), showUserLocation: vi.fn() };
      onAdapterReady?.(adapter);
      return () => onAdapterReady?.(null);
    }, [onAdapterReady]);
    return <div data-testid="mock-map">map</div>;
  },
}));

import { AirspaceConsoleShell } from '@/components/console/AirspaceConsoleShell';
import { ConsoleStateProvider, INITIAL_CONSOLE_STATE } from '@/components/console/ConsoleStateContext';

function buildState(mapStatus = 'available') {
  return {
    ...INITIAL_CONSOLE_STATE,
    bootstrapStatus: 'ready',
    runtimeStatus: 'ready',
    webglSupported: true,
    capabilities: [
      { id: 'map_navigation', status: mapStatus, reason: mapStatus === 'available' ? 'ready' : 'blocked' },
      { id: 'geolocation', status: 'available', reason: 'ready' },
      { id: 'basemap_controls', status: 'available', reason: 'ready' },
    ],
    repositories: [],
  };
}

describe('AirspaceConsoleShell', () => {
  it('renders the map, status panel, toolbar, and permanent attribution', () => {
    render(<ConsoleStateProvider initialState={buildState()}><AirspaceConsoleShell /></ConsoleStateProvider>);
    expect(screen.getByTestId('mock-map')).toBeInTheDocument();
    expect(screen.getByTestId('permanent-map-attribution')).toBeVisible();
    expect(screen.getByText('Interactive Airspace Console')).toBeInTheDocument();
  });

  it('fails closed when server capability is unavailable', () => {
    render(<ConsoleStateProvider initialState={buildState('unavailable_no_adapter')}><AirspaceConsoleShell /></ConsoleStateProvider>);
    expect(screen.getByTestId('console-runtime-unavailable')).toHaveTextContent('blocked');
    expect(screen.queryByTestId('mock-map')).not.toBeInTheDocument();
  });
});
