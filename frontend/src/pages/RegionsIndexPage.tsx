import { useId, useMemo, useState } from 'react';
import { Link } from 'react-router';
import type { RegionListItem } from '../api/types';
import { Async, Card, EmptyState, PageHeader } from '../components/ui';
import { fmtDate, fmtInt } from '../lib/format';
import { useFetch } from '../lib/useFetch';

export default function RegionsIndexPage() {
  const states = useFetch<RegionListItem[]>('/api/regions?level=state', { cache: true });
  const districts = useFetch<RegionListItem[]>('/api/regions?level=district', { cache: true });
  const [term, setTerm] = useState('');
  const searchId = useId();

  const stateNames = useMemo(() => new Map((states.data ?? []).map((s) => [s.key, s.name])), [states.data]);
  const grouped = useMemo(() => {
    const t = term.trim().toLocaleLowerCase('de');
    const groups = new Map<string, RegionListItem[]>();
    for (const d of districts.data ?? []) {
      if (t && !d.name.toLocaleLowerCase('de').includes(t) && !d.key.startsWith(t)) continue;
      const parent = d.parent_key ?? d.key.slice(0, 2);
      groups.set(parent, [...(groups.get(parent) ?? []), d]);
    }
    return [...groups.entries()].sort((a, b) => (stateNames.get(a[0]) ?? a[0]).localeCompare(stateNames.get(b[0]) ?? b[0], 'de'));
  }, [districts.data, term, stateNames]);
  const shown = grouped.reduce((n, [, list]) => n + list.length, 0);

  return (
    <div className="page">
      <PageHeader title="Regionen" lead="Länder sowie Kreise und kreisfreie Städte. Die Detailseite zeigt Anzeigenkennzahlen, Zeitreihe, häufigste Berufe und amtliche Kontextstatistik." />

      <Card title="Bundesländer">
        <Async state={states} compact loadingLabel="Länder werden geladen …">
          {(data) =>
            data.length === 0 ? (
              <EmptyState compact title="Noch keine Länder vorhanden" icon="region">
                Die Gebietsdaten (Länder und Kreise) sind noch nicht importiert.
              </EmptyState>
            ) : (
              <ul className="region-grid">
                {data.map((s) => (
                  <li key={s.key}>
                    <Link className="region-link" to={`/regionen/${s.key}`}>
                      {s.name}
                    </Link>
                  </li>
                ))}
              </ul>
            )
          }
        </Async>
      </Card>

      <Card
        title="Kreise und kreisfreie Städte"
        subtitle={districts.data && districts.data.length > 0 ? `${fmtInt(shown)} von ${fmtInt(districts.data.length)} · Gebietsstand ${fmtDate(districts.data[0]?.gebietsstand)}` : undefined}
        actions={
          <div className="field field--inline">
            <label className="visually-hidden" htmlFor={searchId}>
              Kreis suchen
            </label>
            <input id={searchId} className="input" type="search" placeholder="Name oder Kreisschlüssel" value={term} onChange={(e) => setTerm(e.target.value)} />
          </div>
        }
      >
        <Async state={districts} compact loadingLabel="Kreise werden geladen …">
          {(data) =>
            data.length === 0 ? (
              <EmptyState title="Kreisgrenzen noch nicht importiert" icon="map">
                Sobald die amtlichen Verwaltungsgrenzen (VG250) importiert sind, stehen hier alle Kreise und kreisfreien Städte zur Auswahl. Bis dahin
                können Anzeigen keinem Kreis zugeordnet werden.
              </EmptyState>
            ) : shown === 0 ? (
              <EmptyState compact title={`Kein Kreis passt zu „${term}“`} icon="search" />
            ) : (
              <div className="stack">
                {grouped.map(([parent, list]) => (
                  <section key={parent} aria-label={stateNames.get(parent) ?? `Land ${parent}`}>
                    <h3 className="subhead">{stateNames.get(parent) ?? `Land ${parent}`}</h3>
                    <ul className="region-grid">
                      {list.map((d) => (
                        <li key={d.key}>
                          <Link className="region-link" to={`/regionen/${d.key}`}>
                            {d.name}
                            <span className="region-link__meta">
                              {d.type_label ?? 'Kreis'} · {d.key}
                            </span>
                          </Link>
                        </li>
                      ))}
                    </ul>
                  </section>
                ))}
              </div>
            )
          }
        </Async>
      </Card>
    </div>
  );
}
