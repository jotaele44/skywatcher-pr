import { resolveCapability } from './capabilityPolicy';

export { capabilityById, resolveCapability } from './capabilityPolicy';

export function CapabilityGate({
  capabilities,
  capabilityId,
  featureEnabled = true,
  runtimeReady = true,
  fallback = null,
  children,
}) {
  const result = resolveCapability({ capabilities, capabilityId, featureEnabled, runtimeReady });
  if (!result.enabled) return typeof fallback === 'function' ? fallback(result) : fallback;
  return children;
}
