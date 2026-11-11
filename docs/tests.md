# Tests und Abnahme

Stand: 10.11.2026. Dieses Dokument trennt strikt zwischen **geprüft** (mit Ergebnis) und **nicht geprüft**.

## Ergänzung BA-Jobsuche / Cloud-Umgebung (11.11.2026)

- Gesamte Backend-Suite: **107 bestanden, 1 übersprungen** (26,77 s). Übersprungen wurde der optionale Import
  echter Statistik-Probedateien, weil `WF_REAL_SAMPLES_DIR` nicht gesetzt ist. Eine vorhandene
  FastAPI/Starlette-Deprecation-Warnung zu HTTPX bleibt bestehen.
- `tests/test_ba_jobsuche.py`: 22 Fälle mit synthetischem HTML/JSON-LD, einschließlich Pagination/Fortsetzung,
  Trefferlimit, Layoutfehler, wiederholter Seiten, unveränderter Tagesläufe, Schutz vor Archivierung nach
  Abruffehlern, Register-Upgrade, Statistik-Standard und explizitem Opt-out.
- PostgreSQL 17/PostGIS 3.5 mit dem Digest aus `compose.yaml`; Migrationen und wiederholtes Seeding erfolgreich.
  Backend mit Python 3.13.5 und `uv sync --frozen`, Frontend mit Node 24.22.1 und `npm ci` installiert.
- `npm run build` einschließlich TypeScript-Prüfung erfolgreich. Ruff für neue Adapter-/Testdateien und geänderte
  Konfigurations-/Register-/Statistikmodule erfolgreich. Bei zusätzlicher Prüfung von `test_api_ops.py` meldet Ruff
  vier bereits vorhandene Hinweise außerhalb der geänderten Zeilen (ungenutzte Variablen / noqa).
- Native Anwendung gestartet: Web, Worker und Scheduler mit erfolgreichen Healthchecks. HTTP-Smoke-Test mit
  temporärem Prüfkonto: Anmeldung, Quellenregister mit verfügbarem BA-Adapter, Dashboard, leere Stellensuche,
  sechs Statistikdatensätze und ausgeliefertes Frontend erfolgreich. Prüfkonto danach entfernt.
- Installations- und Startschritte in der laufenden Cloud-Instanz wiederholt geprüft. Ein vollständiger
  Compose-App-Build und Wiederherstellung in einer neu veröffentlichten Cloud-Instanz wurden hier nicht geprüft.
- Der anfangs durch den Cloud-Proxy blockierte BA-Live-Abgleich wurde nach Übernahme der Netzwerkfreigaben
  nachgeholt (siehe folgende Ergänzung). Ein neuer Live-Statistikabruf bleibt außerhalb dieser Prüfung.

### Korrektur wechselnder BA-Trefferzahlen (`ba-html-2`, 11.11.2026)

- Live-Reproduktion: Seite 1 meldete 712.837, Seite 2 nur 712.835 Treffer. Beide HTML-Seiten und eine
  verlinkte JSON-LD-Detailseite waren gültig; die starre Gleichheitsprüfung verursachte den Abbruch.
- Live-Prüfung der Korrektur: drei Suchseiten mit 712.854 / 712.854 / 712.856 gemeldeten Treffern erfolgreich
  verarbeitet, 70 eindeutige Anzeigen, fünf Wiederholungen dedupliziert. Eingeschränkte Abdeckung ausgewiesen.
- Regressionstests prüfen steigende/sinkende und zum Ausgangswert zurückkehrende Gesamtzahlen, Überlappungen,
  wiederholte Seiten ohne Fortschritt, Seitengrenzen, erhaltene Einschränkungen über Checkpoints sowie die
  Fortsetzung eines fehlgeschlagenen alten Checkpoints. Mehrere solche Läufe archivieren keine fehlenden Anzeigen.
