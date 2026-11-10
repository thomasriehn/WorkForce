/**
 * Antwortmodelle der WorkForce-API – von Hand aus dem Backend abgeleitet
 * (workforce/api/*.py, workforce/search/analytics.py, workforce/sources/manage.py).
 * Datums- und Zeitwerte kommen als ISO-Zeichenketten.
 */

export type Role = 'admin' | 'reader';

export interface SessionUser {
  username: string;
  role: Role;
  csrf_token: string;
}

// ---------------------------------------------------------------------------------------------
// Gemeinsame Bausteine
// ---------------------------------------------------------------------------------------------
export type GeoClass = 'resolved' | 'partial' | 'unresolved' | 'remote_nationwide' | 'foreign' | 'none';
export const GEO_CLASSES: GeoClass[] = ['resolved', 'partial', 'unresolved', 'remote_nationwide', 'foreign', 'none'];

export interface Totals {
  total: number;
  geo: Record<GeoClass, number>;
  labels: Record<GeoClass, string>;
}

export interface Scope {
  searched_fields: string[];
  not_searched: string;
  basis: string;
  kind_group: string;
}

export interface NearInfo {
  name: string;
  lat: number;
  lon: number;
  approximate: boolean;
  note: string;
}

export type PostingStatus = 'active' | 'not_reobserved' | 'presumed_removed' | 'ended' | 'stale';

export interface CoverageSource {
  id: number;
  name: string;
  config_status: SourceConfigStatus;
  segment: string | null;
  last_complete: string | null;
  last_status: RunStatus | null;
  stock: number;
}

export interface Coverage {
  sources: CoverageSource[];
  note: string;
}

// ---------------------------------------------------------------------------------------------
// Trefferliste
// ---------------------------------------------------------------------------------------------
export interface PostingListItem {
  id: number;
  status: PostingStatus;
  status_label: string;
  first_seen_date: string;
  first_seen_baseline: boolean;
  last_seen_date: string;
  member_count: number;
  source_ids: number[];
  title: string;
  employer_name: string | null;
  kind: string;
  kind_label: string;
  remote_type: string | null;
  working_time: string[];
  contract_term: string | null;
  date_posted: string | null;
  apply_until: string | null;
  valid_through: string | null;
  kldb_code: string | null;
  kldb_source: string | null;
  kldb_confidence: number | null;
  occupation_label: string | null;
  kreis_keys: string[];
  state_keys: string[];
  geo_class: GeoClass;
  loc_total: number;
  loc_unresolved: number;
  feature_keys: string[];
  feature_required_keys: string[];
  is_agency: boolean | null;
  salary_min: number | null;
  salary_max: number | null;
  salary_currency: string | null;
  salary_period: string | null;
  salary_origin: string | null;
  salary_text: string | null;
  detail_level: string;
  places: string | null;
  original_url: string | null;
}

export interface PostingListResponse {
  total: number;
  page: number;
  page_size: number;
  items: PostingListItem[];
  scope: Scope;
  totals: Totals;
  near: NearInfo | null;
}

export interface Facets {
  occupations: { kldb_code: string; name: string | null; count: number }[];
  occupations_unclassified: number;
  features: { key: string; label: string; count: number; required: number }[];
  employers: { name: string; count: number }[];
  kinds: { kind: string; count: number }[];
}

export interface MetaFilters {
  sources: { id: number; key: string; name: string; config_status: SourceConfigStatus; has_adapter: boolean }[];
  states: { key: string; name: string }[];
  features: { key: string; type: string; label: string; synonyms: string[] }[];
  kldb_groups: { code: string; name: string; level: number }[];
  kind_groups: string[];
  kind_labels: Record<string, string>;
  status_labels: Record<string, string>;
  sorts: string[];
  feature_types: Record<string, string>;
}

export interface KldbHit {
  code: string;
  name: string;
  level: number;
  from_title?: boolean;
}

export interface SavedSearch {
  id: number;
  name: string;
  params: Record<string, unknown>;
  created_at: string;
}

// ---------------------------------------------------------------------------------------------
// Anzeigendetail
// ---------------------------------------------------------------------------------------------
export interface PostingLocation {
  raw: string | null;
  locality: string | null;
  postal_code: string | null;
  country: string | null;
  kreis_key: string | null;
  state_key: string | null;
  match_method: string;
  precision: string;
  confidence: number | null;
  gebietsstand: string | null;
  point_origin: string | null;
}

export type Polarity = 'required' | 'desired' | 'negated' | 'unclear';

export interface PostingFeature {
  key: string;
  type: string;
  label: string;
  polarity: Polarity;
  origin: string;
  rule_version: string;
  confidence: number | null;
  evidence: string | null;
  detail: string | null;
}

export interface Salary {
  min: number | null;
  max: number | null;
  currency: string | null;
  period: string | null;
  origin: string | null;
  text: string | null;
}

