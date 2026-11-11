# Betrieb

Alle Befehle werden im Projektverzeichnis ausgeführt. `workforce …` läuft im Container:
`docker compose exec web workforce …`.

## Installation und Start

1. Docker Engine und Compose-Plugin installieren (LXC unter Proxmox: [proxmox-lxc.md](proxmox-lxc.md)).
2. Repository klonen, `.env` aus `.env.example` anlegen, `POSTGRES_PASSWORD` und `WF_CRAWLER_CONTACT` setzen,
   Datei schützen (`chmod 600 .env`).
3. Starten:

```bash
docker compose up -d --build
```

4. Zustand prüfen – alle Dienste müssen `healthy` sein, `migrate` endet mit Exit-Code 0:

```bash
docker compose ps
```

5. Administrator anlegen:

```bash
docker compose exec web workforce user create admin --role admin --generate
```

| Dienst | Aufgabe | Veröffentlicht |
|---|---|---|
| `db` | PostgreSQL 17 + PostGIS 3.5, Volume `db-data` | nein (internes Netz) |
| `migrate` | Migrationen und Stammdaten, läuft einmal je Start | nein |
| `web` | API und Oberfläche | `127.0.0.1:8080` (einstellbar) |
| `worker` | Scans, Statistikimporte, Aggregate | nein |
| `scheduler` | Zeitplan (genau eine Instanz) | nein |

Daten überleben Neustarts in den Volumes `db-data` (Datenbank) und `app-data` (heruntergeladene Quelldateien,
Exporte).

### Reverse Proxy und TLS

WorkForce lauscht nur auf `127.0.0.1:8080`. Davor gehört ein Reverse Proxy mit TLS – Beispiele in
`deploy/Caddyfile.example` und `deploy/nginx.conf.example`. `WF_COOKIE_SECURE=true` (Standard) setzt HTTPS voraus.
Läuft der Proxy auf einem anderen Host, `WF_BIND_ADDRESS` auf die interne Adresse des LXC setzen und den Port per
Firewall nur für den Proxy freigeben. PostgreSQL wird nie veröffentlicht.

## Erstimport amtlicher Daten

Reihenfolge einhalten – die Ortszuordnung braucht Grenzen und Ortsreferenz.

| Schritt | Datensatz | Herausgeber, Lizenz | Abruf |
|---|---|---|---|
| 1 | `vg250` Verwaltungsgrenzen, Kreise, Gemeinden | BKG, Datenlizenz Deutschland – Namensnennung 2.0 | automatisch |
| 2 | `gv_isys` Gemeindeverzeichnis (PLZ des Verwaltungssitzes, Bevölkerung) | Statistisches Bundesamt | automatisch |
| 3 | `kldb2010` Klassifikation der Berufe 2010, Fassung 2020 | Bundesagentur für Arbeit | manuell (siehe unten) |
| 4 | `bevoelkerung_kreise_alter` Bevölkerung nach Kreisen und Altersgruppen (GENESIS 12411-0017) | Statistisches Bundesamt, Datenlizenz Deutschland – Namensnennung 2.0 | automatisch über die öffentliche Oberfläche |
| 5 | `ba_arbeitslose_kreise` Arbeitslose und Arbeitslosenquoten je Kreis (monatlich) | Statistik der BA | manuell (siehe unten) |
| 6 | `ba_berufe` Arbeitsmarkt nach Berufen: Arbeitslose, Arbeitsuchende, gemeldete Stellen (Deutschland, West/Ost, Länder) | Statistik der BA | manuell (siehe unten) |

**Arbeitsuchende auf Kreisebene** bietet die geprüfte Standardveröffentlichung nicht an; berufsbezogene Arbeitsuchende gibt es
bis zur Bundeslandebene. Kreiswerte werden nicht aus Landeswerten geschätzt.

**Gebietsstände:** Kreisgrenzen und Bevölkerung haben den Stand 31.12.2025 (400 Kreise). Die Monatsdaten der BA und das
Gemeindeverzeichnis führen 2026 bereits 401 Kreise, weil Hanau (Schlüssel `06415`) seit 01.01.2026 kreisfrei ist. Werte zu
Schlüsseln ohne Grenze im geladenen Gebietsstand werden importiert und im Importergebnis als unbekannte Gebietsschlüssel
gemeldet, aber nicht umgerechnet; auf der Karte erscheinen sie erst mit dem nächsten VG250-Stand. Werte des
Main-Kinzig-Kreises sind über diesen Wechsel hinweg nicht vergleichbar.

