import { Link } from 'react-router';
import type { Dashboard, DashboardChange, SourcesResponse, Totals } from '../api/types';
import { GEO_CLASSES } from '../api/types';
import { TimeSeriesChart } from '../charts/TimeSeriesChart';
import { BasisBox, ConfigStatusBadge, FramingNote, HealthBadge, RunStatusBadge } from '../components/domain';
import { Icon } from '../components/Icon';
import { Alert, Async, Badge, Card, EmptyState, PageHeader, TableWrap } from '../components/ui';
import { fmtAgeDays, fmtDate, fmtDateTime, fmtInt, fmtNum, fmtPct, fmtSigned } from '../lib/format';
import { CONFIG_STATUS_LABELS, GEO_CLASS_SHORT, METRIC_LABELS, TIMELINE_KIND_LABELS } from '../lib/labels';
import { useFetch } from '../lib/useFetch';

const KIND_TILES: { key: 'jobs' | 'ausbildung' | 'praktikum'; label: string; hint: string; query: string }[] = [
  { key: 'jobs', label: 'Stellen', hint: 'Stellenanzeigen einschließlich Trainee, Werkstudierende, Minijob und Abschlussarbeit', query: '' },
  { key: 'ausbildung', label: 'Ausbildung & duales Studium', hint: 'getrennt von regulären Stellen ausgewiesen', query: '?kind_group=ausbildung' },
  { key: 'praktikum', label: 'Praktika', hint: 'getrennt von regulären Stellen ausgewiesen', query: '?kind_group=praktikum' },
];

function TotalsTile({ label, hint, totals, to }: { label: string; hint: string; totals: Totals; to: string }) {
  const outside = GEO_CLASSES.filter((g) => g !== 'resolved' && totals.geo[g] > 0);
  return (
    <article className="stat stat--accent dash-tile">
      <h3 className="stat__label">{label}</h3>
      <p className="stat__value">{fmtInt(totals.total)}</p>
      <p className="stat__hint">beobachtete Anzeigen im Bestand · {hint}</p>
      <dl className="kv dash-tile__geo">
        <div>
          <dt>{GEO_CLASS_SHORT.resolved} (in der Karte)</dt>
          <dd>{fmtInt(totals.geo.resolved)}</dd>
        </div>
        {outside.map((g) => (
          <div key={g}>
            <dt>{GEO_CLASS_SHORT[g]}</dt>
            <dd>{fmtInt(totals.geo[g])}</dd>
          </div>
        ))}
      </dl>
      <p className="stat__footer">
        <Link to={`/suche${to}`}>In der Stellensuche öffnen</Link>
      </p>
    </article>
  );
}

function ChangeTile({ days, change, sourceNames }: { days: string; change: DashboardChange; sourceNames: Map<number, string> }) {
  const total = change.total;
  const comparable = change.basis.comparable && total !== null;
  return (
    <article className="stat dash-change">
      <h3 className="stat__label">Veränderung in {days} Tagen</h3>
      {comparable && total ? (
        <>
          <p className="stat__value">
            {fmtSigned(total.abs, 0)}
            <span className="dash-change__unit"> Anzeigen</span>
          </p>
          <p className="stat__hint">
            {total.pct !== null ? <strong>{fmtPct(total.pct)}</strong> : <span>{total.pct_note ?? 'kein Prozentwert'}</span>}
            {' · '}
            {fmtInt(total.then)} am {fmtDate(change.basis.date_then)} → {fmtInt(total.now)} am {fmtDate(change.basis.date_now)}
          </p>
        </>
      ) : (
        <>
          <p className="dash-change__none">
            <Icon name="alert" size={16} /> Kein Vergleich möglich
          </p>
          <p className="stat__hint">{(change.message ?? 'Für die beiden Stichtage liegt keine vergleichbare Abdeckung vor.').replace(/^Kein Vergleich möglich:\s*/, '')}</p>
        </>
      )}
      <details className="disclosure">
        <summary>
          Vergleichsgrundlage: {fmtInt(change.basis.comparable_sources.length)} vergleichbar, {fmtInt(change.basis.excluded.length)} ausgeschlossen
        </summary>
        <BasisBox basis={change.basis} message={change.message} sourceNames={sourceNames} compact />
      </details>
    </article>
  );
}

