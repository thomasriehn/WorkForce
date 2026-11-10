import { type FormEvent, useEffect, useId, useState } from 'react';
import { Link } from 'react-router';
import { api, errorMessage } from '../api/client';
import type { Facets, PostingListResponse, SavedSearch } from '../api/types';
import { ConfirmDialog, Dialog } from '../components/Dialog';
import { FramingNote, Pagination, TotalsBox } from '../components/domain';
import { Icon } from '../components/Icon';
import { Popover } from '../components/Popover';
import { KindTabs, PostingCard } from '../components/postings';
import { useToast } from '../components/Toast';
import { Alert, Async, Button, Card, EmptyState, ErrorState, LoadingState, PageHeader } from '../components/ui';
import { ActiveFilters, FilterLayout } from '../filters/FilterPanel';
import { countActiveFilters, filtersToParams, paramsToSearch, parseFilters, withQuery } from '../filters/model';
import { type FilterController, useFilters } from '../filters/useFilters';
import { fmtDate, fmtInt } from '../lib/format';
import { KIND_GROUP_LABELS, KIND_LABELS, SORT_LABELS } from '../lib/labels';
import { useFeatureLabels, useMetaFilters } from '../lib/lookups';
import { useFetch } from '../lib/useFetch';

const PAGE_SIZE = 25;
const DEFAULT_SORTS = ['relevance', 'first_seen', 'date_posted', 'title', 'employer', 'apply_until', 'last_seen'];

function SearchBox({ ctl }: { ctl: FilterController }) {
  const { filters, update } = ctl;
  const [draft, setDraft] = useState(filters.q);
  const inputId = useId();
  useEffect(() => setDraft(filters.q), [filters.q]);

  const onSubmit = (e: FormEvent) => {
    e.preventDefault();
    update({ q: draft.trim() });
  };

  return (
    <form className="searchbox" role="search" onSubmit={onSubmit}>
      <div className="searchbox__row">
        <label className="visually-hidden" htmlFor={inputId}>
          Suchbegriffe
        </label>
        <input
          id={inputId}
          className="input searchbox__input"
          type="search"
          maxLength={500}
          value={draft}
          placeholder='Titel, Arbeitgeber, Beruf, Merkmal oder Ort – z. B. "Sachbearbeitung Personal" ODER Verwaltungsfach*'
          onChange={(e) => setDraft(e.target.value)}
        />
        <Popover label="Hilfe zur Suchsyntax" align="right">
          <p>
            <strong>So funktioniert die Suche</strong>
          </p>
          <dl className="syntax-help">
            <div>
              <dt>
                <code>"Leitung Personal"</code>
              </dt>
              <dd>Phrase: die Wörter müssen genau so hintereinander stehen.</dd>
            </div>
            <div>
              <dt>
                <code>Pflege UND Nachtdienst</code>
              </dt>
              <dd>Beide Begriffe müssen vorkommen. Mehrere Wörter ohne Operator werden ebenfalls mit UND verknüpft.</dd>
            </div>
            <div>
              <dt>
                <code>Erzieher ODER Sozialpädagoge</code>
              </dt>
              <dd>Mindestens einer der Begriffe muss vorkommen. Klammern gruppieren.</dd>
            </div>
            <div>
              <dt>
                <code>Ingenieur -Vertrieb</code> oder <code>NICHT Vertrieb</code>
              </dt>
              <dd>Ausschluss: Treffer mit diesem Begriff werden weggelassen. Eine Suche nur aus Ausschlüssen ist nicht möglich.</dd>
            </div>
            <div>
              <dt>
                <code>Verwaltung*</code>
              </dt>
              <dd>Präfix: findet alle Wörter, die so beginnen (mindestens zwei Zeichen vor dem Stern).</dd>
            </div>
          </dl>
          <p className="field__hint">
            Groß- und Kleinschreibung sowie Umlaute spielen keine Rolle. Gebräuchliche Synonyme (z. B. Krankenschwester/Pflegefachkraft) werden
            mitgesucht. Durchsucht werden die gespeicherten Rumpfdaten – der Volltext der Anzeigen wird nicht gespeichert.
          </p>
        </Popover>
        <Button type="submit" variant="primary" icon="search">
          Suchen
        </Button>
      </div>
      <label className="check searchbox__fuzzy">
        <input type="checkbox" checked={filters.fuzzy} onChange={(e) => update({ fuzzy: e.target.checked, q: draft.trim() })} />
        <span className="check__label">
          Ähnliche Schreibweisen einbeziehen
          <span className="check__hint">findet auch Tippfehler und abweichende Schreibungen in Titel und Arbeitgeber</span>
        </span>
      </label>
    </form>
  );
}

