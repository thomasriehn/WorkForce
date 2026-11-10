import { Link } from 'react-router';
import type { PostingListItem } from '../api/types';
import type { KindGroup } from '../filters/model';
import { KIND_GROUPS } from '../filters/model';
import { fmtDate, fmtSalary, plural } from '../lib/format';
import { CONTRACT_LABELS, KIND_GROUP_LABELS, REMOTE_LABELS, SALARY_ORIGIN_LABELS, WORKING_TIME_LABELS } from '../lib/labels';
import { PostingStatusBadge } from './domain';
import { ExternalLink } from './ExternalLink';
import { Chip, Unknown } from './ui';

/** Beschäftigungsart als Reiter: Ausbildung und Praktika sind von regulären Stellen getrennt. */
export function KindTabs({ value, onChange }: { value: KindGroup; onChange: (value: KindGroup) => void }) {
  return (
    <div className="tabs" role="group" aria-label="Beschäftigungsart">
      {KIND_GROUPS.map((k) => (
        <button key={k} type="button" className={k === value ? 'tab is-active' : 'tab'} aria-pressed={k === value} onClick={() => (k === value ? undefined : onChange(k))}>
          {KIND_GROUP_LABELS[k]}
        </button>
      ))}
    </div>
  );
}

interface CardProps {
  item: PostingListItem;
  featureLabels: Map<string, { label: string; type: string }>;
  compact?: boolean;
}

const MAX_FEATURES = 6;

/** Ein Treffer der Liste. Alle Texte stammen aus der API und werden ausschließlich als Text ausgegeben. */
export function PostingCard({ item, featureLabels, compact }: CardProps) {
  const required = new Set(item.feature_required_keys);
  const features = [...item.feature_keys].sort((a, b) => Number(required.has(b)) - Number(required.has(a)));
  const shown = features.slice(0, compact ? 3 : MAX_FEATURES);
  const salary = fmtSalary(item.salary_min, item.salary_max, item.salary_currency, item.salary_period) ?? item.salary_text;
  const sourceCount = Math.max(item.source_ids.length, 1);

  return (
    <article className={compact ? 'posting posting--compact' : 'posting'}>
      <header className="posting__head">
        <h3 className="posting__title">
          <Link to={`/anzeigen/${item.id}`}>{item.title}</Link>
        </h3>
        <PostingStatusBadge status={item.status} label={item.status_label} />
      </header>
      <p className="posting__sub">
        <span className="posting__employer">{item.employer_name ?? <Unknown label="Arbeitgeber unbekannt" />}</span>
        <span aria-hidden="true"> · </span>
        <span>{item.places ?? <Unknown label={item.geo_class === 'remote_nationwide' ? 'deutschlandweit remote' : 'ohne Ortsangabe'} />}</span>
        {item.geo_class === 'partial' ? <span className="posting__flag"> (Arbeitsorte teilweise ungeklärt)</span> : null}
        {item.geo_class === 'unresolved' ? <span className="posting__flag"> (keinem Kreis zugeordnet)</span> : null}
      </p>

      <div className="chip-row">
        <Chip tone="strong">{item.kind_label}</Chip>
        {item.working_time.map((w) => (
          <Chip key={w}>{WORKING_TIME_LABELS[w] ?? w}</Chip>
        ))}
        {item.contract_term ? <Chip>{CONTRACT_LABELS[item.contract_term] ?? item.contract_term}</Chip> : null}
        {item.remote_type ? <Chip>{REMOTE_LABELS[item.remote_type] ?? item.remote_type}</Chip> : null}
        {item.is_agency ? <Chip>Personalvermittlung</Chip> : null}
        {shown.map((key) => (
          <Chip key={key} tone={required.has(key) ? 'accent' : 'plain'}>
            {featureLabels.get(key)?.label ?? key}
            {required.has(key) ? ' · verlangt' : ''}
          </Chip>
        ))}
        {features.length > shown.length ? <span className="posting__more">+{features.length - shown.length} weitere Merkmale</span> : null}
      </div>

      {compact ? null : (
        <dl className="posting__facts">
          <div>
            <dt>Erstmals beobachtet</dt>
            <dd>
              {fmtDate(item.first_seen_date)}
              {item.first_seen_baseline ? <span className="posting__baseline"> – bei Bestandsaufnahme erfasst</span> : null}
            </dd>
          </div>
          <div>
            <dt>Veröffentlicht laut Quelle</dt>
            <dd>{item.date_posted ? fmtDate(item.date_posted) : <Unknown />}</dd>
          </div>
          {item.apply_until ? (
            <div>
              <dt>Bewerbungsfrist</dt>
              <dd>{fmtDate(item.apply_until)}</dd>
            </div>
          ) : null}
          {salary ? (
            <div>
              <dt>Vergütung</dt>
              <dd title={SALARY_ORIGIN_LABELS[item.salary_origin ?? 'unknown'] ?? undefined}>
                {salary}
                {item.salary_origin === 'portal_estimate' ? ' (Schätzung des Portals)' : ''}
              </dd>
            </div>
          ) : null}
          <div>
            <dt>Quellen</dt>
            <dd>
              {plural(sourceCount, 'Quelle', 'Quellen')}
              {item.member_count > 1 ? `, ${item.member_count} Quellanzeigen zusammengeführt` : ''}
            </dd>
          </div>
        </dl>
      )}

      <footer className="posting__actions">
        {compact ? <span className="muted">erstmals beobachtet {fmtDate(item.first_seen_date)}</span> : null}
        <ExternalLink href={item.original_url} fallback={<span className="muted">Originalverweis nicht verfügbar</span>}>
          Originalanzeige
        </ExternalLink>
        <Link to={`/anzeigen/${item.id}`}>Details und Verlauf</Link>
      </footer>
    </article>
  );
}
