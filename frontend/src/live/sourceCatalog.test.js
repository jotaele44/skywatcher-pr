import { describe, expect, it } from "vitest";
import {
  ALL_SOURCES, BASE_LAYERS, FEATURE_LAYERS, LAYER_GROUPS, OVERLAYS, TAR1090_COMMIT,
  customBaseLayer, gibsDate, layerTitle, resolveTiles, validateCustomTemplate,
} from "./sourceCatalog";

// Every entry visible in the adsb.lol layer menu of the reference recording,
// in on-screen order.
const VIDEO_MENU = {
  features: ["Aircraft pos. webGL", "Aircraft positions", "Aircraft trails", "Your position", "Range rings"],
  world: [
    "OpenStreetMap", "ESRI.com Satellite", "OpenStreetMap DE", "OpenFreeMap Bright", "OpenFreeMap Liberty",
    "OpenFreeMap Positron", "OpenFreeMap Dark", "OpenFreeMap Fiord", "ESRI.com Sat.", "ESRI.com Gray",
    "ESRI.com Streets", "GIBS Clouds", "ESRI.com Geography Labels", "openAIP TMS", "RainViewer Radar",
  ],
  us: [
    "VFR Sectional Chart", "VFR Terminal Chart", "IFR Enroute Chart Low", "IFR Enroute Chart High", "TFRs",
    "Special Use Airspace", "NEXRAD", "NOAA Infrared Sat", "NOAA Radar", "US A2A Refueling", "US ARTCC Boundaries",
  ],
  europe: [
    "DWD RADOLAN", "PL AWACS Orbits", "NL AWACS Orbits", "DE AWACS Orbits", "DE Low Flying Areas",
    "UK Radar Corridors", "UK A2A Refueling", "UK AWACS Orbits",
  ],
};

const titlesFor = (group) => [...BASE_LAYERS, ...OVERLAYS].filter((e) => e.group === group).map((e) => e.title);

describe("live source catalog", () => {
  it("covers every layer of the reference layer menu in the same order", () => {
    expect(FEATURE_LAYERS.map((f) => f.title)).toEqual(VIDEO_MENU.features);
    expect(titlesFor("world")).toEqual(VIDEO_MENU.world);
    expect(titlesFor("us")).toEqual(VIDEO_MENU.us);
    expect(titlesFor("europe")).toEqual(VIDEO_MENU.europe);
    expect(LAYER_GROUPS.map((g) => g.title)).toEqual(["Worldwide", "US", "Europe", "Custom"]);
  });

  it("gives every source a unique id, attribution and licence note", () => {
    const ids = ALL_SOURCES.map((e) => e.id);
    expect(new Set(ids).size).toBe(ids.length);
    for (const entry of ALL_SOURCES) {
      expect(entry.attribution, entry.id).toBeTruthy();
      expect(entry.license, entry.id).toBeTruthy();
    }
  });

  it("uses https upstreams except the key-gated openAIP proxy", () => {
    for (const entry of ALL_SOURCES) {
      const urls = [...(entry.tiles || []), entry.url, entry.styleUrl, entry.indexUrl, ...(entry.buildTiles ? entry.buildTiles({ now: new Date() }) : [])].filter(Boolean);
      expect(urls.length, entry.id).toBeGreaterThan(0);
      for (const url of urls) {
        if (entry.proxied) expect(url.startsWith("/api/console/live/tiles/")).toBe(true);
        else expect(url.startsWith("https://"), `${entry.id}: ${url}`).toBe(true);
        expect(url).not.toMatch(/adsb\.lol|adsbexchange/);
        expect(url).not.toMatch(/api[_-]?key=|access_token/i);
      }
    }
    expect(OVERLAYS.find((e) => e.id === "openaip").requires).toBe("openaip_key");
  });

  it("pins static airspace geometry to a tar1090 commit", () => {
    const pinned = OVERLAYS.filter((e) => e.kind === "geojson" && e.url.includes("wiedehopf/tar1090/"));
    expect(pinned.length).toBe(9);
    for (const entry of pinned) expect(entry.url).toContain(TAR1090_COMMIT);
  });

  it("dates GIBS imagery to yesterday (UTC) and labels it like the menu", () => {
    const now = new Date("2026-11-03T16:32:00Z");
    expect(gibsDate(now)).toBe("2026-11-02");
    const gibs = BASE_LAYERS.find((e) => e.id === "gibs");
    expect(layerTitle(gibs, now)).toBe("GIBS Clouds 2026-11-02");
    expect(resolveTiles(gibs, { now })[0]).toContain("/default/2026-11-02/GoogleMapsCompatible_Level9/");
  });

  it("refreshes time-varying overlays with stable cache buckets", () => {
    const nexrad = OVERLAYS.find((e) => e.id === "nexrad");
    const t0 = new Date("2026-11-03T16:00:10Z");
    const t1 = new Date("2026-11-03T16:01:10Z");
    const t2 = new Date("2026-11-03T16:03:10Z");
    expect(resolveTiles(nexrad, { now: t0 })).toEqual(resolveTiles(nexrad, { now: t1 }));
    expect(resolveTiles(nexrad, { now: t0 })).not.toEqual(resolveTiles(nexrad, { now: t2 }));
    const dwd = OVERLAYS.find((e) => e.id === "dwd_radolan");
    expect(resolveTiles(dwd, { now: t1 })[0]).toContain(`validtime=${Date.parse("2026-11-03T16:00:00Z") / 1000}`);
    expect(resolveTiles(dwd, { now: t1 })[0]).toContain("{bbox-epsg-3857}");
  });

  it("routes openAIP through the configured API base", () => {
    const openaip = OVERLAYS.find((e) => e.id === "openaip");
    expect(resolveTiles(openaip, { apiBase: "http://127.0.0.1:8000/api" })[0]).toBe("http://127.0.0.1:8000/api/console/live/tiles/openaip/{z}/{x}/{y}.png");
  });

  it("validates custom tile templates", () => {
    expect(validateCustomTemplate("http://x/{z}/{x}/{y}.png")).toMatch(/https/);
    expect(validateCustomTemplate("https://x/{z}/{x}.png")).toMatch(/\{y\}/);
    expect(validateCustomTemplate("https://tiles.example/{z}/{x}/{y}.png")).toBeNull();
    expect(customBaseLayer("https://tiles.example/{z}/{x}/{y}.png").tiles).toEqual(["https://tiles.example/{z}/{x}/{y}.png"]);
  });
});
