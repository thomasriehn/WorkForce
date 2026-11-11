# WorkForce

Selbst gehostete Anwendung, die öffentlich ausgeschriebene Stellenanzeigen aus freigegebenen Quellen erfasst, ihre
Entwicklung über die Zeit dokumentiert und regionale Schwerpunkte auf einer Deutschlandkarte (Landkreise und
kreisfreie Städte) sichtbar macht – ergänzt um amtliche Bevölkerungs- und Arbeitsmarktkennzahlen.

> WorkForce beobachtet **Stellenanzeigen als Hinweis auf Arbeitskräftebedarf**. Die Zahlen sind weder die Anzahl
> offener Arbeitsplätze noch ein amtlicher Nachweis von Fachkräftemangel. Eine Anzeige kann mehrere Stellen
> betreffen; derselbe Bedarf kann auf mehreren Portalen erscheinen.

## Stand dieser Version (0.1.0, 10.11.2026)

| Bereich | Stand |
|---|---|
| Erfassung | Nächtliche Läufe mit Checkpoints, Pause/Fortsetzung, Testläufen, Schutz vor Überlappung; unveränderliche Inhaltsversionen, kompakte Beobachtungen, Statusableitung, Dublettenzusammenführung |
| Quellen | **Zielabdeckung nicht erreicht.** Technisch umgesetzt: RSS-Feed von service.bund.de (live geprüft), karriere.bund.de, INTERAMT, greenjobs, BA-Jobsuche (HTML/JSON-LD, Live-Prüfung ausstehend), generischer Adapter für Arbeitgeber-Karriereseiten. Freigabestatus und Grenzen: [docs/quellenregister.md](docs/quellenregister.md) |
| Freigabe | Keine Quelle ist automatisch aktiv. Der Betreiber gibt Quellen mit Freigabevermerk frei |
| Suche | Freitext mit Phrasen, UND/ODER, Ausschlüssen; Filter nach Beruf (KldB), Qualifikationen, Region, Umkreis, Zeitraum, Status, Quelle; gespeicherte Suchen, CSV-Export |
| Karte | Kreisflächen ohne externen Kartendienst; anteilig gezählte Anzeigen, unterschiedliche Anzeigen, Rate je 1.000 Einwohner (15 bis unter 65), Veränderung über 7/30/90 Tage bei vergleichbarer Abdeckung |
| Amtliche Daten | Verwaltungsgrenzen (BKG VG250), Gemeindeverzeichnis, KldB 2010/2020, Arbeitsmarktdaten der BA-Statistik, Bevölkerung nach Altersgruppen; mit Berichtszeitraum, Prüfsumme und Revisionen |
| Betrieb | Docker Compose, Migrationen, Healthchecks, Rollen Administrator/Leser, Sicherung und Wiederherstellung |

Was tatsächlich geprüft wurde und was nicht, steht in [docs/tests.md](docs/tests.md).

## Schnellstart

Voraussetzungen: Linux mit Docker Engine und Compose-Plugin (Zielumgebung: LXC unter Proxmox, siehe
[docs/proxmox-lxc.md](docs/proxmox-lxc.md)), ausgehender HTTPS-Zugang, etwa 4 GB RAM.

```bash
git clone https://github.com/thomasriehn/WorkForce.git && cd WorkForce
```

```bash
cp .env.example .env && chmod 600 .env
```

In `.env` mindestens setzen:

- `POSTGRES_PASSWORD` – langes Zufallspasswort,
- `WF_CRAWLER_CONTACT` – Kontakt des Betreibers (URL oder E-Mail). Er erscheint im User-Agent; ohne Angabe werden
  keine Scans gestartet.

```bash
docker compose up -d --build
```

Der erste Build dauert einige Minuten (Oberfläche, Python-Abhängigkeiten, Chromium). Migrationen und Stammdaten
laufen automatisch im Dienst `migrate`.

```bash
docker compose ps
```

Administrator anlegen (das Passwort wird einmalig angezeigt; es gibt kein Standardpasswort):

```bash
docker compose exec web workforce user create admin --role admin --generate
```

Die Oberfläche ist danach unter `http://127.0.0.1:8080` erreichbar. Für den Zugriff aus dem Netz gehört ein
Reverse Proxy mit TLS davor (`deploy/Caddyfile.example`, `deploy/nginx.conf.example`). Für einen lokalen Test ohne
TLS `WF_COOKIE_SECURE=false` setzen.

## Erststart in vier Schritten

