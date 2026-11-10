import { useEffect, useMemo, useState } from 'react';
import { api, isAbortError } from '../api/client';
import type { KldbHit, MetaFilters, RegionListItem } from '../api/types';
import { useFetch } from './useFetch';

/** Stammdaten der Filter (Quellen, Länder, Merkmale, Berufsgruppen) – einmal je Sitzung geladen. */
export function useMetaFilters() {
  return useFetch<MetaFilters>('/api/meta/filters', { cache: true });
}

export function useDistricts() {
  return useFetch<RegionListItem[]>('/api/regions?level=district', { cache: true });
}

export function useDistrictNames(): Map<string, RegionListItem> {
  const { data } = useDistricts();
  return useMemo(() => new Map((data ?? []).map((r) => [r.key, r])), [data]);
}

export function useSourceNames(meta: MetaFilters | undefined): Map<number, string> {
  return useMemo(() => new Map((meta?.sources ?? []).map((s) => [s.id, s.name])), [meta]);
}

export function useFeatureLabels(meta: MetaFilters | undefined): Map<string, { label: string; type: string }> {
  return useMemo(() => new Map((meta?.features ?? []).map((f) => [f.key, { label: f.label, type: f.type }])), [meta]);
}

// --- Namen von KldB-Codes (die Adresszeile enthält nur die Codes) ----------------------------------------
const kldbNames = new Map<string, string>();
const kldbPending = new Set<string>();

export function rememberKldb(code: string, name: string): void {
  if (code && name) kldbNames.set(code, name);
}

/** Liefert bekannte Namen zu KldB-Codes und lädt unbekannte nach. */
export function useKldbNames(codes: string[], meta: MetaFilters | undefined): Map<string, string> {
  const [, bump] = useState(0);
  const key = codes.join(',');

  useEffect(() => {
    for (const g of meta?.kldb_groups ?? []) rememberKldb(g.code, g.name);
    if (meta) bump((n) => n + 1);
  }, [meta]);

  useEffect(() => {
    const controller = new AbortController();
    for (const code of key ? key.split(',') : []) {
      if (kldbNames.has(code) || kldbPending.has(code) || code.length < 2) continue;
      kldbPending.add(code);
      api
        .get<KldbHit[]>('/api/meta/kldb', { query: { q: code }, signal: controller.signal })
        .then((hits) => {
          const exact = hits.find((h) => h.code === code && !h.from_title);
          if (exact) rememberKldb(code, exact.name);
          bump((n) => n + 1);
        })
        .catch((err: unknown) => {
          if (!isAbortError(err)) bump((n) => n + 1);
        })
        .finally(() => kldbPending.delete(code));
    }
    return () => controller.abort();
  }, [key]);

  return kldbNames;
}
