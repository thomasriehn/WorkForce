/**
 * Deutsche Bezeichnungen für Schlüsselwerte der API. Wo die API selbst Beschriftungen liefert
 * (status_label, kind_label, labels der Summen), haben diese Vorrang; die Tabellen hier sind Rückfallwerte
 * und Erläuterungen in Klartext.
 */
import type { ChangeKind, GeoClass, Polarity, PostingStatus, RunStatus, SourceConfigStatus, SourceHealth, ValueStatus } from '../api/types';

export type Tone = 'good' | 'warn' | 'serious' | 'crit' | 'info' | 'neutral' | 'muted';

export const POSTING_STATUS_LABELS: Record<PostingStatus, string> = {
  active: 'aktiv beobachtet',
  not_reobserved: 'nicht erneut beobachtet',
  presumed_removed: 'vermutlich entfernt',
  ended: 'als beendet beobachtet',
  stale: 'unbekannt/veraltet',
};

export const POSTING_STATUS_TONE: Record<PostingStatus, Tone> = {
  active: 'good',
  not_reobserved: 'warn',
  presumed_removed: 'serious',
  ended: 'neutral',
  stale: 'muted',
};

export const POSTING_STATUS_HELP: Record<PostingStatus, string> = {
  active: 'Im letzten vollständigen Scan des Suchbereichs gesehen.',
  not_reobserved: 'In einem vollständigen Scan nicht wiedergefunden – zählt weiter zum Bestand, bis genügend Scans vorliegen.',
  presumed_removed: 'In mehreren vollständigen, vergleichbaren Scans nicht mehr gefunden. Eine Ableitung, kein Nachweis – und kein Beleg, dass die Stelle besetzt wurde.',
  ended: 'Von der Quelle als beendet gemeldet oder das angekündigte Veröffentlichungsende ist erreicht.',
  stale: 'Seit längerer Zeit kein vergleichbarer Scan – der Zustand ist unbekannt.',
};

export const CONFIG_STATUS_LABELS: Record<SourceConfigStatus, string> = {
  candidate: 'vorgemerkt',
  active: 'aktiv',
  disabled: 'deaktiviert',
  permission_required: 'Erlaubnis erforderlich',
};

export const CONFIG_STATUS_TONE: Record<SourceConfigStatus, Tone> = {
  candidate: 'info',
  active: 'good',
  disabled: 'muted',
  permission_required: 'warn',
};

export const HEALTH_LABELS: Record<SourceHealth, string> = {
  ok: 'letzter Lauf vollständig',
  degraded: 'letzter Lauf unvollständig',
  blocked: 'blockiert',
  failing: 'fehlgeschlagen',
  running: 'läuft',
  never_run: 'noch kein Lauf',
  inactive: 'nicht aktiv',
};

export const HEALTH_TONE: Record<SourceHealth, Tone> = {
  ok: 'good',
  degraded: 'warn',
  blocked: 'crit',
  failing: 'crit',
  running: 'info',
  never_run: 'neutral',
  inactive: 'muted',
};

export const RUN_STATUS_LABELS: Record<RunStatus, string> = {
  queued: 'eingereiht',
  running: 'läuft',
  paused: 'pausiert',
  complete: 'vollständig',
  partial: 'unvollständig',
  blocked: 'blockiert',
  failed: 'fehlgeschlagen',
  cancelled: 'abgebrochen',
};

export const RUN_STATUS_TONE: Record<RunStatus, Tone> = {
  queued: 'info',
  running: 'info',
  paused: 'neutral',
  complete: 'good',
  partial: 'warn',
  blocked: 'crit',
  failed: 'crit',
  cancelled: 'muted',
};

export const RUN_TRIGGER_LABELS: Record<string, string> = {
  scheduled: 'geplant',
  catchup: 'nachgeholt',
  manual: 'manuell',
  test: 'Test',
};

export const SCOPE_MODE_LABELS: Record<string, string> = {
  full: 'Vollerfassung des Suchbereichs',
  new_only: 'nur neue Einträge (Fenster)',
};

export const TASK_STATUS_LABELS: Record<string, string> = {
  pending: 'ausstehend',
  running: 'läuft',
  done: 'erledigt',
  partial: 'unvollständig',
  blocked: 'blockiert',
  failed: 'fehlgeschlagen',
};

