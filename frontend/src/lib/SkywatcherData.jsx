import React, { createContext, useContext, useEffect, useState, useCallback } from 'react';
import { useLocation } from 'react-router-dom';
import { federation } from '@/api/federationClient';

const DataContext = createContext(null);

const ENTITIES = {
  observations: 'AirspaceObservations',
  aircraft: 'AircraftProfiles',
  captures: 'FR24Captures',
  routes: 'RouteSegments',
  assets: 'InfrastructureAssets',
  links: 'AirspaceAssetLinks',
  airports: 'PRAirports',
  reviews: 'ManualReviewItems',
  exports: 'ExportPackages',
  readiness: 'ReadinessReports',
  syncs: 'FederationSyncEvents',
};

const EMPTY_DATA = Object.freeze({
  observations: [], aircraft: [], captures: [], routes: [], assets: [],
  links: [], airports: [], reviews: [], exports: [], readiness: [], syncs: [],
});

export function SkywatcherDataProvider({ children }) {
  const { pathname } = useLocation();
  const consoleMode = pathname.startsWith('/console');
  const [data, setData] = useState(EMPTY_DATA);
  const [loading, setLoading] = useState(!consoleMode);

  const loadAll = useCallback(async () => {
    if (consoleMode) {
      setData(EMPTY_DATA);
      setLoading(false);
      return;
    }
    setLoading(true);
    const keys = Object.keys(ENTITIES);
    try {
      const results = await Promise.allSettled(
        keys.map((key) => federation.entities[ENTITIES[key]].list('-created_date', 500)),
      );
      const next = {};
      keys.forEach((key, index) => {
        next[key] = results[index].status === 'fulfilled' ? (results[index].value || []) : [];
      });
      setData(next);
    } finally {
      setLoading(false);
    }
  }, [consoleMode]);

  useEffect(() => { loadAll(); }, [loadAll]);

  const updateRecord = useCallback(async (collection, id, patch) => {
    const entityName = ENTITIES[collection];
    setData((previous) => ({
      ...previous,
      [collection]: previous[collection].map((record) => (record.id === id ? { ...record, ...patch } : record)),
    }));
    await federation.entities[entityName].update(id, patch);
  }, []);

  const createReview = useCallback(async (payload) => {
    const created = await federation.entities.ManualReviewItems.create(payload);
    setData((previous) => ({ ...previous, reviews: [created, ...previous.reviews] }));
    return created;
  }, []);

  return (
    <DataContext.Provider value={{ ...data, loading, reload: loadAll, updateRecord, createReview }}>
      {children}
    </DataContext.Provider>
  );
}

export function useSkywatcher() {
  const value = useContext(DataContext);
  if (!value) throw new Error('useSkywatcher must be used within SkywatcherDataProvider');
  return value;
}

export function useResolvers() {
  const data = useSkywatcher();
  return {
    observationById: (id) => data.observations.find((record) => record.observation_id === id),
    aircraftByTail: (tail) => data.aircraft.find((record) => record.tail_number === tail),
    aircraftById: (id) => data.aircraft.find((record) => record.aircraft_id === id),
    captureById: (id) => data.captures.find((record) => record.capture_id === id),
    routeById: (id) => data.routes.find((record) => record.route_segment_id === id),
    assetById: (id) => data.assets.find((record) => record.asset_id === id),
    airportById: (id) => data.airports.find((record) => record.airport_id === id),
    linksForObservation: (id) => data.links.filter((record) => record.observation_id === id),
    linksForAsset: (id) => data.links.filter((record) => record.asset_id === id),
    observationsForAsset: (id) => data.observations.filter((record) => (record.linked_asset_ids || []).includes(id) || record.nearest_asset_id === id),
    observationsForAircraft: (tail) => data.observations.filter((record) => record.tail_number === tail),
    routesForCapture: (id) => data.routes.filter((record) => record.capture_id === id),
    routesForObservation: (id) => data.routes.filter((record) => record.observation_id === id),
    observationsForCapture: (id) => data.observations.filter((record) => record.linked_capture_id === id),
    observationsForAirport: (id) => data.observations.filter((record) => record.nearest_airport_id === id),
    routesForAircraftTail: (tail) => {
      const observationIds = data.observations.filter((record) => record.tail_number === tail).map((record) => record.observation_id);
      return data.routes.filter((record) => observationIds.includes(record.observation_id));
    },
    linksForAircraftTail: (tail) => {
      const observationIds = data.observations.filter((record) => record.tail_number === tail).map((record) => record.observation_id);
      return data.links.filter((record) => observationIds.includes(record.observation_id));
    },
    reviewItemTarget: (item) => {
      switch (item.item_type) {
        case 'observation': return { kind: 'observation', rec: data.observations.find((record) => record.observation_id === item.item_id) };
        case 'capture': return { kind: 'capture', rec: data.captures.find((record) => record.capture_id === item.item_id) };
        case 'route_segment': return { kind: 'route', rec: data.routes.find((record) => record.route_segment_id === item.item_id) };
        case 'asset_link': return { kind: 'link', rec: data.links.find((record) => record.link_id === item.item_id) };
        case 'aircraft_profile': return { kind: 'aircraft', rec: data.aircraft.find((record) => record.aircraft_id === item.item_id) };
        case 'export_package': return { kind: 'export', rec: data.exports.find((record) => record.package_id === item.item_id) };
        default: return { kind: null, rec: null };
      }
    },
  };
}
