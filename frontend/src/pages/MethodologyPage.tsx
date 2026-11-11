import type { ReactNode } from 'react';
import { Link } from 'react-router';
import type { MapMetrics, SourcesResponse, StatsOverview, SystemStatus } from '../api/types';
import { ConfigStatusBadge, HealthBadge } from '../components/domain';
import { ExternalLink } from '../components/ExternalLink';
import { Async, EmptyState, PageHeader, TableWrap } from '../components/ui';
import { fmtDate } from '../lib/format';
import { ACCESS_METHOD_LABELS, HEALTH_LABELS, METRIC_LABELS, UPDATE_CYCLE_LABELS } from '../lib/labels';
import { useFetch } from '../lib/useFetch';

const SECTIONS: { id: string; title: string }[] = [
  { id: 'gezaehlt', title: 'Was gezählt wird' },
  { id: 'dubletten', title: 'Quellanzeige und zusammengeführte Anzeige' },
  { id: 'status', title: 'Status einer Anzeige' },
  { id: 'orte', title: 'Zählregeln bei mehreren Arbeitsorten' },
  { id: 'zeitreihen', title: 'Zeitreihen und Vergleiche' },
  { id: 'statistik', title: 'Amtliche Statistik als Kontext' },
  { id: 'grenzen', title: 'Grenzen der Aussagekraft' },
  { id: 'quellen', title: 'Quellenregister' },
];

function Section({ id, title, children }: { id: string; title: string; children: ReactNode }) {
  return (
    <section className="card prose-card" id={id} aria-labelledby={`${id}-titel`}>
      <h2 className="card__title" id={`${id}-titel`}>
        {title}
      </h2>
      <div className="prose">{children}</div>
    </section>
  );
}