export const JOB_STATUS_LABELS: Record<string, string> = {
  queued: 'eingereiht',
  running: 'läuft',
  done: 'erledigt',
  failed: 'fehlgeschlagen',
  cancelled: 'abgebrochen',
};

export const JOB_STATUS_TONE: Record<string, Tone> = {
  queued: 'info',
  running: 'info',
  done: 'good',
  failed: 'crit',
  cancelled: 'muted',
};

export const JOB_KIND_LABELS: Record<string, string> = {
  aggregate: 'Tagesaggregate berechnen',
  stats_check: 'Auf neue Statistikveröffentlichungen prüfen',
  maintenance: 'Wartung (Statusfortschreibung, Aufräumen)',
  geo_rematch: 'Ungeklärte Arbeitsorte erneut zuordnen',
  scan: 'Scanlauf',
  run: 'Scanlauf',
};

export const ACCESS_METHOD_LABELS: Record<string, string> = {
  official_rss_feed: 'offizieller RSS-Feed',
  html_list_jsonld: 'HTML-Liste mit JSON-LD',
  sitemap_jsonld: 'Sitemap mit JSON-LD',
  html_embedded_state: 'HTML mit eingebettetem Zustand',
  api: 'öffentliche Schnittstelle',
};

export const GEO_CLASS_SHORT: Record<GeoClass, string> = {
  resolved: 'Kreis zugeordnet',
  partial: 'teilweise ungeklärt',
  unresolved: 'ungeklärt',
  remote_nationwide: 'deutschlandweit remote',
  foreign: 'Ausland',
  none: 'ohne Ortsangabe',
};

export const REMOTE_LABELS: Record<string, string> = {
  remote: 'remote',
  hybrid: 'hybrid',
  onsite: 'vor Ort',
  unknown: 'unbekannt',
};

export const WORKING_TIME_LABELS: Record<string, string> = { vollzeit: 'Vollzeit', teilzeit: 'Teilzeit' };
export const CONTRACT_LABELS: Record<string, string> = { befristet: 'befristet', unbefristet: 'unbefristet' };

export const KIND_GROUP_LABELS: Record<string, string> = {
  jobs: 'Stellen',
  ausbildung: 'Ausbildung & duales Studium',
  praktikum: 'Praktika',
  all: 'Alle',
};

export const KIND_LABELS: Record<string, string> = {
  job: 'Stelle',
  ausbildung: 'Ausbildung',
  duales_studium: 'Duales Studium',
  praktikum: 'Praktikum',
  trainee: 'Trainee/Volontariat',
  werkstudent: 'Werkstudent/stud. Hilfskraft',
  minijob: 'Minijob',
  abschlussarbeit: 'Abschlussarbeit',
};

export const SORT_LABELS: Record<string, string> = {
  relevance: 'Relevanz',
  first_seen: 'erstmals beobachtet (neueste zuerst)',
  date_posted: 'veröffentlicht laut Quelle (neueste zuerst)',
  title: 'Titel (A–Z)',
  employer: 'Arbeitgeber (A–Z)',
  apply_until: 'Bewerbungsfrist (früheste zuerst)',
  last_seen: 'zuletzt beobachtet (neueste zuerst)',
};

export const FEATURE_TYPE_LABELS: Record<string, string> = {
  qual: 'Formaler Abschluss',
  exp: 'Erfahrung',
  skill: 'Fachliche Kenntnisse',
  cert: 'Zertifikat',
  lang: 'Sprache',
  license: 'Berechtigung',
};

export const POLARITY_LABELS: Record<Polarity, string> = {
  required: 'verlangt',
  desired: 'erwünscht',
  negated: 'verneint',
  unclear: 'unklar',
};

export const POLARITY_TONE: Record<Polarity, Tone> = {
  required: 'info',
  desired: 'good',
  negated: 'serious',
  unclear: 'muted',
};

export const POLARITY_HELP: Record<Polarity, string> = {
  required: 'In der Anzeige ausdrücklich als Voraussetzung formuliert.',
  desired: 'Als wünschenswert oder von Vorteil formuliert.',
  negated: 'Ausdrücklich nicht erforderlich.',
  unclear: 'Das Merkmal wird genannt, die Regel konnte aber nicht entscheiden, ob es verlangt ist.',
};

