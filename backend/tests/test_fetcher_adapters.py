"""Fetcher-Höflichkeit/Schutz und Quellenadapter – ausschließlich synthetische Fixtures, kein Netzwerk."""
from __future__ import annotations

from datetime import date, timedelta

import httpx
import pytest
from sqlalchemy import select

from workforce.config import get_settings
from workforce.crawl.fetcher import BlockedError, Fetcher, RobotsDisallowed, TargetForbidden, TransientError, parse_retry_after
from workforce.crawl.netguard import ForbiddenTarget, check_url, ip_is_public
from workforce.crawl.robots import RobotsPolicy
from workforce.models import PostingLocation, PostingVersion, ScanError, Source, SourcePosting
from workforce.sources.adapters import InteramtAdapter, KarriereBundAdapter, ServiceBundRssAdapter, split_places
from workforce.sources.base import ParseError
from workforce.sources.jsonld import parse_date, parse_job_page
from workforce.sources.registry import seed_registry

from .helpers import ROBOTS_OK, make_regions, run_scan

D0 = date(2026, 11, 2)


def fetcher(handler, domains=("portal.example",), **kw):
    sleeps: list[float] = []
    f = Fetcher(domains, interval_seconds=0, settings=get_settings(), transport=httpx.MockTransport(handler), sleep=sleeps.append, **kw)
    return f, sleeps


# --- robots.txt ---------------------------------------------------------------------------------------
def test_robots_wildcards_longest_match_and_crawl_delay():
    pol = RobotsPolicy("User-agent: *\nDisallow: /suche*?*page=\nDisallow: /privat/\nAllow: /privat/offen$\nDisallow: /*.pdf$\nCrawl-delay: 30\n\n"
                       "User-agent: BoeserBot\nDisallow: /\n")
    assert pol.allowed("/jobs/1", "WorkForceBot") and not pol.allowed("/suche/x?a=1&page=2", "WorkForceBot")
    assert not pol.allowed("/privat/x", "WorkForceBot") and pol.allowed("/privat/offen", "WorkForceBot")
    assert not pol.allowed("/a/b.pdf", "WorkForceBot") and pol.allowed("/a/b.pdf?x=1", "WorkForceBot")
    assert not pol.allowed("/jobs/1", "BoeserBot/2.0") and pol.crawl_delay("WorkForceBot") == 30
    # nicht erreichbare robots.txt (5xx/Timeout) ⇒ vollständig gesperrt; 404 ⇒ keine Einschränkung
    assert not RobotsPolicy(None, 503).allowed("/x", "WorkForceBot") and not RobotsPolicy(None, None).allowed("/x", "WorkForceBot")
    assert RobotsPolicy(None, 404).allowed("/x", "WorkForceBot")


def test_netguard_blocks_internal_targets():
    for bad in ("http://127.0.0.1/x", "https://169.254.169.254/latest/meta-data", "https://[::1]/", "ftp://portal.example/x",
                "https://user:pw@portal.example/", "https://evil.example/x", "https://portal.example:8443/x", "https://portal.example.evil.org/"):
        with pytest.raises(ForbiddenTarget):
            check_url(bad, ["portal.example"], resolve=False)
    assert check_url("http://Sub.Portal.Example/a?b=1#frag", ["portal.example"], resolve=False) == "https://sub.portal.example/a?b=1"
    assert not any(ip_is_public(ip) for ip in ("10.0.0.5", "192.168.1.1", "172.16.0.1", "127.0.0.1", "169.254.169.254", "100.64.0.1", "::1", "fd00::1", "0.0.0.0"))
    assert ip_is_public("93.184.216.34")