function DashboardContent({ data, sources }: { data: Dashboard; sources: SourcesResponse | undefined }) {
  const byId = new Map((sources?.sources ?? []).map((s) => [s.id, s]));
  const sourceNames = new Map((sources?.sources ?? []).map((s) => [s.id, s.name]));
  const statusCounts = new Map<string, number>();
  for (const s of sources?.sources ?? []) statusCounts.set(s.config_status, (statusCounts.get(s.config_status) ?? 0) + 1);
  const anyData = data.totals.jobs.total + data.totals.ausbildung.total + data.totals.praktikum.total > 0;

  return (
    <>
      <FramingNote text={data.disclaimer} />

      {data.warnings.length > 0 ? (
        <Card title={`Offene Warnungen (${data.warnings.length})`} subtitle="Betriebshinweise, die die Aussagekraft der Zahlen einschränken können">
          <ul className="plain-list">
            {data.warnings.map((w) => (
              <li key={w.id}>
                <Alert tone="warn" compact title={w.message}>
                  {w.kind} · gemeldet am {fmtDateTime(w.created_at)}
                </Alert>
              </li>
            ))}
          </ul>
          <p className="field__hint">
            Warnungen werden in der <Link to="/quellen/system">Quellenverwaltung unter „System“</Link> bearbeitet.
          </p>
        </Card>
      ) : null}

      <section aria-labelledby="dash-observed" className="stack">
        <div className="row row--between">
          <h2 className="section-title" id="dash-observed">
            Beobachtete Anzeigen
          </h2>
          <p className="muted nowrap">Stand der Beobachtung: {fmtDate(data.reference_date)}</p>
        </div>
        {!anyData ? (
          <Alert tone="neutral" title="Noch keine Anzeigen erfasst">
            Anzeigen erscheinen hier, sobald eine Quelle freigegeben ist und ein Scanlauf abgeschlossen wurde. Die Freigabe erfolgt in der{' '}
            <Link to="/quellen">Quellenverwaltung</Link>.
          </Alert>
        ) : null}
        <div className="grid grid--3 grid--keep">
          {KIND_TILES.map((t) => (
            <TotalsTile key={t.key} label={t.label} hint={t.hint} totals={data.totals[t.key]} to={t.query} />
          ))}
        </div>
        <p className="field__hint">
          Jede zusammengeführte Anzeige zählt deutschlandweit einmal. Eine Anzeige kann mehrere Stellen betreffen; derselbe Bedarf kann auf mehreren
          Portalen erscheinen.
        </p>
      </section>

      <section aria-labelledby="dash-changes" className="stack">
        <h2 className="section-title" id="dash-changes">
          Veränderung des Bestands (Stellen)
        </h2>
        <div className="grid grid--3 grid--keep">
          {(['7', '30', '90'] as const).map((d) => {
            const change = data.changes[d];
            return change ? <ChangeTile key={d} days={d} change={change} sourceNames={sourceNames} /> : null;
          })}
        </div>
        <p className="field__hint">
          Verglichen wird nur, was an beiden Stichtagen von denselben Quellen mit demselben Suchbereich vollständig erfasst wurde. Ein Prozentwert
          erscheint nur bei einem Ausgangswert über null.
        </p>
      </section>

      <Card title="Zeitreihe: Stellenanzeigen der letzten 60 Tage" subtitle="Bestand sowie tägliche Zu- und Abgänge – ohne Filter, alle freigegebenen Quellen">
        <TimeSeriesChart series={data.timeseries} subject="Stellen" />
      </Card>

      <div className="grid grid--2">
        <Card title="Regionen mit den meisten Anzeigen" subtitle={data.top_regions_label}>
          {data.top_regions.length === 0 ? (
            <EmptyState title="Noch keine regionale Auswertung" icon="map" compact>
              Es gibt noch keine Anzeigen mit einem zugeordneten Kreis.
            </EmptyState>
          ) : (
            <TableWrap label="Regionen mit den meisten anteilig gezählten Anzeigen">
              <table className="table table--compact">
                <thead>
                  <tr>
                    <th scope="col">Kreis</th>
                    <th scope="col" className="col-num" title={METRIC_LABELS.weighted}>
                      anteilig gezählt
                    </th>
                    <th scope="col" className="col-num" title={METRIC_LABELS.distinct}>
                      unterschiedliche
                    </th>
                    <th scope="col" className="col-num" title={METRIC_LABELS.rate}>
                      je 1.000 Einw.
                    </th>
                  </tr>
                </thead>
                <tbody>
                  {data.top_regions.map((r) => (
                    <tr key={r.key}>
                      <th scope="row">
                        <Link to={`/regionen/${r.key}`}>{r.name}</Link>
                        {r.low_count ? <span className="table__sub">geringe Fallzahl</span> : null}
                      </th>
                      <td className="col-num">{fmtNum(r.weighted, 2)}</td>
                      <td className="col-num">{fmtInt(r.distinct)}</td>
                      <td className="col-num">{r.rate_per_1000 === null ? <span className="muted" title="Kein Bevölkerungswert als Nenner vorhanden">keine Daten</span> : fmtNum(r.rate_per_1000, 2)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </TableWrap>
          )}
          <p className="field__hint">
            <Link to="/karte">Zur Karte</Link> · Unterschiedliche Anzeigen je Kreis sind nicht addierbar.
          </p>
        </Card>

        <Card title="Quellen" subtitle={data.coverage.note}>
          {sources ? (
            <p className="row dash-status-counts">
              {(['active', 'candidate', 'permission_required', 'disabled'] as const).map((st) => (
                <span key={st} className="dash-status-count">
                  <strong>{fmtInt(statusCounts.get(st) ?? 0)}</strong> {CONFIG_STATUS_LABELS[st]}
                </span>
              ))}
            </p>
          ) : null}
          {data.coverage.sources.length === 0 ? (
            <EmptyState title="Keine Quelle ist freigegeben" icon="sources" compact action={<Link className="btn" to="/quellen">Zur Quellenverwaltung</Link>}>
              Nach der Installation ist keine Quelle automatisch aktiv. Eine Quelle wird erst nach einer dokumentierten Freigabe abgerufen.
            </EmptyState>
          ) : (
            <ul className="source-status">
              {data.coverage.sources.map((s) => {
                const full = byId.get(s.id);
                return (
                  <li key={s.id} className="source-status__item">
                    <div className="source-status__main">
                      <Link to={`/quellen/${s.id}`} className="source-status__name">
                        {s.name}
                      </Link>
                      <span className="source-status__meta">
                        Bestand {fmtInt(s.stock)} · letzter vollständiger Lauf {s.last_complete ? fmtDate(s.last_complete) : 'noch keiner'}
                      </span>
                    </div>
                    <div className="source-status__badges">
                      <ConfigStatusBadge status={s.config_status} />
                      {full ? <HealthBadge health={full.health} label={sources?.health_labels[full.health]} /> : s.last_status ? <RunStatusBadge status={s.last_status} /> : <Badge tone="muted">noch kein Lauf</Badge>}
                    </div>
                  </li>
                );
              })}
            </ul>
          )}
        </Card>
      </div>

      <div className="grid grid--2">
        <Card title="Datenaktualität der amtlichen Statistik" subtitle="Berichtszeitraum, Revision und Alter des jeweils jüngsten Datenstands">
          {data.freshness.statistics.length === 0 ? (
            <EmptyState title="Noch keine amtlichen Statistiken importiert" icon="table" compact>
              Bevölkerungs- und Arbeitsmarktdaten erscheinen hier nach dem ersten Import. Ohne Bevölkerungsdaten kann keine Quote je 1.000 Einwohner
              berechnet werden.
            </EmptyState>
          ) : (
            <TableWrap label="Datenstände der amtlichen Statistik">
              <table className="table table--compact">
                <thead>
                  <tr>
                    <th scope="col">Datensatz</th>
                    <th scope="col">Berichtszeitraum</th>
                    <th scope="col">Revision</th>
                    <th scope="col">Alter</th>
                    <th scope="col">Abgerufen</th>
                  </tr>
                </thead>
                <tbody>
                  {data.freshness.statistics.map((s) => (
                    <tr key={s.key}>
                      <th scope="row">
                        {s.name}
                        <span className="table__sub">{s.publisher}</span>
                      </th>
                      <td>
                        {s.period_key}
                        <span className="table__sub">Stand {fmtDate(s.period_end)}</span>
                      </td>
                      <td className="num">{s.revision}</td>
                      <td>{fmtAgeDays(s.age_days)}</td>
                      <td>{fmtDate(s.retrieved_at)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </TableWrap>
          )}
          <p className="field__hint">Das Alter bezieht sich auf das Ende des Berichtszeitraums, nicht auf den Abruf. Statistiken werden nicht interpoliert.</p>
        </Card>

        <Card title="Vermerke zur Vergleichbarkeit" subtitle="Neue Quellen, geänderte Suchbereiche, Regelwechsel und Datenlücken">
          {data.notes.length === 0 ? (
            <EmptyState title="Keine Vermerke" icon="clock" compact>
              Sobald Quellen hinzukommen oder sich Suchbereiche und Regeln ändern, wird das hier festgehalten.
            </EmptyState>
          ) : (
            <ol className="timeline">
              {data.notes.map((n, i) => (
                <li key={i} className="timeline__item">
                  <span className="timeline__date">{fmtDate(n.note_date)}</span>
                  <span className="timeline__kind">{TIMELINE_KIND_LABELS[n.kind] ?? n.kind}</span>
                  <span className="timeline__text">{n.message}</span>
                </li>
              ))}
            </ol>
          )}
        </Card>
      </div>
    </>
  );
}

export default function DashboardPage() {
  const dashboard = useFetch<Dashboard>('/api/dashboard');
  const sources = useFetch<SourcesResponse>('/api/sources');

  return (
    <div className="page">
      <PageHeader
        title="Dashboard"
        lead="Überblick über die beobachteten Stellenanzeigen, den Zustand der Quellen und die Aktualität der Daten."
        actions={dashboard.data ? <p className="muted">Berechnet am {fmtDateTime(dashboard.data.generated_at)}</p> : null}
      />
      <Async state={dashboard} loadingLabel="Dashboard wird berechnet …">
        {(data) => <DashboardContent data={data} sources={sources.data} />}
      </Async>
    </div>
  );
}
