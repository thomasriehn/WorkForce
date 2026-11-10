import { useMemo, useState } from 'react';
import { Bar, BarChart, CartesianGrid, Line, LineChart, ReferenceArea, ReferenceLine, ResponsiveContainer, Tooltip, XAxis, YAxis } from 'recharts';
import type { TimeSeries, TimeSeriesPoint } from '../api/types';
import { EmptyState, TableWrap } from '../components/ui';
import { fmtDate, fmtDayShort, fmtInt } from '../lib/format';
import { RUN_QUALITY_LABELS, TIMELINE_KIND_LABELS } from '../lib/labels';
import { VIZ } from '../lib/viz';

interface Props {
  series: TimeSeries;
  /** Kompakte Variante für Seitenleisten (niedrigere Diagramme, ohne Tabellenumschalter). */
  compact?: boolean;
  /** Für die Beschriftung: worauf sich die Reihe bezieht. */
  subject?: string;
}

interface Row {
  date: string;
  stock: number | null;
  firstSeen: number;
  baseline: number;
  leftNeg: number;
  point: TimeSeriesPoint;
}

const Y_AXIS_WIDTH = 56;
const MARGIN = { top: 8, right: 12, bottom: 0, left: 0 };

const DEFINITION_LABELS: Record<string, string> = {
  stock: 'Bekannter Bestand',
  first_seen: 'Erstmals beobachtet',
  baseline: 'Bei Bestandsaufnahme erfasst',
  changed: 'Fachlich geändert',
  left: 'Aus dem Bestand gefallen',
  run_quality: 'Laufqualität',
};

function TooltipBody({ row, provisional }: { row: Row; provisional: boolean }) {
  const p = row.point;
  return (
    <div className="chart-tip">
      <p className="chart-tip__title">{fmtDate(p.date)}</p>
      <dl className="chart-tip__rows">
        <div>
          <dt>
            <span className="key key--line" style={{ background: VIZ.stock }} />
            Bekannter Bestand
          </dt>
          <dd>{p.stock === null ? 'nicht berechnet' : fmtInt(p.stock)}</dd>
        </div>
        <div>
          <dt>
            <span className="key" style={{ background: VIZ.firstSeen }} />
            Erstmals beobachtet
          </dt>
          <dd>{fmtInt(p.first_seen)}</dd>
        </div>
        {p.baseline > 0 ? (
          <div>
            <dt>
              <span className="key" style={{ background: VIZ.baseline }} />
              Bei Bestandsaufnahme erfasst
            </dt>
            <dd>{fmtInt(p.baseline)}</dd>
          </div>
        ) : null}
        <div>
          <dt>
            <span className="key" style={{ background: VIZ.left }} />
            Aus dem Bestand gefallen
          </dt>
          <dd>{fmtInt(p.left)}</dd>
        </div>
        <div>
          <dt>Fachlich geändert</dt>
          <dd>{fmtInt(p.changed)}</dd>
        </div>
        {p.republished + p.reactivated > 0 ? (
          <div>
            <dt>Erneut veröffentlicht / reaktiviert</dt>
            <dd>
              {fmtInt(p.republished)} / {fmtInt(p.reactivated)}
            </dd>
          </div>
        ) : null}
      </dl>
      <p className="chart-tip__note">
        Läufe: {RUN_QUALITY_LABELS[p.run_quality] ?? p.run_quality}
        {provisional ? ' · Bestand noch vorläufig' : ''}
      </p>
    </div>
  );
}

/**
 * Zeitreihe in zwei Feldern mit gemeinsamer Zeitachse (bewusst keine zweite y-Achse):
 * oben der bekannte Bestand, unten die täglichen Zu- und Abgänge. Bestandsaufnahmen werden grau
 * und getrennt von echten Erstbeobachtungen gezeigt, Datenlücken in einem Qualitätsband markiert.
 */
