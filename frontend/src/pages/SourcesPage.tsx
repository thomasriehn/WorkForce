import { useId, useState } from 'react';
import { Link, NavLink, useNavigate } from 'react-router';
import type { ScanRun, SourcesResponse } from '../api/types';
import { useAuth } from '../auth/AuthContext';
import { ConfigStatusBadge, HealthBadge, RunStatusBadge } from '../components/domain';
import { Alert, Async, Badge, Button, Card, PageHeader, TableWrap } from '../components/ui';
import { fmtDate, fmtDateTime, fmtInt } from '../lib/format';
import { ACCESS_METHOD_LABELS, CONFIG_STATUS_LABELS, HEALTH_LABELS } from '../lib/labels';
import { useFetch } from '../lib/useFetch';
import { RunsTable } from './sources/RunsTable';
import { CareerPageDialog } from './sources/SourceDialogs';
import { SystemTab } from './sources/SystemTab';

type Tab = 'quellen' | 'laeufe' | 'system';

function SourcesTab() {
  const { isAdmin } = useAuth();
  const navigate = useNavigate();
  const sources = useFetch<SourcesResponse>('/api/sources');
  const [careerOpen, setCareerOpen] = useState(false);

  return (
    <Async state={sources} loadingLabel="Quellenregister wird geladen …">
      {(data) => {
        const counts = new Map<string, number>();
        for (const s of data.sources) counts.set(s.config_status, (counts.get(s.config_status) ?? 0) + 1);
        return (
          <div className="stack stack--loose">
            {!data.crawler.contact_configured ? (
              <Alert tone="warn" title="Keine Kontaktangabe für den Abruf hinterlegt">
                Ohne Kontaktangabe im User-Agent (Einstellung WF_CRAWLER_CONTACT) wird keine Quelle freigegeben und kein Scan gestartet.
              </Alert>
            ) : null}
            <Card
              title={`Quellenregister (${fmtInt(data.sources.length)})`}
              subtitle="Konfigurationsstatus (Entscheidung des Betreibers) und technischer Zustand (Ergebnis der Läufe) sind getrennte Angaben."
              actions={
                isAdmin ? (
                  <Button size="sm" icon="plus" data-admin-action onClick={() => setCareerOpen(true)}>
                    Karriereseite vormerken
                  </Button>
                ) : null
              }
              flush
            >
              <p className="register-counts">
                {(['active', 'candidate', 'permission_required', 'disabled'] as const).map((st) => (
                  <span key={st}>
                    <strong>{fmtInt(counts.get(st) ?? 0)}</strong> {CONFIG_STATUS_LABELS[st]}
                  </span>
                ))}
              </p>
              <TableWrap label="Quellenregister">
                <table className="table table--compact sources-table">
                  <thead>
                    <tr>
                      <th scope="col">Quelle</th>
                      <th scope="col" className="col-group col-group--config">
                        Konfigurationsstatus
                      </th>
                      <th scope="col" className="col-group col-group--health">
                        Technischer Zustand
                      </th>
                      <th scope="col">Segment</th>
                      <th scope="col">Zugriffsart</th>
                      <th scope="col">Adapter</th>
                      <th scope="col">Geprüft am</th>
                      <th scope="col">Letzter vollständiger Lauf</th>
                      <th scope="col">Datenstand</th>
                      <th scope="col" className="col-num">
                        Bestand
                      </th>
                      <th scope="col" className="col-num">
                        Offene Details
                      </th>
                    </tr>
                  </thead>
                  <tbody>
                    {data.sources.map((s) => (
                      <tr key={s.id}>
                        <th scope="row">
                          <Link to={`/quellen/${s.id}`}>{s.name}</Link>
                          <span className="table__sub mono">{s.domain}</span>
                        </th>
                        <td className="col-group col-group--config">
                          <ConfigStatusBadge status={s.config_status} />
                          {s.status_reason ? <span className="table__sub sources-table__reason">{s.status_reason}</span> : null}
                        </td>
                        <td className="col-group col-group--health">
                          <HealthBadge health={s.health} label={data.health_labels[s.health] ?? HEALTH_LABELS[s.health]} />
                          {s.last_run ? (
                            <span className="table__sub">
                              letzter Lauf {fmtDate(s.last_run.logical_date)}: <RunStatusBadge status={s.last_run.status} />
                            </span>
                          ) : null}
                        </td>
                        <td className="col-wrap">{s.segment ?? <span className="muted">–</span>}</td>
                        <td>{s.access_method ? (ACCESS_METHOD_LABELS[s.access_method] ?? s.access_method) : <span className="muted">–</span>}</td>
                        <td className="nowrap">
                          {s.adapter_available ? (
                            <>
                              <code>{s.adapter_key}</code>
                              <span className="table__sub">Version {s.adapter_version ?? '–'}</span>
                            </>
                          ) : (
                            <Badge tone="muted">kein Adapter</Badge>
                          )}
                        </td>
                        <td className="nowrap">{s.legal_checked_on ? fmtDate(s.legal_checked_on) : <span className="muted">–</span>}</td>
                        <td className="nowrap">{s.last_complete_run ? fmtDate(s.last_complete_run.logical_date) : <span className="muted">noch keiner</span>}</td>
                        <td className="nowrap">{s.data_as_of ? fmtDateTime(s.data_as_of) : <span className="muted">keine Daten</span>}</td>
                        <td className="col-num">{fmtInt(s.stock)}</td>
                        <td className="col-num">{fmtInt(s.details_pending)}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </TableWrap>
            </Card>

            <Card title="Abrufkennung und Zeitplan">
              <dl className="deflist deflist--3">
                <div className="deflist__item deflist__item--wide">
                  <dt>User-Agent der Abrufe</dt>
                  <dd className="mono">{data.crawler.user_agent}</dd>
                </div>
                <div className="deflist__item">
                  <dt>Kontaktangabe</dt>
                  <dd>{data.crawler.contact_configured ? 'hinterlegt' : 'fehlt'}</dd>
                </div>
                <div className="deflist__item">
                  <dt>Täglicher Lauf</dt>
                  <dd>
                    {data.crawler.scan_time} Uhr ({data.crawler.timezone})
                  </dd>
                </div>
              </dl>
              <p className="field__hint">
                CAPTCHA, Zugriffssperren (HTTP 403), Zeitüberschreitungen und Parserfehler werden nie umgangen und nie als Hinweis auf entfernte Anzeigen gewertet. Ein
                solcher Lauf gilt als blockiert oder unvollständig.
              </p>
            </Card>
            <CareerPageDialog open={careerOpen} onClose={() => setCareerOpen(false)} onDone={(src) => void navigate(`/quellen/${src.id}`)} />
          </div>
        );
      }}
    </Async>
  );
}

function RunsTab() {
  const [includeTests, setIncludeTests] = useState(true);
  const runs = useFetch<ScanRun[]>(`/api/runs?limit=100&include_tests=${includeTests}`);
  const checkId = useId();
  return (
    <Card
      title="Laufprotokoll aller Quellen"
      subtitle="die letzten 100 Läufe, neueste zuerst"
      actions={
        <>
          <label className="check" htmlFor={checkId}>
            <input id={checkId} type="checkbox" checked={includeTests} onChange={(e) => setIncludeTests(e.target.checked)} />
            <span className="check__label">Testläufe anzeigen</span>
          </label>
          <Button size="sm" variant="ghost" icon="refresh" onClick={runs.reload}>
            Aktualisieren
          </Button>
        </>
      }
      flush
    >
      <Async state={runs} compact loadingLabel="Läufe werden geladen …">
        {(data) => <RunsTable runs={data} showSource onChanged={runs.reload} />}
      </Async>
    </Card>
  );
}

export default function SourcesPage({ tab }: { tab: Tab }) {
  return (
    <div className="page">
      <PageHeader
        title="Quellenverwaltung"
        lead="Register aller bekannten Portale mit dokumentierter Prüfung. Abgerufen werden nur Quellen, die der Betreiber ausdrücklich freigegeben hat."
      />
      <nav className="tabs" aria-label="Bereiche der Quellenverwaltung">
        <NavLink to="/quellen" end className={({ isActive }) => (isActive ? 'tab is-active' : 'tab')}>
          Quellen
        </NavLink>
        <NavLink to="/quellen/laeufe" className={({ isActive }) => (isActive ? 'tab is-active' : 'tab')}>
          Läufe
        </NavLink>
        <NavLink to="/quellen/system" className={({ isActive }) => (isActive ? 'tab is-active' : 'tab')}>
          System
        </NavLink>
      </nav>
      {tab === 'quellen' ? <SourcesTab /> : null}
      {tab === 'laeufe' ? <RunsTab /> : null}
      {tab === 'system' ? <SystemTab /> : null}
    </div>
  );
}
