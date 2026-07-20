const ENABLED_STATUSES = new Set(["available", "available_synthetic_only", "degraded"]);

export function indexCapabilities(payload) {
  const entries = Array.isArray(payload?.capabilities) ? payload.capabilities : [];
  return Object.fromEntries(entries.map((entry) => [entry.id, { ...entry }]));
}

export function isCapabilityEnabled(index, capabilityId) {
  if (!capabilityId) return true;
  return ENABLED_STATUSES.has(index?.[capabilityId]?.status);
}

export function capabilityReason(index, capabilityId) {
  const entry = index?.[capabilityId];
  if (!entry) return "Capability was not reported by the backend.";
  return entry.reason || `Capability status: ${entry.status}`;
}

export function capabilityTone(status) {
  if (status === "available") return "success";
  if (status === "available_synthetic_only" || status === "degraded") return "warning";
  return "muted";
}
