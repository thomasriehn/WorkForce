import { type FormEvent, useEffect, useId, useState } from 'react';
import { api, errorMessage } from '../../api/client';
import type { RunStartResponse, Source, SourceScope } from '../../api/types';
import { Dialog } from '../../components/Dialog';
import { useToast } from '../../components/Toast';
import { Alert, Button } from '../../components/ui';
import { CONFIG_STATUS_LABELS, RUN_STATUS_LABELS, SCOPE_MODE_LABELS } from '../../lib/labels';

interface BaseProps {
  source: Source;
  open: boolean;
  onClose: () => void;
  onDone: () => void;
}

function FormError({ error }: { error: string | null }) {
  return error ? (
    <p className="form-error" role="alert">
      {error}
    </p>
  ) : null;
}

/** Freigabe einer Quelle: nur mit dokumentiertem Freigabevermerk; Prüfmeldungen der API werden angezeigt. */
export function ActivateDialog({ source, open, onClose, onDone }: BaseProps) {
  const toast = useToast();
  const [basis, setBasis] = useState('');
  const [permission, setPermission] = useState('');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const basisId = useId();
  const permId = useId();
  const needsPermission = source.config_status === 'permission_required';

  useEffect(() => {
    if (open) {
      setBasis('');
      setPermission('');
      setError(null);
    }
  }, [open]);

  const submit = (e: FormEvent) => {
    e.preventDefault();
    setBusy(true);
    setError(null);
    api
      .post(`/api/sources/${source.id}/activate`, { basis, permission_reference: permission.trim() || null })
      .then(() => {
        toast.success(`„${source.name}“ ist freigegeben und wird beim nächsten Tageslauf abgerufen.`);
        onDone();
        onClose();
      })
      .catch((err: unknown) => setError(errorMessage(err)))
      .finally(() => setBusy(false));
  };

  return (
    <Dialog
      open={open}
      onClose={onClose}
      title={`Quelle freigeben: ${source.name}`}
      size="lg"
      footer={
        <>
          <Button variant="ghost" onClick={onClose} disabled={busy}>
            Abbrechen
          </Button>
          <Button variant="primary" type="submit" form="activate-form" busy={busy}>
            Freigabe dokumentieren und aktivieren
          </Button>
        </>
      }
    >
      <form id="activate-form" className="form" onSubmit={submit}>
        <Alert tone={needsPermission ? 'warn' : 'info'} title={needsPermission ? 'Diese Quelle erfordert eine Erlaubnis des Betreibers' : 'Die Freigabe ist eine Entscheidung des Betreibers dieser Installation'}>
          {source.status_reason ?? 'Bitte prüfen Sie robots.txt und Nutzungsbedingungen der Quelle, bevor Sie sie freigeben.'}
        </Alert>
        <div className="field">
          <label className="field__label" htmlFor={basisId}>
            Freigabevermerk
          </label>
          <textarea id={basisId} className="textarea" required value={basis} onChange={(e) => setBasis(e.target.value)} placeholder="Was wurde geprüft, und worauf stützt sich die Freigabe? (z. B. robots.txt und Nutzungsbedingungen am … geprüft; Abruf des RSS-Feeds ist ausdrücklich vorgesehen)" />
          <p className="field__hint">Mindestens 20 Zeichen. Der Vermerk wird mit Zeitpunkt und Benutzername am Registereintrag gespeichert ({basis.trim().length} Zeichen).</p>
        </div>
        {needsPermission ? (
          <div className="field">
            <label className="field__label" htmlFor={permId}>
              Nachweis der Erlaubnis
            </label>
            <input id={permId} className="input" value={permission} onChange={(e) => setPermission(e.target.value)} placeholder="z. B. schriftliche Zustimmung vom 12.11.2026, Absender, Aktenzeichen" />
            <p className="field__hint">Erforderlich, weil die Bedingungen der Quelle eine vorherige Zustimmung verlangen.</p>
          </div>
        ) : null}
        <FormError error={error} />
      </form>
    </Dialog>
  );
}

