import { useId } from 'react';
import { Link, useParams } from 'react-router';
import type { RegionContextRow, RegionDetail } from '../api/types';
import { TimeSeriesChart } from '../charts/TimeSeriesChart';
import { FramingNote, TotalsBox } from '../components/domain';
import { ExternalLink } from '../components/ExternalLink';
import { KindTabs } from '../components/postings';
import { Alert, Async, Card, EmptyState, PageHeader, StatTile, TableWrap } from '../components/ui';
import { ActiveFilters } from '../filters/FilterPanel';
import { serializeFilters, withQuery } from '../filters/model';
import { useFilters } from '../filters/useFilters';
import { fmtAgeDays, fmtDate, fmtInt, fmtNum } from '../lib/format';
import { KIND_GROUP_LABELS, METRIC_LABELS, VALUE_STATUS_LABELS } from '../lib/labels';
import { useMetaFilters } from '../lib/lookups';
import { useFetch } from '../lib/useFetch';

const DAY_OPTIONS = [30, 90, 180, 365];

function contextValue(row: RegionContextRow) {
  if (row.value !== null && (row.value_status === 'ok' || row.value_status === 'zero')) {
    return (
      <>
        <strong>{fmtNum(row.value, Number.isInteger(row.value) ? 0 : 2)}</strong> {row.unit}
        {row.value_status === 'zero' ? <span className="table__sub">echter Nullwert</span> : null}
      </>
    );
  }
  return (
    <span className="unknown">
      kein Wert – {VALUE_STATUS_LABELS[row.value_status] ?? row.value_status}
      {row.raw_value ? ` (Angabe der Quelle: „${row.raw_value}“)` : ''}
    </span>
  );
}

