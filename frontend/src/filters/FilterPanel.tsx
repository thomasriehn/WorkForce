import { type ReactNode, useEffect, useId, useMemo, useState } from 'react';
import { api } from '../api/client';
import type { KldbHit, MetaFilters, RegionListItem } from '../api/types';
import { Dialog } from '../components/Dialog';
import { Typeahead, type TypeaheadOption } from '../components/Typeahead';
import { Button, Chip, Segmented } from '../components/ui';
import { addDaysIso, fmtDate, todayIso } from '../lib/format';
import {
  CONFIG_STATUS_LABELS,
  CONTRACT_LABELS,
  FEATURE_TYPE_LABELS,
  GEO_CLASS_SHORT,
  POSTING_STATUS_LABELS,
  REMOTE_LABELS,
  WORKING_TIME_LABELS,
} from '../lib/labels';
import { rememberKldb, useDistrictNames, useKldbNames } from '../lib/lookups';
import { useMediaQuery } from '../lib/useMediaQuery';
import { type ContractTerm, countActiveFilters, DEFAULT_RADIUS_KM, type Filters, RADIUS_OPTIONS } from './model';
import type { FilterController } from './useFilters';

const KLDB_LEVEL_LABELS: Record<number, string> = {
  1: 'Berufsbereich',
  2: 'Berufshauptgruppe',
  3: 'Berufsgruppe',
  4: 'Berufsuntergruppe',
  5: 'Berufsgattung',
};

function toggle(list: string[], value: string): string[] {
  return list.includes(value) ? list.filter((v) => v !== value) : [...list, value];
}

// --- Bausteine ----------------------------------------------------------------------------------------
function Group({ title, count, children, defaultOpen }: { title: string; count?: number; children: ReactNode; defaultOpen?: boolean }) {
  // Gruppen mit gesetzten Filtern starten geöffnet; danach entscheidet allein die Person (kein Zuklappen beim Abwählen).
  const [open, setOpen] = useState(Boolean(defaultOpen) || (count ?? 0) > 0);
  return (
    <details className="filter-group" open={open} onToggle={(e) => setOpen(e.currentTarget.open)}>
      <summary className="filter-group__summary">
        <span>{title}</span>
        {count ? (
          <span className="filter-group__count" aria-label={`${count} gesetzt`}>
            {count}
          </span>
        ) : null}
      </summary>
      <div className="filter-group__body">{children}</div>
    </details>
  );
}

interface CheckOption {
  value: string;
  label: string;
  hint?: string;
}

function CheckList({ legend, options, selected, onChange, scroll, hideLegend }: { legend: string; options: CheckOption[]; selected: string[]; onChange: (next: string[]) => void; scroll?: boolean; hideLegend?: boolean }) {
  return (
    <fieldset className="checklist">
      <legend className={hideLegend ? 'visually-hidden' : 'field__label'}>{legend}</legend>
      <div className={scroll ? 'checklist__items checklist__items--scroll' : 'checklist__items'}>
        {options.map((o) => (
          <label key={o.value} className="check">
            <input type="checkbox" checked={selected.includes(o.value)} onChange={() => onChange(toggle(selected, o.value))} />
            <span className="check__label">
              {o.label}
              {o.hint ? <span className="check__hint">{o.hint}</span> : null}
            </span>
          </label>
        ))}
      </div>
    </fieldset>
  );
}

/** Textfeld, das erst bei Enter oder beim Verlassen übernimmt – so entsteht nicht je Tastendruck ein Verlaufseintrag. */
function CommitInput({ label, value, onCommit, placeholder, hint, type = 'text', inputMode, maxLength }: { label: string; value: string; onCommit: (value: string) => void; placeholder?: string; hint?: ReactNode; type?: string; inputMode?: 'numeric' | 'text'; maxLength?: number }) {
  const id = useId();
  const [draft, setDraft] = useState(value);
  useEffect(() => setDraft(value), [value]);
  const commit = () => {
    if (draft.trim() !== value.trim()) onCommit(draft.trim());
  };
  return (
    <div className="field">
      <label className="field__label" htmlFor={id}>
        {label}
      </label>
      <input
        id={id}
        className="input"
        type={type}
        inputMode={inputMode}
        maxLength={maxLength}
        value={draft}
        placeholder={placeholder}
        onChange={(e) => setDraft(e.target.value)}
        onBlur={commit}
        onKeyDown={(e) => {
          if (e.key === 'Enter') {
            e.preventDefault();
            commit();
          }
        }}
      />
      {hint ? <p className="field__hint">{hint}</p> : null}
    </div>
  );
}