Übersicht der Datensätze, ihrer Fundstellen und des letzten Stands:

```bash
docker compose exec web workforce stats list
```

Automatischer Import eines Datensatzes (entdeckt die aktuelle Datei auf der Produktseite, lädt sie, prüft die
Prüfsumme und importiert nur Neues):

```bash
docker compose exec worker workforce stats import vg250
```

Alle automatisch abrufbaren Datensätze nacheinander:

```bash
docker compose exec worker workforce stats import all
```

Danach die Ortszuordnung bereits erfasster Anzeigen ergänzen:

```bash
docker compose exec web workforce geo-rematch
```

### Dateien der BA-Statistik (automatischer und manueller Import)

Der automatische Abruf von `statistik.arbeitsagentur.de` ist standardmäßig eingeschaltet (`WF_STATS_BA_AUTO=true`).
Der Scheduler prüft täglich um `WF_STATS_CHECK_TIME` (Standard 05:30 Uhr Europe/Berlin) auf fällige Veröffentlichungen;
der Worker übernimmt Download und Import. `WF_CRAWLER_CONTACT` muss gesetzt sein. Mit `WF_STATS_BA_AUTO=false`
lässt sich der BA-Abruf abschalten. Bereits vorhandene `.env`-Dateien mit `false` behalten ihre Wirkung und müssen
bei gewünschter Aktivierung angepasst werden (`docker compose up -d` übernimmt die Änderung).
Dies aktiviert keine Jobsuche-Quelle. Nutzungsbedingungen und Quellenvermerke sind weiterhin zu beachten;
Abrufabstände, robots.txt, HTTP-429-Sperrpausen und Revisionsprüfung bleiben wirksam. Die Statistikdateien selbst
dürfen laut ihrem Impressum mit Quellenangabe gespeichert, vervielfältigt und verbreitet werden; eigene
Berechnungen sind als solche zu kennzeichnen.

Vorgehen: Datei im Browser von der Produktseite laden (die Fundstelle zeigt `workforce stats list`), dann über
*Quellenverwaltung → System → Statistikdatei importieren* hochladen oder per CLI:

```bash
docker compose cp ./datei.xlsx worker:/tmp/datei.xlsx
```

```bash
docker compose exec worker workforce stats import ba_arbeitslose_kreise --file /tmp/datei.xlsx
```

Der Import ist validiert (erwartete Blätter und Kopfzeilen, Berichtszeitraum aus der Datei, plausible Zeilenzahl)
und schreibt bei Abweichungen nichts. Der manuelle Dateiimport funktioniert auch bei abgeschaltetem automatischem Abruf.

### Eigenschaften aller Importe

- Der Berichtszeitraum bzw. Stichtag stammt aus der Datei, nicht aus dem Abrufdatum.
- Dieselbe Datei erneut zu importieren ändert nichts. Eine andere Datei für denselben Zeitraum wird als neue
  **Revision** geführt; die alte bleibt mit allen Werten erhalten.
- Quelldateien werden unter `/data/downloads/<Datensatz>/<Zeitraum>/` aufbewahrt
  (`WF_STATS_KEEP_SOURCE_FILES`).
- Die nächtliche Prüfung (`WF_STATS_CHECK_TIME`, Standard 05:30) entdeckt neue Veröffentlichungen. Monats- und
  Jahreswerte werden nie interpoliert.

## Quellen freigeben und Läufe steuern

```bash
docker compose exec web workforce source list
```

```bash
docker compose exec web workforce source show service_bund_rss
```

Freigabe mit Vermerk (bei Status „Erlaubnis erforderlich“ zusätzlich `--permission "Nachweis der Erlaubnis"`):

```bash
docker compose exec web workforce source activate service_bund_rss --basis "robots.txt und Impressum geprüft am TT.MM.JJJJ; offizieller RSS-Feed; nur Rumpfdaten"
```

```bash
docker compose exec web workforce source deactivate karriere_bund --reason "Zustimmung des Betreibers steht aus"
```

Manueller Lauf im Vordergrund; `--test --pages 2` für einen begrenzten Testlauf, der keinen Status verändert:

```bash
docker compose exec worker workforce scan service_bund_rss
```

In der Oberfläche (*Quellenverwaltung*): Freigabe, Deaktivierung mit Grund, Abrufbudget, Suchbereiche, manuelle
Läufe und Testläufe, Pause, Fortsetzung, Abbruch, Wiederholung, Scanprotokolle mit Fehlergründen.

