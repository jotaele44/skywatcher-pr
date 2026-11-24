// Catalog of every map data source on the /live airspace map.
//
// The entries, titles, grouping and order mirror the layer menu of the
// adsb.lol web map (tar1090) so the two are functionally equivalent. Every
// URL below is a public upstream endpoint that sends CORS headers and is
// fetched by the browser directly, except openAIP, which needs an API key and
// therefore goes through the backend proxy (/api/console/live/tiles/openaip).
//
// Two adsb.lol layers are served from adsb.lol's private tile proxy, which is
// not intended for third-party sites. They are sourced from the same upstreams
// instead: "ESRI.com Geography Labels" uses Esri's public raster reference
// labels, and "openAIP TMS" uses openAIP's official tile API.

const ESRI_ATTRIBUTION =
  'Powered by <a href="https://www.esri.com">Esri.com</a> — Sources: Esri, i-cubed, USDA, USGS, AEX, GeoEye, Getmapping, Aerogrid, IGN, IGP, UPR-EGP, and the GIS User Community';
const OSM_ATTRIBUTION = '© <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors';
const OFM_ATTRIBUTION = `<a href="https://openfreemap.org">OpenFreeMap</a> ${OSM_ATTRIBUTION}`;
const FAA_CHART_ATTRIBUTION = 'FAA charts, tiles courtesy of <a href="https://tiles.arcgis.com/">arcgis.com</a>';
const TAR1090_ATTRIBUTION = 'Airspace geometry via <a href="https://github.com/wiedehopf/tar1090">tar1090</a>';

// Static airspace GeoJSON is read from tar1090 at a pinned commit so the
// geometry cannot change underneath us. TFRs change constantly and are read
// from the live tar1090-aux feed instead.
export const TAR1090_COMMIT = "5d59b1ba2c5e30eb23f1161940367b7767f10ad5";
const tar1090GeoJson = (file) =>
  `https://raw.githubusercontent.com/wiedehopf/tar1090/${TAR1090_COMMIT}/html/geojson/${file}`;

const wms = (base, layers, extra = "") =>
  `${base}?SERVICE=WMS&VERSION=1.1.1&REQUEST=GetMap&FORMAT=image/png&TRANSPARENT=true&LAYERS=${layers}&SRS=EPSG:3857&STYLES=&WIDTH=256&HEIGHT=256${extra}&BBOX={bbox-epsg-3857}`;

export const GLYPHS_URL = "https://tiles.openfreemap.org/fonts/{fontstack}/{range}.pbf";
export const LABEL_FONT = ["Noto Sans Regular"];

export const LAYER_GROUPS = Object.freeze([
  { id: "world", title: "Worldwide" },
  { id: "us", title: "US" },
  { id: "europe", title: "Europe" },
  { id: "custom", title: "Custom" },
]);

export function utcDateString(date) {
  return date.toISOString().slice(0, 10);
}

export function gibsDate(now = new Date()) {
  return utcDateString(new Date(now.getTime() - 86_400_000));
}

const raster = (id, title, group, tiles, options = {}) => ({
  id,
  title,
  group,
  kind: "raster",
  tiles: Array.isArray(tiles) ? tiles : [tiles],
  tileSize: 256,
  minzoom: 0,
  maxzoom: 19,
  ...options,
});