function DateInput({ label, value, onChange, max }: { label: string; value: string; onChange: (value: string) => void; max?: string }) {
  const id = useId();
  return (
    <div className="field">
      <label className="field__label" htmlFor={id}>
        {label}
      </label>
      <input id={id} className="input" type="date" value={value} max={max} onChange={(e) => onChange(e.target.value)} />
    </div>
  );
}

// --- Das Filterfeld ---------------------------------------------------------------------------------------
interface PanelProps {
  ctl: FilterController;
  meta: MetaFilters | undefined;
  metaError?: string | null;
}

/**
 * Gemeinsames Filterfeld für Stellensuche und Karte. Es schreibt ausschließlich in die Adresszeile
 * (über `ctl.update`), sodass Liste, Karte, Summen und Diagramme dieselben Filter verwenden.
 */
export function FilterPanel({ ctl, meta, metaError }: PanelProps) {
  const { filters: f, update } = ctl;
  const districts = useDistrictNames();
  const kldbNames = useKldbNames(f.kldb, meta);
  const [featureTerm, setFeatureTerm] = useState('');
  const featureSearchId = useId();
  const radiusId = useId();
  const today = todayIso();

  const featureGroups = useMemo(() => {
    const term = featureTerm.trim().toLocaleLowerCase('de');
    const groups = new Map<string, CheckOption[]>();
    for (const ft of meta?.features ?? []) {
      const hit = !term || ft.label.toLocaleLowerCase('de').includes(term) || ft.synonyms.some((s) => s.toLocaleLowerCase('de').includes(term));
      if (!hit && !f.features.includes(ft.key)) continue;
      const list = groups.get(ft.type) ?? [];
      list.push({ value: ft.key, label: ft.label });
      groups.set(ft.type, list);
    }
    return [...groups.entries()];
  }, [meta, featureTerm, f.features]);

  const sourceOptions = useMemo<CheckOption[]>(() => {
    const rank = (s: MetaFilters['sources'][number]) => (s.config_status === 'active' ? 0 : s.has_adapter ? 1 : 2);
    return [...(meta?.sources ?? [])]
      .sort((a, b) => rank(a) - rank(b) || a.name.localeCompare(b.name, 'de'))
      .map((s) => ({ value: String(s.id), label: s.name, hint: CONFIG_STATUS_LABELS[s.config_status] ?? s.config_status }));
  }, [meta]);

  const statusLabels = meta?.status_labels ?? POSTING_STATUS_LABELS;
  const center = f.plz || f.place;

  const searchKldb = async (term: string, signal: AbortSignal): Promise<TypeaheadOption<KldbHit>[]> => {
    const hits = await api.get<KldbHit[]>('/api/meta/kldb', { query: { q: term }, signal });
    const seen = new Set<string>();
    const out: TypeaheadOption<KldbHit>[] = [];
    for (const h of hits) {
      const id = `${h.code}|${h.from_title ? h.name : ''}`;
      if (seen.has(id)) continue;
      seen.add(id);
      out.push({
        id,
        label: h.from_title ? h.name : `${h.code} ${h.name}`,
        hint: h.from_title ? `Berufsbenennung → KldB ${h.code}` : (KLDB_LEVEL_LABELS[h.level] ?? `${h.level}-Steller`),
        value: h,
        disabled: f.kldb.includes(h.code),
      });
    }
    return out;
  };

  const searchDistricts = async (term: string, signal: AbortSignal): Promise<TypeaheadOption<RegionListItem>[]> => {
    const rows = await api.get<RegionListItem[]>('/api/regions', { query: { level: 'district', q: term }, signal });
    return rows.slice(0, 30).map((r) => ({
      id: r.key,
      label: r.name,
      hint: [r.type_label, r.key].filter(Boolean).join(' · '),
      value: r,
      disabled: f.kreise.includes(r.key),
    }));
  };

  return (
    <div className="filter-panel">
      {metaError ? (
        <p className="form-error" role="alert">
          Die Filterlisten konnten nicht geladen werden: {metaError}
        </p>
      ) : null}

      <Group title="Beruf und Berufsgruppe" count={f.kldb.length} defaultOpen>
        <Typeahead<KldbHit>
          label="Beruf suchen (KldB 2010)"
          placeholder="z. B. Pflege, Informatik oder 8130"
          search={searchKldb}
          emptyText="Keine passende Berufsklasse gefunden"
          hint="Bezeichnung oder Code. Ein kürzerer Code schließt alle darunterliegenden Berufe ein."
          onSelect={(o) => {
            if (!o.value.from_title) rememberKldb(o.value.code, o.value.name);
            update({ kldb: [...f.kldb, o.value.code] });
          }}
        />
        {f.kldb.length > 0 ? (
          <div className="chip-row">
            {f.kldb.map((code) => (
              <Chip key={code} tone="accent" onRemove={() => update({ kldb: f.kldb.filter((c) => c !== code) })} removeLabel={`Beruf ${code} entfernen`}>
                {code}
                {kldbNames.get(code) ? ` ${kldbNames.get(code)}` : ''}
              </Chip>
            ))}
          </div>
        ) : null}
      </Group>

      <Group title="Qualifikationen und Merkmale" count={f.features.length}>
        <div className="field">
          <label className="field__label" htmlFor={featureSearchId}>
            Merkmal suchen
          </label>
          <input id={featureSearchId} className="input" type="search" value={featureTerm} placeholder="z. B. Führerschein, Englisch, Python" onChange={(e) => setFeatureTerm(e.target.value)} />
        </div>
        {meta && meta.features.length === 0 ? <p className="field__hint">Das Merkmalswörterbuch ist leer.</p> : null}
        <div className="feature-groups">
          {featureGroups.map(([type, options]) => (
            <CheckList
              key={type}
              legend={meta?.feature_types?.[type] ?? FEATURE_TYPE_LABELS[type] ?? type}
              options={options}
              selected={f.features}
              onChange={(next) => update({ features: next })}
            />
          ))}
          {meta && meta.features.length > 0 && featureGroups.length === 0 ? <p className="field__hint">Kein Merkmal passt zu „{featureTerm}“.</p> : null}
        </div>
        <Segmented
          label="Verknüpfung mehrerer Merkmale"
          size="sm"
          value={f.featuresMode}
          options={[
            { value: 'and', label: 'UND – alle', title: 'Anzeigen müssen alle gewählten Merkmale enthalten' },
            { value: 'or', label: 'ODER – mindestens eines', title: 'Anzeigen müssen mindestens eines der gewählten Merkmale enthalten' },
          ]}
          onChange={(v) => update({ featuresMode: v })}
        />
        <label className="check">
          <input type="checkbox" checked={f.featuresRequired} onChange={(e) => update({ featuresRequired: e.target.checked })} />
          <span className="check__label">
            nur ausdrücklich verlangt
            <span className="check__hint">ohne „erwünscht“, „verneint“ und „unklar“</span>
          </span>
        </label>
      </Group>

      <Group title="Region" count={f.states.length + f.kreise.length + (center ? 1 : 0)} defaultOpen>
        <CheckList
          legend="Bundesland"
          options={(meta?.states ?? []).map((s) => ({ value: s.key, label: s.name }))}
          selected={f.states}
          onChange={(next) => update({ states: next })}
          scroll
        />
        {meta && meta.states.length === 0 ? <p className="field__hint">Noch keine Länder importiert (Gebietsdaten fehlen).</p> : null}
        <Typeahead<RegionListItem>
          label="Kreis oder kreisfreie Stadt"
          placeholder="Name oder Kreisschlüssel"
          search={searchDistricts}
          emptyText="Kein Kreis gefunden"
          onSelect={(o) => update({ kreise: [...f.kreise, o.value.key] })}
        />
        {f.kreise.length > 0 ? (
          <div className="chip-row">
            {f.kreise.map((key) => (
              <Chip key={key} tone="accent" onRemove={() => update({ kreise: f.kreise.filter((k) => k !== key) })} removeLabel={`Kreis ${districts.get(key)?.name ?? key} entfernen`}>
                {districts.get(key)?.name ?? `Kreis ${key}`}
              </Chip>
            ))}
          </div>
        ) : null}
        <div className="field-row">
          <CommitInput
            label="Ort oder PLZ"
            value={center}
            placeholder="z. B. Kassel oder 34117"
            onCommit={(v) => {
              if (!v) update({ place: '', plz: '', radiusKm: null });
              else if (/^\d{5}$/.test(v)) update({ plz: v, place: '', radiusKm: f.radiusKm ?? DEFAULT_RADIUS_KM });
              else update({ place: v, plz: '', radiusKm: f.radiusKm ?? DEFAULT_RADIUS_KM });
            }}
          />
          <div className="field field--narrow">
            <label className="field__label" htmlFor={radiusId}>
              Umkreis
            </label>
            <select id={radiusId} className="select" value={String(f.radiusKm ?? DEFAULT_RADIUS_KM)} disabled={!center} onChange={(e) => update({ radiusKm: Number(e.target.value) })}>
              {[...new Set([...RADIUS_OPTIONS, f.radiusKm ?? DEFAULT_RADIUS_KM])]
                .sort((a, b) => a - b)
                .map((r) => (
                  <option key={r} value={r}>
                    {r} km
                  </option>
                ))}
            </select>
          </div>
        </div>
        <p className="field__hint">Der Mittelpunkt ist angenähert (Gemeindemittelpunkt aus der lokalen Ortsreferenz, kein Adressabgleich).</p>
      </Group>

      <Group title="Zeitraum" count={(f.dateFrom || f.dateTo ? 1 : 0) + (f.asOf ? 1 : 0)}>
        <Segmented
          label="Datum bezieht sich auf"
          size="sm"
          value={f.dateField}
          options={[
            { value: 'first_seen', label: 'erstmals beobachtet' },
            { value: 'date_posted', label: 'veröffentlicht laut Quelle' },
          ]}
          onChange={(v) => update({ dateField: v })}
        />
        <div className="field-row">
          <DateInput label="von" value={f.dateFrom} max={f.dateTo || today} onChange={(v) => update({ dateFrom: v })} />
          <DateInput label="bis" value={f.dateTo} max={today} onChange={(v) => update({ dateTo: v })} />
        </div>
        <div className="preset-row" role="group" aria-label="Zeitraum-Vorgaben">
          {[7, 30, 90].map((d) => (
            <button key={d} type="button" className="btn btn--ghost btn--sm" onClick={() => update({ dateFrom: addDaysIso(today, -(d - 1)), dateTo: '' })}>
              letzte {d} Tage
            </button>
          ))}
          {f.dateFrom || f.dateTo ? (
            <button type="button" className="btn btn--ghost btn--sm" onClick={() => update({ dateFrom: '', dateTo: '' })}>
              Zeitraum löschen
            </button>
          ) : null}
        </div>
        <p className="field__hint">
          {f.dateField === 'first_seen'
            ? '„Erstmals beobachtet“ ist der Tag, an dem WorkForce die Anzeige zum ersten Mal gesehen hat – kein Veröffentlichungsdatum.'
            : 'Das Veröffentlichungsdatum stammt von der Quelle und fehlt bei vielen Anzeigen; Anzeigen ohne Angabe fallen aus diesem Filter heraus.'}
        </p>
        <DateInput label="Bestand zum Stichtag (optional)" value={f.asOf} max={today} onChange={(v) => update({ asOf: v })} />
        {f.asOf ? <p className="field__hint">Gezeigt wird der beobachtete Bestand am {fmtDate(f.asOf)} mit den damals gültigen Angaben. Der Statusfilter wirkt dabei nicht.</p> : null}
      </Group>

      <Group title="Anzeigenstatus" count={f.status.length}>
        <CheckList
          legend="Anzeigenstatus"
          hideLegend
          options={Object.entries(statusLabels).map(([value, label]) => ({ value, label }))}
          selected={f.status}
          onChange={(next) => update({ status: next })}
        />
        <p className="field__hint">Ohne Auswahl: aktuell beobachteter Bestand („aktiv beobachtet“ und „nicht erneut beobachtet“).</p>
      </Group>

      <Group title="Quelle" count={f.sources.length}>
        <CheckList legend="Quelle" hideLegend options={sourceOptions} selected={f.sources} onChange={(next) => update({ sources: next })} scroll />
        <p className="field__hint">Nur freigegebene Quellen liefern Anzeigen. Eine zusammengeführte Anzeige kann aus mehreren Quellen stammen.</p>
      </Group>

      <Group title="Arbeitszeit, Befristung, Remote" count={f.workingTime.length + f.remote.length + (f.contractTerm ? 1 : 0)}>
        <CheckList legend="Arbeitszeit" options={Object.entries(WORKING_TIME_LABELS).map(([value, label]) => ({ value, label }))} selected={f.workingTime} onChange={(next) => update({ workingTime: next })} />
        <Segmented<ContractTerm>
          label="Befristung"
          size="sm"
          value={f.contractTerm}
          options={[
            { value: '', label: 'egal' },
            { value: 'unbefristet', label: CONTRACT_LABELS.unbefristet ?? 'unbefristet' },
            { value: 'befristet', label: CONTRACT_LABELS.befristet ?? 'befristet' },
          ]}
          onChange={(v) => update({ contractTerm: v })}
        />
        <CheckList legend="Remote-Status" options={Object.entries(REMOTE_LABELS).map(([value, label]) => ({ value, label }))} selected={f.remote} onChange={(next) => update({ remote: next })} />
        <p className="field__hint">Fehlt die Angabe in der Anzeige, bleibt sie „unbekannt“ und wird nicht geschätzt.</p>
      </Group>

      <Group title="Ortszuordnung und Arbeitgeber" count={f.geoClass.length + (f.employer ? 1 : 0)}>
        <CheckList legend="Geografische Zuordnung der Anzeige" options={Object.entries(GEO_CLASS_SHORT).map(([value, label]) => ({ value, label }))} selected={f.geoClass} onChange={(next) => update({ geoClass: next })} />
        <CommitInput label="Arbeitgeber (genaue Bezeichnung)" value={f.employer} placeholder="z. B. Stadt Musterstadt" onCommit={(v) => update({ employer: v })} hint="Vergleicht die normalisierte Bezeichnung; für eine freie Suche das Suchfeld verwenden." />
      </Group>

      <div className="filter-panel__footer">
        <Button variant="ghost" size="sm" icon="refresh" onClick={ctl.reset} disabled={countActiveFilters(f) === 0}>
          Alle Filter zurücksetzen
        </Button>
      </div>
    </div>
  );
}

