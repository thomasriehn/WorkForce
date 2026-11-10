import { useCallback, useMemo } from 'react';
import { useSearchParams } from 'react-router';
import { DEFAULT_FILTERS, FILTER_PARAM_NAMES, type Filters, parseFilters, serializeFilters } from './model';

export interface FilterController {
  filters: Filters;
  /** Abfragezeichenkette nur der Filter – identisch für alle API-Aufrufe einer Seite. */
  query: string;
  update: (patch: Partial<Filters>) => void;
  reset: () => void;
  /** Seitenspezifische Parameter (z. B. sort, metric) lesen und setzen, ohne die Filter zu berühren. */
  getParam: (name: string) => string | null;
  setParams: (patch: Record<string, string | null>, options?: { replace?: boolean }) => void;
}

/**
 * Der gesamte Filterzustand lebt in der Abfragezeichenkette der Adresse. Jede Änderung erzeugt einen
 * Verlaufseintrag (Zurück-Schaltfläche funktioniert) und setzt die Seitennummer zurück.
 */
export function useFilters(): FilterController {
  const [searchParams, setSearchParams] = useSearchParams();
  const key = searchParams.toString();

  const filters = useMemo(() => parseFilters(new URLSearchParams(key)), [key]);
  const query = useMemo(() => serializeFilters(filters).toString(), [filters]);

  const update = useCallback(
    (patch: Partial<Filters>) => {
      setSearchParams((prev) => {
        const next = new URLSearchParams(prev);
        serializeFilters({ ...parseFilters(prev), ...patch }, next);
        next.delete('page');
        return next;
      });
    },
    [setSearchParams],
  );

  const reset = useCallback(() => {
    setSearchParams((prev) => {
      const next = new URLSearchParams(prev);
      const kindGroup = parseFilters(prev).kindGroup;
      for (const name of FILTER_PARAM_NAMES) next.delete(name);
      serializeFilters({ ...DEFAULT_FILTERS, kindGroup }, next);
      next.delete('page');
      return next;
    });
  }, [setSearchParams]);

  const getParam = useCallback((name: string) => new URLSearchParams(key).get(name), [key]);

  const setParams = useCallback(
    (patch: Record<string, string | null>, options?: { replace?: boolean }) => {
      setSearchParams(
        (prev) => {
          const next = new URLSearchParams(prev);
          for (const [name, value] of Object.entries(patch)) {
            if (value === null || value === '') next.delete(name);
            else next.set(name, value);
          }
          return next;
        },
        { replace: options?.replace },
      );
    },
    [setSearchParams],
  );

  return { filters, query, update, reset, getParam, setParams };
}