export function DeactivateDialog({ source, open, onClose, onDone }: BaseProps) {
  const toast = useToast();
  const [reason, setReason] = useState('');
  const [status, setStatus] = useState('disabled');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const reasonId = useId();
  const statusId = useId();

  useEffect(() => {
    if (open) {
      setReason('');
      setStatus('disabled');
      setError(null);
    }
  }, [open]);

  const submit = (e: FormEvent) => {
    e.preventDefault();
    setBusy(true);
    setError(null);
    api
      .post(`/api/sources/${source.id}/deactivate`, { reason, status })
      .then(() => {
        toast.success(`„${source.name}“ wird nicht mehr abgerufen.`);
        onDone();
        onClose();
      })
      .catch((err: unknown) => setError(errorMessage(err)))
      .finally(() => setBusy(false));
  };

  return (
    <Dialog
      open={open}
      onClose={onClose}
      title={`Quelle deaktivieren: ${source.name}`}
      footer={
        <>
          <Button variant="ghost" onClick={onClose} disabled={busy}>
            Abbrechen
          </Button>
          <Button variant="danger" type="submit" form="deactivate-form" busy={busy}>
            Deaktivieren
          </Button>
        </>
      }
    >
      <form id="deactivate-form" className="form" onSubmit={submit}>
        <p>
          Die Quelle wird ab sofort nicht mehr abgerufen. Bereits erfasste Anzeigen und ihre Historie bleiben erhalten; ohne weitere Scans gelten sie nach einiger Zeit
          als „unbekannt/veraltet“ – nicht als entfernt.
        </p>
        <div className="field">
          <label className="field__label" htmlFor={reasonId}>
            Grund der Deaktivierung
          </label>
          <textarea id={reasonId} className="textarea" required value={reason} onChange={(e) => setReason(e.target.value)} placeholder="z. B. Nutzungsbedingungen geändert, Betreiber hat widersprochen, dauerhafte Blockade" />
        </div>
        <div className="field">
          <label className="field__label" htmlFor={statusId}>
            Neuer Konfigurationsstatus
          </label>
          <select id={statusId} className="select" value={status} onChange={(e) => setStatus(e.target.value)}>
            <option value="disabled">{CONFIG_STATUS_LABELS.disabled}</option>
            <option value="permission_required">{CONFIG_STATUS_LABELS.permission_required}</option>
            <option value="candidate">{CONFIG_STATUS_LABELS.candidate}</option>
          </select>
        </div>
        <FormError error={error} />
      </form>
    </Dialog>
  );
}