function RegionContent({ data, searchLink, kindLabel }: { data: RegionDetail; searchLink: string; kindLabel: string }) {
  const m = data.metrics;
  const isDistrict = data.level === 'district';
  return (
    <>
      {isDistrict && m ? (
        <section className="stack" aria-label="Kennzahlen des Kreises">
          <div className="grid grid--3">
            <StatTile
              tone="accent"
              label={METRIC_LABELS.weighted}
              value={fmtNum(m.weighted, 2)}
              hint="Anzeigen mit mehreren Arbeitsorten zählen je Kreis anteilig (1 geteilt durch die Zahl der Kreise) – nur wenn alle Arbeitsorte zugeordnet sind."
            />
            <StatTile label={METRIC_LABELS.distinct} value={fmtInt(m.distinct)} hint="Jede Anzeige mit mindestens einem Arbeitsort im Kreis zählt ganz. Nicht über Kreise addierbar." />
            <StatTile
              label={METRIC_LABELS.rate}
              value={m.rate_per_1000 === null ? <span className="unknown">keine Daten</span> : fmtNum(m.rate_per_1000, 3)}
              hint={
                m.population_15_65
                  ? `Nenner: ${fmtInt(m.population_15_65)} Einwohner von 15 bis unter 65 Jahren.`
                  : 'Es liegt kein Bevölkerungswert als Nenner vor – ohne Nenner wird kein Quotient gebildet.'
              }
            />
          </div>
          {m.low_count ? (
            <Alert tone="warn" compact title="Geringe Fallzahl">
              In diesem Kreis liegen nur wenige Anzeigen vor. Einzelne Anzeigen verändern die Werte stark; Anteile und Veränderungen sind wenig belastbar.
            </Alert>
          ) : null}
        </section>
      ) : null}

      <div className="grid grid--main-side">
        <Card title="Zeitreihe" subtitle={`${kindLabel} mit Arbeitsort in ${data.region.name}`}>
          <TimeSeriesChart series={data.timeseries} subject={data.region.name} />
        </Card>
        <Card title="Anzeigen mit Bezug zur Region" subtitle="jede zusammengeführte Anzeige einmal">
          <TotalsBox totals={data.totals} totalLabel={`${kindLabel} im beobachteten Bestand`} compact />
          <p className="field__hint">
            {isDistrict
              ? 'Die Gesamtzahl entspricht den unterschiedlichen Anzeigen mit Bezug zum Kreis.'
              : 'Für Länder werden die Anzeigen mit mindestens einem Arbeitsort im Land gezählt; die Kennzahlen je Kreis stehen auf der Karte.'}
          </p>
          <Link className="btn btn--sm" to={searchLink}>
            Diese Anzeigen in der Stellensuche
          </Link>
        </Card>
      </div>

      <div className="grid grid--2">
        <Card title="Häufigste Berufe" subtitle="nach Berufsklasse (KldB 2010) der Anzeigen">
          {data.facets.occupations.length === 0 ? (
            <EmptyState compact title="Keine klassifizierten Anzeigen" icon="posting">
              Für diese Region liegt keine Anzeige mit zugeordneter Berufsklasse vor.
            </EmptyState>
          ) : (
            <ol className="rank-list">
              {data.facets.occupations.map((o) => (
                <li key={o.kldb_code}>
                  <span>
                    {o.name ?? 'Bezeichnung unbekannt'} <span className="muted">({o.kldb_code})</span>
                  </span>
                  <span className="rank-list__count">{fmtInt(o.count)}</span>
                </li>
              ))}
            </ol>
          )}
          <p className="rank-list__rest">
            Ohne Berufsklasse (nicht zuordenbar): <strong>{fmtInt(data.facets.occupations_unclassified)}</strong> Anzeigen
          </p>
        </Card>
        <Card title="Häufigste Qualifikationen und Merkmale" subtitle="regelbasiert erkannt – kann irren">
          {data.facets.features.length === 0 ? (
            <EmptyState compact title="Keine erkannten Merkmale" icon="posting">
              In den Anzeigen dieser Region wurde kein Merkmal aus dem Wörterbuch erkannt.
            </EmptyState>
          ) : (
            <ol className="rank-list">
              {data.facets.features.map((x) => (
                <li key={x.key}>
                  <span>
                    {x.label} <span className="muted">· davon ausdrücklich verlangt {fmtInt(x.required)}</span>
                  </span>
                  <span className="rank-list__count">{fmtInt(x.count)}</span>
                </li>
              ))}
            </ol>
          )}
          {data.facets.employers.length > 0 ? (
            <>
              <h3 className="subhead">Häufigste Arbeitgeber</h3>
              <ol className="rank-list">
                {data.facets.employers.slice(0, 6).map((x) => (
                  <li key={x.name}>
                    <span>{x.name}</span>
                    <span className="rank-list__count">{fmtInt(x.count)}</span>
                  </li>
                ))}
              </ol>
            </>
          ) : null}
        </Card>
      </div>

      <Card title="Amtliche Kontextstatistik" subtitle="jeweils jüngster Datenstand – getrennt von den Anzeigenzahlen">
        <Alert tone="neutral" compact>
          {data.context_note}
        </Alert>
        {data.context.length === 0 ? (
          <EmptyState compact title="Keine Kontextdaten für diese Region" icon="table">
            Für diese Region sind noch keine amtlichen Statistiken importiert.
          </EmptyState>
        ) : (
          <TableWrap label="Amtliche Kontextstatistik der Region">
            <table className="table">
              <thead>
                <tr>
                  <th scope="col">Kennzahl</th>
                  <th scope="col">Wert</th>
                  <th scope="col">Berichtszeitraum</th>
                  <th scope="col">Revision</th>
                  <th scope="col">Alter</th>
                  <th scope="col">Herausgeber und Quellenangabe</th>
                </tr>
              </thead>
              <tbody>
                {data.context.map((row) => (
                  <tr key={`${row.indicator_key}|${row.dim_key}`}>
                    <th scope="row" className="col-wrap">
                      {row.name}
                      {row.dim_label ? ` – ${row.dim_label}` : ''}
                      {row.definition ? <span className="table__sub">{row.definition}</span> : null}
                      {row.population_group ? <span className="table__sub">Bezugsgruppe: {row.population_group}</span> : null}
                    </th>
                    <td className="nowrap">{contextValue(row)}</td>
                    <td>
                      {row.period_key}
                      <span className="table__sub">Stand {fmtDate(row.period_end)}</span>
                    </td>
                    <td>
                      {row.revision}
                      {row.revisions > 1 ? <span className="table__sub">{row.revisions} Fassungen gespeichert</span> : null}
                    </td>
                    <td>
                      {fmtInt(row.age_days)} Tage
                      <span className="table__sub">{fmtAgeDays(row.age_days)}</span>
                    </td>
                    <td className="col-wrap">
                      {row.publisher}
                      <span className="table__sub">{row.attribution ?? row.dataset}</span>
                      {row.licence ? <span className="table__sub">Lizenz: {row.licence}</span> : null}
                      <ExternalLink href={row.landing_url}>Seite des Herausgebers</ExternalLink>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </TableWrap>
        )}
        <p className="field__hint">Fehlende Werte werden in Worten ausgewiesen und nie als 0 dargestellt. Das Alter bezieht sich auf das Ende des Berichtszeitraums.</p>
      </Card>

      {data.region.source_note ? <p className="field__hint">Gebietsdaten: {data.region.source_note}</p> : null}
    </>
  );
}

export default function RegionDetailPage() {
  const { key = '' } = useParams();
  const ctl = useFilters();
  const meta = useMetaFilters();
  const daysId = useId();
  const daysParam = Number(ctl.getParam('days'));
  const days = DAY_OPTIONS.includes(daysParam) ? daysParam : 90;
  // Kreis- und Länderfilter setzt die API für diese Seite selbst; alle übrigen Filter gelten wie in Suche und Karte.
  const base = serializeFilters({ ...ctl.filters, kreise: [], states: [] }).toString();
  const validKey = /^\d{2}$|^\d{5}$/.test(key);
  const detail = useFetch<RegionDetail>(validKey ? withQuery(`/api/regions/${key}`, [base, `days=${days}`].filter(Boolean).join('&')) : null);
  const kindLabel = KIND_GROUP_LABELS[ctl.filters.kindGroup] ?? 'Anzeigen';
  const region = detail.data?.region;
  const searchLink = withQuery('/suche', [base, key.length === 5 ? `kreise=${key}` : `states=${key}`].filter(Boolean).join('&'));

  return (
    <div className="page">
      <PageHeader
        eyebrow={<Link to="/regionen">Regionen</Link>}
        title={region ? region.name : validKey ? `Region ${key}` : 'Region'}
        lead={
          region ? (
            <>
              {region.type_label ?? (detail.data?.level === 'state' ? 'Bundesland' : 'Kreis')}
              {region.state_name ? ` · ${region.state_name}` : ''} · Schlüssel {region.key} · Gebietsstand {fmtDate(region.gebietsstand)}
              {region.area_km2 ? ` · ${fmtNum(region.area_km2, 1)} km²` : ''}
            </>
          ) : undefined
        }
        actions={
          <div className="field field--inline">
            <label className="field__label" htmlFor={daysId}>
              Zeitreihe
            </label>
            <select id={daysId} className="select" value={days} onChange={(e) => ctl.setParams({ days: e.target.value === '90' ? null : e.target.value })}>
              {DAY_OPTIONS.map((d) => (
                <option key={d} value={d}>
                  letzte {d} Tage
                </option>
              ))}
            </select>
          </div>
        }
      />
      {!validKey ? (
        <Card>
          <EmptyState title="Ungültiger Regionalschlüssel" action={<Link className="btn" to="/regionen">Zur Regionenübersicht</Link>}>
            Erwartet wird ein zweistelliger Länderschlüssel oder ein fünfstelliger Kreisschlüssel, zum Beispiel 06 oder 06611.
          </EmptyState>
        </Card>
      ) : (
        <>
          <KindTabs value={ctl.filters.kindGroup} onChange={(kindGroup) => ctl.update({ kindGroup })} />
          <ActiveFilters ctl={ctl} meta={meta.data} />
          <Async state={detail} loadingLabel="Region wird geladen …" errorTitle="Die Region konnte nicht geladen werden">
            {(data) => <RegionContent data={data} searchLink={searchLink} kindLabel={kindLabel} />}
          </Async>
          <FramingNote />
        </>
      )}
    </div>
  );
}