export type ChangeKind = 'initial' | 'enrichment' | 'content' | 'parser' | 'mixed';

export interface PostingVersion {
  id: number;
  version_no: number;
  change_kind: ChangeKind;
  detail_level: string;
  valid_from: string;
  valid_to: string | null;
  parser_version: string;
  classifier_version: string;
  geo_rule_version: string;
  title: string;
  employer_name: string | null;
  reference: string | null;
  employer_url: string | null;
  is_agency: boolean | null;
  kind: string;
  kind_label: string;
  employment_types: string[];
  working_time: string[];
  contract_term: string | null;
  remote_type: string | null;
  occupation_label: string | null;
  occupation_field: string | null;
  kldb_code: string | null;
  kldb_source: string | null;
  kldb_confidence: number | null;
  requirement_level: number | null;
  salary: Salary;
  date_posted: string | null;
  apply_until: string | null;
  valid_through: string | null;
  excerpts: string[];
  quality: Record<string, unknown>;
  geo_class: GeoClass;
  kreis_keys: string[];
  locations: PostingLocation[];
  features: PostingFeature[];
}

export interface PostingMember {
  source_posting_id: number;
  source_id: number;
  source_name: string | null;
  source_key: string;
  original_url: string | null;
  canonical_url: string | null;
  status: PostingStatus;
  status_label: string;
  status_reason: string | null;
  first_seen_at: string;
  first_seen_baseline: boolean;
  last_seen_at: string;
  last_detail_check_at: string | null;
  is_primary: boolean;
  merge: {
    reason: string;
    confidence: number;
    rule_version: string;
    decided_by: string;
    created_at: string;
  } | null;
  periods: { start_date: string; end_date: string | null; end_reason: string | null }[];
  versions: PostingVersion[];
}

export interface PostingEvent {
  at: string;
  event_date: string;
  effective_date: string;
  type: string;
  baseline: boolean;
  source_posting_id: number | null;
  details: Record<string, unknown> | null;
}

export interface PostingDetail {
  id: number;
  status: PostingStatus;
  status_label: string;
  first_seen_date: string;
  first_seen_baseline: boolean;
  last_seen_date: string;
  member_count: number;
  dedup_rule_version: string | null;
  is_synthetic: boolean;
  current: PostingVersion | null;
  members: PostingMember[];
  events: PostingEvent[];
  notes: string[];
}

// ---------------------------------------------------------------------------------------------
// Karte, Zeitvergleich, Zeitreihe
// ---------------------------------------------------------------------------------------------
export interface MapRegionMetric {
  key: string;
  weighted: number;
  distinct: number;
  rate_per_1000: number | null;
  population_15_65: number | null;
  low_count: boolean;
}

export interface PopulationRelease {
  id: number;
  period_key: string;
  period_end: string;
  revision: number;
  published_on: string | null;
  retrieved_at: string;
  gebietsstand: string | null;
  name: string;
  attribution: string | null;
}

export interface RuleVersions {
  dedup: string;
  classifier: string;
  geo: string;
  aggregate: string;
}

export interface MapMetrics {
  as_of: string | null;
  regions: MapRegionMetric[];
  totals: Totals;
  weighted_sum: number;
  population_release: PopulationRelease | null;
  small_count_threshold: number;
  rule_versions: RuleVersions;
  formulas: { weighted: string; distinct: string; rate_per_1000: string };
  reference_date: string;
  scope: Scope;
  coverage: Coverage;
}

export interface ChangeValue {
  now: number;
  then: number;
  abs: number;
  pct: number | null;
  pct_note: string | null;
}

export interface ComparableBasis {
  date_now: string;
  date_then: string;
  comparable_sources: number[];
  excluded: { source_id: number; name: string | null; reason: string }[];
  hints: string[];
  notes: { date: string; kind: string; message: string }[];
  comparable: boolean;
}

export interface MapChange {
  days: number;
  metric: 'weighted' | 'distinct';
  basis: ComparableBasis;
  regions: (ChangeValue & { key: string; low_count: boolean })[];
  total: ChangeValue | null;
  message?: string | null;
}

export type RunQuality = 'complete' | 'partial' | 'none';

export interface TimeSeriesPoint {
  date: string;
  stock: number | null;
  first_seen: number;
  baseline: number;
  changed: number;
  left: number;
  republished: number;
  reactivated: number;
  run_quality: RunQuality;
  before_start: boolean;
}

export interface TimeSeries {
  from: string;
  to: string;
  points: TimeSeriesPoint[];
  sampled_every_days: number;
  notes: { date: string; kind: string; message: string }[];
  provisional_days: number;
  definitions: Record<string, string>;
}

export interface KreisProperties {
  key: string;
  name: string;
  type: string | null;
  state_key: string | null;
  state: string | null;
  gebietsstand: string;
}

