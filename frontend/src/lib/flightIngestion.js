import { parseMasterFlightLogHtml } from "./masterFlightLog";

const HEADER_SCAN_ROWS = 500;

const LAT_NAMES = ["lat", "latitude", "y", "gps_lat", "position_lat"];
const LON_NAMES = ["lon", "lng", "longitude", "x", "gps_lon", "position_lon"];
const TIME_NAMES = ["timestamp", "time", "datetime", "date", "utc", "seen", "created_at"];
const ALT_NAMES = ["alt", "altitude", "altitude_ft", "baro_altitude", "geo_altitude"];
const SPD_NAMES = ["speed", "groundspeed", "gs", "speed_mph", "velocity", "ground_speed"];
const HDG_NAMES = ["heading", "track", "bearing", "course", "direction"];
const POSITION_NAMES = ["position", "coordinates", "coordinate", "lat_lon", "latlon"];
const START_LAT_NAMES = ["start_lat", "start_latitude"];
const START_LON_NAMES = ["start_lon", "start_lng", "start_longitude"];
const END_LAT_NAMES = ["end_lat", "end_latitude"];
const END_LON_NAMES = ["end_lon", "end_lng", "end_longitude"];

export const FLIGHT_INGEST_STATUS = Object.freeze({
  READY: "READY",
  CORPUS_READY: "CORPUS_READY",
  EMPTY_TRACK: "EMPTY_TRACK",
  SCHEMA_UNRESOLVED: "SCHEMA_UNRESOLVED",
  COORDINATE_BINDING_UNRESOLVED: "COORDINATE_BINDING_UNRESOLVED",
  MALFORMED_CSV: "MALFORMED_CSV",
  MALFORMED_XML: "MALFORMED_XML",
  UNSUPPORTED_GEOMETRY: "UNSUPPORTED_GEOMETRY",
});

const normalize = (value) => String(value ?? "").trim().toLowerCase().replaceAll(" ", "_");

const findColumn = (headers, aliases) => {
  const byNorm = new Map(headers.map((h) => [normalize(h), h]));
  for (const alias of aliases) {
    if (byNorm.has(alias)) return byNorm.get(alias);
  }
  return null;
};

const coordinateHeaderCandidate = (headers) => {
  const normalized = new Set(headers.map(normalize));
  const hasSplit = LAT_NAMES.some((n) => normalized.has(n)) && LON_NAMES.some((n) => normalized.has(n));
  const hasPosition = POSITION_NAMES.some((n) => normalized.has(n));
  const hasSegments =
    START_LAT_NAMES.some((n) => normalized.has(n)) &&
    START_LON_NAMES.some((n) => normalized.has(n)) &&
    END_LAT_NAMES.some((n) => normalized.has(n)) &&
    END_LON_NAMES.some((n) => normalized.has(n));
  return hasSplit || hasPosition || hasSegments;
};

const parseCsvLine = (line, delimiter) => {
  const cells = [];
  let current = "";
  let quoted = false;
  for (let i = 0; i < line.length; i += 1) {
    const ch = line[i];
    if (ch === '"') {
      if (quoted && line[i + 1] === '"') {
        current += '"';
        i += 1;
      } else {
        quoted = !quoted;
      }
    } else if (ch === delimiter && !quoted) {
      cells.push(current);
      current = "";
    } else {
      current += ch;
    }
  }
  cells.push(current);
  if (quoted) throw new Error("Unterminated quoted CSV field");
  return cells;
};

const detectDelimiter = (line) => {
  const candidates = [",", ";", "\t", "|"];
  let best = null;
  let bestCount = -1;
  for (const delimiter of candidates) {
    try {
      const count = parseCsvLine(line, delimiter).length;
      if (count > bestCount) {
        best = delimiter;
        bestCount = count;
      }
    } catch {
      // Ignore malformed delimiter candidates.
    }
  }
  return bestCount > 1 ? best : ",";
};

const toNumber = (value) => {
  if (value == null || String(value).trim() === "") return null;
  const number = Number(value);
  return Number.isFinite(number) ? number : null;
};

const validLatLon = (lat, lon) =>
  Number.isFinite(lat) && Number.isFinite(lon) && lat >= -90 && lat <= 90 && lon >= -180 && lon <= 180;

