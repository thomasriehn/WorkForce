import { Link } from 'react-router';
import type { ComparableBasis, GeoClass, PostingStatus, RunStatus, SourceConfigStatus, SourceHealth, Totals } from '../api/types';
import { GEO_CLASSES } from '../api/types';
import { fmtDate, fmtInt } from '../lib/format';
import {
  CONFIG_STATUS_LABELS,
  CONFIG_STATUS_TONE,
  GEO_CLASS_SHORT,
  HEALTH_LABELS,
  HEALTH_TONE,
  POSTING_STATUS_HELP,
  POSTING_STATUS_LABELS,
  POSTING_STATUS_TONE,
  RUN_STATUS_LABELS,
  RUN_STATUS_TONE,
  TIMELINE_KIND_LABELS,
} from '../lib/labels';
import { Icon } from './Icon';
import { Badge } from './ui';

export function PostingStatusBadge({ status, label }: { status: PostingStatus; label?: string }) {
  return (
    <Badge tone={POSTING_STATUS_TONE[status] ?? 'neutral'} title={POSTING_STATUS_HELP[status]}>
      {label ?? POSTING_STATUS_LABELS[status] ?? status}
    </Badge>
  );
}

export function ConfigStatusBadge({ status }: { status: SourceConfigStatus }) {
  return <Badge tone={CONFIG_STATUS_TONE[status] ?? 'neutral'}>{CONFIG_STATUS_LABELS[status] ?? status}</Badge>;
}

export function HealthBadge({ health, label }: { health: SourceHealth; label?: string }) {
  return (
    <Badge tone={HEALTH_TONE[health] ?? 'neutral'} icon={health === 'running' ? 'refresh' : health === 'never_run' ? 'clock' : undefined}>
      {label ?? HEALTH_LABELS[health] ?? health}
    </Badge>
  );
}

export function RunStatusBadge({ status }: { status: RunStatus }) {
  return (
    <Badge tone={RUN_STATUS_TONE[status] ?? 'neutral'} icon={status === 'paused' ? 'pause' : status === 'queued' ? 'clock' : status === 'running' ? 'refresh' : undefined}>
      {RUN_STATUS_LABELS[status] ?? status}
    </Badge>
  );
}

/** Vollständigkeit von Listen- und Detailphase getrennt – ein „vollständiger“ Lauf kann offene Details haben. */
export function Completeness({ value, yes = 'vollständig', no = 'unvollständig' }: { value: boolean | null; yes?: string; no?: string }) {
  if (value === null || value === undefined) return <span className="muted">offen</span>;
  return value ? (
    <span className="mark mark--good">
      <Icon name="check" size={14} /> {yes}
    </span>
  ) : (
    <span className="mark mark--warn">
      <Icon name="alert" size={14} /> {no}
    </span>
  );
}

const GEO_COLORS: Record<GeoClass, string> = {
  resolved: '#2a78d6',
  partial: '#eb6834',
  unresolved: '#1baf7a',
  remote_nationwide: '#eda100',
  foreign: '#e87ba4',
  none: '#898781',
};

interface TotalsBoxProps {
  totals: Totals;
  /** Überschrift der Gesamtzahl, z. B. „Anzeigen im aktuellen Filter“. */
  totalLabel?: string;
  compact?: boolean;
  /** Optional: Klick auf eine Zeile filtert auf diese Ortszuordnung. */
  onSelect?: (geoClass: GeoClass) => void;
}

/**
 * Summenfeld: deutschlandweit zählt jede zusammengeführte Anzeige einmal; die geografische Zuordnung wird
 * getrennt ausgewiesen (Beschriftungen kommen aus der API).
 */
export function TotalsBox({ totals, totalLabel = 'Zusammengeführte Anzeigen (jede zählt deutschlandweit einmal)', compact, onSelect }: TotalsBoxProps) {
  const total = totals.total;
  return (
    <div className={compact ? 'totals totals--compact' : 'totals'}>
      <div className="totals__head">
        <span className="totals__value">{fmtInt(total)}</span>
        <span className="totals__label">{totalLabel}</span>
      </div>
      {total > 0 ? (
        <div className="totals__bar" aria-hidden="true">
          {GEO_CLASSES.filter((g) => totals.geo[g] > 0).map((g) => (
            <span key={g} style={{ flexGrow: totals.geo[g], background: GEO_COLORS[g] }} title={`${GEO_CLASS_SHORT[g]}: ${fmtInt(totals.geo[g])}`} />
          ))}
        </div>
      ) : null}
      <ul className="totals__list">
        {GEO_CLASSES.map((g) => {
          const label = totals.labels?.[g] ?? GEO_CLASS_SHORT[g];
          const content = (
            <>
              <span className="totals__swatch" style={{ background: GEO_COLORS[g] }} aria-hidden="true" />
              <span className="totals__name">{label}</span>
              <span className="totals__count">{fmtInt(totals.geo[g])}</span>
            </>
          );
          return (
            <li key={g}>
              {onSelect && totals.geo[g] > 0 ? (
                <button type="button" className="totals__row totals__row--button" onClick={() => onSelect(g)} title="Auf diese Ortszuordnung filtern">
                  {content}
                </button>
              ) : (
                <span className="totals__row">{content}</span>
              )}
            </li>
          );
        })}
      </ul>
    </div>
  );
}

