# Methodik, Zählregeln und Grenzen der Aussagekraft

Stand der Regeln: Zusammenführung `dedup-1`, Klassifikation `klass-1`, Georeferenz `geo-1`, Aggregate `agg-1`.
Die Regelversionen stehen an jeder Inhaltsversion, jeder Zusammenführung und jedem Tagesaggregat.

## 1. Was gezählt wird – und was nicht

WorkForce beobachtet **Stellenanzeigen als Hinweis auf Arbeitskräftebedarf**.

- Eine Anzeige ist nicht ein Arbeitsplatz. Eine Anzeige kann mehrere Stellen betreffen; derselbe Bedarf kann auf
  mehreren Portalen erscheinen. Ein Plural im Titel belegt keine bestimmte Stellenzahl.
- Die Zahlen sind weder die Anzahl offener Arbeitsplätze noch ein amtlicher Nachweis von Fachkräftemangel.
- Eine hohe Anzeigenzahl oder -rate ist ein **Hotspot der erfassten Nachfrage**. Ein Fachkräfteengpass folgt
  daraus nicht automatisch.
- Erfasst wird nur, was die freigegebenen Quellen in ihren Suchbereichen zeigen. Das ist keine Vollerhebung des
  Stellenmarkts (siehe Abschnitt 9).

## 2. Quellanzeige und zusammengeführte Anzeige

| Begriff | Bedeutung |
|---|---|
| Quellanzeige | Eine Anzeige auf genau einem Portal, identifiziert über die stabile Quell-ID. |
| Inhaltsversion | Unveränderlicher Stand der Rumpfdaten einer Quellanzeige. Eine neue Version entsteht nur bei tatsächlicher Änderung. |
| Beobachtung | Kompakter Nachweis: Quellanzeige wurde in einem logischen Lauf gesehen (keine tägliche Vollkopie). |
| Zusammengeführte Anzeige | Portalübergreifende Einheit. Jede Quellanzeige gehört zu genau einer; alle Originalverweise bleiben erhalten. |

Gespeichert werden Rumpfdaten und strukturierte Extraktionsergebnisse. Der Volltext wird nur flüchtig für die
Extraktion verarbeitet und nicht archiviert. Ansprechpartner, Kontaktdaten, Lebensläufe und Bewerberprofile werden
nicht erfasst. Für Quellen, deren Bedingungen die Übernahme von Texten vorbehalten, werden auch keine kurzen
Belegauszüge gespeichert (Adaptermerkmal `store_excerpts`).

### 2.1 Wann entsteht eine neue Inhaltsversion?

Der Inhalts-Hash umfasst die fachlichen Felder: normalisierter Titel, Arbeitgeber, Stellenreferenz,
Arbeitgeber-Zielverweis, Arbeitsorte, Anzeigenart, Arbeitszeit, Befristung, Remote-Status, Vergütung, Fristen und die
extrahierten Merkmale samt Polarität. **Nicht** enthalten sind Trackingparameter, Abrufzeit, Veröffentlichungsdatum
der Quelle und dynamische Seitenelemente.

| Art der Version | Auslöser | Zählt als fachliche Änderung? |
|---|---|---|
| `initial` | erste Erfassung | nein |
| `enrichment` | Detailseite ergänzt eine zuvor nur aus der Liste bekannte Anzeige | nein |
| `content` | Inhalt geändert bei unveränderten Regeln | **ja** |
| `parser` | Rohinhalt unverändert, Extraktion anders (neue Parser-/Klassifikationsregeln) | nein, gesondert gekennzeichnet |
| `mixed` | Inhalt und Regeln gleichzeitig geändert, nicht trennbar | nein, gesondert gekennzeichnet |

Historische Versionen werden nie überschrieben. Filter zu einem Stichtag greifen auf die damals gültige Version zu.
Einzige Ausnahme: Nach dem Import einer Ortsreferenz werden **bisher fehlende** Ortszuordnungen aktueller Versionen
ergänzt (`workforce geo-rematch`); belegte Zuordnungen bleiben unverändert.

