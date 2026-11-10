import { useState } from 'react';
import { Link } from 'react-router';
import { api, errorMessage } from '../../api/client';
import type { RunStatus, ScanRun } from '../../api/types';
import { useAuth } from '../../auth/AuthContext';
import { Completeness, RunStatusBadge } from '../../components/domain';
import { useToast } from '../../components/Toast';
import { Badge, Button, EmptyState, TableWrap } from '../../components/ui';
import { fmtDate, fmtDateTime, fmtInt } from '../../lib/format';
import { RUN_TRIGGER_LABELS } from '../../lib/labels';

export type RunAction = 'pause' | 'resume' | 'cancel' | 'retry';

const ACTION_LABELS: Record<RunAction, string> = { pause: 'Pausieren', resume: 'Fortsetzen', cancel: 'Abbrechen', retry: 'Wiederholen' };
const ACTION_DONE: Record<RunAction, string> = {
  pause: 'Pause angefordert – der Lauf hält am nächsten Kontrollpunkt an.',
  resume: 'Lauf wird fortgesetzt.',
  cancel: 'Abbruch angefordert.',
  retry: 'Lauf wird wiederholt.',
};

export function actionsFor(status: RunStatus): RunAction[] {
  switch (status) {
    case 'running':
      return ['pause', 'cancel'];
    case 'queued':
      return ['cancel'];
    case 'paused':
      return ['resume', 'cancel'];
    case 'partial':
    case 'blocked':
    case 'failed':
      return ['retry'];
    default:
      return [];
  }
}

/** Steuerung eines Laufs (nur Administration). Fehler der API – z. B. „Wiederholung nur am selben Tag“ – werden angezeigt. */
export function RunActions({ run, onChanged, size = 'sm' }: { run: ScanRun; onChanged: () => void; size?: 'sm' | 'md' }) {
  const { isAdmin } = useAuth();
  const toast = useToast();
  const [busy, setBusy] = useState<RunAction | null>(null);
  const actions = actionsFor(run.status);
  if (!isAdmin || actions.length === 0) return null;

  const run_ = (action: RunAction) => {
    setBusy(action);
    api
      .post(`/api/runs/${run.id}/${action}`)
      .then(() => {
        toast.success(`Lauf ${run.id}: ${ACTION_DONE[action]}`);
        onChanged();
      })
      .catch((err: unknown) => toast.error(`Lauf ${run.id}: ${errorMessage(err)}`))
      .finally(() => setBusy(null));
  };

  return (
    <span className="run-actions">
      {actions.map((a) => (
        <Button key={a} size={size} variant={a === 'cancel' ? 'danger' : 'secondary'} icon={a === 'pause' ? 'pause' : a === 'resume' ? 'play' : a === 'cancel' ? 'stop' : 'refresh'} busy={busy === a} disabled={busy !== null} data-admin-action onClick={() => run_(a)}>
          {ACTION_LABELS[a]}
        </Button>
      ))}
      {run.control ? <span className="muted">angefordert: {run.control === 'pause' ? 'Pause' : run.control === 'cancel' ? 'Abbruch' : run.control}</span> : null}
    </span>
  );
}

export function coverageNote(run: ScanRun): string | null {
  const note = run.coverage?.note;
  return typeof note === 'string' && note ? note : null;
}

interface Props {
  runs: ScanRun[];
  showSource?: boolean;
  onChanged: () => void;
  emptyText?: string;
}

/** Laufprotokoll. Vollständigkeit der Liste und der Detailanreicherung stehen bewusst in getrennten Spalten. */
export function RunsTable({ runs, showSource, onChanged, emptyText }: Props) {
  if (runs.length === 0) {
    return (
      <EmptyState compact title="Noch keine Läufe" icon="clock">
        {emptyText ?? 'Läufe erscheinen hier, sobald eine freigegebene Quelle gescannt oder ein Testlauf gestartet wurde.'}
      </EmptyState>
    );
  }
  return (
    <TableWrap label="Laufprotokoll">
      <table className="table table--compact">
        <thead>
          <tr>
            <th scope="col">Lauf</th>
            {showSource ? <th scope="col">Quelle</th> : null}
            <th scope="col">Suchbereich</th>
            <th scope="col">Status</th>
            <th scope="col">Liste</th>
            <th scope="col">Details</th>
            <th scope="col" className="col-num">
              Seiten
            </th>
            <th scope="col" className="col-num">
              IDs gefunden
            </th>
            <th scope="col" className="col-num">
              neu
            </th>
            <th scope="col" className="col-num">
              geändert
            </th>
            <th scope="col" className="col-num">
              Fehler
            </th>
            <th scope="col">Abdeckungshinweis</th>
            <th scope="col">
              <span className="visually-hidden">Aktionen</span>
            </th>
          </tr>
        </thead>
        <tbody>
          {runs.map((r) => (
            <tr key={r.id}>
              <th scope="row" className="nowrap">
                <Link to={`/quellen/laeufe/${r.id}`}>Nr. {r.id}</Link>
                <span className="table__sub">
                  {fmtDate(r.logical_date)} · {RUN_TRIGGER_LABELS[r.trigger] ?? r.trigger}
                </span>
                <span className="run-flags">
                  {r.is_test ? <Badge tone="muted" icon={false}>Testlauf</Badge> : null}
                  {r.is_baseline ? <Badge tone="info" icon={false}>Bestandsaufnahme</Badge> : null}
                </span>
              </th>
              {showSource ? (
                <td>
                  <Link to={`/quellen/${r.source_id}`}>{r.source_name ?? `Quelle ${r.source_id}`}</Link>
                </td>
              ) : null}
              <td className="nowrap">
                {r.scope_key}
                <span className="table__sub">Version {r.scope_version}</span>
              </td>
              <td>
                <RunStatusBadge status={r.status} />
                {r.finished_at ? <span className="table__sub">beendet {fmtDateTime(r.finished_at)}</span> : r.started_at ? <span className="table__sub">gestartet {fmtDateTime(r.started_at)}</span> : null}
              </td>
              <td>
                <Completeness value={r.list_complete} />
              </td>
              <td>
                <Completeness value={r.detail_complete} />
                {r.details_pending > 0 ? <span className="table__sub">{fmtInt(r.details_pending)} offen</span> : null}
              </td>
              <td className="col-num">{fmtInt(r.pages_fetched)}</td>
              <td className="col-num">
                {fmtInt(r.ids_found)}
                {r.reported_total !== null ? <span className="table__sub">Portal meldet {fmtInt(r.reported_total)}</span> : null}
              </td>
              <td className="col-num">{fmtInt(r.postings_new)}</td>
              <td className="col-num">{fmtInt(r.postings_changed)}</td>
              <td className="col-num">{r.error_count > 0 ? <strong>{fmtInt(r.error_count)}</strong> : '0'}</td>
              <td className="col-wrap">{coverageNote(r) ?? r.status_detail ?? <span className="muted">–</span>}</td>
              <td className="col-actions">
                <RunActions run={r} onChanged={onChanged} />
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </TableWrap>
  );
}
