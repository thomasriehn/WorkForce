"""Quellenregister (Startbestand) mit belegtem Prüfergebnis je Portal.

Prüfdatum der Einträge: 2026-11-10. Grundlage: robots.txt, veröffentlichte Nutzungsbedingungen/AGB/Impressum
und ein technischer Abruftest. Das ist **keine Rechtsberatung** – es dokumentiert, was die Bedingungen sagen.

Grundsatz: Keine Quelle ist nach der Installation automatisch aktiv. Der Betreiber gibt eine Quelle mit
einem Freigabevermerk frei (``workforce source activate`` bzw. Quellenverwaltung). Quellen im Status
``permission_required`` verlangen zusätzlich einen Verweis auf die vorliegende Erlaubnis.
"""
from __future__ import annotations

from datetime import date
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..models import SearchScope, Source
from .adapters import ADAPTERS

CHECKED = date(2026, 11, 10)

REGISTRY: list[dict[str, Any]] = [
    # ---------------------------------------------------------------------------------------- umsetzbar
    {
        "key": "service_bund_rss", "name": "service.bund.de – Stellenangebote (RSS)", "domain": "www.service.bund.de",
        "entry_url": "https://www.service.bund.de/Content/DE/Service/RSS/rss_node.html",
        "segment": "Öffentlicher Dienst: Bund, Länder, Kommunen (inkl. Importe aus 14 Partnerbörsen, u. a. INTERAMT)",
        "access_method": "official_rss_feed", "adapter_key": "service_bund_rss", "allowed_domains": ["www.service.bund.de"],
        "terms_url": "https://www.service.bund.de/Content/DE/Service/Impressum/impressum_node.html",
        "robots_url": "https://www.service.bund.de/robots.txt",
        "config_status": "candidate",
        "status_reason": "Technisch geprüft, zur Freigabe empfohlen. Wartet auf den Freigabevermerk des Betreibers.",
        "legal_notes": (
            "Das Portal bietet den RSS-Feed „Stellenangebote“ selbst als maschinenlesbaren Kanal an (RSS-Seite: „Neue Angebote "
            "sofort erhalten“). robots.txt: Feed-Pfad /Content/Globals/… nicht gesperrt; gesperrt sind u. a. /Content/DE/Stellen/Suche/ "
            "und /SiteGlobals/; Crawl-delay 30 s (wird eingehalten). Impressum, Urheberrecht: Texte/Textteile dürfen, „soweit diese "
            "urheberrechtlich geschützt sind“, nicht ohne Zustimmung des Bundesverwaltungsamtes vervielfältigt werden; zu automatisierten "
            "Abrufen schweigt das Impressum. Umsetzung: nur Rumpfdaten (Titel, Behörde, PLZ/Ort, Fristen, Link), keine Textauszüge. "
            "Hinweis: Der Feed ist ein Fenster der neuesten 500 Einträge – er meldet neue Anzeigen, keine Vollerhebung."
        ),
        "attribution": "Quelle: service.bund.de (Bundesverwaltungsamt), Stellenangebote der Bundes-, Landes- und Kommunalverwaltung",
        "request_interval_seconds": 30, "max_pages_per_run": 5, "max_details_per_run": 0,
        "scopes": [{"key": "stellen", "name": "RSS-Feed Stellenangebote (neueste Einträge)", "mode": "new_only",
                    "params": {"feed_url": "https://www.service.bund.de/Content/Globals/Functions/RSSFeed/RSSGenerator_Stellen.xml"}}],
    },
    {
        "key": "karriere_bund", "name": "karriere.bund.de", "domain": "karriere.bund.de", "entry_url": "https://karriere.bund.de/",
        "segment": "Bundesverwaltung",
        "access_method": "html_list_jsonld", "adapter_key": "karriere_bund", "allowed_domains": ["karriere.bund.de"],
        "terms_url": "https://karriere.bund.de/impressum", "robots_url": "https://karriere.bund.de/robots.txt",
        "config_status": "candidate",
        "status_reason": "Technisch umgesetzt. Freigabe ist eine Betreiberentscheidung (Textvorbehalt im Impressum, s. Prüfvermerk).",
        "legal_notes": (
            "robots.txt sperrt nur /typo3/, /typo3_src/ und einen Upload-Ordner. Keine Nutzungsbedingungen; das Impressum schweigt zu "
            "automatisierten Abrufen. Impressum Nr. 5: „Texte, Textteile, Grafiken, Tabellen oder Bildmaterialien dürfen ohne vorherige "
            "Zustimmung des Bundesministeriums für Digitales und Staatsmodernisierung nicht vervielfältigt, nicht verbreitet und nicht "
            "ausgestellt werden.“ Ob Titel/Behörde/Ort als „Textteile“ gelten, lässt die Seite offen. Umsetzung daher ohne Textauszüge; "
            "vor Freigabe Zustimmung einholen oder die Auslegung selbst verantworten. Einzelne Anzeigen stammen von INTERAMT (Dubletten)."
        ),
        "request_interval_seconds": 5, "max_pages_per_run": 250, "max_details_per_run": 300,
        "scopes": [{"key": "alle", "name": "Alle Stellenangebote", "mode": "full", "params": {}}],
    },
    {
        "key": "interamt", "name": "INTERAMT", "domain": "karriere.interamt.de", "entry_url": "https://karriere.interamt.de/de",
        "segment": "Öffentlicher Dienst",
        "access_method": "sitemap_jsonld", "adapter_key": "interamt", "allowed_domains": ["karriere.interamt.de"],
        "terms_url": "https://karriere.interamt.de/footer/impressum", "robots_url": "https://karriere.interamt.de/robots.txt",
        "config_status": "permission_required",
        "status_reason": "Speicherung/Übernahme nur nach vorheriger schriftlicher Zustimmung der DVZ M-V GmbH (Impressum, Rechtshinweis).",
        "legal_notes": (
            "robots.txt sperrt nur /meininteramt und /jobs/merkliste; Sitemap öffentlich. Nutzungsbedingungen (Stand 27.01.2021) nennen "
            "keine Robots/Crawler. Impressum (Stand 04.11.2025), Rechtshinweis: Inhalte seien „als wesentliche Teile von Datenbanken“ "
            "geschützt; „Aufnahme in fremde Internetangebote und Online-Dienste … sowie Vervielfältigungen auf Datenträger aller Art …, "
            "auch auszugsweise, nur nach vorheriger schriftlicher Zustimmung“. Adapter ist technisch fertig (Sitemap + JSON-LD), läuft "
            "aber erst nach dokumentierter Zustimmung."
        ),
        "request_interval_seconds": 4, "max_pages_per_run": 60, "max_details_per_run": 600,
        "scopes": [{"key": "alle", "name": "Alle Stellen laut Sitemap", "mode": "full", "params": {}}],
    },
    {
        "key": "greenjobs", "name": "greenjobs.de", "domain": "www.greenjobs.de", "entry_url": "https://www.greenjobs.de/",
        "segment": "Umwelt und Nachhaltigkeit",
        "access_method": "sitemap_jsonld", "adapter_key": "greenjobs", "allowed_domains": ["www.greenjobs.de"],
        "terms_url": "https://www.greenjobs.de/home/agb.html", "robots_url": "https://www.greenjobs.de/robots.txt",
        "config_status": "permission_required",
        "status_reason": "AGB § 12 beschränkt die Nutzung auf Abruf und Anzeige innerhalb der Portalfunktionen; Erlaubnis von greenjobs einholen.",
        "legal_notes": (
            "robots.txt erlaubt alles außer /_ads/, /a/ und Sortiervarianten; Sitemap öffentlich. AGB (Stand 6.2.2024) gelten auch für "
            "Portalbesucher. § 12: Inhalte dürfen „ausschließlich innerhalb der zur Verfügung gestellten Funktionalitäten“ genutzt bzw. "
            "online abgerufen und angezeigt werden. § 13: Verbreitung/öffentliche Wiedergabe nur mit ausdrücklicher Gestattung; keine "
            "übermäßige Belastung der Systeme. Robots/Crawler werden nicht genannt. Adapter technisch fertig, läuft erst nach Erlaubnis."
        ),
        "request_interval_seconds": 5, "max_pages_per_run": 20, "max_details_per_run": 300,
        "scopes": [{"key": "alle", "name": "Alle Stellenanzeigen laut Sitemap", "mode": "full", "params": {}}],
    },
    # ------------------------------------------------------------------------- ausdrücklich nicht freigegeben
    {
        "key": "ba_jobsuche", "name": "Bundesagentur für Arbeit – Jobsuche", "domain": "www.arbeitsagentur.de",
        "entry_url": "https://www.arbeitsagentur.de/jobsuche/", "segment": "Allgemeiner Stellenmarkt (größter Bestand)",
        "adapter_key": "ba_jobsuche", "access_method": "html_list_jsonld", "allowed_domains": ["www.arbeitsagentur.de"],
        "terms_url": "https://www.arbeitsagentur.de/nutzungsbedingungen", "robots_url": "https://www.arbeitsagentur.de/robots.txt",
        "config_status": "permission_required",
        "status_reason": "HTML-/JSON-LD-Adapter im begrenzten Live-Test geprüft (11.11.2026). Nutzungsbedingungen Nr. 2a (3): Freigabe mit Erlaubnisnachweis erforderlich.",
        "request_interval_seconds": 5, "max_pages_per_run": 40, "max_details_per_run": 500,
        "scopes": [{"key": "stellen", "name": "BA-Stellenangebote (Suchbereich bei Trefferlimit eingrenzen)",
                    "mode": "full", "params": {"list_url": "https://www.arbeitsagentur.de/jobsuche/suche?angebotsart=1"}}],
        "legal_notes": (
            "robots.txt erlaubt zwar alles, die Nutzungsbedingungen (Stand 10.11.2026) gehen aber vor: Nr. 2a (3) „Es ist insbesondere "
            "nicht zulässig: Robots, Webspider oder ähnliche Technologien einzusetzen“ sowie unautorisiert Schnittstellen zu nutzen, um "
            "Inhalte „zum Zweck der Datensammlung und -auswertung auszulesen“. Impressum: Nutzung zu anderen Zwecken nur mit ausdrücklicher "
            "vorheriger Genehmigung; Quellenformat vorgeschrieben. Vorgesehener Weg für Dritte: Kooperationsvereinbarung zur "
            "HR-BA-XML-Schnittstelle (Account- und Allianzpartnermanagement der BA). Technisch wäre die Jobsuche lesbar (serverseitig "
            "gerendertes HTML, Trefferobergrenze 10.000) – das ändert nichts an der fehlenden Erlaubnis."
        ),
    },
    {
        "key": "stepstone", "name": "Stepstone", "domain": "www.stepstone.de", "entry_url": "https://www.stepstone.de/",
        "segment": "Allgemeiner Stellenmarkt",
        "terms_url": "https://www.stepstone.de/e-recruiting/rechtliches/nutzungsbedingungen-bewerber/", "robots_url": "https://www.stepstone.de/robots.txt",
        "config_status": "permission_required",
        "status_reason": "Nutzungsbedingungen Nr. 4.3.4 untersagen Scraping; Nr. 13.2 (i) die Nutzung zur Entwicklung anderer Dienste. Kein Adapter.",
        "legal_notes": (
            "Allgemeine Nutzungsbedingungen (Stand 06.11.2025): Nr. 4.3.4 untersagt, „Scraping- oder vergleichbare Techniken zu benutzen, "
            "um Inhalte zu erfassen und für einen anderen Zweck zu verwenden“; Nr. 1.2 nur individuelle Arbeitssuche. robots.txt sperrt "
            "zudem Ergebnislisten und Parameter-URLs weitgehend."
        ),
    },
    {
        "key": "meinestadt", "name": "meinestadt.de – Stellenmarkt", "domain": "jobs.meinestadt.de", "entry_url": "https://jobs.meinestadt.de/",
        "segment": "Regionaler Stellenmarkt",
        "terms_url": "https://www.meinestadt.de/agb-allgemeine-nutzungsbedingungen", "robots_url": "https://jobs.meinestadt.de/robots.txt",
        "config_status": "permission_required",
        "status_reason": "Nutzungsbedingungen Nr. 5.2 untersagen Scraping; Nr. 12 (i) die Nutzung zur Entwicklung anderer Dienste. Kein Adapter.",
        "legal_notes": (
            "Allgemeine Nutzungsbedingungen (Stand 07.04.2026), Nr. 5.2: nicht gestattet, „Scraping- oder vergleichbare Techniken zu "
            "nutzen, um Inhalte zu erfassen und für einen anderen Zweck zu verwenden“. robots.txt sperrt Such-/Paginierungs-URLs."
        ),
    },
    {
        "key": "indeed", "name": "Indeed", "domain": "de.indeed.com", "entry_url": "https://de.indeed.com/", "segment": "Allgemeiner Stellenmarkt (Aggregator)",
        "terms_url": "https://de.indeed.com/legal", "robots_url": "https://de.indeed.com/robots.txt",
        "config_status": "permission_required",
        "status_reason": "Nutzungsbedingungen Abschnitt D.21 untersagen automatisierten Zugriff und Datenextraktion ohne schriftliche Erlaubnis. Kein Adapter.",
        "legal_notes": (
            "Nutzungsbedingungen (letzte Aktualisierung 29.06.2026), Abschnitt D Nr. 21 „Regeln für die Website“: kein Scraping, keine "
            "Datenextraktion oder Vervielfältigung irgendeines Teils der Website; Crawling nur „wie in unserer Datei robots.txt beschrieben“, "
            "die u. a. /job/ und /jobs sperrt."
        ),
    },
    {
        "key": "academics", "name": "academics", "domain": "www.academics.de", "entry_url": "https://www.academics.de/",
        "segment": "Hochschulen, Wissenschaft und Forschung",
        "terms_url": "https://www.academics.de/info/nutzungsbedingungen", "robots_url": "https://www.academics.de/robots.txt",
        "config_status": "permission_required",
        "status_reason": "robots.txt und Nutzungsbedingungen Nr. 4 (3) untersagen automatisierte Zugriffe ohne ausdrückliche Erlaubnis. Kein Adapter.",
        "legal_notes": (
            "robots.txt enthält einen ausdrücklichen Nutzungsvorbehalt (§ 44b UrhG) und verweist für Crawl-Erlaubnisse an den Betreiber. "
            "Nutzungsbedingungen Nr. 4 (3): „automatisierte Zugriffe (Bots, Scraping) … sind strikt untersagt“."
        ),
    },
    # ------------------------------------------------------------------------------ gesperrt / nicht prüfbar
    {
        "key": "monster", "name": "Monster", "domain": "www.monster.de", "entry_url": "https://www.monster.de/", "segment": "Allgemeiner Stellenmarkt",
        "robots_url": "https://www.monster.de/robots.txt", "config_status": "disabled",
        "status_reason": "Weiterleitung auf monster.com/de mit Bot-Schutz-Challenge (HTTP 403); kein brauchbarer deutscher Stellenbestand verifiziert.",
        "legal_notes": "Abruftest 10.11.2026: monster.de leitet auf https://www.monster.com/de/ um und antwortet mit einer JavaScript-/CAPTCHA-Challenge. Keine Umgehung.",
    },
    {
        "key": "jobvector", "name": "jobvector", "domain": "www.jobvector.de", "entry_url": "https://www.jobvector.de/jobs/",
        "segment": "Technische und wissenschaftliche Fachberufe", "robots_url": "https://www.jobvector.de/robots.txt", "config_status": "disabled",
        "status_reason": "Bot-Schutz-Challenge bereits für robots.txt (HTTP 403, „Just a moment…“). Keine Umgehung; Anfrage beim Betreiber nötig.",
        "legal_notes": "Abruftest 10.11.2026. Ohne lesbare robots.txt ist keine Freigabe ableitbar.",
    },
    {
        "key": "azubiyo", "name": "Azubiyo", "domain": "www.azubiyo.de", "entry_url": "https://www.azubiyo.de/",
        "segment": "Ausbildung und duales Studium (getrennt auszuwerten)", "robots_url": "https://www.azubiyo.de/robots.txt", "config_status": "disabled",
        "status_reason": "Bot-Schutz-Challenge bereits für robots.txt (HTTP 403). Keine Umgehung; Anfrage beim Betreiber nötig.",
        "legal_notes": "Abruftest 10.11.2026.",
    },
    {
        "key": "absolventa", "name": "Absolventa", "domain": "www.absolventa.de", "entry_url": "https://www.absolventa.de/",
        "segment": "Berufseinstieg, Traineeprogramme", "robots_url": "https://www.absolventa.de/robots.txt", "config_status": "disabled",
        "status_reason": "„Human Verification“ (WAF-Challenge, HTTP 405) bereits für robots.txt. Keine Umgehung; Anfrage beim Betreiber nötig.",
        "legal_notes": "Abruftest 10.11.2026.",
    },
    {
        "key": "stellenanzeigen_de", "name": "stellenanzeigen.de", "domain": "www.stellenanzeigen.de", "entry_url": "https://www.stellenanzeigen.de/jobs/",
        "segment": "Allgemeiner Stellenmarkt", "robots_url": "https://www.stellenanzeigen.de/robots.txt", "config_status": "candidate",
        "status_reason": "Nicht geprüft: Aus der Entwicklungsumgebung geo-gesperrt (HTTP 403). Prüfung muss aus dem Zielnetz wiederholt werden. Kein Adapter.",
        "legal_notes": "Abruftest 10.11.2026: Antwort „Unfortunately, our service is not available in your country.“ – robots.txt und Bedingungen daher ungeprüft.",
    },
    {
        "key": "yourfirm", "name": "yourfirm", "domain": "www.yourfirm.de", "entry_url": "https://www.yourfirm.de/stellenangebote/",
        "segment": "Mittelständische Arbeitgeber", "robots_url": "https://www.yourfirm.de/robots.txt", "config_status": "candidate",
        "status_reason": "Nicht geprüft: Aus der Entwicklungsumgebung geo-gesperrt (HTTP 403). Prüfung muss aus dem Zielnetz wiederholt werden. Kein Adapter.",
        "legal_notes": "Abruftest 10.11.2026: Antwort „Unfortunately, our service is not available in your country.“ – robots.txt und Bedingungen daher ungeprüft.",
    },
    {
        "key": "jobware", "name": "Jobware", "domain": "www.jobware.de", "entry_url": "https://www.jobware.de/", "segment": "Branchenübergreifend (Fach- und Führungskräfte)",
        "terms_url": "https://www.jobware.de/pdf/agb-jobware-gmbh.pdf", "robots_url": "https://www.jobware.de/robots.txt", "config_status": "candidate",
        "status_reason": "Offen: keine Besucherbedingungen, Anzeigen-Sitemap für unbekannte Clients gesperrt (HTTP 403). Vor einer Anbindung beim Betreiber anfragen. Kein Adapter.",
        "legal_notes": (
            "robots.txt erlaubt allgemeine Crawler (außer /apply/, /api/, /account/ …), schließt aber benannte KI-Bots aus. Die AGB "
            "(Stand Juli 2025) sind reine Auftraggeberbedingungen; zu Robots/Scraping kein Wort. Die in robots.txt genannte Sitemap der "
            "Anzeigen antwortete mit HTTP 403 – ein Sperrsignal, das nicht umgangen wird. Listen- und Detailseiten (JobPosting-JSON-LD) "
            "waren abrufbar."
        ),
    },
]


