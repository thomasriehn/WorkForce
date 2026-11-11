"""Synthetische BA-HTML-/JSON-LD-Fixtures; keine externen Abrufe."""
from __future__ import annotations

import json
from datetime import date, timedelta
from urllib.parse import parse_qs, urlsplit

import httpx
import pytest
from sqlalchemy import func, select

from workforce.config import Settings, get_settings
from workforce.crawl.fetcher import Fetcher, FetchResult
from workforce.models import Observation, PostingVersion, ScanTask, SearchScope, Source, SourcePosting
from workforce.pipeline.run import execute_run, request_control
from workforce.sources.ba_jobsuche import BaJobsucheAdapter
from workforce.sources.base import ParseError, Partition
from workforce.sources.registry import seed_registry
from workforce.stats import runner

from .helpers import ROBOTS_OK, fetcher_factory, run_scan

BA = BaJobsucheAdapter()
BASE = "https://www.arbeitsagentur.de"
DAY = date(2026, 11, 11)


def listing(ids=("10000-SYNTH-1",), total="1", extra=""):
    links = "".join(f'<article><a href="/jobsuche/jobdetail/{key}?utm_source=test">'
                    f'Synthetische Anzeige {key}</a></article>' for key in ids)
    return f'<html lang="de"><main><h1>{total} Stellenangebote</h1>{links}{extra}</main></html>'


def detail(key="10000-SYNTH-1"):
    job = {"@context": "https://schema.org", "@type": "JobPosting", "title": "Synthetisch: C++ Entwickler",
           "identifier": {"value": key}, "url": f"{BASE}/jobsuche/jobdetail/{key}?utm_source=test",
           "hiringOrganization": {"name": "Synthetische Musterfirma", "sameAs": "https://example.invalid"},
           "description": "<p>C++ erforderlich. Keine Berufserfahrung erforderlich.</p>",
           "datePosted": "2026-11-10", "validThrough": "2026-12-10", "employmentType": "FULL_TIME",
           "jobLocation": [{"@type": "Place", "address": {"addressLocality": "Berlin", "postalCode": "10115", "addressCountry": "DE"}},
                           {"@type": "Place", "address": {"addressLocality": "Bonn", "addressCountry": "DE"}}]}
    return '<html><script type="application/ld+json">' + json.dumps(job) + '</script></html>'


def fetch(handler):
    return Fetcher(BA.default_domains, settings=get_settings(), interval_seconds=0,
                   transport=httpx.MockTransport(handler), sleep=lambda _: None)


def test_list_canonical_ids_counts_and_foreign_links():
    extra = ('<a href="https://evil.example/jobsuche/jobdetail/evil">Fremdes Ziel</a>'
             '<a href="//www.arbeitsagentur.de/jobsuche/jobdetail/10000-SYNTH-1#top">Doppelter Link</a>')
    items, total, capped = BA.parse_list(listing(extra=extra), BA.LIST_URL)
    assert total == 1 and capped is False
    assert [(i.source_key, i.url) for i in items] == [("10000-SYNTH-1", BASE + "/jobsuche/jobdetail/10000-SYNTH-1")]
    assert BA.parse_list(listing(total="10.000"), BA.LIST_URL)[1:] == (10000, True)
    assert BA.parse_list(listing(total="Mehr als 100"), BA.LIST_URL)[1:] == (100, True)


@pytest.mark.parametrize("html", ["<main>Fehler</main>", listing(ids=(), total="2"),
                                      listing(total="0"), listing(extra="<h2>2 Treffer</h2>")])
def test_broken_lists_are_never_empty_successes(html):
    with pytest.raises(ParseError):
        BA.parse_list(html, BA.LIST_URL)


def test_empty_scope_requires_explicit_zero():
    items, total, capped = BA.parse_list(listing(ids=(), total="0"), BA.LIST_URL)
    assert items == [] and total == 0 and capped is False


def test_pagination_checkpoint_preserves_filter_and_unique_count():
    calls = []

    def handler(req):
        if req.url.path == "/robots.txt":
            return httpx.Response(200, text=ROBOTS_OK)
        calls.append(str(req.url))
        page = int(req.url.params["page"])
        return httpx.Response(200, text=listing(ids=(f"10000-SYNTH-{page}",), total="2"))

    f = fetch(handler)
    params = {"list_url": BA.LIST_URL + "&was=C%2B%2B&wo=Berlin&umkreis=25&page=9"}
    gen = BA.list_pages(f, params, Partition("all"), None)
    first = next(gen)
    gen.close()
    assert not first.is_last
    resumed = list(BA.list_pages(f, params, Partition("all"), first.next_checkpoint))
    f.close()
    assert len(resumed) == 1 and resumed[0].is_last
    assert [parse_qs(urlsplit(u).query)["page"] for u in calls] == [["1"], ["2"]]
    assert all(parse_qs(urlsplit(u).query)["was"] == ["C++"] for u in calls)
    assert BA.assess_coverage([resumed[0].signals], None).list_complete