- Gezielte Adapter-/Pipeline-Suite: 44 bestanden. Ruff für die geänderten Adapter-/Testdateien erfolgreich.
- Gesamte Backend-Suite nach der Korrektur: **113 bestanden, 1 übersprungen** (48,33 s); derselbe optionale
  Statistik-Probedateitest und dieselbe FastAPI/Starlette-Warnung wie oben.

## 1. Tests ausführen

Die Tests laufen gegen eine echte PostgreSQL-Datenbank mit PostGIS (keine SQL-Mocks) und rufen **nie** externe
Webseiten ab. Alle Anzeigen, Arbeitgeber und Zahlen in den Tests sind synthetisch und als solche benannt.

Testdatenbank starten (Port nur lokal):

```bash
docker run -d --name wf-testdb -e POSTGRES_USER=workforce -e POSTGRES_PASSWORD=devpass -e POSTGRES_DB=workforce -p 127.0.0.1:55432:5432 postgis/postgis:17-3.5
```

```bash
cd backend && uv sync
```

```bash
cd backend && WF_TEST_DATABASE_URL=postgresql+psycopg://workforce:devpass@127.0.0.1:55432/wf_test uv run pytest
```

Die Testdatenbank `wf_test` wird je Testsitzung neu angelegt, per Alembic migriert und vor jedem Test geleert.

Oberfläche bauen und Typprüfung:

```bash
cd frontend && npm ci && npm run build
```

## 2. Was die automatischen Tests abdecken

| Datei | Inhalt |
|---|---|
| `tests/test_pipeline.py` | Idempotenz des Tageslaufs; fachliche Version bei geänderter Anforderung, keine bei Trackingparametern; Parserwechsel gesondert; „vermutlich entfernt“ erst nach drei vollständigen Scans; Reaktivierung; acht Störungsarten ohne Archivierung; Feed-Quellen; keine Kontaktdaten in gespeicherten Feldern |
| `tests/test_dedup_counting.py` | dieselbe Anzeige auf zwei Portalen zählt einmal; ähnliche echte Ausschreibungen bleiben getrennt; Zusammenführung umkehrbar; Wiederveröffentlichung; Zählregeln für Mehrfachstandorte, Remote, ungeklärte Orte; identische Filterwirkung auf Liste, Karte, Diagramm; neue Quelle und geänderter Suchbereich ohne Scheinwachstum; Ausgangswert 0; Tagesaggregate reproduzierbar |
| `tests/test_fetcher_adapters.py` | robots.txt (Platzhalter, längste Übereinstimmung, Crawl-delay); Schutz vor internen Zielen; 403, CAPTCHA, `Retry-After`, Timeout, Weiterleitungen; JSON-LD-Parser; RSS-Adapter mit Abdeckungssignal; Sitemap-Adapter mit Detailbudget, 404-Bestätigung, Layoutänderung; Listenparser karriere.bund.de |
| `tests/test_api_ops.py` | Login, Rollen, CSRF, Kontosperre; Freigabe mit Vermerk und Erlaubnisnachweis; Suche, Export, Schutz vor HTML-/CSV-Injection; Zeitplan (ein Lauf je Tag, Zeitumstellung, Nachholen); Jobqueue (Sperren, Wiederholung, verwaiste Jobs); Aufbewahrung nur technischer Protokolle; Laufsteuerung |
| `tests/test_stats_*.py` | Importer für amtliche Statistik, Klassifikation und Geodaten (Berichtszeitraum, Fehlwerte, Revisionen, Altersgruppen, Gebietsschlüssel) |

Beim Schreiben der Tests gefundene und behobene Fehler: verlorenes Abdeckungssignal des Feeds; Statusflattern, wenn
eine Liste eine nicht mehr erreichbare Anzeige weiter nennt; Bestandszeitraum am Tag des Wegfalls; fehlerhafte
Aggregatabfrage; veralteter Wiederholungszähler in der Jobqueue; dauerhaft gespeicherter robots.txt-Fehlschlag.

