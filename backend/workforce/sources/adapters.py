"""Konkrete Quellenadapter.

* ``service_bund_rss`` – offizieller RSS-Feed von service.bund.de (öffentlich angebotene Datei, nur neue Anzeigen).
* ``sitemap_jsonld``   – generisch: öffentliche Sitemap + JobPosting-JSON-LD der Anzeigenseite
  (INTERAMT, greenjobs, Arbeitgeber-Karriereseiten).
* ``karriere_bund``    – paginierte HTML-Ergebnisliste + JobPosting-JSON-LD.

Welche Adapter in einer Installation laufen dürfen, entscheidet das Quellenregister (Freigabevermerk).
"""
from __future__ import annotations

import html as _html
import re
from collections.abc import Iterator
from datetime import datetime
from email.utils import parsedate_to_datetime
from typing import Any
from urllib.parse import urljoin, urlsplit

from bs4 import BeautifulSoup
from lxml import etree

from ..crawl.fetcher import Fetcher, FetchResult
from ..normalize.text import clean_url, clean_ws
from .ba_jobsuche import BaJobsucheAdapter
from .base import (
    CoverageAssessment,
    ListItem,
    ListPage,
    ParsedPosting,
    ParseError,
    Partition,
    RawLocation,
    SourceAdapter,
)
from .jsonld import EMPLOYMENT_MAP, parse_date, parse_job_page

EMPLOYMENT_MAP.update(
    {
        "BEFRISTET": ("contract", "befristet"),
        "UNBEFRISTET": ("contract", "unbefristet"),
        "VOLLZEIT": ("working_time", "vollzeit"),
        "TEILZEIT": ("working_time", "teilzeit"),
        "AUSBILDUNG": ("kind", "ausbildung"),
        "PRAKTIKUM": ("kind", "praktikum"),
    }
)


def _xml_root(content: bytes) -> etree._Element:
    """XML sicher parsen: keine Entity-Auflösung, kein Netz, keine riesigen Bäume."""
    parser = etree.XMLParser(resolve_entities=False, no_network=True, huge_tree=False, recover=True, load_dtd=False)
    root = etree.fromstring(content, parser=parser)
    if root is None:
        raise ParseError("XML nicht lesbar")
    return root


def _local(tag: Any) -> str:
    return tag.rsplit("}", 1)[-1] if isinstance(tag, str) else ""


_PLZ_ORT = re.compile(r"^\s*(?:D-)?(\d{5})\s+(.+?)\s*$")


def split_places(text: str | None) -> list[RawLocation]:
    """Zerlegt eine Ortsangabe wie „01129 Dresden“ oder „Berlin; Bonn“ in einzelne Arbeitsorte."""
    text = clean_ws(text)
    if not text:
        return []
    parts = [p.strip() for p in re.split(r"\s*;\s*|\s+/\s+|\s*\|\s*|,\s*(?=(?:D-)?\d{5}\s)|\s+und\s+(?=(?:D-)?\d{5}\s)", text) if p.strip()]
    out: list[RawLocation] = []
    for part in parts:
        m = _PLZ_ORT.match(part)
        if m:
            out.append(RawLocation(locality=m[2], postal_code=m[1], country="DE", raw=part))
        else:
            out.append(RawLocation(locality=part, raw=part))
    return out