def test_empty_page_with_reported_hits_is_still_a_parse_error_after_resume():
    second = listing(ids=(), total="2")
    f = fetch(lambda req: httpx.Response(200, text=ROBOTS_OK if req.url.path == "/robots.txt" else second))
    try:
        with pytest.raises(ParseError):
            list(BA.list_pages(f, {}, Partition("all"), {"page": 2, "seen_ids": ["10000-SYNTH-1"], "total": 2}))
    finally:
        f.close()


@pytest.mark.parametrize("totals", [(3, 4, 4, 4), (4, 3, 3), (3, 4, 3), (4, 1)])
def test_live_total_changes_continue_but_never_claim_complete(totals):
    calls = []

    def handler(req):
        if req.url.path == "/robots.txt":
            return httpx.Response(200, text=ROBOTS_OK)
        page = int(req.url.params["page"])
        calls.append(page)
        assert page <= len(totals), "Pagination darf nicht über das Listenende hinauslaufen"
        return httpx.Response(200, text=listing(ids=(f"SYNTH-{page}",), total=str(totals[page - 1])))

    f = fetch(handler)
    try:
        gen = BA.list_pages(f, {}, Partition("all"), None)
        first, second = next(gen), next(gen)
        gen.close()
        # Fortsetzung nach einer bereits erkannten Änderung muss die Einschränkung behalten,
        # auch wenn die Trefferzahl später wieder dem Anfangswert entspricht.
        rest = list(BA.list_pages(f, {}, Partition("all"), second.next_checkpoint)) if not second.is_last else []
    finally:
        f.close()
    pages = [first, second, *rest]
    assert calls == list(range(1, len(totals) + 1))
    assert sum(len(p.items) for p in pages) == len(totals)
    last = pages[-1]
    assert last.is_last and last.signals["total_changed"]
    coverage = BA.assess_coverage([last.signals], None)
    assert not coverage.list_complete and "weiter erfasst" in coverage.note


def test_overlapping_pages_continue_with_unique_items_and_preserve_position_on_resume():
    ids = [("SYNTH-a", "SYNTH-b"), ("SYNTH-b", "SYNTH-c"), ("SYNTH-d",)]

    def handler(req):
        if req.url.path == "/robots.txt":
            return httpx.Response(200, text=ROBOTS_OK)
        page = int(req.url.params["page"])
        assert page <= len(ids)
        return httpx.Response(200, text=listing(ids=ids[page - 1], total="5"))

    f = fetch(handler)
    try:
        gen = BA.list_pages(f, {}, Partition("all"), None)
        first, second = next(gen), next(gen)
        gen.close()
        assert not second.is_last and second.next_checkpoint["rows_seen"] == 4
        last, = BA.list_pages(f, {}, Partition("all"), second.next_checkpoint)
    finally:
        f.close()
    assert [item.source_key for p in (first, second, last) for item in p.items] == ["SYNTH-a", "SYNTH-b", "SYNTH-c", "SYNTH-d"]
    assert last.is_last and last.signals["overlap_count"] == 1 and last.signals["unique_ids"] == 4
    assert not BA.assess_coverage([last.signals], None).list_complete


def test_wholly_repeated_page_terminates_as_partial_without_looping():
    f = fetch(lambda req: httpx.Response(200, text=ROBOTS_OK if req.url.path == "/robots.txt" else listing(total="3")))
    try:
        pages = list(BA.list_pages(f, {}, Partition("all"), None))
    finally:
        f.close()
    assert len(pages) == 2 and pages[1].items == [] and pages[1].is_last
    coverage = BA.assess_coverage([p.signals for p in pages], None)
    assert not coverage.list_complete and "Seite ohne neue Anzeigen" in coverage.note