def test_fetcher_respects_robots_blocks_and_backoff():
    calls = {"n": 0}

    def handler(req: httpx.Request) -> httpx.Response:
        p = req.url.path
        if p == "/robots.txt":
            return httpx.Response(200, text="User-agent: *\nDisallow: /intern/\n")
        if p == "/intern/x":
            raise AssertionError("gesperrter Pfad darf nicht abgerufen werden")
        if p == "/verboten":
            return httpx.Response(403)
        if p == "/captcha":
            return httpx.Response(200, text="<html><title>Just a moment...</title></html>")
        if p == "/drossel":
            calls["n"] += 1
            return httpx.Response(429, headers={"Retry-After": "7"}) if calls["n"] < 3 else httpx.Response(200, text="ok")
        if p == "/lange-sperre":
            return httpx.Response(503, headers={"Retry-After": "86400"})
        if p == "/timeout":
            raise httpx.ReadTimeout("timeout")
        if p == "/weiter-intern":
            return httpx.Response(302, headers={"Location": "http://169.254.169.254/latest/meta-data/"})
        if p == "/weiter-fremd":
            return httpx.Response(301, headers={"Location": "https://anderswo.example/x"})
        if p == "/weiter-ok":
            return httpx.Response(302, headers={"Location": "/ziel"})
        if p == "/ziel":
            assert "WorkForceBot" in req.headers["user-agent"] and "example.invalid" in req.headers["user-agent"]  # identifizierbar
            return httpx.Response(200, text="ziel")
        if p == "/weg":
            return httpx.Response(410)
        return httpx.Response(404)

    f, sleeps = fetcher(handler)
    with pytest.raises(RobotsDisallowed):
        f.get("https://portal.example/intern/x")
    with pytest.raises(BlockedError):
        f.get("https://portal.example/verboten")
    with pytest.raises(BlockedError):
        f.get("https://portal.example/captcha")
    assert f.get("https://portal.example/drossel").text == "ok" and [s for s in sleeps if s >= 7][:2] and len([s for s in sleeps if s >= 7]) == 2  # Retry-After beachtet
    with pytest.raises(BlockedError):  # sehr langes Retry-After ⇒ Lauf endet als blockiert statt zu warten/zu hämmern
        f.get("https://portal.example/lange-sperre")
    with pytest.raises(TransientError):
        f.get("https://portal.example/timeout")
    for path in ("/weiter-intern", "/weiter-fremd"):  # Weiterleitungen werden einzeln geprüft
        with pytest.raises(TargetForbidden):
            f.get("https://portal.example" + path)
    assert f.get("https://portal.example/weiter-ok").text == "ziel"
    assert f.get("https://portal.example/weg").gone  # 410 ist ein Ergebnis, keine Sperre
    with pytest.raises(TargetForbidden):
        f.get("https://nicht-erlaubt.example/")
    assert parse_retry_after("120") == 120 and parse_retry_after("unsinn") is None


# --- Parser ---------------------------------------------------------------------------------------------
JOB_HTML = """<html><head><script type="application/ld+json">{"@context":"https://schema.org","@graph":[{"@type":"WebSite","name":"x"},
{"@type":"JobPosting","title":"Sachbearbeitung Haushalt (m/w/d)","description":"<p>Ihr Profil</p><ul><li>Abgeschlossene Berufsausbildung erforderlich</li><li>Kenntnisse im Haushaltsrecht von Vorteil</li></ul>",
"datePosted":"Tue Nov 03 16:46:16 CET 2026","validThrough":"2026-12-01T00:00:00+01:00","employmentType":["https://schema.org/FullTime","Befristet"],
"hiringOrganization":{"@type":"Organization","name":"Musterbehörde (synthetisch)","email":"personal@example.invalid","telephone":"+49 000 000","sameAs":"https://behoerde.example/karriere/stelle-4711?utm_source=portal"},
"identifier":{"@type":"PropertyValue","name":"Kennziffer","value":"MB-2026-4711"},
"jobLocation":[{"@type":"Place","address":{"@type":"PostalAddress","addressLocality":"Musterstadt","postalCode":"91010","addressCountry":"Deutschland"}},
{"@type":"Place","address":{"@type":"PostalAddress","addressLocality":"Beispielhausen","addressCountry":"DE"}}],
"jobLocationType":"TELECOMMUTE","baseSalary":{"@type":"QuantitativeValue","name":"Besoldungsgruppe/Tarif TVöD E 9b"}}]}</script></head><body>…</body></html>"""


