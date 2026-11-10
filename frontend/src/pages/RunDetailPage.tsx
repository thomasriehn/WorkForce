import { Link, useParams } from 'react-router';
import type { ScanRunDetail } from '../api/types';
import { Completeness, RunStatusBadge } from '../components/domain';
import { Alert, Async, Badge, Button, Card, DefList, EmptyState, PageHeader, TableWrap, Unknown } from '../components/ui';
import { fmtDate, fmtDateTime, fmtInt } from '../lib/format';
import { RUN_TRIGGER_LABELS, SCOPE_MODE_LABELS, TASK_STATUS_LABELS } from '../lib/labels';
import { useFetch } from '../lib/useFetch';
import { coverageNote, RunActions } from './sources/RunsTable';

const TASK_KIND_LABELS: Record<string, string> = { list: 'Listenentdeckung', detail: 'Detailanreicherung' };

const ERROR_KIND_LABELS: Record<string, string> = {
  timeout: 'Zeitüberschreitung',
  http_403: 'Zugriff verweigert (HTTP 403)',
  captcha: 'CAPTCHA oder Bot-Schutz',
  parse: 'Seite nicht lesbar (Parserfehler)',
  robots: 'durch robots.txt ausgeschlossen',
  cap: 'Seitenlimit erreicht',
  repeat: 'wiederholte Seite',
  empty: 'leere Antwort',
};

