/**
 * Aufbereitung der Kartenansichten: aus den API-Antworten wird je Kreis Farbe/Schraffur, Tooltip-Inhalt und
 * Tabellenwert abgeleitet. Grundregeln:
 *  – „keine Daten“ (fehlender Nenner, unterdrückter/unbekannter Statistikwert, keine vergleichbare Grundlage)
 *    ist eine Schraffur und nie die unterste Farbklasse;
 *  – ein echter Nullwert hat eine eigene, sehr helle Klasse;
 *  – geringe Fallzahlen werden markiert;
 *  – Anzeigenkennzahlen und amtliche Kontextstatistik werden nie in einer Ansicht vermischt.
 */
import type { KreisProperties, MapChange, MapMetrics, StatsMap, ValueStatus } from '../api/types';
import { daysBetween, fmtAgeDays, fmtDate, fmtInt, fmtNum, fmtPct, fmtSigned } from '../lib/format';
import { METRIC_LABELS, VALUE_STATUS_LABELS } from '../lib/labels';
import { CHANGE_BREAKS, CHANGE_CLASS_LABELS, changeClass, type ClassMethod, classify, DIVERGING, rampFor, SEQ_BLUE, SEQ_TEAL, ZERO_FILL } from '../lib/viz';
import type { RegionStyle } from './ChoroplethMap';

export type MapView = 'weighted' | 'distinct' | 'rate' | 'change' | 'context';

export interface TipLine {
  label: string;
  value: string;
  strong?: boolean;
}

export interface RegionInfo extends RegionStyle {
  /** Hauptwert als Text, z. B. „3,5“ oder „keine Daten“. */
  valueText: string;
  /** Sortierwert für die Tabellenansicht (null = keine Daten). */
  sortValue: number | null;
  lines: TipLine[];
  hints: string[];
}

export interface LegendEntry {
  fill: string;
  pattern?: 'nodata' | 'newbase';
  label: string;
  count: number;
}

export interface MapModel {
  view: MapView;
  /** Exakte Bezeichnung der dargestellten Größe. */
  metricLabel: string;
  unit?: string;
  info: (key: string) => RegionInfo;
  legend: LegendEntry[];
  /** Erläuterung zur Klassenbildung unter der Legende. */
  legendNote: string;
  /** Zeilen, die in jedem Tooltip gleich sind (Stichtag, Abdeckung, Datenstand). */
  commonLines: TipLine[];
  showLowCount: boolean;
  lowCountLabel: string;
  noDataReasons: string[];
}

const NO_DATA: Pick<RegionInfo, 'fill' | 'pattern'> = { fill: '#ffffff', pattern: 'nodata' };

function rangeLabel(index: number, upper: number[], min: number, integer: boolean, digits: number): string {
  const hi = upper[index] as number;
  if (index === 0) {
    return min === hi ? fmtNum(hi, digits) : `${fmtNum(min, digits)} bis ${fmtNum(hi, digits)}`;
  }
  const prev = upper[index - 1] as number;
  if (integer) {
    const lo = prev + 1;
    return lo >= hi ? fmtNum(hi, 0) : `${fmtNum(lo, 0)} bis ${fmtNum(hi, 0)}`;
  }
  return `über ${fmtNum(prev, digits)} bis ${fmtNum(hi, digits)}`;
}

function coverageLine(metrics: MapMetrics): TipLine {
  const n = metrics.coverage.sources.length;
  const names = metrics.coverage.sources.slice(0, 3).map((s) => s.name);
  const more = n > names.length ? ` und ${n - names.length} weitere` : '';
  return {
    label: 'Abdeckung',
    value: n === 0 ? 'keine freigegebene Quelle' : `${n} ${n === 1 ? 'Quelle' : 'Quellen'} (${names.join(', ')}${more}) – keine Vollerhebung`,
  };
}

function assignmentHint(metrics: MapMetrics): string | null {
  const g = metrics.totals.geo;
  const parts: string[] = [];
  if (g.partial > 0) parts.push(`${fmtInt(g.partial)} teilweise ungeklärt`);
  if (g.unresolved > 0) parts.push(`${fmtInt(g.unresolved)} ungeklärt`);
  if (g.remote_nationwide > 0) parts.push(`${fmtInt(g.remote_nationwide)} deutschlandweit remote`);
  if (!parts.length) return null;
  return `Keinem Kreis anteilig zugerechnet: ${parts.join(', ')} (siehe Summenfeld).`;
}

