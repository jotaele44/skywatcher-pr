import React, { useEffect, useRef } from 'react';
import maplibregl from 'maplibre-gl';
import 'maplibre-gl/dist/maplibre-gl.css';
import { useAppStore } from '../state/store';

/**
 * MapPane renders a MapLibre map centered on Puerto Rico. It
 * initializes the map on mount and cleans it up on unmount. A
 * simple click handler demonstrates how to update the global
 * selection state. Replace this with real map layers and feature
 * selection logic once geospatial data is available.
 */
export const MapPane: React.FC = () => {
  const mapContainer = useRef<HTMLDivElement>(null);
  const setSelection = useAppStore((s) => s.setSelection);

  useEffect(() => {
    if (!mapContainer.current) return;

    const map = new maplibregl.Map({
      container: mapContainer.current,
      style: 'https://demotiles.maplibre.org/style.json',
      center: [-66.1057, 18.4655],
      zoom: 8,
    });

    // Example click event that sets a dummy selection. Replace this with
    // feature identification when real layers are loaded.
    map.on('click', () => {
      setSelection({ id: 'dummy-site', type: 'site' });
    });

    return () => {
      map.remove();
    };
  }, [setSelection]);

  return <div ref={mapContainer} style={{ width: '100%', height: '300px' }} />;
};