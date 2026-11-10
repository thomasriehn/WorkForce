import { useCallback, useEffect, useRef, useState } from 'react';
import { ApiError, api, cachedGet, errorMessage, invalidateCached, isAbortError } from '../api/client';

export interface FetchState<T> {
  /** Zuletzt geladene Daten; bleibt während eines Nachladens erhalten (kein Flackern). */
  data: T | undefined;
  error: ApiError | null;
  /** true, solange eine Anfrage läuft. */
  loading: boolean;
  /** true, wenn `data` noch zur vorherigen Anfrage gehört. */
  stale: boolean;
  reload: () => void;
}

interface Options {
  /** Stammdaten, die sich selten ändern, für die Dauer der Sitzung zwischenspeichern. */
  cache?: boolean;
}

interface Inner<T> {
  data: T | undefined;
  error: ApiError | null;
  loading: boolean;
  loadedUrl: string | null;
}

/**
 * Lädt eine GET-Ressource, sobald sich die URL ändert. `url = null` bedeutet: (noch) nichts laden.
 * Laufende Anfragen werden beim Wechsel abgebrochen; veraltete Antworten werden verworfen.
 */
export function useFetch<T>(url: string | null, options: Options = {}): FetchState<T> {
  const useCache = options.cache === true;
  const [state, setState] = useState<Inner<T>>({ data: undefined, error: null, loading: url !== null, loadedUrl: null });
  const [nonce, setNonce] = useState(0);
  const seenNonce = useRef(0);

  useEffect(() => {
    if (url === null) {
      setState({ data: undefined, error: null, loading: false, loadedUrl: null });
      return;
    }
    const controller = new AbortController();
    let active = true;
    setState((prev) => ({ ...prev, loading: true, error: null }));
    if (useCache && seenNonce.current !== nonce) invalidateCached(url); // „Erneut laden“ umgeht den Zwischenspeicher
    seenNonce.current = nonce;
    const promise = useCache ? cachedGet<T>(url) : api.get<T>(url, { signal: controller.signal });
    promise
      .then((data) => {
        if (active) setState({ data, error: null, loading: false, loadedUrl: url });
      })
      .catch((err: unknown) => {
        if (!active || isAbortError(err)) return;
        const error = err instanceof ApiError ? err : new ApiError(0, errorMessage(err));
        setState({ data: undefined, error, loading: false, loadedUrl: url });
      });
    return () => {
      active = false;
      controller.abort();
    };
  }, [url, nonce, useCache]);

  const reload = useCallback(() => setNonce((n) => n + 1), []);

  return {
    data: state.data,
    error: state.error,
    loading: state.loading || (url !== null && state.loadedUrl !== url && state.error === null),
    stale: state.data !== undefined && state.loadedUrl !== url,
    reload,
  };
}
