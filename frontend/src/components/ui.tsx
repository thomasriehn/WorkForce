import type { ButtonHTMLAttributes, ReactNode } from 'react';
import type { ApiError } from '../api/client';
import type { FetchState } from '../lib/useFetch';
import type { Tone } from '../lib/labels';
import { Icon, type IconName } from './Icon';

function cx(...parts: (string | false | null | undefined)[]): string {
  return parts.filter(Boolean).join(' ');
}

// --- Schaltflächen ------------------------------------------------------------------------------------
interface ButtonProps extends ButtonHTMLAttributes<HTMLButtonElement> {
  variant?: 'primary' | 'secondary' | 'ghost' | 'danger';
  size?: 'md' | 'sm';
  icon?: IconName;
  busy?: boolean;
}

export function Button({ variant = 'secondary', size = 'md', icon, busy, className, children, disabled, type, ...rest }: ButtonProps) {
  return (
    <button
      type={type ?? 'button'}
      className={cx('btn', `btn--${variant}`, size === 'sm' && 'btn--sm', className)}
      disabled={disabled || busy}
      aria-busy={busy || undefined}
      {...rest}
    >
      {busy ? <span className="spinner spinner--inline" aria-hidden="true" /> : icon ? <Icon name={icon} size={size === 'sm' ? 16 : 18} /> : null}
      {children}
    </button>
  );
}

// --- Kennzeichnungen ----------------------------------------------------------------------------------
const TONE_ICON: Record<Tone, IconName> = {
  good: 'check',
  warn: 'alert',
  serious: 'alert',
  crit: 'cross',
  info: 'dot',
  neutral: 'dot',
  muted: 'minus',
};

/** Status nie nur über Farbe: jede Kennzeichnung trägt Symbol und Text. */
export function Badge({ tone = 'neutral', children, title, icon }: { tone?: Tone; children: ReactNode; title?: string; icon?: IconName | false }) {
  return (
    <span className={`badge badge--${tone}`} title={title}>
      {icon === false ? null : <Icon name={icon ?? TONE_ICON[tone]} size={13} />}
      <span>{children}</span>
    </span>
  );
}

export function Chip({ children, onRemove, removeLabel, tone }: { children: ReactNode; onRemove?: () => void; removeLabel?: string; tone?: 'accent' | 'plain' | 'strong' }) {
  return (
    <span className={cx('chip', tone === 'accent' && 'chip--accent', tone === 'strong' && 'chip--strong')}>
      <span className="chip__label">{children}</span>
      {onRemove ? (
        <button type="button" className="chip__remove" onClick={onRemove} aria-label={removeLabel ?? 'Entfernen'}>
          <Icon name="close" size={13} />
        </button>
      ) : null}
    </span>
  );
}

// --- Karten und Abschnitte ------------------------------------------------------------------------------
interface CardProps {
  title?: ReactNode;
  subtitle?: ReactNode;
  actions?: ReactNode;
  children: ReactNode;
  className?: string;
  flush?: boolean;
  as?: 'section' | 'div' | 'aside';
  id?: string;
}

export function Card({ title, subtitle, actions, children, className, flush, as = 'section', id }: CardProps) {
  const Tag = as;
  return (
    <Tag className={cx('card', className)} id={id}>
      {title || actions ? (
        <header className="card__header">
          <div>
            {title ? <h2 className="card__title">{title}</h2> : null}
            {subtitle ? <p className="card__subtitle">{subtitle}</p> : null}
          </div>
          {actions ? <div className="card__actions">{actions}</div> : null}
        </header>
      ) : null}
      <div className={cx('card__body', flush && 'card__body--flush')}>{children}</div>
    </Tag>
  );
}

export function PageHeader({ title, lead, actions, eyebrow }: { title: ReactNode; lead?: ReactNode; actions?: ReactNode; eyebrow?: ReactNode }) {
  return (
    <header className="page-header">
      <div className="page-header__text">
        {eyebrow ? <div className="page-header__eyebrow">{eyebrow}</div> : null}
        <h1 className="page-title">{title}</h1>
        {lead ? <p className="page-lead">{lead}</p> : null}
      </div>
      {actions ? <div className="page-header__actions">{actions}</div> : null}
    </header>
  );
}

// --- Hinweise -----------------------------------------------------------------------------------------
export function Alert({ tone = 'info', title, children, role, compact }: { tone?: 'info' | 'warn' | 'crit' | 'good' | 'neutral'; title?: ReactNode; children?: ReactNode; role?: 'alert' | 'status' | 'note'; compact?: boolean }) {
  const icon: IconName = tone === 'crit' ? 'cross' : tone === 'warn' ? 'alert' : tone === 'good' ? 'check' : 'info';
  return (
    <div className={cx('alert', `alert--${tone}`, compact && 'alert--compact')} role={role ?? (tone === 'crit' ? 'alert' : 'note')}>
      <Icon name={icon} size={18} className="alert__icon" />
      <div className="alert__content">
        {title ? <p className="alert__title">{title}</p> : null}
        {children ? <div className="alert__text">{children}</div> : null}
      </div>
    </div>
  );
}

