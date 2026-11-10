"""Auffinden der jeweils neuesten Datei auf den offiziellen Produktseiten.

Es werden nie Monats-URLs geraten: Jede Funktion wertet die Verweise der veröffentlichten Seite aus (Stand der
Seitenstruktur: 10.11.2026) und meldet mit :class:`ImportProblem`, wenn die erwarteten Verweise fehlen – dann hat
sich die Seite geändert und der manuelle Import ist der Ausweichweg.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date
from urllib.parse import urljoin, urlsplit

from bs4 import BeautifulSoup

from .common import MONTHS, ImportProblem, parse_german_date


@dataclass(frozen=True)
class Candidate:
    """Eine auf der offiziellen Seite gefundene Datei."""

    url: str
    name: str
    label: str
    page_url: str
    period_hint: str | None = None     # Angabe der Seite zum Zeitraum/Stand (nur zur Information)
    published_on: date | None = None   # nur, wenn die Seite ein Datum der Datenaktualisierung nennt
    slot: str = "datei"                # unterscheidet mehrere Dateien eines Datensatzes


BA_BASE = "https://statistik.arbeitsagentur.de"
_BA_RESULT = "div.c-teaser-search-result.statisticdocument a.c-teaser-search-result__title"
_BA_KREISE_CURRENT = re.compile(
    r"^https://statistik\.arbeitsagentur\.de/Statistikdaten/Detail/Aktuell/iiia4/gemeinde-arbeitslose-quoten/"
    r"arbeitslose-quoten-dlk-0-zip\.zip\?__blob=publicationFile&v=\d+$")
_BA_BERUFE = re.compile(
    r"^https://statistik\.arbeitsagentur\.de/Statistikdaten/Detail/(\d{6})/iiia4/berufe-heft-kldb2010/"
    r"berufe-heft-kldb2010-dwol-0-\1-xlsx\.xlsx\?__blob=publicationFile&v=\d+$")
_MONTH_LABEL = re.compile(r"(Januar|Februar|März|April|Mai|Juni|Juli|August|September|Oktober|November|Dezember)\s+(\d{4})")
_VG250_GPKG = re.compile(
    r"^https://daten\.gdz\.bkg\.bund\.de/produkte/vg/vg250_ebenen_1231/aktuell/vg250_12-31\.utm32s\.gpkg\.ebenen\.zip$")
_VG250_STAND = re.compile(r"Aktualitätsstand:\s*(\d{2}\.\d{2}\.\d{4})")
_VG250_CHANGE = re.compile(r"Änderung vom\s+(\d{2}\.\d{2}\.\d{4})\s*(?:[–-]\s*)?Datenaktualisierung\s+Stand\s+(\d{2}\.\d{2}\.\d{4})")
_GV_SLOT = re.compile(r"/Gemeindeverzeichnis/Administrativ/Archiv/GVAuszugQ/AuszugGV([1-4])QAktuell\.html$")
_GV_FILE = re.compile(r"/AuszugGV[1-4]QAktuell\.xlsx\?__blob=publicationFile&v=\d+$")
_KLDB_FILES = {
    "systematik": re.compile(r"/Systematisches-Verzeichnis-KldB-2020\.xlsx\?__blob=publicationFile&v=\d+$"),
    "alphabet": re.compile(r"/Alphabetisches-Verzeichnis-Berufsbenennungen\.xlsx\?__blob=publicationFile&v=\d+$"),
}


def _soup(html: str) -> BeautifulSoup:
    return BeautifulSoup(html, "lxml")


def _text(node: object) -> str:
    return re.sub(r"\s+", " ", node.get_text(" ")).strip()  # type: ignore[attr-defined]


def _file_name(url: str) -> str:
    return urlsplit(url).path.rsplit("/", 1)[-1] or "datei"


def ba_kreise(html: str, page_url: str) -> Candidate:
    """Einzelheftsuche „gemeinde-arbeitslose-quoten“: der Eintrag „(Aktuelle Ausgabe)“."""
    hits = []
    for a in _soup(html).select(_BA_RESULT):
        href = urljoin(page_url, (a.get("href") or "").strip())
        if _BA_KREISE_CURRENT.match(href):
            hits.append((href, _text(a)))
    current = [h for h in hits if "Aktuelle Ausgabe" in h[1]]
    if len(current) != 1:
        raise ImportProblem(
            "BA-Statistik: Der Verweis auf die aktuelle Ausgabe „Arbeitslose und Arbeitslosenquoten – Deutschland, Länder "
            f"und Kreise“ wurde auf der Ergebnisseite nicht eindeutig gefunden ({len(current)} Treffer). "
            "Der Seitenaufbau hat sich vermutlich geändert.")
    href, label = current[0]
    m = _MONTH_LABEL.search(label)
    return Candidate(url=href, name=_file_name(href), label=label, page_url=page_url,
                     period_hint=f"{m.group(1)} {m.group(2)}" if m else None)


def ba_berufe(html: str, page_url: str) -> Candidate:
    """Einzelheftsuche „berufe-heft-kldb2010“: die Ausgabe mit dem jüngsten Monat in der Datei-URL."""
    hits: list[tuple[str, str, str]] = []
    for a in _soup(html).select(_BA_RESULT):
        href = urljoin(page_url, (a.get("href") or "").strip())
        m = _BA_BERUFE.match(href)
        if m:
            hits.append((m.group(1), href, _text(a)))
    if not hits:
        raise ImportProblem("BA-Statistik: Auf der Ergebnisseite „Arbeitsmarkt nach Berufen (KldB 2010)“ wurde kein Verweis "
                            "auf eine Monatsausgabe gefunden. Der Seitenaufbau hat sich vermutlich geändert.")
    yyyymm, href, label = max(hits)
    m = _MONTH_LABEL.search(label)
    if m and (int(m.group(2)), MONTHS[m.group(1).lower()]) != (int(yyyymm[:4]), int(yyyymm[4:])):
        raise ImportProblem(f"BA-Statistik: Linktext „{label}“ und Datei-URL ({yyyymm}) nennen unterschiedliche Monate.")
    return Candidate(url=href, name=_file_name(href), label=label, page_url=page_url, period_hint=f"{yyyymm[:4]}-{yyyymm[4:]}")


def vg250(html: str, page_url: str) -> Candidate:
    """BKG-Produktseite VG250 (Stand 31.12.): Direktdownload „UTM32s, geopackage, Ebenen“."""
    soup = _soup(html)
    links = []
    for a in soup.select("a.download"):
        href = urljoin(page_url, (a.get("href") or "").strip())
        if _VG250_GPKG.match(href):
            links.append((href, _text(a)))
    urls = {h for h, _ in links}
    if len(urls) != 1:
        raise ImportProblem("BKG: Der Direktdownload „VG250 Stand 31.12., UTM32s, Format geopackage, Inhalt Ebenen“ wurde auf "
                            f"der Produktseite nicht eindeutig gefunden ({len(urls)} Treffer).")
    href, label = links[0]
    page_text = _text(soup)
    stand = _VG250_STAND.search(page_text)
    if not stand:
        raise ImportProblem("BKG: Die Angabe „Aktualitätsstand“ fehlt auf der Produktseite.")
    published = None
    for m in _VG250_CHANGE.finditer(page_text):
        if m.group(2) == stand.group(1):
            published = parse_german_date(m.group(1))
            break
    return Candidate(url=href, name=_file_name(href), label=label, page_url=page_url, period_hint=stand.group(1),
                     published_on=published)


def gv_isys_publication_page(html: str, page_url: str) -> tuple[str, date]:
    """Themenseite Gemeindeverzeichnis: Verweis auf die Quartalsausgabe mit dem jüngsten Datum im Linktext."""
    found: dict[str, date] = {}
    for a in _soup(html).select("a[href]"):
        href = urljoin(page_url, (a.get("href") or "").strip())
        if not _GV_SLOT.search(urlsplit(href).path):
            continue
        d = parse_german_date(_text(a)) or parse_german_date(a.get("title") or "")
        if d:
            found[href] = max(d, found.get(href, d))
    if not found:
        raise ImportProblem("Destatis: Auf der Seite „Gemeindeverzeichnis“ wurde kein Verweis auf eine Quartalsausgabe "
                            "(AuszugGV<n>QAktuell) mit Datum gefunden.")
    url, stand = max(found.items(), key=lambda kv: kv[1])
    return url, stand


def gv_isys_file(html: str, page_url: str, stand: date | None = None) -> Candidate:
    """Publikationsseite der Quartalsausgabe: Download-Verweis auf die XLSX-Datei."""
    urls = []
    for a in _soup(html).select("a.downloadLink[href]"):
        href = urljoin(page_url, (a.get("href") or "").strip())
        parts = urlsplit(href)
        if _GV_FILE.search(parts.path + "?" + parts.query):
            urls.append(href)
    if len(set(urls)) != 1:
        raise ImportProblem("Destatis: Der Download-Verweis auf die XLSX-Datei der Quartalsausgabe wurde nicht eindeutig "
                            f"gefunden ({len(set(urls))} Treffer).")
    return Candidate(url=urls[0], name=_file_name(urls[0]), label="Quartalsausgabe GV-ISys", page_url=page_url,
                     period_hint=stand.strftime("%d.%m.%Y") if stand else None)


def kldb(html: str, page_url: str) -> list[Candidate]:
    """Seite „Systematik und Verzeichnisse“ der KldB 2010 (Fassung 2020): beide Excel-Dateien."""
    out: list[Candidate] = []
    soup = _soup(html)
    for slot, rx in _KLDB_FILES.items():
        urls: dict[str, str] = {}
        for a in soup.select("a[href]"):
            href = urljoin(page_url, (a.get("href") or "").strip())
            parts = urlsplit(href)
            if parts.netloc == urlsplit(BA_BASE).netloc and rx.search(parts.path + "?" + parts.query):
                urls.setdefault(href, _text(a))
        if len(urls) != 1:
            raise ImportProblem(f"BA-Statistik: Der Verweis auf das {'systematische' if slot == 'systematik' else 'alphabetische'} "
                                f"Verzeichnis der KldB 2010 wurde nicht eindeutig gefunden ({len(urls)} Treffer).")
        href, label = next(iter(urls.items()))
        out.append(Candidate(url=href, name=_file_name(href), label=label, page_url=page_url, slot=slot))
    return out