/** Manueller Lauf oder begrenzter Testlauf. */
export function RunDialog({ source, open, onClose, onDone, test }: BaseProps & { test: boolean }) {
  const [scopeKey, setScopeKey] = useState('');
  const [pageLimit, setPageLimit] = useState('2');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [result, setResult] = useState<RunStartResponse | null>(null);
  const scopeId = useId();
  const limitId = useId();
  const scopes = source.scopes.filter((s) => s.is_active);

  useEffect(() => {
    if (open) {
      setScopeKey('');
      setPageLimit('2');
      setError(null);
      setResult(null);
    }
  }, [open]);

  const submit = (e: FormEvent) => {
    e.preventDefault();
    setBusy(true);
    setError(null);
    api
      .post<RunStartResponse>(`/api/sources/${source.id}/runs`, { scope_key: scopeKey || null, test, page_limit: test && pageLimit ? Number(pageLimit) : null })
      .then((res) => {
        setResult(res);
        onDone();
      })
      .catch((err: unknown) => setError(errorMessage(err)))
      .finally(() => setBusy(false));
  };

  return (
    <Dialog
      open={open}
      onClose={onClose}
      title={test ? `Begrenzter Testlauf: ${source.name}` : `Manuellen Lauf starten: ${source.name}`}
      footer={
        result ? (
          <Button variant="primary" onClick={onClose}>
            Schließen
          </Button>
        ) : (
          <>
            <Button variant="ghost" onClick={onClose} disabled={busy}>
              Abbrechen
            </Button>
            <Button variant="primary" type="submit" form="run-form" busy={busy} icon="play">
              {test ? 'Testlauf starten' : 'Lauf starten'}
            </Button>
          </>
        )
      }
    >
      {result ? (
        <div className="stack" role="status">
          <Alert tone="good" title="Auftrag angenommen">
            Der Lauf wird vom Hintergrunddienst ausgeführt. Den Fortschritt sehen Sie im Laufprotokoll.
          </Alert>
          <ul className="plain-list">
            {result.runs.map((r) => (
              <li key={r.run_id}>
                Lauf Nr. {r.run_id} · Suchbereich „{r.scope}“ · {r.created ? 'neu angelegt' : 'bereits vorhanden'} · Status: {RUN_STATUS_LABELS[r.status] ?? r.status}
                {r.note ? <span className="table__sub">{r.note}</span> : null}
              </li>
            ))}
          </ul>
        </div>
      ) : (
        <form id="run-form" className="form" onSubmit={submit}>
          <p>
            {test
              ? 'Ein Testlauf ruft nur wenige Seiten ab und prüft, ob der Adapter die Quelle lesen kann. Testläufe zählen nicht als Scan und verändern keinen Anzeigenstatus.'
              : 'Je Suchbereich und Tag gibt es nur einen logischen Lauf. Existiert für heute bereits einer, wird kein zweiter angelegt.'}
          </p>
          <div className="field">
            <label className="field__label" htmlFor={scopeId}>
              Suchbereich
            </label>
            <select id={scopeId} className="select" value={scopeKey} onChange={(e) => setScopeKey(e.target.value)}>
              <option value="">alle aktiven Suchbereiche ({scopes.length})</option>
              {scopes.map((s) => (
                <option key={s.id} value={s.key}>
                  {s.name} ({s.key}, Version {s.version})
                </option>
              ))}
            </select>
          </div>
          {test ? (
            <div className="field field--narrow">
              <label className="field__label" htmlFor={limitId}>
                Seitenlimit
              </label>
              <input id={limitId} className="input" type="number" min={1} max={500} value={pageLimit} onChange={(e) => setPageLimit(e.target.value)} />
            </div>
          ) : null}
          <FormError error={error} />
        </form>
      )}
    </Dialog>
  );
}

