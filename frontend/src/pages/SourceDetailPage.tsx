import { type FormEvent, useEffect, useId, useState } from 'react';
import { Link, useParams } from 'react-router';
import { api, errorMessage } from '../api/client';
import type { ScanRun, Source, SourceScope, SourcesResponse } from '../api/types';
import { useAuth } from '../auth/AuthContext';
import { Completeness, ConfigStatusBadge, HealthBadge, RunStatusBadge } from '../components/domain';
import { ExternalLink } from '../components/ExternalLink';
import { useToast } from '../components/Toast';
import { Alert, Async, Badge, Button, Card, DefList, EmptyState, orUnknown, PageHeader, TableWrap, Unknown } from '../components/ui';
import { fmtDate, fmtDateTime, fmtInt, fmtNum } from '../lib/format';
import { ACCESS_METHOD_LABELS, HEALTH_LABELS, SCOPE_MODE_LABELS } from '../lib/labels';
import { useFetch } from '../lib/useFetch';
import { RunsTable } from './sources/RunsTable';
import { ActivateDialog, DeactivateDialog, RunDialog, ScopeDialog } from './sources/SourceDialogs';

function BudgetCard({ source, onSaved }: { source: Source; onSaved: () => void }) {
  const { isAdmin } = useAuth();
  const toast = useToast();
  const [interval, setIntervalValue] = useState(String(source.budget.request_interval_seconds));
  const [pages, setPages] = useState(String(source.budget.max_pages_per_run));
  const [details, setDetails] = useState(String(source.budget.max_details_per_run));
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const ids = { interval: useId(), pages: useId(), details: useId() };

  useEffect(() => {
    setIntervalValue(String(source.budget.request_interval_seconds));
    setPages(String(source.budget.max_pages_per_run));
    setDetails(String(source.budget.max_details_per_run));
  }, [source.budget.request_interval_seconds, source.budget.max_pages_per_run, source.budget.max_details_per_run]);

  const dirty = Number(interval) !== source.budget.request_interval_seconds || Number(pages) !== source.budget.max_pages_per_run || Number(details) !== source.budget.max_details_per_run;

  const submit = (e: FormEvent) => {
    e.preventDefault();
    setBusy(true);
    setError(null);
    api
      .patch(`/api/sources/${source.id}/budget`, { request_interval_seconds: Number(interval), max_pages_per_run: Number(pages), max_details_per_run: Number(details) })
      .then(() => {
        toast.success('Abrufbudget gespeichert.');
        onSaved();
      })
      .catch((err: unknown) => setError(errorMessage(err)))
      .finally(() => setBusy(false));
  };

  return (
    <Card title="Abrufbudget" subtitle="Begrenzt die Last, die WorkForce bei der Quelle erzeugt">
      {isAdmin ? (
        <form className="form" onSubmit={submit}>
          <div className="form-grid">
            <div className="field">
              <label className="field__label" htmlFor={ids.interval}>
                Abstand zwischen Anfragen (Sekunden)
              </label>
              <input id={ids.interval} className="input" type="number" min={1} max={600} step="0.5" required value={interval} onChange={(e) => setIntervalValue(e.target.value)} />
            </div>
            <div className="field">
              <label className="field__label" htmlFor={ids.pages}>
                Höchstzahl Listenseiten je Lauf
              </label>
              <input id={ids.pages} className="input" type="number" min={1} max={5000} required value={pages} onChange={(e) => setPages(e.target.value)} />
            </div>
            <div className="field">
              <label className="field__label" htmlFor={ids.details}>
                Höchstzahl Detailseiten je Lauf
              </label>
              <input id={ids.details} className="input" type="number" min={0} max={20000} required value={details} onChange={(e) => setDetails(e.target.value)} />
            </div>
          </div>
          <p className="field__hint">Ein in robots.txt vorgegebener Crawl-delay wird zusätzlich eingehalten. Erreicht ein Lauf das Seitenlimit, gilt er als unvollständig – nie als Beleg für entfernte Anzeigen.</p>
          {error ? (
            <p className="form-error" role="alert">
              {error}
            </p>
          ) : null}
          <div className="row">
            <Button type="submit" variant="primary" busy={busy} disabled={!dirty} data-admin-action>
              Budget speichern
            </Button>
          </div>
        </form>
      ) : (
        <DefList
          columns={3}
          items={[
            { term: 'Abstand zwischen Anfragen', value: `${fmtNum(source.budget.request_interval_seconds, 1)} Sekunden` },
            { term: 'Höchstzahl Listenseiten je Lauf', value: fmtInt(source.budget.max_pages_per_run) },
            { term: 'Höchstzahl Detailseiten je Lauf', value: fmtInt(source.budget.max_details_per_run) },
          ]}
        />
      )}
    </Card>
  );
}

