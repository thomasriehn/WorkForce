# BA-Jobsuche

Der Adapter `ba_jobsuche` (`ba-html-2`) liest die öffentlichen HTML-Suchergebnisse unter
`https://www.arbeitsagentur.de/jobsuche/suche` und das `JobPosting`-JSON-LD der verlinkten Detailseiten.
Er verwendet den vorhandenen HTTP-Fetcher mit identifizierbarem User-Agent, robots.txt-Prüfung,
Domainprüfung, Abrufabständen und Backoff. Es werden keine Portal-APIs oder internen Endpunkte aufgerufen.

## Einrichtung und Update

`workforce migrate` bzw. der Compose-Dienst `migrate` ergänzt den Adapter auch bei bestehenden Installationen.
Individuelle Quellenstatus, Freigabevermerke, Budgets und Suchbereiche bleiben erhalten. Ein Standardsuchbereich
wird nur angelegt, wenn noch kein Suchbereich vorhanden ist. Keine Quelle wird dabei automatisch freigegeben.

Update einer bestehenden Compose-Installation nach dem Abruf des neuen Repository-Stands:

```bash
docker compose up -d --build
```

Bereits fehlgeschlagene Läufe können am selben logischen Tag über **Wiederholen** fortgesetzt werden.
Checkpoints aus `ba-html-1` werden weiterverwendet; der Lauf startet bei der nächsten noch offenen Seite.
An einem späteren Tag einen neuen Lauf starten. Die Korrektur benötigt keine Schemaänderung.

Die BA-Quelle behält den vorhandenen Status `permission_required`. Nach Prüfung der im
[Quellenregister](quellenregister.md) dokumentierten Bedingungen erfolgt die Freigabe über die Quellenverwaltung
mit Freigabevermerk und Erlaubnisnachweis. `WF_CRAWLER_CONTACT` muss die Kontaktadresse des Betreibers enthalten.

Unter den Suchbereichen lässt sich `list_url` auf eine öffentliche BA-Such-URL eingrenzen, beispielsweise:

```json
{"list_url": "https://www.arbeitsagentur.de/jobsuche/suche?angebotsart=1&was=Pflege&wo=Berlin&umkreis=25"}
```

Die Filter stammen aus der öffentlichen Jobsuche. Seitenwechsel erhalten diese Filter; `page` wird vom Adapter
gesetzt. Änderungen am Suchbereich erzeugen wie bisher eine neue Version und eine neue Bestandsaufnahme.
Der Standardsuchbereich umfasst Stellenangebote (`angebotsart=1`). Eine deutschlandweite Vollerhebung wird
daraus nicht abgeleitet: Bei großen Suchen greift die Trefferobergrenze von 10.000; kleinere, fachlich sinnvolle
Suchbereiche sind erforderlich. Neue Installationen begrenzen einen Lauf auf 40 Listen- und 500 Detailseiten
mit mindestens fünf Sekunden Abrufabstand.

Nach Freigabe einen begrenzten Testlauf starten:

```bash
docker compose exec worker workforce scan ba_jobsuche --scope stellen --test --pages 2
```

Anschließend Laufprotokoll und einige Originalverweise kontrollieren. Erst ein vollständiger Lauf mit
verlässlicher Trefferzahl darf zur Ableitung fehlender Anzeigen beitragen.

## Vollständigkeit und Datenqualität

- Stabile BA-Referenznummern aus Detail-URLs identifizieren Quellanzeigen. Trackingparameter werden entfernt.
- Titel, Arbeitgeber, Arbeitsorte, Beschäftigungsart, Termine und weitere explizite Merkmale kommen aus JSON-LD.
  Fehlende Werte bleiben unbekannt. Portal-IDs und Arbeitgeber-Homepages dienen nicht als belegte
  portalübergreifende Arbeitgeber-Stellenreferenzen bzw. Bewerbungs-URLs.
- Suchseiten ohne Trefferzahl, widersprüchliche Angaben innerhalb einer Seite, leere Fehlerseiten und
  Detailseiten ohne eindeutiges JobPosting erzeugen sichtbare Fehler.
- Die Gesamtzahl darf sich während eines Abrufs ändern: Neue und entfernte Veröffentlichungen gehören zum
  laufenden Betrieb der Jobsuche. Der Adapter sammelt weiter und dokumentiert die Änderung als Einschränkung
  der Abdeckung. Sie ist kein Parserfehler. Das gilt auch, wenn die Zahl später wieder den Ausgangswert erreicht.
- Durch verschobene Seitengrenzen doppelt auftauchende IDs werden nur einmal gezählt; neue IDs derselben Seite
  werden weiterverarbeitet. Eine vollständig wiederholte Seite beendet die Pagination kontrolliert als partiell.
- Checkpoints bewahren nächste Seite, ursprüngliche Trefferzahl, Listenposition, gelesene IDs und bereits
  erkannte Abweichungen. Nur eine vollständig gelesene Liste ohne Trefferzahländerung, Überschneidung oder
  Trefferlimit kann vollständige Abdeckung belegen. Die Gesamtzahl ist keine Garantie einer atomaren Momentaufnahme.
- Trefferlimit, Seitenbudget und Abruffehler ergeben unvollständige Läufe; sie archivieren keine fehlenden Anzeigen.
  Unvollständige Detailanreicherung wird separat ausgewiesen. Anzeigentexte werden nur vorübergehend verarbeitet;
  dieser Adapter speichert keine Belegauszüge.

## Statistikabruf und Prüfstand

`WF_STATS_BA_AUTO=true` ist jetzt der Standard im Backend und in `.env.example`. Das betrifft BA-Statistik und
KldB, unabhängig vom Freigabestatus der BA-Jobsuche. Mit `false` ist weiterhin ein ausdrücklicher Opt-out möglich.
Bestehende `.env`-Dateien werden nicht überschrieben. Zeitplan, Kontaktpflicht, Importvalidierung, Quellenangaben
und Sperrpausen bleiben unverändert; siehe [Betrieb](betrieb.md#dateien-der-ba-statistik-automatischer-und-manueller-import).

Die Tests verwenden ausdrücklich synthetische HTML-/JSON-LD-Daten und eine echte PostgreSQL-/PostGIS-Datenbank.
Nach Übernahme der Netzwerkfreigaben wurde am 11.11.2026 die fehlerhafte Abbruchbedingung live reproduziert:
Zwei gültige HTML-Seiten meldeten 712.837 bzw. 712.835 Treffer; eine verlinkte Detailseite lieferte Titel,
Arbeitgeber und Arbeitsort per JSON-LD. Mit `ba-html-2` wurden anschließend drei echte Suchseiten erfolgreich
gelesen: 712.854 / 712.854 / 712.856 gemeldete Treffer, 70 eindeutige Anzeigen, fünf seitenübergreifende
Wiederholungen korrekt entfernt. Der Lauf blieb ausdrücklich unvollständig. Das belegt HTML-Pagination und
Detailauswertung stichprobenartig, keine deutschlandweite Vollerhebung. Ein neuer Live-Statistikimport war
nicht Gegenstand dieser Fehlerkorrektur.