def test_cap_remains_known_after_total_decreases_on_resume(monkeypatch):
    monkeypatch.setattr(BA, "RESULT_LIMIT", 3)
    totals = (4, 2)
    f = fetch(lambda req: httpx.Response(200, text=ROBOTS_OK if req.url.path == "/robots.txt" else listing(
        ids=(f"SYNTH-{req.url.params['page']}",), total=str(totals[int(req.url.params["page"]) - 1]))))
    try:
        gen = BA.list_pages(f, {}, Partition("all"), None)
        first = next(gen)
        gen.close()
        last, = BA.list_pages(f, {}, Partition("all"), first.next_checkpoint)
    finally:
        f.close()
    assert last.is_last and last.capped and last.signals["capped"]
    assert not BA.assess_coverage([last.signals], None).list_complete


def test_limit_is_partial_and_still_collects_available_pages(monkeypatch):
    monkeypatch.setattr(BA, "RESULT_LIMIT", 2)
    f = fetch(lambda req: httpx.Response(200, text=ROBOTS_OK if req.url.path == "/robots.txt"
                                        else listing(ids=(f"10000-SYNTH-{req.url.params['page']}",), total="3")))
    try:
        pages = list(BA.list_pages(f, {}, Partition("all"), None))
    finally:
        f.close()
    assert len(pages) == 2 and not pages[0].capped and pages[-1].capped
    assert not BA.assess_coverage([p.signals for p in pages], None).list_complete


def test_detail_fields_and_portal_id_not_used_for_cross_source_dedup():
    url = BASE + "/jobsuche/jobdetail/10000-SYNTH-1"
    p = BA.parse_detail(FetchResult(url=url, final_url=url, status=200, content=detail().encode()), "10000-SYNTH-1")
    assert p.title == "Synthetisch: C++ Entwickler" and p.employer_name == "Synthetische Musterfirma"
    assert [loc.locality for loc in p.locations] == ["Berlin", "Bonn"]
    assert p.date_posted == date(2026, 11, 10) and p.working_time == ["vollzeit"]
    assert p.canonical_url == url and p.reference is None and p.employer_url is None
    with pytest.raises(ParseError):
        BA.parse_detail(FetchResult(url=url, final_url=BASE + "/jobsuche/", status=200, content=detail().encode()), "10000-SYNTH-1")
    with pytest.raises(ParseError):
        BA.parse_detail(FetchResult(url=url, final_url=url, status=200, content=b"<main>Layout changed</main>"), "10000-SYNTH-1")


@pytest.mark.parametrize("bad", ["https://127.0.0.1/jobsuche/suche", BASE + "/api/jobs", "http://www.arbeitsagentur.de/jobsuche/suche"])
def test_scope_accepts_only_public_search_urls(bad):
    with pytest.raises(ParseError):
        BA.search_url({"list_url": bad}, 1)


@pytest.mark.parametrize("failure", ["403", "robots", "layout", "repeat", "cap"])
def test_pipeline_repeated_days_and_failures_preserve_postings(db, failure, monkeypatch):
    seed_registry(db)
    source = db.scalar(select(Source).where(Source.key == BA.key))
    source.config_status = "active"
    scope = source.scopes[0]
    db.commit()
    broken = False

    def handler(req):
        if req.url.path == "/robots.txt":
            return httpx.Response(200, text="User-agent: *\nDisallow: /" if broken and failure == "robots" else ROBOTS_OK)
        if req.url.path == "/jobsuche/suche":
            if broken:
                if failure == "403":
                    return httpx.Response(403)
                if failure == "layout":
                    return httpx.Response(200, text="<main>Technischer Fehler</main>")
                if failure in ("repeat", "cap"):
                    return httpx.Response(200, text=listing(total="2"))
            return httpx.Response(200, text=listing())
        return httpx.Response(200, text=detail())

    for offset in (0, 0, 1):
        run = run_scan(db, scope, DAY + timedelta(days=offset), BA, handler=handler)
        assert run.status == "complete" and run.detail_complete
    assert db.scalar(select(func.count()).select_from(SourcePosting)) == 1
    assert db.scalar(select(func.count()).select_from(PostingVersion)) == 1
    assert db.scalar(select(func.count()).select_from(Observation)) == 2
    broken = True
    if failure == "cap":
        monkeypatch.setattr(BA, "RESULT_LIMIT", 1)
    for offset in range(2, 6):
        run = run_scan(db, scope, DAY + timedelta(days=offset), BA, handler=handler)
        assert run.status in ("blocked", "failed", "partial") and not run.list_complete
    assert db.scalar(select(SourcePosting)).status not in ("presumed_removed", "ended")


