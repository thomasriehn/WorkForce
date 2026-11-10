# Quellenregister

Prüfdatum aller Einträge: **10.11.2026**. Diese Datei wird aus `backend/workforce/sources/registry.py` erzeugt
(`uv run python scripts/render_quellenregister.py`). Der laufende Stand einer Installation steht in der Quellenverwaltung.

> Das Register dokumentiert, was robots.txt und die veröffentlichten Bedingungen der Portale am Prüfdatum sagen. Es ist
> keine Rechtsberatung. Ob Nutzungsbedingungen einen nicht registrierten Besucher binden und ob Titel, Arbeitgeber und Ort
> überhaupt schutzfähig sind, sind Rechtsfragen außerhalb dieser Prüfung. Frei sichtbare Inhalte allein belegen keine
> Erlaubnis zur automatisierten Weiterverwendung.

## Ergebnis in Kürze

- **Zielabdeckung nicht erreicht:** Drei *freigegebene* Quellen aus unterschiedlichen Marktsegmenten gibt es unter den Vorgaben
  (keine Portal-APIs, Bedingungen beachten, keine Umgehung von Sperren) derzeit nicht.
- **Konkrete Grenze:** Die großen allgemeinen Portale (BA-Jobsuche, Stepstone, Indeed, meinestadt.de) und academics untersagen
  automatisierte Abrufe ausdrücklich. Monster, jobvector, Azubiyo und Absolventa antworten mit Bot-Schutz-Challenges.
  stellenanzeigen.de und yourfirm waren aus der Entwicklungsumgebung geo-gesperrt und sind ungeprüft.
- **Technisch umgesetzt** sind vier Quellenadapter plus ein generischer Adapter für Arbeitgeber-Karriereseiten. Live geprüft
  wurde der offizielle RSS-Feed von service.bund.de. Alle umgesetzten Quellen liegen im öffentlichen Dienst bzw. im
  Umweltsegment.
- **Keine Quelle ist nach der Installation automatisch aktiv.** Die Freigabe erfolgt durch den Betreiber mit Freigabevermerk;
  Quellen mit Erlaubnisvorbehalt verlangen zusätzlich den Nachweis der Erlaubnis.

## Übersicht

