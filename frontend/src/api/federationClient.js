import { appParams } from '@/lib/app-params';

const TOKEN_STORAGE_KEY = 'federation_access_token';

const trimSlash = (value = '') => value.replace(/\/+$/, '');
const encode = (value) => encodeURIComponent(String(value));

const getStoredToken = () => {
  if (typeof window === 'undefined') return null;
  return window.localStorage.getItem(TOKEN_STORAGE_KEY) || window.localStorage.getItem('access_token') || null;
};

const setStoredToken = (token) => {
  if (typeof window === 'undefined') return;
  if (token) {
    window.localStorage.setItem(TOKEN_STORAGE_KEY, token);
    window.localStorage.setItem('access_token', token);
  } else {
    window.localStorage.removeItem(TOKEN_STORAGE_KEY);
    window.localStorage.removeItem('access_token');
    window.localStorage.removeItem('token');
  }
};

const normalizeError = async (response) => {
  let data = null;
  let message = response.statusText || 'Request failed';
  try {
    data = await response.json();
    message = data?.message || data?.error || message;
  } catch {
    try {
      const text = await response.text();
      if (text) message = text;
    } catch {
      // no body
    }
  }
  const error = new Error(message);
  error.status = response.status;
  error.data = data;
  return error;
};

async function request(path, options = {}) {
  const baseUrl = trimSlash(options.baseUrl || appParams.apiBaseUrl || '/api');
  const token = options.token ?? appParams.token ?? getStoredToken();
  const headers = new Headers(options.headers || {});

  if (!(options.body instanceof FormData) && !headers.has('Content-Type')) {
    headers.set('Content-Type', 'application/json');
  }
  if (token && !headers.has('Authorization')) {
    headers.set('Authorization', `Bearer ${token}`);
  }

  const response = await fetch(`${baseUrl}${path}`, {
    method: options.method || 'GET',
    headers,
    body: options.body instanceof FormData ? options.body : options.body ? JSON.stringify(options.body) : undefined,
    credentials: options.credentials || 'include',
    signal: options.signal,
  });

  if (!response.ok) throw await normalizeError(response);
  if (response.status === 204) return null;

  const contentType = response.headers.get('content-type') || '';
  if (contentType.includes('application/json')) return response.json();
  return response.text();
}

const queryString = (params = {}) => {
  const search = new URLSearchParams();
  Object.entries(params).forEach(([key, value]) => {
    if (value !== undefined && value !== null && value !== '') search.set(key, String(value));
  });
  const qs = search.toString();
  return qs ? `?${qs}` : '';
};

const entityClient = (entityName) => ({
  list: (sort, limit) => request(`/entities/${encode(entityName)}${queryString({ sort, limit })}`),
  filter: (filters = {}, sort, limit) => request(`/entities/${encode(entityName)}/filter`, {
    method: 'POST',
    body: { filters, sort, limit },
  }),
  get: (id) => request(`/entities/${encode(entityName)}/${encode(id)}`),
  create: (data) => request(`/entities/${encode(entityName)}`, { method: 'POST', body: data }),
  bulkCreate: (items) => request(`/entities/${encode(entityName)}/bulk`, { method: 'POST', body: { items } }),
  update: (id, data) => request(`/entities/${encode(entityName)}/${encode(id)}`, { method: 'PATCH', body: data }),
  delete: (id) => request(`/entities/${encode(entityName)}/${encode(id)}`, { method: 'DELETE' }),
});

const entities = new Proxy({}, {
  get: (_target, entityName) => entityClient(entityName),
});

const auth = {
  me: () => request('/auth/me'),
  isAuthenticated: () => Boolean(appParams.token || getStoredToken()),
  setToken: setStoredToken,
  loginViaEmailPassword: async (email, password) => {
    const result = await request('/auth/login', { method: 'POST', body: { email, password } });
    if (result?.access_token || result?.token) setStoredToken(result.access_token || result.token);
    return result;
  },
  loginWithProvider: (provider, redirectPath = '/') => {
    const baseUrl = trimSlash(appParams.apiBaseUrl || '/api');
    const redirect = new URL(redirectPath, window.location.origin).toString();
    window.location.href = `${baseUrl}/auth/${encode(provider)}/login${queryString({ redirect })}`;
  },
  register: (payload) => request('/auth/register', { method: 'POST', body: payload }),
  verifyOtp: async (payload) => {
    const result = await request('/auth/verify-otp', { method: 'POST', body: payload });
    if (result?.access_token || result?.token) setStoredToken(result.access_token || result.token);
    return result;
  },
  resendOtp: (email) => request('/auth/resend-otp', { method: 'POST', body: { email } }),
  resetPasswordRequest: (email) => request('/auth/password/reset-request', { method: 'POST', body: { email } }),
  resetPassword: (payload) => request('/auth/password/reset', { method: 'POST', body: payload }),
  logout: (redirectUrl) => {
    setStoredToken(null);
    if (redirectUrl) {
      const baseUrl = trimSlash(appParams.apiBaseUrl || '/api');
      window.location.href = `${baseUrl}/auth/logout${queryString({ redirect: redirectUrl })}`;
    }
  },
  redirectToLogin: (redirectUrl = window.location.href) => {
    window.location.href = `/login${queryString({ redirect: redirectUrl })}`;
  },
};

const functions = {
  invoke: (name, payload = {}) => request(`/functions/${encode(name)}/invoke`, { method: 'POST', body: payload }),
};

const integrations = {
  Core: {
    InvokeLLM: (payload) => request('/integrations/llm/invoke', { method: 'POST', body: payload }),
    SendEmail: (payload) => request('/integrations/email/send', { method: 'POST', body: payload }),
    ExtractDataFromUploadedFile: (payload) => request('/integrations/extract-uploaded-file', { method: 'POST', body: payload }),
    UploadFile: ({ file, ...rest }) => {
      const form = new FormData();
      form.append('file', file);
      Object.entries(rest).forEach(([key, value]) => form.append(key, value));
      return request('/files/upload', { method: 'POST', body: form });
    },
  },
};

const agents = {
  listConversations: (params = {}) => request(`/agents/conversations${queryString(params)}`),
  getConversation: (id) => request(`/agents/conversations/${encode(id)}`),
  createConversation: (payload) => request('/agents/conversations', { method: 'POST', body: payload }),
  addMessage: (conversation, payload) => {
    const id = typeof conversation === 'string' ? conversation : conversation?.id;
    return request(`/agents/conversations/${encode(id)}/messages`, { method: 'POST', body: payload });
  },
  subscribeToConversation: (conversationId, onMessage) => {
    if (typeof EventSource === 'undefined' || !conversationId) return () => {};
    const baseUrl = trimSlash(appParams.apiBaseUrl || '/api');
    const source = new EventSource(`${baseUrl}/agents/conversations/${encode(conversationId)}/events`, { withCredentials: true });
    source.onmessage = (event) => {
      try { onMessage(JSON.parse(event.data)); } catch { onMessage(event.data); }
    };
    source.onerror = () => source.close();
    return () => source.close();
  },
};

const connectors = {
  getConnection: (name) => request(`/connectors/${encode(name)}/connection`),
};

const system = {
  publicSettings: () => request('/apps/public-settings').catch(() => ({
    id: appParams.appId,
    public_settings: { requires_auth: Boolean(appParams.requireAuth) },
  })),
};

export const federation = {
  app: { id: appParams.appId, programId: appParams.programId },
  auth,
  entities,
  functions,
  integrations,
  agents,
  connectors,
  asServiceRole: { entities, connectors },
  system,
  request,
};
