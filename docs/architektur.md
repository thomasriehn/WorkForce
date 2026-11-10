# Architektur und Datenmodell

## 1. Überblick

```
                 ┌────────────────────────── Docker Compose (im LXC) ───────────────────────────┐
 Browser ──TLS──▶│ Reverse Proxy* ──▶ web (FastAPI + gebaute React-Oberfläche)  ─┐              │
                 │                                                               ├──▶ db       │
                 │   scheduler (genau eine Instanz) ── plant Läufe/Jobs ─────────┤  PostgreSQL │
                 │   worker (Jobs: Scans, Statistikimporte, Aggregate) ──────────┘  + PostGIS  │
                 │        │                                                     (nur internes  │
                 │        └──▶ ausgehend: freigegebene Quellen, amtliche Dateien   Docker-Netz)│
                 └───────────────────────────────────────────────────────────────────────────────┘
 * Reverse Proxy mit TLS: im selben LXC oder vorgelagert (deploy/Caddyfile.example, deploy/nginx.conf.example)
```

Web, Worker und Scheduler sind getrennte Prozesse aus **derselben Codebasis und demselben Image** (`workforce web`,
`workforce worker`, `workforce scheduler`). Veröffentlicht wird nur der Webzugang.

## 2. Wichtige Entscheidungen

| Thema | Entscheidung | Begründung |
|---|---|---|
| Jobverwaltung | Tabelle `job` in PostgreSQL (`FOR UPDATE SKIP LOCKED`, Wiederholungszähler, Heartbeat, Wiederaufnahme verwaister Jobs) | Kein zusätzlicher Dienst; die Last sind wenige lange Jobs. Celery/Redis brächte hier nur eine weitere Betriebskomponente. |
| Genau ein Scheduler | Advisory-Sperre in PostgreSQL; ein zweiter Scheduler wartet | Schutz vor Doppelplanung auch bei versehentlich mehrfach gestartetem Dienst. |
| Ein logischer Tageslauf | eindeutiger Index auf (Suchbereich, lokales Datum) für reguläre Läufe | Wiederholungen setzen denselben Lauf an Checkpoints fort und sind idempotent. |
| Schutz vor Überlappung | Job-`lock_key` je Quelle und sitzungsgebundene Advisory-Sperre je Quelle/Suchbereich | Wirkt auch zwischen Worker und manuellem CLI-Lauf. |
| Suche | PostgreSQL-Volltext (`simple` + `german`) und `pg_trgm` | Vorgabe; kein Elasticsearch nötig. |
| Gemeinsame Bezugsbasis | eine Abfragefunktion (`search/query.py: build_where`) für Liste, Karte, Summen, Zeitreihen, Export | Filter wirken überall identisch; per Test abgesichert. |
| Bestand über Zeiträume | `activity_period` je Quellanzeige + Gültigkeit je Inhaltsversion | Stichtagsabfragen mit damaligen Merkmalen; Bestandslücken durch fehlgeschlagene Läufe entstehen nicht. |
| Volltext | wird nicht gespeichert | Vorgabe; nur Rumpfdaten, strukturierte Merkmale und – wo zulässig – kurze Belege. |
| Karte | Kreisgrenzen (VG250) vereinfacht aus PostGIS als GeoJSON, Darstellung mit Leaflet ohne Kacheln | Kein Kartendienst, kein API-Key, keine externen Anfragen. |
| Quellenfreigabe | keine Quelle ist automatisch aktiv; Freigabe mit Vermerk, bei Erlaubnisvorbehalt mit Nachweis | Die rechtliche Entscheidung liegt beim Betreiber und ist nachvollziehbar dokumentiert. |
| Frontend-Auslieferung | gebaute Oberfläche liegt im Backend-Image und wird von FastAPI ausgeliefert | Ein veröffentlichter Dienst, strikte Content-Security-Policy. |
| Abhängigkeiten | Python über `uv.lock`, Node über `package-lock.json`, Images mit Tag + Digest | Reproduzierbarer Build. |

## 3. Codestruktur

```
backend/workforce/
  config.py            Einstellungen (Umgebungsvariablen WF_…), Regelversionen
  models.py            Datenmodell (SQLAlchemy)            alembic/versions/  Migrationen
  crawl/               fetcher.py (höflicher Abruf), robots.py, netguard.py (SSRF-Schutz)
  sources/             base.py (Adapter-Schnittstelle), adapters.py, jsonld.py, registry.py, manage.py
  normalize/           text.py (Faltung, Titel, URLs), features.py (Merkmale + Polarität), occupation.py (KldB)
  geo/                 matcher.py (Ort → Gemeinde → Kreis), vg250.py (Grenzen und Ortsreferenz)
  pipeline/            run.py (Lauf-Engine), ingest.py (Versionen/Beobachtungen), dedup.py, status.py, aggregate.py
  search/              query.py (Suchparser, Bezugsbasis), analytics.py (Karte, Vergleiche, Zeitreihen)
  stats/               Importer für amtliche Statistik, Klassifikation und Geodaten
  jobs/                queue.py, worker.py, scheduler.py
  api/                 FastAPI-Router: auth, postings, analysis, admin
  cli.py               Betrieb und Administration
frontend/              React + TypeScript + Vite, Leaflet, Recharts
scripts/               backup.sh, restore.sh        deploy/  Reverse-Proxy-Beispiele
```