function SavedSearches({ ctl, sort }: { ctl: FilterController; sort: string | null }) {
  const toast = useToast();
  const saved = useFetch<SavedSearch[]>('/api/saved-searches');
  const [saveOpen, setSaveOpen] = useState(false);
  const [name, setName] = useState('');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [toDelete, setToDelete] = useState<SavedSearch | null>(null);
  const nameId = useId();
  const existing = saved.data?.find((s) => s.name === name.trim());

  const save = (e: FormEvent) => {
    e.preventDefault();
    setBusy(true);
    setError(null);
    api
      .post<{ id: number; name: string; updated: boolean }>('/api/saved-searches', { name: name.trim(), params: filtersToParams(ctl.filters, sort) })
      .then((res) => {
        toast.success(res.updated ? `Gespeicherte Suche „${res.name}“ aktualisiert.` : `Suche „${res.name}“ gespeichert.`);
        setSaveOpen(false);
        setName('');
        saved.reload();
      })
      .catch((err: unknown) => setError(errorMessage(err)))
      .finally(() => setBusy(false));
  };

  const remove = () => {
    if (!toDelete) return;
    setBusy(true);
    setError(null);
    api
      .delete(`/api/saved-searches/${toDelete.id}`)
      .then(() => {
        toast.success(`Gespeicherte Suche „${toDelete.name}“ gelöscht.`);
        setToDelete(null);
        saved.reload();
      })
      .catch((err: unknown) => setError(errorMessage(err)))
      .finally(() => setBusy(false));
  };

  return (
    <>
      <Popover label="Gespeicherte Suchen" icon="save" text={`Gespeicherte Suchen${saved.data ? ` (${saved.data.length})` : ''}`} align="right">
        <p>
          <strong>Gespeicherte Suchen</strong>
        </p>
        {saved.error ? <ErrorState compact error={saved.error} onRetry={saved.reload} title="Gespeicherte Suchen nicht verfügbar" /> : null}
        {!saved.error && saved.data === undefined ? <LoadingState compact label="Wird geladen …" /> : null}
        {saved.data && saved.data.length === 0 ? <p className="muted">Sie haben noch keine Suche gespeichert. Gespeicherte Suchen sind nur für Ihr eigenes Konto sichtbar.</p> : null}
        {saved.data && saved.data.length > 0 ? (
          <ul className="saved-list">
            {saved.data.map((s) => {
              const sp = paramsToSearch(s.params);
              const kind = parseFilters(sp).kindGroup;
              return (
                <li key={s.id} className="saved-list__item">
                  <Link to={withQuery('/suche', sp.toString())} className="saved-list__link">
                    {s.name}
                    <span className="saved-list__meta">
                      {KIND_GROUP_LABELS[kind]} · {countActiveFilters(parseFilters(sp))} Filter · gespeichert am {fmtDate(s.created_at)}
                    </span>
                  </Link>
                  <button type="button" className="icon-btn" aria-label={`Gespeicherte Suche „${s.name}“ löschen`} title="Löschen" onClick={() => setToDelete(s)}>
                    <Icon name="trash" />
                  </button>
                </li>
              );
            })}
          </ul>
        ) : null}
        <Button icon="save" size="sm" onClick={() => setSaveOpen(true)}>
          Aktuelle Suche speichern
        </Button>
      </Popover>

      <Dialog
        open={saveOpen}
        onClose={() => setSaveOpen(false)}
        title="Aktuelle Suche speichern"
        footer={
          <>
            <Button variant="ghost" onClick={() => setSaveOpen(false)} disabled={busy}>
              Abbrechen
            </Button>
            <Button variant="primary" type="submit" form="save-search-form" busy={busy} disabled={!name.trim()}>
              {existing ? 'Überschreiben' : 'Speichern'}
            </Button>
          </>
        }
      >
        <form id="save-search-form" className="form" onSubmit={save}>
          <div className="field">
            <label className="field__label" htmlFor={nameId}>
              Name der Suche
            </label>
            <input id={nameId} className="input" value={name} maxLength={120} required autoFocus onChange={(e) => setName(e.target.value)} placeholder="z. B. Pflege in Nordhessen" />
            <p className="field__hint">
              Gespeichert werden Suchbegriffe, alle Filter und die Sortierung – nicht die Treffer. {existing ? 'Eine Suche mit diesem Namen existiert bereits und wird überschrieben.' : ''}
            </p>
          </div>
          {error ? (
            <p className="form-error" role="alert">
              {error}
            </p>
          ) : null}
        </form>
      </Dialog>

      <ConfirmDialog open={toDelete !== null} title="Gespeicherte Suche löschen?" confirmLabel="Löschen" danger busy={busy} error={error} onConfirm={remove} onClose={() => setToDelete(null)}>
        <p>Die gespeicherte Suche „{toDelete?.name}“ wird entfernt. Anzeigen und Daten bleiben unverändert.</p>
      </ConfirmDialog>
    </>
  );
}