## 3. Dubletten (`dedup-1`)

Innerhalb einer Quelle gilt die stabile Quell-ID. Portalübergreifend wird nur bei starker Evidenz automatisch
zusammengeführt:

| Regel | Bedingung | Konfidenz |
|---|---|---|
| `employer_reference` | gleicher Arbeitgeber und gleiche Stellenreferenz des Arbeitgebers | 0,95 |
| `employer_url` | identischer Arbeitgeber-Zielverweis (Deep-Link, ohne Trackingparameter) | 0,90 |
| `employer_title_location` | gleicher Arbeitgeber, gleicher normalisierter Titel, gleiche Anzeigenart, gleiche Kreis-Menge, Veröffentlichungsdaten höchstens 45 Tage auseinander | 0,82 |

Automatisch zusammengeführt wird ab Konfidenz 0,80. **Ein ähnlicher Titel allein genügt nie.**

Schutzregeln – diese Fälle werden nicht vereinigt, sondern als unsicherer Kandidat vorgemerkt:

- disjunkte Arbeitsorte (Niederlassungen),
- Personalvermittlung/Zeitarbeit bei Regel `employer_title_location`,
- zwei gleichzeitig aktive Anzeigen derselben Quelle (echte parallele Ausschreibung),
- nur ähnlicher Titel oder nur überlappende Orte.

Jede Entscheidung trägt Grund, Konfidenz und Regelversion. Zusammenführungen sind umkehrbar; manuell getrennte
Paare werden nicht erneut automatisch vereinigt.

Folgen für die Zählung:

- Erscheint eine bekannte Anzeige auf einem weiteren Portal, ist das eine **zusätzliche Veröffentlichung**, kein
  neuer Bedarf.
- Taucht eine neue Quell-ID auf, die zu einer nicht mehr aktiven zusammengeführten Anzeige passt, ist das eine
  **Wiederveröffentlichung**.
- Taucht dieselbe Quell-ID nach einem Wegfall wieder auf, ist das eine **Reaktivierung**.
- Nur was zu keiner bestehenden Anzeige passt, zählt als erstmals beobachtete Anzeige.

## 4. Anzeigenstatus

| Status | Bedeutung |
|---|---|
| aktiv beobachtet | im jüngsten maßgeblichen Scan gesehen (bei Feed-Quellen: laut Quelle bis zum angekündigten Ende veröffentlicht) |
| nicht erneut beobachtet | in mindestens einem vollständigen, vergleichbaren Scan ihres Suchbereichs nicht mehr gesehen |
| vermutlich entfernt | in **drei** solchen Scans nicht mehr gesehen, oder Detailseite an zwei verschiedenen Tagen mit HTTP 404/410 nicht verfügbar. Bleibt eine Ableitung. |
| als beendet beobachtet | eindeutiger Ablaufhinweis der Quelle oder das von der Quelle angekündigte Veröffentlichungsende ist erreicht |
| unbekannt/veraltet | seit über 14 Tagen kein vergleichbarer Scan – der Zustand ist nicht bekannt |

Grundsätze:

- Als verpasste Sichtung zählt nur ein Lauf mit Abschlussstatus `complete`, vollständiger Listenentdeckung, Modus
  `full` und derselben Suchbereichsversion.
- **Keine Schließungsnachweise** sind: CAPTCHA, HTTP 403, Timeout, Parserfehler, Seitenlimit, Trefferobergrenze,
  wiederholte oder leere Seiten, Suchbereichswechsel und Quellen, die nur neue Anzeigen melden.
- Zeigt eine andere Quelle dieselbe Anzeige noch aktiv, bleibt die zusammengeführte Anzeige aktiv.
- Eine entfernte Anzeige belegt nicht, dass die Stelle besetzt wurde.
- `first_seen_at` (erstmals beobachtet) ersetzt kein unbekanntes Veröffentlichungsdatum.