// Base layers are mutually exclusive (radio buttons in the layer menu).
export const BASE_LAYERS = Object.freeze([
  raster("osm", "OpenStreetMap", "world", "https://tile.openstreetmap.org/{z}/{x}/{y}.png", {
    maxzoom: 19, attribution: OSM_ATTRIBUTION, license: "ODbL-1.0 data; OSMF tile usage policy",
  }),
  raster("esri_satellite", "ESRI.com Satellite", "world",
    "https://services.arcgisonline.com/arcgis/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}.png", {
      maxzoom: 21, attribution: ESRI_ATTRIBUTION, license: "Esri terms of use",
    }),
  raster("osm_de", "OpenStreetMap DE", "world",
    ["a", "b", "c", "d"].map((s) => `https://${s}.tile.openstreetmap.de/{z}/{x}/{y}.png`), {
      maxzoom: 18, attribution: OSM_ATTRIBUTION, license: "ODbL-1.0 data; openstreetmap.de tile policy",
    }),
  ...["bright", "liberty", "positron", "dark", "fiord"].map((name) => ({
    id: `ofm_${name}`,
    title: `OpenFreeMap ${name[0].toUpperCase()}${name.slice(1)}`,
    group: "world",
    kind: "vector-style",
    styleUrl: `https://tiles.openfreemap.org/styles/${name}`,
    attribution: OFM_ATTRIBUTION,
    license: "OpenFreeMap (free, no key); ODbL-1.0 data",
  })),
  raster("esri_sat", "ESRI.com Sat.", "world",
    "https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}", {
      maxzoom: 17, attribution: ESRI_ATTRIBUTION, license: "Esri terms of use",
    }),
  raster("esri_gray", "ESRI.com Gray", "world",
    "https://services.arcgisonline.com/ArcGIS/rest/services/Canvas/World_Light_Gray_Base/MapServer/tile/{z}/{y}/{x}", {
      maxzoom: 16, attribution: ESRI_ATTRIBUTION, license: "Esri terms of use",
    }),
  raster("esri_streets", "ESRI.com Streets", "world",
    "https://services.arcgisonline.com/ArcGIS/rest/services/World_Street_Map/MapServer/tile/{z}/{y}/{x}", {
      maxzoom: 17, attribution: ESRI_ATTRIBUTION, license: "Esri terms of use",
    }),
  {
    id: "gibs",
    title: "GIBS Clouds",
    titleSuffix: "gibs-date",
    group: "world",
    kind: "raster",
    tileSize: 256,
    minzoom: 0,
    maxzoom: 9,
    buildTiles: ({ now = new Date() } = {}) => ["a", "b", "c"].map((s) =>
      `https://gibs-${s}.earthdata.nasa.gov/wmts/epsg3857/best/MODIS_Terra_CorrectedReflectance_TrueColor/default/${gibsDate(now)}/GoogleMapsCompatible_Level9/{z}/{y}/{x}.jpg`),
    attribution: 'MODIS Terra imagery provided by NASA Global Imagery Browse Services (<a href="https://earthdata.nasa.gov/gibs">GIBS</a>)',
    license: "NASA open data",
  },
  raster("vfr_sectional", "VFR Sectional Chart", "us",
    "https://tiles.arcgis.com/tiles/ssFJjBXIUyZDrSYZ/arcgis/rest/services/VFR_Sectional/MapServer/tile/{z}/{y}/{x}", {
      minzoom: 8, maxzoom: 12, attribution: FAA_CHART_ATTRIBUTION, license: "FAA public charts",
    }),
  raster("vfr_terminal", "VFR Terminal Chart", "us",
    "https://tiles.arcgis.com/tiles/ssFJjBXIUyZDrSYZ/arcgis/rest/services/VFR_Terminal/MapServer/tile/{z}/{y}/{x}", {
      minzoom: 10, maxzoom: 12, attribution: FAA_CHART_ATTRIBUTION, license: "FAA public charts",
    }),
  raster("ifr_low", "IFR Enroute Chart Low", "us",
    "https://tiles.arcgis.com/tiles/ssFJjBXIUyZDrSYZ/arcgis/rest/services/IFR_AreaLow/MapServer/tile/{z}/{y}/{x}", {
      minzoom: 8, maxzoom: 11, attribution: FAA_CHART_ATTRIBUTION, license: "FAA public charts",
    }),
  raster("ifr_high", "IFR Enroute Chart High", "us",
    "https://tiles.arcgis.com/tiles/ssFJjBXIUyZDrSYZ/arcgis/rest/services/IFR_High/MapServer/tile/{z}/{y}/{x}", {
      minzoom: 7, maxzoom: 11, attribution: FAA_CHART_ATTRIBUTION, license: "FAA public charts",
    }),
]);

const geojson = (id, title, group, url, fill, stroke, options = {}) => ({
  id,
  title,
  group,
  kind: "geojson",
  url,
  fill,
  stroke,
  showLabel: true,
  labelField: "name",
  attribution: TAR1090_ATTRIBUTION,
  license: "Geometry derived from public AIP publications, distributed with tar1090",
  ...options,
});