# =================================================================================================
class ServiceBundRssAdapter(SourceAdapter):
    """Offizieller RSS-Feed „Stellenangebote“ von service.bund.de.

    Der Feed ist ein rollierendes Fenster der neuesten Einträge. Er meldet also nur **neue** Anzeigen;
    das Fehlen einer älteren Anzeige ist kein Schließungssignal. Das Ende ergibt sich aus dem von der
    Quelle angekündigten Veröffentlichungsende.
    """

    key = "service_bund_rss"
    version = "sbrss-1"
    access_method = "official_rss_feed"
    default_domains = ("www.service.bund.de",)
    discovery_mode = "new_only"
    detail_mode = "none"
    store_excerpts = False
    DEFAULT_FEED = "https://www.service.bund.de/Content/Globals/Functions/RSSFeed/RSSGenerator_Stellen.xml"
    _FIELD = re.compile(r"([A-Za-zÄÖÜäöüß \-]+?):\s*<strong>(.*?)</strong>", re.S)

    def list_pages(self, fetcher: Fetcher, params: dict[str, Any], partition: Partition, checkpoint: dict[str, Any] | None) -> Iterator[ListPage]:
        res = fetcher.get(params.get("feed_url") or self.DEFAULT_FEED)
        if res.status != 200:
            raise ParseError(f"Feed nicht abrufbar (HTTP {res.status})")
        yield self.parse_feed(res.content, default_kind=params.get("kind"))

    def parse_feed(self, content: bytes, default_kind: str | None = None) -> ListPage:
        root = _xml_root(content)
        if _local(root.tag) != "rss":
            raise ParseError("kein RSS-Dokument")
        items: list[ListItem] = []
        pubs: list[datetime] = []
        for node in root.iter():
            if _local(node.tag) != "item":
                continue
            fields = {_local(c.tag): (c.text or "") for c in node}
            link = clean_ws(fields.get("guid")) or clean_ws(fields.get("link"))
            title = clean_ws(fields.get("title"))
            if not link or not title:
                continue
            url = clean_url(link.split("#", 1)[0])
            if not url:
                continue
            m = re.search(r"/(\d+)\.html$", urlsplit(url).path)
            key = m[1] if m else urlsplit(url).path
            desc = fields.get("description") or ""
            meta = {clean_ws(k) or "": clean_ws(BeautifulSoup(v, "lxml").get_text(" ")) for k, v in self._FIELD.findall(desc)}
            published = None
            try:
                published = parsedate_to_datetime(fields.get("pubDate", "").strip())
            except (TypeError, ValueError):
                published = None
            p = ParsedPosting(source_key=key, url=url, title=_html.unescape(title), canonical_url=url, detail_level="list")
            p.employer_name = meta.get("Arbeitgeber")
            p.locations = split_places(meta.get("Ort"))
            p.apply_until = parse_date(meta.get("Bewerbungsfrist"))
            p.valid_through = parse_date(meta.get("Veröffentlichungsende"))
            p.date_posted = published.date() if published else None
            p.kind = default_kind
            p.raw_payload = {"title": p.title, "employer": p.employer_name, "ort": meta.get("Ort"),
                             "frist": meta.get("Bewerbungsfrist"), "ende": meta.get("Veröffentlichungsende")}
            if published:
                pubs.append(published)
            items.append(ListItem(source_key=key, url=url, posting=p, published_at=published))
        if not items:
            raise ParseError("Feed enthält keine Einträge (leere Antwort oder geänderter Aufbau)")
        signals = {
            "feed_items": len(items),
            "oldest_published": min(pubs).isoformat() if pubs else None,
            "newest_published": max(pubs).isoformat() if pubs else None,
        }
        return ListPage(items=items, reported_total=None, is_last=True, signals=signals)

    def assess_coverage(self, pages: list[dict[str, Any]], previous: dict[str, Any] | None) -> CoverageAssessment:
        sig = pages[-1] if pages else {}
        oldest, prev_newest = sig.get("oldest_published"), (previous or {}).get("newest_published")
        signals = dict(sig)
        if not prev_newest:
            signals["window_overlap"] = None
            return CoverageAssessment(True, signals, "Erstlauf: Feedfenster ohne Vergleich (Bestandsaufnahme der neuesten Einträge)")
        if oldest and datetime.fromisoformat(oldest) <= datetime.fromisoformat(prev_newest):
            signals["window_overlap"] = True
            return CoverageAssessment(True, signals, "Feedfenster überlappt mit dem vorherigen Lauf – neue Anzeigen lückenlos")
        signals["window_overlap"] = False
        return CoverageAssessment(False, signals, "Feedfenster überlappt nicht mit dem vorherigen Lauf – neue Anzeigen können fehlen")