function FacetPanel({ ctl, query }: { ctl: FilterController; query: string }) {
  const [open, setOpen] = useState(false);
  const facets = useFetch<Facets>(open ? withQuery('/api/facets', query) : null);
  const { filters: f, update } = ctl;

  return (
    <details className="card facets" onToggle={(e) => setOpen(e.currentTarget.open)}>
      <summary className="facets__summary">Verteilung der Treffer: häufigste Berufe, Merkmale und Arbeitgeber</summary>
      {open ? (
        <div className="card__body">
          <Async state={facets} compact loadingLabel="Verteilung wird berechnet …">
            {(data) => (
              <div className="facets__grid">
                <section>
                  <h3 className="subhead">Berufe (KldB)</h3>
                  {data.occupations.length === 0 ? <p className="muted">Keine klassifizierten Anzeigen.</p> : null}
                  <ul className="facet-list">
                    {data.occupations.map((o) => (
                      <li key={o.kldb_code}>
                        <button type="button" className="facet-list__btn" disabled={f.kldb.includes(o.kldb_code)} onClick={() => update({ kldb: [...f.kldb, o.kldb_code] })} title="Als Filter übernehmen">
                          <span>
                            {o.name ?? 'Bezeichnung unbekannt'} <span className="muted">({o.kldb_code})</span>
                          </span>
                          <span className="facet-list__count">{fmtInt(o.count)}</span>
                        </button>
                      </li>
                    ))}
                  </ul>
                  <p className="field__hint">
                    Ohne Berufsklasse: <strong>{fmtInt(data.occupations_unclassified)}</strong> Anzeigen – sie fehlen in dieser Liste, nicht in der Suche.
                  </p>
                </section>
                <section>
                  <h3 className="subhead">Qualifikationen und Merkmale</h3>
                  {data.features.length === 0 ? <p className="muted">Keine erkannten Merkmale.</p> : null}
                  <ul className="facet-list">
                    {data.features.map((x) => (
                      <li key={x.key}>
                        <button type="button" className="facet-list__btn" disabled={f.features.includes(x.key)} onClick={() => update({ features: [...f.features, x.key] })} title="Als Filter übernehmen">
                          <span>
                            {x.label} <span className="muted">· davon verlangt {fmtInt(x.required)}</span>
                          </span>
                          <span className="facet-list__count">{fmtInt(x.count)}</span>
                        </button>
                      </li>
                    ))}
                  </ul>
                  <p className="field__hint">Die Erkennung ist regelbasiert und kann irren.</p>
                </section>
                <section>
                  <h3 className="subhead">Arbeitgeber</h3>
                  {data.employers.length === 0 ? <p className="muted">Keine Arbeitgeberangaben.</p> : null}
                  <ul className="facet-list">
                    {data.employers.map((x) => (
                      <li key={x.name}>
                        <button type="button" className="facet-list__btn" disabled={f.employer === x.name} onClick={() => update({ employer: x.name })} title="Als Filter übernehmen">
                          <span>{x.name}</span>
                          <span className="facet-list__count">{fmtInt(x.count)}</span>
                        </button>
                      </li>
                    ))}
                  </ul>
                  {data.kinds.length > 0 ? (
                    <>
                      <h3 className="subhead facets__kinds">Art der Anzeige</h3>
                      <ul className="facet-list">
                        {data.kinds.map((k) => (
                          <li key={k.kind} className="facet-list__row">
                            <span>{KIND_LABELS[k.kind] ?? k.kind}</span>
                            <span className="facet-list__count">{fmtInt(k.count)}</span>
                          </li>
                        ))}
                      </ul>
                    </>
                  ) : null}
                </section>
              </div>
            )}
          </Async>
        </div>
      ) : null}
    </details>
  );
}