export default function MethodologyPage() {
  const metrics = useFetch<MapMetrics>('/api/map/metrics');
  const stats = useFetch<StatsOverview>('/api/stats/overview');
  const sources = useFetch<SourcesResponse>('/api/sources');
  const system = useFetch<SystemStatus>('/api/system/status');
  const threshold = system.data?.settings.missing_scans_threshold ?? 3;
  const staleDays = system.data?.settings.stale_after_days ?? 14;
  const smallCount = metrics.data?.small_count_threshold ?? system.data?.settings.small_count_threshold ?? 5;

  return (
    <div className="page methodology">
      <PageHeader
        title="Methodik und Quellen"
        lead="Wie WorkForce Stellenanzeigen beobachtet, zählt und einordnet – und was sich aus den Zahlen ablesen lässt und was nicht."
      />

      <div className="methodology__layout">
        <nav className="toc" aria-label="Inhalt dieser Seite">
          <p className="toc__title">Inhalt</p>
          <ol>
            {SECTIONS.map((s) => (
              <li key={s.id}>
                <a href={`#${s.id}`}>{s.title}</a>
              </li>
            ))}
          </ol>
        </nav>

        <div className="stack stack--loose">
          <Section id="gezaehlt" title="Was gezählt wird">
            <p>
              WorkForce beobachtet <strong>öffentlich ausgeschriebene Stellenanzeigen</strong> und wertet sie als <strong>Hinweis auf Arbeitskräftebedarf</strong>. Gezählt
              werden Anzeigen – nicht Arbeitsplätze, nicht offene Stellen und nicht Personen.
            </p>
            <ul>
              <li>Eine Anzeige kann mehrere Stellen betreffen („mehrere Sachbearbeiterinnen und Sachbearbeiter“) oder eine Dauerausschreibung sein.</li>
              <li>Derselbe Bedarf kann auf mehreren Portalen erscheinen. WorkForce führt solche Anzeigen zusammen, wo das sicher möglich ist.</li>
              <li>Nicht jede offene Stelle wird öffentlich ausgeschrieben, und nicht jede Ausschreibung landet auf einer beobachteten Quelle.</li>
              <li>Eine verschwundene Anzeige belegt nicht, dass die Stelle besetzt wurde.</li>
            </ul>
            <p>
              Die Zahlen sind deshalb <strong>weder die Anzahl offener Arbeitsplätze noch ein amtlicher Nachweis von Fachkräftemangel</strong>. Sie zeigen, wo und wofür
              in den beobachteten Quellen sichtbar gesucht wird.
            </p>
            <p>
              Stellen, <strong>Ausbildung und duales Studium</strong> sowie <strong>Praktika</strong> werden getrennt ausgewiesen, weil sie unterschiedliche Arten von
              Bedarf beschreiben.
            </p>
          </Section>

          <Section id="dubletten" title="Quellanzeige und zusammengeführte Anzeige">
            <p>
              Eine <strong>Quellanzeige</strong> ist eine Anzeige auf genau einem Portal. Eine <strong>zusammengeführte Anzeige</strong> fasst die Quellanzeigen zusammen,
              die nach festen Regeln denselben Bedarf beschreiben. Alle Zählungen beziehen sich auf zusammengeführte Anzeigen.
            </p>
            <p>Zwei Quellanzeigen werden nur zusammengeführt, wenn eine dieser Regeln greift:</p>
            <ol>
              <li>derselbe Arbeitgeber nennt dieselbe <strong>Stellenreferenz</strong> (Kennziffer),</li>
              <li>beide verweisen auf denselben <strong>Zielverweis beim Arbeitgeber</strong> (identische Adresse der Ausschreibung),</li>
              <li><strong>Arbeitgeber, Titel und Arbeitsort</strong> stimmen überein.</li>
            </ol>
            <p>
              Ein ähnlicher Titel allein genügt nie. Unsichere Paare – etwa bei abweichenden Arbeitsorten, parallelen Anzeigen auf derselben Quelle oder
              Personalvermittlungen – bleiben getrennt und erscheinen als Dublettenkandidaten in der Quellenverwaltung. Jede Zusammenführung ist mit Grund, Sicherheit
              und Regelstand gespeichert und lässt sich wieder lösen; ein gelöstes Paar wird nicht erneut automatisch vereinigt.
            </p>
            <p>
              „<strong>Erstmals beobachtet</strong>“ ist der Tag, an dem WorkForce eine Anzeige zum ersten Mal gesehen hat. Das ist <strong>kein Veröffentlichungsdatum</strong>:
              Die Anzeige kann schon länger online gewesen sein, besonders wenn sie bei einer Bestandsaufnahme erfasst wurde. Das Veröffentlichungsdatum laut Quelle wird
              getrennt geführt und bleibt „unbekannt“, wenn die Quelle es nicht nennt.
            </p>
          </Section>

          <Section id="status" title="Status einer Anzeige">
            <dl className="definition-list">
              <div>
                <dt>aktiv beobachtet</dt>
                <dd>Die Anzeige wurde im letzten vollständigen Scan ihres Suchbereichs gesehen.</dd>
              </div>
              <div>
                <dt>nicht erneut beobachtet</dt>
                <dd>Ein vollständiger Scan hat die Anzeige nicht wiedergefunden. Sie zählt weiter zum Bestand, bis genügend Scans vorliegen.</dd>
              </div>
              <div>
                <dt>vermutlich entfernt</dt>
                <dd>
                  Erst nach <strong>{threshold} vollständigen, vergleichbaren Scans</strong> desselben Suchbereichs ohne Sichtung. Auch dann bleibt es eine Ableitung und
                  kein Nachweis.
                </dd>
              </div>
              <div>
                <dt>als beendet beobachtet</dt>
                <dd>Die Quelle meldet die Anzeige ausdrücklich als beendet, oder das von ihr angekündigte Veröffentlichungsende ist erreicht.</dd>
              </div>
              <div>
                <dt>unbekannt/veraltet</dt>
                <dd>Seit mehr als {staleDays} Tagen gab es keinen vergleichbaren Scan. Über den Zustand der Anzeige lässt sich nichts sagen.</dd>
              </div>
            </dl>
            <p>
              <strong>Nie ein Hinweis auf eine entfernte Anzeige</strong> sind: CAPTCHA oder Bot-Schutz, Zugriffssperren (HTTP 403), Zeitüberschreitungen, Parserfehler,
              erreichte Seitenlimits und geänderte Suchbereiche. Ein solcher Lauf gilt als blockiert oder unvollständig; die Anzeigen behalten ihren Status. Sperren
              werden nicht umgangen.
            </p>
          </Section>

          <Section id="orte" title="Zählregeln bei mehreren Arbeitsorten">
            <p>Deutschlandweit zählt jede zusammengeführte Anzeige genau einmal. Für die Kreiskarte gelten drei Kennzahlen:</p>
            <Async state={metrics} compact loadingLabel="Formeln werden geladen …">
              {(m) => (
                <>
                  <dl className="definition-list">
                    <div>
                      <dt>{METRIC_LABELS.weighted}</dt>
                      <dd>{m.formulas.weighted}</dd>
                    </div>
                    <div>
                      <dt>{METRIC_LABELS.distinct}</dt>
                      <dd>{m.formulas.distinct}</dd>
                    </div>
                    <div>
                      <dt>{METRIC_LABELS.rate}</dt>
                      <dd>{m.formulas.rate_per_1000}</dd>
                    </div>
                  </dl>
                  <p className="field__hint">
                    Aktuelle Regelstände laut API: Dubletten <code>{m.rule_versions.dedup}</code>, Klassifikation <code>{m.rule_versions.classifier}</code>, Ortszuordnung{' '}
                    <code>{m.rule_versions.geo}</code>, Aggregation <code>{m.rule_versions.aggregate}</code>. Schwelle für „geringe Fallzahl“: weniger als {m.small_count_threshold}{' '}
                    Anzeigen.
                  </p>
                </>
              )}
            </Async>
            <ul>
              <li>
                Eine Anzeige mit <em>k</em> Kreisen zählt je Kreis <strong>1/k</strong> – aber nur, wenn <strong>alle</strong> ihre Arbeitsorte einem Kreis zugeordnet sind. So
                ergibt die Summe über alle Kreise wieder ganze Anzeigen.
              </li>
              <li>
                Die Zahl der <strong>unterschiedlichen Anzeigen je Kreis ist nicht addierbar</strong>: Eine Anzeige mit drei Arbeitsorten zählt in jedem der drei Kreise ganz.
              </li>
              <li>
                <strong>Teilweise ungeklärte</strong> Anzeigen (mindestens ein Ort nicht zuordenbar), <strong>ungeklärte</strong> Orte, <strong>deutschlandweit remote</strong>{' '}
                ausgeschriebene Stellen, Auslandsorte und Anzeigen ohne Ortsangabe werden getrennt ausgewiesen und keinem Kreis zugeschlagen.
              </li>
              <li>Hybride Stellen zählen an ihrem angegebenen Arbeitsort.</li>
              <li>Fehlt für einen Kreis der Bevölkerungswert, wird keine Quote gebildet. Die Karte zeigt dann „keine Daten“ (Schraffur) – nicht 0.</li>
              <li>Kreise mit weniger als {smallCount} Anzeigen sind als „geringe Fallzahl“ markiert, weil einzelne Anzeigen den Wert stark verändern.</li>
            </ul>
            <p>
              Die Ortszuordnung nutzt eine lokale Ortsreferenz (Gemeinden, Postleitzahlen) und keinen externen Geodienst. Mittelpunkte von Gemeinden sind Näherungen;
              mehrdeutige Ortsnamen bleiben ungeklärt, statt geraten zu werden.
            </p>
          </Section>

          <Section id="zeitreihen" title="Zeitreihen und Vergleiche">
            <ul>
              <li>
                Der <strong>bekannte Bestand</strong> eines Tages umfasst die Anzeigen, die an diesem Tag zum beobachteten Bestand zählten. Er ist für die{' '}
                <strong>letzten Tage vorläufig</strong>: Ein Wegfall wird erst nach mehreren vollständigen Scans bestätigt und dann rückwirkend auf den Tag nach der
                letzten Sichtung datiert.
              </li>
              <li>
                <strong>Bestandsaufnahmen sind keine Neuzugänge.</strong> Der erste Lauf einer Quelle oder einer neuen Suchbereichsversion findet alles, was schon online
                war. Diese Anzeigen werden als „bei Bestandsaufnahme erfasst“ gezählt und im Diagramm getrennt (grau) gezeigt.
              </li>
              <li>
                <strong>Datenlücken bleiben sichtbar.</strong> Tage ohne Lauf oder mit unvollständigem Lauf sind im Diagramm markiert; es wird nichts interpoliert.
              </li>
              <li>
                <strong>Vergleiche über 7, 30 oder 90 Tage</strong> gelten nur für Quellen, die an beiden Stichtagen mit demselben Suchbereich vollständig erfasst wurden. Neue
                Quellen, unvollständige Läufe und geänderte Suchbereiche werden vom Vergleich ausgeschlossen und mit Grund genannt. Gibt es keine vergleichbare Grundlage,
                zeigt WorkForce keinen Wert.
              </li>
              <li>Bei einem Ausgangswert von 0 wird nur die absolute Veränderung genannt, kein Prozentwert.</li>
              <li>Parser- und Regelwechsel werden als Vermerk festgehalten und zählen nicht als inhaltliche Änderung einer Anzeige.</li>
            </ul>
          </Section>

          <Section id="statistik" title="Amtliche Statistik als Kontext">
            <p>
              Bevölkerungs- und Arbeitsmarktdaten stehen als Kontext <strong>neben</strong> den Anzeigenzahlen. Sie werden nicht mit ihnen vermischt; einzige Ausnahme ist
              die ausgewiesene Quote „anteilige Anzeigen je 1.000 Einwohner (15 bis unter 65 Jahre)“.
            </p>
            <ul>
              <li>
                <strong>Berichtszeitraum und Abrufdatum sind verschiedene Angaben.</strong> Das angezeigte Alter bezieht sich auf das Ende des Berichtszeitraums.
              </li>
              <li>
                <strong>Revisionen bleiben erhalten.</strong> Korrigiert der Herausgeber einen Stand, wird die neue Fassung als Revision gespeichert; die alte bleibt abrufbar.
              </li>
              <li>
                <strong>Fehlwerte sind keine Nullen.</strong> Unterdrückte, unbekannte oder nicht erhobene Werte werden in Worten ausgewiesen und in der Karte schraffiert.
              </li>
              <li>Monats- und Jahreswerte werden <strong>nicht interpoliert</strong> und nicht fortgeschrieben.</li>
              <li>
                <strong>Arbeitslose und Arbeitsuchende sind unterschiedliche Größen.</strong> Berufsbezogene Anzeigenzahlen werden nicht durch alle Arbeitslosen oder
                Arbeitsuchenden geteilt – eine solche Quote würde eine Passung behaupten, die die Daten nicht hergeben.
              </li>
            </ul>
            <h3 className="subhead">Datensätze, Lizenzen und Quellenangaben</h3>
            <Async state={stats} compact loadingLabel="Datensätze werden geladen …">
              {(data) =>
                data.datasets.length === 0 ? (
                  <EmptyState compact title="Noch keine Statistik-Datensätze eingerichtet" icon="table">
                    Sobald amtliche Statistiken eingerichtet sind, stehen hier Herausgeber, Lizenz und die verlangte Quellenangabe.
                  </EmptyState>
                ) : (
                  <>
                    <TableWrap label="Statistik-Datensätze mit Lizenz und Quellenangabe">
                      <table className="table table--compact">
                        <thead>
                          <tr>
                            <th scope="col">Datensatz</th>
                            <th scope="col">Herausgeber</th>
                            <th scope="col">Lizenz</th>
                            <th scope="col">Quellenangabe</th>
                            <th scope="col">Erscheinungsweise</th>
                            <th scope="col">Jüngster Stand</th>
                          </tr>
                        </thead>
                        <tbody>
                          {data.datasets.map((d) => {
                            const latest = data.releases.find((r) => r.dataset_key === d.key && r.is_current);
                            return (
                              <tr key={d.key}>
                                <th scope="row" className="col-wrap">
                                  {d.name}
                                  {d.dataset_code ? <span className="table__sub">Kennung {d.dataset_code}</span> : null}
                                  {d.notes ? <span className="table__sub">{d.notes}</span> : null}
                                  <ExternalLink href={d.landing_url}>Seite des Herausgebers</ExternalLink>
                                </th>
                                <td>{d.publisher}</td>
                                <td>
                                  <ExternalLink href={d.licence_url} fallback={d.licence ?? <span className="unknown">unbekannt</span>}>
                                    {d.licence ?? 'Lizenz'}
                                  </ExternalLink>
                                </td>
                                <td className="col-wrap">{d.attribution ?? <span className="unknown">keine hinterlegt</span>}</td>
                                <td>{UPDATE_CYCLE_LABELS[d.update_cycle ?? ''] ?? <span className="unknown">unbekannt</span>}</td>
                                <td className="nowrap">
                                  {latest ? (
                                    <>
                                      {latest.period_key}
                                      <span className="table__sub">Revision {latest.revision}</span>
                                    </>
                                  ) : (
                                    <span className="muted">noch nicht importiert</span>
                                  )}
                                </td>
                              </tr>
                            );
                          })}
                        </tbody>
                      </table>
                    </TableWrap>
                    <p className="field__hint">{data.note}</p>
                  </>
                )
              }
            </Async>
          </Section>

          <Section id="grenzen" title="Grenzen der Aussagekraft">
            <ul>
              <li>
                <strong>Abdeckung:</strong> Die Zahlen beziehen sich ausschließlich auf die unten aufgeführten, freigegebenen Quellen und deren Suchbereiche. Sie sind keine
                Vollerhebung des Stellenmarkts.
              </li>
              <li>
                <strong>Schwerpunkt öffentlicher Dienst:</strong> Derzeit stehen vor allem Quellen des öffentlichen Sektors zur Verfügung. Die großen kommerziellen Portale
                und die Jobsuche der Bundesagentur für Arbeit untersagen automatisierte Abrufe in ihren Nutzungsbedingungen; sie sind im Register dokumentiert, werden aber
                ohne Erlaubnis nicht abgerufen. Branchen und Berufe außerhalb des öffentlichen Dienstes sind dadurch stark unterrepräsentiert.
              </li>
              <li>
                <strong>Kein Volltext:</strong> Der Text der Anzeigen wird nicht gespeichert. Gespeichert werden Rumpfdaten (Titel, Arbeitgeber, Ort, Fristen, Verweis) und
                abgeleitete Merkmale, je nach Quelle mit kurzen Belegauszügen. Die Suche durchsucht nur diese Daten.
              </li>
              <li>
                <strong>Merkmale sind regelbasiert:</strong> Qualifikationen, Kenntnisse und Berufsklassen werden mit Regeln und Wörterbüchern erkannt. Das kann falsch
                sein. Deshalb gibt es die Einordnung „unklar“, und jedes Merkmal nennt Herkunft, Regelstand und – wo vorhanden – den kurzen Beleg.
              </li>
              <li>
                <strong>Unbekannt bleibt unbekannt:</strong> Fehlende Angaben zu Vergütung, Arbeitszeit, Befristung oder Remote-Status werden nicht geschätzt.
                Vergütungsschätzungen eines Portals sind als solche gekennzeichnet.
              </li>
              <li>
                <strong>Regionale Hotspots</strong> zeigen, wo in den beobachteten Quellen viele Anzeigen erscheinen. Sie hängen auch davon ab, welche Arbeitgeber auf diesen
                Quellen ausschreiben, und sind kein Maß für Engpässe.
              </li>
            </ul>
          </Section>

          <Section id="quellen" title="Quellenregister">
            <p>
              Jede Quelle ist mit dem Ergebnis ihrer Prüfung dokumentiert (robots.txt, Nutzungsbedingungen, technischer Abruftest). Das ist keine Rechtsberatung, sondern
              hält fest, was die Bedingungen sagen. <strong>Keine Quelle ist automatisch aktiv</strong>: Der Betreiber dieser Installation gibt sie mit einem
              Freigabevermerk frei; wo eine Erlaubnis nötig ist, zusätzlich mit deren Nachweis.
            </p>
            <Async state={sources} compact loadingLabel="Quellenregister wird geladen …">
              {(data) => (
                <TableWrap label="Quellenregister mit Status">
                  <table className="table table--compact">
                    <thead>
                      <tr>
                        <th scope="col">Quelle</th>
                        <th scope="col">Abdeckung</th>
                        <th scope="col">Konfigurationsstatus</th>
                        <th scope="col">Technischer Zustand</th>
                        <th scope="col">Zugriffsart</th>
                        <th scope="col">Geprüft am</th>
                      </tr>
                    </thead>
                    <tbody>
                      {data.sources.map((s) => (
                        <tr key={s.id}>
                          <th scope="row">
                            <Link to={`/quellen/${s.id}`}>{s.name}</Link>
                            <span className="table__sub mono">{s.domain}</span>
                          </th>
                          <td className="col-wrap">{s.segment ?? <span className="muted">–</span>}</td>
                          <td className="col-wrap">
                            <ConfigStatusBadge status={s.config_status} />
                            {s.status_reason ? <span className="table__sub">{s.status_reason}</span> : null}
                          </td>
                          <td>
                            <HealthBadge health={s.health} label={data.health_labels[s.health] ?? HEALTH_LABELS[s.health]} />
                          </td>
                          <td>{s.adapter_available ? (ACCESS_METHOD_LABELS[s.access_method ?? ''] ?? s.access_method ?? '–') : <span className="muted">kein Adapter</span>}</td>
                          <td className="nowrap">{s.legal_checked_on ? fmtDate(s.legal_checked_on) : <span className="muted">–</span>}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </TableWrap>
              )}
            </Async>
            <p className="field__hint">
              Einzelheiten zu jeder Quelle – Prüfvermerk, Verweise auf Nutzungsbedingungen und robots.txt, Suchbereiche und Läufe – stehen in der{' '}
              <Link to="/quellen">Quellenverwaltung</Link>.
            </p>
          </Section>
        </div>
      </div>
    </div>
  );
}
