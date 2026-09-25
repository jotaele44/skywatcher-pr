const MFL_ASSIGNMENT = /window\.MFL_SEED\s*=\s*/m;

export const MASTER_FLIGHT_LOG_STATUS = Object.freeze({
  CORPUS_READY: "CORPUS_READY",
  SEED_NOT_FOUND: "SEED_NOT_FOUND",
  MALFORMED_SEED: "MALFORMED_SEED",
  UNSUPPORTED_VERSION: "UNSUPPORTED_VERSION",
});

function extractAssignedJson(text) {
  const source = String(text ?? "");
  const match = MFL_ASSIGNMENT.exec(source);
  if (!match) return null;

  let index = match.index + match[0].length;
  while (index < source.length && /\s/.test(source[index])) index += 1;
  if (source[index] !== "{") return null;

  let depth = 0;
  let inString = false;
  let escaped = false;
  for (let i = index; i < source.length; i += 1) {
    const ch = source[i];
    if (inString) {
      if (escaped) {
        escaped = false;
      } else if (ch === "\\") {
        escaped = true;
      } else if (ch === '"') {
        inString = false;
      }
      continue;
    }
    if (ch === '"') {
      inString = true;
      continue;
    }
    if (ch === "{") depth += 1;
    if (ch === "}") {
      depth -= 1;
      if (depth === 0) return source.slice(index, i + 1);
    }
  }
  return null;
}

function isoFromEpochSeconds(value) {
  if (!Number.isFinite(value)) return null;
  return new Date(value * 1000).toISOString();
}

function stableCorpusUid(monthBucket, record, ordinal) {
  // Preserve source identity without pretending callsign/name equality is identity.
  // h is retained when supplied because the MFL artifact uses it as a record hash.
  const sourceHash = typeof record?.h === "string" && record.h ? record.h : null;
  if (sourceHash) return `mfl:${sourceHash}`;
  const sourceId = typeof record?.fid === "string" && record.fid ? record.fid : "no-source-id";
  return `mfl:${monthBucket}:${sourceId}:${ordinal}`;
}

function normalizeRecord(monthBucket, record, ordinal) {
  const t0 = Number.isFinite(record?.t0) ? record.t0 : null;
  const t1 = Number.isFinite(record?.t1) ? record.t1 : null;
  return {
    corpusUid: stableCorpusUid(monthBucket, record, ordinal),
    monthBucket,
    sourceFlightIdRaw: record?.fid ?? null,
    callsignRaw: record?.cs ?? null,
    pointCount: Number.isInteger(record?.n) ? record.n : null,
    startTimeUtc: isoFromEpochSeconds(t0),
    endTimeUtc: isoFromEpochSeconds(t1),
    start: Number.isFinite(record?.la0) && Number.isFinite(record?.lo0)
      ? { lat: record.la0, lon: record.lo0 }
      : null,
    end: Number.isFinite(record?.la1) && Number.isFinite(record?.lo1)
      ? { lat: record.la1, lon: record.lo1 }
      : null,
    sourceManifestations: Array.isArray(record?.s)
      ? record.s.map((item) => ({
          folderRaw: item?.f ?? null,
          filenameRaw: item?.n ?? null,
          mtimeRaw: item?.m ?? null,
          bindingCodeRaw: item?.k ?? null,
          raw: item,
        }))
      : [],
    // Deliberately preserve fields whose semantics have not yet been certified.
    sourceFieldsOpen: {
      alt: record?.alt ?? null,
      spd: record?.spd ?? null,
      dist: record?.dist ?? null,
      pr: record?.pr ?? null,
      gap: record?.gap ?? null,
      gp: record?.gp ?? null,
      km: record?.km ?? null,
      rt: record?.rt ?? null,
    },
    raw: record,
  };
}

export function parseMasterFlightLogHtml(text, source = "Master Flight Log.html") {
  const jsonText = extractAssignedJson(text);
  if (!jsonText) {
    return {
      status: MASTER_FLIGHT_LOG_STATUS.SEED_NOT_FOUND,
      source,
      snapshot: null,
      records: [],
      diagnostics: {},
    };
  }

  let seed;
  try {
    seed = JSON.parse(jsonText);
  } catch (error) {
    return {
      status: MASTER_FLIGHT_LOG_STATUS.MALFORMED_SEED,
      source,
      snapshot: null,
      records: [],
      diagnostics: { error: String(error) },
    };
  }

  if (seed?.format !== "master-flight-log-backup" || seed?.version !== 1) {
    return {
      status: MASTER_FLIGHT_LOG_STATUS.UNSUPPORTED_VERSION,
      source,
      snapshot: {
        format: seed?.format ?? null,
        version: seed?.version ?? null,
        exportedAt: seed?.exported ?? null,
      },
      records: [],
      diagnostics: {},
    };
  }

  const records = [];
  const flights = seed?.flights && typeof seed.flights === "object" ? seed.flights : {};
  for (const [monthBucket, monthRecords] of Object.entries(flights)) {
    if (!Array.isArray(monthRecords)) continue;
    monthRecords.forEach((record, ordinal) => {
      if (record && typeof record === "object") records.push(normalizeRecord(monthBucket, record, ordinal));
    });
  }

  return {
    status: MASTER_FLIGHT_LOG_STATUS.CORPUS_READY,
    source,
    snapshot: {
      format: seed.format,
      version: seed.version,
      exportedAt: seed.exported ?? null,
      recordCount: records.length,
    },
    records,
    diagnostics: {
      monthBuckets: Object.keys(flights).length,
      recordCount: records.length,
    },
  };
}
