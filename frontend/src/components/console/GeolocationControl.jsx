import React, { useState } from 'react';
import { LocateFixed, LoaderCircle } from 'lucide-react';

export function GeolocationControl({ disabled = false, onLocation, onStatusChange, navigatorRef = globalThis.navigator }) {
  const [status, setStatus] = useState('idle');

  const updateStatus = (next, detail) => {
    setStatus(next);
    onStatusChange?.(next, detail);
  };

  const requestLocation = () => {
    if (disabled || status === 'requesting') return;
    const geolocation = navigatorRef?.geolocation;
    if (!geolocation) {
      updateStatus('unavailable', 'Browser geolocation is unavailable.');
      return;
    }
    updateStatus('requesting');
    geolocation.getCurrentPosition(
      (position) => {
        const location = {
          longitude: position.coords.longitude,
          latitude: position.coords.latitude,
          accuracy: position.coords.accuracy || 0,
        };
        updateStatus('ready', location);
        onLocation?.(location);
      },
      (error) => updateStatus('denied', error?.message || 'Location permission was denied.'),
      { enableHighAccuracy: false, timeout: 10_000, maximumAge: 0 },
    );
  };

  return (
    <button
      type="button"
      onClick={requestLocation}
      disabled={disabled || status === 'requesting'}
      className="inline-flex h-9 items-center gap-2 rounded-md border border-border bg-secondary px-3 text-xs font-medium text-foreground hover:bg-secondary/80 disabled:cursor-not-allowed disabled:opacity-50"
      aria-label="Center map on my current location"
      data-testid="geolocation-control"
    >
      {status === 'requesting' ? <LoaderCircle className="h-4 w-4 animate-spin" aria-hidden="true" /> : <LocateFixed className="h-4 w-4" aria-hidden="true" />}
      Locate me
    </button>
  );
}