/** Neue Version eines Suchbereichs: geänderte Parameter erzeugen eine neue Version, die alte wird stillgelegt. */
export function ScopeDialog({ source, open, onClose, onDone, template }: BaseProps & { template: SourceScope | null }) {
  const toast = useToast();
  const [key, setKey] = useState('');
  const [name, setName] = useState('');
  const [mode, setMode] = useState('full');
  const [pageBudget, setPageBudget] = useState('');
  const [note, setNote] = useState('');
  const [params, setParams] = useState('{}');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const ids = { key: useId(), name: useId(), mode: useId(), budget: useId(), note: useId(), params: useId() };

  useEffect(() => {
    if (!open) return;
    setKey(template?.key ?? '');
    setName(template?.name ?? '');
    setMode(template?.mode ?? 'full');
    setPageBudget(template?.page_budget ? String(template.page_budget) : '');
    setNote('');
    setParams(JSON.stringify(template?.params ?? {}, null, 2));
    setError(null);
  }, [open, template]);

  const submit = (e: FormEvent) => {
    e.preventDefault();
    let parsed: unknown;
    try {
      parsed = JSON.parse(params || '{}');
    } catch {
      setError('Die Parameter sind kein gültiges JSON.');
      return;
    }
    if (!parsed || typeof parsed !== 'object' || Array.isArray(parsed)) {
      setError('Die Parameter müssen ein JSON-Objekt sein, zum Beispiel {"feed_url": "https://…"}.');
      return;
    }
    setBusy(true);
    setError(null);
    api
      .post(`/api/sources/${source.id}/scopes`, { key: key.trim(), name: name.trim(), params: parsed, mode, page_budget: pageBudget ? Number(pageBudget) : null, note: note.trim() || null })
      .then(() => {
        toast.success(`Suchbereich „${key.trim()}“ gespeichert.`);
        onDone();
        onClose();
      })
      .catch((err: unknown) => setError(errorMessage(err)))
      .finally(() => setBusy(false));
  };

  return (
    <Dialog
      open={open}
      onClose={onClose}
      size="lg"
      title={template ? `Neue Version des Suchbereichs „${template.key}“` : 'Suchbereich anlegen'}
      footer={
        <>
          <Button variant="ghost" onClick={onClose} disabled={busy}>
            Abbrechen
          </Button>
          <Button variant="primary" type="submit" form="scope-form" busy={busy}>
            {template ? 'Neue Version speichern' : 'Suchbereich anlegen'}
          </Button>
        </>
      }
    >
      <form id="scope-form" className="form" onSubmit={submit}>
        <Alert tone="warn" title="Der erste Lauf einer neuen Version ist eine Bestandsaufnahme">
          Geänderte Parameter, ein anderer Modus oder ein anderes Seitenbudget erzeugen eine neue Version; die bisherige wird stillgelegt. Alles, was der erste Lauf der
          neuen Version findet, gilt als „bei Bestandsaufnahme erfasst“ und nicht als neu veröffentlicht. Zeitvergleiche über diesen Wechsel sind eingeschränkt und
          werden entsprechend vermerkt.
        </Alert>
        <div className="form-grid">
          <div className="field">
            <label className="field__label" htmlFor={ids.key}>
              Schlüssel
            </label>
            <input id={ids.key} className="input mono" required pattern="[a-z0-9_\-]{1,80}" value={key} readOnly={template !== null} onChange={(e) => setKey(e.target.value)} placeholder="z. B. alle" />
            <p className="field__hint">Kleinbuchstaben, Ziffern, „_“ und „-“. Gleicher Schlüssel = neue Version.</p>
          </div>
          <div className="field">
            <label className="field__label" htmlFor={ids.name}>
              Bezeichnung
            </label>
            <input id={ids.name} className="input" required maxLength={200} value={name} onChange={(e) => setName(e.target.value)} />
          </div>
          <div className="field">
            <label className="field__label" htmlFor={ids.mode}>
              Modus
            </label>
            <select id={ids.mode} className="select" value={mode} onChange={(e) => setMode(e.target.value)}>
              <option value="full">{SCOPE_MODE_LABELS.full}</option>
              <option value="new_only">{SCOPE_MODE_LABELS.new_only}</option>
            </select>
          </div>
          <div className="field">
            <label className="field__label" htmlFor={ids.budget}>
              Seitenbudget (optional)
            </label>
            <input id={ids.budget} className="input" type="number" min={1} max={5000} value={pageBudget} onChange={(e) => setPageBudget(e.target.value)} placeholder="Budget der Quelle" />
          </div>
        </div>
        <div className="field">
          <label className="field__label" htmlFor={ids.params}>
            Parameter (JSON-Objekt)
          </label>
          <textarea id={ids.params} className="textarea textarea--mono" rows={6} spellCheck={false} value={params} onChange={(e) => setParams(e.target.value)} />
        </div>
        <div className="field">
          <label className="field__label" htmlFor={ids.note}>
            Vermerk (optional)
          </label>
          <input id={ids.note} className="input" value={note} onChange={(e) => setNote(e.target.value)} placeholder="Warum wurde der Suchbereich geändert?" />
        </div>
        <FormError error={error} />
      </form>
    </Dialog>
  );
}

const EMPTY_CAREER_FORM = { key: '', name: '', domain: '', sitemap_url: '', url_pattern: '', id_pattern: '', terms_url: '', legal_notes: '' };