export function TimeSeriesChart({ series, compact, subject }: Props) {
  const [showTable, setShowTable] = useState(false);

  const rows = useMemo<Row[]>(
    () =>
      series.points
        .filter((p) => !p.before_start)
        .map((p) => ({ date: p.date, stock: p.stock, firstSeen: p.first_seen, baseline: p.baseline, leftNeg: p.left > 0 ? -p.left : 0, point: p })),
    [series],
  );
  const byDate = useMemo(() => new Map(rows.map((r) => [r.date, r])), [rows]);

  if (rows.length === 0) {
    return (
      <EmptyState title="Noch keine Zeitreihe" icon="clock" compact={compact}>
        Die Zeitreihe beginnt mit dem ersten regulären Scanlauf einer freigegebenen Quelle. Für die Zeit davor werden keine Werte
        angenommen.
      </EmptyState>
    );
  }

  const provisionalCount = Math.min(series.provisional_days, rows.length);
  const provisionalFrom = provisionalCount > 0 ? rows[rows.length - provisionalCount]?.date : undefined;
  const lastDate = rows[rows.length - 1]?.date;
  const provisionalDates = new Set(rows.slice(rows.length - provisionalCount).map((r) => r.date));
  const hasBaseline = rows.some((r) => r.baseline > 0);
  const hasGaps = rows.some((r) => r.point.run_quality !== 'complete');
  const notes = series.notes.filter((n) => byDate.has(n.date));
  const stockHeight = compact ? 150 : 210;
  const eventHeight = compact ? 120 : 160;

  const tooltip = ({ active, label }: { active?: boolean; label?: string | number }) => {
    const row = active && typeof label === 'string' ? byDate.get(label) : undefined;
    return row ? <TooltipBody row={row} provisional={provisionalDates.has(row.date)} /> : null;
  };

  const xAxis = (hidden: boolean) => (
    <XAxis
      dataKey="date"
      scale="band"
      tickFormatter={fmtDayShort}
      tick={hidden ? false : { fill: VIZ.tick, fontSize: 12 }}
      tickLine={false}
      axisLine={{ stroke: VIZ.axis }}
      minTickGap={28}
      height={hidden ? 6 : 28}
    />
  );

  return (
    <figure className="ts-chart" aria-label={`Zeitreihe${subject ? ` – ${subject}` : ''}: ${fmtDate(series.from)} bis ${fmtDate(series.to)}`}>
      <ul className="chart-legend" aria-label="Legende">
        <li>
          <span className="key key--line" style={{ background: VIZ.stock }} />
          Bekannter Bestand
        </li>
        <li>
          <span className="key" style={{ background: VIZ.firstSeen }} />
          Erstmals beobachtet
        </li>
        {hasBaseline ? (
          <li>
            <span className="key" style={{ background: VIZ.baseline }} />
            Bei Bestandsaufnahme erfasst (keine Neuveröffentlichungen)
          </li>
        ) : null}
        <li>
          <span className="key" style={{ background: VIZ.left }} />
          Aus dem Bestand gefallen
        </li>
        {provisionalFrom ? (
          <li>
            <span className="key key--provisional" />
            vorläufig (letzte {series.provisional_days} Tage)
          </li>
        ) : null}
      </ul>

      <p className="ts-chart__panel-title">Bekannter Bestand (Anzeigen)</p>
      <div className="ts-chart__plot" style={{ height: stockHeight }}>
        <ResponsiveContainer width="100%" height="100%">
          <LineChart data={rows} margin={MARGIN} syncId="wf-timeseries">
            <CartesianGrid stroke={VIZ.grid} vertical={false} />
            {xAxis(true)}
            <YAxis width={Y_AXIS_WIDTH} tick={{ fill: VIZ.tick, fontSize: 12 }} tickLine={false} axisLine={false} tickFormatter={(v: number) => fmtInt(v)} allowDecimals={false} domain={[0, 'auto']} />
            {provisionalFrom && lastDate ? <ReferenceArea x1={provisionalFrom} x2={lastDate} fill="#17202c" fillOpacity={0.05} strokeOpacity={0} ifOverflow="hidden" /> : null}
            {notes.map((n, i) => (
              <ReferenceLine key={`${n.date}-${i}`} x={n.date} stroke={VIZ.tick} strokeWidth={1} strokeDasharray="2 3" />
            ))}
            <Tooltip content={tooltip} cursor={{ stroke: VIZ.axis, strokeWidth: 1 }} isAnimationActive={false} />
            <Line type="linear" dataKey="stock" stroke={VIZ.stock} strokeWidth={2} dot={rows.length <= 31 ? { r: 2.5, fill: VIZ.stock, strokeWidth: 0 } : false} activeDot={{ r: 5, stroke: VIZ.surface, strokeWidth: 2 }} connectNulls isAnimationActive={false} />
          </LineChart>
        </ResponsiveContainer>
      </div>

      <div className="ts-chart__quality" style={{ marginLeft: Y_AXIS_WIDTH, marginRight: MARGIN.right }} aria-hidden="true">
        {rows.map((r) => (
          <span key={r.date} className={`ts-chart__q ts-chart__q--${r.point.run_quality}`} title={`${fmtDate(r.date)}: ${RUN_QUALITY_LABELS[r.point.run_quality] ?? ''}`} />
        ))}
      </div>
      {hasGaps ? (
        <ul className="chart-legend chart-legend--sub">
          <li>
            <span className="key ts-chart__q--partial" />
            Tag mit unvollständigem Lauf
          </li>
          <li>
            <span className="key ts-chart__q--none" />
            kein Lauf (Datenlücke)
          </li>
        </ul>
      ) : null}

      <p className="ts-chart__panel-title">Zugänge und Abgänge je Tag (Anzeigen)</p>
      <div className="ts-chart__plot" style={{ height: eventHeight }}>
        <ResponsiveContainer width="100%" height="100%">
          <BarChart data={rows} margin={MARGIN} stackOffset="sign" syncId="wf-timeseries" barCategoryGap="18%">
            <CartesianGrid stroke={VIZ.grid} vertical={false} />
            {xAxis(false)}
            <YAxis width={Y_AXIS_WIDTH} tick={{ fill: VIZ.tick, fontSize: 12 }} tickLine={false} axisLine={false} tickFormatter={(v: number) => fmtInt(Math.abs(v))} allowDecimals={false} />
            <ReferenceLine y={0} stroke={VIZ.axis} />
            <Tooltip content={tooltip} cursor={{ fill: '#17202c', fillOpacity: 0.05 }} isAnimationActive={false} />
            <Bar dataKey="firstSeen" stackId="flow" fill={VIZ.firstSeen} maxBarSize={18} isAnimationActive={false} />
            <Bar dataKey="baseline" stackId="flow" fill={VIZ.baseline} maxBarSize={18} isAnimationActive={false} />
            <Bar dataKey="leftNeg" stackId="flow" fill={VIZ.left} maxBarSize={18} isAnimationActive={false} />
          </BarChart>
        </ResponsiveContainer>
      </div>

      <figcaption className="ts-chart__caption">
        {series.sampled_every_days > 1 ? `Bestand in Abständen von ${series.sampled_every_days} Tagen berechnet. ` : ''}
        Der Bestand der letzten {series.provisional_days} Tage ist vorläufig: Ein Wegfall wird erst nach mehreren vollständigen Scans bestätigt
        und dann rückwirkend eingetragen.
      </figcaption>

      {notes.length > 0 ? (
        <ul className="ts-chart__notes">
          {notes.map((n, i) => (
            <li key={`${n.date}-${i}`}>
              <strong>{fmtDate(n.date)}</strong> · {TIMELINE_KIND_LABELS[n.kind] ?? n.kind}: {n.message}
            </li>
          ))}
        </ul>
      ) : null}

      <details className="disclosure">
        <summary>Definitionen der Reihen</summary>
        <dl className="definition-list">
          {Object.entries(series.definitions).map(([key, text]) => (
            <div key={key}>
              <dt>{DEFINITION_LABELS[key] ?? key}</dt>
              <dd>{text}</dd>
            </div>
          ))}
        </dl>
      </details>

      {compact ? null : (
        <div className="ts-chart__table-toggle">
          <button type="button" className="btn btn--ghost btn--sm" aria-expanded={showTable} onClick={() => setShowTable((v) => !v)}>
            {showTable ? 'Tabelle ausblenden' : 'Werte als Tabelle anzeigen'}
          </button>
        </div>
      )}
      {showTable ? (
        <TableWrap label="Zeitreihe als Tabelle">
          <table className="table table--compact table--numeric">
            <thead>
              <tr>
                <th scope="col">Datum</th>
                <th scope="col">Bestand</th>
                <th scope="col">Erstmals beobachtet</th>
                <th scope="col">Bestandsaufnahme</th>
                <th scope="col">Geändert</th>
                <th scope="col">Aus dem Bestand gefallen</th>
                <th scope="col">Läufe</th>
              </tr>
            </thead>
            <tbody>
              {[...rows].reverse().map((r) => (
                <tr key={r.date}>
                  <th scope="row">{fmtDate(r.date)}</th>
                  <td>{r.point.stock === null ? '–' : fmtInt(r.point.stock)}</td>
                  <td>{fmtInt(r.point.first_seen)}</td>
                  <td>{fmtInt(r.point.baseline)}</td>
                  <td>{fmtInt(r.point.changed)}</td>
                  <td>{fmtInt(r.point.left)}</td>
                  <td className="table__text">{RUN_QUALITY_LABELS[r.point.run_quality] ?? r.point.run_quality}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </TableWrap>
      ) : null}
    </figure>
  );
}