def test_jsonld_parser_core_fields_and_no_contact_data():
    p = parse_job_page(JOB_HTML, source_key="4711", url="https://portal.example/jobs/x-4711")
    assert p.title == "Sachbearbeitung Haushalt (m/w/d)" and p.employer_name == "Musterbehörde (synthetisch)" and p.reference == "MB-2026-4711"
    assert p.date_posted == date(2026, 11, 3) and p.valid_through == date(2026, 12, 1)
    assert p.working_time == ["vollzeit"] and p.contract_term == "befristet" and p.remote_type == "hybrid"
    assert [(loc.locality, loc.postal_code, loc.country) for loc in p.locations] == [("Musterstadt", "91010", "DE"), ("Beispielhausen", None, "DE")]
    assert p.employer_url == "https://behoerde.example/karriere/stelle-4711" and p.salary_text.endswith("TVöD E 9b") and p.salary_min is None
    blob = repr(p)
    assert "personal@example.invalid" not in blob and "+49 000 000" not in blob  # Ansprechpartner-/Kontaktdaten werden nicht erfasst
    with pytest.raises(ParseError):
        parse_job_page("<html><body>kein Markup</body></html>", source_key="x", url="https://portal.example/x")
    assert parse_date("10.11.2026 23:59") == date(2026, 11, 10) and parse_date("Tue, 10 Nov 2026 14:00:00 +0100") == date(2026, 11, 10) and parse_date("irgendwann") is None
    assert [(x.postal_code, x.locality) for x in split_places("01129 Dresden; 04109 Leipzig")] == [("01129", "Dresden"), ("04109", "Leipzig")]


def feed(items: list[tuple[str, str, str, str, str]]) -> bytes:
    body = "".join(
        f"<item><title>{t}</title><link>https://www.service.bund.de/IMPORTE/Stellenangebote/editor/Test/2026/11/{i}.html#track=feed-jobs</link>"
        f"<description><![CDATA[ Arbeitgeber: <strong>{emp}</strong><br /> Ort: <strong>{ort}</strong> <br /><br />Bewerbungsfrist: <strong>30.11.2026 23:59</strong> <br />"
        f"Veröffentlichungsende: <strong>30.11.2026 23:59</strong> ]]></description><pubDate>{pub}</pubDate>"
        f"<guid>https://www.service.bund.de/IMPORTE/Stellenangebote/editor/Test/2026/11/{i}.html</guid></item>" for i, t, emp, ort, pub in items)
    return f'<?xml version="1.0" encoding="UTF-8"?><rss version="2.0"><channel><title>synthetischer Testfeed</title>{body}</channel></rss>'.encode()


def test_rss_adapter_run_end_to_end_with_coverage_signal(db):
    """Feed-Adapter: reale Struktur, synthetische Inhalte. Fenster ohne Überlappung ⇒ partieller Lauf."""
    make_regions(db)
    seed_registry(db)
    src = db.execute(select(Source).where(Source.key == "service_bund_rss")).scalar_one()
    src.config_status = "active"
    scope = src.scopes[0]
    db.commit()
    state = {"feed": feed([("7001", "Sachbearbeiter (m/w/d) &amp; Vertretung", "Test&#228;mter Musterstadt", "91010 Musterstadt", "Mon, 2 Nov 2026 10:00:00 +0100"),
                           ("7002", "Ingenieur (m/w/d)", "Amt Beispiel", "Beispielhausen", "Mon, 2 Nov 2026 09:00:00 +0100")])}

    def handler(req: httpx.Request) -> httpx.Response:
        if req.url.path == "/robots.txt":
            return httpx.Response(200, text="User-agent: *\nDisallow: /Content/DE/Stellen/Suche/\nCrawl-delay: 30\n")
        if req.url.path.endswith("RSSGenerator_Stellen.xml"):
            return httpx.Response(200, content=state["feed"], headers={"content-type": "text/xml;charset=utf-8"})
        return httpx.Response(404)

    r1 = run_scan(db, scope, D0, handler=handler)
    assert r1.status == "complete" and r1.ids_found == 2 and r1.mode == "new_only" and r1.detail_complete
    v = db.execute(select(PostingVersion).join(SourcePosting, SourcePosting.current_version_id == PostingVersion.id).where(SourcePosting.source_key == "7001")).scalar_one()
    assert v.title == "Sachbearbeiter (m/w/d) & Vertretung" and v.employer_name == "Testämter Musterstadt" and v.kreis_keys == ["91001"]
    assert v.apply_until == date(2026, 11, 30) and v.valid_through == date(2026, 11, 30) and v.excerpts == [] and v.detail_level == "list"
    sp = db.execute(select(SourcePosting).where(SourcePosting.source_key == "7001")).scalar_one()
    assert sp.original_url.endswith("/7001.html") and "track" not in sp.original_url  # funktionierender Originalverweis ohne Tracking
    loc = db.execute(select(PostingLocation).where(PostingLocation.version_id == v.id)).scalar_one()
    assert loc.postal_code == "91010" and loc.match_method in ("place_name", "place_name+plz") and loc.point_origin == "place_centroid"
    # Tag 2: Fenster überlappt (7002 noch enthalten) ⇒ vollständig
    state["feed"] = feed([("7003", "Neu", "Amt Neu", "Südheim", "Tue, 3 Nov 2026 08:00:00 +0100"), ("7002", "Ingenieur (m/w/d)", "Amt Beispiel", "Beispielhausen", "Mon, 2 Nov 2026 09:00:00 +0100")])
    r2 = run_scan(db, scope, D0 + timedelta(days=1), handler=handler)
    assert r2.status == "complete" and r2.coverage["signals"]["window_overlap"] is True and r2.postings_new == 1
    # Tag 3: Fenster überlappt nicht mehr ⇒ partiell („neue Anzeigen können fehlen“), keine Statusänderung
    state["feed"] = feed([("7099", "Viel später", "Amt Spät", "Südheim", "Thu, 5 Nov 2026 08:00:00 +0100")])
    r3 = run_scan(db, scope, D0 + timedelta(days=2), handler=handler)
    assert r3.status == "partial" and "überlappt nicht" in r3.status_detail
    # Layoutänderung/leere Fehlerseite ⇒ fehlgeschlagen mit Parserfehler, nichts wird entfernt
    state["feed"] = b"<html><body>Wartungsarbeiten</body></html>"
    r4 = run_scan(db, scope, D0 + timedelta(days=3), handler=handler)
    assert r4.status == "failed" and db.execute(select(ScanError.kind).where(ScanError.run_id == r4.id)).scalar_one() == "parse"
    db.expire_all()
    assert {s for s in db.execute(select(SourcePosting.status)).scalars()} == {"active"}
    # XML-Entities werden nicht aufgelöst (XXE)
    evil = b'<?xml version="1.0"?><!DOCTYPE r [<!ENTITY x SYSTEM "file:///etc/passwd">]><rss version="2.0"><channel><item><title>&x;T</title><guid>https://www.service.bund.de/a/1.html</guid></item></channel></rss>'
    try:
        titles = [i.posting.title for i in ServiceBundRssAdapter().parse_feed(evil).items]
    except ParseError:
        titles = []  # Eintrag ohne auflösbaren Titel wird verworfen – ebenfalls sicher
    assert not any("root:" in t for t in titles)