// --- Rahmen: Seitenleiste auf breiten Bildschirmen, einfahrendes Bedienfeld auf schmalen ---------------------
interface LayoutProps {
  ctl: FilterController;
  meta: MetaFilters | undefined;
  metaError?: string | null;
  /** Der Seiteninhalt erhält die Schaltfläche, die das Bedienfeld öffnet (null, wenn die Filter daneben stehen). */
  children: (filterButton: ReactNode) => ReactNode;
}

export function FilterLayout({ ctl, meta, metaError, children }: LayoutProps) {
  const wide = useMediaQuery('(min-width: 1280px)');
  const [open, setOpen] = useState(false);
  const active = countActiveFilters(ctl.filters);

  useEffect(() => {
    if (wide) setOpen(false);
  }, [wide]);

  const button = wide ? null : (
    <Button icon="filter" onClick={() => setOpen(true)} aria-haspopup="dialog">
      Filter{active > 0 ? ` (${active})` : ''}
    </Button>
  );

  return (
    <div className={wide ? 'with-filters' : 'with-filters with-filters--stacked'}>
      {wide ? (
        <aside className="filter-aside" aria-label="Filter">
          <h2 className="filter-aside__title">Filter</h2>
          <FilterPanel ctl={ctl} meta={meta} metaError={metaError} />
        </aside>
      ) : (
        <Dialog
          variant="drawer"
          open={open}
          onClose={() => setOpen(false)}
          title="Filter"
          footer={
            <Button variant="primary" onClick={() => setOpen(false)}>
              Ergebnisse anzeigen
            </Button>
          }
        >
          <FilterPanel ctl={ctl} meta={meta} metaError={metaError} />
        </Dialog>
      )}
      <div className="with-filters__main">{children(button)}</div>
    </div>
  );
}