## 3. Kontrollierte Live-Prüfungen (10.11.2026)

| Quelle | Prüfung | Ergebnis |
|---|---|---|
| service.bund.de (RSS) | regulärer Lauf über die CLI, 2 Abrufe (robots.txt, Feed), Crawl-delay 30 s eingehalten | **bestanden:** 500 reale Anzeigen; Titel, Behörde, PLZ/Ort, Bewerbungsfrist und Veröffentlichungsende bei allen vorhanden; Originalverweise ohne Trackingparameter; Lauf `complete`, als Bestandsaufnahme gekennzeichnet |
| karriere.bund.de | begrenzter Testlauf (1 Seite) | **nicht bestanden / offen:** robots.txt war wegen wiederholter Verbindungsabbrüche nicht abrufbar; der Lauf endete zweimal wie vorgesehen als `blocked`, es wurde nichts erfasst. Der Adapter ist nur offline gegen eine am selben Tag gespeicherte Listen- und Detailseite geprüft (12 Anzeigen je Seite, gemeldete Trefferzahl 1.912, Rumpfdaten korrekt). |
| INTERAMT | kein Live-Lauf (Erlaubnisvorbehalt) | offline gegen die bei der Machbarkeitsprüfung gespeicherte Sitemap (10.882 Anzeigen-URLs) und eine Detailseite geprüft |
| greenjobs | kein Live-Lauf (Erlaubnisvorbehalt) | offline gegen die gespeicherte Sitemap (714 Anzeigen) und eine Detailseite geprüft |

Zweiter realer Tageslauf des Feeds (logisches Datum 11.11.2026, kurz nach Mitternacht Berliner Zeit): `complete`,
Feedfenster überlappt mit dem Vortag, 500 Kennungen gesehen, **0 neue Anzeigen, 0 neue Versionen**; danach 500
Quellanzeigen, 500 Versionen, 1.000 Beobachtungen. Neue Anzeigen zwischen zwei realen Läufen konnten in diesem
kurzen Abstand nicht beobachtet werden; dieser Fall und das nicht überlappende Fenster sind nur durch Tests mit
synthetischem Feed belegt.

Ortszuordnung und Berufsklassifikation auf den 500 realen Anzeigen (nach Import von VG250, Gemeindeverzeichnis und
KldB):

| Prüfung | Ergebnis |
|---|---|
| Kreis zugeordnet | 497 von 500; ungeklärt: zwei Orte im Ausland ohne Länderangabe, einmal „bundesweit“ |
| Zuordnungsweg | 477 über den amtlichen Ortsnamen, 15 über Name + PLZ, 4 nur über die PLZ, 1 über Kurzname + PLZ |
| KldB-Zuordnung | 97 von 500 (41 exakter Titeltreffer, 56 ähnlicher Titel und als unsicher markiert); 403 ohne Zuordnung |

Die Berufsklassifikation über den Titel ist damit **schwach**: Die Quelle liefert keine Berufsangabe, und die
unscharfen Treffer enthalten sichtbar falsche Zuordnungen (z. B. „Lehrkraft für das Lehrfach Englisch“ →
IT-Anwendungstraining). Sie sind als unsicher gekennzeichnet; für berufsbezogene Auswertungen reicht die Qualität
noch nicht.

## 3a. Amtliche Daten: realer Import

Importiert wurden die am 10.11.2026 von den offiziellen Seiten geladenen Dateien – einmal auf der
Entwicklungsmaschine und einmal im Worker-Container des Compose-Aufbaus (`workforce stats import <Datensatz> --file …`).