def test_sitemap_jsonld_adapter_detail_budget_gone_and_layout_change(db):
    make_regions(db)
    src = Source(key="sm", name="Sitemap-Testquelle (synthetisch)", domain="karriere.interamt.de", allowed_domains=["karriere.interamt.de"], adapter_key="interamt",
                 config_status="active", request_interval_seconds=0, max_pages_per_run=10, max_details_per_run=2)
    db.add(src)
    db.flush()
    from workforce.models import SearchScope

    scope = SearchScope(source_id=src.id, key="alle", version=1, name="Alle", params={}, mode="full", is_active=True)
    db.add(scope)
    db.commit()
    state = {"ids": [101, 102, 103], "broken": set(), "gone": set()}

    def handler(req: httpx.Request) -> httpx.Response:
        p = req.url.path
        if p == "/robots.txt":
            return httpx.Response(200, text=ROBOTS_OK)
        if p == "/sitemap.xml":
            urls = "".join(f"<url><loc>http://karriere.interamt.de/jobs/stelle-nr-{i}</loc></url>" for i in state["ids"])
            return httpx.Response(200, content=f'<?xml version="1.0"?><urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9"><url><loc>http://karriere.interamt.de/wissen</loc></url>{urls}</urlset>'.encode())
        i = int(p.rsplit("-", 1)[-1])
        if i in state["gone"]:
            return httpx.Response(404)
        if i in state["broken"]:
            return httpx.Response(200, text="<html><body>Neues Layout ohne strukturierte Daten</body></html>")
        return httpx.Response(200, text=JOB_HTML.replace("MB-2026-4711", f"MB-{i}").replace("Sachbearbeitung Haushalt", f"Stelle {i}"))

    r1 = run_scan(db, scope, D0, InteramtAdapter(), handler=handler)
    # Liste vollständig, Detailanreicherung wegen Budget (2) unvollständig – getrennt ausgewiesen
    assert r1.status == "complete" and r1.list_complete and r1.detail_complete is False and r1.details_pending == 1 and r1.ids_found == 3
    r2 = run_scan(db, scope, D0 + timedelta(days=1), InteramtAdapter(), handler=handler)
    assert r2.detail_complete and r2.details_pending == 0
    v = db.execute(select(PostingVersion).join(SourcePosting, SourcePosting.current_version_id == PostingVersion.id).where(SourcePosting.source_key == "101")).scalar_one()
    assert v.reference == "MB-101" and v.kreis_keys == ["91001", "91002"] and v.salary_text == "TVöD E 9b" and v.excerpts == []  # store_excerpts=False
    assert "qual:berufsausbildung" in v.feature_required_keys and "skill:haushaltsrecht" in v.feature_keys
    # Layoutänderung einer Detailseite: Parserfehler wird protokolliert, die Anzeige bleibt unverändert im Bestand
    db.execute(Source.__table__.update().values(max_details_per_run=10))  # Budget für die folgenden Schritte ausreichend
    db.execute(SourcePosting.__table__.update().values(detail_due=True))
    db.commit()
    state["broken"] = {101}
    r3 = run_scan(db, scope, D0 + timedelta(days=2), InteramtAdapter(), handler=handler)
    assert r3.status == "complete" and r3.error_count >= 1
    db.expire_all()
    assert db.execute(select(SourcePosting.status).where(SourcePosting.source_key == "101")).scalar_one() == "active"
    # echte Nichtverfügbarkeit (404) muss an zwei verschiedenen Tagen bestätigt sein
    state["broken"], state["gone"] = set(), {102}
    for i, expected in ((3, "active"), (4, "presumed_removed")):
        db.execute(SourcePosting.__table__.update().values(detail_due=True))
        db.commit()
        run_scan(db, scope, D0 + timedelta(days=i), InteramtAdapter(), handler=handler)
        db.expire_all()
        assert db.execute(select(SourcePosting.status).where(SourcePosting.source_key == "102")).scalar_one() == expected


