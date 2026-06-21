import React, { createContext, useContext, useState, useCallback } from "react";
import ObservationDetailDrawer from "./ObservationDetailDrawer";
import AircraftDetailDrawer from "./AircraftDetailDrawer";
import CaptureDetailDrawer from "./CaptureDetailDrawer";
import RouteDetailDrawer from "./RouteDetailDrawer";
import AssetDetailDrawer from "./AssetDetailDrawer";
import ExportDetailDrawer from "./ExportDetailDrawer";
import ReviewDetailDrawer from "./ReviewDetailDrawer";

const DrawerContext = createContext(null);

export function DrawerHubProvider({ children }) {
  // stack of { kind, id }
  const [stack, setStack] = useState([]);

  const push = useCallback((kind, id) => setStack((s) => [...s, { kind, id }]), []);
  const replace = useCallback((kind, id) => setStack((s) => [...s.slice(0, -1), { kind, id }]), []);
  const closeAll = useCallback(() => setStack([]), []);

  const open = {
    observation: (id) => push("observation", id),
    aircraft: (id) => push("aircraft", id),
    capture: (id) => push("capture", id),
    route: (id) => push("route", id),
    asset: (id) => push("asset", id),
    export: (id) => push("export", id),
    review: (id) => push("review", id),
  };
  // navigate within same drawer slot (relationship jump)
  const go = {
    observation: (id) => replace("observation", id),
    aircraft: (id) => replace("aircraft", id),
    capture: (id) => replace("capture", id),
    route: (id) => replace("route", id),
    asset: (id) => replace("asset", id),
    export: (id) => replace("export", id),
    review: (id) => replace("review", id),
  };

  const top = stack[stack.length - 1];
  const onClose = () => setStack((s) => s.slice(0, -1));

  return (
    <DrawerContext.Provider value={{ open, go, closeAll }}>
      {children}
      {top?.kind === "observation" && <ObservationDetailDrawer id={top.id} onClose={onClose} go={go} />}
      {top?.kind === "aircraft" && <AircraftDetailDrawer id={top.id} onClose={onClose} go={go} />}
      {top?.kind === "capture" && <CaptureDetailDrawer id={top.id} onClose={onClose} go={go} />}
      {top?.kind === "route" && <RouteDetailDrawer id={top.id} onClose={onClose} go={go} />}
      {top?.kind === "asset" && <AssetDetailDrawer id={top.id} onClose={onClose} go={go} />}
      {top?.kind === "export" && <ExportDetailDrawer id={top.id} onClose={onClose} go={go} />}
      {top?.kind === "review" && <ReviewDetailDrawer id={top.id} onClose={onClose} go={go} />}
    </DrawerContext.Provider>
  );
}

export function useDrawers() {
  const ctx = useContext(DrawerContext);
  if (!ctx) throw new Error("useDrawers must be used within DrawerHubProvider");
  return ctx;
}