| Datensatz | Stand | Ergebnis |
|---|---|---|
| `vg250` | Gebietsstand 31.12.2025 | 16 Länder, 400 Kreise mit Geometrie, 10.950 Gemeinden als Ortsreferenz; Kreis-GeoJSON 2,2 MB |
| `gv_isys` | 30.09.2026 | 10.943 Gemeinden angereichert, 10.750 PLZ-Einträge; `06415` (Hanau), `07000`, `13000` als unbekannte Schlüssel gemeldet |
| `kldb2010` | Systematik 2020, Benennungen 01/2026 | 2.193 Klassen, 18.863 Berufsbenennungen |
| `ba_arbeitslose_kreise` | Berichtsmonat 2026-10 | 836 Werte; Leipzig (14713): 32.470 Arbeitslose, Quote 9,1 %; `06415` als unbekannter Schlüssel gemeldet |
| `ba_berufe` | Berichtsmonat 2026-10 | 46.169 Werte für Deutschland und Länder; Deutschland: 2.954.598 Arbeitslose, 4.678.997 Arbeitsuchende, 653.993 gemeldete Stellen |
| `bevoelkerung_kreise_alter` | Stichtag 31.12.2025 | 8.986 Werte; Summe 83.467.117; 15 bis unter 65: 52.627.803; Leipzig 414.411 |

- Fehlwerte: von 55.991 Werten sind 49.898 Zahlen, 2.499 echte Nullwerte, 2.208 unterdrückt und 1.386 nicht verfügbar.
- Erneuter Import derselben Datei: `unchanged`, keine neuen Zeilen.
- Revisionen, Fehlwertzeichen und Kachelung der Altersgruppen sind durch Tests mit synthetischen Dateien belegt; eine
  echte amtliche Korrektur wurde nicht beobachtet.
- **Automatischer Abruf live geprüft:** Bevölkerung über die öffentliche GENESIS-Oberfläche (Chromium, „Download →
  CSV (Flat)“) und Gemeindeverzeichnis – jeweils `unchanged` gegenüber der Probedatei. Für VG250 wurden Produktseite
  und Link gefunden; der Download der 70-MB-Datei über den Importer wurde nicht erneut ausgeführt.
- **Nicht live geprüft:** der automatische Abruf der drei BA-Datensätze (bewusst keine Anfragen, siehe
  [betrieb.md](betrieb.md)); der Ausweichweg über die Regionaldatenbank.

## 4. Skalierungsmessung (synthetische Daten)

Datensatz: `workforce synthetic load --postings 100000 --days 60 --confirm-synthetic` in einer eigenen Datenbank;
Messung mit `backend/scripts/benchmark.py` (Median aus fünf Durchläufen, warmer Cache).

| Eckdaten | Wert |
|---|---|
| Hardware | Intel Xeon 2,1 GHz, 4 Kerne, 15,7 GB RAM (Entwicklungsmaschine, kein Proxmox) |
| PostgreSQL | 17.5 mit Standardeinstellungen des Images (`shared_buffers` 160 MB, `work_mem` 4 MB) |
| Daten | 100.000 Quellanzeigen, 100.000 zusammengeführte Anzeigen, 4.373.581 Beobachtungen, 400 synthetische Kreisschlüssel |
| Ladezeit | 113 s |
| Größte Tabellen | `observation` 409 MB, `posting_version` 269 MB, `source_posting` 153 MB; Datenbank insgesamt rund 1 GB |