def test_karriere_bund_list_parser_pagination():
    html = ('<html><body><p>Es wurden 1.912 Ergebnisse gefunden.</p>'
            '<a href="/arbeiten-bei-uns/stellenangebote/sachbearbeitung-test/25913788">A</a><a href="/arbeiten-bei-uns/stellenangebote/sachbearbeitung-test/25913788">A (Bild)</a>'
            '<a href="/arbeiten-bei-uns/stellenangebote/referent-test/25913999">B</a><a href="/arbeiten-bei-uns/stellenangebote-bei-uns?tx_solr%5Bpage%5D=2">2</a></body></html>')
    items, total, has_next = KarriereBundAdapter().parse_list(html, "https://karriere.bund.de/arbeiten-bei-uns/stellenangebote-bei-uns")
    assert total == 1912 and has_next and [i.source_key for i in items] == ["25913788", "25913999"]
    assert items[0].url == "https://karriere.bund.de/arbeiten-bei-uns/stellenangebote/sachbearbeitung-test/25913788"


def test_robots_transient_failure_is_retried_and_not_cached_for_a_day():
    """Ein kurzer Verbindungsabbruch bei robots.txt sperrt die Quelle nicht dauerhaft; dauerhafte Störung sperrt nur diesen Lauf."""
    state = {"robots_calls": 0, "fail": 2}

    def handler(req: httpx.Request) -> httpx.Response:
        if req.url.path == "/robots.txt":
            state["robots_calls"] += 1
            if state["robots_calls"] <= state["fail"]:
                raise httpx.ConnectError("Connection reset by peer")
            return httpx.Response(200, text=ROBOTS_OK)
        return httpx.Response(200, text="inhalt")

    f, sleeps = fetcher(handler)
    assert f.get("https://portal.example/a").text == "inhalt" and state["robots_calls"] == 3 and len(sleeps) >= 2  # mit Backoff wiederholt
    state.update(robots_calls=0, fail=99)
    f2, _ = fetcher(handler)
    with pytest.raises(RobotsDisallowed):
        f2.get("https://portal.example/a")
    calls = state["robots_calls"]
    with pytest.raises(RobotsDisallowed):  # innerhalb des Laufs nicht erneut hämmern
        f2.get("https://portal.example/b")
    assert state["robots_calls"] == calls
    state.update(robots_calls=0, fail=0)
    f3, _ = fetcher(handler)  # nächster Lauf: robots.txt wieder erreichbar ⇒ Abruf erlaubt (Fehlschlag wurde nicht gespeichert)
    assert f3.get("https://portal.example/a").text == "inhalt"