const rowObject = (headers, values) =>
  Object.fromEntries(headers.map((header, index) => [header, values[index] ?? ""]));

const parsePosition = (value) => {
  const match = String(value ?? "").match(
    /^\s*([+-]?(?:\d+(?:\.\d*)?|\.\d+))\s*,\s*([+-]?(?:\d+(?:\.\d*)?|\.\d+))\s*$/,
  );
  if (!match) return null;
  const lat = Number(match[1]);
  const lon = Number(match[2]);
  return validLatLon(lat, lon) ? { lat, lon } : null;
};

const selectMetadata = (row, headers) => {
  const pick = (aliases) => {
    const column = findColumn(headers, aliases);
    return column ? row[column] : null;
  };
  return {
    timestamp: pick(TIME_NAMES),
    altitude: toNumber(pick(ALT_NAMES)),
    speed: toNumber(pick(SPD_NAMES)),
    heading: toNumber(pick(HDG_NAMES)),
    callsign: pick(["callsign"]),
    registration: pick(["registration", "tail_number"]),
    aircraftType: pick(["aircraft_type", "aircrafttype"]),
  };
};

export function parseFlightCsv(text, source = "local.csv") {
  const lines = String(text ?? "").replace(/^\uFEFF/, "").split(/\r?\n/);
  let headerIndex = -1;
  let delimiter = ",";

  for (let index = 0; index < Math.min(lines.length, HEADER_SCAN_ROWS); index += 1) {
    const line = lines[index];
    if (!line.trim()) continue;
    const candidateDelimiter = detectDelimiter(line);
    let headers;
    try {
      headers = parseCsvLine(line, candidateDelimiter);
    } catch {
      continue;
    }
    if (coordinateHeaderCandidate(headers)) {
      headerIndex = index;
      delimiter = candidateDelimiter;
      break;
    }
  }

  if (headerIndex < 0) {
    return {
      status: FLIGHT_INGEST_STATUS.SCHEMA_UNRESOLVED,
      source,
      diagnostics: { scannedRows: Math.min(lines.length, HEADER_SCAN_ROWS) },
      points: [],
    };
  }

  let headers;
  try {
    headers = parseCsvLine(lines[headerIndex], delimiter);
  } catch (error) {
    return {
      status: FLIGHT_INGEST_STATUS.MALFORMED_CSV,
      source,
      diagnostics: { error: String(error), headerIndex, delimiter },
      points: [],
    };
  }

  const rows = [];
  let malformedRows = 0;
  for (let index = headerIndex + 1; index < lines.length; index += 1) {
    if (!lines[index].trim()) continue;
    try {
      rows.push(rowObject(headers, parseCsvLine(lines[index], delimiter)));
    } catch {
      malformedRows += 1;
    }
  }

  if (rows.length === 0) {
    return {
      status: FLIGHT_INGEST_STATUS.EMPTY_TRACK,
      source,
      diagnostics: { headerIndex, delimiter, malformedRows },
      points: [],
    };
  }

  const startLat = findColumn(headers, START_LAT_NAMES);
  const startLon = findColumn(headers, START_LON_NAMES);
  const endLat = findColumn(headers, END_LAT_NAMES);
  const endLon = findColumn(headers, END_LON_NAMES);

  if (startLat && startLon && endLat && endLon) {
    const points = [];
    for (const row of rows) {
      const metadata = selectMetadata(row, headers);
      const start = { lat: toNumber(row[startLat]), lon: toNumber(row[startLon]) };
      const end = { lat: toNumber(row[endLat]), lon: toNumber(row[endLon]) };
      if (validLatLon(start.lat, start.lon)) {
        points.push({ ...metadata, ...start, sourceGeometry: "segment_start" });
      }
      if (validLatLon(end.lat, end.lon)) {
        points.push({ ...metadata, ...end, sourceGeometry: "segment_end" });
      }
    }
    return {
      status: points.length ? FLIGHT_INGEST_STATUS.READY : FLIGHT_INGEST_STATUS.COORDINATE_BINDING_UNRESOLVED,
      source,
      manifestation: "DERIVED_SEGMENT_TABLE",
      diagnostics: { headerIndex, delimiter, malformedRows, acceptedPoints: points.length },
      points,
    };
  }

  const latColumn = findColumn(headers, LAT_NAMES);
  const lonColumn = findColumn(headers, LON_NAMES);
  const positionColumn = findColumn(headers, POSITION_NAMES);
  const points = [];

  for (const row of rows) {
    const metadata = selectMetadata(row, headers);
    let position = null;
    if (latColumn && lonColumn) {
      const lat = toNumber(row[latColumn]);
      const lon = toNumber(row[lonColumn]);
      if (validLatLon(lat, lon)) position = { lat, lon };
    } else if (positionColumn) {
      position = parsePosition(row[positionColumn]);
    }
    if (position) points.push({ ...metadata, ...position });
  }

  if (!latColumn && !lonColumn && !positionColumn) {
    return {
      status: FLIGHT_INGEST_STATUS.COORDINATE_BINDING_UNRESOLVED,
      source,
      diagnostics: { headerIndex, delimiter, malformedRows, headers },
      points: [],
    };
  }

  return {
    status: points.length ? FLIGHT_INGEST_STATUS.READY : FLIGHT_INGEST_STATUS.COORDINATE_BINDING_UNRESOLVED,
    source,
    manifestation: positionColumn ? "FR24_POSITION" : "SPLIT_COORDINATES",
    diagnostics: { headerIndex, delimiter, malformedRows, acceptedPoints: points.length },
    points,
  };
}

