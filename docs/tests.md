# Tests und Abnahme

Stand: 10.11.2026. Dieses Dokument trennt strikt zwischen **geprüft** (mit Ergebnis) und **nicht geprüft**.

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

Ein zweiter Tageslauf des Feeds (Überlappung des Fensters, neue Anzeigen) konnte am selben Kalendertag nicht real
beobachtet werden; dieses Verhalten ist nur durch Tests mit synthetischem Feed belegt.

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
