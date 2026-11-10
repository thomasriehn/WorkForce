/** Zahlen- und Datumsformate nach deutscher Schreibweise. Fehlende Werte bleiben sichtbar („–“ bzw. „unbekannt“). */

export const DASH = '–';
const TZ = 'Europe/Berlin';

const intFmt = new Intl.NumberFormat('de-DE', { maximumFractionDigits: 0 });
const dateTimeFmt = new Intl.DateTimeFormat('de-DE', {
  day: '2-digit',
  month: '2-digit',
  year: 'numeric',
  hour: '2-digit',
  minute: '2-digit',
  timeZone: TZ,
});
const dateFromInstantFmt = new Intl.DateTimeFormat('de-DE', { day: '2-digit', month: '2-digit', year: 'numeric', timeZone: TZ });
const shortDayFmt = new Intl.DateTimeFormat('de-DE', { day: '2-digit', month: '2-digit', timeZone: 'UTC' });

export function fmtInt(value: number | null | undefined): string {
  if (value === null || value === undefined || Number.isNaN(value)) return DASH;
  return intFmt.format(value);
}

/** Dezimalzahl mit höchstens `max` Nachkommastellen (anteilige Zählungen sind keine ganzen Zahlen). */
export function fmtNum(value: number | null | undefined, max = 2, min = 0): string {
  if (value === null || value === undefined || Number.isNaN(value)) return DASH;
  return new Intl.NumberFormat('de-DE', { maximumFractionDigits: max, minimumFractionDigits: min }).format(value);
}

export function fmtSigned(value: number | null | undefined, max = 2): string {
  if (value === null || value === undefined || Number.isNaN(value)) return DASH;
  const body = fmtNum(Math.abs(value), max);
  if (value > 0) return `+${body}`;
  if (value < 0) return `−${body}`;
  return `±${body}`;
}

export function fmtPct(value: number | null | undefined, max = 1): string {
  if (value === null || value === undefined || Number.isNaN(value)) return DASH;
  return `${fmtSigned(value, max)} %`;
}

const ISO_DATE = /^(\d{4})-(\d{2})-(\d{2})$/;

/** Kalenderdatum (ohne Zeitzonenverschiebung) oder Zeitstempel → TT.MM.JJJJ. */
export function fmtDate(value: string | null | undefined): string {
  if (!value) return DASH;
  const m = ISO_DATE.exec(value);
  if (m) return `${m[3]}.${m[2]}.${m[1]}`;
  const d = new Date(value);
  return Number.isNaN(d.getTime()) ? value : dateFromInstantFmt.format(d);
}

export function fmtDateTime(value: string | null | undefined): string {
  if (!value) return DASH;
  const d = new Date(value);
  return Number.isNaN(d.getTime()) ? value : `${dateTimeFmt.format(d)} Uhr`;
}

/** Kurzform für Diagrammachsen: TT.MM. */
export function fmtDayShort(isoDate: string): string {
  const d = new Date(`${isoDate}T00:00:00Z`);
  return Number.isNaN(d.getTime()) ? isoDate : shortDayFmt.format(d);
}

export function fmtAgeDays(days: number | null | undefined): string {
  if (days === null || days === undefined) return DASH;
  if (days < 0) return 'Berichtszeitraum läuft noch';
  if (days === 0) return 'heute';
  if (days === 1) return '1 Tag';
  if (days < 90) return `${fmtInt(days)} Tage`;
  const months = Math.round(days / 30.44);
  if (months < 24) return `${fmtInt(days)} Tage (rund ${months} Monate)`;
  return `${fmtInt(days)} Tage (rund ${fmtNum(days / 365.25, 1)} Jahre)`;
}

export function daysBetween(fromIso: string, toIso: string): number | null {
  const a = Date.parse(`${fromIso.slice(0, 10)}T00:00:00Z`);
  const b = Date.parse(`${toIso.slice(0, 10)}T00:00:00Z`);
  if (Number.isNaN(a) || Number.isNaN(b)) return null;
  return Math.round((b - a) / 86_400_000);
}

export function todayIso(): string {
  const parts = new Intl.DateTimeFormat('en-CA', { timeZone: TZ, year: 'numeric', month: '2-digit', day: '2-digit' }).format(new Date());
  return parts;
}

export function addDaysIso(isoDate: string, days: number): string {
  const d = new Date(`${isoDate}T00:00:00Z`);
  d.setUTCDate(d.getUTCDate() + days);
  return d.toISOString().slice(0, 10);
}

export function plural(count: number, one: string, many: string): string {
  return `${fmtInt(count)} ${count === 1 ? one : many}`;
}

const PERIOD_LABELS: Record<string, string> = { HOUR: 'Stunde', DAY: 'Tag', WEEK: 'Woche', MONTH: 'Monat', YEAR: 'Jahr' };

export function fmtSalary(min: number | null, max: number | null, currency: string | null, period: string | null): string | null {
  if (min === null && max === null) return null;
  const unit = currency === 'EUR' || !currency ? '€' : currency;
  const per = period ? ` je ${PERIOD_LABELS[period] ?? period}` : '';
  if (min !== null && max !== null && min !== max) return `${fmtNum(min, 2)} – ${fmtNum(max, 2)} ${unit}${per}`;
  return `${fmtNum((min ?? max) as number, 2)} ${unit}${per}`;
}
