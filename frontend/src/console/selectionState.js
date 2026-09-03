export const EMPTY_SELECTION = Object.freeze({ kind: "none", id: null, coordinate: null, properties: {} });

export function selectionReducer(state, action) {
  switch (action.type) {
    case "clear":
      return { ...EMPTY_SELECTION, properties: {} };
    case "coordinate":
      return {
        kind: "coordinate",
        id: null,
        coordinate: [Number(action.coordinate[0]), Number(action.coordinate[1])],
        properties: {},
      };
    case "feature":
      return {
        kind: action.kind || "feature",
        id: action.id ?? null,
        coordinate: Array.isArray(action.coordinate) ? [...action.coordinate] : null,
        properties: { ...(action.properties || {}) },
      };
    default:
      return state;
  }
}

export function selectionToGeoJSON(selection) {
  if (!Array.isArray(selection?.coordinate)) {
    return { type: "FeatureCollection", features: [] };
  }
  return {
    type: "FeatureCollection",
    features: [
      {
        type: "Feature",
        id: selection.id || "console-selection",
        properties: { kind: selection.kind, ...(selection.properties || {}) },
        geometry: { type: "Point", coordinates: [...selection.coordinate] },
      },
    ],
  };
}