// --- Lade-, Leer- und Fehlerzustände ----------------------------------------------------------------------
export function LoadingState({ label = 'Daten werden geladen …', compact }: { label?: string; compact?: boolean }) {
  return (
    <div className={cx('state', compact && 'state--compact')} role="status" aria-live="polite">
      <span className="spinner" aria-hidden="true" />
      <p className="state__text">{label}</p>
    </div>
  );
}

export function EmptyState({ title, children, icon = 'info', action, compact }: { title: ReactNode; children?: ReactNode; icon?: IconName; action?: ReactNode; compact?: boolean }) {
  return (
    <div className={cx('state state--empty', compact && 'state--compact')}>
      <span className="state__icon" aria-hidden="true">
        <Icon name={icon} size={22} />
      </span>
      <p className="state__title">{title}</p>
      {children ? <div className="state__text">{children}</div> : null}
      {action ? <div className="state__action">{action}</div> : null}
    </div>
  );
}

export function ErrorState({ error, onRetry, title = 'Die Daten konnten nicht geladen werden', compact }: { error: ApiError | Error | string; onRetry?: () => void; title?: string; compact?: boolean }) {
  const message = typeof error === 'string' ? error : error.message;
  const status = typeof error === 'object' && 'status' in error && error.status ? error.status : null;
  return (
    <div className={cx('state state--error', compact && 'state--compact')} role="alert">
      <span className="state__icon" aria-hidden="true">
        <Icon name="alert" size={22} />
      </span>
      <p className="state__title">{title}</p>
      <p className="state__text">
        {message}
        {status ? <span className="state__code"> (HTTP {status})</span> : null}
      </p>
      {onRetry ? (
        <div className="state__action">
          <Button icon="refresh" onClick={onRetry}>
            Erneut versuchen
          </Button>
        </div>
      ) : null}
    </div>
  );
}

interface AsyncProps<T> {
  state: FetchState<T>;
  children: (data: T) => ReactNode;
  loadingLabel?: string;
  errorTitle?: string;
  compact?: boolean;
}

/** Einheitlicher Rahmen für Datenansichten: erst laden, dann Fehler mit Wiederholung, sonst Inhalt. */
export function Async<T>({ state, children, loadingLabel, errorTitle, compact }: AsyncProps<T>) {
  if (state.error) return <ErrorState error={state.error} onRetry={state.reload} title={errorTitle} compact={compact} />;
  if (state.data === undefined) return <LoadingState label={loadingLabel} compact={compact} />;
  return (
    <div className={state.stale || state.loading ? 'is-refreshing' : undefined} aria-busy={state.loading || undefined}>
      {children(state.data)}
    </div>
  );
}

// --- Tabellen, Listen, Kennzahlen ---------------------------------------------------------------------------
export function TableWrap({ children, label }: { children: ReactNode; label: string }) {
  return (
    <div className="table-wrap" role="region" aria-label={label} tabIndex={0}>
      {children}
    </div>
  );
}

export function DefList({ items, columns = 2 }: { items: { term: ReactNode; value: ReactNode; wide?: boolean }[]; columns?: 1 | 2 | 3 }) {
  return (
    <dl className={`deflist deflist--${columns}`}>
      {items.map((item, i) => (
        <div className={cx('deflist__item', item.wide && 'deflist__item--wide')} key={i}>
          <dt>{item.term}</dt>
          <dd>{item.value}</dd>
        </div>
      ))}
    </dl>
  );
}

export function StatTile({ label, value, hint, footer, tone }: { label: ReactNode; value: ReactNode; hint?: ReactNode; footer?: ReactNode; tone?: 'accent' | 'plain' }) {
  return (
    <div className={cx('stat', tone === 'accent' && 'stat--accent')}>
      <div className="stat__label">{label}</div>
      <div className="stat__value">{value}</div>
      {hint ? <div className="stat__hint">{hint}</div> : null}
      {footer ? <div className="stat__footer">{footer}</div> : null}
    </div>
  );
}

/** Unbekannte Angaben bleiben ausdrücklich „unbekannt“ – es wird nichts erfunden. */
export function Unknown({ label = 'unbekannt' }: { label?: string }) {
  return <span className="unknown">{label}</span>;
}

export function orUnknown(value: ReactNode | null | undefined, label?: string): ReactNode {
  if (value === null || value === undefined || value === '') return <Unknown label={label} />;
  return value;
}

// --- Umschalter ---------------------------------------------------------------------------------------
interface SegmentedProps<T extends string> {
  label: string;
  value: T;
  options: { value: T; label: ReactNode; title?: string }[];
  onChange: (value: T) => void;
  size?: 'md' | 'sm';
  hideLabel?: boolean;
}

export function Segmented<T extends string>({ label, value, options, onChange, size = 'md', hideLabel }: SegmentedProps<T>) {
  return (
    <div className={cx('segmented-field', size === 'sm' && 'segmented-field--sm')} role="group" aria-label={label}>
      {hideLabel ? null : <span className="field__label">{label}</span>}
      <div className="segmented">
        {options.map((o) => (
          <button
            key={o.value}
            type="button"
            className={cx('segmented__option', o.value === value && 'is-active')}
            aria-pressed={o.value === value}
            title={o.title}
            onClick={() => {
              if (o.value !== value) onChange(o.value);
            }}
          >
            {o.label}
          </button>
        ))}
      </div>
    </div>
  );
}

export { cx };
