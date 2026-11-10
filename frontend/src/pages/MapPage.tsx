import { useCallback, useId, useMemo } from 'react';
import { Link } from 'react-router';
import type { KreiseGeoJson, KreisProperties, MapChange, MapMetrics, PostingListResponse, StatsMap, StatsOverview, TimeSeries } from '../api/types';
import { TimeSeriesChart } from '../charts/TimeSeriesChart';
import { BasisBox, FramingNote, TotalsBox } from '../components/domain';
import { ExternalLink } from '../components/ExternalLink';
import { KindTabs, PostingCard } from '../components/postings';
import { Typeahead, type TypeaheadOption } from '../components/Typeahead';
import { Alert, Async, Button, Card, EmptyState, ErrorState, LoadingState, PageHeader, Segmented, TableWrap } from '../components/ui';
import { ActiveFilters, FilterLayout } from '../filters/FilterPanel';
import { DEFAULT_RADIUS_KM, serializeFilters, withQuery } from '../filters/model';
import { useFilters } from '../filters/useFilters';
import { fmtAgeDays, fmtDate, fmtInt, fmtNum, fmtPct, fmtSigned } from '../lib/format';
import { KIND_GROUP_LABELS, METRIC_LABELS, UPDATE_CYCLE_LABELS } from '../lib/labels';
import { useFeatureLabels, useMetaFilters, useSourceNames } from '../lib/lookups';
import { useFetch } from '../lib/useFetch';
import type { ClassMethod } from '../lib/viz';
import { ChoroplethMap, type MapCenter } from '../map/ChoroplethMap';
import { buildAdModel, buildChangeModel, buildContextModel, buildTooltip, type LegendEntry, type MapModel, type MapView } from '../map/model';

/** Kennzahl, die das Backend als Nenner der Quote verwendet (analytics.POP_INDICATOR). */
const POPULATION_INDICATOR = 'bev_15_bis_unter_65';
const VIEWS: MapView[] = ['weighted', 'distinct', 'rate', 'change', 'context'];
const VIEW_SHORT: Record<MapView, string> = {
  weighted: 'anteilig gezählt',
  distinct: 'unterschiedliche Anzeigen',
  rate: 'je 1.000 Einwohner',
  change: 'Veränderung',
  context: 'Kontextstatistik',
};
/** Vollständige Bezeichnungen (als Hinweistext der Umschalter; die Karte trägt sie als Überschrift). */
const VIEW_TITLE: Record<MapView, string> = {
  weighted: METRIC_LABELS.weighted,
  distinct: METRIC_LABELS.distinct,
  rate: METRIC_LABELS.rate,
  change: 'Veränderung der Anzeigen über 7, 30 oder 90 Tage',
  context: 'Bevölkerung und Arbeitsmarkt aus der amtlichen Statistik – getrennt von den Anzeigen',
};

function LegendSwatch({ entry }: { entry: LegendEntry }) {
  if (entry.pattern) return <span className={`legend__swatch legend__swatch--${entry.pattern}`} aria-hidden="true" />;
  return <span className="legend__swatch" style={{ background: entry.fill }} aria-hidden="true" />;
}

