const BACKGROUND_COLOR = '#070b14';

export const BLANK_OFFLINE_STYLE = Object.freeze({
  version: 8,
  name: 'Skywatcher Offline Diagnostic',
  metadata: Object.freeze({
    'skywatcher:offline': true,
    'skywatcher:network_required': false,
  }),
  sources: Object.freeze({}),
  layers: Object.freeze([
    Object.freeze({
      id: 'skywatcher-background',
      type: 'background',
      paint: Object.freeze({
        'background-color': BACKGROUND_COLOR,
      }),
    }),
  ]),
});

const REMOTE_PROTOCOL = /^(?:https?:)?\/\//i;
const SENSITIVE_KEY = /(?:api[-_]?key|access[-_]?token|secret|password)/i;

export function collectExternalStyleReferences(style) {
  const findings = [];
  const visit = (value, path = 'style') => {
    if (typeof value === 'string') {
      if (REMOTE_PROTOCOL.test(value)) findings.push({ path, value, kind: 'remote_url' });
      return;
    }
    if (Array.isArray(value)) {
      value.forEach((entry, index) => visit(entry, `${path}[${index}]`));
      return;
    }
    if (!value || typeof value !== 'object') return;
    Object.entries(value).forEach(([key, entry]) => {
      const nextPath = `${path}.${key}`;
      if (SENSITIVE_KEY.test(key) && entry) findings.push({ path: nextPath, value: '[redacted]', kind: 'credential' });
      visit(entry, nextPath);
    });
  };
  visit(style);
  return findings;
}

export function assertOfflineStyle(style) {
  if (!style || style.version !== 8) throw new Error('offline style must be a MapLibre style specification version 8');
  const findings = collectExternalStyleReferences(style);
  if (findings.length) {
    throw new Error(`offline style contains prohibited external references: ${findings.map((item) => item.path).join(', ')}`);
  }
  return style;
}
