/**
 * apiFetch — Centralized API fetch utility for CV. Dewi Aditya ERP
 * 
 * Usage:
 *   import apiFetch from '@/lib/apiFetch';
 *   const data = await apiFetch('/employees', { method: 'GET' });
 * 
 *   import { apiFetch, ApiError, configureApi } from '@/lib/apiFetch';
 */

const BACKEND_URL = process.env.REACT_APP_BACKEND_URL || '';

// Internal config — mutable via configureApi()
let _config = {
  onUnauthorized: null,
};

/**
 * Configure global apiFetch behaviour.
 * Call once in App.js useEffect with your logout/redirect handler.
 */
export function configureApi(options = {}) {
  if (options.onUnauthorized) _config.onUnauthorized = options.onUnauthorized;
}

/**
 * Custom error class with HTTP status + backend detail message.
 */
export class ApiError extends Error {
  constructor(status, detail, body) {
    super(detail || `HTTP ${status}`);
    this.status = status;
    this.detail = detail;
    this.body = body;
    this.name = 'ApiError';
  }
}

/**
 * Token login yang dipakai setiap panggilan API (override → erp_token → client_token).
 * Dipakai bersama oleh apiFetch dan sseFetch (Asisten AI) supaya cara membaca token hanya satu.
 */
export function resolveToken(tokenOverride) {
  if (tokenOverride !== undefined) return tokenOverride;
  try {
    return localStorage.getItem('erp_token') || localStorage.getItem('client_token');
  } catch {
    return null;
  }
}

/** Alamat lengkap endpoint: '/x' → `${BACKEND}/api/x`; '/api/x' dan http(s)://… dipakai apa adanya. */
export function buildApiUrl(endpoint) {
  if (endpoint.startsWith('http://') || endpoint.startsWith('https://')) return endpoint;
  const clean = endpoint.startsWith('/') ? endpoint : `/${endpoint}`;
  const prefix = clean.startsWith('/api') ? '' : '/api';
  return `${BACKEND_URL}${prefix}${clean}`;
}

/** Jalankan penanganan sesi habis (logout/redirect) yang dipasang lewat configureApi. */
export function notifyUnauthorized() {
  if (_config.onUnauthorized) _config.onUnauthorized();
}

/**
 * apiFetch — Fetch wrapper for all ERP API calls.
 *
 * @param {string} endpoint   — API path, e.g. '/employees' (no /api prefix, added automatically)
 * @param {object} options
 *   @param {string}  method             — HTTP verb (default: 'GET')
 *   @param {object}  body               — Request body (serialized as JSON)
 *   @param {string}  token              — JWT token (default: read from localStorage)
 *   @param {boolean} skipOnUnauthorized — If true, 401 won't trigger onUnauthorized (login page)
 *   @param {boolean} rawResponse        — If true, return raw Response (for file downloads)
 *   @param {object}  headers            — Extra headers merged with defaults
 *   @param {FormData} formData          — Send as multipart/form-data (body ignored if set)
 */
async function apiFetch(endpoint, options = {}) {
  const {
    method = 'GET',
    body,
    token: tokenOverride,
    skipOnUnauthorized = false,
    rawResponse = false,
    headers: extraHeaders = {},
    formData,
  } = options;

  // Resolve JWT token
  const token = resolveToken(tokenOverride);

  // Build headers
  const headers = {};
  if (token) headers['Authorization'] = `Bearer ${token}`;

  if (formData) {
    // Let browser set Content-Type with boundary for multipart
  } else {
    headers['Content-Type'] = 'application/json';
  }

  Object.assign(headers, extraHeaders);

  // Build URL — endpoint may already start with /api or just /
  const url = buildApiUrl(endpoint);

  // Build fetch init
  const init = {
    method,
    headers,
  };

  if (formData) {
    init.body = formData;
  } else if (body !== undefined) {
    // If body is already a string, assume it's already JSON-stringified by caller.
    // Otherwise, stringify it. This prevents double-encoding when caller passes
    // JSON.stringify(...) directly.
    init.body = typeof body === 'string' ? body : JSON.stringify(body);
  }

  let response;
  try {
    response = await fetch(url, init);
  } catch (networkErr) {
    throw new ApiError(0, 'Tidak dapat terhubung ke server. Periksa koneksi Anda.', null);
  }

  // Handle 401 — unauthorized
  if (response.status === 401) {
    if (!skipOnUnauthorized) notifyUnauthorized();
    const errBody = await response.json().catch(() => ({}));
    throw new ApiError(401, errBody.detail || 'Sesi habis. Silakan login kembali.', errBody);
  }

  // Return raw response for file downloads
  if (rawResponse) return response;

  // Parse JSON (or text)
  let data;
  const contentType = response.headers.get('content-type') || '';

  if (contentType.includes('application/json')) {
    data = await response.json();
  } else if (contentType.includes('text/')) {
    data = await response.text();
  } else {
    // For binary/other, return blob
    data = await response.blob();
  }

  if (!response.ok) {
    const detail =
      typeof data === 'object'
        ? data?.detail || data?.message || `HTTP ${response.status}`
        : String(data);
    throw new ApiError(response.status, detail, data);
  }

  return data;
}

export { apiFetch };
export default apiFetch;
