/**
 * Gemeinsamer API-Client: relative URLs unter /api, Sitzungs-Cookie (HttpOnly) über same-origin,
 * CSRF-Kopfzeile für alle schreibenden Anfragen und einheitliche Fehlerobjekte mit deutscher Meldung.
 */

export class ApiError extends Error {
  readonly status: number;
  readonly detail: unknown;

  constructor(status: number, message: string, detail?: unknown) {
    super(message);
    this.name = 'ApiError';
    this.status = status;
    this.detail = detail;
  }
}

export type QueryValue = string | number | boolean | null | undefined | readonly (string | number)[];
export type Query = Record<string, QueryValue> | URLSearchParams;

let csrfToken: string | null = null;
let unauthorizedHandler: (() => void) | null = null;

export function setCsrfToken(token: string | null): void {
  csrfToken = token;
}

/** Wird aufgerufen, sobald eine Anfrage mit 401 beantwortet wird (Sitzung abgelaufen). */
export function setUnauthorizedHandler(handler: (() => void) | null): void {
  unauthorizedHandler = handler;
}

export function toSearchParams(query?: Query): URLSearchParams {
  if (!query) return new URLSearchParams();
  if (query instanceof URLSearchParams) return new URLSearchParams(query);
  const sp = new URLSearchParams();
  for (const [key, value] of Object.entries(query)) {
    if (value === null || value === undefined || value === '') continue;
    if (Array.isArray(value)) {
      if (value.length > 0) sp.set(key, value.join(','));
    } else {
      sp.set(key, String(value));
    }
  }
  return sp;
}

export function buildUrl(path: string, query?: Query): string {
  const qs = toSearchParams(query).toString();
  return qs ? `${path}?${qs}` : path;
}

const FALLBACK_MESSAGES: Record<number, string> = {
  400: 'Die Anfrage war ungültig.',
  401: 'Sie sind nicht angemeldet oder Ihre Sitzung ist abgelaufen.',
  403: 'Für diese Aktion fehlt Ihnen die Berechtigung.',
  404: 'Der angeforderte Eintrag wurde nicht gefunden.',
  409: 'Der Eintrag steht im Konflikt mit einem vorhandenen Eintrag.',
  413: 'Die übermittelte Datei ist zu groß.',
  422: 'Die Eingabe konnte nicht verarbeitet werden.',
};

function fallbackMessage(status: number): string {
  if (FALLBACK_MESSAGES[status]) return FALLBACK_MESSAGES[status];
  if (status >= 500) return `Der Server meldet einen Fehler (HTTP ${status}). Bitte versuchen Sie es später erneut.`;
  return `Unerwartete Antwort des Servers (HTTP ${status}).`;
}

/** FastAPI liefert `detail` als Text oder – bei Validierungsfehlern – als Liste mit `loc` und `msg`. */
function messageFromDetail(detail: unknown): string | null {
  if (typeof detail === 'string' && detail.trim()) return detail;
  if (Array.isArray(detail)) {
    const parts = detail
      .map((entry) => {
        if (entry && typeof entry === 'object') {
          const e = entry as { loc?: unknown; msg?: unknown };
          const loc = Array.isArray(e.loc) ? e.loc.filter((p) => p !== 'body' && p !== 'query' && p !== 'path').join('.') : '';
          const msg = typeof e.msg === 'string' ? e.msg : '';
          return loc && msg ? `${loc}: ${msg}` : msg || loc;
        }
        return typeof entry === 'string' ? entry : '';
      })
      .filter(Boolean);
    if (parts.length) return `Eingabe ungültig – ${parts.join('; ')}`;
  }
  return null;
}

async function toApiError(res: Response): Promise<ApiError> {
  let detail: unknown;
  try {
    const type = res.headers.get('content-type') ?? '';
    if (type.includes('json')) {
      const body: unknown = await res.json();
      detail = body && typeof body === 'object' && 'detail' in body ? (body as { detail: unknown }).detail : body;
    }
  } catch {
    detail = undefined;
  }
  return new ApiError(res.status, messageFromDetail(detail) ?? fallbackMessage(res.status), detail);
}

export function isAbortError(err: unknown): boolean {
  return err instanceof DOMException && err.name === 'AbortError';
}

interface RequestOptions {
  query?: Query;
  json?: unknown;
  form?: FormData;
  signal?: AbortSignal;
  /** Für Anmeldung und Sitzungsprüfung: 401 nicht als „Sitzung abgelaufen“ behandeln. */
  quiet401?: boolean;
}

async function request<T>(method: string, path: string, options: RequestOptions = {}): Promise<T> {
  const headers: Record<string, string> = { Accept: 'application/json' };
  let body: BodyInit | undefined;
  if (options.json !== undefined) {
    headers['Content-Type'] = 'application/json';
    body = JSON.stringify(options.json);
  } else if (options.form) {
    body = options.form;
  }
  if (method !== 'GET' && method !== 'HEAD' && csrfToken) {
    headers['X-CSRF-Token'] = csrfToken;
  }
  let res: Response;
  try {
    res = await fetch(buildUrl(path, options.query), {
      method,
      headers,
      body,
      credentials: 'same-origin',
      signal: options.signal,
    });
  } catch (err) {
    if (isAbortError(err)) throw err;
    throw new ApiError(0, 'Der Server ist nicht erreichbar. Bitte prüfen Sie die Verbindung und versuchen Sie es erneut.');
  }
  if (!res.ok) {
    const error = await toApiError(res);
    if (res.status === 401 && !options.quiet401) unauthorizedHandler?.();
    throw error;
  }
  if (res.status === 204) return undefined as T;
  const type = res.headers.get('content-type') ?? '';
  if (type.includes('json')) return (await res.json()) as T;
  return (await res.text()) as unknown as T;
}

export const api = {
  get: <T>(path: string, options?: Pick<RequestOptions, 'query' | 'signal' | 'quiet401'>) => request<T>('GET', path, options),
  post: <T>(path: string, json?: unknown, options?: Pick<RequestOptions, 'query' | 'quiet401'>) =>
    request<T>('POST', path, { ...options, json: json ?? {} }),
  postForm: <T>(path: string, form: FormData) => request<T>('POST', path, { form }),
  patch: <T>(path: string, json?: unknown, options?: Pick<RequestOptions, 'query'>) =>
    request<T>('PATCH', path, { ...options, json: json ?? {} }),
  delete: <T>(path: string) => request<T>('DELETE', path),
};

// --- kleiner Zwischenspeicher für selten wechselnde Stammdaten (Filterlisten, Kreisgrenzen) ----------
const cache = new Map<string, Promise<unknown>>();

export function cachedGet<T>(url: string): Promise<T> {
  let hit = cache.get(url);
  if (!hit) {
    hit = api.get<T>(url).catch((err: unknown) => {
      cache.delete(url);
      throw err;
    });
    cache.set(url, hit);
  }
  return hit as Promise<T>;
}

export function invalidateCached(url: string): void {
  cache.delete(url);
}

export function clearApiCache(): void {
  cache.clear();
}

export function errorMessage(err: unknown): string {
  if (err instanceof ApiError) return err.message;
  if (err instanceof Error && err.message) return err.message;
  return 'Unbekannter Fehler.';
}