// Overlays stack independently (checkboxes in the layer menu).
export const OVERLAYS = Object.freeze([
  raster("esri_geography_labels", "ESRI.com Geography Labels", "world",
    "https://services.arcgisonline.com/arcgis/rest/services/Reference/World_Boundaries_and_Places/MapServer/tile/{z}/{y}/{x}", {
      maxzoom: 19, opacity: 0.7, attribution: ESRI_ATTRIBUTION, license: "Esri terms of use",
    }),
  raster("openaip", "openAIP TMS", "world", "/api/console/live/tiles/openaip/{z}/{x}/{y}.png", {
    maxzoom: 14, opacity: 0.7, requires: "openaip_key", proxied: true,
    attribution: '<a href="https://www.openaip.net">openAIP.net</a>', license: "openAIP CC BY-NC 4.0; API key required",
  }),
  {
    id: "rainviewer",
    title: "RainViewer Radar",
    group: "world",
    kind: "rainviewer",
    indexUrl: "https://api.rainviewer.com/public/weather-maps.json",
    tileSize: 512,
    maxzoom: 7,
    opacity: 0.3,
    refreshMs: 2 * 60_000,
    attribution: '<a href="https://www.rainviewer.com/api.html">RainViewer.com</a>',
    license: "RainViewer public API",
  },
  geojson("tfrs", "TFRs", "us", "https://raw.githubusercontent.com/wiedehopf/tar1090-aux/master/tfrs.geojson",
    "rgba(255, 0, 0, 0.08)", "rgb(255, 0, 0)", {
      lineWidth: 2, opacity: 0.7, labelExpression: ["concat", ["coalesce", ["get", "NOTAM_KEY"], ""], "\n", ["coalesce", ["get", "LEGAL"], ""]],
      refreshMs: 5 * 60_000, attribution: 'TFRs via FAA, hosted by <a href="https://github.com/wiedehopf/tar1090-aux">tar1090-aux</a>',
      license: "FAA public data",
    }),
  {
    id: "sua",
    title: "Special Use Airspace",
    group: "us",
    kind: "geojson",
    url: "https://opendata.arcgis.com/datasets/dd0d1b726e504137ab3c41b21835d05b_0.geojson",
    // Prohibited / restricted / warning areas blue; alert areas and MOAs maroon.
    fill: ["match", ["get", "TYPE_CODE"], ["P", "R", "W"], "rgba(72, 149, 239, 0.3)", ["A", "MOA"], "rgba(133, 45, 69, 0.3)", "rgba(0, 0, 0, 0)"],
    stroke: ["match", ["get", "TYPE_CODE"], ["P", "R", "W"], "rgba(72, 149, 239, 1)", ["A", "MOA"], "rgba(133, 45, 69, 1)", "rgba(0, 0, 0, 0)"],
    lineWidth: 2,
    showLabel: false,
    attribution: 'Special Use Airspace: FAA via <a href="https://adds-faa.opendata.arcgis.com/">ADDS open data</a>',
    license: "FAA public data",
  },
  {
    ...raster("nexrad", "NEXRAD", "us", "https://mesonet.agron.iastate.edu/cache/tile.py/1.0.0/nexrad-n0q-900913/{z}/{x}/{y}.png", {
      maxzoom: 8, opacity: 0.35, refreshMs: 2 * 60_000, cacheBust: true,
      attribution: 'NEXRAD courtesy of <a href="https://mesonet.agron.iastate.edu/">IEM</a>', license: "IEM public service",
    }),
    tiles: [1, 2, 3].map((n) => `https://mesonet${n}.agron.iastate.edu/cache/tile.py/1.0.0/nexrad-n0q-900913/{z}/{x}/{y}.png`),
  },
  raster("noaa_sat", "NOAA Infrared Sat", "us", wms("https://nowcoast.noaa.gov/geoserver/satellite/wms", "global_longwave_imagery_mosaic"), {
    maxzoom: 7.99, opacity: 0.35, refreshMs: 15 * 60_000, cacheBust: true, bounds: [-171, 9, -51, 69],
    attribution: '<a href="https://nowcoast.noaa.gov/">NOAA</a>', license: "NOAA public data",
  }),
  raster("noaa_radar", "NOAA Radar", "us", wms("https://nowcoast.noaa.gov/geoserver/weather_radar/wms", "base_reflectivity_mosaic"), {
    maxzoom: 7.99, opacity: 0.35, refreshMs: 5 * 60_000, cacheBust: true, bounds: [-171, 9, -51, 69],
    attribution: '<a href="https://nowcoast.noaa.gov/">NOAA</a>', license: "NOAA public data",
  }),
  geojson("us_a2a_refueling", "US A2A Refueling", "us", tar1090GeoJson("US_A2A_refueling.geojson"),
    "rgba(52, 50, 168, 0.3)", "rgba(52, 50, 168, 1)"),
  geojson("us_artcc", "US ARTCC Boundaries", "us", tar1090GeoJson("US_ARTCC_boundaries.geojson"),
    "rgba(255, 0, 255, 0.3)", "rgba(255, 0, 255, 1)", { showLabel: false }),
  {
    ...raster("dwd_radolan", "DWD RADOLAN", "europe", wms("https://maps.dwd.de/geoserver/wms", "dwd:RADOLAN-RY", "&validtime={validtime}"), {
      maxzoom: 8, opacity: 0.3, refreshMs: 15_000, bounds: [1.9, 46.2, 16.0, 55.0],
      attribution: "Deutscher Wetterdienst (DWD)", license: "DWD open data (GeoNutzV)",
    }),
    validTime: true,
  },
  geojson("pl_awacs", "PL AWACS Orbits", "europe", tar1090GeoJson("PL_Mil_AWACS_Orbits.geojson"),
    "rgba(252, 186, 3, 0.3)", "rgba(252, 186, 3, 1)", { showLabel: false }),
  geojson("nl_awacs", "NL AWACS Orbits", "europe", tar1090GeoJson("NL_Mil_AWACS_Orbits.geojson"),
    "rgba(252, 186, 3, 0.3)", "rgba(252, 186, 3, 1)", { showLabel: false }),
  geojson("de_awacs", "DE AWACS Orbits", "europe", tar1090GeoJson("DE_Mil_AWACS_Orbits.geojson"),
    "rgba(252, 186, 3, 0.3)", "rgba(252, 186, 3, 1)", { showLabel: false }),
  geojson("de_lfa", "DE Low Flying Areas", "europe", tar1090GeoJson("DE_Mil_LFA.geojson"),
    "rgba(255, 60, 0, 0.25)", "rgba(255, 60, 0, 1)", { showLabel: false }),
  geojson("uk_radar_corridors", "UK Radar Corridors", "europe", tar1090GeoJson("UK_Mil_RC.geojson"),
    "rgba(22, 171, 22, 0.3)", "rgba(22, 171, 22, 1)"),
  geojson("uk_a2a_refueling", "UK A2A Refueling", "europe", tar1090GeoJson("UK_Mil_AAR_Zones.geojson"),
    "rgba(52, 50, 168, 0.3)", "rgba(52, 50, 168, 1)"),
  geojson("uk_awacs", "UK AWACS Orbits", "europe", tar1090GeoJson("UK_Mil_AWACS_Orbits.geojson"),
    "rgba(252, 186, 3, 0.3)", "rgba(252, 186, 3, 1)", { showLabel: false }),
]);