def test_pipeline_retries_legacy_checkpoint_and_changed_totals_do_not_archive(db, monkeypatch):
    seed_registry(db)
    source = db.scalar(select(Source).where(Source.key == BA.key))
    source.config_status = "active"
    scope = source.scopes[0]
    db.commit()
    day = DAY
    mode = "baseline"
    calls = []
    ids = ["SYNTH-old", "SYNTH-a", "SYNTH-b", "SYNTH-c"]

    def handler(req):
        if req.url.path == "/robots.txt":
            return httpx.Response(200, text=ROBOTS_OK)
        if req.url.path != "/jobsuche/suche":
            return httpx.Response(200, text=detail(req.url.path.rsplit("/", 1)[-1]))
        page = int(req.url.params["page"])
        calls.append(page)
        if mode == "baseline":
            return httpx.Response(200, text=listing(ids=ids, total="4"))
        if mode == "legacy" and page == 2:
            return httpx.Response(200, text="<main>Fehlerseite</main>")
        # Seite 2 verschiebt sich um einen Eintrag, Seite 3 liefert den Rest.
        return httpx.Response(200, text=listing(
            ids=[("SYNTH-a",), ("SYNTH-a", "SYNTH-b"), ("SYNTH-c",)][page - 1],
            total=["3", "4", "4"][page - 1]))

    assert run_scan(db, scope, day, BA, handler=handler).status == "complete"
    mode = "legacy"
    day += timedelta(days=1)
    monkeypatch.setattr("workforce.pipeline.run.local_today", lambda: day)
    run = run_scan(db, scope, day, BA, handler=handler)
    assert run.status == "failed"
    task = db.scalar(select(ScanTask).where(ScanTask.run_id == run.id))
    task.checkpoint = {"page": 2, "seen_ids": ["SYNTH-a"], "total": 3}
    db.commit()
    calls.clear()
    mode = "dynamic"
    request_control(db, run, "retry")
    db.commit()
    execute_run(run.id, settings=get_settings(), fetcher_factory=fetcher_factory(handler), adapter=BA)
    db.expire_all()
    assert calls == [2, 3]  # vorhandene erste Seite nicht nochmals laden
    assert run.status == "partial" and not run.list_complete and run.ids_found == 3
    assert run.coverage["signals"]["overlap_count"] == 1
    assert run.coverage["signals"]["total_changed"]
    assert db.scalar(select(func.count()).select_from(Observation).where(Observation.run_id == run.id)) == 3
    for offset in range(2, 6):
        current = run_scan(db, scope, DAY + timedelta(days=offset), BA, handler=handler)
        assert current.status == "partial" and current.error_count == 0
        assert current.ids_found == 3 and not current.list_complete
    missing = db.scalar(select(SourcePosting).where(SourcePosting.source_key == "SYNTH-old"))
    assert missing.status not in ("presumed_removed", "ended", "not_reobserved")


def test_registry_upgrade_preserves_operator_settings_and_retired_scopes(db):
    source = Source(key=BA.key, name="Eigene BA", domain=BA.default_domains[0], allowed_domains=list(BA.default_domains),
                    config_status="disabled", status_reason="Betreiber hat pausiert", max_pages_per_run=7)
    db.add(source)
    db.commit()
    result = seed_registry(db)
    db.flush()
    assert source.adapter_key == BA.key and source.config_status == "disabled"
    assert source.status_reason == "Betreiber hat pausiert" and source.max_pages_per_run == 7
    scope = db.scalar(select(SearchScope).where(SearchScope.source_id == source.id))
    assert scope and result["scopes"] > 0
    scope.is_active = False
    db.flush()
    assert seed_registry(db) == {"sources": 0, "scopes": 0}
    assert not scope.is_active


def test_statistics_default_opt_out_and_missing_contact(db, monkeypatch):
    monkeypatch.delenv("WF_STATS_BA_AUTO", raising=False)
    assert Settings(_env_file=None).stats_ba_auto is True
    monkeypatch.setenv("WF_STATS_BA_AUTO", "false")
    assert Settings(_env_file=None).stats_ba_auto is False
    monkeypatch.setattr(get_settings(), "stats_ba_auto", False)
    monkeypatch.setattr(runner, "make_fetcher", lambda *a, **kw: pytest.fail("Opt-out darf keinen Abruf starten"))
    result = runner.run_imports(["ba_berufe", "ba_arbeitslose_kreise", "kldb2010"])
    assert all(r["status"] == "skipped" and "WF_STATS_BA_AUTO=false" in r["reason"] for r in result.values())
    spec = runner.DATASET_BY_KEY["ba_berufe"]
    enabled, reason = runner._auto_status(spec, Settings(_env_file=None, env="production", crawler_contact="", stats_ba_auto=True))
    assert not enabled and "WF_CRAWLER_CONTACT" in reason
