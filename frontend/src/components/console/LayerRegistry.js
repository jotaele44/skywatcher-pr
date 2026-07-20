export const LAYER_REGISTRY = Object.freeze([
  Object.freeze({
    id: 'aircraft-states',
    label: 'Aircraft states',
    enabledByDefault: false,
    requiredCapabilities: Object.freeze(['aircraft_viewport_list']),
    dataEndpoint: '/console/aircraft/states',
  }),
  Object.freeze({
    id: 'route-segments',
    label: 'Route segments',
    enabledByDefault: false,
    requiredCapabilities: Object.freeze(['playback_timeline']),
    dataEndpoint: '/console/routes',
  }),
  Object.freeze({
    id: 'airport-operations',
    label: 'Airport operations',
    enabledByDefault: false,
    requiredCapabilities: Object.freeze(['airport_operations']),
    dataEndpoint: null,
  }),
]);

export function validateLayerRegistry(registry = LAYER_REGISTRY) {
  const ids = new Set();
  registry.forEach((entry) => {
    if (!entry?.id || ids.has(entry.id)) throw new Error(`invalid or duplicate layer id: ${entry?.id || '<missing>'}`);
    ids.add(entry.id);
    if (!Array.isArray(entry.requiredCapabilities)) throw new Error(`layer ${entry.id} must declare requiredCapabilities`);
    if (entry.enabledByDefault && !entry.dataEndpoint) throw new Error(`enabled layer ${entry.id} must declare a data endpoint`);
  });
  return true;
}
