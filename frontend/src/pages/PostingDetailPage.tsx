import { useEffect, useState } from 'react';
import { Link, useParams } from 'react-router';
import { api, errorMessage } from '../api/client';
import type { PostingDetail, PostingEvent, PostingFeature, PostingLocation, PostingMember, PostingVersion } from '../api/types';
import { useAuth } from '../auth/AuthContext';
import { ConfirmDialog } from '../components/Dialog';
import { PostingStatusBadge } from '../components/domain';
import { ExternalLink } from '../components/ExternalLink';
import { useToast } from '../components/Toast';
import { Alert, Async, Badge, Button, Card, DefList, EmptyState, orUnknown, PageHeader, Unknown } from '../components/ui';
import { fmtDate, fmtDateTime, fmtInt, fmtNum, fmtSalary } from '../lib/format';
import {
  CHANGE_KIND_HELP,
  CHANGE_KIND_LABELS,
  CHANGE_KIND_TONE,
  CONTRACT_LABELS,
  EVENT_LABELS,
  FEATURE_ORIGIN_LABELS,
  FEATURE_TYPE_LABELS,
  FIELD_LABELS,
  GEO_CLASS_SHORT,
  KLDB_SOURCE_LABELS,
  MATCH_METHOD_LABELS,
  mergeReasonLabel,
  POINT_ORIGIN_LABELS,
  POLARITY_HELP,
  POLARITY_LABELS,
  POLARITY_TONE,
  POSTING_STATUS_LABELS,
  PRECISION_LABELS,
  REMOTE_LABELS,
  SALARY_ORIGIN_LABELS,
  WORKING_TIME_LABELS,
} from '../lib/labels';
import { useDistrictNames, useMetaFilters } from '../lib/lookups';
import { rememberPosting } from '../lib/recent';
import { useFetch } from '../lib/useFetch';

const yesNoUnknown = (v: boolean | null) => (v === null ? <Unknown /> : v ? 'ja' : 'nein');
const pct = (v: number | null) => (v === null ? null : `${fmtNum(v * 100, 0)} %`);

function salaryText(v: PostingVersion): string | null {
  const range = fmtSalary(v.salary.min, v.salary.max, v.salary.currency, v.salary.period);
  return [range, v.salary.text].filter(Boolean).join(' · ') || null;
}

function locationText(l: PostingLocation): string {
  return [l.postal_code, l.locality].filter(Boolean).join(' ') || l.raw || 'ohne Angabe';
}

// --- Vergleich zweier Fassungen: was hat sich geändert? ------------------------------------------------
interface DiffField {
  label: string;
  technical?: boolean;
  get: (v: PostingVersion) => string;
}

const list = (items: string[], labels?: Record<string, string>) => items.map((i) => labels?.[i] ?? i).join(', ') || 'keine Angabe';

const DIFF_FIELDS: DiffField[] = [
  { label: 'Titel', get: (v) => v.title },
  { label: 'Arbeitgeber', get: (v) => v.employer_name ?? 'unbekannt' },
  { label: 'Stellenreferenz', get: (v) => v.reference ?? 'keine' },
  { label: 'Art der Anzeige', get: (v) => v.kind_label },
  { label: 'Arbeitszeit', get: (v) => list(v.working_time, WORKING_TIME_LABELS) },
  { label: 'Befristung', get: (v) => (v.contract_term ? (CONTRACT_LABELS[v.contract_term] ?? v.contract_term) : 'unbekannt') },
  { label: 'Remote-Status', get: (v) => (v.remote_type ? (REMOTE_LABELS[v.remote_type] ?? v.remote_type) : 'unbekannt') },
  { label: 'Berufsangabe', get: (v) => v.occupation_label ?? 'keine' },
  { label: 'Berufsklasse (KldB)', get: (v) => v.kldb_code ?? 'keine' },
  { label: 'Vergütung', get: (v) => salaryText(v) ?? 'keine Angabe' },
  { label: 'Veröffentlicht laut Quelle', get: (v) => (v.date_posted ? fmtDate(v.date_posted) : 'unbekannt') },
  { label: 'Bewerbungsfrist', get: (v) => (v.apply_until ? fmtDate(v.apply_until) : 'keine Angabe') },
  { label: 'Angekündigtes Veröffentlichungsende', get: (v) => (v.valid_through ? fmtDate(v.valid_through) : 'keine Angabe') },
  { label: 'Arbeitsorte', get: (v) => v.locations.map(locationText).sort().join('; ') || 'keine Angabe' },
  { label: 'Zugeordnete Kreise', get: (v) => [...v.kreis_keys].sort().join(', ') || 'keine' },
  {
    label: 'Merkmale',
    get: (v) =>
      v.features
        .map((f) => `${f.label} (${POLARITY_LABELS[f.polarity] ?? f.polarity})`)
        .sort()
        .join(', ') || 'keine',
  },
  { label: 'Erfassungstiefe', technical: true, get: (v) => (v.detail_level === 'detail' ? 'Detailseite ausgewertet' : 'nur Listendaten') },
  { label: 'Parserversion', technical: true, get: (v) => v.parser_version },
  { label: 'Klassifikationsregeln', technical: true, get: (v) => v.classifier_version },
  { label: 'Regeln der Ortszuordnung', technical: true, get: (v) => v.geo_rule_version },
];