// ---------------------------------------------------------------------------------------------
// Anzeigenkennzahlen
// ---------------------------------------------------------------------------------------------
interface AdOptions {
  view: 'weighted' | 'distinct' | 'rate';
  metrics: MapMetrics;
  keys: string[];
  method: ClassMethod;
  /** Bevölkerungswerte aller Kreise (für Kreise ohne Anzeigen: gibt es einen Nenner?). */
  population: Map<string, number> | null;
}

export function buildAdModel({ view, metrics, keys, method, population }: AdOptions): MapModel {
  const byKey = new Map(metrics.regions.map((r) => [r.key, r]));
  const rel = metrics.population_release;
  const digits = view === 'distinct' ? 0 : view === 'rate' ? 3 : 2;

  const valueOf = (key: string): number | null => {
    const r = byKey.get(key);
    if (view === 'weighted') return r ? r.weighted : 0;
    if (view === 'distinct') return r ? r.distinct : 0;
    if (r) return r.rate_per_1000; // null = kein Nenner
    if (!rel) return null;
    const pop = population?.get(key);
    return pop && pop > 0 ? 0 : null;
  };

  const values = keys.map(valueOf);
  const cls = classify(values.filter((v): v is number => v !== null), method);
  const ramp = cls ? rampFor(SEQ_BLUE, cls.upper.length) : [];
  const counts = new Array<number>(cls?.upper.length ?? 0).fill(0);
  let zeros = 0;
  let missing = 0;
  for (const v of values) {
    if (v === null) missing += 1;
    else if (v <= 0) zeros += 1;
    else if (cls) counts[cls.classOf(v)] = (counts[cls.classOf(v)] ?? 0) + 1;
  }

  const legend: LegendEntry[] = [];
  legend.push({ fill: ZERO_FILL, label: view === 'rate' ? '0 – keine anteilig gezählte Anzeige' : '0 – keine Anzeige in dieser Auswahl', count: zeros });
  if (cls) {
    cls.upper.forEach((_, i) => legend.push({ fill: ramp[i] as string, label: rangeLabel(i, cls.upper, cls.min, view === 'distinct', digits), count: counts[i] ?? 0 }));
  }
  legend.push({ fill: '#ffffff', pattern: 'nodata', label: view === 'rate' ? 'keine Daten – Bevölkerungswert (Nenner) fehlt' : 'keine Daten', count: missing });

  const noDataReason = !rel
    ? 'Bevölkerung 15 bis unter 65 Jahre ist nicht importiert – die Quote kann nicht berechnet werden.'
    : 'Für diesen Kreis liegt kein Bevölkerungswert (Nenner) vor – es wird kein Quotient gebildet.';
  const commonHint = assignmentHint(metrics);

  const info = (key: string): RegionInfo => {
    const r = byKey.get(key);
    const v = valueOf(key);
    const lines: TipLine[] = [
      { label: METRIC_LABELS.weighted, value: fmtNum(r?.weighted ?? 0, 2), strong: view === 'weighted' },
      { label: METRIC_LABELS.distinct, value: fmtInt(r?.distinct ?? 0), strong: view === 'distinct' },
    ];
    if (view === 'rate') {
      lines.push({ label: METRIC_LABELS.rate, value: v === null ? 'keine Daten' : fmtNum(v, 3), strong: true });
      const pop = r?.population_15_65 ?? population?.get(key) ?? null;
      lines.push({ label: 'Bevölkerung 15 bis unter 65 Jahre', value: pop ? fmtInt(pop) : 'kein Wert vorhanden' });
    }
    const hints: string[] = [];
    if (r?.low_count) hints.push(`Geringe Fallzahl (weniger als ${metrics.small_count_threshold} Anzeigen) – einzelne Anzeigen verändern den Wert stark.`);
    if (r && r.distinct > 0 && Math.abs(r.weighted - r.distinct) > 1e-9) {
      hints.push('Anzeigen mit mehreren Arbeitsorten zählen je Kreis nur anteilig; teilweise ungeklärte Anzeigen zählen nur bei den unterschiedlichen Anzeigen.');
    }
    if (view === 'rate' && v === null) hints.push(noDataReason);
    if (commonHint) hints.push(commonHint);
    const base = v === null ? NO_DATA : v <= 0 ? { fill: ZERO_FILL, pattern: null } : { fill: ramp[cls ? cls.classOf(v) : 0] ?? ZERO_FILL, pattern: null };
    return {
      ...base,
      lowCount: Boolean(r?.low_count),
      valueText: v === null ? 'keine Daten' : fmtNum(v, digits),
      sortValue: v,
      lines,
      hints,
    };
  };

  const commonLines: TipLine[] = [{ label: 'Stichtag der Anzeigen', value: fmtDate(metrics.reference_date) }, coverageLine(metrics)];
  if (view === 'rate' && rel) {
    const age = daysBetween(rel.period_end, metrics.reference_date);
    commonLines.push({
      label: 'Bevölkerungsstand',
      value: `${rel.name}, Berichtszeitraum ${rel.period_key} (Stand ${fmtDate(rel.period_end)}), Revision ${rel.revision}, Alter ${fmtAgeDays(age)}`,
    });
  }

  return {
    view,
    metricLabel: METRIC_LABELS[view],
    info,
    legend,
    legendNote: cls
      ? `${method === 'quantile' ? 'Quantile' : 'Gleiche Intervalle'} über die Kreise mit einem Wert über null; die Grenzen werden für die aktuelle Auswahl neu berechnet.`
      : 'In dieser Auswahl hat kein Kreis einen Wert über null.',
    commonLines,
    showLowCount: true,
    lowCountLabel: `geringe Fallzahl: weniger als ${metrics.small_count_threshold} Anzeigen`,
    noDataReasons: view === 'rate' && missing > 0 ? [noDataReason] : [],
  };
}