| Abfrage | Median | Maximum |
|---|---|---|
| Suche: Freitext, Seite 1 | 120 ms | 142 ms |
| Suche: Freitext + Merkmal + Kreis | 5 ms | 5 ms |
| Suche: Phrase, ODER, Ausschluss | 176 ms | 354 ms |
| Suche: zwei Merkmale (UND) | 27 ms | 28 ms |
| Suche: ohne Filter, Seite 200 | 103 ms | 117 ms |
| Suche: ähnliche Schreibweisen (Trigramme) | 597 ms | 685 ms |
| Summen der Bezugsbasis | 53 ms | 57 ms |
| Karte: Kennzahlen je Kreis, ungefiltert | 130 ms | 137 ms |
| Karte: mit Freitext + Merkmal | 33 ms | 35 ms |
| Karte: Stichtag vor 30 Tagen (historische Versionen) | 268 ms | 275 ms |
| Karte: Veränderung über 30 Tage | 408 ms | 576 ms |
| Zeitreihe 60 Tage, gefiltert (live, 45 Stützstellen) | 1.447 ms | 1.557 ms |
| Zeitreihe 60 Tage, ungefiltert, live berechnet | 3.571 ms | 3.595 ms |
| Facetten für einen Kreis | 10 ms | 11 ms |
| CSV-Export, 10.000 Zeilen | 411 ms | 436 ms |
| Anzeigendetail | 1 ms | 2 ms |
| Tagesaggregate: ein Tag / 60 Tage | 1,1 s / 88,5 s | – |

Einordnung: Such- und Kartenabfragen bleiben deutlich unter einer Sekunde. Die ungefilterte Zeitreihe wird im
Betrieb aus den Tagesaggregaten gelesen; der Messwert zeigt den ungünstigeren Live-Fall. Gefilterte Zeitreihen sind
mit rund 1,5 s die langsamste interaktive Abfrage. Für zusätzliche Partitionierung oder Caches besteht bei dieser
Größe kein Anlass. Mit real importierten Kreisgrenzen und anderer Hardware können die Werte abweichen.

## 5. Compose-Abnahme, Neustart und Wiederherstellung (11.11.2026)

Umgebung: Entwicklungsmaschine mit Docker 29.9 und Compose 5.6 – **kein Proxmox, kein LXC**. Das Image wurde wegen
des TLS-inspizierenden Proxys dieser Umgebung mit `docker build --network host --secret id=extra_ca,…` gebaut;
`docker compose up -d` hat dieses Image verwendet. Der Weg `docker compose up -d --build` ohne Proxy ist damit nicht
eins zu eins ausgeführt worden.

| Schritt | Ergebnis |
|---|---|
| Build | erfolgreich; Image 2,5 GB (mit Chromium) |
| Frischer Start mit neu erzeugter `.env` | `db`, `web`, `worker`, `scheduler` nach rund 45 s `healthy`; `migrate` legt Schema und 16 Registereinträge an |
| Administrator anlegen | einmalig angezeigtes Zufallspasswort; Anmeldung über die API erfolgreich |
| Zugriffsschutz | ohne Anmeldung HTTP 401; nur `web` veröffentlicht einen Port (`127.0.0.1`); PostgreSQL von außen nicht erreichbar; Prozesse laufen als Benutzer 10001; Chromium startet im gehärteten Container |
| Amtliche Daten im Container importiert | alle sechs Datensätze, Quelldateien unter `/data/downloads` (99 MB) |
| Neustart (`docker compose down`, `up -d`) | identische Zeilenzahlen vor und nach dem Neustart (500 Anzeigen, 1.000 Beobachtungen, 416 Regionen, 55.991 Statistikwerte, Benutzer, Quellenstatus); Anmeldung funktioniert |
| Sicherung (`scripts/backup.sh`) | Dump 14 MB, Referenzdateien 98 MB, Konfiguration, Prüfsummen |
| Probe-Restore (`scripts/restore.sh --verify`) in frische Datenbank | Schemaversion und alle Zeilenzahlen identisch; Stichproben: Anzeigenhistorie, Kreisgeometrien mit Punkt-in-Polygon, Statistikwerte, Quellenkonfiguration mit Freigabevermerk, Benutzer, Volltextsuche |
| Vollständige Wiederherstellung (`--replace`) nach simuliertem Verlust | Anzeigen, Statistik und Referenzdateien wieder vorhanden, Dienste `healthy`, Anmeldung und Karte funktionieren |

Einschränkungen dieser Abnahme:

- Die Compose-Container hatten in der Entwicklungsumgebung keinen Internetzugang. Die 500 real erfassten Anzeigen
  wurden deshalb aus der Entwicklungsdatenbank übertragen; ein Scan **aus dem Container heraus** wurde nicht ausgeführt.
- Der zeitgesteuerte Lauf um 03:15 Uhr wurde nicht in Echtzeit abgewartet; die Planung ist durch Tests belegt.
- Beim ersten Versuch der vollständigen Wiederherstellung scheiterte das Zurückspielen der Referenzdateien (Schritt
  lief als root ohne Schreibrechte). Das Skript wurde korrigiert; der zweite Durchlauf war erfolgreich.

## 6. Oberfläche

Geprüft mit dem Browser-Prüfskript `frontend/scripts/verify.cjs` (Chromium) gegen den Compose-Aufbau mit den
**realen Daten**, jeweils als Administrator und als Leser, in 1440×900 und 820×1180:

```bash
cd frontend && WF_BASE_URL=http://127.0.0.1:8080 WF_VERIFY_PLACE=Leipzig WF_ADMIN_USER=… WF_ADMIN_PASS=… WF_READER_USER=… WF_READER_PASS=… npm run verify
```

Ergebnis: **keine Probleme** – keine Konsolenfehler, keine Verstöße gegen die Content-Security-Policy, keine
fehlgeschlagenen Anfragen, keine Anfrage an fremde Hosts (keine Kartenkacheln, keine Schriftarten, kein API-Key),
keine schreibenden Bedienelemente im Lesezugriff. Durchlaufen werden alle Bereiche einschließlich Umkreissuche,
Kartenansichten (anteilig, unterschiedliche Anzeigen, Rate, Veränderung, Kontextstatistik), Kreisauswahl, Regionen-
und Anzeigendetail, Quellenverwaltung, Läufe und System.

Stichproben der Bildschirmfotos mit echten Daten: Karte mit 400 Kreisflächen und getrennter Darstellung von „0“ und
„keine Daten“; Kontextkarte „Arbeitslose“ mit Berichtszeitraum, Revision, Alter, „Veröffentlicht: unbekannt“ und
Quellenangabe; Quellenregister mit getrennten Spalten für Konfigurationsstatus und technischen Zustand; Dashboard
mit „Kein Vergleich möglich“ samt Vergleichsgrundlage.

Zusätzlich hat die Oberflächenentwicklung dasselbe Skript mit synthetischen Entwicklungsdaten (112 Ansichten) und
mit leerer Datenbank (68 Ansichten) ohne Befund durchlaufen.

Nicht ausgeführt, nur dargestellt: erfolgreiche Freigabe und Deaktivierung über die Oberfläche, Laufstart sowie
Pause/Fortsetzung/Abbruch/Wiederholung, Zusammenführen/Trennen, Statistik-Upload, Job-Auslöser, Budget- und
Suchbereichsänderung. Diese Aktionen sind über API-Tests bzw. die CLI geprüft, nicht per Klick.

Nicht systematisch geprüft: Bedienung per Tastatur und Screenreader (Kreisflächen der Karte sind nicht per Tastatur
fokussierbar; Ersatz sind Kreissuche und Tabellenansicht), ältere Browser, reale Tablets.

## 7. Abnahmekriterien