function diffVersions(prev: PostingVersion, next: PostingVersion) {
  return DIFF_FIELDS.map((f) => ({ field: f, before: f.get(prev), after: f.get(next) })).filter((d) => d.before !== d.after);
}

function VersionHistory({ member, showSource }: { member: PostingMember; showSource: boolean }) {
  const versions = [...member.versions].sort((a, b) => b.version_no - a.version_no);
  return (
    <div className="stack">
      {showSource ? (
        <h3 className="subhead">
          {member.source_name ?? `Quelle ${member.source_id}`} · Quellanzeige {member.source_key}
        </h3>
      ) : null}
      <ol className="versions">
        {versions.map((v, i) => {
          const prev = versions[i + 1];
          const changes = prev ? diffVersions(prev, v) : [];
          const content = changes.filter((c) => !c.field.technical);
          const technical = changes.filter((c) => c.field.technical);
          return (
            <li key={v.id} className={`version version--${v.change_kind}`}>
              <div className="version__head">
                <span className="version__no">Fassung {v.version_no}</span>
                <Badge tone={CHANGE_KIND_TONE[v.change_kind] ?? 'neutral'} title={CHANGE_KIND_HELP[v.change_kind]}>
                  {CHANGE_KIND_LABELS[v.change_kind] ?? v.change_kind}
                </Badge>
                <span className="version__dates">
                  gültig ab {fmtDate(v.valid_from)}
                  {v.valid_to ? ` bis ${fmtDate(v.valid_to)}` : ' – aktuelle Fassung'}
                </span>
              </div>
              <p className="version__help">{CHANGE_KIND_HELP[v.change_kind]}</p>
              {!prev ? <p className="muted">Ausgangsfassung – kein Vergleich möglich.</p> : null}
              {prev && changes.length === 0 ? <p className="muted">Keine Unterschiede in den dargestellten Feldern.</p> : null}
              {content.length > 0 ? (
                <dl className="diff">
                  {content.map((c) => (
                    <div key={c.field.label}>
                      <dt>{c.field.label}</dt>
                      <dd>
                        <span className="diff__before">{c.before}</span>
                        <span className="diff__arrow" aria-label="geändert in">
                          →
                        </span>
                        <span className="diff__after">{c.after}</span>
                      </dd>
                    </div>
                  ))}
                </dl>
              ) : null}
              {technical.length > 0 ? (
                <dl className="diff diff--technical">
                  {technical.map((c) => (
                    <div key={c.field.label}>
                      <dt>{c.field.label} (technisch)</dt>
                      <dd>
                        <span className="diff__before">{c.before}</span>
                        <span className="diff__arrow" aria-label="geändert in">
                          →
                        </span>
                        <span className="diff__after">{c.after}</span>
                      </dd>
                    </div>
                  ))}
                </dl>
              ) : null}
              <p className="version__meta">
                Parser {v.parser_version} · Klassifikation {v.classifier_version} · Ortszuordnung {v.geo_rule_version} ·{' '}
                {v.detail_level === 'detail' ? 'Detailseite ausgewertet' : 'nur Listendaten'}
              </p>
            </li>
          );
        })}
      </ol>
    </div>
  );
}

