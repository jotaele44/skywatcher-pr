import { updateGlobalDiagnostics } from './RuntimeResourceLedger';

export function probeWebGL(documentRef = globalThis.document) {
  if (!documentRef?.createElement) {
    const result = { supported: false, context: null, reason: 'document_unavailable' };
    updateGlobalDiagnostics({ webglSupported: false });
    return result;
  }
  const canvas = documentRef.createElement('canvas');
  const contexts = ['webgl2', 'webgl', 'experimental-webgl'];
  for (const context of contexts) {
    try {
      const gl = canvas.getContext(context, { failIfMajorPerformanceCaveat: true });
      if (gl) {
        const result = { supported: true, context, reason: null };
        updateGlobalDiagnostics({ webglSupported: true });
        return result;
      }
    } catch {
      // Continue to the next supported context name.
    }
  }
  const result = { supported: false, context: null, reason: 'webgl_unavailable' };
  updateGlobalDiagnostics({ webglSupported: false });
  return result;
}