// --- Gesetzte Filter als entfernbare Marken -------------------------------------------------------------------
export function ActiveFilters({ ctl, meta }: { ctl: FilterController; meta: MetaFilters | undefined }) {
  const { filters: f, update } = ctl;
  const districts = useDistrictNames();
  const kldbNames = useKldbNames(f.kldb, meta);
  const chips: { key: string; label: string; remove: () => void }[] = [];
  const stateName = (key: string) => meta?.states.find((s) => s.key === key)?.name ?? `Land ${key}`;
  const featureName = (key: string) => meta?.features.find((x) => x.key === key)?.label ?? key;
  const sourceName = (id: string) => meta?.sources.find((s) => String(s.id) === id)?.name ?? `Quelle ${id}`;
  const without = (list: string[], value: string) => list.filter((v) => v !== value);

  if (f.q.trim()) chips.push({ key: 'q', label: `Suche: ${f.q.trim()}`, remove: () => update({ q: '', fuzzy: false }) });
  for (const c of f.kldb) chips.push({ key: `kldb-${c}`, label: `Beruf: ${c}${kldbNames.get(c) ? ` ${kldbNames.get(c)}` : ''}`, remove: () => update({ kldb: without(f.kldb, c) }) });
  for (const k of f.features) chips.push({ key: `ft-${k}`, label: `Merkmal: ${featureName(k)}`, remove: () => update({ features: without(f.features, k) }) });
  if (f.features.length > 1 && f.featuresMode === 'or') chips.push({ key: 'ftmode', label: 'Merkmale: mindestens eines', remove: () => update({ featuresMode: 'and' }) });
  if (f.features.length > 0 && f.featuresRequired) chips.push({ key: 'ftreq', label: 'nur ausdrücklich verlangt', remove: () => update({ featuresRequired: false }) });
  for (const s of f.states) chips.push({ key: `st-${s}`, label: stateName(s), remove: () => update({ states: without(f.states, s) }) });
  for (const k of f.kreise) chips.push({ key: `kr-${k}`, label: districts.get(k)?.name ?? `Kreis ${k}`, remove: () => update({ kreise: without(f.kreise, k) }) });
  if (f.plz || f.place) chips.push({ key: 'near', label: `Umkreis ${f.radiusKm ?? DEFAULT_RADIUS_KM} km um ${f.plz || f.place}`, remove: () => update({ place: '', plz: '', radiusKm: null }) });
  if (f.dateFrom || f.dateTo) {
    const what = f.dateField === 'date_posted' ? 'veröffentlicht laut Quelle' : 'erstmals beobachtet';
    const range = f.dateFrom && f.dateTo ? `${fmtDate(f.dateFrom)} – ${fmtDate(f.dateTo)}` : f.dateFrom ? `ab ${fmtDate(f.dateFrom)}` : `bis ${fmtDate(f.dateTo)}`;
    chips.push({ key: 'date', label: `${what}: ${range}`, remove: () => update({ dateFrom: '', dateTo: '' }) });
  }
  if (f.asOf) chips.push({ key: 'asof', label: `Bestand am ${fmtDate(f.asOf)}`, remove: () => update({ asOf: '' }) });
  for (const s of f.status) chips.push({ key: `status-${s}`, label: `Status: ${meta?.status_labels[s] ?? POSTING_STATUS_LABELS[s as keyof typeof POSTING_STATUS_LABELS] ?? s}`, remove: () => update({ status: without(f.status, s) }) });
  for (const s of f.sources) chips.push({ key: `src-${s}`, label: `Quelle: ${sourceName(s)}`, remove: () => update({ sources: without(f.sources, s) }) });
  for (const w of f.workingTime) chips.push({ key: `wt-${w}`, label: WORKING_TIME_LABELS[w] ?? w, remove: () => update({ workingTime: without(f.workingTime, w) }) });
  if (f.contractTerm) chips.push({ key: 'ct', label: CONTRACT_LABELS[f.contractTerm] ?? f.contractTerm, remove: () => update({ contractTerm: '' }) });
  for (const r of f.remote) chips.push({ key: `rm-${r}`, label: `Remote: ${REMOTE_LABELS[r] ?? r}`, remove: () => update({ remote: without(f.remote, r) }) });
  for (const g of f.geoClass) chips.push({ key: `geo-${g}`, label: `Ort: ${GEO_CLASS_SHORT[g as keyof typeof GEO_CLASS_SHORT] ?? g}`, remove: () => update({ geoClass: without(f.geoClass, g) }) });
  if (f.employer) chips.push({ key: 'emp', label: `Arbeitgeber: ${f.employer}`, remove: () => update({ employer: '' }) });

  if (chips.length === 0) return null;
  return (
    <div className="active-filters" aria-label="Gesetzte Filter">
      <span className="active-filters__label">Gesetzte Filter:</span>
      {chips.map((c) => (
        <Chip key={c.key} onRemove={c.remove} removeLabel={`Filter „${c.label}“ entfernen`}>
          {c.label}
        </Chip>
      ))}
      <button type="button" className="link-button" onClick={ctl.reset}>
        alle zurücksetzen
      </button>
    </div>
  );
}

export type { Filters };