function Legend({ model, classMethod, onMethod }: { model: MapModel; classMethod: ClassMethod; onMethod: (m: ClassMethod) => void }) {
  return (
    <div className="legend">
      <p className="legend__title">
        {model.metricLabel}
        {model.unit ? <span className="muted"> ({model.unit})</span> : null}
      </p>
      <ul className="legend__list">
        {model.legend.map((e, i) => (
          <li key={i} className={e.count === 0 ? 'legend__item legend__item--empty' : 'legend__item'}>
            <LegendSwatch entry={e} />
            <span className="legend__label">{e.label}</span>
            <span className="legend__count" title="Anzahl Kreise">
              {fmtInt(e.count)}
            </span>
          </li>
        ))}
        {model.showLowCount ? (
          <li className="legend__item">
            <span className="legend__swatch legend__swatch--lowcount" aria-hidden="true" />
            <span className="legend__label">gestrichelter Rand = {model.lowCountLabel}</span>
          </li>
        ) : null}
      </ul>
      <p className="field__hint">
        Schraffur bedeutet „keine Daten“ und ist etwas anderes als der Wert 0. Die Zahl rechts nennt die Kreise je Klasse. {model.legendNote}
      </p>
      {model.noDataReasons.length > 0 ? (
        <ul className="note-list">
          {model.noDataReasons.map((r, i) => (
            <li key={i}>Keine Daten: {r}</li>
          ))}
        </ul>
      ) : null}
      {model.view !== 'change' ? (
        <Segmented<ClassMethod>
          label="Klassenbildung"
          size="sm"
          value={classMethod}
          options={[
            { value: 'quantile', label: 'Quantile', title: 'Etwa gleich viele Kreise je Klasse' },
            { value: 'equal', label: 'gleiche Intervalle', title: 'Gleich breite Wertebereiche je Klasse' },
          ]}
          onChange={onMethod}
        />
      ) : null}
    </div>
  );
}

