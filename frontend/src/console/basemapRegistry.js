export const LOCAL_BLANK_STYLE_ID = "local-blank-diagnostic";

const LOCAL_BLANK_STYLE = Object.freeze({
  version: 8,
  name: "Skywatcher Local Blank Diagnostic",
  metadata: {
    "skywatcher:offline": true,
    "skywatcher:diagnostic_only": true,
    "skywatcher:provider_keys_required": false,
  },
  sources: {},
  layers: [
    {
      id: "skywatcher-diagnostic-background",
      type: "background",
      paint: {
        "background-color": "#071019",
      },
    },
  ],
});

const REGISTRY = Object.freeze({
  [LOCAL_BLANK_STYLE_ID]: Object.freeze({
    id: LOCAL_BLANK_STYLE_ID,
    label: "Local blank diagnostic",
    description: "Offline MapLibre canvas with no remote tiles, glyphs, sprites, or provider keys.",
    networkRequired: false,
    providerKeysRequired: false,
    attribution: "Skywatcher-PR diagnostic canvas · MapLibre GL JS",
    style: LOCAL_BLANK_STYLE,
  }),
});

export function listBasemaps() {
  return Object.values(REGISTRY).map((entry) => ({ ...entry, style: structuredClone(entry.style) }));
}

export function getBasemap(id = LOCAL_BLANK_STYLE_ID) {
  const entry = REGISTRY[id];
  if (!entry) throw new Error(`Unknown basemap: ${id}`);
  return { ...entry, style: structuredClone(entry.style) };
}

export function assertOfflineStyle(style) {
  const serialized = JSON.stringify(style).toLowerCase();
  const forbidden = ["http://", "https://", "mapbox://", "access_token", "api_key", "apikey="];
  const hit = forbidden.find((token) => serialized.includes(token));
  if (hit) throw new Error(`Offline style contains forbidden network or credential token: ${hit}`);
  return true;
}

assertOfflineStyle(LOCAL_BLANK_STYLE);