function eventText(e: PostingEvent, sourceName: (id: number | null) => string | null): string {
  const d = e.details ?? {};
  const parts: string[] = [];
  const src = sourceName(e.source_posting_id);
  if (src) parts.push(src);
  if (e.type === 'left_stock') {
    const status = typeof d.status === 'string' ? (POSTING_STATUS_LABELS[d.status as keyof typeof POSTING_STATUS_LABELS] ?? d.status) : null;
    if (status) parts.push(`neuer Status: ${status}`);
    if (typeof d.reason === 'string') parts.push(d.reason);
  }
  if (e.type === 'content_change' || e.type === 'parser_change') {
    const changed = Array.isArray(d.changed) ? d.changed.filter((x): x is string => typeof x === 'string') : [];
    const labels = [...new Set(changed.map((c) => FIELD_LABELS[c] ?? c))];
    if (labels.length) parts.push(`betroffen: ${labels.join(', ')}`);
  }
  if (e.type === 'additional_source' || e.type === 'republication') {
    if (typeof d.reason === 'string') parts.push(`Grund der Zusammenführung: ${mergeReasonLabel(d.reason)}`);
    if (typeof d.confidence === 'number') parts.push(`Sicherheit ${fmtNum(d.confidence * 100, 0)} %`);
  }
  if (e.type === 'reactivation' && typeof d.previous_status === 'string') {
    parts.push(`zuvor: ${POSTING_STATUS_LABELS[d.previous_status as keyof typeof POSTING_STATUS_LABELS] ?? d.previous_status}`);
  }
  return parts.join(' · ');
}

function FeatureItem({ f }: { f: PostingFeature }) {
  return (
    <li className="feature">
      <div className="feature__head">
        <span className="feature__label">
          {f.label}
          {f.detail ? <span className="muted"> · {f.detail}</span> : null}
        </span>
        <Badge tone={POLARITY_TONE[f.polarity] ?? 'neutral'} title={POLARITY_HELP[f.polarity]}>
          {POLARITY_LABELS[f.polarity] ?? f.polarity}
        </Badge>
      </div>
      {f.evidence ? <blockquote className="quote">„{f.evidence}“</blockquote> : null}
      <p className="feature__meta">
        Herkunft: {FEATURE_ORIGIN_LABELS[f.origin] ?? f.origin} · Regelstand {f.rule_version}
        {f.confidence !== null ? ` · Sicherheit ${pct(f.confidence)}` : ''}
      </p>
    </li>
  );
}

