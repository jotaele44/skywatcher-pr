import React from 'react';
import { render, screen, waitFor } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';

vi.mock('@/components/console/AirspaceConsoleShell', () => ({
  AirspaceConsoleShell: () => <div data-testid="console-shell-loaded">loaded</div>,
}));

import { AirspaceConsole } from '@/pages/AirspaceConsole';

const payload = {
  capabilities: {
    capabilities: [
      { id: 'map_navigation', status: 'available', reason: 'ready' },
      { id: 'geolocation', status: 'available', reason: 'ready' },
      { id: 'basemap_controls', status: 'available', reason: 'ready' },
    ],
    policy: { offline_console_startup: true },
  },
  repositories: { repositories: [] },
};

afterEach(() => vi.unstubAllEnvs());

describe('AirspaceConsole page', () => {
  it('loads capability and repository contracts before rendering the shell', async () => {
    const client = {
      capabilities: vi.fn(async () => payload.capabilities),
      repositories: vi.fn(async () => payload.repositories),
    };
    render(<AirspaceConsole client={client} />);
    expect(screen.getByText(/Loading console capabilities/)).toBeInTheDocument();
    await waitFor(() => expect(screen.getByTestId('console-shell-loaded')).toBeInTheDocument());
    expect(client.capabilities).toHaveBeenCalledOnce();
    expect(client.repositories).toHaveBeenCalledOnce();
  });

  it('fails visibly when capability bootstrap fails', async () => {
    const client = {
      capabilities: vi.fn(async () => { throw new Error('backend unavailable'); }),
      repositories: vi.fn(async () => payload.repositories),
    };
    render(<AirspaceConsole client={client} />);
    await waitFor(() => expect(screen.getByTestId('console-runtime-unavailable')).toHaveTextContent('backend unavailable'));
  });

  it('honors the feature kill switch without loading the bootstrap client', () => {
    vi.stubEnv('VITE_SKYWATCHER_CONSOLE_ENABLED', 'false');
    const client = { capabilities: vi.fn(), repositories: vi.fn() };
    render(<AirspaceConsole client={client} />);
    expect(screen.getByTestId('console-runtime-unavailable')).toHaveTextContent('kill switch');
    expect(client.capabilities).not.toHaveBeenCalled();
  });
});
