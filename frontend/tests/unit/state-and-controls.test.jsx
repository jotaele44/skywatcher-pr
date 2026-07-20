import React from 'react';
import { act, fireEvent, render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, expect, it, vi } from 'vitest';
import { CapabilityGate, resolveCapability } from '@/components/console/CapabilityGate';
import { ConsoleApiClient, loadConsoleBootstrap } from '@/components/console/ConsoleApiClient';
import { ConsoleStateProvider, consoleStateReducer, INITIAL_CONSOLE_STATE, useConsoleState } from '@/components/console/ConsoleStateContext';
import { GeolocationControl } from '@/components/console/GeolocationControl';
import { MapAttribution } from '@/components/console/MapAttribution';
import { RuntimeUnavailable } from '@/components/console/RuntimeUnavailable';

const capabilities = [{ id: 'map_navigation', status: 'available', reason: 'ready' }];

describe('capability contract', () => {
  it('fails closed for missing, disabled, degraded, and unready capabilities', () => {
    expect(resolveCapability({ capabilities, capabilityId: 'map_navigation' }).enabled).toBe(true);
    expect(resolveCapability({ capabilities, capabilityId: 'missing' }).enabled).toBe(false);
    expect(resolveCapability({ capabilities, capabilityId: 'map_navigation', featureEnabled: false }).status).toBe('disabled_by_policy');
    expect(resolveCapability({ capabilities, capabilityId: 'map_navigation', runtimeReady: false }).status).toBe('degraded');
  });

  it('renders children only when enabled', () => {
    const { rerender } = render(
      <CapabilityGate capabilities={capabilities} capabilityId="map_navigation" fallback={<span>blocked</span>}>
        <span>enabled</span>
      </CapabilityGate>,
    );
    expect(screen.getByText('enabled')).toBeInTheDocument();
    rerender(
      <CapabilityGate capabilities={[]} capabilityId="map_navigation" fallback={({ reason }) => <span>{reason}</span>}>
        <span>enabled</span>
      </CapabilityGate>,
    );
    expect(screen.getByText(/not reported/)).toBeInTheDocument();
  });
});

describe('console state reducer', () => {
  it('handles viewport, selection, layer, runtime, bootstrap, and geolocation actions', () => {
    let state = INITIAL_CONSOLE_STATE;
    state = consoleStateReducer(state, { type: 'viewport/set', viewport: { zoom: 9 } });
    expect(state.viewport.zoom).toBe(9);
    state = consoleStateReducer(state, { type: 'selection/set', entity: { id: 1 }, entityType: 'aircraft' });
    expect(state.selectedEntityType).toBe('aircraft');
    state = consoleStateReducer(state, { type: 'selection/clear' });
    expect(state.selectedEntity).toBeNull();
    state = consoleStateReducer(state, { type: 'basemap/set', basemapId: 'x' });
    expect(state.activeBasemapId).toBe('x');
    state = consoleStateReducer(state, { type: 'layer/toggle', layerId: 'routes' });
    expect(state.visibleLayerIds).toContain('routes');
    state = consoleStateReducer(state, { type: 'layer/toggle', layerId: 'routes' });
    expect(state.visibleLayerIds).not.toContain('routes');
    state = consoleStateReducer(state, { type: 'runtime/status', status: 'ready', webglSupported: true });
    expect(state.webglSupported).toBe(true);
    state = consoleStateReducer(state, { type: 'bootstrap/loading' });
    state = consoleStateReducer(state, { type: 'bootstrap/ready', capabilities: { capabilities }, repositories: { repositories: [{ repository: 'x' }] } });
    expect(state.bootstrapStatus).toBe('ready');
    state = consoleStateReducer(state, { type: 'geolocation/status', status: 'ready', location: { latitude: 18 } });
    expect(state.geolocation.latitude).toBe(18);
    expect(consoleStateReducer(state, { type: 'unknown' })).toBe(state);
  });

  it('provides state through context', () => {
    function Probe() {
      const { state, dispatch } = useConsoleState();
      return <button onClick={() => dispatch({ type: 'runtime/status', status: 'ready' })}>{state.runtimeStatus}</button>;
    }
    render(<ConsoleStateProvider><Probe /></ConsoleStateProvider>);
    fireEvent.click(screen.getByRole('button'));
    expect(screen.getByRole('button')).toHaveTextContent('ready');
  });
});

describe('API and explicit geolocation controls', () => {
  it('loads capability and repository contracts through an injected request', async () => {
    const request = vi.fn(async (path) => path.includes('capabilities') ? { capabilities } : { repositories: [] });
    const client = new ConsoleApiClient(request);
    const result = await loadConsoleBootstrap(client);
    expect(result.capabilities.capabilities).toEqual(capabilities);
    await client.aircraftStates({ bbox: '-67,17,-65,19', synthetic: false });
    expect(request).toHaveBeenLastCalledWith(expect.stringContaining('bbox='), expect.any(Object));
  });

  it('never calls geolocation until the user clicks and does not persist coordinates', async () => {
    const getCurrentPosition = vi.fn((success) => success({ coords: { longitude: -66, latitude: 18, accuracy: 8 } }));
    const onLocation = vi.fn();
    const setItem = vi.spyOn(Storage.prototype, 'setItem');
    render(<GeolocationControl navigatorRef={{ geolocation: { getCurrentPosition } }} onLocation={onLocation} />);
    expect(getCurrentPosition).not.toHaveBeenCalled();
    await userEvent.click(screen.getByRole('button', { name: /current location/i }));
    expect(getCurrentPosition).toHaveBeenCalledOnce();
    expect(onLocation).toHaveBeenCalledWith({ longitude: -66, latitude: 18, accuracy: 8 });
    expect(setItem).not.toHaveBeenCalled();
  });

  it('reports denied and unavailable geolocation without retry loops', async () => {
    const onStatusChange = vi.fn();
    const { rerender } = render(<GeolocationControl navigatorRef={{}} onStatusChange={onStatusChange} />);
    await userEvent.click(screen.getByRole('button'));
    expect(onStatusChange).toHaveBeenCalledWith('unavailable', expect.any(String));
    rerender(<GeolocationControl navigatorRef={{ geolocation: { getCurrentPosition: (_ok, fail) => fail({ message: 'denied' }) } }} onStatusChange={onStatusChange} />);
    await userEvent.click(screen.getByRole('button'));
    expect(onStatusChange).toHaveBeenCalledWith('denied', 'denied');
  });
});

describe('status surfaces', () => {
  it('keeps attribution and fallback information visible', () => {
    render(<><MapAttribution attribution="Required attribution" /><RuntimeUnavailable reason="No WebGL" /></>);
    expect(screen.getByTestId('permanent-map-attribution')).toHaveTextContent('Required attribution');
    expect(screen.getByTestId('console-runtime-unavailable')).toHaveTextContent('No WebGL');
  });
});