// Aircraft and map-feature layers listed at the top of the layer menu.
export const FEATURE_LAYERS = Object.freeze([
  { id: "aircraftWebGL", title: "Aircraft pos. webGL", description: "GPU icon renderer; off falls back to simple dots for weak devices." },
  { id: "aircraftPositions", title: "Aircraft positions" },
  { id: "aircraftTrails", title: "Aircraft trails", heading: true },
  { id: "yourPosition", title: "Your position" },
  { id: "rangeRings", title: "Range rings" },
]);

export const DEFAULT_BASE_LAYER = "esri_satellite";

export function layerTitle(entry, now = new Date()) {
  return entry.titleSuffix === "gibs-date" ? `${entry.title} ${gibsDate(now)}` : entry.title;
}

export function findBaseLayer(id) {
  return BASE_LAYERS.find((entry) => entry.id === id) || null;
}

export function findOverlay(id) {
  return OVERLAYS.find((entry) => entry.id === id) || null;
}

// Resolve the tile URL templates for a raster entry at a given moment.
export function resolveTiles(entry, { now = new Date(), apiBase = "" } = {}) {
  let tiles = entry.buildTiles ? entry.buildTiles({ now }) : [...(entry.tiles || [])];
  if (entry.validTime) {
    // DWD publishes RADOLAN every 5 minutes; key requests to that bucket
    // (epoch seconds, as the adsb.lol map does).
    const ms = now.getTime();
    const bucket = (ms - (ms % 300_000)) / 1000;
    tiles = tiles.map((url) => url.replace("{validtime}", String(bucket)));
  }
  if (entry.cacheBust && entry.refreshMs) {
    const bucket = Math.floor(now.getTime() / entry.refreshMs);
    tiles = tiles.map((url) => `${url}${url.includes("?") ? "&" : "?"}_=${bucket}`);
  }
  if (entry.proxied && apiBase) {
    tiles = tiles.map((url) => (url.startsWith("/api/") ? `${apiBase.replace(/\/api$/, "")}${url}` : url));
  }
  return tiles;
}

// Validate a user-supplied custom XYZ template (the "Custom" group).
export function validateCustomTemplate(template) {
  const value = String(template || "").trim();
  if (!/^https:\/\//i.test(value)) return "Custom tile URL must start with https://";
  if (!value.includes("{z}") || !value.includes("{x}") || !value.includes("{y}")) {
    return "Custom tile URL must contain {z}, {x} and {y}";
  }
  return null;
}

export function customBaseLayer(template) {
  return raster("custom_tiles", "Custom tiles", "custom", template, {
    maxzoom: 19, attribution: "Custom tiles (user supplied)", license: "user supplied",
  });
}

export const ALL_SOURCES = Object.freeze([...BASE_LAYERS, ...OVERLAYS]);