export default function SearchPage() {
  const ctl = useFilters();
  const { filters, query } = ctl;
  const meta = useMetaFilters();
  const featureLabels = useFeatureLabels(meta.data);
  const sortId = useId();

  const page = Math.max(1, Number(ctl.getParam('page')) || 1);
  const hasQuery = filters.q.trim() !== '';
  const sortParam = ctl.getParam('sort');
  const sorts = (meta.data?.sorts ?? DEFAULT_SORTS).filter((s) => s !== 'relevance' || hasQuery);
  const sort = sortParam && sorts.includes(sortParam) ? sortParam : hasQuery ? 'relevance' : 'first_seen';
  const explicitSort = sortParam && sorts.includes(sortParam) ? sortParam : null;

  const listQuery = [query, explicitSort ? `sort=${explicitSort}` : '', page > 1 ? `page=${page}` : '', `page_size=${PAGE_SIZE}`].filter(Boolean).join('&');
  const results = useFetch<PostingListResponse>(withQuery('/api/postings', listQuery));
  const exportHref = withQuery('/api/postings/export.csv', [query, explicitSort ? `sort=${explicitSort}` : ''].filter(Boolean).join('&'));
  const activeCount = countActiveFilters(filters);

  return (
    <div className="page">
      <PageHeader
        title="Stellensuche"
        lead="Durchsucht die beobachteten Anzeigen aller freigegebenen Quellen. Jede Suche ist über die Adresszeile teilbar."
        actions={<SavedSearches ctl={ctl} sort={explicitSort} />}
      />
      <KindTabs value={filters.kindGroup} onChange={(kindGroup) => ctl.update({ kindGroup })} />
      <SearchBox ctl={ctl} />

      <FilterLayout ctl={ctl} meta={meta.data} metaError={meta.error?.message}>
        {(filterButton) => (
          <>
            <div className="toolbar">
              {filterButton}
              <div className="toolbar__grow">
                <ActiveFilters ctl={ctl} meta={meta.data} />
              </div>
            </div>

            <Async state={results} loadingLabel="Anzeigen werden gesucht …" errorTitle="Die Suche konnte nicht ausgeführt werden">
              {(data) => (
                <div className="stack">
                  <Card className="result-summary">
                    <div className="result-summary__grid">
                      <div className="stack stack--tight">
                        <p className="result-summary__count" role="status">
                          <strong>{fmtInt(data.total)}</strong> {data.total === 1 ? 'Anzeige' : 'Anzeigen'}
                          <span className="result-summary__basis"> · {data.scope.basis}</span>
                        </p>
                        <p className="result-summary__scope">
                          Durchsucht werden: {data.scope.searched_fields.join(', ')}. <strong>{data.scope.not_searched}</strong>
                        </p>
                        <p className="field__hint">Eine Anzeige kann mehrere Stellen betreffen; „erstmals beobachtet“ ist kein Veröffentlichungsdatum.</p>
                        {data.near ? (
                          <Alert tone="info" compact title={`Umkreissuche um ${data.near.name}`}>
                            {data.near.note}. Entfernungen beziehen sich auf diesen angenäherten Mittelpunkt, nicht auf eine Adresse.
                          </Alert>
                        ) : null}
                      </div>
                      <TotalsBox totals={data.totals} compact totalLabel="Treffer nach Ortszuordnung" onSelect={(g) => ctl.update({ geoClass: [g] })} />
                    </div>
                  </Card>

                  <FacetPanel ctl={ctl} query={query} />

                  <div className="toolbar">
                    <div className="field field--inline">
                      <label className="field__label" htmlFor={sortId}>
                        Sortierung
                      </label>
                      <select id={sortId} className="select" value={sort} onChange={(e) => ctl.setParams({ sort: e.target.value === (hasQuery ? 'relevance' : 'first_seen') ? null : e.target.value, page: null })}>
                        {sorts.map((s) => (
                          <option key={s} value={s}>
                            {SORT_LABELS[s] ?? s}
                          </option>
                        ))}
                      </select>
                    </div>
                    <div className="toolbar__grow" />
                    {data.total > 0 ? (
                      <a className="btn" href={exportHref} download="workforce-anzeigen.csv" title="Alle Treffer dieser Suche als CSV-Datei (höchstens 50.000 Zeilen)">
                        <Icon name="download" />
                        CSV-Export
                      </a>
                    ) : null}
                  </div>

                  {data.items.length === 0 ? (
                    <Card>
                      {activeCount === 0 ? (
                        <EmptyState title={`Noch keine Anzeigen im Bereich „${KIND_GROUP_LABELS[filters.kindGroup]}“`} icon="posting" action={<Link className="btn" to="/quellen">Zur Quellenverwaltung</Link>}>
                          Anzeigen erscheinen, sobald eine Quelle freigegeben ist und ein Scanlauf abgeschlossen wurde. Ausbildung und Praktika finden Sie
                          in den eigenen Reitern.
                        </EmptyState>
                      ) : (
                        <EmptyState title="Keine Anzeigen für diese Auswahl" icon="search" action={<Button onClick={ctl.reset}>Alle Filter zurücksetzen</Button>}>
                          Lockern Sie die Filter, prüfen Sie die Schreibweise oder aktivieren Sie „Ähnliche Schreibweisen“. Die Suche umfasst nur die
                          gespeicherten Rumpfdaten der freigegebenen Quellen – nicht den Volltext und nicht den gesamten Stellenmarkt.
                        </EmptyState>
                      )}
                    </Card>
                  ) : (
                    <ol className="posting-list" aria-label="Trefferliste">
                      {data.items.map((item) => (
                        <li key={item.id}>
                          <PostingCard item={item} featureLabels={featureLabels} />
                        </li>
                      ))}
                    </ol>
                  )}

                  <Pagination page={data.page} pageSize={data.page_size} total={data.total} onPage={(p) => { ctl.setParams({ page: p > 1 ? String(p) : null }); window.scrollTo({ top: 0 }); }} />
                </div>
              )}
            </Async>
          </>
        )}
      </FilterLayout>
      <FramingNote />
    </div>
  );
}