function RunContent({ run, reload }: { run: ScanRunDetail; reload: () => void }) {
  const note = coverageNote(run);
  const blocked = run.status === 'blocked' || run.status === 'partial' || run.status === 'failed';
  return (
    <>
      {blocked ? (
        <Alert tone="warn" title="Dieser Lauf ist kein Beleg für entfernte Anzeigen">
          Blockaden, Zeitüberschreitungen, Parserfehler und Seitenlimits machen einen Lauf unvollständig. Anzeigen, die dabei nicht gesehen wurden, behalten ihren Status.
        </Alert>
      ) : null}
      <Card title="Ergebnis" actions={<RunActions run={run} onChanged={reload} size="md" />}>
        <DefList
          columns={3}
          items={[
            { term: 'Status', value: <RunStatusBadge status={run.status} /> },
            { term: 'Listenentdeckung', value: <Completeness value={run.list_complete} /> },
            {
              term: 'Detailanreicherung',
              value: (
                <>
                  <Completeness value={run.detail_complete} />
                  <span className="table__sub">
                    {fmtInt(run.details_fetched)} abgerufen, {fmtInt(run.details_pending)} offen
                  </span>
                </>
              ),
            },
            { term: 'Statushinweis', value: run.status_detail ?? <Unknown label="keiner" />, wide: true },
            { term: 'Abdeckungshinweis', value: note ?? <Unknown label="keiner" />, wide: true },
            { term: 'Seiten abgerufen', value: fmtInt(run.pages_fetched) },
            { term: 'Anfragen insgesamt', value: fmtInt(run.requests_made) },
            { term: 'Teilaufträge', value: `${fmtInt(run.partitions_done)} von ${fmtInt(run.partitions_total)} erledigt` },
            { term: 'IDs gefunden', value: fmtInt(run.ids_found) },
            { term: 'Vom Portal gemeldete Trefferzahl', value: run.reported_total === null ? <Unknown label="keine Angabe" /> : fmtInt(run.reported_total) },
            { term: 'Anzeigen ausgewertet', value: fmtInt(run.postings_extracted) },
            { term: 'Neu', value: fmtInt(run.postings_new) },
            { term: 'Geändert', value: fmtInt(run.postings_changed) },
            { term: 'Fehler', value: fmtInt(run.error_count) },
          ]}
        />
      </Card>

      <Card title="Rahmen des Laufs">
        <DefList
          columns={3}
          items={[
            { term: 'Quelle', value: <Link to={`/quellen/${run.source_id}`}>{run.source_name ?? `Quelle ${run.source_id}`}</Link> },
            { term: 'Suchbereich', value: `${run.scope_key} · Version ${run.scope_version}` },
            { term: 'Logisches Datum', value: fmtDate(run.logical_date) },
            { term: 'Auslöser', value: RUN_TRIGGER_LABELS[run.trigger] ?? run.trigger },
            { term: 'Modus', value: SCOPE_MODE_LABELS[run.mode] ?? run.mode },
            {
              term: 'Art',
              value: (
                <span className="row">
                  {run.is_test ? <Badge tone="muted" icon={false}>Testlauf{run.page_limit ? ` (höchstens ${run.page_limit} Seiten)` : ''}</Badge> : <span>regulärer Lauf</span>}
                  {run.is_baseline ? <Badge tone="info" icon={false}>Bestandsaufnahme</Badge> : null}
                </span>
              ),
            },
            { term: 'Angelegt', value: fmtDateTime(run.created_at) },
            { term: 'Gestartet', value: run.started_at ? fmtDateTime(run.started_at) : <Unknown label="noch nicht" /> },
            { term: 'Beendet', value: run.finished_at ? fmtDateTime(run.finished_at) : <Unknown label="noch nicht" /> },
            { term: 'Beobachtungsfenster', value: run.window_start ? `${fmtDateTime(run.window_start)} – ${run.window_end ? fmtDateTime(run.window_end) : 'offen'}` : <Unknown label="–" /> },
            { term: 'Parser / Klassifikation', value: `${run.parser_version ?? '–'} / ${run.classifier_version ?? '–'}` },
            { term: 'Versuche', value: fmtInt(run.attempts) },
          ]}
        />
        {run.is_baseline ? <p className="field__hint">Bestandsaufnahme: Die in diesem Lauf erstmals gesehenen Anzeigen gelten nicht als neu veröffentlicht.</p> : null}
      </Card>

      <Card title={`Teilaufträge (${run.tasks.length})`} subtitle="Abschnitte der Listenentdeckung und die Detailphase" flush>
        {run.tasks.length === 0 ? (
          <EmptyState compact title="Noch keine Teilaufträge" icon="clock">
            Teilaufträge entstehen, sobald der Lauf startet.
          </EmptyState>
        ) : (
          <TableWrap label="Teilaufträge des Laufs">
            <table className="table table--compact">
              <thead>
                <tr>
                  <th scope="col">Abschnitt</th>
                  <th scope="col">Phase</th>
                  <th scope="col">Status</th>
                  <th scope="col" className="col-num">
                    Seiten
                  </th>
                  <th scope="col" className="col-num">
                    IDs
                  </th>
                  <th scope="col" className="col-num">
                    gemeldet
                  </th>
                  <th scope="col">Beginn</th>
                  <th scope="col">Ende</th>
                  <th scope="col">Hinweis</th>
                </tr>
              </thead>
              <tbody>
                {run.tasks.map((t) => (
                  <tr key={t.id}>
                    <th scope="row" className="mono">
                      {t.partition_key || '–'}
                    </th>
                    <td>{TASK_KIND_LABELS[t.kind] ?? t.kind}</td>
                    <td>{TASK_STATUS_LABELS[t.status] ?? t.status}</td>
                    <td className="col-num">{fmtInt(t.pages_fetched)}</td>
                    <td className="col-num">{fmtInt(t.ids_found)}</td>
                    <td className="col-num">{t.reported_total === null ? '–' : fmtInt(t.reported_total)}</td>
                    <td className="nowrap">{t.started_at ? fmtDateTime(t.started_at) : '–'}</td>
                    <td className="nowrap">{t.finished_at ? fmtDateTime(t.finished_at) : '–'}</td>
                    <td className="col-wrap">{t.status_detail ?? <span className="muted">–</span>}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </TableWrap>
        )}
      </Card>

      <Card title={`Fehlerprotokoll (${run.errors.length}${run.errors.length >= 200 ? '+' : ''})`} subtitle="technische Fehler dieses Laufs, neueste zuerst (höchstens 200)" flush>
        {run.errors.length === 0 ? (
          <EmptyState compact title="Keine Fehler protokolliert" icon="check" />
        ) : (
          <TableWrap label="Fehlerprotokoll des Laufs">
            <table className="table table--compact">
              <thead>
                <tr>
                  <th scope="col">Zeitpunkt</th>
                  <th scope="col">Art</th>
                  <th scope="col">Adresse</th>
                  <th scope="col">Meldung</th>
                </tr>
              </thead>
              <tbody>
                {run.errors.map((e, i) => (
                  <tr key={i}>
                    <td className="nowrap">{fmtDateTime(e.at)}</td>
                    <td>{ERROR_KIND_LABELS[e.kind] ?? e.kind}</td>
                    <td className="col-wrap mono">{e.url ?? '–'}</td>
                    <td className="col-wrap">{e.message ?? '–'}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </TableWrap>
        )}
      </Card>
    </>
  );
}

export default function RunDetailPage() {
  const { runId = '' } = useParams();
  const valid = /^\d+$/.test(runId);
  const run = useFetch<ScanRunDetail>(valid ? `/api/runs/${runId}` : null);
  return (
    <div className="page">
      <PageHeader
        eyebrow={
          <>
            <Link to="/quellen">Quellenverwaltung</Link> · <Link to="/quellen/laeufe">Läufe</Link>
          </>
        }
        title={`Lauf Nr. ${valid ? runId : '–'}`}
        lead={run.data ? `${run.data.source_name ?? 'Quelle'} · Suchbereich ${run.data.scope_key} · ${fmtDate(run.data.logical_date)}` : undefined}
        actions={
          <Button variant="ghost" icon="refresh" onClick={run.reload}>
            Aktualisieren
          </Button>
        }
      />
      {!valid ? (
        <Card>
          <EmptyState title="Ungültige Laufnummer" action={<Link className="btn" to="/quellen/laeufe">Zum Laufprotokoll</Link>} />
        </Card>
      ) : (
        <Async state={run} loadingLabel="Lauf wird geladen …" errorTitle="Der Lauf konnte nicht geladen werden">
          {(data) => <RunContent run={data} reload={run.reload} />}
        </Async>
      )}
    </div>
  );
}