| Nr. | Kriterium | Stand | Beleg |
|---|---|---|---|
| 1 | Frischer Aufbau per Docker Compose; Daten überleben Neustart | **erfüllt** (Entwicklungsmaschine, nicht Proxmox) | Abschnitt 5 |
| 2 | Angebundene Quellen liefern reale Titel, Arbeitgeber/Ort, funktionierende Originalverweise; aktive und vorgemerkte Adapter unterscheidbar | **teilweise:** eine Quelle live (service.bund.de); karriere.bund.de live nicht erreichbar; INTERAMT und greenjobs nur offline geprüft. Zielabdeckung von drei freigegebenen Quellen **nicht erreicht** | Abschnitt 3, [quellenregister.md](quellenregister.md) |
| 3 | Wiederholter Tageslauf ohne Dubletten; unterbrochene Jobs werden fortgesetzt | **erfüllt** | Tests; realer zweiter Tageslauf |
| 4 | Dieselbe Anzeige auf zwei Portalen zählt einmal; ähnliche echte Ausschreibungen bleiben getrennt | **erfüllt (synthetisch)** – mit nur einer Live-Quelle real nicht beobachtbar | `test_dedup_counting.py` |
| 5 | Geänderte Anforderung erzeugt Version; Trackingparameter nicht | **erfüllt (synthetisch)** | `test_pipeline.py` |
| 6 | Timeout, CAPTCHA, 403, Layoutänderung, Trefferlimit, unvollständige Pagination ohne Massenarchivierung | **erfüllt (synthetisch)**; real: blockierter Lauf bei karriere.bund.de ohne Folgen für den Bestand | `test_pipeline.py`, Abschnitt 3 |
| 7 | Neue Quellen und geänderte Suchbereiche ohne unkommentierten Trendanstieg | **erfüllt (synthetisch)**; real: Dashboard zeigt „Kein Vergleich möglich“ | `test_dedup_counting.py` |
| 8 | Zählregeln für Mehrfachstandorte, Remote, ungeklärte Orte | **erfüllt (synthetisch)** | `test_dedup_counting.py` |
| 9 | Filter wirken konsistent auf Liste, Karte, Diagramm | **erfüllt** | `test_dedup_counting.py` |
| 10 | Reale amtliche Regionaldaten mit Berichtszeitraum; Arbeitslose und Arbeitsuchende getrennt; Fehlwerte keine Nullen | **erfüllt**; Arbeitsuchende nur bis Bundeslandebene verfügbar | Abschnitt 3a |
| 11 | Revidierte Statistikdatei erhält neuen Stand; alte Werte rekonstruierbar | **erfüllt (synthetisch)** – keine echte Korrektur beobachtet | `test_stats_statistics.py` |
| 12 | Karte und Kernsuche ohne bezahlten Dienst und ohne API-Key | **erfüllt** | Abschnitt 6 |
| 13 | Nach Restore sind Anzeigenhistorie, Regionaldaten und Quellenkonfiguration verfügbar | **erfüllt** | Abschnitt 5 |

## 8. Nicht geprüft

- Betrieb im LXC unter Proxmox (alles in [proxmox-lxc.md](proxmox-lxc.md) ist aus der offiziellen Dokumentation
  abgeleitet und als ungetestet gekennzeichnet).
- Mehrtägiger Dauerbetrieb, der nächtliche Zeitplan in Echtzeit, Verhalten bei wachsendem Realbestand.
- Portalübergreifende Dubletten, Wegfall und Inhaltsänderungen an realen Anzeigen (dafür fehlen eine zweite
  Live-Quelle und mehrere Beobachtungstage).
- Automatischer Abruf der BA-Statistikdateien, VG250-Download über den Importer.
- Reverse-Proxy-Beispiele (`deploy/`) – nicht ausgeführt.
- Die Prüfung von stellenanzeigen.de und yourfirm aus einem deutschen Netz.

## 9. Bekannte kleinere Lücken

- `export.csv` endet ohne Hinweis bei 50.000 Zeilen.
- Die Kontextkarte zeigt nur ungegliederte Kennzahlen; berufsbezogene Werte (KldB-Dimension) sind in der Datenbank,
  aber in der Oberfläche nicht auswählbar.
- Die Oberfläche zeigt nicht an, welche Datei ein Statistik-Upload erwartet; das liefert bisher nur
  `workforce stats list`.
- Der Statusfilter wird bei Stichtagsabfragen ignoriert (der Stichtagsbestand ist per Definition „im Bestand“).
- Nur helles Farbschema.
