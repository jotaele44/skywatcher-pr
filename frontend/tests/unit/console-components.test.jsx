import React from 'react';
import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { AirspaceMap } from '@/components/console/AirspaceMap';
import { ConsoleErrorBoundary } from '@/components/console/ConsoleErrorBoundary';
import { ConsoleStateProvider, INITIAL_CONSOLE_STATE } from '@/components/console/ConsoleStateContext';
import { ConsoleStatusPanel } from '@/components/console/ConsoleStatusPanel';
import { ConsoleToolbar } from '@/components/console/ConsoleToolbar';

function state(overrides = {}) {
  return {
    ...INITIAL_CONSOLE_STATE,
    capabilities: [
      { id: 'map_navigation', status: 'available', reason: 'ready' },
      { id: 'geolocation', status: 'available', reason: 'ready' },
      { id: 'basemap_controls', status: 'available', reason: 'ready' },
    ],
    repositories: [{ repository: 'aircraft_states', status: 'available' }],
    bootstrapStatus: 'ready',
    runtimeStatus: 'ready',
    webglSupported: true,
    ...overrides,
  };
}

afterEach(() => vi.restoreAllMocks());

describe('console components', () => {
  it('renders toolbar, resets viewport, switches basemap, and locates explicitly', async () => {
    const onResetViewport = vi.fn();
    const onLocation = vi.fn();
    const geolocation = {
      getCurrentPosition: vi.fn((success) => success({ coords: { longitude: -66, latitude: 18, accuracy: 6 } })),
    };
    vi.stubGlobal('navigator', { geolocation });
    render(
      <ConsoleStateProvider initialState={state()}>
        <ConsoleToolbar onResetViewport={onResetViewport} onLocation={onLocation} />
      </ConsoleStateProvider>,
    );
    await userEvent.click(screen.getByRole('button', { name: /reset view/i }));
    await userEvent.click(screen.getByRole('button', { name: /current location/i }));
    expect(onResetViewport).toHaveBeenCalledOnce();
    expect(onLocation).toHaveBeenCalledWith({ longitude: -66, latitude: 18, accuracy: 6 });
    fireEvent.change(screen.getByLabelText('Select basemap'), { target: { value: 'skywatcher-blank-offline' } });
    expect(screen.getByLabelText('Select basemap')).toHaveValue('skywatcher-blank-offline');
  });

  it('disables runtime-dependent controls and renders status data', () => {
    render(
      <ConsoleStateProvider initialState={state({ runtimeStatus: 'error', webglSupported: false, bootstrapStatus: 'degraded' })}>
        <ConsoleToolbar onResetViewport={vi.fn()} onLocation={vi.fn()} />
        <ConsoleStatusPanel />
      </ConsoleStateProvider>,
    );
    expect(screen.getByRole('button', { name: /reset view/i })).toBeDisabled();
    expect(screen.getByRole('button', { name: /current location/i })).toBeDisabled();
    expect(screen.getByText('degraded')).toBeInTheDocument();
    expect(screen.getAllByText('1')).toHaveLength(2);
    expect(screen.getByText(/No FR24 visual assets/)).toBeInTheDocument();
  });

  it('initializes and destroys the map adapter, forwards location, and shows unsupported fallback', async () => {
    const create = vi.fn(({ onReady }) => onReady());
    const destroy = vi.fn(() => ({ balanced: true }));
    const showUserLocation = vi.fn();
    const adapter = { create, destroy, showUserLocation };
    vi.spyOn(HTMLCanvasElement.prototype, 'getContext').mockImplementation((name) => (name === 'webgl2' ? {} : null));
    const { rerender, unmount } = render(
      <ConsoleStateProvider initialState={state({ runtimeStatus: 'idle', webglSupported: null })}>
        <AirspaceMap
          basemap={{ style: { version: 8, sources: {}, layers: [] } }}
          location={null}
          adapterFactory={() => adapter}
        />
      </ConsoleStateProvider>,
    );
    await waitFor(() => expect(create).toHaveBeenCalledOnce());
    rerender(
      <ConsoleStateProvider initialState={state()}>
        <AirspaceMap
          basemap={{ style: { version: 8, sources: {}, layers: [] } }}
          location={{ longitude: -66, latitude: 18 }}
          adapterFactory={() => adapter}
        />
      </ConsoleStateProvider>,
    );
    expect(showUserLocation).toHaveBeenCalled();
    unmount();
    expect(destroy).toHaveBeenCalled();

    vi.spyOn(HTMLCanvasElement.prototype, 'getContext').mockReturnValue(null);
    render(
      <ConsoleStateProvider initialState={state({ runtimeStatus: 'idle', webglSupported: null })}>
        <AirspaceMap basemap={{ style: { version: 8, sources: {}, layers: [] } }} adapterFactory={() => adapter} />
      </ConsoleStateProvider>,
    );
    await waitFor(() => expect(screen.getByTestId('console-runtime-unavailable')).toBeInTheDocument());
  });

  it('shows adapter initialization errors', async () => {
    vi.spyOn(HTMLCanvasElement.prototype, 'getContext').mockReturnValue({});
    const adapter = {
      create: () => { throw new Error('adapter failed'); },
      destroy: vi.fn(),
      showUserLocation: vi.fn(),
    };
    render(
      <ConsoleStateProvider initialState={state({ runtimeStatus: 'idle' })}>
        <AirspaceMap basemap={{ style: { version: 8, sources: {}, layers: [] } }} adapterFactory={() => adapter} />
      </ConsoleStateProvider>,
    );
    await waitFor(() => expect(adapter.destroy).not.toHaveBeenCalled());
  });

  it('catches render errors inside the console boundary', () => {
    const error = vi.spyOn(console, 'error').mockImplementation(() => {});
    function Crash() { throw new Error('render crash'); }
    render(<ConsoleErrorBoundary><Crash /></ConsoleErrorBoundary>);
    expect(screen.getByTestId('console-runtime-unavailable')).toHaveTextContent('render crash');
    expect(error).toHaveBeenCalled();
  });
});