function DetailContent({ data, reload }: { data: PostingDetail; reload: () => void }) {
  const { isAdmin } = useAuth();
  const toast = useToast();
  const meta = useMetaFilters();
  const districts = useDistrictNames();
  const [splitTarget, setSplitTarget] = useState<PostingMember | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [splitResult, setSplitResult] = useState<number | null>(null);
  const cur = data.current;
  const primary = data.members.find((m) => m.is_primary) ?? data.members[0];
  const featureTypes = meta.data?.feature_types ?? FEATURE_TYPE_LABELS;

  useEffect(() => {
    if (cur) rememberPosting({ id: data.id, title: cur.title, employer: cur.employer_name });
  }, [data.id, cur]);

  const memberName = (spId: number | null) => {
    if (spId === null || data.members.length < 2) return null;
    const m = data.members.find((x) => x.source_posting_id === spId);
    return m ? (m.source_name ?? `Quelle ${m.source_id}`) : null;
  };

  const split = () => {
    if (!splitTarget) return;
    setBusy(true);
    setError(null);
    api
      .post<{ merged_posting_id: number }>(`/api/merges/split/${splitTarget.source_posting_id}`)
      .then((res) => {
        toast.success('Zusammenführung gelöst. Die Quellanzeige ist jetzt eine eigene Anzeige.');
        setSplitResult(res.merged_posting_id);
        setSplitTarget(null);
        reload();
      })
      .catch((err: unknown) => setError(errorMessage(err)))
      .finally(() => setBusy(false));
  };

  const featureGroups = new Map<string, PostingFeature[]>();
  for (const f of cur?.features ?? []) featureGroups.set(f.type, [...(featureGroups.get(f.type) ?? []), f]);
  const salary = cur ? salaryText(cur) : null;

  return (
    <>
      {data.is_synthetic ? (
        <Alert tone="warn" title="Synthetische Testanzeige">
          Diese Anzeige wurde zu Testzwecken erzeugt und zählt in keiner Auswertung mit.
        </Alert>
      ) : null}
      {splitResult ? (
        <Alert tone="good" title="Zusammenführung gelöst" role="status">
          Die abgetrennte Quellanzeige ist jetzt <Link to={`/anzeigen/${splitResult}`}>Anzeige Nr. {splitResult}</Link>. Das Paar wird von den automatischen Regeln nicht erneut vereinigt.
        </Alert>
      ) : null}

      <Alert tone="neutral" title="Einordnung">
        <ul className="note-list">
          {data.notes.map((n, i) => (
            <li key={i}>{n}</li>
          ))}
        </ul>
      </Alert>

      {!cur ? (
        <Card>
          <EmptyState title="Keine Inhaltsfassung vorhanden" icon="posting">
            Zu dieser Anzeige ist keine aktuelle Fassung gespeichert. Die Quellenangaben unten bleiben einsehbar.
          </EmptyState>
        </Card>
      ) : (
        <div className="grid grid--main-side">
          <div className="stack stack--loose">
            <Card title="Kerndaten" subtitle="Rumpfdaten der Anzeige. Der Volltext wird nicht gespeichert; fehlende Angaben bleiben „unbekannt“.">
              <DefList
                columns={2}
                items={[
                  { term: 'Titel', value: cur.title, wide: true },
                  { term: 'Arbeitgeber', value: orUnknown(cur.employer_name) },
                  { term: 'Personalvermittlung oder Zeitarbeit', value: yesNoUnknown(cur.is_agency) },
                  { term: 'Art der Anzeige', value: cur.kind_label },
                  { term: 'Stellenreferenz des Arbeitgebers', value: orUnknown(cur.reference, 'keine Angabe') },
                  { term: 'Arbeitszeit', value: cur.working_time.length ? list(cur.working_time, WORKING_TIME_LABELS) : <Unknown /> },
                  { term: 'Befristung', value: cur.contract_term ? (CONTRACT_LABELS[cur.contract_term] ?? cur.contract_term) : <Unknown /> },
                  { term: 'Remote-Status', value: cur.remote_type ? (REMOTE_LABELS[cur.remote_type] ?? cur.remote_type) : <Unknown /> },
                  { term: 'Beschäftigungsarten laut Quelle', value: cur.employment_types.length ? cur.employment_types.join(', ') : <Unknown label="keine Angabe" /> },
                  { term: 'Berufsangabe der Quelle', value: orUnknown([cur.occupation_label, cur.occupation_field].filter(Boolean).join(' · ') || null, 'keine Angabe') },
                  {
                    term: 'Berufsklasse (KldB 2010)',
                    value: cur.kldb_code ? (
                      <>
                        {cur.kldb_code}
                        <span className="table__sub">
                          {KLDB_SOURCE_LABELS[cur.kldb_source ?? ''] ?? cur.kldb_source ?? 'Herkunft unbekannt'}
                          {cur.kldb_confidence !== null ? ` · Sicherheit ${pct(cur.kldb_confidence)}` : ''}
                          {cur.requirement_level ? ` · Anforderungsniveau ${cur.requirement_level}` : ''}
                        </span>
                      </>
                    ) : (
                      <Unknown label="nicht zugeordnet" />
                    ),
                  },
                  {
                    term: 'Erstmals beobachtet',
                    value: (
                      <>
                        {fmtDate(data.first_seen_date)}
                        {data.first_seen_baseline ? <span className="table__sub">bei Bestandsaufnahme erfasst – die Anzeige war damals schon online</span> : <span className="table__sub">kein Veröffentlichungsdatum</span>}
                      </>
                    ),
                  },
                  { term: 'Zuletzt beobachtet', value: fmtDate(data.last_seen_date) },
                  { term: 'Veröffentlicht laut Quelle', value: cur.date_posted ? fmtDate(cur.date_posted) : <Unknown /> },
                  { term: 'Bewerbungsfrist', value: cur.apply_until ? fmtDate(cur.apply_until) : <Unknown label="keine Angabe" /> },
                  { term: 'Angekündigtes Veröffentlichungsende', value: cur.valid_through ? fmtDate(cur.valid_through) : <Unknown label="keine Angabe" /> },
                  { term: 'Erfassungstiefe', value: cur.detail_level === 'detail' ? 'Detailseite ausgewertet' : 'nur Listendaten (Detailseite noch nicht ausgewertet)' },
                ]}
              />
              <div className="salary">
                <h3 className="subhead">Vergütung</h3>
                {salary ? (
                  <p>
                    <strong>{salary}</strong>
                    <span className="table__sub">Herkunft: {SALARY_ORIGIN_LABELS[cur.salary.origin ?? 'unknown'] ?? cur.salary.origin}</span>
                  </p>
                ) : (
                  <p>
                    <Unknown /> <span className="muted">– die Anzeige nennt keine auswertbare Vergütung; es wird nichts geschätzt.</span>
                  </p>
                )}
              </div>
              {cur.excerpts.length > 0 ? (
                <div className="stack stack--tight">
                  <h3 className="subhead">Kurze Belegauszüge</h3>
                  {cur.excerpts.map((x, i) => (
                    <blockquote key={i} className="quote">
                      „{x}“
                    </blockquote>
                  ))}
                </div>
              ) : null}
            </Card>

            <Card title="Qualifikationen und Merkmale" subtitle="regelbasiert aus der Anzeige abgeleitet – die Einordnung kann falsch sein">
              {cur.features.length === 0 ? (
                <EmptyState compact title="Keine Merkmale erkannt" icon="posting">
                  {cur.detail_level === 'detail' ? 'In dieser Anzeige wurde kein Merkmal aus dem Wörterbuch erkannt.' : 'Bisher liegen nur Listendaten vor; Merkmale werden aus der Detailseite abgeleitet.'}
                </EmptyState>
              ) : (
                [...featureGroups.entries()].map(([type, items]) => (
                  <section key={type} className="stack stack--tight">
                    <h3 className="subhead">{featureTypes[type] ?? type}</h3>
                    <ul className="feature-list">
                      {items.map((f) => (
                        <FeatureItem key={`${f.key}-${f.polarity}`} f={f} />
                      ))}
                    </ul>
                  </section>
                ))
              )}
              <p className="field__hint">
                „verlangt“, „erwünscht“ und „verneint“ beschreiben die Formulierung in der Anzeige. „unklar“ heißt: Das Merkmal wird genannt, die Regel konnte aber
                nicht entscheiden, ob es Voraussetzung ist.
              </p>
            </Card>
          </div>

          <div className="stack stack--loose">
            <Card title="Arbeitsorte" subtitle={GEO_CLASS_SHORT[cur.geo_class] ? `Ortszuordnung der Anzeige: ${GEO_CLASS_SHORT[cur.geo_class]}` : undefined}>
              {cur.locations.length === 0 ? (
                <EmptyState compact title="Keine Ortsangabe" icon="region">
                  Die Anzeige nennt keinen Arbeitsort. Sie wird keinem Kreis zugerechnet.
                </EmptyState>
              ) : (
                <ul className="location-list">
                  {cur.locations.map((l, i) => (
                    <li key={i} className="location">
                      <p className="location__name">
                        {locationText(l)}
                        {l.country && l.country !== 'DE' ? ` (${l.country})` : ''}
                      </p>
                      {l.raw && l.raw !== l.locality ? <p className="muted">Angabe der Quelle: „{l.raw}“</p> : null}
                      <dl className="kv kv--wrap">
                        <div>
                          <dt>Zugeordneter Kreis</dt>
                          <dd>{l.kreis_key ? <Link to={`/regionen/${l.kreis_key}`}>{districts.get(l.kreis_key)?.name ?? `Kreis ${l.kreis_key}`}</Link> : <Unknown label="keiner" />}</dd>
                        </div>
                        <div>
                          <dt>Zuordnung über</dt>
                          <dd>{MATCH_METHOD_LABELS[l.match_method] ?? l.match_method}</dd>
                        </div>
                        <div>
                          <dt>Genauigkeit</dt>
                          <dd>
                            {PRECISION_LABELS[l.precision] ?? l.precision}
                            {l.confidence !== null && l.confidence > 0 ? ` · Sicherheit ${pct(l.confidence)}` : ''}
                          </dd>
                        </div>
                        {l.point_origin ? (
                          <div>
                            <dt>Lagepunkt</dt>
                            <dd>{POINT_ORIGIN_LABELS[l.point_origin] ?? l.point_origin}</dd>
                          </div>
                        ) : null}
                        {l.gebietsstand ? (
                          <div>
                            <dt>Gebietsstand</dt>
                            <dd>{fmtDate(l.gebietsstand)}</dd>
                          </div>
                        ) : null}
                      </dl>
                    </li>
                  ))}
                </ul>
              )}
              <p className="field__hint">Mittelpunkte von Gemeinden sind Näherungen und keine Adressen. Nicht eindeutig zuordenbare Orte bleiben ungeklärt.</p>
            </Card>
          </div>
        </div>
      )}

      <Card title={`Quellen dieser Anzeige (${fmtInt(data.members.length)})`} subtitle="Quellanzeigen der Portale, die zu dieser Anzeige zusammengeführt wurden – jede Zusammenführung ist begründet und umkehrbar">
        {data.members.length === 0 ? (
          <EmptyState compact title="Keine Quellanzeige zugeordnet" />
        ) : (
          <ul className="member-list">
            {data.members.map((m) => (
              <li key={m.source_posting_id} className="member">
                <div className="member__head">
                  <div>
                    <h3 className="member__title">
                      <Link to={`/quellen/${m.source_id}`}>{m.source_name ?? `Quelle ${m.source_id}`}</Link>
                    </h3>
                    <p className="muted">
                      Quellanzeige {m.source_key}
                      {m.is_primary ? ' · maßgebliche Quelle für die Kerndaten' : ''}
                    </p>
                  </div>
                  <div className="row">
                    <PostingStatusBadge status={m.status} label={m.status_label} />
                    <ExternalLink href={m.original_url} fallback={<span className="muted">Originalverweis nicht verfügbar</span>}>
                      Originalanzeige
                    </ExternalLink>
                  </div>
                </div>
                <DefList
                  columns={3}
                  items={[
                    { term: 'Grund des Status', value: orUnknown(m.status_reason, 'keine Angabe') },
                    {
                      term: 'Erstmals beobachtet',
                      value: (
                        <>
                          {fmtDateTime(m.first_seen_at)}
                          {m.first_seen_baseline ? <span className="table__sub">bei Bestandsaufnahme erfasst</span> : null}
                        </>
                      ),
                    },
                    { term: 'Zuletzt beobachtet', value: fmtDateTime(m.last_seen_at) },
                    { term: 'Letzte Detailprüfung', value: m.last_detail_check_at ? fmtDateTime(m.last_detail_check_at) : <Unknown label="noch keine" /> },
                    {
                      term: 'Zusammenführung',
                      value: m.merge ? (
                        <>
                          {mergeReasonLabel(m.merge.reason)}
                          <span className="table__sub">
                            Sicherheit {pct(m.merge.confidence)} · Regelstand {m.merge.rule_version} · entschieden {m.merge.decided_by === 'auto' ? 'automatisch' : `von ${m.merge.decided_by}`} am{' '}
                            {fmtDate(m.merge.created_at)}
                          </span>
                        </>
                      ) : (
                        <Unknown label="keine Angabe" />
                      ),
                    },
                    {
                      term: 'Beobachtungszeiträume im Bestand',
                      value:
                        m.periods.length === 0 ? (
                          <Unknown label="keine" />
                        ) : (
                          <ul className="period-list">
                            {m.periods.map((p, i) => (
                              <li key={i}>
                                {fmtDate(p.start_date)} – {p.end_date ? fmtDate(p.end_date) : 'läuft'}
                                {p.end_reason ? <span className="muted"> ({POSTING_STATUS_LABELS[p.end_reason as keyof typeof POSTING_STATUS_LABELS] ?? p.end_reason})</span> : null}
                              </li>
                            ))}
                          </ul>
                        ),
                    },
                  ]}
                />
                {isAdmin && data.members.length > 1 ? (
                  <div className="row row--end">
                    <Button size="sm" icon="split" data-admin-action onClick={() => { setError(null); setSplitTarget(m); }}>
                      Zusammenführung lösen
                    </Button>
                  </div>
                ) : null}
              </li>
            ))}
          </ul>
        )}
        <p className="field__hint">
          Dublettenregel {data.dedup_rule_version ?? 'unbekannt'}. Ein ähnlicher Titel allein führt nie zu einer Zusammenführung; unsichere Paare bleiben getrennt.
        </p>
      </Card>

      <div className="grid grid--2">
        <Card title="Änderungsverlauf" subtitle="Fassungen je Quellanzeige, neueste zuerst. Inhaltliche Änderungen und technische Regelwechsel sind getrennt gekennzeichnet.">
          {data.members.every((m) => m.versions.length === 0) ? (
            <EmptyState compact title="Keine Fassungen gespeichert" />
          ) : (
            data.members.filter((m) => m.versions.length > 0).map((m) => <VersionHistory key={m.source_posting_id} member={m} showSource={data.members.length > 1} />)
          )}
        </Card>
        <Card title="Ereignisse" subtitle="fachliche Ereignisse, neueste zuerst">
          {data.events.length === 0 ? (
            <EmptyState compact title="Keine Ereignisse" icon="clock" />
          ) : (
            <ol className="timeline">
              {data.events.map((e, i) => (
                <li key={i} className={e.type === 'parser_change' ? 'timeline__item timeline__item--technical' : 'timeline__item'}>
                  <span className="timeline__date">{fmtDate(e.effective_date)}</span>
                  <span className="timeline__kind">
                    {EVENT_LABELS[e.type] ?? e.type}
                    {e.type === 'first_seen' && e.baseline ? ' (bei Bestandsaufnahme)' : ''}
                  </span>
                  <span className="timeline__text">
                    {eventText(e, memberName)}
                    {e.event_date !== e.effective_date ? <span className="muted"> festgestellt am {fmtDate(e.event_date)}</span> : null}
                  </span>
                </li>
              ))}
            </ol>
          )}
          <p className="field__hint">Ein Wegfall wird auf den Tag nach der letzten Sichtung datiert und erst nach mehreren vollständigen Scans festgestellt.</p>
        </Card>
      </div>

      <ConfirmDialog open={splitTarget !== null} title="Zusammenführung lösen?" confirmLabel="Zusammenführung lösen" busy={busy} error={error} onConfirm={split} onClose={() => setSplitTarget(null)}>
        <p>
          Die Quellanzeige <strong>{splitTarget?.source_key}</strong> von <strong>{splitTarget?.source_name}</strong> wird aus dieser Anzeige herausgelöst und als eigene Anzeige geführt.
        </p>
        <p className="muted">Die automatischen Regeln vereinigen dieses Paar danach nicht erneut. Zählungen und Zeitreihen ändern sich entsprechend.</p>
      </ConfirmDialog>
    </>
  );
}

