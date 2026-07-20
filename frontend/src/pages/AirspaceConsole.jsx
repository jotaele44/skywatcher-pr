import React, { useEffect, useMemo } from 'react';
import { AirspaceConsoleShell } from '@/components/console/AirspaceConsoleShell';
import { ConsoleApiClient, loadConsoleBootstrap } from '@/components/console/ConsoleApiClient';
import { ConsoleErrorBoundary } from '@/components/console/ConsoleErrorBoundary';
import { ConsoleStateProvider, useConsoleState } from '@/components/console/ConsoleStateContext';
import { isConsoleEnabled } from '@/components/console/consoleDefaults';
import { RuntimeUnavailable } from '@/components/console/RuntimeUnavailable';

function ConsoleBootstrap({ client = new ConsoleApiClient() }) {
  const { state, dispatch } = useConsoleState();

  useEffect(() => {
    const controller = new AbortController();
    dispatch({ type: 'bootstrap/loading' });
    loadConsoleBootstrap(client, { signal: controller.signal })
      .then(({ capabilities, repositories }) => {
        dispatch({ type: 'bootstrap/ready', capabilities, repositories });
      })
      .catch((error) => {
        if (error?.name !== 'AbortError') dispatch({ type: 'bootstrap/error', error: error?.message });
      });
    return () => controller.abort();
  }, [client, dispatch]);

  if (state.bootstrapStatus === 'idle' || state.bootstrapStatus === 'loading') {
    return (
      <div className="flex h-full items-center justify-center bg-[hsl(220_34%_4%)] text-sm text-muted-foreground" role="status">
        Loading console capabilities…
      </div>
    );
  }
  if (state.bootstrapStatus === 'degraded') {
    return <RuntimeUnavailable title="Console capability service unavailable" reason={state.runtimeError || 'The local capability contract could not be loaded.'} />;
  }
  return <AirspaceConsoleShell />;
}

export function AirspaceConsole({ client }) {
  const resolvedClient = useMemo(() => client || new ConsoleApiClient(), [client]);
  if (!isConsoleEnabled()) {
    return <RuntimeUnavailable title="Interactive console disabled" reason="The VITE_SKYWATCHER_CONSOLE_ENABLED kill switch is set to false." />;
  }
  return (
    <ConsoleErrorBoundary>
      <ConsoleStateProvider>
        <ConsoleBootstrap client={resolvedClient} />
      </ConsoleStateProvider>
    </ConsoleErrorBoundary>
  );
}

export default AirspaceConsole;