interface BasisProps {
  basis: ComparableBasis;
  message?: string | null;
  sourceNames?: Map<number, string>;
  compact?: boolean;
}

/** Vergleichbarkeitsgrundlage eines Zeitvergleichs: welche Quellen zählen mit, welche nicht – und warum. */
export function BasisBox({ basis, message, sourceNames, compact }: BasisProps) {
  const names = basis.comparable_sources.map((id) => sourceNames?.get(id) ?? `Quelle Nr. ${id}`);
  return (
    <div className={compact ? 'basis basis--compact' : 'basis'}>
      <p className="basis__dates">
        Vergleich der Stichtage <strong>{fmtDate(basis.date_then)}</strong> und <strong>{fmtDate(basis.date_now)}</strong>
      </p>
      {!basis.comparable ? (
        <p className="basis__message">
          <Icon name="alert" size={16} /> {message ?? 'Kein Vergleich möglich: Für die beiden Stichtage liegt keine vergleichbare Abdeckung vor.'}
        </p>
      ) : (
        <div className="basis__group">
          <p className="basis__heading">Vergleichbare Quellen ({fmtInt(names.length)})</p>
          <p className="basis__text">{names.join(' · ')}</p>
        </div>
      )}
      {basis.excluded.length > 0 ? (
        <div className="basis__group">
          <p className="basis__heading">Vom Vergleich ausgeschlossen ({fmtInt(basis.excluded.length)})</p>
          <ul className="basis__list">
            {basis.excluded.map((e) => (
              <li key={e.source_id}>
                <strong>{e.name ?? `Quelle Nr. ${e.source_id}`}</strong>: {e.reason}
              </li>
            ))}
          </ul>
        </div>
      ) : basis.comparable ? null : (
        <p className="basis__text muted">An beiden Stichtagen wurde keine Quelle vollständig und mit demselben Suchbereich erfasst.</p>
      )}
      {basis.hints.length > 0 ? (
        <div className="basis__group">
          <p className="basis__heading">Hinweise</p>
          <ul className="basis__list">
            {basis.hints.map((h, i) => (
              <li key={i}>{h}</li>
            ))}
          </ul>
        </div>
      ) : null}
      {basis.notes.length > 0 ? (
        <div className="basis__group">
          <p className="basis__heading">Vermerke im Vergleichszeitraum</p>
          <ul className="basis__list">
            {basis.notes.map((n, i) => (
              <li key={i}>
                {fmtDate(n.date)} · {TIMELINE_KIND_LABELS[n.kind] ?? n.kind}: {n.message}
              </li>
            ))}
          </ul>
        </div>
      ) : null}
    </div>
  );
}

interface PaginationProps {
  page: number;
  pageSize: number;
  total: number;
  onPage: (page: number) => void;
}

export function Pagination({ page, pageSize, total, onPage }: PaginationProps) {
  const pages = Math.max(1, Math.ceil(total / pageSize));
  if (pages <= 1) return null;
  const from = (page - 1) * pageSize + 1;
  const to = Math.min(total, page * pageSize);
  const numbers: (number | 'gap')[] = [];
  for (let p = 1; p <= pages; p += 1) {
    if (p === 1 || p === pages || Math.abs(p - page) <= 1) numbers.push(p);
    else if (numbers[numbers.length - 1] !== 'gap') numbers.push('gap');
  }
  return (
    <nav className="pagination" aria-label="Seiten der Trefferliste">
      <p className="pagination__info">
        Treffer {fmtInt(from)}–{fmtInt(to)} von {fmtInt(total)}
      </p>
      <ul className="pagination__list">
        <li>
          <button type="button" className="pagination__btn" disabled={page <= 1} onClick={() => onPage(page - 1)} aria-label="Vorherige Seite">
            <Icon name="chevronLeft" size={16} />
          </button>
        </li>
        {numbers.map((n, i) =>
          n === 'gap' ? (
            <li key={`gap-${i}`} className="pagination__gap" aria-hidden="true">
              …
            </li>
          ) : (
            <li key={n}>
              <button type="button" className={`pagination__btn${n === page ? ' is-current' : ''}`} aria-current={n === page ? 'page' : undefined} aria-label={`Seite ${n}`} onClick={() => onPage(n)}>
                {fmtInt(n)}
              </button>
            </li>
          ),
        )}
        <li>
          <button type="button" className="pagination__btn" disabled={page >= pages} onClick={() => onPage(page + 1)} aria-label="Nächste Seite">
            <Icon name="chevronRight" size={16} />
          </button>
        </li>
      </ul>
    </nav>
  );
}

/** Der Rahmenhinweis, der überall gilt: Anzeigen sind ein Hinweis auf Bedarf, keine Zahl offener Stellen. */
export function FramingNote({ text }: { text?: string }) {
  return (
    <aside className="framing" aria-label="Einordnung der Zahlen">
      <Icon name="info" size={18} />
      <p>
        {text ??
          'WorkForce beobachtet Stellenanzeigen als Hinweis auf Arbeitskräftebedarf. Die Zahlen sind weder die Anzahl offener Arbeitsplätze noch ein amtlicher Nachweis von Fachkräftemangel.'}{' '}
        <Link to="/methodik">Zur Methodik</Link>
      </p>
    </aside>
  );
}