1. **Amtliche Referenzdaten importieren** (Kreisgrenzen, Ortsreferenz, Berufsklassifikation, Bevölkerung):
   [docs/betrieb.md](docs/betrieb.md#erstimport-amtlicher-daten).
2. **Quelle freigeben:** Quellenregister lesen, dann in der Quellenverwaltung oder per CLI mit Freigabevermerk
   aktivieren, zum Beispiel:

   ```bash
   docker compose exec web workforce source activate service_bund_rss --basis "robots.txt und Impressum geprüft am TT.MM.JJJJ; offizieller RSS-Feed; nur Rumpfdaten"
   ```

3. **Ersten Lauf starten** (sonst läuft er automatisch um 03:15 Uhr Europe/Berlin):

   ```bash
   docker compose exec web workforce scan service_bund_rss
   ```

4. **Ortszuordnungen nachziehen**, falls Anzeigen vor dem Import der Kreisgrenzen erfasst wurden:

   ```bash
   docker compose exec web workforce geo-rematch
   ```

Der erste Lauf einer Quelle ist eine **Bestandsaufnahme**: Die dabei gesehenen Anzeigen gelten nicht als neu
veröffentlicht.

Die BA-Statistik wird standardmäßig automatisch geprüft und importiert (`WF_STATS_BA_AUTO=true`, Kontaktangabe
erforderlich). Bestehende `.env`-Dateien mit `false` überschreiben diesen Standard. BA-Jobsuche und BA-Statistik sind
getrennte Quellen: Einrichtung des neuen Jobsuche-Adapters und begrenzte Suchbereiche siehe
[docs/ba-jobsuche.md](docs/ba-jobsuche.md).

## Bedienung

| Bereich | Inhalt |
|---|---|
| Dashboard | Beobachtete Anzeigen, Quellenstatus, Veränderungen, Datenstand, regionale Schwerpunkte, Warnungen |
| Stellensuche | Kombinierbare Filter, Trefferliste mit Originalverweisen, gespeicherte Suchen, CSV-Export |
| Karte | Kennzahl, Zeitvergleich, Berufs- und Qualifikationsfilter; Klick auf einen Kreis filtert Liste und Diagramm |
| Regionendetail | Anzeigenentwicklung, häufige Berufe und Qualifikationen, amtliche Kontextdaten |
| Anzeigendetail | Rumpfdaten, Quellverweise, Beobachtungsstatus, Änderungsverlauf |
| Quellenverwaltung | Register, Freigabe, Suchbereiche, Budgets, Scanprotokolle, manuelle Läufe, Fehlergründe |
| Methodik und Quellen | Zählweise, Definitionen, Abdeckung, Datenstände, Quellenangaben |

Suchsyntax: `"Software Engineer" UND (C++ ODER C#) -SAP`, Präfixsuche mit `entwickl*`. Durchsucht werden Titel,
Arbeitgeber, Berufsangaben, gespeicherte Merkmale und Arbeitsorte – nicht der Volltext, der nicht gespeichert wird.

## Dokumentation

| Dokument | Inhalt |
|---|---|
| [docs/betrieb.md](docs/betrieb.md) | Installation, Erstimport, Administration, Updates, Fehlersuche, Sicherung und Wiederherstellung, Dimensionierung |
| [docs/proxmox-lxc.md](docs/proxmox-lxc.md) | Docker im LXC unter Proxmox: Voraussetzungen laut offizieller Dokumentation, ungetestete Punkte |
| [docs/quellenregister.md](docs/quellenregister.md) | Alle Portale mit Status, Prüfdatum und belegten Einschränkungen |
| [docs/methodik.md](docs/methodik.md) | Zählregeln, Definitionen, Formeln, Grenzen der Aussagekraft |
| [docs/architektur.md](docs/architektur.md) | Architekturentscheidungen, Abläufe, Datenmodell, Sicherheit |
| [docs/tests.md](docs/tests.md) | Testanleitung, Ergebnisse, Skalierungsmessung, Wiederherstellungstest, Abnahmekriterien |

## Entwicklung

```bash
cd backend && uv sync
```

Tests benötigen eine PostgreSQL-Datenbank mit PostGIS (siehe [docs/tests.md](docs/tests.md)); externe Webseiten
werden in den Tests nie abgerufen.

```bash
cd backend && uv run pytest
```

```bash
cd frontend && npm ci && npm run build
```

## Lizenzen und Quellenangaben der Daten

Die Anwendung enthält keine Daten. Importierte amtliche Daten unterliegen den Bedingungen ihrer Herausgeber
(u. a. Datenlizenz Deutschland – Namensnennung 2.0 für Destatis und BKG; eigene Nutzungsbedingungen der Statistik der
Bundesagentur für Arbeit). Die erforderlichen Quellenvermerke werden beim Import gespeichert und in der Oberfläche
angezeigt.