function SourceContent({ source, labels, reload }: { source: Source; labels: SourcesResponse | undefined; reload: () => void }) {
  const { isAdmin } = useAuth();
  const runs = useFetch<ScanRun[]>(`/api/runs?source_id=${source.id}&limit=50`);
  const [dialog, setDialog] = useState<null | 'activate' | 'deactivate' | 'run' | 'test' | 'scope'>(null);
  const [scopeTemplate, setScopeTemplate] = useState<SourceScope | null>(null);
  const isActive = source.config_status === 'active';
  const canTest = source.adapter_available && (isActive || source.config_status === 'candidate');
  const refresh = () => {
    reload();
    runs.reload();
  };

  return (
    <>
      {isAdmin ? (
        <Card title="Aktionen" subtitle="Nur für die Administration – jede Aktion wird protokolliert">
          {!source.adapter_available ? (
            <Alert tone="neutral" title="Kein Adapter implementiert">
              Diese Quelle ist nur im Register dokumentiert. Sie kann weder freigegeben noch abgerufen werden.
            </Alert>
          ) : (
            <div className="row">
              {isActive ? (
                <>
                  <Button icon="play" variant="primary" data-admin-action onClick={() => setDialog('run')}>
                    Manuellen Lauf starten
                  </Button>
                  <Button icon="play" data-admin-action onClick={() => setDialog('test')}>
                    Begrenzter Testlauf
                  </Button>
                  <Button icon="stop" variant="danger" data-admin-action onClick={() => setDialog('deactivate')}>
                    Deaktivieren
                  </Button>
                </>
              ) : (
                <>
                  <Button icon="check" variant="primary" data-admin-action onClick={() => setDialog('activate')}>
                    Freigeben …
                  </Button>
                  <Button icon="play" data-admin-action disabled={!canTest} title={canTest ? undefined : 'Testläufe sind nur für vorgemerkte oder freigegebene Quellen möglich'} onClick={() => setDialog('test')}>
                    Begrenzter Testlauf
                  </Button>
                  {source.config_status !== 'disabled' ? (
                    <Button variant="ghost" data-admin-action onClick={() => setDialog('deactivate')}>
                      Status ändern …
                    </Button>
                  ) : null}
                </>
              )}
            </div>
          )}
          {!isActive && source.adapter_available ? <p className="field__hint">Keine Quelle ist automatisch aktiv. Die Freigabe verlangt einen Freigabevermerk{source.config_status === 'permission_required' ? ' und den Nachweis der Erlaubnis des Betreibers' : ''}.</p> : null}
        </Card>
      ) : null}

      <div className="grid grid--2">
        <Card title="Konfigurationsstatus" subtitle="Entscheidung des Betreibers: Darf die Quelle abgerufen werden?">
          <div className="row">
            <ConfigStatusBadge status={source.config_status} />
            <span className="muted">{labels?.status_labels[source.config_status]}</span>
          </div>
          <DefList
            columns={1}
            items={[
              { term: 'Begründung', value: orUnknown(source.status_reason, 'keine Angabe') },
              { term: 'Rechtliche Prüfung zuletzt am', value: source.legal_checked_on ? fmtDate(source.legal_checked_on) : <Unknown label="noch nicht geprüft" /> },
              { term: 'Registereintrag geändert', value: fmtDateTime(source.updated_at) },
            ]}
          />
        </Card>
        <Card title="Technischer Zustand" subtitle="Ergebnis der letzten Läufe – unabhängig vom Konfigurationsstatus">
          <div className="row">
            <HealthBadge health={source.health} label={labels?.health_labels[source.health] ?? HEALTH_LABELS[source.health]} />
          </div>
          <DefList
            columns={2}
            items={[
              {
                term: 'Letzter Lauf',
                value: source.last_run ? (
                  <>
                    <Link to={`/quellen/laeufe/${source.last_run.id}`}>Nr. {source.last_run.id}</Link> vom {fmtDate(source.last_run.logical_date)} <RunStatusBadge status={source.last_run.status} />
                    {source.last_run.status_detail ? <span className="table__sub">{source.last_run.status_detail}</span> : null}
                  </>
                ) : (
                  <Unknown label="noch kein Lauf" />
                ),
              },
              {
                term: 'Letzter vollständiger Lauf',
                value: source.last_complete_run ? (
                  <>
                    <Link to={`/quellen/laeufe/${source.last_complete_run.id}`}>Nr. {source.last_complete_run.id}</Link> vom {fmtDate(source.last_complete_run.logical_date)}
                  </>
                ) : (
                  <Unknown label="noch keiner" />
                ),
              },
              {
                term: 'Liste / Details im letzten Lauf',
                value: source.last_run ? (
                  <span className="row">
                    <Completeness value={source.last_run.list_complete} yes="Liste vollständig" no="Liste unvollständig" />
                    <Completeness value={source.last_run.detail_complete} yes="Details vollständig" no="Details unvollständig" />
                  </span>
                ) : (
                  <Unknown label="–" />
                ),
              },
              { term: 'Datenstand (zuletzt beobachtet)', value: source.data_as_of ? fmtDateTime(source.data_as_of) : <Unknown label="noch keine Daten" /> },
              { term: 'Bestand', value: `${fmtInt(source.stock)} Anzeigen im beobachteten Bestand` },
              { term: 'Erfasste Quellanzeigen insgesamt', value: fmtInt(source.postings_total) },
              { term: 'Offene Detailprüfungen', value: fmtInt(source.details_pending) },
            ]}
          />
        </Card>
      </div>

      <Card title="Rechtliche Hinweise" subtitle="Dokumentiertes Prüfergebnis – keine Rechtsberatung">
        <p className="prose">{source.legal_notes ?? <Unknown label="Kein Prüfvermerk hinterlegt." />}</p>
        <DefList
          columns={3}
          items={[
            { term: 'Nutzungsbedingungen / Impressum', value: <ExternalLink href={source.terms_url} fallback={<Unknown label="nicht hinterlegt" />}>{source.terms_url}</ExternalLink> },
            { term: 'robots.txt', value: <ExternalLink href={source.robots_url} fallback={<Unknown label="nicht hinterlegt" />}>{source.robots_url}</ExternalLink> },
            { term: 'Einstiegsseite', value: <ExternalLink href={source.entry_url} fallback={<Unknown label="nicht hinterlegt" />}>{source.entry_url}</ExternalLink> },
            { term: 'Quellenangabe', value: orUnknown(source.attribution, 'keine Vorgabe hinterlegt'), wide: true },
          ]}
        />
      </Card>

      <div className="grid grid--2">
        <Card title="Zugriff und Adapter">
          <DefList
            columns={2}
            items={[
              { term: 'Fachliche Abdeckung', value: orUnknown(source.segment, 'keine Angabe'), wide: true },
              { term: 'Zugriffsart', value: source.access_method ? (ACCESS_METHOD_LABELS[source.access_method] ?? source.access_method) : <Unknown label="nicht festgelegt" /> },
              {
                term: 'Adapter',
                value: source.adapter_available ? (
                  <>
                    <code>{source.adapter_key}</code> · Version {source.adapter_version ?? 'unbekannt'}
                  </>
                ) : (
                  <Badge tone="muted">kein Adapter</Badge>
                ),
              },
              { term: 'Erfassungsart', value: source.discovery_mode ? (SCOPE_MODE_LABELS[source.discovery_mode] ?? source.discovery_mode) : <Unknown label="–" /> },
              { term: 'Kurze Belegauszüge', value: source.store_excerpts === null ? <Unknown label="–" /> : source.store_excerpts ? 'werden gespeichert' : 'werden nicht gespeichert (nur Rumpfdaten)' },
              { term: 'Zulässige Domains', value: source.allowed_domains.length ? source.allowed_domains.join(', ') : source.domain, wide: true },
            ]}
          />
        </Card>
        <BudgetCard source={source} onSaved={reload} />
      </div>

      <Card
        title="Suchbereiche"
        subtitle="Versioniert: Jede Änderung erzeugt eine neue Version, damit Zeitvergleiche nachvollziehbar bleiben"
        actions={
          isAdmin && source.adapter_available ? (
            <Button size="sm" icon="plus" data-admin-action onClick={() => { setScopeTemplate(null); setDialog('scope'); }}>
              Suchbereich anlegen
            </Button>
          ) : null
        }
      >
        {source.scopes.length === 0 ? (
          <EmptyState compact title="Kein Suchbereich angelegt" icon="layers">
            Ohne Suchbereich kann die Quelle nicht abgerufen werden.
          </EmptyState>
        ) : (
          <TableWrap label="Suchbereiche und Versionen">
            <table className="table table--compact">
              <thead>
                <tr>
                  <th scope="col">Suchbereich</th>
                  <th scope="col">Version</th>
                  <th scope="col">Zustand</th>
                  <th scope="col">Modus</th>
                  <th scope="col" className="col-num">
                    Seitenbudget
                  </th>
                  <th scope="col">Parameter</th>
                  <th scope="col">Angelegt</th>
                  <th scope="col">
                    <span className="visually-hidden">Aktionen</span>
                  </th>
                </tr>
              </thead>
              <tbody>
                {[...source.scopes]
                  .sort((a, b) => a.key.localeCompare(b.key) || b.version - a.version)
                  .map((sc) => (
                    <tr key={sc.id}>
                      <th scope="row">
                        {sc.name}
                        <span className="table__sub mono">{sc.key}</span>
                        {sc.note ? <span className="table__sub">{sc.note}</span> : null}
                      </th>
                      <td className="num">{sc.version}</td>
                      <td>{sc.is_active ? <Badge tone="good">aktiv</Badge> : <Badge tone="muted">stillgelegt{sc.retired_at ? ` am ${fmtDate(sc.retired_at)}` : ''}</Badge>}</td>
                      <td>{SCOPE_MODE_LABELS[sc.mode] ?? sc.mode}</td>
                      <td className="col-num">{sc.page_budget ?? <span className="muted">wie Quelle</span>}</td>
                      <td className="col-wrap">
                        <code className="params">{Object.keys(sc.params).length ? JSON.stringify(sc.params) : '{}'}</code>
                      </td>
                      <td className="nowrap">{fmtDate(sc.created_at)}</td>
                      <td className="col-actions">
                        {isAdmin && sc.is_active ? (
                          <Button size="sm" data-admin-action onClick={() => { setScopeTemplate(sc); setDialog('scope'); }}>
                            Neue Version …
                          </Button>
                        ) : null}
                      </td>
                    </tr>
                  ))}
              </tbody>
            </table>
          </TableWrap>
        )}
        <p className="field__hint">Der erste Lauf einer neuen Version ist eine Bestandsaufnahme: Was er findet, gilt nicht als neu veröffentlicht.</p>
      </Card>

      <Card title="Laufprotokoll dieser Quelle" subtitle="die letzten 50 Läufe einschließlich Testläufen" actions={<Button size="sm" variant="ghost" icon="refresh" onClick={runs.reload}>Aktualisieren</Button>} flush>
        <Async state={runs} compact loadingLabel="Läufe werden geladen …">
          {(data) => <RunsTable runs={data} onChanged={refresh} />}
        </Async>
      </Card>

      <ActivateDialog source={source} open={dialog === 'activate'} onClose={() => setDialog(null)} onDone={refresh} />
      <DeactivateDialog source={source} open={dialog === 'deactivate'} onClose={() => setDialog(null)} onDone={refresh} />
      <RunDialog source={source} open={dialog === 'run' || dialog === 'test'} test={dialog === 'test'} onClose={() => setDialog(null)} onDone={refresh} />
      <ScopeDialog source={source} open={dialog === 'scope'} template={scopeTemplate} onClose={() => setDialog(null)} onDone={refresh} />
    </>
  );
}

export default function SourceDetailPage() {
  const { sourceId = '' } = useParams();
  const valid = /^\d+$/.test(sourceId);
  const detail = useFetch<Source>(valid ? `/api/sources/${sourceId}` : null);
  const all = useFetch<SourcesResponse>('/api/sources');

  return (
    <div className="page">
      <PageHeader
        eyebrow={<Link to="/quellen">Quellenverwaltung</Link>}
        title={detail.data?.name ?? 'Quelle'}
        lead={
          detail.data ? (
            <span className="row">
              <span className="mono">{detail.data.domain}</span>
              <ConfigStatusBadge status={detail.data.config_status} />
              <HealthBadge health={detail.data.health} />
            </span>
          ) : undefined
        }
      />
      {!valid ? (
        <Card>
          <EmptyState title="Ungültige Quellennummer" action={<Link className="btn" to="/quellen">Zur Quellenverwaltung</Link>} />
        </Card>
      ) : (
        <Async state={detail} loadingLabel="Quelle wird geladen …" errorTitle="Die Quelle konnte nicht geladen werden">
          {(source) => <SourceContent source={source} labels={all.data} reload={detail.reload} />}
        </Async>
      )}
    </div>
  );
}