# =================================================================================================
class SitemapJsonLdAdapter(SourceAdapter):
    """Öffentliche Sitemap (vollständige Aufzählung) + JobPosting-JSON-LD der Anzeigenseite."""

    key = "sitemap_jsonld"
    version = "smld-1"
    access_method = "sitemap_jsonld"
    discovery_mode = "full"
    detail_mode = "required"
    sitemap_urls: tuple[str, ...] = ()
    url_pattern: str = r".*"
    id_pattern: str | None = None
    chunk = 500
    max_sitemap_files = 60

    def _cfg(self, params: dict[str, Any]) -> tuple[list[str], re.Pattern[str], re.Pattern[str] | None]:
        sitemaps = list(params.get("sitemap_urls") or self.sitemap_urls)
        if not sitemaps:
            raise ParseError("keine Sitemap konfiguriert")
        pat = re.compile(params.get("url_pattern") or self.url_pattern)
        idp = params.get("id_pattern") or self.id_pattern
        return sitemaps, pat, re.compile(idp) if idp else None

    def key_for(self, url: str, id_rx: re.Pattern[str] | None) -> str:
        if id_rx:
            m = id_rx.search(url)
            if m:
                return m.group(1) if m.groups() else m.group(0)
        return urlsplit(url).path.rstrip("/")

    def list_pages(self, fetcher: Fetcher, params: dict[str, Any], partition: Partition, checkpoint: dict[str, Any] | None) -> Iterator[ListPage]:
        sitemaps, pat, id_rx = self._cfg(params)
        queue = list(sitemaps)
        seen_files: set[str] = set()
        found: dict[str, ListItem] = {}
        files = 0
        while queue:
            sm = queue.pop(0)
            if sm in seen_files:
                continue
            seen_files.add(sm)
            files += 1
            if files > self.max_sitemap_files:
                raise ParseError("zu viele Sitemap-Dateien – Abbruch (Suchbereich enger fassen)")
            res = fetcher.get(sm)
            if res.status != 200:
                raise ParseError(f"Sitemap nicht abrufbar (HTTP {res.status}): {sm}")
            root = _xml_root(res.content)
            kind = _local(root.tag)
            if kind == "sitemapindex":
                for node in root.iter():
                    if _local(node.tag) == "loc" and node.text:
                        queue.append(node.text.strip())
                continue
            if kind != "urlset":
                raise ParseError(f"unerwartetes Sitemap-Wurzelelement {kind!r}")
            for url_node in root:
                if _local(url_node.tag) != "url":
                    continue
                loc = lastmod = None
                for c in url_node:
                    if _local(c.tag) == "loc":
                        loc = (c.text or "").strip()
                    elif _local(c.tag) == "lastmod":
                        lastmod = (c.text or "").strip() or None
                url = clean_url(loc)
                if not url or not pat.search(url):
                    continue
                k = self.key_for(url, id_rx)
                found.setdefault(k, ListItem(source_key=k, url=url, lastmod=lastmod))
        items = list(found.values())
        if not items:
            raise ParseError("Sitemap enthält keine passenden Anzeigen-URLs (leer oder geänderter Aufbau)")
        start = int((checkpoint or {}).get("offset", 0))
        total = len(items)
        for off in range(start, total, self.chunk):
            part = items[off : off + self.chunk]
            last = off + self.chunk >= total
            yield ListPage(items=part, reported_total=total, is_last=last,
                           next_checkpoint=None if last else {"offset": off + self.chunk},
                           signals={"sitemap_files": files, "sitemap_urls": total})

    def assess_coverage(self, pages: list[dict[str, Any]], previous: dict[str, Any] | None) -> CoverageAssessment:
        sig = dict(pages[-1]) if pages else {}
        return CoverageAssessment(True, sig, "Sitemap vollständig gelesen")

    def parse_detail(self, result: FetchResult, item_key: str) -> ParsedPosting:
        p = parse_job_page(result.text, source_key=item_key, url=result.url)
        self.postprocess(p, result)
        return p

    def postprocess(self, p: ParsedPosting, result: FetchResult) -> None:
        """Quellenspezifische Nachbearbeitung."""


class InteramtAdapter(SitemapJsonLdAdapter):
    key = "interamt"
    version = "interamt-1"
    default_domains = ("karriere.interamt.de",)
    sitemap_urls = ("https://karriere.interamt.de/sitemap.xml",)
    url_pattern = r"^https://karriere\.interamt\.de/jobs/[^/?#]+-\d+$"
    id_pattern = r"-(\d+)$"
    store_excerpts = False

    def postprocess(self, p: ParsedPosting, result: FetchResult) -> None:
        # JSON-LD nennt Besoldungs-/Tarifgruppe als Namen ohne Betrag
        if p.salary_text:
            p.salary_text = re.sub(r"^Besoldungsgruppe/Tarif\s*", "", p.salary_text).strip() or p.salary_text
            p.salary_origin = "employer"


class GreenjobsAdapter(SitemapJsonLdAdapter):
    key = "greenjobs"
    version = "greenjobs-1"
    default_domains = ("www.greenjobs.de",)
    sitemap_urls = ("https://www.greenjobs.de/sitemap.xml",)
    url_pattern = r"^https://www\.greenjobs\.de/stellenanzeige/[^/?#]+--\d+/?$"
    id_pattern = r"--(\d+)/?$"
    store_excerpts = False