export const FEATURE_ORIGIN_LABELS: Record<string, string> = {
  rule_text: 'Regel auf dem Anzeigentext',
  portal_field: 'strukturiertes Feld des Portals',
  jsonld: 'strukturierte Daten der Anzeige (JSON-LD)',
  kldb: 'abgeleitet aus der Berufsklasse',
};

export const SALARY_ORIGIN_LABELS: Record<string, string> = {
  employer: 'Angabe des Arbeitgebers',
  portal_estimate: 'Schätzung des Portals (keine Arbeitgeberangabe)',
  unknown: 'Herkunft unbekannt',
};

export const KLDB_SOURCE_LABELS: Record<string, string> = {
  portal_field: 'Berufsangabe des Portals',
  title_exact: 'Titel entspricht einer Berufsbenennung',
  title_fuzzy: 'Titel ähnelt einer Berufsbenennung (unscharf)',
};

export const MATCH_METHOD_LABELS: Record<string, string> = {
  source_coordinates: 'Koordinaten aus der Quelle',
  country_field: 'Länderangabe der Quelle',
  nationwide_term: 'Angabe „bundesweit“ bzw. deutschlandweit',
  place_name: 'Ortsname',
  'place_name+plz': 'Ortsname und Postleitzahl',
  'place_name+plz_prefix': 'Ortsname und Postleitzahlbereich',
  place_name_dominant: 'Ortsname mehrdeutig – einwohnerstärkste Gemeinde gewählt',
  plz_unique: 'Postleitzahl (eindeutig einem Kreis zugeordnet)',
  state_name: 'nur das Bundesland ist erkennbar',
  ambiguous_name: 'Ortsname mehrdeutig – nicht zugeordnet',
  ambiguous_plz: 'Postleitzahl mehrdeutig – nicht zugeordnet',
  unknown_place: 'Ort nicht in der lokalen Ortsreferenz',
  unresolved: 'nicht zugeordnet',
};

export const PRECISION_LABELS: Record<string, string> = {
  coordinates: 'punktgenau (Angabe der Quelle)',
  municipality: 'Gemeinde',
  district: 'Kreis',
  state: 'Bundesland',
  country: 'bundesweit',
  foreign: 'Ausland',
  unresolved: 'ungeklärt',
};

export const POINT_ORIGIN_LABELS: Record<string, string> = {
  source: 'Koordinate aus der Quelle',
  place_centroid: 'angenähert: Mittelpunkt der Gemeinde',
};

export const CHANGE_KIND_LABELS: Record<ChangeKind, string> = {
  initial: 'Erstfassung',
  enrichment: 'Anreicherung durch die Detailseite',
  content: 'Inhaltsänderung der Anzeige',
  parser: 'Parser- oder Regelwechsel',
  mixed: 'Inhaltsänderung und Regelwechsel',
};

export const CHANGE_KIND_TONE: Record<ChangeKind, Tone> = {
  initial: 'neutral',
  enrichment: 'info',
  content: 'warn',
  parser: 'muted',
  mixed: 'warn',
};

export const CHANGE_KIND_HELP: Record<ChangeKind, string> = {
  initial: 'Erste gespeicherte Fassung dieser Quellanzeige.',
  enrichment: 'Die Detailseite hat Angaben ergänzt, die in der Liste fehlten – keine Änderung durch den Arbeitgeber.',
  content: 'Der Inhalt der Anzeige hat sich fachlich geändert.',
  parser: 'Technische Änderung: Die Anzeige selbst blieb gleich, nur die Auswertung (Parser, Regeln) wurde aktualisiert.',
  mixed: 'Der Inhalt hat sich geändert und zugleich wurden Auswertungsregeln aktualisiert.',
};

export const EVENT_LABELS: Record<string, string> = {
  first_seen: 'Erstmals beobachtet',
  additional_source: 'Auf weiterer Quelle beobachtet',
  republication: 'Erneut veröffentlicht',
  reactivation: 'Wieder im Bestand beobachtet',
  content_change: 'Inhalt geändert',
  parser_change: 'Parser- oder Regelwechsel',
  left_stock: 'Aus dem beobachteten Bestand gefallen',
};

export const MERGE_REASON_LABELS: Record<string, string> = {
  singleton: 'Einzelanzeige (keine Zusammenführung)',
  employer_reference: 'gleiche Stellenreferenz desselben Arbeitgebers',
  employer_url: 'identischer Zielverweis zum Arbeitgeber',
  employer_title_location: 'Arbeitgeber, Titel und Arbeitsort stimmen überein',
  manual: 'manuell zusammengeführt',
};