export default function PostingDetailPage() {
  const { id = '' } = useParams();
  const valid = /^\d+$/.test(id);
  const detail = useFetch<PostingDetail>(valid ? `/api/postings/${id}` : null);
  const cur = detail.data?.current;
  const primary = detail.data?.members.find((m) => m.is_primary) ?? detail.data?.members[0];

  return (
    <div className="page">
      <PageHeader
        eyebrow={
          <>
            <Link to="/anzeigen">Anzeigen</Link> · Nr. {valid ? id : '–'}
          </>
        }
        title={cur?.title ?? (detail.data ? 'Anzeige ohne Inhaltsfassung' : 'Anzeige')}
        lead={
          detail.data ? (
            <span className="row">
              <span>{cur?.employer_name ?? 'Arbeitgeber unbekannt'}</span>
              {cur ? <span className="chip chip--strong">{cur.kind_label}</span> : null}
              <PostingStatusBadge status={detail.data.status} label={detail.data.status_label} />
            </span>
          ) : undefined
        }
        actions={
          primary ? (
            <ExternalLink className="btn" href={primary.original_url}>
              Originalanzeige
            </ExternalLink>
          ) : null
        }
      />
      {!valid ? (
        <Card>
          <EmptyState title="Ungültige Anzeigennummer" action={<Link className="btn" to="/suche">Zur Stellensuche</Link>}>
            Die Adresse enthält keine gültige Nummer einer Anzeige.
          </EmptyState>
        </Card>
      ) : (
        <Async state={detail} loadingLabel="Anzeige wird geladen …" errorTitle="Die Anzeige konnte nicht geladen werden">
          {(data) => <DetailContent data={data} reload={detail.reload} />}
        </Async>
      )}
    </div>
  );
}
