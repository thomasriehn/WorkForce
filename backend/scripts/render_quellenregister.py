"""Erzeugt docs/quellenregister.md aus dem Quellenregister im Code (eine Quelle der Wahrheit).

    uv run python scripts/render_quellenregister.py > ../docs/quellenregister.md
"""
from __future__ import annotations

from workforce.sources.adapters import ADAPTERS
from workforce.sources.registry import CHECKED, REGISTRY

LABEL = {"candidate": "vorgemerkt", "active": "aktiv", "disabled": "deaktiviert", "permission_required": "Erlaubnis erforderlich"}


def main() -> None:
    out: list[str] = []
    w = out.append
    w("# Quellenregister")
    w("")
    w(f"Prüfdatum aller Einträge: **{CHECKED:%d.%m.%Y}**. Diese Datei wird aus `backend/workforce/sources/registry.py` erzeugt")
    w("(`uv run python scripts/render_quellenregister.py`). Der laufende Stand einer Installation steht in der Quellenverwaltung.")
    w("")
    w("> Das Register dokumentiert, was robots.txt und die veröffentlichten Bedingungen der Portale am Prüfdatum sagen. Es ist")
    w("> keine Rechtsberatung. Ob Nutzungsbedingungen einen nicht registrierten Besucher binden und ob Titel, Arbeitgeber und Ort")
    w("> überhaupt schutzfähig sind, sind Rechtsfragen außerhalb dieser Prüfung. Frei sichtbare Inhalte allein belegen keine")
    w("> Erlaubnis zur automatisierten Weiterverwendung.")
    w("")
    w("## Ergebnis in Kürze")
    w("")
    w("- **Zielabdeckung nicht erreicht:** Drei *freigegebene* Quellen aus unterschiedlichen Marktsegmenten gibt es unter den Vorgaben")
    w("  (keine Portal-APIs, Bedingungen beachten, keine Umgehung von Sperren) derzeit nicht.")
    w("- **Konkrete Grenze:** Die großen allgemeinen Portale (BA-Jobsuche, Stepstone, Indeed, meinestadt.de) und academics untersagen")
    w("  automatisierte Abrufe ausdrücklich. Monster, jobvector, Azubiyo und Absolventa antworten mit Bot-Schutz-Challenges.")
    w("  stellenanzeigen.de und yourfirm waren aus der Entwicklungsumgebung geo-gesperrt und sind ungeprüft.")
    w("- **Technisch umgesetzt** sind fünf Quellenadapter plus ein generischer Adapter für Arbeitgeber-Karriereseiten. Live geprüft")
    w("  wurde der offizielle RSS-Feed von service.bund.de. Der BA-Jobsuche-Adapter ergänzt HTML-Suche und JSON-LD-Details;")
    w("  seine Live-Prüfung steht aus (Cloud-Netzwerkzugriff am 11.11.2026 durch den Proxy blockiert).")
    w("- **Keine Quelle ist nach der Installation automatisch aktiv.** Die Freigabe erfolgt durch den Betreiber mit Freigabevermerk;")
    w("  Quellen mit Erlaubnisvorbehalt verlangen zusätzlich den Nachweis der Erlaubnis.")
    w("")
    w("## Übersicht")
    w("")
    w("| Portal | Segment | Status | Adapter | Zugriffsart | Kurzgrund |")
    w("|---|---|---|---|---|---|")
    for e in REGISTRY:
        adapter = f"`{e['adapter_key']}` ({ADAPTERS[e['adapter_key']].version})" if e.get("adapter_key") else "keiner"
        w(f"| [{e['name']}]({e['entry_url']}) | {e.get('segment', '')} | {LABEL[e['config_status']]} | {adapter} | {e.get('access_method') or '–'} | {e['status_reason']} |")
    w("")
    w("Statuswerte: *vorgemerkt* (`candidate`), *aktiv* (`active`), *deaktiviert* (`disabled`), *Erlaubnis erforderlich* (`permission_required`).")
    w("Der technische Gesundheitszustand (letzter Lauf, Datenstand, Fehler) wird getrennt davon in der Quellenverwaltung geführt.")
    w("")
    w("## Einzelnachweise")
    for e in REGISTRY:
        w("")
        w(f"### {e['name']}")
        w("")
        w(f"- **Domain:** `{e['domain']}` – Einstieg: {e['entry_url']}")
        w(f"- **Fachliche Abdeckung:** {e.get('segment', '–')}")
        w(f"- **Konfigurationsstatus:** {LABEL[e['config_status']]} (`{e['config_status']}`)")
        w(f"- **Grund:** {e['status_reason']}")
        if e.get("adapter_key"):
            a = ADAPTERS[e["adapter_key"]]
            mode = "vollständige Aufzählung des Suchbereichs" if a.discovery_mode == "full" else "meldet nur neue Anzeigen"
            w(f"- **Adapter:** `{a.key}`, Version `{a.version}`, Zugriffsart `{a.access_method}`, Entdeckung: {mode}, Detailseiten: {a.detail_mode}, "
              f"Textauszüge: {'ja' if a.store_excerpts else 'nein'}")
            w(f"- **Abrufbudget (Standard):** Abstand {e.get('request_interval_seconds', 3)} s, höchstens {e.get('max_pages_per_run', 400)} Listenseiten und "
              f"{e.get('max_details_per_run', 500)} Detailseiten je Lauf")
            for sc in e.get("scopes", []):
                w(f"- **Suchbereich:** `{sc['key']}` v1 – {sc['name']} (Modus `{sc.get('mode', 'full')}`)")
        else:
            w("- **Adapter:** keiner (nur vorgemerkt)")
        if e.get("terms_url"):
            w(f"- **Bedingungen:** {e['terms_url']}")
        w(f"- **robots.txt:** {e.get('robots_url', '–')}")
        w(f"- **Prüfvermerk ({CHECKED:%d.%m.%Y}):** {e.get('legal_notes', '–')}")
        if e.get("attribution"):
            w(f"- **Quellenangabe:** {e['attribution']}")
    w("")
    w("## Arbeitgeber-Karriereseiten")
    w("")
    w("Öffentliche Karriereseiten einzelner Arbeitgeber lassen sich als eigenständige Quellen anlegen (Quellenverwaltung →")
    w("„Karriereseite vormerken“). Der generische Adapter `career_page` liest eine öffentliche Sitemap und das")
    w("`JobPosting`-JSON-LD der Anzeigenseiten. Er ersetzt nicht die Prüfung der jeweiligen Domain: Jede Karriereseite startet")
    w("als *vorgemerkt* und braucht einen eigenen Prüf- und Freigabevermerk (robots.txt, Nutzungsbedingungen).")
    w("")
    w("## Amtliche Statistik- und Geodaten")
    w("")
    w("Lizenz, Quellenvermerk und Abrufweg je Datenprodukt stehen in [betrieb.md](betrieb.md#erstimport-amtlicher-daten) und in der")
    w("Oberfläche unter „Methodik und Quellen“. Besonderheit: Der automatische Abruf von `statistik.arbeitsagentur.de` ist")
    w("standardmäßig aktiv (`WF_STATS_BA_AUTO=true`); `WF_CRAWLER_CONTACT` bleibt erforderlich. Mit `false` abschaltbar.")
    w("Die allgemeinen Nutzungsbedingungen und die Nutzungshinweise der Statistik gelten weiterhin. Der Host hat bei der Recherche")
    w("mit HTTP 429 gedrosselt; Abrufabstände und Sperrpausen bleiben wirksam. Die Dateien dürfen laut Impressum mit Quellenangabe")
    w("gespeichert und genutzt werden; alternativ ist der manuelle Import über Oberfläche oder CLI möglich.")
    w("")
    w("## Offenlegung zur Entwicklung")
    w("")
    w("Während der Machbarkeitsprüfung am 10.11.2026 wurden – bevor das Ergebnis der Bedingungsprüfung vorlag – etwa ein Dutzend")
    w("Seiten der BA-Jobsuche sowie einzelne Seiten von Jobware, INTERAMT, greenjobs und meinestadt.de automatisiert abgerufen")
    w("(jeweils wenige Anfragen mit Pausen und identifizierbarem User-Agent). Nach Vorliegen der Bedingungen wurden die Abrufe der")
    w("untersagenden Portale eingestellt. Inhalte dieser Abrufe sind nicht Bestandteil des Repositories; die Testfixtures sind")
    w("synthetisch.")
    print("\n".join(out))


if __name__ == "__main__":
    main()
