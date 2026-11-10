import { type FormEvent, useId, useState } from 'react';
import { Link, useNavigate } from 'react-router';
import { FramingNote } from '../components/domain';
import { Button, Card, EmptyState, PageHeader } from '../components/ui';
import { readRecent } from '../lib/recent';

export default function PostingsIndexPage() {
  const navigate = useNavigate();
  const [value, setValue] = useState('');
  const inputId = useId();
  const recent = readRecent();
  const valid = /^\d{1,9}$/.test(value.trim()) && Number(value) > 0;

  const onSubmit = (e: FormEvent) => {
    e.preventDefault();
    if (valid) void navigate(`/anzeigen/${Number(value.trim())}`);
  };

  return (
    <div className="page">
      <PageHeader
        title="Anzeigen"
        lead="Die Detailansicht einer Anzeige zeigt Kerndaten, Arbeitsorte, erkannte Merkmale, alle Quellen, Beobachtungszeiträume und den Änderungsverlauf."
        actions={
          <Link className="btn btn--primary" to="/suche">
            Zur Stellensuche
          </Link>
        }
      />
      <div className="grid grid--2">
        <Card title="Anzeige direkt öffnen" subtitle="über die Nummer der zusammengeführten Anzeige (z. B. aus einem CSV-Export)">
          <form className="row row--top" onSubmit={onSubmit}>
            <div className="field">
              <label className="field__label" htmlFor={inputId}>
                Anzeigennummer
              </label>
              <input id={inputId} className="input" inputMode="numeric" pattern="[0-9]*" value={value} onChange={(e) => setValue(e.target.value)} placeholder="z. B. 1024" />
            </div>
            <Button type="submit" variant="primary" disabled={!valid} className="align-end">
              Öffnen
            </Button>
          </form>
          <p className="field__hint">Anzeigen finden Sie am einfachsten über die Stellensuche oder über einen Kreis auf der Karte.</p>
        </Card>
        <Card title="Zuletzt geöffnet" subtitle="in diesem Browser-Tab">
          {recent.length === 0 ? (
            <EmptyState compact title="Noch keine Anzeige geöffnet" icon="posting">
              Hier erscheinen die Anzeigen, die Sie in dieser Sitzung angesehen haben.
            </EmptyState>
          ) : (
            <ul className="plain-list">
              {recent.map((p) => (
                <li key={p.id}>
                  <Link to={`/anzeigen/${p.id}`}>{p.title}</Link>
                  <span className="table__sub">
                    {p.employer ?? 'Arbeitgeber unbekannt'} · Nr. {p.id}
                  </span>
                </li>
              ))}
            </ul>
          )}
        </Card>
      </div>
      <FramingNote />
    </div>
  );
}