/** Öffentliche Karriereseite eines Arbeitgebers als eigene Quelle vormerken (Freigabe erfolgt gesondert). */
export function CareerPageDialog({ open, onClose, onDone }: { open: boolean; onClose: () => void; onDone: (source: Source) => void }) {
  const toast = useToast();
  const [form, setForm] = useState(EMPTY_CAREER_FORM);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const baseId = useId();
  const set = (field: keyof typeof EMPTY_CAREER_FORM) => (e: { target: { value: string } }) => setForm((f) => ({ ...f, [field]: e.target.value }));

  useEffect(() => {
    if (open) {
      setForm(EMPTY_CAREER_FORM);
      setError(null);
    }
  }, [open]);

  const submit = (e: FormEvent) => {
    e.preventDefault();
    setBusy(true);
    setError(null);
    api
      .post<Source>('/api/sources/career-page', { ...form, id_pattern: form.id_pattern.trim() || null, terms_url: form.terms_url.trim() || null })
      .then((src) => {
        toast.success(`„${src.name}“ ist vorgemerkt. Die Freigabe erfolgt gesondert.`);
        onDone(src);
        onClose();
      })
      .catch((err: unknown) => setError(errorMessage(err)))
      .finally(() => setBusy(false));
  };

  const field = (name: keyof typeof EMPTY_CAREER_FORM, label: string, opts: { hint?: string; placeholder?: string; required?: boolean; mono?: boolean; pattern?: string } = {}) => (
    <div className="field">
      <label className="field__label" htmlFor={`${baseId}-${name}`}>
        {label}
      </label>
      <input id={`${baseId}-${name}`} className={opts.mono ? 'input mono' : 'input'} required={opts.required} pattern={opts.pattern} value={form[name]} onChange={set(name)} placeholder={opts.placeholder} />
      {opts.hint ? <p className="field__hint">{opts.hint}</p> : null}
    </div>
  );

  return (
    <Dialog
      open={open}
      onClose={onClose}
      size="lg"
      title="Karriereseite eines Arbeitgebers vormerken"
      footer={
        <>
          <Button variant="ghost" onClick={onClose} disabled={busy}>
            Abbrechen
          </Button>
          <Button variant="primary" type="submit" form="career-form" busy={busy}>
            Vormerken
          </Button>
        </>
      }
    >
      <form id="career-form" className="form" onSubmit={submit}>
        <p>
          Die Quelle wird nur vorgemerkt. Abgerufen wird sie erst nach einer dokumentierten Freigabe – prüfen Sie vorher robots.txt und Nutzungsbedingungen der Domain.
        </p>
        <div className="form-grid">
          {field('key', 'Schlüssel', { required: true, mono: true, pattern: '[a-z0-9_]{3,60}', placeholder: 'z. B. stadt_musterstadt', hint: 'Kleinbuchstaben, Ziffern und „_“' })}
          {field('name', 'Name', { required: true, placeholder: 'z. B. Stadt Musterstadt – Karriere' })}
          {field('domain', 'Domain', { required: true, mono: true, placeholder: 'karriere.example.de' })}
          {field('terms_url', 'Nutzungsbedingungen (optional)', { placeholder: 'https://…' })}
        </div>
        {field('sitemap_url', 'Sitemap-URL', { required: true, mono: true, placeholder: 'https://karriere.example.de/sitemap.xml', hint: 'Muss auf der angegebenen Domain liegen.' })}
        <div className="form-grid">
          {field('url_pattern', 'Muster der Anzeigen-URLs (regulärer Ausdruck)', { required: true, mono: true, placeholder: '/stellen/\\d+' })}
          {field('id_pattern', 'Muster der Anzeigen-ID (optional)', { mono: true, placeholder: '/stellen/(\\d+)' })}
        </div>
        <div className="field">
          <label className="field__label" htmlFor={`${baseId}-legal`}>
            Prüfvermerk
          </label>
          <textarea id={`${baseId}-legal`} className="textarea" required minLength={20} value={form.legal_notes} onChange={set('legal_notes')} placeholder="Was sagen robots.txt, Impressum und Nutzungsbedingungen zu automatisierten Abrufen? (mindestens 20 Zeichen)" />
        </div>
        <FormError error={error} />
      </form>
    </Dialog>
  );
}
