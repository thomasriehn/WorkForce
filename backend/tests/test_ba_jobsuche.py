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
from workforce.models import Observation, PostingVersion, SearchScope, Source, SourcePosting
from workforce.sources.ba_jobsuche import BaJobsucheAdapter
from workforce.sources.base import ParseError, Partition
from workforce.sources.registry import seed_registry
from workforce.stats import runner

from .helpers import ROBOTS_OK, run_scan

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


@pytest.mark.parametrize("second", [listing(total="2"), listing(ids=("10000-SYNTH-2",), total="3"),
                                    listing(ids=(), total="2")])
def test_repeat_changed_total_or_empty_page_after_resume(second):
    f = fetch(lambda req: httpx.Response(200, text=ROBOTS_OK if req.url.path == "/robots.txt" else second))
    try:
        with pytest.raises(ParseError):
            list(BA.list_pages(f, {}, Partition("all"), {"page": 2, "seen_ids": ["10000-SYNTH-1"], "total": 2}))
    finally:
        f.close()


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