const localName = (node) => (node?.localName || node?.nodeName || "").split(":").at(-1)?.toLowerCase();

export function parseFlightKml(text, source = "local.kml") {
  let xml;
  try {
    xml = new DOMParser().parseFromString(String(text ?? ""), "application/xml");
  } catch (error) {
    return { status: FLIGHT_INGEST_STATUS.MALFORMED_XML, source, diagnostics: { error: String(error) }, points: [] };
  }

  if (xml.querySelector("parsererror")) {
    return { status: FLIGHT_INGEST_STATUS.MALFORMED_XML, source, diagnostics: {}, points: [] };
  }

  const points = [];
  for (const node of [...xml.getElementsByTagName("*")]) {
    if (localName(node) !== "coordinates") continue;
    for (const token of String(node.textContent ?? "").trim().split(/\s+/)) {
      if (!token) continue;
      const [lonRaw, latRaw, altRaw] = token.split(",");
      const lon = toNumber(lonRaw);
      const lat = toNumber(latRaw);
      const altitude = toNumber(altRaw);
      if (validLatLon(lat, lon)) points.push({ lat, lon, altitude });
    }
  }

  if (points.length === 0) {
    const whenValues = [...xml.getElementsByTagName("*")]
      .filter((node) => localName(node) === "when")
      .map((node) => String(node.textContent ?? "").trim());
    const coordNodes = [...xml.getElementsByTagName("*")].filter((node) => localName(node) === "coord");
    coordNodes.forEach((node, index) => {
      const [lonRaw, latRaw, altRaw] = String(node.textContent ?? "").trim().split(/\s+/);
      const lon = toNumber(lonRaw);
      const lat = toNumber(latRaw);
      const altitude = toNumber(altRaw);
      if (validLatLon(lat, lon)) {
        points.push({ lat, lon, altitude, timestamp: whenValues[index] ?? null });
      }
    });
  }

  return {
    status: points.length ? FLIGHT_INGEST_STATUS.READY : FLIGHT_INGEST_STATUS.EMPTY_TRACK,
    source,
    manifestation: points.length ? "KML_TRACK" : "KML_METADATA_ONLY",
    diagnostics: { acceptedPoints: points.length },
    points,
  };
}

export async function parseFlightFile(file) {
  const name = file?.name || "local";
  const extension = name.toLowerCase().split(".").at(-1);
  const text = await file.text();
  if (extension === "csv") return parseFlightCsv(text, name);
  if (extension === "kml") return parseFlightKml(text, name);
  if (extension === "html" || extension === "htm") return parseMasterFlightLogHtml(text, name);
  return {
    status: FLIGHT_INGEST_STATUS.UNSUPPORTED_GEOMETRY,
    source: name,
    diagnostics: { extension },
    points: [],
  };
}

export async function parseFlightFiles(files) {
  return Promise.all([...files].map((file) => parseFlightFile(file)));
}
