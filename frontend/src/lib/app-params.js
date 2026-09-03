const isNode = typeof window === 'undefined';
const windowObj = isNode ? { localStorage: new Map(), location: { href: '' }, history: { replaceState: () => {} } } : window;
const storage = windowObj.localStorage;

const toSnakeCase = (str) => str.replace(/([A-Z])/g, '_$1').toLowerCase();

const getParamValue = (paramName, { defaultValue = undefined, removeFromUrl = false } = {}) => {
  if (isNode) return defaultValue ?? null;
  const storageKey = `federation_${toSnakeCase(paramName)}`;
  const urlParams = new URLSearchParams(window.location.search);
  const searchParam = urlParams.get(paramName);

  if (removeFromUrl) {
    urlParams.delete(paramName);
    const newUrl = `${window.location.pathname}${urlParams.toString() ? `?${urlParams.toString()}` : ''}${window.location.hash}`;
    window.history.replaceState({}, document.title, newUrl);
  }

  if (searchParam) {
    storage.setItem(storageKey, searchParam);
    return searchParam;
  }
  if (defaultValue !== undefined && defaultValue !== null) {
    storage.setItem(storageKey, defaultValue);
    return defaultValue;
  }
  return storage.getItem(storageKey);
};

const getAppParams = () => {
  if (getParamValue('clear_access_token') === 'true') {
    storage.removeItem('federation_access_token');
    storage.removeItem('access_token');
    storage.removeItem('token');
  }
  if (getParamValue('clear_write_token') === 'true') {
    storage.removeItem('federation_write_token');
  }

  const programId = import.meta.env.VITE_FEDERATION_PROGRAM_ID || 'skywatcher-pr';
  const scopedApiBaseUrl = import.meta.env.VITE_SKYWATCHER_API_BASE_URL;

  return {
    appId: getParamValue('app_id', { defaultValue: import.meta.env.VITE_FEDERATION_APP_ID || programId }),
    programId,
    apiBaseUrl: getParamValue('api_base_url', {
      defaultValue: scopedApiBaseUrl || import.meta.env.VITE_FEDERATION_API_BASE_URL || '/api',
    }),
    token: getParamValue('access_token', { removeFromUrl: true }),
    // PRII_WRITE_TOKEN, supplied as ?write_token=… and stripped from the URL.
    // Deliberately a separate slot from `token`: in diagnostic mode
    // `/api/auth/me` always 401s, and AuthContext responds by clearing the
    // access token so a stale one cannot trap the session in a login redirect
    // (lib/AuthContext.jsx). That cleanup would wipe a write token too, which is
    // why supplying one as ?access_token= never survived to the first request.
    writeToken: getParamValue('write_token', { removeFromUrl: true }),
    fromUrl: getParamValue('from_url', { defaultValue: window.location.href }),
    mode: import.meta.env.VITE_FEDERATION_MODE || 'diagnostic',
    requireAuth: import.meta.env.VITE_FEDERATION_REQUIRE_AUTH === 'true',
  };
};

export const appParams = {
  ...getAppParams(),
};
