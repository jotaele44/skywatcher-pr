import { assertOfflineStyle } from './BlankOfflineStyle';

const ALLOWED_PROTOCOLS = new Set(['blob:', 'data:']);

export function isExternalUrl(url, locationRef = globalThis.location) {
  if (!url) return false;
  try {
    const parsed = new URL(url, locationRef?.origin || 'http://127.0.0.1');
    if (ALLOWED_PROTOCOLS.has(parsed.protocol)) return false;
    return Boolean(locationRef?.origin) && parsed.origin !== locationRef.origin;
  } catch {
    return true;
  }
}

export function createOfflineTransformRequest(locationRef = globalThis.location) {
  return (url) => {
    if (isExternalUrl(url, locationRef)) throw new Error(`external map request blocked in offline mode: ${url}`);
    return { url };
  };
}

export function enforceOfflineMapPolicy(style) {
  assertOfflineStyle(style);
  return Object.freeze({ externalRequestsAllowed: false, styleValidated: true });
}