| Portal | Segment | Status | Adapter | Zugriffsart | Kurzgrund |
|---|---|---|---|---|---|
| [service.bund.de – Stellenangebote (RSS)](https://www.service.bund.de/Content/DE/Service/RSS/rss_node.html) | Öffentlicher Dienst: Bund, Länder, Kommunen (inkl. Importe aus 14 Partnerbörsen, u. a. INTERAMT) | vorgemerkt | `service_bund_rss` (sbrss-1) | official_rss_feed | Technisch geprüft, zur Freigabe empfohlen. Wartet auf den Freigabevermerk des Betreibers. |
| [karriere.bund.de](https://karriere.bund.de/) | Bundesverwaltung | vorgemerkt | `karriere_bund` (kbund-1) | html_list_jsonld | Technisch umgesetzt. Freigabe ist eine Betreiberentscheidung (Textvorbehalt im Impressum, s. Prüfvermerk). |
| [INTERAMT](https://karriere.interamt.de/de) | Öffentlicher Dienst | Erlaubnis erforderlich | `interamt` (interamt-1) | sitemap_jsonld | Speicherung/Übernahme nur nach vorheriger schriftlicher Zustimmung der DVZ M-V GmbH (Impressum, Rechtshinweis). |
| [greenjobs.de](https://www.greenjobs.de/) | Umwelt und Nachhaltigkeit | Erlaubnis erforderlich | `greenjobs` (greenjobs-1) | sitemap_jsonld | AGB § 12 beschränkt die Nutzung auf Abruf und Anzeige innerhalb der Portalfunktionen; Erlaubnis von greenjobs einholen. |
| [Bundesagentur für Arbeit – Jobsuche](https://www.arbeitsagentur.de/jobsuche/) | Allgemeiner Stellenmarkt (größter Bestand) | Erlaubnis erforderlich | keiner | – | Nutzungsbedingungen Nr. 2a (3) untersagen ausdrücklich den Einsatz von Robots/Webspidern. Kein Adapter. |
| [Stepstone](https://www.stepstone.de/) | Allgemeiner Stellenmarkt | Erlaubnis erforderlich | keiner | – | Nutzungsbedingungen Nr. 4.3.4 untersagen Scraping; Nr. 13.2 (i) die Nutzung zur Entwicklung anderer Dienste. Kein Adapter. |
| [meinestadt.de – Stellenmarkt](https://jobs.meinestadt.de/) | Regionaler Stellenmarkt | Erlaubnis erforderlich | keiner | – | Nutzungsbedingungen Nr. 5.2 untersagen Scraping; Nr. 12 (i) die Nutzung zur Entwicklung anderer Dienste. Kein Adapter. |
| [Indeed](https://de.indeed.com/) | Allgemeiner Stellenmarkt (Aggregator) | Erlaubnis erforderlich | keiner | – | Nutzungsbedingungen Abschnitt D.21 untersagen automatisierten Zugriff und Datenextraktion ohne schriftliche Erlaubnis. Kein Adapter. |
| [academics](https://www.academics.de/) | Hochschulen, Wissenschaft und Forschung | Erlaubnis erforderlich | keiner | – | robots.txt und Nutzungsbedingungen Nr. 4 (3) untersagen automatisierte Zugriffe ohne ausdrückliche Erlaubnis. Kein Adapter. |
| [Monster](https://www.monster.de/) | Allgemeiner Stellenmarkt | deaktiviert | keiner | – | Weiterleitung auf monster.com/de mit Bot-Schutz-Challenge (HTTP 403); kein brauchbarer deutscher Stellenbestand verifiziert. |
| [jobvector](https://www.jobvector.de/jobs/) | Technische und wissenschaftliche Fachberufe | deaktiviert | keiner | – | Bot-Schutz-Challenge bereits für robots.txt (HTTP 403, „Just a moment…“). Keine Umgehung; Anfrage beim Betreiber nötig. |
| [Azubiyo](https://www.azubiyo.de/) | Ausbildung und duales Studium (getrennt auszuwerten) | deaktiviert | keiner | – | Bot-Schutz-Challenge bereits für robots.txt (HTTP 403). Keine Umgehung; Anfrage beim Betreiber nötig. |
| [Absolventa](https://www.absolventa.de/) | Berufseinstieg, Traineeprogramme | deaktiviert | keiner | – | „Human Verification“ (WAF-Challenge, HTTP 405) bereits für robots.txt. Keine Umgehung; Anfrage beim Betreiber nötig. |
| [stellenanzeigen.de](https://www.stellenanzeigen.de/jobs/) | Allgemeiner Stellenmarkt | vorgemerkt | keiner | – | Nicht geprüft: Aus der Entwicklungsumgebung geo-gesperrt (HTTP 403). Prüfung muss aus dem Zielnetz wiederholt werden. Kein Adapter. |
| [yourfirm](https://www.yourfirm.de/stellenangebote/) | Mittelständische Arbeitgeber | vorgemerkt | keiner | – | Nicht geprüft: Aus der Entwicklungsumgebung geo-gesperrt (HTTP 403). Prüfung muss aus dem Zielnetz wiederholt werden. Kein Adapter. |
| [Jobware](https://www.jobware.de/) | Branchenübergreifend (Fach- und Führungskräfte) | vorgemerkt | keiner | – | Offen: keine Besucherbedingungen, Anzeigen-Sitemap für unbekannte Clients gesperrt (HTTP 403). Vor einer Anbindung beim Betreiber anfragen. Kein Adapter. |

Statuswerte: *vorgemerkt* (`candidate`), *aktiv* (`active`), *deaktiviert* (`disabled`), *Erlaubnis erforderlich* (`permission_required`).
Der technische Gesundheitszustand (letzter Lauf, Datenstand, Fehler) wird getrennt davon in der Quellenverwaltung geführt.

## Einzelnachweise

### service.bund.de – Stellenangebote (RSS)

- **Domain:** `www.service.bund.de` – Einstieg: https://www.service.bund.de/Content/DE/Service/RSS/rss_node.html
- **Fachliche Abdeckung:** Öffentlicher Dienst: Bund, Länder, Kommunen (inkl. Importe aus 14 Partnerbörsen, u. a. INTERAMT)
- **Konfigurationsstatus:** vorgemerkt (`candidate`)
- **Grund:** Technisch geprüft, zur Freigabe empfohlen. Wartet auf den Freigabevermerk des Betreibers.
- **Adapter:** `service_bund_rss`, Version `sbrss-1`, Zugriffsart `official_rss_feed`, Entdeckung: meldet nur neue Anzeigen, Detailseiten: none, Textauszüge: nein
- **Abrufbudget (Standard):** Abstand 30 s, höchstens 5 Listenseiten und 0 Detailseiten je Lauf
- **Suchbereich:** `stellen` v1 – RSS-Feed Stellenangebote (neueste Einträge) (Modus `new_only`)
- **Bedingungen:** https://www.service.bund.de/Content/DE/Service/Impressum/impressum_node.html
- **robots.txt:** https://www.service.bund.de/robots.txt
- **Prüfvermerk (10.11.2026):** Das Portal bietet den RSS-Feed „Stellenangebote“ selbst als maschinenlesbaren Kanal an (RSS-Seite: „Neue Angebote sofort erhalten“). robots.txt: Feed-Pfad /Content/Globals/… nicht gesperrt; gesperrt sind u. a. /Content/DE/Stellen/Suche/ und /SiteGlobals/; Crawl-delay 30 s (wird eingehalten). Impressum, Urheberrecht: Texte/Textteile dürfen, „soweit diese urheberrechtlich geschützt sind“, nicht ohne Zustimmung des Bundesverwaltungsamtes vervielfältigt werden; zu automatisierten Abrufen schweigt das Impressum. Umsetzung: nur Rumpfdaten (Titel, Behörde, PLZ/Ort, Fristen, Link), keine Textauszüge. Hinweis: Der Feed ist ein Fenster der neuesten 500 Einträge – er meldet neue Anzeigen, keine Vollerhebung.
- **Quellenangabe:** Quelle: service.bund.de (Bundesverwaltungsamt), Stellenangebote der Bundes-, Landes- und Kommunalverwaltung

### karriere.bund.de

- **Domain:** `karriere.bund.de` – Einstieg: https://karriere.bund.de/
- **Fachliche Abdeckung:** Bundesverwaltung
- **Konfigurationsstatus:** vorgemerkt (`candidate`)
- **Grund:** Technisch umgesetzt. Freigabe ist eine Betreiberentscheidung (Textvorbehalt im Impressum, s. Prüfvermerk).
- **Adapter:** `karriere_bund`, Version `kbund-1`, Zugriffsart `html_list_jsonld`, Entdeckung: vollständige Aufzählung des Suchbereichs, Detailseiten: required, Textauszüge: nein
- **Abrufbudget (Standard):** Abstand 5 s, höchstens 250 Listenseiten und 300 Detailseiten je Lauf
- **Suchbereich:** `alle` v1 – Alle Stellenangebote (Modus `full`)
- **Bedingungen:** https://karriere.bund.de/impressum
- **robots.txt:** https://karriere.bund.de/robots.txt
- **Prüfvermerk (10.11.2026):** robots.txt sperrt nur /typo3/, /typo3_src/ und einen Upload-Ordner. Keine Nutzungsbedingungen; das Impressum schweigt zu automatisierten Abrufen. Impressum Nr. 5: „Texte, Textteile, Grafiken, Tabellen oder Bildmaterialien dürfen ohne vorherige Zustimmung des Bundesministeriums für Digitales und Staatsmodernisierung nicht vervielfältigt, nicht verbreitet und nicht ausgestellt werden.“ Ob Titel/Behörde/Ort als „Textteile“ gelten, lässt die Seite offen. Umsetzung daher ohne Textauszüge; vor Freigabe Zustimmung einholen oder die Auslegung selbst verantworten. Einzelne Anzeigen stammen von INTERAMT (Dubletten).

### INTERAMT

- **Domain:** `karriere.interamt.de` – Einstieg: https://karriere.interamt.de/de
- **Fachliche Abdeckung:** Öffentlicher Dienst
- **Konfigurationsstatus:** Erlaubnis erforderlich (`permission_required`)
- **Grund:** Speicherung/Übernahme nur nach vorheriger schriftlicher Zustimmung der DVZ M-V GmbH (Impressum, Rechtshinweis).
- **Adapter:** `interamt`, Version `interamt-1`, Zugriffsart `sitemap_jsonld`, Entdeckung: vollständige Aufzählung des Suchbereichs, Detailseiten: required, Textauszüge: nein
- **Abrufbudget (Standard):** Abstand 4 s, höchstens 60 Listenseiten und 600 Detailseiten je Lauf
- **Suchbereich:** `alle` v1 – Alle Stellen laut Sitemap (Modus `full`)
- **Bedingungen:** https://karriere.interamt.de/footer/impressum
- **robots.txt:** https://karriere.interamt.de/robots.txt
- **Prüfvermerk (10.11.2026):** robots.txt sperrt nur /meininteramt und /jobs/merkliste; Sitemap öffentlich. Nutzungsbedingungen (Stand 27.01.2021) nennen keine Robots/Crawler. Impressum (Stand 04.11.2025), Rechtshinweis: Inhalte seien „als wesentliche Teile von Datenbanken“ geschützt; „Aufnahme in fremde Internetangebote und Online-Dienste … sowie Vervielfältigungen auf Datenträger aller Art …, auch auszugsweise, nur nach vorheriger schriftlicher Zustimmung“. Adapter ist technisch fertig (Sitemap + JSON-LD), läuft aber erst nach dokumentierter Zustimmung.

### greenjobs.de

- **Domain:** `www.greenjobs.de` – Einstieg: https://www.greenjobs.de/
- **Fachliche Abdeckung:** Umwelt und Nachhaltigkeit
- **Konfigurationsstatus:** Erlaubnis erforderlich (`permission_required`)
- **Grund:** AGB § 12 beschränkt die Nutzung auf Abruf und Anzeige innerhalb der Portalfunktionen; Erlaubnis von greenjobs einholen.
- **Adapter:** `greenjobs`, Version `greenjobs-1`, Zugriffsart `sitemap_jsonld`, Entdeckung: vollständige Aufzählung des Suchbereichs, Detailseiten: required, Textauszüge: nein
- **Abrufbudget (Standard):** Abstand 5 s, höchstens 20 Listenseiten und 300 Detailseiten je Lauf
- **Suchbereich:** `alle` v1 – Alle Stellenanzeigen laut Sitemap (Modus `full`)
- **Bedingungen:** https://www.greenjobs.de/home/agb.html
- **robots.txt:** https://www.greenjobs.de/robots.txt
- **Prüfvermerk (10.11.2026):** robots.txt erlaubt alles außer /_ads/, /a/ und Sortiervarianten; Sitemap öffentlich. AGB (Stand 6.2.2024) gelten auch für Portalbesucher. § 12: Inhalte dürfen „ausschließlich innerhalb der zur Verfügung gestellten Funktionalitäten“ genutzt bzw. online abgerufen und angezeigt werden. § 13: Verbreitung/öffentliche Wiedergabe nur mit ausdrücklicher Gestattung; keine übermäßige Belastung der Systeme. Robots/Crawler werden nicht genannt. Adapter technisch fertig, läuft erst nach Erlaubnis.

### Bundesagentur für Arbeit – Jobsuche

- **Domain:** `www.arbeitsagentur.de` – Einstieg: https://www.arbeitsagentur.de/jobsuche/
- **Fachliche Abdeckung:** Allgemeiner Stellenmarkt (größter Bestand)
- **Konfigurationsstatus:** Erlaubnis erforderlich (`permission_required`)
- **Grund:** Nutzungsbedingungen Nr. 2a (3) untersagen ausdrücklich den Einsatz von Robots/Webspidern. Kein Adapter.
- **Adapter:** keiner (nur vorgemerkt)
- **Bedingungen:** https://www.arbeitsagentur.de/nutzungsbedingungen
- **robots.txt:** https://www.arbeitsagentur.de/robots.txt
- **Prüfvermerk (10.11.2026):** robots.txt erlaubt zwar alles, die Nutzungsbedingungen (Stand 10.11.2026) gehen aber vor: Nr. 2a (3) „Es ist insbesondere nicht zulässig: Robots, Webspider oder ähnliche Technologien einzusetzen“ sowie unautorisiert Schnittstellen zu nutzen, um Inhalte „zum Zweck der Datensammlung und -auswertung auszulesen“. Impressum: Nutzung zu anderen Zwecken nur mit ausdrücklicher vorheriger Genehmigung; Quellenformat vorgeschrieben. Vorgesehener Weg für Dritte: Kooperationsvereinbarung zur HR-BA-XML-Schnittstelle (Account- und Allianzpartnermanagement der BA). Technisch wäre die Jobsuche lesbar (serverseitig gerendertes HTML, Trefferobergrenze 10.000) – das ändert nichts an der fehlenden Erlaubnis.

### Stepstone

- **Domain:** `www.stepstone.de` – Einstieg: https://www.stepstone.de/
- **Fachliche Abdeckung:** Allgemeiner Stellenmarkt
- **Konfigurationsstatus:** Erlaubnis erforderlich (`permission_required`)
- **Grund:** Nutzungsbedingungen Nr. 4.3.4 untersagen Scraping; Nr. 13.2 (i) die Nutzung zur Entwicklung anderer Dienste. Kein Adapter.
- **Adapter:** keiner (nur vorgemerkt)
- **Bedingungen:** https://www.stepstone.de/e-recruiting/rechtliches/nutzungsbedingungen-bewerber/
- **robots.txt:** https://www.stepstone.de/robots.txt
- **Prüfvermerk (10.11.2026):** Allgemeine Nutzungsbedingungen (Stand 06.11.2025): Nr. 4.3.4 untersagt, „Scraping- oder vergleichbare Techniken zu benutzen, um Inhalte zu erfassen und für einen anderen Zweck zu verwenden“; Nr. 1.2 nur individuelle Arbeitssuche. robots.txt sperrt zudem Ergebnislisten und Parameter-URLs weitgehend.

### meinestadt.de – Stellenmarkt

- **Domain:** `jobs.meinestadt.de` – Einstieg: https://jobs.meinestadt.de/
- **Fachliche Abdeckung:** Regionaler Stellenmarkt
- **Konfigurationsstatus:** Erlaubnis erforderlich (`permission_required`)
- **Grund:** Nutzungsbedingungen Nr. 5.2 untersagen Scraping; Nr. 12 (i) die Nutzung zur Entwicklung anderer Dienste. Kein Adapter.
- **Adapter:** keiner (nur vorgemerkt)
- **Bedingungen:** https://www.meinestadt.de/agb-allgemeine-nutzungsbedingungen
- **robots.txt:** https://jobs.meinestadt.de/robots.txt
- **Prüfvermerk (10.11.2026):** Allgemeine Nutzungsbedingungen (Stand 07.04.2026), Nr. 5.2: nicht gestattet, „Scraping- oder vergleichbare Techniken zu nutzen, um Inhalte zu erfassen und für einen anderen Zweck zu verwenden“. robots.txt sperrt Such-/Paginierungs-URLs.

### Indeed

- **Domain:** `de.indeed.com` – Einstieg: https://de.indeed.com/
- **Fachliche Abdeckung:** Allgemeiner Stellenmarkt (Aggregator)
- **Konfigurationsstatus:** Erlaubnis erforderlich (`permission_required`)
- **Grund:** Nutzungsbedingungen Abschnitt D.21 untersagen automatisierten Zugriff und Datenextraktion ohne schriftliche Erlaubnis. Kein Adapter.
- **Adapter:** keiner (nur vorgemerkt)
- **Bedingungen:** https://de.indeed.com/legal
- **robots.txt:** https://de.indeed.com/robots.txt
- **Prüfvermerk (10.11.2026):** Nutzungsbedingungen (letzte Aktualisierung 29.06.2026), Abschnitt D Nr. 21 „Regeln für die Website“: kein Scraping, keine Datenextraktion oder Vervielfältigung irgendeines Teils der Website; Crawling nur „wie in unserer Datei robots.txt beschrieben“, die u. a. /job/ und /jobs sperrt.

### academics

- **Domain:** `www.academics.de` – Einstieg: https://www.academics.de/
- **Fachliche Abdeckung:** Hochschulen, Wissenschaft und Forschung
- **Konfigurationsstatus:** Erlaubnis erforderlich (`permission_required`)
- **Grund:** robots.txt und Nutzungsbedingungen Nr. 4 (3) untersagen automatisierte Zugriffe ohne ausdrückliche Erlaubnis. Kein Adapter.
- **Adapter:** keiner (nur vorgemerkt)
- **Bedingungen:** https://www.academics.de/info/nutzungsbedingungen
- **robots.txt:** https://www.academics.de/robots.txt
- **Prüfvermerk (10.11.2026):** robots.txt enthält einen ausdrücklichen Nutzungsvorbehalt (§ 44b UrhG) und verweist für Crawl-Erlaubnisse an den Betreiber. Nutzungsbedingungen Nr. 4 (3): „automatisierte Zugriffe (Bots, Scraping) … sind strikt untersagt“.

### Monster

- **Domain:** `www.monster.de` – Einstieg: https://www.monster.de/
- **Fachliche Abdeckung:** Allgemeiner Stellenmarkt
- **Konfigurationsstatus:** deaktiviert (`disabled`)
- **Grund:** Weiterleitung auf monster.com/de mit Bot-Schutz-Challenge (HTTP 403); kein brauchbarer deutscher Stellenbestand verifiziert.
- **Adapter:** keiner (nur vorgemerkt)
- **robots.txt:** https://www.monster.de/robots.txt
- **Prüfvermerk (10.11.2026):** Abruftest 10.11.2026: monster.de leitet auf https://www.monster.com/de/ um und antwortet mit einer JavaScript-/CAPTCHA-Challenge. Keine Umgehung.

### jobvector

- **Domain:** `www.jobvector.de` – Einstieg: https://www.jobvector.de/jobs/
- **Fachliche Abdeckung:** Technische und wissenschaftliche Fachberufe
- **Konfigurationsstatus:** deaktiviert (`disabled`)
- **Grund:** Bot-Schutz-Challenge bereits für robots.txt (HTTP 403, „Just a moment…“). Keine Umgehung; Anfrage beim Betreiber nötig.
- **Adapter:** keiner (nur vorgemerkt)
- **robots.txt:** https://www.jobvector.de/robots.txt
- **Prüfvermerk (10.11.2026):** Abruftest 10.11.2026. Ohne lesbare robots.txt ist keine Freigabe ableitbar.

### Azubiyo

- **Domain:** `www.azubiyo.de` – Einstieg: https://www.azubiyo.de/
- **Fachliche Abdeckung:** Ausbildung und duales Studium (getrennt auszuwerten)
- **Konfigurationsstatus:** deaktiviert (`disabled`)
- **Grund:** Bot-Schutz-Challenge bereits für robots.txt (HTTP 403). Keine Umgehung; Anfrage beim Betreiber nötig.
- **Adapter:** keiner (nur vorgemerkt)
- **robots.txt:** https://www.azubiyo.de/robots.txt
- **Prüfvermerk (10.11.2026):** Abruftest 10.11.2026.

### Absolventa

- **Domain:** `www.absolventa.de` – Einstieg: https://www.absolventa.de/
- **Fachliche Abdeckung:** Berufseinstieg, Traineeprogramme
- **Konfigurationsstatus:** deaktiviert (`disabled`)
- **Grund:** „Human Verification“ (WAF-Challenge, HTTP 405) bereits für robots.txt. Keine Umgehung; Anfrage beim Betreiber nötig.
- **Adapter:** keiner (nur vorgemerkt)
- **robots.txt:** https://www.absolventa.de/robots.txt
- **Prüfvermerk (10.11.2026):** Abruftest 10.11.2026.

### stellenanzeigen.de

- **Domain:** `www.stellenanzeigen.de` – Einstieg: https://www.stellenanzeigen.de/jobs/
- **Fachliche Abdeckung:** Allgemeiner Stellenmarkt
- **Konfigurationsstatus:** vorgemerkt (`candidate`)
- **Grund:** Nicht geprüft: Aus der Entwicklungsumgebung geo-gesperrt (HTTP 403). Prüfung muss aus dem Zielnetz wiederholt werden. Kein Adapter.
- **Adapter:** keiner (nur vorgemerkt)
- **robots.txt:** https://www.stellenanzeigen.de/robots.txt
- **Prüfvermerk (10.11.2026):** Abruftest 10.11.2026: Antwort „Unfortunately, our service is not available in your country.“ – robots.txt und Bedingungen daher ungeprüft.

### yourfirm

- **Domain:** `www.yourfirm.de` – Einstieg: https://www.yourfirm.de/stellenangebote/
- **Fachliche Abdeckung:** Mittelständische Arbeitgeber
- **Konfigurationsstatus:** vorgemerkt (`candidate`)
- **Grund:** Nicht geprüft: Aus der Entwicklungsumgebung geo-gesperrt (HTTP 403). Prüfung muss aus dem Zielnetz wiederholt werden. Kein Adapter.
- **Adapter:** keiner (nur vorgemerkt)
- **robots.txt:** https://www.yourfirm.de/robots.txt
- **Prüfvermerk (10.11.2026):** Abruftest 10.11.2026: Antwort „Unfortunately, our service is not available in your country.“ – robots.txt und Bedingungen daher ungeprüft.

### Jobware

- **Domain:** `www.jobware.de` – Einstieg: https://www.jobware.de/
- **Fachliche Abdeckung:** Branchenübergreifend (Fach- und Führungskräfte)
- **Konfigurationsstatus:** vorgemerkt (`candidate`)
- **Grund:** Offen: keine Besucherbedingungen, Anzeigen-Sitemap für unbekannte Clients gesperrt (HTTP 403). Vor einer Anbindung beim Betreiber anfragen. Kein Adapter.
- **Adapter:** keiner (nur vorgemerkt)
- **Bedingungen:** https://www.jobware.de/pdf/agb-jobware-gmbh.pdf
- **robots.txt:** https://www.jobware.de/robots.txt
- **Prüfvermerk (10.11.2026):** robots.txt erlaubt allgemeine Crawler (außer /apply/, /api/, /account/ …), schließt aber benannte KI-Bots aus. Die AGB (Stand Juli 2025) sind reine Auftraggeberbedingungen; zu Robots/Scraping kein Wort. Die in robots.txt genannte Sitemap der Anzeigen antwortete mit HTTP 403 – ein Sperrsignal, das nicht umgangen wird. Listen- und Detailseiten (JobPosting-JSON-LD) waren abrufbar.

## Arbeitgeber-Karriereseiten

Öffentliche Karriereseiten einzelner Arbeitgeber lassen sich als eigenständige Quellen anlegen (Quellenverwaltung →
„Karriereseite vormerken“). Der generische Adapter `career_page` liest eine öffentliche Sitemap und das
`JobPosting`-JSON-LD der Anzeigenseiten. Er ersetzt nicht die Prüfung der jeweiligen Domain: Jede Karriereseite startet
als *vorgemerkt* und braucht einen eigenen Prüf- und Freigabevermerk (robots.txt, Nutzungsbedingungen).

## Amtliche Statistik- und Geodaten

Lizenz, Quellenvermerk und Abrufweg je Datenprodukt stehen in [betrieb.md](betrieb.md#erstimport-amtlicher-daten) und in der
Oberfläche unter „Methodik und Quellen“. Besonderheit: Der automatische Abruf von `statistik.arbeitsagentur.de` ist
standardmäßig ausgeschaltet (`WF_STATS_BA_AUTO=false`), weil die allgemeinen Nutzungsbedingungen der BA Robots untersagen und der
Host bei der Recherche Zugriffe mit HTTP 429 gedrosselt hat. Die Dateien selbst dürfen laut Impressum der Statistikhefte mit
Quellenangabe gespeichert und genutzt werden; sie werden manuell geladen und über Oberfläche oder CLI importiert.

## Offenlegung zur Entwicklung

Während der Machbarkeitsprüfung am 10.11.2026 wurden – bevor das Ergebnis der Bedingungsprüfung vorlag – etwa ein Dutzend
Seiten der BA-Jobsuche sowie einzelne Seiten von Jobware, INTERAMT, greenjobs und meinestadt.de automatisiert abgerufen
(jeweils wenige Anfragen mit Pausen und identifizierbarem User-Agent). Nach Vorliegen der Bedingungen wurden die Abrufe der
untersagenden Portale eingestellt. Inhalte dieser Abrufe sind nicht Bestandteil des Repositories; die Testfixtures sind
synthetisch.