def seed_registry(db: Session) -> dict[str, int]:
    """Legt Registereinträge an; ergänzt den BA-Adapter ohne bestehende Freigaben/Suchbereiche zu ändern."""
    created = {"sources": 0, "scopes": 0}
    for entry in REGISTRY:
        e = dict(entry)
        scopes = e.pop("scopes", [])
        src = db.execute(select(Source).where(Source.key == e["key"])).scalar_one_or_none()
        if src is None:
            adapter_key = e.get("adapter_key")
            src = Source(
                **{k: v for k, v in e.items() if k != "allowed_domains"},
                allowed_domains=e.get("allowed_domains") or [e["domain"]],
                adapter_version=ADAPTERS[adapter_key].version if adapter_key else None,
                legal_checked_on=CHECKED,
            )
            db.add(src)
            db.flush()
            created["sources"] += 1
            for sc in scopes:
                db.add(SearchScope(source_id=src.id, key=sc["key"], version=1, name=sc["name"], params=sc.get("params") or {},
                                   mode=sc.get("mode", "full"), is_active=True))
                created["scopes"] += 1
        elif src.key == "ba_jobsuche" and src.adapter_key is None:
            # Upgrade bisheriger Installationen: die BA war bereits als Kandidat ohne Adapter vorhanden.
            src.adapter_key = e["adapter_key"]
            src.adapter_version = ADAPTERS[src.adapter_key].version
            src.access_method = e["access_method"]
            old_reason = "Nutzungsbedingungen Nr. 2a (3) untersagen ausdrücklich den Einsatz von Robots/Webspidern. Kein Adapter."
            if src.status_reason == old_reason:
                src.status_reason = e["status_reason"]
            # Auch pensionierte Versionen zählen: keine bewusst deaktivierten Suchbereiche reaktivieren.
            has_scopes = db.execute(select(SearchScope.id).where(SearchScope.source_id == src.id).limit(1)).first()
            if not has_scopes:
                for sc in scopes:
                    db.add(SearchScope(source_id=src.id, key=sc["key"], version=1, name=sc["name"],
                                       params=sc["params"], mode=sc["mode"], is_active=True))
                    created["scopes"] += 1
        elif src.adapter_key:
            src.adapter_version = ADAPTERS[src.adapter_key].version if src.adapter_key in ADAPTERS else src.adapter_version
    db.flush()
    return created
