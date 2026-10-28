// One place that talks to the service. Errors keep the API's `message`, `error` code and any extra fields.
export class ApiError extends Error {
  constructor(status, body) {
    super((body && body.message) || (status === 0 ? 'Cannot reach the service' : `Request failed (HTTP ${status})`));
    this.status = status;
    this.code = body && body.error;
    this.body = body || {};
  }
}

const listeners = new Set();
let online = true;
export const onOnline = (fn) => { listeners.add(fn); return () => listeners.delete(fn); };
const setOnline = (v) => { if (v !== online) { online = v; listeners.forEach((fn) => fn(v)); } };

export async function api(method, path, body) {
  let res;
  try {
    res = await fetch(`api${path}`, {
      method,
      headers: body === undefined ? undefined : { 'Content-Type': 'application/json' },
      body: body === undefined ? undefined : JSON.stringify(body),
    });
  } catch (e) {
    setOnline(false);
    throw new ApiError(0, { error: 'unreachable', message: 'Cannot reach the service. Is it still running?' });
  }
  setOnline(true);
  let data = null;
  try { data = await res.json(); } catch (e) { /* empty body */ }
  if (!res.ok) throw new ApiError(res.status, data);
  return data;
}

export const get = (path) => api('GET', path);
export const post = (path, body = {}) => api('POST', path, body);
export const put = (path, body = {}) => api('PUT', path, body);
export const del = (path) => api('DELETE', path);
export const enc = encodeURIComponent;
export const qs = (params) => {
  const q = Object.entries(params).filter(([, v]) => v !== undefined && v !== null && v !== '').map(([k, v]) => `${k}=${enc(v)}`).join('&');
  return q ? `?${q}` : '';
};