Die Schwellen sind konfigurierbar (`WF_MISSING_SCANS_THRESHOLD`, `WF_STALE_AFTER_DAYS`).

## 5. Läufe und Abdeckung

Je Quelle, Suchbereich und lokalem Tagesdatum (Europe/Berlin) gibt es genau einen logischen Tageslauf. Testläufe mit
Seitenlimit sind davon ausgenommen und verändern keinen Status.

| Abschlussstatus | Bedeutung |
|---|---|
| `complete` | Listenentdeckung vollständig. Die Detailanreicherung wird getrennt ausgewiesen (`detail_complete`). |
| `partial` | Seitenlimit, Trefferobergrenze, wiederholte/leere Seite oder nicht belegbare Abdeckung |
| `blocked` | Sperrsignal der Quelle (403, 429 trotz Backoff, CAPTCHA, robots.txt). Es gibt keinen Umgehungsversuch. |
| `failed` | keine Listenseite verarbeitbar (z. B. Layoutänderung) |
| `cancelled` | vom Administrator abgebrochen |

Abdeckung wird nur aus überprüfbaren Signalen abgeleitet (vom Portal gemeldete Trefferzahl, gelesene Seiten,
Sitemap-Umfang, Überlappung des Feedfensters). Es werden keine Prozentwerte geschätzt.

**Feed-Quellen** (z. B. der RSS-Feed von service.bund.de) melden nur die neuesten Einträge. Ein Lauf gilt als
vollständig, wenn sein Fenster mit dem des vorherigen Laufs überlappt; sonst können neue Anzeigen fehlen und der
Lauf ist `partial`. Das Fehlen älterer Anzeigen im Feed ist nie ein Schließungssignal.

## 6. Regionen und Zählregeln

Auswertungsebene sind Landkreise und kreisfreie Städte (fünfstelliger Kreisschlüssel als Zeichenkette mit führenden
Nullen), ergänzt um Bundesländer. Maßgeblich ist der Arbeitsort, nicht der Unternehmenssitz.

### 6.1 Zuordnung der Arbeitsorte (`geo-1`)

1. Liefert die Quelle Koordinaten, entscheidet Punkt-in-Polygon gegen die Kreisgrenzen.
2. Sonst der Ortsname in der lokal importierten Ortsreferenz. Bei mehrdeutigen Namen entscheiden Bundeslandangabe
   und PLZ. Bleibt es mehrdeutig, wird **nicht** zugeordnet.
3. Kreisnamen werden dem Kreis zugeordnet; ein Bundeslandname allein gilt für die Kreiskarte als ungeklärt.
4. Alles Übrige bleibt in der Kategorie „ungeklärt“.

Zu jedem Arbeitsort werden Methode, Genauigkeit, Konfidenz und Gebietsstand gespeichert. Es werden keine
Stellenkoordinaten erfunden. Ortsmittelpunkte (auch für die Umkreissuche) sind als angenähert gekennzeichnet.

### 6.2 Zählregeln

| Kennzahl | Regel |
|---|---|
| Deutschlandweit | Jede zusammengeführte Anzeige zählt genau einmal. |
| **Anteilig gezählte Anzeigen** (Kreiskarte) | Anzeige mit `k` eindeutig zugeordneten Kreisen zählt je Kreis `1/k` – nur wenn **alle** genannten Arbeitsorte zugeordnet sind. |
| Unterschiedliche Anzeigen mit Bezug zum Kreis | Jede Anzeige zählt je Kreis ganz. Diese Zahlen sind **nicht addierbar**. |
| Geografisch teilweise ungeklärt | Mehrfachstandorte mit mindestens einem ungeklärten Ort: nicht in der anteiligen Karte, separat ausgewiesen; der belegte Kreisbezug bleibt in „unterschiedliche Anzeigen“ und in der Liste erhalten. |
| Deutschlandweit remote | Eigene Kategorie, keinem Ort und nicht allen Kreisen zugeschlagen. |
| Hybrid | Zählt am belegten Arbeitsort. |
| Ausbildung, duales Studium, Praktika | Getrennte Auswertung von regulären Stellen. |

