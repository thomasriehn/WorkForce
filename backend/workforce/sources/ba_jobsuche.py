"""BA-Jobsuche: öffentliche HTML-Ergebnislisten und JobPosting-JSON-LD.

Keine direkten Portal-API-Aufrufe. Fehlende/wechselnde Trefferzahlen, wiederholte
Seiten und das Suchlimit belegen keine vollständige Erfassung des Suchbereichs.
"""
from __future__ import annotations

import re
from collections.abc import Iterator
from typing import Any
from urllib.parse import parse_qsl, urlencode, urljoin, urlsplit, urlunsplit

from bs4 import BeautifulSoup

from ..crawl.fetcher import Fetcher, FetchResult
from ..normalize.text import clean_ws
from .base import CoverageAssessment, ListItem, ListPage, ParsedPosting, ParseError, Partition, SourceAdapter
from .jsonld import find_job_postings, posting_from_jsonld


class BaJobsucheAdapter(SourceAdapter):
    key = "ba_jobsuche"
    version = "ba-html-1"
    access_method = "html_list_jsonld"
    default_domains = ("www.arbeitsagentur.de",)
    store_excerpts = False
    LIST_URL = "https://www.arbeitsagentur.de/jobsuche/suche?angebotsart=1"
    RESULT_LIMIT = 10_000
    _DETAIL = re.compile(r"^/jobsuche/jobdetail/([A-Za-z0-9_-]+)/?$")
    _COUNT = re.compile(
        r"(?P<lower>mehr als|über|mindestens)?\s*(?P<count>\d+(?:[.\s]\d{3})*)\s*"
        r"(?P<plus>\+)?\s*(?:Jobs|Stellenangebote?|Ergebnisse?|Treffer)\b", re.IGNORECASE,
    )

    @classmethod
    def search_url(cls, params: dict[str, Any], page: int) -> str:
        """Nur öffentliche Suchseiten; Filter bleiben beim Seitenwechsel erhalten."""
        parts = urlsplit(params.get("list_url") or cls.LIST_URL)
        if (parts.scheme != "https" or parts.netloc != cls.default_domains[0]
                or parts.path.rstrip("/") != "/jobsuche/suche"):
            raise ParseError("BA-Suchbereich muss eine öffentliche https://www.arbeitsagentur.de/jobsuche/suche-URL sein")
        query = [(k, v) for k, v in parse_qsl(parts.query, keep_blank_values=True) if k != "page"]
        return urlunsplit((parts.scheme, parts.netloc, parts.path, urlencode(query + [("page", str(page))]), ""))

    def parse_list(self, html: str, base_url: str) -> tuple[list[ListItem], int, bool]:
        soup = BeautifulSoup(html, "lxml")
        # Ausschließlich sichtbares HTML, kein Angular-/Hydration-State oder interne JSON-Endpunkte.
        for node in soup.select("script, style, template, [hidden], [aria-hidden='true']"):
            node.decompose()
        root = soup.find("main") or soup
        counts = []
        for node in root.select("h1, h2, h3, [id*='ergebnis'], [class*='ergebnis'], [aria-live]"):
            match = self._COUNT.search(node.get_text(" ", strip=True))
            if match:
                counts.append(match)
        if not counts:
            raise ParseError("BA-Trefferzahl fehlt – leere Fehlerseite oder geänderter HTML-Aufbau")
        totals = {int(re.sub(r"\D", "", m["count"])) for m in counts}
        if len(totals) != 1:
            raise ParseError("BA-Trefferzahlen widersprechen sich – Suchbereich nicht verlässlich lesbar")
        total = totals.pop()
        capped = total >= self.RESULT_LIMIT or any(m["lower"] or m["plus"] for m in counts)
        items: dict[str, ListItem] = {}
        for link in root.find_all("a", href=True):
            url = urlsplit(urljoin(base_url, link["href"]))
            match = self._DETAIL.fullmatch(url.path)
            if url.scheme != "https" or url.netloc != self.default_domains[0] or not match:
                continue
            key = match[1]
            canonical = f"https://{self.default_domains[0]}/jobsuche/jobdetail/{key}"
            items.setdefault(key, ListItem(source_key=key, url=canonical))
        if total == 0 and items:
            raise ParseError("BA meldet null Treffer, zeigt aber Anzeigen")
        if total > 0 and not items:
            raise ParseError("BA meldet Treffer, liefert aber keine Anzeigenlinks – Lauf unvollständig")
        return list(items.values()), total, capped

    def list_pages(self, fetcher: Fetcher, params: dict[str, Any], partition: Partition,
                   checkpoint: dict[str, Any] | None) -> Iterator[ListPage]:
        cp = checkpoint or {}
        page = int(cp.get("page", 1))
        seen = set(cp.get("seen_ids", []))
        initial_total = cp.get("total")
        if page < 1 or page > self.RESULT_LIMIT:
            raise ParseError("Ungültiger BA-Seitencheckpoint")
        while True:
            url = self.search_url(params, page)
            result = fetcher.get(url)
            if result.status != 200:
                raise ParseError(f"BA-Ergebnisliste nicht abrufbar (HTTP {result.status})")
            items, total, capped = self.parse_list(result.text, url)
            if initial_total is None:
                initial_total = total
            if total != initial_total:
                raise ParseError("BA-Trefferzahl während der Pagination geändert – keine vollständige Momentaufnahme")
            ids = {item.source_key for item in items}
            if ids & seen:
                raise ParseError("BA-Pagination wiederholt Anzeigen – Seiten verschoben oder Suchlimit erreicht")
            seen.update(ids)
            if len(seen) > total:
                raise ParseError("BA-Liste enthält mehr Anzeigen als gemeldet")
            last = len(seen) == total or len(seen) >= self.RESULT_LIMIT
            signals = {"page": page, "reported_total": total, "unique_ids": len(seen),
                       "capped": capped, "terminal": last, "search_url": self.search_url(params, 1)}
            yield ListPage(
                items=items, reported_total=total, is_last=last, capped=capped and last,
                next_checkpoint=None if last else {"page": page + 1, "seen_ids": sorted(seen), "total": total},
                signals=signals,
            )
            if last:
                return
            page += 1

    def assess_coverage(self, pages: list[dict[str, Any]], previous: dict[str, Any] | None) -> CoverageAssessment:
        sig = dict(pages[-1]) if pages else {}
        complete = bool(sig.get("terminal") and not sig.get("capped")
                        and sig.get("unique_ids") == sig.get("reported_total"))
        note = ("BA-Suchbereich vollständig gelesen (eindeutige Anzeigenzahl entspricht der Trefferzahl)" if complete
                else "BA-Suchbereich unvollständig oder Trefferobergrenze erreicht; Suche nach Ort/Beruf eingrenzen")
        return CoverageAssessment(complete, sig, note)

    def parse_detail(self, result: FetchResult, item_key: str) -> ParsedPosting:
        if result.status != 200:
            raise ParseError(f"BA-Detailseite nicht abrufbar (HTTP {result.status})")
        parts = urlsplit(result.final_url or result.url)
        match = self._DETAIL.fullmatch(parts.path)
        if parts.scheme != "https" or parts.netloc != self.default_domains[0] or not match or match[1] != item_key:
            raise ParseError("BA-Detailseite verweist nicht auf die erwartete Anzeige")
        postings = find_job_postings(result.text)
        if len(postings) != 1:
            raise ParseError("BA-Detailseite enthält nicht genau ein JobPosting-JSON-LD")
        p = posting_from_jsonld(postings[0], source_key=item_key, url=result.url)
        p.url = p.canonical_url = f"https://{self.default_domains[0]}/jobsuche/jobdetail/{item_key}"
        # BA-Referenznummer ist eine Portal-ID, kein portalübergreifender Arbeitgeber-Schlüssel.
        if clean_ws(p.reference) == item_key:
            p.reference = None
        # hiringOrganization.url/sameAs ist die Arbeitgeber-Homepage, keine Bewerbungs-Zieladresse.
        # Deren Verwendung als Deduplizierungsschlüssel könnte verschiedene Stellen zusammenführen.
        p.employer_url = None
        p.quality["access_method"] = self.access_method
        return p
