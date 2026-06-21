import React, { createContext, useContext, useEffect, useState, useCallback } from "react";
import { federation } from "@/api/federationClient";

const DataContext = createContext(null);

const ENTITIES = {
  observations: "AirspaceObservations",
  aircraft: "AircraftProfiles",
  captures: "FR24Captures",
  routes: "RouteSegments",
  assets: "InfrastructureAssets",
  links: "AirspaceAssetLinks",
  airports: "PRAirports",
  reviews: "ManualReviewItems",
  exports: "ExportPackages",
  readiness: "ReadinessReports",
  syncs: "FederationSyncEvents",
};

export function SkywatcherDataProvider({ children }) {
  const [data, setData] = useState({
    observations: [], aircraft: [], captures: [], routes: [], assets: [],
    links: [], airports: [], reviews: [], exports: [], readiness: [], syncs: [],
  });
  const [loading, setLoading] = useState(true);

  const loadAll = useCallback(async () => {
    const keys = Object.keys(ENTITIES);
    try {
      // allSettled + finally: a single failed/missing collection (e.g. no
      // backend yet, or a 401 before login) must not trap the UI on the spinner.
      const results = await Promise.allSettled(
        keys.map((k) => federation.entities[ENTITIES[k]].list("-created_date", 500))
      );
      const next = {};
      keys.forEach((k, i) => {
        next[k] = results[i].status === "fulfilled" ? (results[i].value || []) : [];
      });
      setData(next);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => { loadAll(); }, [loadAll]);

  // Optimistic local update + persisted write
  const updateRecord = useCallback(async (collection, id, patch) => {
    const entityName = ENTITIES[collection];
    setData((prev) => ({
      ...prev,
      [collection]: prev[collection].map((r) => (r.id === id ? { ...r, ...patch } : r)),
    }));
    await federation.entities[entityName].update(id, patch);
  }, []);

  const createReview = useCallback(async (payload) => {
    const created = await federation.entities.ManualReviewItems.create(payload);
    setData((prev) => ({ ...prev, reviews: [created, ...prev.reviews] }));
    return created;
  }, []);

  return (
    <DataContext.Provider value={{ ...data, loading, reload: loadAll, updateRecord, createReview }}>
      {children}
    </DataContext.Provider>
  );
}

export function useSkywatcher() {
  const ctx = useContext(DataContext);
  if (!ctx) throw new Error("useSkywatcher must be used within SkywatcherDataProvider");
  return ctx;
}

// Resolver helpers
export function useResolvers() {
  const d = useSkywatcher();
  return {
    observationById: (id) => d.observations.find((o) => o.observation_id === id),
    aircraftByTail: (tail) => d.aircraft.find((a) => a.tail_number === tail),
    aircraftById: (id) => d.aircraft.find((a) => a.aircraft_id === id),
    captureById: (id) => d.captures.find((c) => c.capture_id === id),
    routeById: (id) => d.routes.find((r) => r.route_segment_id === id),
    assetById: (id) => d.assets.find((a) => a.asset_id === id),
    airportById: (id) => d.airports.find((a) => a.airport_id === id),
    linksForObservation: (obsId) => d.links.filter((l) => l.observation_id === obsId),
    linksForAsset: (assetId) => d.links.filter((l) => l.asset_id === assetId),
    observationsForAsset: (assetId) =>
      d.observations.filter((o) => (o.linked_asset_ids || []).includes(assetId) || o.nearest_asset_id === assetId),
    observationsForAircraft: (tail) => d.observations.filter((o) => o.tail_number === tail),
    routesForCapture: (capId) => d.routes.filter((r) => r.capture_id === capId),
    routesForObservation: (obsId) => d.routes.filter((r) => r.observation_id === obsId),
    observationsForCapture: (capId) => d.observations.filter((o) => o.linked_capture_id === capId),
    observationsForAirport: (aptId) => d.observations.filter((o) => o.nearest_airport_id === aptId),
    routesForAircraftTail: (tail) => {
      const obsIds = d.observations.filter((o) => o.tail_number === tail).map((o) => o.observation_id);
      return d.routes.filter((r) => obsIds.includes(r.observation_id));
    },
    linksForAircraftTail: (tail) => {
      const obsIds = d.observations.filter((o) => o.tail_number === tail).map((o) => o.observation_id);
      return d.links.filter((l) => obsIds.includes(l.observation_id));
    },
    reviewItemTarget: (item) => {
      switch (item.item_type) {
        case "observation": return { kind: "observation", rec: d.observations.find((o) => o.observation_id === item.item_id) };
        case "capture": return { kind: "capture", rec: d.captures.find((c) => c.capture_id === item.item_id) };
        case "route_segment": return { kind: "route", rec: d.routes.find((r) => r.route_segment_id === item.item_id) };
        case "asset_link": return { kind: "link", rec: d.links.find((l) => l.link_id === item.item_id) };
        case "aircraft_profile": return { kind: "aircraft", rec: d.aircraft.find((a) => a.aircraft_id === item.item_id) };
        case "export_package": return { kind: "export", rec: d.exports.find((e) => e.package_id === item.item_id) };
        default: return { kind: null, rec: null };
      }
    },
  };
}