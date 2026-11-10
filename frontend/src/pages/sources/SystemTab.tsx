import { type FormEvent, useId, useState } from 'react';
import { Link } from 'react-router';
import { api, errorMessage } from '../../api/client';
import type { AppUser, MergeCandidate, StatsOverview, SystemStatus, UserCreateResponse, UserUpdateResponse } from '../../api/types';
import { useAuth } from '../../auth/AuthContext';
import { ConfirmDialog, Dialog } from '../../components/Dialog';
import { ExternalLink } from '../../components/ExternalLink';
import { useToast } from '../../components/Toast';
import { Alert, Async, Badge, Button, Card, EmptyState, TableWrap } from '../../components/ui';
import { fmtAgeDays, fmtDate, fmtDateTime, fmtInt, fmtNum } from '../../lib/format';
import { COUNT_LABELS, JOB_KIND_LABELS, JOB_STATUS_LABELS, JOB_STATUS_TONE, mergeReasonLabel, SETTING_LABELS, UPDATE_CYCLE_LABELS } from '../../lib/labels';
import { useFetch } from '../../lib/useFetch';

const JOB_KINDS = ['aggregate', 'stats_check', 'maintenance', 'geo_rematch'] as const;

/** Einmalige Anzeige eines generierten Passworts. */
function SecretDialog({ secret, onClose }: { secret: { username: string; password: string } | null; onClose: () => void }) {
  const [copied, setCopied] = useState(false);
  const canCopy = typeof navigator !== 'undefined' && Boolean(navigator.clipboard) && window.isSecureContext;
  return (
    <Dialog
      open={secret !== null}
      onClose={() => {
        setCopied(false);
        onClose();
      }}
      title="Generiertes Passwort"
      footer={
        <Button variant="primary" onClick={onClose}>
          Passwort notiert – schließen
        </Button>
      }
    >
      <Alert tone="warn" title="Dieses Passwort wird nur dieses eine Mal angezeigt">
        Geben Sie es auf einem sicheren Weg an <strong>{secret?.username}</strong> weiter. Es lässt sich später nicht erneut anzeigen, nur zurücksetzen.
      </Alert>
      <div className="secret">
        <code>{secret?.password}</code>
        {canCopy ? (
          <Button
            size="sm"
            onClick={() => {
              void navigator.clipboard.writeText(secret?.password ?? '').then(() => setCopied(true));
            }}
          >
            {copied ? 'Kopiert' : 'Kopieren'}
          </Button>
        ) : null}
      </div>
    </Dialog>
  );
}

