import { federation } from '@/api/federationClient';

export class ConsoleApiClient {
  /** @param {(path: string, options?: Record<string, unknown>) => Promise<unknown>} [request] */
  constructor(request = federation.request) {
    this.request = request;
  }

  /** @param {{signal?: AbortSignal}} [options] */
  capabilities(options = {}) {
    return this.request('/console/capabilities', { signal: options.signal });
  }

  /** @param {{signal?: AbortSignal}} [options] */
  repositories(options = {}) {
    return this.request('/console/repositories', { signal: options.signal });
  }

  /**
   * @param {Record<string, unknown>} [params]
   * @param {{signal?: AbortSignal}} [options]
   */
  aircraftStates(params = {}, options = {}) {
    const search = new URLSearchParams();
    Object.entries(params).forEach(([key, value]) => {
      if (value !== undefined && value !== null && value !== '') search.set(key, String(value));
    });
    const suffix = search.size ? `?${search.toString()}` : '';
    return this.request(`/console/aircraft/states${suffix}`, { signal: options.signal });
  }
}

/**
 * @param {ConsoleApiClient} [client]
 * @param {{signal?: AbortSignal}} [options]
 */
export async function loadConsoleBootstrap(client = new ConsoleApiClient(), options = {}) {
  const [capabilities, repositories] = await Promise.all([
    client.capabilities({ signal: options.signal }),
    client.repositories({ signal: options.signal }),
  ]);
  return { capabilities, repositories };
}