// ---------------------------------------------------------------------------------------------
// Veränderung über 7 / 30 / 90 Tage
// ---------------------------------------------------------------------------------------------
interface ChangeOptions {
  change: MapChange;
  metrics: MapMetrics | undefined;
  keys: string[];
}

export function buildChangeModel({ change, metrics, keys }: ChangeOptions): MapModel {
  const byKey = new Map(change.regions.map((r) => [r.key, r]));
  const comparable = change.basis.comparable;
  const baseLabel = change.metric === 'distinct' ? METRIC_LABELS.distinct : METRIC_LABELS.weighted;
  const digits = change.metric === 'distinct' ? 0 : 2;
  const counts = new Array<number>(DIVERGING.length).fill(0);
  let bothZero = 0;
  let newBase = 0;
  let missing = 0;
  for (const key of keys) {
    const r = byKey.get(key);
    if (!comparable) missing += 1;
    else if (!r) bothZero += 1;
    else if (r.pct !== null) counts[changeClass(r.pct)] = (counts[changeClass(r.pct)] ?? 0) + 1;
    else if (r.abs !== 0) newBase += 1;
    else bothZero += 1;
  }
  const noComparison = change.message ?? 'Kein Vergleich möglich: Für die beiden Stichtage liegt keine vergleichbare Abdeckung vor.';

  const info = (key: string): RegionInfo => {
    if (!comparable) {
      return { ...NO_DATA, lowCount: false, valueText: 'keine Daten', sortValue: null, lines: [], hints: [noComparison] };
    }
    const r = byKey.get(key);
    if (!r) {
      return {
        fill: ZERO_FILL,
        pattern: null,
        lowCount: false,
        valueText: '±0',
        sortValue: 0,
        lines: [{ label: `Veränderung (${baseLabel})`, value: '±0 – an beiden Stichtagen keine Anzeige', strong: true }],
        hints: [],
      };
    }
    const lines: TipLine[] = [];
    const hints: string[] = [];
    if (r.pct !== null) {
      lines.push({ label: `Veränderung in ${change.days} Tagen`, value: `${fmtPct(r.pct)} (absolut ${fmtSigned(r.abs, digits)})`, strong: true });
    } else {
      lines.push({ label: `Veränderung in ${change.days} Tagen (absolut)`, value: fmtSigned(r.abs, digits), strong: true });
      if (r.pct_note) hints.push(r.pct_note);
    }
    lines.push({ label: `${baseLabel} am ${fmtDate(change.basis.date_then)}`, value: fmtNum(r.then, digits) });
    lines.push({ label: `${baseLabel} am ${fmtDate(change.basis.date_now)}`, value: fmtNum(r.now, digits) });
    if (r.low_count) hints.push('Geringe Fallzahl – prozentuale Veränderungen sind hier wenig belastbar.');
    const style: Pick<RegionInfo, 'fill' | 'pattern'> =
      r.pct !== null ? { fill: DIVERGING[changeClass(r.pct)] as string, pattern: null } : r.abs !== 0 ? { fill: '#fbe3e0', pattern: 'newbase' } : { fill: ZERO_FILL, pattern: null };
    return {
      ...style,
      lowCount: r.low_count,
      valueText: r.pct !== null ? fmtPct(r.pct) : `${fmtSigned(r.abs, digits)} (absolut)`,
      sortValue: r.pct ?? (r.abs !== 0 ? Number.POSITIVE_INFINITY : 0),
      lines,
      hints,
    };
  };

  const legend: LegendEntry[] = DIVERGING.map((fill, i) => ({ fill, label: CHANGE_CLASS_LABELS[i] as string, count: counts[i] ?? 0 }));
  legend.push({ fill: '#fbe3e0', pattern: 'newbase', label: 'Ausgangswert 0 – nur absolute Veränderung', count: newBase });
  legend.push({ fill: ZERO_FILL, label: 'an beiden Stichtagen keine Anzeige', count: bothZero });
  legend.push({ fill: '#ffffff', pattern: 'nodata', label: 'keine Daten – keine vergleichbare Grundlage', count: missing });

  const commonLines: TipLine[] = [
    { label: 'Stichtage', value: `${fmtDate(change.basis.date_then)} und ${fmtDate(change.basis.date_now)}` },
    {
      label: 'Vergleichsgrundlage',
      value: comparable
        ? `${change.basis.comparable_sources.length} vergleichbare ${change.basis.comparable_sources.length === 1 ? 'Quelle' : 'Quellen'}, ${change.basis.excluded.length} ausgeschlossen`
        : 'keine vergleichbare Abdeckung',
    },
  ];
  if (metrics) commonLines.push(coverageLine(metrics));

  return {
    view: 'change',
    metricLabel: `Veränderung in ${change.days} Tagen (${baseLabel})`,
    info,
    legend,
    legendNote: `Feste Klassengrenzen (${CHANGE_BREAKS.map((b) => `${b > 0 ? '+' : b < 0 ? '−' : ''}${Math.abs(b)} %`).join(' / ')}) – identisch für 7, 30 und 90 Tage, damit ein Wechsel des Zeitraums die Skala nicht stillschweigend verschiebt.`,
    commonLines,
    showLowCount: true,
    lowCountLabel: `geringe Fallzahl: an beiden Stichtagen weniger als ${metrics?.small_count_threshold ?? 5} Anzeigen`,
    noDataReasons: comparable ? [] : [noComparison],
  };
}