Die Summe der anteilig gezählten Anzeigen über alle Kreise entspricht genau der Zahl der Anzeigen mit vollständig
zugeordneten Arbeitsorten.

### 6.3 Formeln

- Anteilig gezählte Anzeigen im Kreis `K` = Σ über Anzeigen mit vollständig zugeordneten Orten und `K` in ihren
  Kreisen: `1 / (Anzahl unterschiedlicher Kreise der Anzeige)`.
- Anzeigen je 1.000 Einwohner 15 bis unter 65 = anteilig gezählte Anzeigen / Bevölkerung 15 bis unter 65 × 1.000.
  Bei fehlendem oder nullwertigem Nenner wird **kein Quotient** berechnet.
- Veränderung über 7/30/90 Tage = Wert am Stichtag − Wert am Vergleichstag. Die prozentuale Veränderung wird nur
  bei Ausgangswert > 0 ausgewiesen; bei Ausgangswert 0 nur die absolute Veränderung mit Hinweis.

## 7. Zeitreihen und Vergleichbarkeit

| Reihe | Definition |
|---|---|
| Bestand | Zusammengeführte Anzeigen, die am Tag zum beobachteten Bestand zählten. Wird rückwirkend korrigiert, sobald ein Wegfall bestätigt ist; die letzten Tage sind daher vorläufig. |
| Erstmals beobachtet | Neue zusammengeführte Anzeigen, **ohne** Bestandsaufnahmen. |
| Bestandsaufnahme | Beim Erstlauf einer Quelle oder Suchbereichsversion erstmals gesehene Anzeigen. Keine Welle neuer Stellen. |
| Fachlich geändert | Anzeigen mit Version der Art `content`. |
| Aus dem Bestand gefallen | vermutlich entfernt, beendet laut Quelle oder veraltet; datiert auf den Tag nach der letzten Sichtung. |

- Vor Inbetriebnahme liegende Historie wird nicht erfunden.
- Tage ohne oder mit unvollständigen Läufen sind als Datenlücke bzw. eingeschränkt vergleichbar markiert.
- Zeitvergleiche rechnen nur mit Quellen, die an beiden Stichtagen mit **denselben Suchbereichsversionen
  vollständig** erfasst wurden. Neue Quellen, geänderte Suchbereiche und unvollständige Läufe werden mit Grund
  ausgeschlossen. Parserwechsel erscheinen als Hinweis.
- Liste, Karte, Summen und Diagramme verwenden dieselbe Bezugsbasis und dieselben Filter. Der Kreisfilter wirkt auf
  Liste und Diagramme; die Karte zeigt weiterhin alle Kreise.

## 8. Berufe, Qualifikationen und Suche

- **Berufsklassifikation:** Zuordnung zur KldB 2010 (überarbeitete Fassung 2020) über die Berufsangabe der Quelle
  oder den Titel (exakt, sonst ähnlich). Herkunft und Konfidenz werden gespeichert; unsichere Zuordnungen bleiben
  sichtbar. Die KldB-Zuordnung belegt **keinen** ausdrücklich verlangten Abschluss.
- **Merkmale** werden regelbasiert und lokal extrahiert, getrennt nach formalem Abschluss, Erfahrung, Kenntnissen,
  Sprachen, Zertifikaten und Berechtigungen. Je Merkmal: Herkunft, Regelversion, Konfidenz und – wo zulässig – ein
  kurzer Beleg.
- **Polarität:** ausdrücklich verlangt, erwünscht, verneint, unklar. „Keine Berufserfahrung erforderlich“ wird als
  *verneint* gespeichert und nie als verlangte Berufserfahrung gefunden.