const MERGE_SUFFIX_LABELS: Record<string, string> = {
  disjoint_locations: 'abweichende Arbeitsorte',
  parallel_same_source: 'parallel auf derselben Quelle',
  agency: 'Personalvermittlung',
};

export function mergeReasonLabel(reason: string): string {
  const [base, ...rest] = reason.split('+');
  const label = MERGE_REASON_LABELS[base ?? ''] ?? base ?? reason;
  if (!rest.length) return label;
  return `${label} – unsicher wegen: ${rest.map((r) => MERGE_SUFFIX_LABELS[r] ?? r).join(', ')}`;
}

export const VALUE_STATUS_LABELS: Record<ValueStatus, string> = {
  ok: 'Wert',
  zero: 'echter Nullwert',
  suppressed: 'aus Geheimhaltungsgründen unterdrückt',
  unknown: 'unbekannt',
  not_available: 'nicht verfügbar',
  not_collected: 'nicht erhoben',
};

export const FIELD_LABELS: Record<string, string> = {
  title: 'Titel',
  title_norm: 'Titel',
  employer_name: 'Arbeitgeber',
  employer_norm: 'Arbeitgeber',
  reference: 'Stellenreferenz',
  employer_url: 'Zielverweis zum Arbeitgeber',
  kind: 'Art der Anzeige',
  working_time: 'Arbeitszeit',
  contract_term: 'Befristung',
  remote_type: 'Remote-Status',
  salary_min: 'Vergütung (von)',
  salary_max: 'Vergütung (bis)',
  salary_text: 'Vergütungsangabe',
  apply_until: 'Bewerbungsfrist',
  valid_through: 'angekündigtes Veröffentlichungsende',
  feature_keys: 'Merkmale',
  feature_required_keys: 'verlangte Merkmale',
  feature_polarity: 'Einordnung der Merkmale',
  kreis_keys: 'zugeordnete Kreise',
  occupation_label: 'Berufsangabe',
  locations: 'Arbeitsorte',
  kldb_code: 'Berufsklasse (KldB)',
  date_posted: 'veröffentlicht laut Quelle',
};

export const TIMELINE_KIND_LABELS: Record<string, string> = {
  source_added: 'Quelle hinzugekommen',
  source_removed: 'Quelle entfallen',
  scope_changed: 'Suchbereich geändert',
  parser_changed: 'Parser geändert',
  rules_changed: 'Regeln geändert',
  gap: 'Datenlücke',
};

export const RUN_QUALITY_LABELS: Record<string, string> = {
  complete: 'alle Läufe vollständig',
  partial: 'mindestens ein unvollständiger Lauf',
  none: 'kein Lauf (Datenlücke)',
};

export const UPDATE_CYCLE_LABELS: Record<string, string> = { monthly: 'monatlich', yearly: 'jährlich', irregular: 'unregelmäßig' };

export const COUNT_LABELS: Record<string, string> = {
  source_postings: 'Quellanzeigen',
  merged_postings: 'zusammengeführte Anzeigen',
  versions: 'Inhaltsversionen',
  observations: 'Beobachtungen',
  districts: 'Kreise (aktueller Gebietsstand)',
  places: 'Einträge der Ortsreferenz',
  kldb_classes: 'KldB-Klassen',
  occupation_titles: 'Berufsbenennungen',
  synthetic_postings: 'synthetische Anzeigen (ausgeblendet)',
};

export const SETTING_LABELS: Record<string, string> = {
  missing_scans_threshold: 'vollständige Scans bis „vermutlich entfernt“',
  stale_after_days: 'Tage ohne vergleichbaren Scan bis „unbekannt/veraltet“',
  detail_recheck_days: 'Tage bis zur erneuten Detailprüfung',
  technical_log_retention_days: 'Aufbewahrung technischer Protokolle (Tage)',
  small_count_threshold: 'Schwelle „geringe Fallzahl“',
};

/** Exakte Bezeichnungen der Kartenkennzahlen – überall gleich verwendet. */
export const METRIC_LABELS = {
  weighted: 'anteilig gezählte Anzeigen',
  distinct: 'unterschiedliche Anzeigen mit Bezug zum Kreis',
  rate: 'anteilige Anzeigen je 1.000 Einwohner (15 bis unter 65 Jahre)',
} as const;