export default function MapPage() {
  const ctl = useFilters();
  const { filters, query } = ctl;
  const meta = useMetaFilters();
  const featureLabels = useFeatureLabels(meta.data);
  const sourceNames = useSourceNames(meta.data);
  const indicatorId = useId();
  const periodId = useId();

  // --- Ansichtsparameter (ebenfalls in der Adresszeile) --------------------------------------------------
  const viewParam = ctl.getParam('metric') as MapView | null;
  const view: MapView = viewParam && VIEWS.includes(viewParam) ? viewParam : 'weighted';
  const daysParam = Number(ctl.getParam('days'));
  const days = [7, 30, 90].includes(daysParam) ? daysParam : 30;
  const changeBase = ctl.getParam('basis') === 'distinct' ? 'distinct' : 'weighted';
  const classMethod: ClassMethod = ctl.getParam('klassen') === 'equal' ? 'equal' : 'quantile';
  const indicatorParam = ctl.getParam('indicator');
  const periodParam = ctl.getParam('period'); // "<period_key>~<revision>"

  // Die Karte zeigt immer alle Kreise – der Kreisfilter wirkt nur auf Liste und Zeitreihe darunter.
  const mapQuery = useMemo(() => serializeFilters({ ...filters, kreise: [] }).toString(), [filters]);

  const geo = useFetch<KreiseGeoJson>('/api/geo/kreise.geojson', { cache: true });
  const metrics = useFetch<MapMetrics>(withQuery('/api/map/metrics', mapQuery));
  const change = useFetch<MapChange>(view === 'change' ? withQuery('/api/map/change', [mapQuery, `days=${days}`, `metric=${changeBase}`].filter(Boolean).join('&')) : null);
  const overview = useFetch<StatsOverview>('/api/stats/overview', { cache: true });
  const indicators = overview.data?.indicators ?? [];
  const indicator = indicators.find((i) => i.key === indicatorParam)?.key ?? indicators.find((i) => i.key === POPULATION_INDICATOR)?.key ?? indicators[0]?.key ?? null;
  const [periodKey, revision] = periodParam ? periodParam.split('~') : [null, null];
  const statsUrl =
    view === 'context' && indicator
      ? withQuery('/api/stats/map', new URLSearchParams({ indicator, ...(periodKey ? { period: periodKey } : {}), ...(revision ? { revision } : {}) }).toString())
      : null;
  const stats = useFetch<StatsMap>(statsUrl);
  const needPopulation = view === 'rate' && Boolean(metrics.data?.population_release);
  const population = useFetch<StatsMap>(needPopulation ? `/api/stats/map?indicator=${POPULATION_INDICATOR}` : null, { cache: true });

  const list = useFetch<PostingListResponse>(withQuery('/api/postings', [query, 'page_size=6'].filter(Boolean).join('&')));
  const series = useFetch<TimeSeries>(withQuery('/api/timeseries', [query, 'days=90'].filter(Boolean).join('&')));

  const features = useMemo(() => geo.data?.features ?? [], [geo.data]);
  const keys = useMemo(() => features.map((f) => f.properties.key), [features]);
  const propsByKey = useMemo(() => new Map(features.map((f) => [f.properties.key, f.properties])), [features]);

  const populationMap = useMemo(() => {
    if (!population.data) return null;
    const m = new Map<string, number>();
    for (const v of population.data.values) if (v.value !== null && v.status === 'ok') m.set(v.key, v.value);
    return m;
  }, [population.data]);

  const model = useMemo<MapModel | null>(() => {
    if (view === 'change') return change.data ? buildChangeModel({ change: change.data, metrics: metrics.data, keys }) : null;
    if (view === 'context') return stats.data ? buildContextModel({ stats: stats.data, keys, method: classMethod }) : null;
    return metrics.data ? buildAdModel({ view, metrics: metrics.data, keys, method: classMethod, population: populationMap }) : null;
  }, [view, change.data, stats.data, metrics.data, keys, classMethod, populationMap]);

  const styleOf = useCallback(
    (key: string) => {
      const i = model?.info(key);
      return i ? { fill: i.fill, pattern: i.pattern, lowCount: i.lowCount } : { fill: '#ffffff', pattern: 'nodata' as const, lowCount: false };
    },
    [model],
  );
  const tooltipFor = useCallback(
    (key: string, props: KreisProperties) => {
      if (!model) {
        const el = document.createElement('div');
        el.textContent = props.name;
        return el;
      }
      return buildTooltip(props, model, model.info(key));
    },
    [model],
  );

  const selectKreis = useCallback(
    (key: string) => {
      const current = ctl.filters.kreise;
      ctl.update({ kreise: current.length === 1 && current[0] === key ? [] : [key] });
    },
    [ctl],
  );

  const selectedKey = filters.kreise.length === 1 ? (filters.kreise[0] ?? null) : null;
  const selectedProps = selectedKey ? propsByKey.get(selectedKey) : undefined;
  const selectedInfo = selectedKey && model ? model.info(selectedKey) : null;

  const near = list.data?.near;
  const center: MapCenter | null = near ? { lat: near.lat, lon: near.lon, radiusKm: filters.radiusKm ?? DEFAULT_RADIUS_KM, label: `${near.name} – angenäherter Mittelpunkt der Umkreissuche` } : null;

  const activeState = view === 'change' ? change : view === 'context' ? stats : metrics;
  const tableRows = useMemo(() => {
    if (!model) return [];
    return features
      .map((f) => ({ props: f.properties, info: model.info(f.properties.key) }))
      .sort((a, b) => (b.info.sortValue ?? Number.NEGATIVE_INFINITY) - (a.info.sortValue ?? Number.NEGATIVE_INFINITY) || a.props.name.localeCompare(b.props.name, 'de'));
  }, [features, model]);

  const searchKreis = async (term: string): Promise<TypeaheadOption<KreisProperties>[]> => {
    const t = term.toLocaleLowerCase('de');
    return features
      .filter((f) => f.properties.name.toLocaleLowerCase('de').includes(t) || f.properties.key.startsWith(term))
      .slice(0, 20)
      .map((f) => ({ id: f.properties.key, label: f.properties.name, hint: [f.properties.type, f.properties.state].filter(Boolean).join(' · '), value: f.properties }));
  };

  const indicatorGroups = useMemo(() => {
    const datasets = new Map((overview.data?.datasets ?? []).map((d) => [d.key, d.name]));
    const groups = new Map<string, StatsOverview['indicators']>();
    for (const ind of overview.data?.indicators ?? []) {
      const name = datasets.get(ind.dataset_key ?? '') ?? 'Ohne Datensatz';
      groups.set(name, [...(groups.get(name) ?? []), ind]);
    }
    return [...groups.entries()];
  }, [overview.data]);
  const currentIndicator = indicators.find((i) => i.key === indicator);
  const regionQuery = serializeFilters({ ...filters, kreise: [], states: [] }).toString();

  return (
    <div className="page">
      <PageHeader
        title="Karte"
        lead="Regionale Schwerpunkte der beobachteten Anzeigen nach Kreisen. Die Karte zeigt erfasste Nachfrage aus den freigegebenen Quellen – keinen Nachweis eines Fachkräfteengpasses."
      />
      <KindTabs value={filters.kindGroup} onChange={(kindGroup) => ctl.update({ kindGroup })} />

      <FilterLayout ctl={ctl} meta={meta.data} metaError={meta.error?.message} inlineFrom={1640}>
        {(filterButton) => (
          <>
            <div className="toolbar">
              {filterButton}
              <div className="toolbar__grow">
                <ActiveFilters ctl={ctl} meta={meta.data} />
              </div>
            </div>

            <div className="map-layout">
              <Card className="map-card" flush>
                <div className="map-card__controls">
                  <Segmented<MapView> label="Dargestellte Größe" value={view} options={VIEWS.map((v) => ({ value: v, label: VIEW_SHORT[v], title: VIEW_TITLE[v] }))} onChange={(v) => ctl.setParams({ metric: v === 'weighted' ? null : v })} />
                  {view === 'change' ? (
                    <div className="row row--top">
                      <Segmented
                        label="Zeitraum"
                        size="sm"
                        value={String(days)}
                        options={[
                          { value: '7', label: '7 Tage' },
                          { value: '30', label: '30 Tage' },
                          { value: '90', label: '90 Tage' },
                        ]}
                        onChange={(v) => ctl.setParams({ days: v === '30' ? null : v })}
                      />
                      <Segmented
                        label="Verglichen wird"
                        size="sm"
                        value={changeBase}
                        options={[
                          { value: 'weighted', label: 'anteilig gezählte Anzeigen' },
                          { value: 'distinct', label: 'unterschiedliche Anzeigen' },
                        ]}
                        onChange={(v) => ctl.setParams({ basis: v === 'weighted' ? null : v })}
                      />
                    </div>
                  ) : null}
                  {view === 'context' ? (
                    <div className="stack stack--tight">
                      <Alert tone="neutral" compact title="Kontextansicht – keine Anzeigenkennzahl">
                        Amtliche Statistik steht getrennt neben den Anzeigen und wird nicht mit ihnen verrechnet. Die Anzeigenfilter wirken auf diese Ansicht
                        nicht.
                      </Alert>
                      {overview.error ? <ErrorState compact error={overview.error} onRetry={overview.reload} title="Kennzahlen nicht verfügbar" /> : null}
                      {overview.data && indicators.length === 0 ? (
                        <p className="muted">Es sind noch keine Kennzahlen der amtlichen Statistik angelegt.</p>
                      ) : (
                        <div className="form-grid">
                          <div className="field">
                            <label className="field__label" htmlFor={indicatorId}>
                              Kennzahl
                            </label>
                            <select id={indicatorId} className="select" value={indicator ?? ''} onChange={(e) => ctl.setParams({ indicator: e.target.value, period: null })}>
                              {indicatorGroups.map(([group, items]) => (
                                <optgroup key={group} label={group}>
                                  {items.map((i) => (
                                    <option key={i.key} value={i.key}>
                                      {i.name} ({i.unit})
                                    </option>
                                  ))}
                                </optgroup>
                              ))}
                            </select>
                          </div>
                          <div className="field">
                            <label className="field__label" htmlFor={periodId}>
                              Berichtszeitraum und Revision
                            </label>
                            <select id={periodId} className="select" value={periodParam ?? ''} disabled={!stats.data || stats.data.periods.length === 0} onChange={(e) => ctl.setParams({ period: e.target.value || null })}>
                              <option value="">jüngster Stand (aktuelle Revision)</option>
                              {(stats.data?.periods ?? []).map((p) => (
                                <option key={`${p.period_key}~${p.revision}`} value={`${p.period_key}~${p.revision}`}>
                                  {p.period_key} · Revision {p.revision}
                                  {p.is_current ? '' : ' (ältere Fassung)'}
                                </option>
                              ))}
                            </select>
                          </div>
                        </div>
                      )}
                      {currentIndicator?.definition ? <p className="field__hint">{currentIndicator.definition}{currentIndicator.population_group ? ` Bezugsgruppe: ${currentIndicator.population_group}.` : ''}</p> : null}
                    </div>
                  ) : null}
                </div>
                <div className="map-card__head">
                  <div>
                    <h2 className="card__title">{model?.metricLabel ?? VIEW_SHORT[view]}</h2>
                    <p className="card__subtitle">
                      {view === 'context'
                        ? stats.data?.release
                          ? `Berichtszeitraum ${stats.data.release.period_key}, Revision ${stats.data.release.revision}, Alter ${fmtAgeDays(stats.data.release.age_days)}`
                          : 'amtliche Statistik'
                        : `${KIND_GROUP_LABELS[filters.kindGroup]} · ${metrics.data ? `Stichtag ${fmtDate(metrics.data.reference_date)} · ${metrics.data.scope.basis}` : 'wird geladen …'}`}
                    </p>
                  </div>
                  {features.length > 0 ? (
                    <div className="map-card__search">
                      <Typeahead<KreisProperties> label="Kreis auswählen" hideLabel placeholder="Kreis suchen und auswählen" search={searchKreis} emptyText="Kein Kreis gefunden" onSelect={(o) => ctl.update({ kreise: [o.value.key] })} />
                    </div>
                  ) : null}
                </div>

                {geo.error ? <ErrorState error={geo.error} onRetry={geo.reload} title="Die Kreisgrenzen konnten nicht geladen werden" /> : null}
                {!geo.error && geo.data === undefined ? <LoadingState label="Kreisgrenzen werden geladen …" /> : null}
                {geo.data && features.length === 0 ? (
                  <EmptyState title="Kreisgrenzen noch nicht importiert" icon="map">
                    Für die Karte fehlen die Verwaltungsgrenzen der Kreise und kreisfreien Städte. Sie werden einmalig aus den amtlichen Geodaten
                    (VG250) importiert und danach lokal ausgeliefert – ohne externe Kartendienste. Liste, Summen und Zeitreihe unten funktionieren
                    auch ohne Karte.
                  </EmptyState>
                ) : null}
                {geo.data && features.length > 0 ? (
                  <div className={activeState.loading ? 'map-frame is-refreshing' : 'map-frame'}>
                    <ChoroplethMap geojson={geo.data} styleOf={styleOf} selected={filters.kreise} onSelect={selectKreis} tooltipFor={tooltipFor} center={center} label={`Karte der Kreise: ${model?.metricLabel ?? VIEW_SHORT[view]}`} />
                    {activeState.error ? (
                      <div className="map-frame__overlay">
                        <ErrorState compact error={activeState.error} onRetry={activeState.reload} title="Die Kartendaten konnten nicht geladen werden" />
                      </div>
                    ) : null}
                    {view === 'context' && overview.data && indicators.length === 0 ? (
                      <div className="map-frame__overlay">
                        <EmptyState compact title="Noch keine amtlichen Statistiken importiert" icon="table">
                          Bevölkerungs- und Arbeitsmarktdaten erscheinen hier nach dem ersten Import (Quellenverwaltung → System).
                        </EmptyState>
                      </div>
                    ) : null}
                    {view === 'context' && stats.data && !stats.data.release ? (
                      <div className="map-frame__overlay">
                        <EmptyState compact title="Keine Kreisdaten für diese Kennzahl" icon="table">
                          {stats.data.message ?? 'Für diese Kennzahl liegen keine Kreisdaten vor.'}
                        </EmptyState>
                      </div>
                    ) : null}
                  </div>
                ) : null}
                <p className="map-card__attribution">
                  {geo.data?.attribution ? `Geodaten: ${geo.data.attribution}` : 'Geodaten: Quellenangabe wird mit dem Import der Kreisgrenzen geliefert.'}
                  {geo.data?.gebietsstand ? ` · Gebietsstand ${fmtDate(geo.data.gebietsstand)}` : ''} · Kartendarstellung mit Leaflet, ohne externe Kartenkacheln.
                  {features.length > 0 ? ' Mausrad-Zoom nach Klick in die Karte.' : ''}
                </p>
              </Card>

              <div className="stack">
                {model && features.length > 0 ? (
                  <Card title="Legende">
                    <Legend model={model} classMethod={classMethod} onMethod={(m) => ctl.setParams({ klassen: m === 'quantile' ? null : m }, { replace: true })} />
                  </Card>
                ) : null}

                <Card title={selectedProps ? selectedProps.name : 'Ausgewählter Kreis'} subtitle={selectedProps ? [selectedProps.type, selectedProps.state].filter(Boolean).join(' · ') : undefined}>
                  {filters.kreise.length === 0 ? (
                    <p className="selected-hint">Klicken Sie auf einen Kreis oder wählen Sie ihn über das Suchfeld aus. Liste und Zeitreihe unten beziehen sich dann auf diesen Kreis.</p>
                  ) : null}
                  {filters.kreise.length > 1 ? <p className="selected-hint">{filters.kreise.length} Kreise sind als Filter gesetzt und in der Karte hervorgehoben.</p> : null}
                  {selectedKey && !selectedProps && geo.data ? <p className="selected-hint">Kreis {selectedKey} ist als Filter gesetzt, in den Kreisgrenzen aber nicht enthalten.</p> : null}
                  {selectedInfo && model ? (
                    <>
                      <dl className="kv kv--wrap">
                        {[...selectedInfo.lines, ...model.commonLines].map((l, i) => (
                          <div key={i} className={l.strong ? 'kv__strong' : undefined}>
                            <dt>{l.label}</dt>
                            <dd>{l.value}</dd>
                          </div>
                        ))}
                      </dl>
                      {selectedInfo.hints.length > 0 ? (
                        <ul className="note-list">
                          {selectedInfo.hints.map((h, i) => (
                            <li key={i}>{h}</li>
                          ))}
                        </ul>
                      ) : null}
                    </>
                  ) : null}
                  {filters.kreise.length > 0 ? (
                    <div className="row">
                      {selectedKey ? (
                        <Link className="btn btn--primary btn--sm" to={withQuery(`/regionen/${selectedKey}`, regionQuery)}>
                          Zur Regionsdetailseite
                        </Link>
                      ) : null}
                      <Button size="sm" variant="ghost" onClick={() => ctl.update({ kreise: [] })}>
                        Auswahl aufheben
                      </Button>
                    </div>
                  ) : null}
                </Card>

                {view !== 'context' ? (
                  <Card title="Summen dieser Auswahl" subtitle="unabhängig vom ausgewählten Kreis">
                    <Async state={metrics} compact>
                      {(m) => (
                        <>
                          <TotalsBox totals={m.totals} totalLabel="zusammengeführte Anzeigen – deutschlandweit zählt jede einmal" onSelect={(g) => ctl.update({ geoClass: [g] })} />
                          <dl className="kv">
                            <div>
                              <dt>Summe der anteilig gezählten Anzeigen über alle Kreise</dt>
                              <dd>{fmtNum(m.weighted_sum, 2)}</dd>
                            </div>
                          </dl>
                          <p className="field__hint">
                            Teilweise ungeklärte, ungeklärte, deutschlandweit remote ausgeschriebene, ausländische und ortslose Anzeigen sind getrennt
                            ausgewiesen und keinem Kreis anteilig zugeschlagen. Die Zahl der unterschiedlichen Anzeigen je Kreis ist <strong>nicht addierbar</strong>:
                            Eine Anzeige mit mehreren Arbeitsorten zählt in jedem dieser Kreise.
                          </p>
                        </>
                      )}
                    </Async>
                  </Card>
                ) : null}
              </div>
            </div>

            {view === 'change' && change.data ? (
              <Card title="Vergleichsgrundlage der Veränderung" subtitle="Verglichen wird nur, was an beiden Stichtagen gleich erfasst wurde">
                {change.data.total ? (
                  <p>
                    Deutschlandweit: <strong>{fmtSigned(change.data.total.abs, 0)} Anzeigen</strong>
                    {change.data.total.pct !== null ? ` (${fmtPct(change.data.total.pct)})` : change.data.total.pct_note ? ` – ${change.data.total.pct_note}` : ''} · {fmtInt(change.data.total.then)} →{' '}
                    {fmtInt(change.data.total.now)}
                  </p>
                ) : null}
                <BasisBox basis={change.data.basis} message={change.data.message} sourceNames={sourceNames} />
              </Card>
            ) : null}

            {view === 'context' && stats.data?.release ? (
              <Card title="Datenstand der Kontextstatistik" subtitle={stats.data.indicator.name}>
                <dl className="deflist deflist--3">
                  <div className="deflist__item">
                    <dt>Datensatz</dt>
                    <dd>
                      {stats.data.release.dataset_name} ({stats.data.release.publisher})
                    </dd>
                  </div>
                  <div className="deflist__item">
                    <dt>Berichtszeitraum</dt>
                    <dd>
                      {stats.data.release.period_key} · Stand {fmtDate(stats.data.release.period_end)}
                    </dd>
                  </div>
                  <div className="deflist__item">
                    <dt>Revision</dt>
                    <dd>
                      {stats.data.release.revision} {stats.data.release.is_current ? '(aktuell)' : '(ältere Fassung)'}
                    </dd>
                  </div>
                  <div className="deflist__item">
                    <dt>Alter</dt>
                    <dd>{fmtAgeDays(stats.data.release.age_days)}</dd>
                  </div>
                  <div className="deflist__item">
                    <dt>Veröffentlicht</dt>
                    <dd>{stats.data.release.published_on ? fmtDate(stats.data.release.published_on) : 'unbekannt'}</dd>
                  </div>
                  <div className="deflist__item">
                    <dt>Abgerufen</dt>
                    <dd>{fmtDate(stats.data.release.retrieved_at)}</dd>
                  </div>
                  <div className="deflist__item deflist__item--wide">
                    <dt>Quellenangabe und Lizenz</dt>
                    <dd>
                      {stats.data.release.attribution ?? stats.data.release.publisher}
                      {stats.data.release.licence ? (
                        <>
                          {' · '}
                          <ExternalLink href={stats.data.release.licence_url} fallback={stats.data.release.licence}>
                            {stats.data.release.licence}
                          </ExternalLink>
                        </>
                      ) : null}
                      {stats.data.release.landing_url ? (
                        <>
                          {' · '}
                          <ExternalLink href={stats.data.release.landing_url}>Seite des Herausgebers</ExternalLink>
                        </>
                      ) : null}
                    </dd>
                  </div>
                </dl>
                <p className="field__hint">{overview.data?.note}</p>
                {overview.data?.datasets.find((d) => d.key === stats.data?.release?.dataset_key)?.update_cycle ? (
                  <p className="field__hint">
                    Erscheinungsweise: {UPDATE_CYCLE_LABELS[overview.data.datasets.find((d) => d.key === stats.data?.release?.dataset_key)?.update_cycle ?? ''] ?? 'unregelmäßig'}.
                  </p>
                ) : null}
              </Card>
            ) : null}

            {model && features.length > 0 ? (
              <details className="card facets">
                <summary className="facets__summary">Kreise als Tabelle anzeigen (gleiche Werte wie in der Karte)</summary>
                <div className="card__body">
                  <TableWrap label="Kreise mit Kartenwert">
                    <table className="table table--compact">
                      <thead>
                        <tr>
                          <th scope="col">Kreis</th>
                          <th scope="col">Land</th>
                          <th scope="col" className="col-num">
                            {model.metricLabel}
                          </th>
                          <th scope="col">Hinweis</th>
                        </tr>
                      </thead>
                      <tbody>
                        {tableRows.map(({ props, info }) => (
                          <tr key={props.key}>
                            <th scope="row">
                              <Link to={withQuery(`/regionen/${props.key}`, regionQuery)}>{props.name}</Link>
                            </th>
                            <td>{props.state ?? '–'}</td>
                            <td className="col-num">{info.valueText}</td>
                            <td>{info.lowCount ? 'geringe Fallzahl' : info.pattern === 'nodata' ? 'keine Daten' : info.pattern === 'newbase' ? 'Ausgangswert 0' : ''}</td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </TableWrap>
                </div>
              </details>
            ) : null}

            {view !== 'context' ? (
              <div className="grid grid--2">
                <Card
                  title={selectedProps ? `Anzeigen in ${selectedProps.name}` : 'Anzeigen dieser Auswahl'}
                  subtitle="neueste zuerst – dieselben Filter wie die Karte"
                  actions={
                    <Link className="btn btn--sm" to={withQuery('/suche', query)}>
                      Alle in der Stellensuche
                    </Link>
                  }
                >
                  <Async state={list} compact loadingLabel="Anzeigen werden geladen …">
                    {(data) =>
                      data.items.length === 0 ? (
                        <EmptyState compact title="Keine Anzeigen für diese Auswahl" icon="posting">
                          {selectedProps ? 'Für diesen Kreis gibt es in der aktuellen Auswahl keine beobachtete Anzeige.' : 'Es gibt noch keine beobachteten Anzeigen, die zu den Filtern passen.'}
                        </EmptyState>
                      ) : (
                        <>
                          <p className="muted">
                            {fmtInt(data.total)} {data.total === 1 ? 'Anzeige' : 'Anzeigen'} · gezeigt werden die ersten {data.items.length}
                          </p>
                          {data.near ? (
                            <Alert tone="info" compact title={`Umkreissuche um ${data.near.name}`}>
                              {data.near.note}
                            </Alert>
                          ) : null}
                          <ol className="posting-list posting-list--compact">
                            {data.items.map((item) => (
                              <li key={item.id}>
                                <PostingCard item={item} featureLabels={featureLabels} compact />
                              </li>
                            ))}
                          </ol>
                        </>
                      )
                    }
                  </Async>
                </Card>
                <Card title={selectedProps ? `Zeitreihe für ${selectedProps.name}` : 'Zeitreihe dieser Auswahl'} subtitle="letzte 90 Tage – dieselben Filter wie die Karte">
                  <Async state={series} compact loadingLabel="Zeitreihe wird berechnet …">
                    {(data) => <TimeSeriesChart series={data} compact subject={selectedProps?.name} />}
                  </Async>
                </Card>
              </div>
            ) : null}

            {metrics.data ? (
              <Card title="Formeln und Regelstände" subtitle="so, wie die API sie für diese Auswertung ausweist">
                <dl className="definition-list">
                  <div>
                    <dt>{METRIC_LABELS.weighted}</dt>
                    <dd>{metrics.data.formulas.weighted}</dd>
                  </div>
                  <div>
                    <dt>{METRIC_LABELS.distinct}</dt>
                    <dd>{metrics.data.formulas.distinct}</dd>
                  </div>
                  <div>
                    <dt>{METRIC_LABELS.rate}</dt>
                    <dd>{metrics.data.formulas.rate_per_1000}</dd>
                  </div>
                </dl>
                <p className="field__hint">
                  Regelstände: Dubletten {metrics.data.rule_versions.dedup} · Klassifikation {metrics.data.rule_versions.classifier} · Ortszuordnung {metrics.data.rule_versions.geo} · Aggregation{' '}
                  {metrics.data.rule_versions.aggregate}. {metrics.data.coverage.note} <Link to="/methodik">Mehr zur Methodik</Link>
                </p>
              </Card>
            ) : null}
          </>
        )}
      </FilterLayout>
      <FramingNote />
    </div>
  );
}