## 4. Ablauf eines Scanlaufs

1. **Planung:** Der Scheduler legt ab der konfigurierten lokalen Uhrzeit (Standard 03:15 Europe/Berlin) je aktivem
   Suchbereich den Lauf des Tages an. War der Dienst zu dieser Zeit aus, wird der Lauf desselben Tages nachgeholt
   (`catchup`). Vergangene Tage lassen sich nicht nachbeobachten und bleiben Datenlücken.
2. **Vorbedingungen:** Quelle freigegeben, Kontaktangabe im User-Agent gesetzt, kein anderer Lauf derselben
   Quelle/Konfiguration aktiv.
3. **Entdeckung** (Liste, Feed oder Sitemap) je Partition mit Checkpoint nach jeder Seite. Erkannt werden
   Seitenlimit, Trefferobergrenze, wiederholte und leere Seiten sowie Parserfehler.
4. **Detailprüfung** getrennt davon und budgetiert: neue Anzeigen, Änderungssignale, turnusmäßige Nachprüfung
   (bedingte Abrufe mit ETag/Last-Modified).
5. **Abschluss:** Status, Abdeckungssignale, Statusableitung der Anzeigen (nur bei vollständiger Listenentdeckung),
   Vermerke zur Vergleichbarkeit, Warnungen.
6. **Aggregate:** Tagesaggregate werden für das Korrekturfenster neu berechnet.

Die Benutzersuche arbeitet ausschließlich auf dem gespeicherten Bestand und löst nie einen Live-Abruf aus.

### Abrufverhalten

Identifizierbarer User-Agent mit Betreiberkontakt, ein Abruf zur Zeit je Host, konfigurierbarer Mindestabstand
(robots-`Crawl-delay` wird zusätzlich eingehalten), Timeouts, exponentieller Backoff, `Retry-After`, bedingte
Abrufe. Ein sehr langes `Retry-After`, HTTP 401/403, anhaltendes 429 und Bot-Schutz-Seiten beenden den Lauf als
`blocked`. Es gibt keine CAPTCHA-Umgehung, keine Login-Umgehung, keine Proxyrotation und keine Verschleierung.

## 5. Datenmodell

Technische Zeitstempel sind UTC (`timestamptz`); fachliche Bezugsdaten sind lokale Tagesdaten. Amtliche Schlüssel
sind Zeichenketten mit führenden Nullen. Wertebereiche sind als CHECK-Constraints hinterlegt.

| Bereich | Tabellen | Kern |
|---|---|---|
| Quellen | `source`, `search_scope` | Register mit Konfigurationsstatus; Suchbereiche sind versioniert (Änderung = neue Zeile, genau eine aktive Version je Schlüssel) |
| Läufe | `scan_run`, `scan_task`, `scan_error` | logischer Lauf mit Bezugsdatum, Beobachtungsfenster, Zählern, Abdeckung; Teilaufträge mit Checkpoint; technisches Fehlerprotokoll |
| Quellanzeigen | `source_posting`, `posting_version`, `posting_location`, `posting_feature`, `observation` | stabile Quell-ID; unveränderliche Versionen mit Gültigkeit, Orten und Merkmalen; kompakte Beobachtung je Lauf |
| Zusammenführung | `merged_posting`, `merge_link`, `merge_candidate`, `merge_block` | Zuordnung mit Grund, Konfidenz, Regelversion; unsichere Kandidaten; manuell getrennte Paare |
| Bestand und Ereignisse | `activity_period`, `posting_scope`, `posting_event`, `timeline_note` | Bestandszeiträume, verpasste vollständige Scans je Suchbereich, fachliche Ereignisse, Vermerke zur Vergleichbarkeit |
| Arbeitgeber | `employer` | normalisierter Name, Kennzeichen Personalvermittlung (unbekannt bleibt unbekannt) |
| Regionen | `region`, `geo_place`, `postal_code` | Länder und Kreise mit Gebietsstand und Geometrie; Ortsreferenz; PLZ-Referenz |
| Klassifikation | `kldb_class`, `occupation_title`, `feature` | KldB 2010/2020, Berufsbenennungen, Merkmalswörterbuch |
| Statistik | `stat_dataset`, `stat_indicator`, `stat_release`, `stat_value` | Datensatz mit Lizenz; Kennzahl mit Definition und Einheit; Datenstand mit Berichtszeitraum, Prüfsumme, Revision; Werte mit Fehlwertstatus |
| Aggregate | `daily_aggregate` | je Tag, Kreis und Anzeigengruppe; mit Bezugsbasis und Regelversionen |
| Benutzer | `app_user`, `user_session`, `saved_search`, `audit_log` | Rollen Administrator/Leser, gespeicherte Suchen, Protokoll administrativer Aktionen |
| Betrieb | `job`, `robots_cache`, `fetch_cache`, `ops_warning`, `app_state` | Jobqueue, Caches (nur Metadaten, keine Seiteninhalte), Warnungen |