// ---------------------------------------------------------------------------------------------
// Amtliche Kontextstatistik
// ---------------------------------------------------------------------------------------------
interface ContextOptions {
  stats: StatsMap;
  keys: string[];
  method: ClassMethod;
}

export function buildContextModel({ stats, keys, method }: ContextOptions): MapModel {
  const byKey = new Map(stats.values.map((v) => [v.key, v]));
  const labels: Record<string, string> = { ...VALUE_STATUS_LABELS, ...(stats.status_labels ?? {}) };
  const unit = stats.indicator.unit;
  const isUsable = (status: ValueStatus, value: number | null): value is number => value !== null && (status === 'ok' || status === 'zero');
  const numbers: number[] = [];
  for (const key of keys) {
    const v = byKey.get(key);
    if (v && isUsable(v.status, v.value)) numbers.push(v.value);
  }
  const hasNegative = numbers.some((n) => n < 0);
  // Bei Kennzahlen mit negativen Werten (z. B. Salden) gibt es keine eigene Nullklasse.
  const shift = hasNegative ? Math.abs(Math.min(...numbers)) + 1 : 0;
  const cls = classify(
    numbers.map((n) => n + shift),
    method,
  );
  const ramp = cls ? rampFor(SEQ_TEAL, cls.upper.length) : [];
  const fractional = numbers.some((n) => !Number.isInteger(n));
  const digits = fractional ? 2 : 0;
  const counts = new Array<number>(cls?.upper.length ?? 0).fill(0);
  let zeros = 0;
  let missing = 0;
  const reasons = new Map<string, number>();
  for (const key of keys) {
    const v = byKey.get(key);
    if (v && isUsable(v.status, v.value)) {
      if (!hasNegative && v.value === 0) zeros += 1;
      else if (cls) counts[cls.classOf(v.value + shift)] = (counts[cls.classOf(v.value + shift)] ?? 0) + 1;
    } else {
      missing += 1;
      const reason = v ? (labels[v.status] ?? v.status) : 'kein Wert geliefert';
      reasons.set(reason, (reasons.get(reason) ?? 0) + 1);
    }
  }

  const legend: LegendEntry[] = [];
  if (!hasNegative) legend.push({ fill: ZERO_FILL, label: `0 – ${labels.zero ?? 'echter Nullwert'}`, count: zeros });
  if (cls) {
    cls.upper.forEach((_, i) =>
      legend.push({
        fill: ramp[i] as string,
        label: rangeLabel(
          i,
          cls.upper.map((u) => u - shift),
          cls.min - shift,
          !fractional,
          digits,
        ),
        count: counts[i] ?? 0,
      }),
    );
  }
  legend.push({ fill: '#ffffff', pattern: 'nodata', label: 'keine Daten – unterdrückt, unbekannt oder nicht geliefert', count: missing });

  const rel = stats.release;
  const info = (key: string): RegionInfo => {
    const v = byKey.get(key);
    if (v && isUsable(v.status, v.value)) {
      const zero = !hasNegative && v.value === 0;
      return {
        fill: zero ? ZERO_FILL : ((cls ? ramp[cls.classOf(v.value + shift)] : undefined) ?? ZERO_FILL),
        pattern: null,
        lowCount: false,
        valueText: `${fmtNum(v.value, digits)} ${unit}`.trim(),
        sortValue: v.value,
        lines: [{ label: stats.indicator.name, value: `${fmtNum(v.value, digits)} ${unit}`.trim(), strong: true }],
        hints: zero ? ['Echter Nullwert laut Statistik – kein Fehlwert.'] : [],
      };
    }
    const reason = v ? (labels[v.status] ?? v.status) : 'kein Wert geliefert';
    return {
      ...NO_DATA,
      lowCount: false,
      valueText: `keine Daten (${reason})`,
      sortValue: null,
      lines: [{ label: stats.indicator.name, value: `keine Daten – ${reason}`, strong: true }],
      hints: ['Fehlwerte bleiben Fehlwerte: Sie werden weder als 0 dargestellt noch geschätzt.'],
    };
  };

  const commonLines: TipLine[] = [];
  if (rel) {
    commonLines.push({ label: 'Berichtszeitraum', value: `${rel.period_key} (Stand ${fmtDate(rel.period_end)})` });
    commonLines.push({ label: 'Revision', value: `${rel.revision}${rel.is_current ? ' (aktuell)' : ' (ältere Fassung)'}` });
    commonLines.push({ label: 'Alter des Datenstands', value: fmtAgeDays(rel.age_days) });
    commonLines.push({ label: 'Quelle', value: rel.attribution ?? `${rel.publisher}, ${rel.dataset_name}` });
  }

  return {
    view: 'context',
    metricLabel: stats.indicator.name,
    unit,
    info,
    legend,
    legendNote: cls
      ? `${method === 'quantile' ? 'Quantile' : 'Gleiche Intervalle'} über die Kreise mit vorhandenem Wert.`
      : 'Für diese Kennzahl liegt in keinem Kreis ein Wert vor.',
    commonLines,
    showLowCount: false,
    lowCountLabel: '',
    noDataReasons: [...reasons.entries()].map(([reason, n]) => `${fmtInt(n)} × ${reason}`),
  };
}

/** Baut den Tooltip als DOM-Knoten. Alle Texte werden über textContent gesetzt. */
export function buildTooltip(props: KreisProperties, model: MapModel, info: RegionInfo): HTMLElement {
  const root = document.createElement('div');
  root.className = 'map-tip__body';
  const el = (tag: string, className: string, text?: string) => {
    const node = document.createElement(tag);
    node.className = className;
    if (text !== undefined) node.textContent = text;
    return node;
  };
  root.append(el('p', 'map-tip__name', props.name));
  root.append(el('p', 'map-tip__sub', [props.type, props.state, `Kreisschlüssel ${props.key}`].filter(Boolean).join(' · ')));
  const list = el('dl', 'map-tip__list');
  for (const line of [...info.lines, ...model.commonLines]) {
    const row = el('div', line.strong ? 'map-tip__row map-tip__row--strong' : 'map-tip__row');
    row.append(el('dt', '', line.label), el('dd', '', line.value));
    list.append(row);
  }
  root.append(list);
  for (const hint of info.hints) root.append(el('p', 'map-tip__hint', hint));
  return root;
}
