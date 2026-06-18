// Skywatcher-PR federation identity & operating posture (diagnostic constants)
export const PROGRAM = {
  appName: "Skywatcher-PR",
  programId: "skywatcher-pr",
  federationRole: "airspace_intelligence_node",
  parentHub: "thehub-pr",
  jurisdiction: "Puerto Rico",
  activeVector: "SKYWATCHER_AIRSPACE_AIRCRAFT_INTELLIGENCE",
  productionStatus: "NON_PRODUCTION_DIAGNOSTIC",
  hubDiscoveryStatus: "READY",
  hubLiveExecutionStatus: "BLOCKED",
  dataMode: "Diagnostic / Synthetic until replaced",
};

export const DISCLAIMER =
  "Skywatcher maps aircraft activity, missions, and airspace–infrastructure relationships. It does not allege wrongdoing.";

export const REPO_COMMANDS = [
  "python -m pip install -r requirements-dev.txt",
  "python scripts/validate_airspace_export.py exports/examples/synthetic_airspace_package --mode test",
  "python scripts/validate_airspace_export.py exports/examples/synthetic_airspace_package --mode production",
  "python -m pytest -q",
  "python3 scripts/federation_export.py --mode test",
  "python3 scripts/ingest_airports.py",
];

// Confidence tiering
export function confidenceTier(score) {
  if (score == null) return "unknown";
  if (score >= 0.75) return "high";
  if (score >= 0.5) return "medium";
  return "low";
}

// Puerto Rico geographic bounding box for the map shell projection
export const PR_BOUNDS = {
  minLat: 17.85,
  maxLat: 18.55,
  minLon: -67.3,
  maxLon: -65.2,
};

export function projectToShell(lat, lon, width, height, pad = 16) {
  const { minLat, maxLat, minLon, maxLon } = PR_BOUNDS;
  const x = pad + ((lon - minLon) / (maxLon - minLon)) * (width - pad * 2);
  const y = pad + ((maxLat - lat) / (maxLat - minLat)) * (height - pad * 2);
  return { x, y };
}

// Review status display config
export const REVIEW_STATUS = {
  new: { label: "New", tone: "muted" },
  triaged: { label: "Triaged", tone: "info" },
  needs_review: { label: "Needs Review", tone: "warn" },
  verified: { label: "Verified", tone: "ready" },
  rejected: { label: "Rejected", tone: "blocked" },
  open: { label: "Open", tone: "warn" },
  in_review: { label: "In Review", tone: "info" },
  resolved: { label: "Resolved", tone: "ready" },
};

export const INGEST_STATUS = {
  queued: { label: "Queued", tone: "muted" },
  processed: { label: "Processed", tone: "ready" },
  needs_manual_review: { label: "Needs Manual Review", tone: "warn" },
  duplicate: { label: "Duplicate", tone: "synthetic" },
  corrupt: { label: "Corrupt", tone: "blocked" },
  rejected: { label: "Rejected", tone: "blocked" },
};

export const EXPORT_STATUS = {
  draft: { label: "Draft", tone: "muted" },
  valid: { label: "Valid", tone: "ready" },
  invalid: { label: "Invalid", tone: "blocked" },
  blocked: { label: "Blocked", tone: "blocked" },
  exported: { label: "Exported", tone: "info" },
};

export const SYNC_STATUS = {
  queued: { label: "Queued", tone: "muted" },
  success: { label: "Success", tone: "ready" },
  warning: { label: "Warning", tone: "warn" },
  failed: { label: "Failed", tone: "blocked" },
  blocked: { label: "Blocked", tone: "blocked" },
};