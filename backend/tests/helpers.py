"""Testhilfen: synthetische Quellen, Fake-Adapter und Laufausführung ohne Netzwerk."""
from __future__ import annotations

from collections.abc import Callable, Iterator
from datetime import date
from typing import Any

import httpx

from workforce.config import get_settings
from workforce.crawl.fetcher import Fetcher
from workforce.models import ScanRun, SearchScope, Source
from workforce.pipeline.run import create_run, execute_run
from workforce.sources.base import CoverageAssessment, ListItem, ListPage, ParsedPosting, Partition, RawLocation, SourceAdapter

ROBOTS_OK = "User-agent: *\nAllow: /\n"


def make_source(db: Any, key: str = "testquelle", *, status: str = "active", mode: str = "full", adapter_key: str | None = None,
                domain: str = "portal.example") -> tuple[Source, SearchScope]:
    src = Source(key=key, name=f"Testquelle {key} (synthetisch)", domain=domain, allowed_domains=[domain], adapter_key=adapter_key,
                 config_status=status, request_interval_seconds=0, max_pages_per_run=100, max_details_per_run=100)
    db.add(src)
    db.flush()
    scope = SearchScope(source_id=src.id, key="alle", version=1, name="Alle", params={}, mode=mode, is_active=True)
    db.add(scope)
    db.commit()
    return src, scope


def posting(key: str, title: str = "Sachbearbeiter (m/w/d)", employer: str = "Musterstadt Verwaltung", *, place: str | None = "Musterstadt",
            plz: str | None = None, description: str | None = None, reference: str | None = None, domain: str = "portal.example",
            **kw: Any) -> ParsedPosting:
    p = ParsedPosting(source_key=key, url=f"https://{domain}/jobs/{key}", title=title, employer_name=employer, reference=reference)
    if place:
        p.locations = [RawLocation(locality=place, postal_code=plz, country="DE", raw=place)]
    p.description_text = description
    p.detail_level = "detail" if description is not None else "list"
    p.raw_payload = {"t": title, "e": employer, "d": description, "p": place, "r": reference, **{k: str(v) for k, v in kw.items()}}
    for k, v in kw.items():
        setattr(p, k, v)
    return p


class FakeAdapter(SourceAdapter):
    """Liefert vorgegebene Seiten; ``behaviour`` kann Fehler oder Sonderfälle auslösen."""

    key = "fake"
    version = "fake-1"
    discovery_mode = "full"
    detail_mode = "none"

    def __init__(self, pages: list[list[ParsedPosting]] | None = None, *, behaviour: Callable[[int], Any] | None = None,
                 reported_total: int | None = None, capped: bool = False, complete: bool = True, version: str = "fake-1"):
        self.pages = pages or []
        self.behaviour = behaviour
        self.reported_total = reported_total
        self.capped = capped
        self.complete = complete
        self.version = version

    def list_pages(self, fetcher: Fetcher, params: dict[str, Any], partition: Partition, checkpoint: dict[str, Any] | None) -> Iterator[ListPage]:
        start = int((checkpoint or {}).get("page", 0))
        for i in range(start, len(self.pages)):
            if self.behaviour:
                self.behaviour(i)
            items = [ListItem(source_key=p.source_key, url=p.url, posting=p) for p in self.pages[i]]
            last = i == len(self.pages) - 1
            yield ListPage(items=items, reported_total=self.reported_total, is_last=last, capped=self.capped and last,
                           next_checkpoint=None if last else {"page": i + 1}, signals={"page": i})

    def assess_coverage(self, pages: list[dict[str, Any]], previous: dict[str, Any] | None) -> CoverageAssessment:
        return CoverageAssessment(self.complete, {}, None if self.complete else "Abdeckung nicht belegbar (Test)")


def fetcher_factory(handler: Callable[[httpx.Request], httpx.Response] | None = None) -> Callable[..., Fetcher]:
    def default(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/robots.txt":
            return httpx.Response(200, text=ROBOTS_OK)
        return httpx.Response(404)

    def factory(source: Source, adapter: SourceAdapter, settings: Any) -> Fetcher:
        return Fetcher(tuple(source.allowed_domains or adapter.default_domains), interval_seconds=0, settings=settings,
                       transport=httpx.MockTransport(handler or default), sleep=lambda s: None)

    return factory


def run_scan(db: Any, scope: SearchScope, day: date, adapter: SourceAdapter | None = None, *, handler: Any = None, page_limit: int | None = None,
             is_test: bool = False, trigger: str = "scheduled") -> ScanRun:
    run, _ = create_run(db, scope, day, trigger, page_limit=page_limit, is_test=is_test)
    db.commit()
    try:
        execute_run(run.id, settings=get_settings(), fetcher_factory=fetcher_factory(handler), adapter=adapter)
    finally:
        db.expire_all()
    return db.get(ScanRun, run.id)
