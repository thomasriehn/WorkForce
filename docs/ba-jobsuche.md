# BA-Jobsuche

Der Adapter `ba_jobsuche` (`ba-html-1`) liest die öffentlichen HTML-Suchergebnisse unter
`https://www.arbeitsagentur.de/jobsuche/suche` und das `JobPosting`-JSON-LD der verlinkten Detailseiten.
Er verwendet den vorhandenen HTTP-Fetcher mit identifizierbarem User-Agent, robots.txt-Prüfung,
Domainprüfung, Abrufabständen und Backoff. Es werden keine Portal-APIs oder internen Endpunkte aufgerufen.

## Einrichtung und Update

`workforce migrate` bzw. der Compose-Dienst `migrate` ergänzt den Adapter auch bei bestehenden Installationen.
Individuelle Quellenstatus, Freigabevermerke, Budgets und Suchbereiche bleiben erhalten. Ein Standardsuchbereich
wird nur angelegt, wenn noch kein Suchbereich vorhanden ist. Keine Quelle wird dabei automatisch freigegeben.

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
- Suchseiten ohne Trefferzahl, widersprüchliche Angaben, wechselnde Trefferzahlen, wiederholte IDs,
  leere Fehlerseiten und Detailseiten ohne eindeutiges JobPosting erzeugen sichtbare Fehler.
- Checkpoints bewahren nächste Seite, Trefferzahl und bereits gelesene IDs auch bei Fortsetzung.
  Nur eindeutige IDs in gleicher Anzahl wie die gemeldeten Treffer und ohne Trefferlimit belegen Vollständigkeit.
- Trefferlimit, Seitenbudget und Abruffehler ergeben unvollständige Läufe; sie archivieren keine fehlenden Anzeigen.
  Unvollständige Detailanreicherung wird separat ausgewiesen. Anzeigentexte werden nur vorübergehend verarbeitet;
  dieser Adapter speichert keine Belegauszüge.

## Statistikabruf und Prüfstand

`WF_STATS_BA_AUTO=true` ist jetzt der Standard im Backend und in `.env.example`. Das betrifft BA-Statistik und
KldB, unabhängig vom Freigabestatus der BA-Jobsuche. Mit `false` ist weiterhin ein ausdrücklicher Opt-out möglich.
Bestehende `.env`-Dateien werden nicht überschrieben. Zeitplan, Kontaktpflicht, Importvalidierung, Quellenangaben
und Sperrpausen bleiben unverändert; siehe [Betrieb](betrieb.md#dateien-der-ba-statistik-automatischer-und-manueller-import).

Die Tests verwenden ausdrücklich synthetische HTML-/JSON-LD-Daten und eine echte PostgreSQL-/PostGIS-Datenbank.
Der aktuelle Live-Abgleich von HTML-Struktur, Suchparametern und Detaildaten steht aus: Am 11.11.2026 blockierte
die Cloud-Netzwerkrichtlinie bereits `https://www.arbeitsagentur.de/robots.txt` mit HTTP 403 am Proxy.
Die benötigten Domains `www.arbeitsagentur.de` und `statistik.arbeitsagentur.de` sind im Cloud-Konfigurationsentwurf
vorgemerkt. Damit ist der Adapter implementiert und lokal testbar; ein erfolgreicher Abruf realer BA-Anzeigen
ist für diese Änderung noch nicht nachgewiesen.
