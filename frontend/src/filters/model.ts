/**
 * Gemeinsames Filtermodell für Stellensuche, Karte, Summen, Regionendetail und Diagramme.
 *
 * Die Parameternamen in der Adresszeile sind bewusst dieselben wie in der API (`filters_dep` im Backend).
 * Dadurch ist die Abfragezeichenkette einer Seite zugleich die Abfrage an die API: Liste, Karte, Summen,
 * Zeitreihen und CSV-Export verwenden nachweislich identische Filter, und jede Suche ist als Link teilbar.
 */

export type KindGroup = 'jobs' | 'ausbildung' | 'praktikum' | 'all';
export const KIND_GROUPS: KindGroup[] = ['jobs', 'ausbildung', 'praktikum', 'all'];

export type DateField = 'first_seen' | 'date_posted';
export type ContractTerm = '' | 'befristet' | 'unbefristet';

export interface Filters {
  q: string;
  fuzzy: boolean;
  kldb: string[];
  features: string[];
  featuresMode: 'and' | 'or';
  featuresRequired: boolean;
  states: string[];
  kreise: string[];
  place: string;
  plz: string;
  radiusKm: number | null;
  dateFrom: string;
  dateTo: string;
  dateField: DateField;
  status: string[];
  sources: string[];
  kindGroup: KindGroup;
  remote: string[];
  workingTime: string[];
  contractTerm: ContractTerm;
  geoClass: string[];
  employer: string;
  asOf: string;
}

export const DEFAULT_FILTERS: Filters = {
  q: '',
  fuzzy: false,
  kldb: [],
  features: [],
  featuresMode: 'and',
  featuresRequired: false,
  states: [],
  kreise: [],
  place: '',
  plz: '',
  radiusKm: null,
  dateFrom: '',
  dateTo: '',
  dateField: 'first_seen',
  status: [],
  sources: [],
  kindGroup: 'jobs',
  remote: [],
  workingTime: [],
  contractTerm: '',
  geoClass: [],
  employer: '',
  asOf: '',
};

export const DEFAULT_RADIUS_KM = 25;
export const RADIUS_OPTIONS = [5, 10, 25, 50, 100, 200];

/** Alle Parameternamen, die zum Filtermodell gehören (alles andere in der URL ist seitenspezifisch). */
export const FILTER_PARAM_NAMES = [
  'q',
  'fuzzy',
  'kldb',
  'features',
  'features_mode',
  'features_required',
  'states',
  'kreise',
  'place',
  'plz',
  'radius_km',
  'date_from',
  'date_to',
  'date_field',
  'status',
  'sources',
  'kind_group',
  'remote',
  'working_time',
  'contract_term',
  'geo_class',
  'employer',
  'as_of',
] as const;

const ISO_DATE = /^\d{4}-\d{2}-\d{2}$/;

function list(sp: URLSearchParams, name: string): string[] {
  const out: string[] = [];
  for (const raw of sp.getAll(name)) {
    for (const part of raw.split(',')) {
      const v = part.trim();
      if (v && !out.includes(v)) out.push(v);
    }
  }
  return out;
}

function date(sp: URLSearchParams, name: string): string {
  const v = sp.get(name) ?? '';
  return ISO_DATE.test(v) ? v : '';
}

function oneOf<T extends string>(value: string | null, allowed: readonly T[], fallback: T): T {
  return allowed.includes(value as T) ? (value as T) : fallback;
}

export function parseFilters(sp: URLSearchParams): Filters {
  const radiusRaw = Number(sp.get('radius_km'));
  const place = (sp.get('place') ?? '').trim();
  const plz = (sp.get('plz') ?? '').trim();
  const hasCenter = place !== '' || plz !== '';
  return {
    q: sp.get('q') ?? '',
    fuzzy: sp.get('fuzzy') === 'true' || sp.get('fuzzy') === '1',
    kldb: list(sp, 'kldb'),
    features: list(sp, 'features'),
    featuresMode: oneOf(sp.get('features_mode'), ['and', 'or'] as const, 'and'),
    featuresRequired: sp.get('features_required') === 'true' || sp.get('features_required') === '1',
    states: list(sp, 'states'),
    kreise: list(sp, 'kreise'),
    place,
    plz,
    radiusKm: hasCenter ? (Number.isFinite(radiusRaw) && radiusRaw >= 1 && radiusRaw <= 300 ? radiusRaw : DEFAULT_RADIUS_KM) : null,
    dateFrom: date(sp, 'date_from'),
    dateTo: date(sp, 'date_to'),
    dateField: oneOf(sp.get('date_field'), ['first_seen', 'date_posted'] as const, 'first_seen'),
    status: list(sp, 'status'),
    sources: list(sp, 'sources').filter((s) => /^\d+$/.test(s)),
    kindGroup: oneOf(sp.get('kind_group'), KIND_GROUPS, 'jobs'),
    remote: list(sp, 'remote'),
    workingTime: list(sp, 'working_time'),
    contractTerm: oneOf(sp.get('contract_term'), ['', 'befristet', 'unbefristet'] as const, ''),
    geoClass: list(sp, 'geo_class'),
    employer: sp.get('employer') ?? '',
    asOf: date(sp, 'as_of'),
  };
}

