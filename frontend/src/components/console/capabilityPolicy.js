const ENABLED_STATUSES = new Set(['available', 'available_synthetic_only']);

export function capabilityById(capabilities, capabilityId) {
  return (capabilities || []).find((item) => item.id === capabilityId) || null;
}

export function resolveCapability({
  capabilities,
  capabilityId,
  featureEnabled = true,
  runtimeReady = true,
}) {
  if (!featureEnabled) return { enabled: false, reason: 'Feature disabled by configuration.', status: 'disabled_by_policy' };
  if (!runtimeReady) return { enabled: false, reason: 'Browser runtime is not ready.', status: 'degraded' };
  const capability = capabilityById(capabilities, capabilityId);
  if (!capability) return { enabled: false, reason: `Capability not reported: ${capabilityId}`, status: 'unavailable_no_adapter' };
  return {
    enabled: ENABLED_STATUSES.has(capability.status),
    reason: capability.reason || capability.status,
    status: capability.status,
  };
}