- **Suche:** durchsucht werden Titel, Arbeitgeber, Berufsangabe, gespeicherte Merkmale und Arbeitsorte. Der Volltext
  der Anzeigen ist nicht gespeichert und wird nicht durchsucht. Unterstützt werden Phrasen, UND/ODER, Ausschluss,
  Präfixsuche, Umlaute, eine lokale Synonymliste und Bezeichnungen wie C++, C# und .NET.

## 9. Amtliche Statistik

- Je Datenstand werden Berichtszeitraum bzw. Stichtag (aus der Datei, nicht aus dem Abrufdatum), Abrufdatum,
  Prüfsumme, Quelle, Lizenz und Revision gespeichert. Das Veröffentlichungsdatum nur, wenn es bekannt ist.
- Derselbe Berichtszeitraum mit anderer Datei ist eine amtliche Korrektur: neue Revision, die alte bleibt erhalten.
- Echte Nullwerte, unterdrückte, unbekannte, nicht verfügbare und nicht erhobene Werte werden unterschieden.
  Fehlwerte sind nie Null. Es wird nicht interpoliert und nichts aufgefüllt.
- **Arbeitslose und Arbeitsuchende sind unterschiedliche Größen** (Arbeitsuchende können beschäftigt sein) und
  werden getrennt gespeichert und beschriftet.
- Berufsbezogene Anzeigenzahlen werden nicht mit allen Arbeitslosen oder Arbeitsuchenden verrechnet. Ein
  berufsspezifischer Verhältnisindikator setzt passende Regionen, Klassifikationen, Populationen und Zeiträume
  voraus; andernfalls stehen die Größen getrennt nebeneinander. Landeswerte werden nicht auf Kreise verteilt.
- Die Bevölkerung 15 bis unter 65 wird nur gebildet, wenn die Altersgruppen diesen Bereich lückenlos und ohne
  Überschneidung abdecken (eigene Berechnung, als solche gekennzeichnet).

## 10. Grenzen

- **Abdeckung:** Der allgemeine privatwirtschaftliche Stellenmarkt ist derzeit nicht abgedeckt. Die BA-Jobsuche,
  Stepstone, Indeed, meinestadt.de und academics untersagen automatisierte Abrufe in ihren Bedingungen; weitere
  Portale sperren automatisierte Zugriffe technisch. Einzelheiten: [quellenregister.md](quellenregister.md).
- **Segment:** Die technisch umgesetzten Quellen stammen überwiegend aus dem öffentlichen Dienst. Regionale
  Unterschiede spiegeln daher auch die Verteilung öffentlicher Arbeitgeber.
- **Feed-Quellen:** Ohne Detailprüfung ist der Bestand „laut Quelle bis zum angekündigten Ende veröffentlicht“, nicht
  täglich neu bestätigt.
- **Extraktion:** Regelbasierte Erkennung kann Anforderungen übersehen oder falsch einordnen. Die Polarität
  „unklar“ existiert aus diesem Grund.
- **Ortszuordnung:** Die PLZ-Referenz kennt je Gemeinde nur die PLZ des Verwaltungssitzes. Mehrdeutige Ortsnamen
  ohne weitere Angabe bleiben ungeklärt.
- **Gebietsreformen:** Jede Region und jeder Statistikwert trägt seinen Gebietsstand. Unterschiedliche Stände werden nicht
  stillschweigend umgerechnet. Aktuelles Beispiel: Hanau ist seit 01.01.2026 kreisfrei; Grenzen und Bevölkerung (Stand
  31.12.2025) kennen den Kreis noch nicht, die Monatsdaten der BA schon.
- **Arbeitsuchende** liegen aus der geprüften Standardveröffentlichung nur berufsbezogen bis zur Bundeslandebene vor, nicht je
  Kreis.
- **Geringe Fallzahlen** sind in Karte und Tabellen gekennzeichnet (`WF_SMALL_COUNT_THRESHOLD`, Standard 5).