/** Schreibt nur vom Standard abweichende Werte – kurze, gut lesbare Links. */
export function serializeFilters(f: Filters, target: URLSearchParams = new URLSearchParams()): URLSearchParams {
  for (const name of FILTER_PARAM_NAMES) target.delete(name);
  const set = (name: string, value: string) => {
    if (value) target.set(name, value);
  };
  set('q', f.q.trim());
  if (f.fuzzy) target.set('fuzzy', 'true');
  set('kldb', f.kldb.join(','));
  set('features', f.features.join(','));
  if (f.features.length > 0 && f.featuresMode === 'or') target.set('features_mode', 'or');
  if (f.features.length > 0 && f.featuresRequired) target.set('features_required', 'true');
  set('states', f.states.join(','));
  set('kreise', f.kreise.join(','));
  const place = f.place.trim();
  const plz = f.plz.trim();
  if (place || plz) {
    set('place', place);
    set('plz', plz);
    // Ohne Umkreis würde die API den Ort ignorieren – daher immer mit Radius senden.
    target.set('radius_km', String(f.radiusKm ?? DEFAULT_RADIUS_KM));
  }
  set('date_from', f.dateFrom);
  set('date_to', f.dateTo);
  if ((f.dateFrom || f.dateTo) && f.dateField === 'date_posted') target.set('date_field', 'date_posted');
  set('status', f.status.join(','));
  set('sources', f.sources.join(','));
  if (f.kindGroup !== 'jobs') target.set('kind_group', f.kindGroup);
  set('remote', f.remote.join(','));
  set('working_time', f.workingTime.join(','));
  set('contract_term', f.contractTerm);
  set('geo_class', f.geoClass.join(','));
  set('employer', f.employer.trim());
  set('as_of', f.asOf);
  return target;
}

export function filtersToQuery(f: Filters, extra?: Record<string, string | number | null | undefined>): string {
  const sp = serializeFilters(f);
  if (extra) {
    for (const [k, v] of Object.entries(extra)) {
      if (v !== null && v !== undefined && v !== '') sp.set(k, String(v));
    }
  }
  return sp.toString();
}

export function withQuery(path: string, query: string): string {
  return query ? `${path}?${query}` : path;
}

/** Anzahl gesetzter Filter (ohne Beschäftigungsart, die als Reiter immer sichtbar ist). */
export function countActiveFilters(f: Filters): number {
  let n = 0;
  if (f.q.trim()) n += 1;
  n += f.kldb.length + f.features.length + f.states.length + f.kreise.length + f.status.length + f.sources.length;
  n += f.remote.length + f.workingTime.length + f.geoClass.length;
  if (f.place.trim() || f.plz.trim()) n += 1;
  if (f.dateFrom || f.dateTo) n += 1;
  if (f.contractTerm) n += 1;
  if (f.employer.trim()) n += 1;
  if (f.asOf) n += 1;
  return n;
}

/** Für gespeicherte Suchen: Filter (und Sortierung) als flaches Objekt. */
export function filtersToParams(f: Filters, sort?: string | null): Record<string, string> {
  const out: Record<string, string> = {};
  serializeFilters(f).forEach((value, key) => {
    out[key] = value;
  });
  if (sort) out.sort = sort;
  return out;
}

export function paramsToSearch(params: Record<string, unknown>): URLSearchParams {
  const sp = new URLSearchParams();
  for (const [key, value] of Object.entries(params)) {
    if (value === null || value === undefined) continue;
    if (Array.isArray(value)) {
      if (value.length) sp.set(key, value.map(String).join(','));
    } else if (typeof value === 'string' || typeof value === 'number' || typeof value === 'boolean') {
      if (String(value) !== '') sp.set(key, String(value));
    }
  }
  return sp;
}
