/**
 * Farben und Klassenbildung für Diagramme und Karte.
 *
 * Farbrollen: kategorial (wer?) – Blau/Orange/Aqua in fester Reihenfolge; sequenziell (wie viel?) – ein Farbton
 * hell→dunkel; divergierend (welche Richtung?) – Blau ↔ Rot mit neutral-grauer Mitte. „Keine Daten“ ist nie eine
 * Farbe der Skala, sondern eine Schraffur.
 */

export const VIZ = {
  stock: '#2a78d6',
  left: '#eb6834',
  firstSeen: '#1baf7a',
  baseline: '#898781',
  grid: '#e6e8ec',
  axis: '#c5ccd8',
  tick: '#5b6676',
  surface: '#ffffff',
} as const;

/** Sequenziell (Anzeigenkennzahlen): Blau, fünf Klassen. */
export const SEQ_BLUE = ['#cde2fb', '#86b6ef', '#3987e5', '#1c5cab', '#0d366b'];
/** Sequenziell (amtliche Kontextstatistik): eigener Farbton, damit Kontext nie wie eine Anzeigenkennzahl aussieht. */
export const SEQ_TEAL = ['#cfeee3', '#8fd6bd', '#3fb08a', '#157a59', '#07513a'];
/** Echter Nullwert: eigene, sehr helle Klasse (deutlich anders als die Schraffur für „keine Daten“). */
export const ZERO_FILL = '#f1f3f6';
/** Divergierend, sieben Klassen: Rückgang (Blau) – unverändert (Grau) – Zunahme (Rot). */
export const DIVERGING = ['#184f95', '#3987e5', '#9ec5f4', '#eceae6', '#f2b3ad', '#e0605a', '#a12a25'];
/** Feste Klassengrenzen der prozentualen Veränderung – identisch für 7, 30 und 90 Tage. */
export const CHANGE_BREAKS = [-50, -20, -5, 5, 20, 50];

export const MAP_STROKE = '#ffffff';
export const MAP_STROKE_MUTED = '#b9c0cb';
export const MAP_SELECTED = '#17202c';
export const NODATA_PATTERN_ID = 'wf-pattern-nodata';
export const NEWBASE_PATTERN_ID = 'wf-pattern-newbase';

export type ClassMethod = 'quantile' | 'equal';

export interface Classification {
  /** Obere Klassengrenzen (einschließlich); die letzte ist das Maximum. */
  upper: number[];
  min: number;
  max: number;
  /** Klassenindex für einen positiven Wert. */
  classOf: (value: number) => number;
}

/**
 * Bildet bis zu `k` Klassen über die positiven Werte. Nullwerte gehören nicht dazu (eigene Klasse),
 * fehlende Werte ebenfalls nicht (Schraffur).
 */
export function classify(values: number[], method: ClassMethod, k = 5): Classification | null {
  const sorted = values.filter((v) => Number.isFinite(v) && v > 0).sort((a, b) => a - b);
  if (!sorted.length) return null;
  const min = sorted[0] as number;
  const max = sorted[sorted.length - 1] as number;
  let upper: number[] = [];
  if (min === max) {
    upper = [max];
  } else if (method === 'equal') {
    const step = (max - min) / k;
    for (let i = 1; i <= k; i += 1) upper.push(i === k ? max : min + step * i);
  } else {
    for (let i = 1; i <= k; i += 1) {
      const pos = Math.min(sorted.length - 1, Math.ceil((i / k) * sorted.length) - 1);
      upper.push(sorted[Math.max(0, pos)] as number);
    }
    upper = upper.filter((v, i) => i === 0 || v > (upper[i - 1] as number));
    if (upper[upper.length - 1] !== max) upper.push(max);
  }
  const classOf = (value: number) => {
    for (let i = 0; i < upper.length; i += 1) {
      if (value <= (upper[i] as number)) return i;
    }
    return upper.length - 1;
  };
  return { upper, min, max, classOf };
}

/** Wählt aus einer fünfstufigen Rampe gleichmäßig verteilte Stufen, wenn weniger Klassen entstehen. */
export function rampFor(ramp: string[], classes: number): string[] {
  if (classes >= ramp.length) return ramp;
  if (classes === 1) return [ramp[2] as string];
  const out: string[] = [];
  for (let i = 0; i < classes; i += 1) {
    out.push(ramp[Math.round((i * (ramp.length - 1)) / (classes - 1))] as string);
  }
  return out;
}

export function changeClass(pct: number): number {
  for (let i = 0; i < CHANGE_BREAKS.length; i += 1) {
    if (pct < (CHANGE_BREAKS[i] as number)) return i;
  }
  return CHANGE_BREAKS.length;
}

/** Legendentexte der festen Veränderungsklassen. */
export const CHANGE_CLASS_LABELS = [
  'Rückgang um mehr als 50 %',
  'Rückgang über 20 % bis 50 %',
  'Rückgang über 5 % bis 20 %',
  'nahezu unverändert (−5 % bis unter +5 %)',
  'Zunahme 5 % bis unter 20 %',
  'Zunahme 20 % bis unter 50 %',
  'Zunahme um 50 % und mehr',
];
