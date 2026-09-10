// Restricted browsers may expose localStorage but throw on access or writes.
// Keep this session usable without claiming that its preferences are durable.
const sessionValues = new Map();

export const browserStorage = {
  getItem(key) {
    if (sessionValues.has(key)) return sessionValues.get(key);
    try {
      return typeof window === 'undefined' ? null : window.localStorage.getItem(key);
    } catch {
      return null;
    }
  },
  setItem(key, value) {
    const text = String(value);
    sessionValues.set(key, text);
    try {
      if (typeof window !== 'undefined') window.localStorage.setItem(key, text);
    } catch { /* Session-only fallback. */ }
  },
  removeItem(key) {
    // A tombstone prevents a failed removal from reviving a stale token.
    sessionValues.set(key, null);
    try {
      if (typeof window !== 'undefined') window.localStorage.removeItem(key);
    } catch { /* The session tombstone remains authoritative. */ }
  },
};