| Einstellung | Bedeutung | Standard |
|---|---|---|
| `WF_SCAN_TIME`, `WF_TIMEZONE` | Uhrzeit und Zeitzone des Tageslaufs | 03:15, Europe/Berlin |
| Abstand je Quelle | Mindestabstand zwischen Abrufen; `Crawl-delay` aus robots.txt gilt zusätzlich | je Quelle 3–30 s |
| Seiten-/Detailbudget je Quelle | Obergrenze je Lauf; Überschreitung ergibt einen partiellen Lauf | je Quelle |
| `WF_MISSING_SCANS_THRESHOLD` | vollständige Scans bis „vermutlich entfernt“ | 3 |
| `WF_DETAIL_RECHECK_DAYS` | turnusmäßige Nachprüfung von Detailseiten | 7 |
| `WF_TECHNICAL_LOG_RETENTION_DAYS` | Aufbewahrung technischer Protokolle | 90 |

Ein geänderter Suchbereich wird als **neue Version** gespeichert. Ihr erster Lauf ist eine Bestandsaufnahme;
Zeitvergleiche über den Wechsel hinweg werden als nicht vergleichbar ausgewiesen.

**Aufbewahrung:** Gelöscht werden nur technische Protokolle (Fehlerprotokoll der Läufe, abgeschlossene Jobs,
abgelaufene Sitzungen, Cache-Metadaten). Läufe, Beobachtungen, Inhaltsversionen, Ereignisse und Statistikstände
werden nie automatisch gelöscht.

## Benutzer

```bash
docker compose exec web workforce user create leserin --role reader --generate
```

```bash
docker compose exec web workforce user reset-password admin
```

```bash
docker compose exec web workforce user list
```

Rollen: `admin` (darf ändern) und `reader` (nur lesen). Passwörter haben mindestens 12 Zeichen; nach acht
Fehlversuchen ist das Konto 15 Minuten gesperrt.

## Überwachung

- **Dashboard und Quellenverwaltung:** letzter Lauf, Datenstand, Fehlergründe, offene Warnungen (veraltete Quelle,
  ungewöhnlich große Bestandsänderung, blockierter Lauf).
- **Healthchecks:** `web` über `/healthz`, `worker` und `scheduler` über ein Lebenszeichen in der Datenbank
  (`docker compose ps`).
- **Logs:** strukturiert als JSON je Zeile.

```bash
docker compose logs --since 1h worker
```

## Updates

1. Sicherung erstellen (siehe unten).
2. Neuen Stand holen und neu bauen; Migrationen laufen automatisch im Dienst `migrate`:

```bash
git pull
```

```bash
docker compose up -d --build
```

3. `docker compose ps` und die Quellenverwaltung prüfen.

Die Basis-Images sind mit Tag und Digest gepinnt (`Dockerfile`, `compose.yaml`), Python-Pakete über
`backend/uv.lock`, Node-Pakete über `frontend/package-lock.json`. Aktualisierung der Pins: Digests mit
`docker pull <image>:<tag>` und `docker inspect --format '{{index .RepoDigests 0}}' <image>:<tag>` neu ermitteln,
`uv lock --upgrade` bzw. `npm update` ausführen, Tests laufen lassen. Ein Wechsel der PostgreSQL-Hauptversion
erfordert Dump und Restore.

Ändern sich Parser- oder Klassifikationsregeln, erscheinen betroffene Anzeigen mit einer Version der Art `parser`
und ein Vermerk in der Zeitleiste; sie zählen nicht als fachliche Änderung.

## Sicherung und Wiederherstellung

Die Sicherung besteht aus einem vollständigen `pg_dump` (Schema und Daten), dem Archiv des Volumes `app-data`
(Quell- und Referenzdateien) und der Konfiguration (`.env`, `compose.yaml`, `deploy/`). Eine Kopie des laufenden
Datenbankverzeichnisses ist keine gültige Sicherung.

```bash
scripts/backup.sh /pfad/zum/sicherungsziel
```

Das Sicherungsverzeichnis enthält `workforce_db.dump`, `workforce_db.toc` (Lesbarkeitsprüfung), `rowcounts.tsv`,
`app_data.tar.gz`, `config.tar.gz` und `SHA256SUMS`. `config.tar.gz` enthält Secrets – das Ziel entsprechend
schützen und auf ein anderes System kopieren. Für tägliche Sicherungen einen Cron-Eintrag oder systemd-Timer auf dem
LXC einrichten.