export interface KreiseGeoJson extends GeoJSON.FeatureCollection<GeoJSON.Polygon | GeoJSON.MultiPolygon, KreisProperties> {
  attribution: string | null;
  gebietsstand: string | null;
}

// ---------------------------------------------------------------------------------------------
// Dashboard
// ---------------------------------------------------------------------------------------------
export interface DashboardChange {
  total: ChangeValue | null;
  basis: ComparableBasis;
  message: string | null;
}

export interface StatFreshness {
  key: string;
  name: string;
  publisher: string;
  period_key: string;
  period_end: string;
  revision: number;
  published_on: string | null;
  retrieved_at: string;
  age_days: number;
}

export interface OpsWarning {
  id: number;
  kind: string;
  message: string;
  created_at: string;
}

export interface Dashboard {
  reference_date: string;
  generated_at: string;
  totals: Record<'jobs' | 'ausbildung' | 'praktikum', Totals>;
  coverage: Coverage;
  changes: Record<string, DashboardChange>;
  top_regions: (MapRegionMetric & { name: string })[];
  top_regions_label: string;
  freshness: { statistics: StatFreshness[] };
  warnings: OpsWarning[];
  notes: { note_date: string; kind: string; message: string }[];
  timeseries: TimeSeries;
  disclaimer: string;
}

// ---------------------------------------------------------------------------------------------
// Regionen und amtliche Statistik
// ---------------------------------------------------------------------------------------------
export interface RegionListItem {
  key: string;
  name: string;
  type_label: string | null;
  parent_key: string | null;
  gebietsstand: string;
}

export type ValueStatus = 'ok' | 'zero' | 'suppressed' | 'unknown' | 'not_available' | 'not_collected';

export interface RegionContextRow {
  indicator_key: string;
  name: string;
  unit: string;
  definition: string | null;
  population_group: string | null;
  dim_key: string;
  dim_label: string | null;
  value: number | null;
  value_status: ValueStatus;
  raw_value: string | null;
  period_key: string;
  period_end: string;
  revision: number;
  published_on: string | null;
  retrieved_at: string;
  gebietsstand: string | null;
  dataset: string;
  publisher: string;
  attribution: string | null;
  licence: string | null;
  landing_url: string | null;
  revisions: number;
  age_days: number;
}

export interface RegionDetail {
  region: {
    key: string;
    name: string;
    type_label: string | null;
    parent_key: string | null;
    gebietsstand: string;
    area_km2: number | null;
    source_note: string | null;
    state_name?: string | null;
  };
  level: 'district' | 'state';
  totals: Totals;
  metrics?: MapRegionMetric;
  timeseries: TimeSeries;
  facets: Facets;
  context: RegionContextRow[];
  context_note: string;
}

export interface StatDataset {
  key: string;
  name: string;
  publisher: string;
  dataset_code: string | null;
  landing_url: string | null;
  licence: string | null;
  licence_url: string | null;
  attribution: string | null;
  update_cycle: string | null;
  notes: string | null;
}

export interface StatIndicator {
  key: string;
  name: string;
  definition: string | null;
  unit: string;
  population_group: string | null;
  dataset_key: string | null;
}

export interface StatRelease {
  id: number;
  dataset_key: string;
  period_key: string;
  period_start: string | null;
  period_end: string;
  revision: number;
  is_current: boolean;
  published_on: string | null;
  retrieved_at: string;
  file_url: string | null;
  file_name: string | null;
  file_sha256: string;
  gebietsstand: string | null;
  import_method: string;
  row_count: number;
  notes: string | null;
  age_days: number;
}

export interface StatsOverview {
  datasets: StatDataset[];
  indicators: StatIndicator[];
  releases: StatRelease[];
  note: string;
}

export interface StatsMapRelease {
  id: number;
  dataset_key: string;
  dataset_name: string;
  publisher: string;
  period_key: string;
  period_start: string | null;
  period_end: string;
  revision: number;
  is_current: boolean;
  published_on: string | null;
  retrieved_at: string;
  file_url: string | null;
  file_sha256: string;
  gebietsstand: string | null;
  attribution: string | null;
  licence: string | null;
  licence_url: string | null;
  landing_url: string | null;
  age_days: number;
}

export interface StatsMap {
  indicator: StatIndicator;
  release: StatsMapRelease | null;
  periods: { period_key: string; period_end: string; revision: number; is_current: boolean }[];
  values: { key: string; value: number | null; status: ValueStatus; raw: string | null }[];
  status_labels?: Record<string, string>;
  message?: string;
}

// ---------------------------------------------------------------------------------------------
// Quellenverwaltung
// ---------------------------------------------------------------------------------------------
export type SourceConfigStatus = 'candidate' | 'active' | 'disabled' | 'permission_required';
export type SourceHealth = 'ok' | 'degraded' | 'blocked' | 'failing' | 'running' | 'never_run' | 'inactive';
export type RunStatus = 'queued' | 'running' | 'paused' | 'complete' | 'partial' | 'blocked' | 'failed' | 'cancelled';