Wichtige Eindeutigkeiten und Indizes:

- `source_posting (source_id, source_key)`, `posting_version (source_posting_id, version_no)`,
  `observation (run_id, source_posting_id)`.
- `scan_run (scope_id, logical_date)` für reguläre Läufe; je Suchbereichsschlüssel genau eine aktive Version.
- Höchstens ein offener Bestandszeitraum und eine aktive Zusammenführung je Quellanzeige.
- `stat_release (dataset, Zeitraum, Revision)` und `(dataset, Zeitraum, Prüfsumme)`; genau ein aktueller Stand je
  Zeitraum.
- GIN-Indizes auf Volltextvektor, Trigrammen (Titel, Arbeitgeber), Merkmals-, Kreis- und Länderlisten; GiST auf
  Geometrien.

### Reproduzierbarkeit

Zusammenführungs-, Klassifikations- und Georegeln sind versioniert und stehen an den abgeleiteten Daten. Aggregate
werden aus Bestandszeiträumen, Versionen und Ereignissen berechnet und lassen sich jederzeit neu erzeugen
(`workforce aggregate --from … --to …`). Partitionierung der Beobachtungstabelle ist bewusst nicht eingeführt: Der
Skalierungstest (siehe [tests.md](tests.md)) zeigt dafür bei 4,4 Mio. Beobachtungen keinen Bedarf.

## 6. Sicherheit

| Risiko | Maßnahme |
|---|---|
| Zugriff | Lokaler Login, Argon2-Passworthashes, serverseitige Sitzungen (Token nur als Hash), HttpOnly-/SameSite-Cookie, CSRF-Token für alle ändernden Anfragen, Sperre nach Fehlversuchen, Rollen Administrator/Leser. Keine Standardpasswörter. |
| Inhalte fremder Webseiten | Werden als unzuverlässige Daten behandelt: nie als Code ausgeführt, nie als HTML in die Oberfläche übernommen (React-Escaping, kein `dangerouslySetInnerHTML`). Externe Verweise nur mit `http(s)`. |
| CSV-Export | Zellen mit Formelbeginn (`=`, `+`, `-`, `@` …) werden als Text maskiert. |
| Abrufe interner Netze | Abrufziele sind auf die Domains der Quelle beschränkt; jede URL und jedes Weiterleitungsziel wird geprüft (Schema, Port, Domain, keine privaten, Loopback-, Link-Local- oder Metadatenadressen). |
| XML/HTML-Parser | Keine Entity-Auflösung, kein Netzwerkzugriff des Parsers, Größenbegrenzung der Antworten. |
| Browser (Statistik-Exporte) | Isolierter Browserkontext nur für amtliche Statistikseiten; Anfragen an andere Hosts werden blockiert. |
| Container | Nicht-Root-Benutzer, `no-new-privileges`, alle Capabilities entzogen; Datenbank ohne veröffentlichten Port in einem internen Netz. |
| Browser-Header | Content-Security-Policy (`default-src 'self'`), `X-Content-Type-Options`, `X-Frame-Options`, `Referrer-Policy`. |
| Secrets | Nur in `.env` (nicht im Repository); `.env.example` enthält keine Passwörter. |

Hinweis zur Namensauflösung: Die Prüfung auf interne Adressen erfolgt vor jedem Abruf. Zwischen Prüfung und
Verbindungsaufbau wird die Adresse nicht festgenagelt; das Restrisiko ist durch die Beschränkung auf konfigurierte
öffentliche Domains begrenzt. Hinter einem ausgehenden Proxy, der die Namen selbst auflöst, bleibt die Domainprüfung
bestehen.

## 7. Erweiterung um Österreich und die Schweiz

Vorbereitet, aber nicht produktiv angebunden: `source.country`, `region.country` mit Gebietstyp, Schlüssel und
Gebietsstand, Länderfeld an jedem Arbeitsort. Arbeitsorte außerhalb Deutschlands werden heute als „Ausland“
ausgewiesen. Für eine Anbindung fehlen Grenzen und Ortsreferenz des jeweiligen Landes, die Zuordnungsregeln und
geprüfte Quellen.