Probe-Wiederherstellung in eine **frische Testdatenbank** mit Vergleich von Schemaversion und Zeilenzahlen (ändert
nichts am Betrieb):

```bash
scripts/restore.sh --verify /pfad/zum/sicherungsziel/20261110T230000Z
```

Vollständige Wiederherstellung (hält die Anwendung an, ersetzt Datenbank und `app-data`):

```bash
scripts/restore.sh --replace /pfad/zum/sicherungsziel/20261110T230000Z
```

Auf einem neuen System: Repository klonen, `config.tar.gz` entpacken, `docker compose up -d db`, dann
`scripts/restore.sh --replace …`. Das Ergebnis des durchgeführten Wiederherstellungstests steht in
[tests.md](tests.md).

## Fehlersuche

| Symptom | Ursache und Abhilfe |
|---|---|
| `migrate` endet mit Fehler | `docker compose logs migrate`. Häufig: `POSTGRES_PASSWORD` nachträglich geändert – das Volume `db-data` kennt noch das alte Passwort. |
| Anmeldung schlägt trotz richtigem Passwort fehl | Zugriff über HTTP bei `WF_COOKIE_SECURE=true`: Der Browser sendet das Cookie nicht. TLS-Proxy verwenden oder für einen Test auf `false` setzen. |
| Es werden keine Läufe geplant | `WF_CRAWLER_CONTACT` leer, keine Quelle freigegeben oder Scheduler nicht `healthy`. |
| Lauf „abgelehnt“ | Quelle nicht freigegeben, oder es läuft bereits ein Scan derselben Quelle. |
| Lauf `blocked` | Die Quelle hat den Zugriff verweigert (403, 429, CAPTCHA, robots.txt). Nicht umgehen: Grund im Protokoll lesen, Abstand erhöhen oder beim Betreiber anfragen. |
| Lauf `partial` | Seitenlimit, Trefferobergrenze oder nicht belegbare Abdeckung. Budget prüfen bzw. Suchbereich enger fassen. Der Lauf zählt nicht als verpasste Sichtung. |
| Lauf `failed` mit Parserfehler | Aufbau der Quelle geändert. Der Bestand bleibt unverändert; der Adapter muss angepasst werden. |
| Karte leer | Kreisgrenzen fehlen: `workforce stats import vg250`, danach `workforce geo-rematch`. |
| Rate je 1.000 Einwohner fehlt | Bevölkerungsdaten fehlen oder die Altersgruppen decken 15 bis unter 65 nicht exakt ab – dann wird bewusst kein Quotient gebildet. |
| Viele Anzeigen „ungeklärt“ | Ortsreferenz fehlt oder Ortsangaben sind mehrdeutig; nach dem Import `workforce geo-rematch` ausführen. |
| Statistikimport bricht mit Validierungsfehler ab | Aufbau der Datei weicht ab. Es wurde nichts geschrieben; die Meldung nennt die Abweichung. |
| Worker `unhealthy` | `docker compose logs worker`; Datenbank erreichbar? Nach einem Neustart werden verwaiste Jobs automatisch wieder eingereiht. |

## Dimensionierung (Planungsannahme)

| Ressource | Startwert | Begründung |
|---|---|---|
| CPU | 2 vCPU | Abrufe sind durch Abrufabstände gedrosselt; Last entsteht durch Abfragen und nächtliche Aggregate. |
| RAM | 4 GB (+ 1 GB Swap) | PostgreSQL mit 512 MB `shared_buffers`, drei Python-Prozesse, zeitweise Chromium für Statistik-Exporte. |
| Speicher | 40 GB | Image mit Chromium rund 2,5 GB zuzüglich PostGIS-Image, Geodaten und Quelldateien unter 1 GB, Datenbank rund 1 GB je 100.000 Quellanzeigen mit 4,4 Mio. Beobachtungen, dazu Sicherungen. |

Grundlage ist der Skalierungstest mit synthetischen Daten auf der Entwicklungsmaschine (siehe [tests.md](tests.md)).
Auf Proxmox wurde nicht gemessen; die Werte sind eine Planungsannahme. Die Speichereinstellungen von PostgreSQL
stehen in `.env` (`PG_SHARED_BUFFERS`, `PG_EFFECTIVE_CACHE_SIZE`, `PG_WORK_MEM`) und sollten bei mehr RAM angehoben
werden. Mehr Ressourcen sind angezeigt bei vielen aktiven Quellen, deutlich über einer Million Beobachtungen im
Monat oder Kartenabfragen über einer Sekunde.
