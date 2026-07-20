let nextToken = 1;

export class RuntimeResourceLedger {
  constructor() {
    this.resources = new Map();
    this.created = new Map();
    this.released = new Map();
  }

  acquire(kind, label = kind, cleanup = null) {
    const token = `${kind}:${nextToken++}`;
    this.resources.set(token, { kind, label, cleanup });
    this.created.set(kind, (this.created.get(kind) || 0) + 1);
    return token;
  }

  release(token, { runCleanup = true } = {}) {
    const resource = this.resources.get(token);
    if (!resource) return false;
    this.resources.delete(token);
    if (runCleanup && typeof resource.cleanup === 'function') resource.cleanup();
    this.released.set(resource.kind, (this.released.get(resource.kind) || 0) + 1);
    return true;
  }

  releaseAll() {
    [...this.resources.keys()].reverse().forEach((token) => this.release(token));
  }

  snapshot() {
    const activeByKind = {};
    this.resources.forEach(({ kind }) => {
      activeByKind[kind] = (activeByKind[kind] || 0) + 1;
    });
    return {
      active: this.resources.size,
      activeByKind,
      created: Object.fromEntries(this.created),
      released: Object.fromEntries(this.released),
      balanced: this.resources.size === 0,
    };
  }

  assertBalanced() {
    const snapshot = this.snapshot();
    if (!snapshot.balanced) throw new Error(`runtime resource leak: ${JSON.stringify(snapshot.activeByKind)}`);
    return snapshot;
  }
}

const globalDiagnostics = {
  mapsCreated: 0,
  mapsRemoved: 0,
  observersCreated: 0,
  observersDisconnected: 0,
  runtimeStatus: 'idle',
  webglSupported: null,
  lastError: null,
};

export function updateGlobalDiagnostics(patch) {
  Object.assign(globalDiagnostics, patch);
  if (typeof window !== 'undefined') {
    Object.assign(window, { __SKYWATCHER_CONSOLE_DIAGNOSTICS__: { ...globalDiagnostics } });
  }
  return { ...globalDiagnostics };
}

export function getGlobalDiagnostics() {
  return { ...globalDiagnostics };
}