export interface SourceScope {
  id: number;
  key: string;
  version: number;
  name: string;
  mode: 'full' | 'new_only';
  params: Record<string, unknown>;
  is_active: boolean;
  page_budget: number | null;
  note: string | null;
  created_at: string;
  retired_at: string | null;
}

export interface Source {
  id: number;
  key: string;
  name: string;
  domain: string;
  entry_url: string | null;
  country: string;
  segment: string | null;
  is_career_page: boolean;
  access_method: string | null;
  adapter_key: string | null;
  adapter_version: string | null;
  adapter_available: boolean;
  discovery_mode: string | null;
  store_excerpts: boolean | null;
  allowed_domains: string[];
  terms_url: string | null;
  robots_url: string | null;
  legal_checked_on: string | null;
  legal_notes: string | null;
  attribution: string | null;
  config_status: SourceConfigStatus;
  status_reason: string | null;
  budget: { request_interval_seconds: number; max_pages_per_run: number; max_details_per_run: number };
  updated_at: string;
  health: SourceHealth;
  last_run: {
    id: number;
    status: RunStatus;
    status_detail: string | null;
    logical_date: string;
    finished_at: string | null;
    list_complete: boolean | null;
    detail_complete: boolean | null;
  } | null;
  last_complete_run: { id: number; logical_date: string; finished_at: string | null } | null;
  data_as_of: string | null;
  stock: number;
  postings_total: number;
  details_pending: number;
  scopes: SourceScope[];
}

export interface SourcesResponse {
  sources: Source[];
  crawler: { user_agent: string; contact_configured: boolean; scan_time: string; timezone: string };
  status_labels: Record<SourceConfigStatus, string>;
  health_labels: Record<SourceHealth, string>;
}

export interface ScanRun {
  id: number;
  source_id: number;
  source_name?: string | null;
  scope_id: number;
  scope_key: string;
  scope_version: number;
  logical_date: string;
  trigger: string;
  mode: string;
  is_test: boolean;
  is_baseline: boolean;
  page_limit: number | null;
  parser_version: string | null;
  classifier_version: string | null;
  status: RunStatus;
  status_detail: string | null;
  control: string | null;
  list_complete: boolean | null;
  detail_complete: boolean | null;
  attempts: number;
  created_at: string;
  started_at: string | null;
  finished_at: string | null;
  window_start: string | null;
  window_end: string | null;
  pages_fetched: number;
  requests_made: number;
  partitions_total: number;
  partitions_done: number;
  reported_total: number | null;
  ids_found: number;
  postings_extracted: number;
  postings_new: number;
  postings_changed: number;
  details_fetched: number;
  details_pending: number;
  error_count: number;
  coverage: (Record<string, unknown> & { note?: string | null }) | null;
}

export interface ScanRunDetail extends ScanRun {
  tasks: {
    id: number;
    kind: string;
    partition_key: string;
    status: string;
    status_detail: string | null;
    pages_fetched: number;
    ids_found: number;
    reported_total: number | null;
    started_at: string | null;
    finished_at: string | null;
  }[];
  errors: { at: string; kind: string; url: string | null; message: string | null }[];
}

export interface RunStartResponse {
  runs: { run_id: number; scope: string; created: boolean; status: RunStatus; note: string | null }[];
}

export interface MergeCandidate {
  id: number;
  reason: string;
  score: number;
  rule_version: string;
  state: string;
  created_at: string;
  a_id: number;
  a_merged: number | null;
  a_title: string | null;
  a_employer: string | null;
  a_source: string;
  b_id: number;
  b_merged: number | null;
  b_title: string | null;
  b_employer: string | null;
  b_source: string;
}

export interface SystemJob {
  id: number;
  kind: string;
  status: string;
  attempts: number;
  created_at: string;
  started_at: string | null;
  finished_at: string | null;
  last_error: string | null;
  result: Record<string, unknown> | null;
}

export interface SystemStatus {
  version: string;
  env: string;
  timezone: string;
  scan_time: string;
  jobs: Record<string, number>;
  recent_jobs: SystemJob[];
  counts: Record<string, number>;
  warnings: OpsWarning[];
  settings: Record<string, number>;
}

export interface AppUser {
  id: number;
  username: string;
  role: Role;
  is_active: boolean;
  created_at: string;
  last_login_at: string | null;
}

export interface UserCreateResponse {
  id: number;
  username: string;
  role: Role;
  generated_password: string | null;
  note: string;
}

export interface UserUpdateResponse {
  id: number;
  username: string;
  role: Role;
  is_active: boolean;
  generated_password?: string;
}