class CareerPageAdapter(SitemapJsonLdAdapter):
    """Öffentliche Karriereseite eines einzelnen Arbeitgebers (eigene Quelle je Domain).

    Suchbereichsparameter: ``sitemap_urls``, ``url_pattern`` (Regex für Anzeigen-URLs), optional ``id_pattern``.
    Die Domain muss vor der Freigabe gesondert geprüft werden (robots.txt, Nutzungsbedingungen).
    """

    key = "career_page"
    version = "career-1"
    access_method = "sitemap_jsonld"


# =================================================================================================
class KarriereBundAdapter(SourceAdapter):
    """karriere.bund.de: paginierte Ergebnisliste (HTML) + JobPosting-JSON-LD der Detailseite."""

    key = "karriere_bund"
    version = "kbund-1"
    access_method = "html_list_jsonld"
    default_domains = ("karriere.bund.de",)
    discovery_mode = "full"
    detail_mode = "required"
    store_excerpts = False
    LIST_URL = "https://karriere.bund.de/arbeiten-bei-uns/stellenangebote-bei-uns"
    _DETAIL = re.compile(r"^/arbeiten-bei-uns/stellenangebote/[^/?#]+/(\d+)$")
    _TOTAL = re.compile(r"Es wurden?\s+([\d\.]+)\s+Ergebnis")

    def parse_list(self, html: str, base_url: str) -> tuple[list[ListItem], int | None, bool]:
        soup = BeautifulSoup(html, "lxml")
        items: dict[str, ListItem] = {}
        for a in soup.find_all("a", href=True):
            path = urlsplit(a["href"]).path
            m = self._DETAIL.match(path)
            if m:
                items.setdefault(m[1], ListItem(source_key=m[1], url=urljoin(base_url, path)))
        text = soup.get_text(" ", strip=True)
        mt = self._TOTAL.search(text)
        total = int(mt[1].replace(".", "")) if mt else None
        has_next = any("tx_solr%5Bpage%5D" in a["href"] or "tx_solr[page]" in a["href"] for a in soup.find_all("a", href=True))
        return list(items.values()), total, has_next

    def list_pages(self, fetcher: Fetcher, params: dict[str, Any], partition: Partition, checkpoint: dict[str, Any] | None) -> Iterator[ListPage]:
        page = int((checkpoint or {}).get("page", 1))
        seen = int((checkpoint or {}).get("seen", 0))
        base = params.get("list_url") or self.LIST_URL
        while True:
            url = base if page == 1 else f"{base}?tx_solr%5Bpage%5D={page}"
            res = fetcher.get(url)
            if res.status != 200:
                raise ParseError(f"Ergebnisliste nicht abrufbar (HTTP {res.status})")
            items, total, _ = self.parse_list(res.text, base)
            if total is None and page == 1:
                raise ParseError("Trefferzahl nicht gefunden – Aufbau der Ergebnisliste geändert?")
            seen += len(items)
            last = not items or (total is not None and seen >= total)
            yield ListPage(items=items, reported_total=total, is_last=last,
                           next_checkpoint=None if last else {"page": page + 1, "seen": seen},
                           signals={"page": page, "reported_total": total})
            if last:
                return
            page += 1

    def assess_coverage(self, pages: list[dict[str, Any]], previous: dict[str, Any] | None) -> CoverageAssessment:
        sig = dict(pages[-1]) if pages else {}
        return CoverageAssessment(True, sig, "Ergebnisliste bis zur letzten Seite gelesen")

    def parse_detail(self, result: FetchResult, item_key: str) -> ParsedPosting:
        p = parse_job_page(result.text, source_key=item_key, url=result.url)
        if p.occupation_label:  # hier: Tätigkeitsbereich des Portals, keine Berufsbenennung
            p.occupation_field, p.occupation_label = p.occupation_label, None
        if p.reference == item_key:  # Portal-ID, keine Stellenreferenz des Arbeitgebers
            p.reference = None
        return p


ADAPTERS: dict[str, type[SourceAdapter]] = {
    a.key: a for a in (ServiceBundRssAdapter, InteramtAdapter, GreenjobsAdapter, CareerPageAdapter, KarriereBundAdapter, BaJobsucheAdapter)
}


def get_adapter(key: str) -> SourceAdapter:
    try:
        return ADAPTERS[key]()
    except KeyError as exc:
        raise KeyError(f"unbekannter Adapter {key!r}") from exc