function UsersCard() {
  const { user: me } = useAuth();
  const toast = useToast();
  const users = useFetch<AppUser[]>('/api/users');
  const [createOpen, setCreateOpen] = useState(false);
  const [username, setUsername] = useState('');
  const [role, setRole] = useState<'reader' | 'admin'>('reader');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [secret, setSecret] = useState<{ username: string; password: string } | null>(null);
  const [confirm, setConfirm] = useState<{ user: AppUser; action: 'deactivate' | 'activate' | 'reset' } | null>(null);
  const ids = { name: useId(), role: useId() };

  const create = (e: FormEvent) => {
    e.preventDefault();
    setBusy(true);
    setError(null);
    api
      .post<UserCreateResponse>('/api/users', { username: username.trim(), role })
      .then((res) => {
        setCreateOpen(false);
        setUsername('');
        setRole('reader');
        users.reload();
        if (res.generated_password) setSecret({ username: res.username, password: res.generated_password });
        else toast.success(`Benutzer „${res.username}“ angelegt.`);
      })
      .catch((err: unknown) => setError(errorMessage(err)))
      .finally(() => setBusy(false));
  };

  const apply = () => {
    if (!confirm) return;
    const { user, action } = confirm;
    setBusy(true);
    setError(null);
    const query = action === 'reset' ? { reset_password: true } : { is_active: action === 'activate' };
    api
      .patch<UserUpdateResponse>(`/api/users/${user.id}`, undefined, { query })
      .then((res) => {
        setConfirm(null);
        users.reload();
        if (res.generated_password) setSecret({ username: res.username, password: res.generated_password });
        else toast.success(action === 'activate' ? `„${user.username}“ ist wieder aktiv.` : `„${user.username}“ ist deaktiviert.`);
      })
      .catch((err: unknown) => setError(errorMessage(err)))
      .finally(() => setBusy(false));
  };

  return (
    <Card
      title="Benutzerverwaltung"
      subtitle="Administratoren dürfen ändern, Leser haben ausschließlich lesenden Zugriff"
      actions={
        <Button size="sm" icon="plus" data-admin-action onClick={() => { setError(null); setCreateOpen(true); }}>
          Benutzer anlegen
        </Button>
      }
      flush
    >
      <Async state={users} compact loadingLabel="Benutzer werden geladen …">
        {(data) => (
          <TableWrap label="Benutzer">
            <table className="table table--compact">
              <thead>
                <tr>
                  <th scope="col">Benutzername</th>
                  <th scope="col">Rolle</th>
                  <th scope="col">Zustand</th>
                  <th scope="col">Angelegt</th>
                  <th scope="col">Letzte Anmeldung</th>
                  <th scope="col">
                    <span className="visually-hidden">Aktionen</span>
                  </th>
                </tr>
              </thead>
              <tbody>
                {data.map((u) => (
                  <tr key={u.id}>
                    <th scope="row">
                      {u.username}
                      {u.username === me?.username ? <span className="table__sub">Ihr Konto</span> : null}
                    </th>
                    <td>{u.role === 'admin' ? 'Administration' : 'Lesezugriff'}</td>
                    <td>{u.is_active ? <Badge tone="good">aktiv</Badge> : <Badge tone="muted">deaktiviert</Badge>}</td>
                    <td className="nowrap">{fmtDate(u.created_at)}</td>
                    <td className="nowrap">{u.last_login_at ? fmtDateTime(u.last_login_at) : <span className="muted">noch nie</span>}</td>
                    <td className="col-actions">
                      <span className="run-actions">
                        <Button size="sm" data-admin-action onClick={() => { setError(null); setConfirm({ user: u, action: 'reset' }); }}>
                          Passwort zurücksetzen
                        </Button>
                        {u.username !== me?.username ? (
                          <Button size="sm" variant={u.is_active ? 'danger' : 'secondary'} data-admin-action onClick={() => { setError(null); setConfirm({ user: u, action: u.is_active ? 'deactivate' : 'activate' }); }}>
                            {u.is_active ? 'Deaktivieren' : 'Reaktivieren'}
                          </Button>
                        ) : null}
                      </span>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </TableWrap>
        )}
      </Async>

      <Dialog
        open={createOpen}
        onClose={() => setCreateOpen(false)}
        title="Benutzer anlegen"
        footer={
          <>
            <Button variant="ghost" onClick={() => setCreateOpen(false)} disabled={busy}>
              Abbrechen
            </Button>
            <Button variant="primary" type="submit" form="user-form" busy={busy}>
              Anlegen und Passwort erzeugen
            </Button>
          </>
        }
      >
        <form id="user-form" className="form" onSubmit={create}>
          <div className="field">
            <label className="field__label" htmlFor={ids.name}>
              Benutzername
            </label>
            <input id={ids.name} className="input" required minLength={3} maxLength={80} pattern="[A-Za-z0-9._\-@]{3,80}" autoComplete="off" value={username} onChange={(e) => setUsername(e.target.value)} />
            <p className="field__hint">3 bis 80 Zeichen: Buchstaben, Ziffern, Punkt, Unterstrich, Bindestrich, @.</p>
          </div>
          <div className="field">
            <label className="field__label" htmlFor={ids.role}>
              Rolle
            </label>
            <select id={ids.role} className="select" value={role} onChange={(e) => setRole(e.target.value === 'admin' ? 'admin' : 'reader')}>
              <option value="reader">Lesezugriff – darf alles ansehen, nichts ändern</option>
              <option value="admin">Administration – darf Quellen, Läufe, Benutzer und Importe ändern</option>
            </select>
          </div>
          <p className="field__hint">Das Passwort wird vom System erzeugt und anschließend genau einmal angezeigt.</p>
          {error ? (
            <p className="form-error" role="alert">
              {error}
            </p>
          ) : null}
        </form>
      </Dialog>

      <ConfirmDialog
        open={confirm !== null}
        title={confirm?.action === 'reset' ? 'Passwort zurücksetzen?' : confirm?.action === 'deactivate' ? 'Benutzer deaktivieren?' : 'Benutzer reaktivieren?'}
        confirmLabel={confirm?.action === 'reset' ? 'Neues Passwort erzeugen' : confirm?.action === 'deactivate' ? 'Deaktivieren' : 'Reaktivieren'}
        danger={confirm?.action === 'deactivate'}
        busy={busy}
        error={error}
        onConfirm={apply}
        onClose={() => setConfirm(null)}
      >
        {confirm?.action === 'reset' ? (
          <p>
            Für <strong>{confirm.user.username}</strong> wird ein neues Passwort erzeugt und einmalig angezeigt. Alle laufenden Sitzungen dieses Kontos werden beendet.
          </p>
        ) : confirm?.action === 'deactivate' ? (
          <p>
            <strong>{confirm.user.username}</strong> kann sich danach nicht mehr anmelden. Das Konto und seine gespeicherten Suchen bleiben erhalten.
          </p>
        ) : (
          <p>
            <strong>{confirm?.user.username}</strong> kann sich danach wieder anmelden.
          </p>
        )}
      </ConfirmDialog>
      <SecretDialog secret={secret} onClose={() => setSecret(null)} />
    </Card>
  );
}

function MergeCandidatesCard() {
  const { isAdmin } = useAuth();
  const toast = useToast();
  const candidates = useFetch<MergeCandidate[]>('/api/merges/candidates?state=open&limit=100');
  const [busy, setBusy] = useState<string | null>(null);

  const decide = (c: MergeCandidate, decision: 'merge' | 'reject') => {
    setBusy(`${c.id}-${decision}`);
    api
      .post(`/api/merges/candidates/${c.id}/${decision}`)
      .then(() => {
        toast.success(decision === 'merge' ? 'Anzeigen zusammengeführt.' : 'Kandidat verworfen – das Paar bleibt dauerhaft getrennt.');
        candidates.reload();
      })
      .catch((err: unknown) => toast.error(errorMessage(err)))
      .finally(() => setBusy(null));
  };

  const side = (title: string | null, employer: string | null, source: string, merged: number | null) => (
    <>
      {merged ? <Link to={`/anzeigen/${merged}`}>{title ?? 'ohne Titel'}</Link> : (title ?? 'ohne Titel')}
      <span className="table__sub">
        {employer ?? 'Arbeitgeber unbekannt'} · {source}
      </span>
    </>
  );

  return (
    <Card title="Dublettenkandidaten" subtitle="Unsichere Paare bleiben getrennt, bis sie hier entschieden werden. Ein ähnlicher Titel allein genügt nie." flush>
      <Async state={candidates} compact loadingLabel="Kandidaten werden geladen …">
        {(data) =>
          data.length === 0 ? (
            <EmptyState compact title="Keine offenen Kandidaten" icon="check">
              Es gibt derzeit kein unsicheres Paar, das eine Entscheidung braucht.
            </EmptyState>
          ) : (
            <TableWrap label="Offene Dublettenkandidaten">
              <table className="table table--compact">
                <thead>
                  <tr>
                    <th scope="col">Anzeige A</th>
                    <th scope="col">Anzeige B</th>
                    <th scope="col">Grund</th>
                    <th scope="col" className="col-num">
                      Übereinstimmung
                    </th>
                    <th scope="col">Erkannt</th>
                    <th scope="col">
                      <span className="visually-hidden">Entscheidung</span>
                    </th>
                  </tr>
                </thead>
                <tbody>
                  {data.map((c) => (
                    <tr key={c.id}>
                      <td className="col-wrap">{side(c.a_title, c.a_employer, c.a_source, c.a_merged)}</td>
                      <td className="col-wrap">{side(c.b_title, c.b_employer, c.b_source, c.b_merged)}</td>
                      <td className="col-wrap">
                        {mergeReasonLabel(c.reason)}
                        <span className="table__sub">Regelstand {c.rule_version}</span>
                      </td>
                      <td className="col-num">{fmtNum(c.score * 100, 0)} %</td>
                      <td className="nowrap">{fmtDate(c.created_at)}</td>
                      <td className="col-actions">
                        {isAdmin ? (
                          <span className="run-actions">
                            <Button size="sm" data-admin-action busy={busy === `${c.id}-merge`} disabled={busy !== null} onClick={() => decide(c, 'merge')}>
                              Zusammenführen
                            </Button>
                            <Button size="sm" variant="ghost" data-admin-action busy={busy === `${c.id}-reject`} disabled={busy !== null} onClick={() => decide(c, 'reject')}>
                              Verwerfen
                            </Button>
                          </span>
                        ) : null}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </TableWrap>
          )
        }
      </Async>
    </Card>
  );
}

function StatisticsCard() {
  const { isAdmin } = useAuth();
  const overview = useFetch<StatsOverview>('/api/stats/overview');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [result, setResult] = useState<Record<string, unknown> | null>(null);
  const ids = { dataset: useId(), file: useId() };

  const upload = (e: FormEvent<HTMLFormElement>) => {
    e.preventDefault();
    const formEl = e.currentTarget;
    const form = new FormData(formEl); // Felder „dataset“ und „file“ wie von der API erwartet
    const file = form.get('file');
    if (!(file instanceof File) || file.size === 0) {
      setError('Bitte wählen Sie eine Datei aus.');
      return;
    }
    setBusy(true);
    setError(null);
    setResult(null);
    api
      .postForm<Record<string, unknown>>('/api/stats/upload', form)
      .then((res) => {
        setResult(res && typeof res === 'object' ? res : { ergebnis: String(res) });
        formEl.reset();
        overview.reload();
      })
      .catch((err: unknown) => setError(errorMessage(err)))
      .finally(() => setBusy(false));
  };

  return (
    <Card title="Amtliche Statistik: Datenstände und Import" subtitle="Berichtszeitraum, Revision und Abrufdatum jedes importierten Datenstands">
      <Async state={overview} compact loadingLabel="Datenstände werden geladen …">
        {(data) => {
          const names = new Map(data.datasets.map((d) => [d.key, d]));
          return (
            <div className="stack">
              {data.releases.length === 0 ? (
                <EmptyState compact title="Noch kein Datenstand importiert" icon="table">
                  {data.datasets.length === 0
                    ? 'Es sind noch keine Statistik-Datensätze angelegt. Sie werden mit den Stammdaten des Statistikmoduls eingerichtet.'
                    : 'Die Datensätze sind angelegt, aber es wurde noch keine Datei importiert.'}
                </EmptyState>
              ) : (
                <TableWrap label="Importierte Datenstände">
                  <table className="table table--compact">
                    <thead>
                      <tr>
                        <th scope="col">Datensatz</th>
                        <th scope="col">Berichtszeitraum</th>
                        <th scope="col">Revision</th>
                        <th scope="col">Alter</th>
                        <th scope="col">Veröffentlicht</th>
                        <th scope="col">Abgerufen</th>
                        <th scope="col">Import</th>
                        <th scope="col" className="col-num">
                          Zeilen
                        </th>
                        <th scope="col">Datei</th>
                      </tr>
                    </thead>
                    <tbody>
                      {data.releases.map((r) => (
                        <tr key={r.id}>
                          <th scope="row">
                            {names.get(r.dataset_key)?.name ?? r.dataset_key}
                            <span className="table__sub">{names.get(r.dataset_key)?.publisher}</span>
                          </th>
                          <td className="nowrap">
                            {r.period_key}
                            <span className="table__sub">Stand {fmtDate(r.period_end)}</span>
                          </td>
                          <td>
                            {r.revision} {r.is_current ? <Badge tone="good">aktuell</Badge> : <Badge tone="muted">ersetzt</Badge>}
                          </td>
                          <td>{fmtAgeDays(r.age_days)}</td>
                          <td className="nowrap">{r.published_on ? fmtDate(r.published_on) : <span className="unknown">unbekannt</span>}</td>
                          <td className="nowrap">{fmtDateTime(r.retrieved_at)}</td>
                          <td>{r.import_method === 'manual' ? 'manuell' : 'automatisch'}</td>
                          <td className="col-num">{fmtInt(r.row_count)}</td>
                          <td className="col-wrap">
                            {r.file_name ?? <span className="muted">–</span>}
                            <span className="table__sub mono" title="SHA-256-Prüfsumme der Quelldatei">
                              {r.file_sha256.slice(0, 16)}…
                            </span>
                            {r.notes ? <span className="table__sub">{r.notes}</span> : null}
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </TableWrap>
              )}
              <p className="field__hint">{data.note}</p>

              {data.datasets.length > 0 ? (
                <details className="disclosure">
                  <summary>Datensätze, Lizenzen und Quellenangaben ({data.datasets.length})</summary>
                  <ul className="plain-list dataset-list">
                    {data.datasets.map((d) => (
                      <li key={d.key}>
                        <strong>{d.name}</strong> · {d.publisher}
                        <span className="table__sub">
                          {d.attribution ?? 'keine Quellenangabe hinterlegt'} · Lizenz: {d.licence ?? 'unbekannt'} · Erscheinungsweise: {UPDATE_CYCLE_LABELS[d.update_cycle ?? ''] ?? 'unbekannt'}
                        </span>
                        <ExternalLink href={d.landing_url}>Seite des Herausgebers</ExternalLink>
                      </li>
                    ))}
                  </ul>
                </details>
              ) : null}

              {isAdmin ? (
                <form className="form upload-form" onSubmit={upload}>
                  <h3 className="subhead">Datei manuell importieren</h3>
                  <p className="field__hint">
                    Ausweichweg, wenn eine Statistik nicht automatisch abgerufen werden darf oder kann. Die Datei wird geprüft; eine geänderte Datei für denselben
                    Berichtszeitraum wird als neue Revision gespeichert, die bisherige bleibt erhalten.
                  </p>
                  <div className="form-grid">
                    <div className="field">
                      <label className="field__label" htmlFor={ids.dataset}>
                        Datensatz
                      </label>
                      {data.datasets.length > 0 ? (
                        <select id={ids.dataset} className="select" name="dataset" required>
                          {data.datasets.map((d) => (
                            <option key={d.key} value={d.key}>
                              {d.name}
                            </option>
                          ))}
                        </select>
                      ) : (
                        <input id={ids.dataset} className="input mono" name="dataset" required placeholder="Schlüssel des Datensatzes" />
                      )}
                    </div>
                    <div className="field">
                      <label className="field__label" htmlFor={ids.file}>
                        Datei (.xlsx, .csv, .zip oder .gpkg)
                      </label>
                      <input id={ids.file} className="input input--file" name="file" type="file" required accept=".xlsx,.csv,.zip,.gpkg" />
                    </div>
                    <Button type="submit" variant="primary" icon="upload" busy={busy} data-admin-action>
                      Importieren
                    </Button>
                  </div>
                  {error ? (
                    <p className="form-error" role="alert">
                      {error}
                    </p>
                  ) : null}
                  {result ? (
                    <Alert tone="good" title="Import abgeschlossen" role="status">
                      <dl className="kv kv--wrap">
                        {Object.entries(result).map(([k, v]) => (
                          <div key={k}>
                            <dt>{k}</dt>
                            <dd>{typeof v === 'object' ? JSON.stringify(v) : String(v)}</dd>
                          </div>
                        ))}
                      </dl>
                    </Alert>
                  ) : null}
                </form>
              ) : null}
            </div>
          );
        }}
      </Async>
    </Card>
  );
}

export function SystemTab() {
  const { isAdmin } = useAuth();
  const toast = useToast();
  const status = useFetch<SystemStatus>('/api/system/status');
  const [busy, setBusy] = useState<string | null>(null);

  const trigger = (kind: string) => {
    setBusy(`job-${kind}`);
    api
      .post<{ queued: boolean; job_id: number | null }>(`/api/system/jobs/${kind}`)
      .then((res) => {
        if (res.queued) toast.success(`Auftrag „${JOB_KIND_LABELS[kind] ?? kind}“ eingereiht (Nr. ${res.job_id}).`);
        else toast.info(`Ein Auftrag „${JOB_KIND_LABELS[kind] ?? kind}“ läuft bereits oder ist eingereiht.`);
        status.reload();
      })
      .catch((err: unknown) => toast.error(errorMessage(err)))
      .finally(() => setBusy(null));
  };

  const resolve = (id: number) => {
    setBusy(`warn-${id}`);
    api
      .post(`/api/system/warnings/${id}/resolve`)
      .then(() => {
        toast.success('Warnung als erledigt markiert.');
        status.reload();
      })
      .catch((err: unknown) => toast.error(errorMessage(err)))
      .finally(() => setBusy(null));
  };

  return (
    <div className="stack stack--loose">
      <Async state={status} loadingLabel="Systemzustand wird geladen …">
        {(data) => (
          <div className="stack stack--loose">
            <Card
              title={`Warnungen (${data.warnings.length})`}
              subtitle="veraltete Quellen, Blockaden, ungewöhnlich große Bestandsänderungen"
              actions={<Button size="sm" variant="ghost" icon="refresh" onClick={status.reload}>Aktualisieren</Button>}
            >
              {data.warnings.length === 0 ? (
                <EmptyState compact title="Keine offenen Warnungen" icon="check" />
              ) : (
                <ul className="plain-list">
                  {data.warnings.map((w) => (
                    <li key={w.id} className="warning-row">
                      <Alert tone="warn" compact title={w.message}>
                        {w.kind} · gemeldet am {fmtDateTime(w.created_at)}
                      </Alert>
                      {isAdmin ? (
                        <Button size="sm" data-admin-action busy={busy === `warn-${w.id}`} disabled={busy !== null} onClick={() => resolve(w.id)}>
                          Als erledigt markieren
                        </Button>
                      ) : null}
                    </li>
                  ))}
                </ul>
              )}
            </Card>

            <div className="grid grid--3">
              <Card title="Installation">
                <dl className="kv">
                  <div>
                    <dt>Version</dt>
                    <dd>{data.version}</dd>
                  </div>
                  <div>
                    <dt>Umgebung</dt>
                    <dd>{data.env}</dd>
                  </div>
                  <div>
                    <dt>Zeitzone</dt>
                    <dd>{data.timezone}</dd>
                  </div>
                  <div>
                    <dt>Täglicher Scan</dt>
                    <dd>{data.scan_time} Uhr</dd>
                  </div>
                  {Object.entries(data.settings).map(([k, v]) => (
                    <div key={k}>
                      <dt>{SETTING_LABELS[k] ?? k}</dt>
                      <dd>{fmtInt(v)}</dd>
                    </div>
                  ))}
                </dl>
              </Card>
              <Card title="Datenbestand">
                <dl className="kv">
                  {Object.entries(data.counts).map(([k, v]) => (
                    <div key={k}>
                      <dt>{COUNT_LABELS[k] ?? k}</dt>
                      <dd>{fmtInt(v)}</dd>
                    </div>
                  ))}
                </dl>
              </Card>
              <Card title="Hintergrundaufträge">
                {Object.keys(data.jobs).length === 0 ? (
                  <p className="muted">Noch kein Auftrag ausgeführt.</p>
                ) : (
                  <dl className="kv">
                    {Object.entries(data.jobs).map(([k, v]) => (
                      <div key={k}>
                        <dt>{JOB_STATUS_LABELS[k] ?? k}</dt>
                        <dd>{fmtInt(v)}</dd>
                      </div>
                    ))}
                  </dl>
                )}
                {isAdmin ? (
                  <div className="stack stack--tight">
                    <h3 className="subhead">Auftrag jetzt einreihen</h3>
                    {JOB_KINDS.map((k) => (
                      <Button key={k} size="sm" data-admin-action busy={busy === `job-${k}`} disabled={busy !== null} onClick={() => trigger(k)} className="btn--block">
                        {JOB_KIND_LABELS[k]}
                      </Button>
                    ))}
                  </div>
                ) : null}
              </Card>
            </div>

            <Card title="Letzte Aufträge" subtitle="die jüngsten 25 Hintergrundaufträge" flush>
              {data.recent_jobs.length === 0 ? (
                <EmptyState compact title="Noch keine Aufträge" icon="clock">
                  Aufträge entstehen durch den Zeitplan oder werden manuell eingereiht.
                </EmptyState>
              ) : (
                <TableWrap label="Letzte Hintergrundaufträge">
                  <table className="table table--compact">
                    <thead>
                      <tr>
                        <th scope="col">Nr.</th>
                        <th scope="col">Art</th>
                        <th scope="col">Status</th>
                        <th scope="col" className="col-num">
                          Versuche
                        </th>
                        <th scope="col">Angelegt</th>
                        <th scope="col">Beendet</th>
                        <th scope="col">Ergebnis oder Fehler</th>
                      </tr>
                    </thead>
                    <tbody>
                      {data.recent_jobs.map((j) => (
                        <tr key={j.id}>
                          <th scope="row">{j.id}</th>
                          <td>{JOB_KIND_LABELS[j.kind] ?? j.kind}</td>
                          <td>
                            <Badge tone={JOB_STATUS_TONE[j.status] ?? 'neutral'}>{JOB_STATUS_LABELS[j.status] ?? j.status}</Badge>
                          </td>
                          <td className="col-num">{j.attempts}</td>
                          <td className="nowrap">{fmtDateTime(j.created_at)}</td>
                          <td className="nowrap">{j.finished_at ? fmtDateTime(j.finished_at) : <span className="muted">–</span>}</td>
                          <td className="col-wrap">{j.last_error ? <span className="error-text">{j.last_error}</span> : j.result ? <code className="params">{JSON.stringify(j.result)}</code> : <span className="muted">–</span>}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </TableWrap>
              )}
            </Card>
          </div>
        )}
      </Async>

      <MergeCandidatesCard />
      <StatisticsCard />
      {isAdmin ? (
        <UsersCard />
      ) : (
        <Card title="Benutzerverwaltung">
          <p className="muted">Die Benutzerverwaltung ist der Administration vorbehalten. Sie sind mit Lesezugriff angemeldet.</p>
        </Card>
      )}
    </div>
  );
}
