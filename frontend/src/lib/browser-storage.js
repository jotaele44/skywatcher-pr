/** Browser storage can be absent, blocked by policy, or fail after startup. */
export function createResilientStorage(getStorage = () => globalThis.localStorage) {
  const memory = new Map();
  const removed = new Set();
  return {
    getItem(key) {
      if (removed.has(key)) return null;
      if (memory.has(key)) return memory.get(key);
      try {
        const storage = getStorage();
        return typeof storage?.getItem === 'function' ? storage.getItem(key) : null;
      } catch {
        return null;
      }
    },
    setItem(key, value) {
      const text = String(value);
      memory.set(key, text);
      removed.delete(key);
      try { getStorage()?.setItem(key, text); } catch { /* Session-only fallback. */ }
    },
    removeItem(key) {
      memory.delete(key);
      removed.add(key);
      try { getStorage()?.removeItem(key); } catch { /* Never resurrect a cleared session. */ }
    },
  };
}

export const browserStorage = createResilientStorage();
