"""Generischer Parser für schema.org/JobPosting (JSON-LD), wie er in öffentlichem HTML eingebettet ist.

Liefert gemeinsame Extraktionslogik für Portale und Arbeitgeber-Karriereseiten. Er ersetzt nicht die
Prüfung der jeweiligen Domain (robots.txt, Nutzungsbedingungen).
"""
from __future__ import annotations

import json
import re
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from typing import Any

from bs4 import BeautifulSoup

from ..normalize.text import clean_url, clean_ws, html_to_text
from .base import ParsedPosting, ParseError, RawLocation

EMPLOYMENT_MAP = {
    "FULL_TIME": ("working_time", "vollzeit"),
    "FULLTIME": ("working_time", "vollzeit"),
    "PART_TIME": ("working_time", "teilzeit"),
    "PARTTIME": ("working_time", "teilzeit"),
    "CONTRACTOR": ("employment", "freie_mitarbeit"),
    "TEMPORARY": ("contract", "befristet"),
    "INTERN": ("kind", "praktikum"),
    "INTERNSHIP": ("kind", "praktikum"),
    "VOLUNTEER": ("employment", "ehrenamt"),
    "PER_DIEM": ("employment", "tageweise"),
    "APPRENTICESHIP": ("kind", "ausbildung"),
}
_MONTHS = {m: i for i, m in enumerate(["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"], 1)}
COUNTRY_NAMES = {
    "deutschland": "DE", "germany": "DE", "de": "DE", "deu": "DE", "österreich": "AT", "austria": "AT", "at": "AT",
    "schweiz": "CH", "switzerland": "CH", "ch": "CH",
}


def parse_date(value: Any) -> date | None:
    """Liest ISO-Daten, deutsche Datumsangaben und Java-``Date.toString()``-Formate. Unbekannt bleibt None."""
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    s = str(value).strip()
    if not s:
        return None
    m = re.match(r"^(\d{4})-(\d{2})-(\d{2})", s)
    if m:
        try:
            return date(int(m[1]), int(m[2]), int(m[3]))
        except ValueError:
            return None
    m = re.match(r"^(\d{1,2})\.(\d{1,2})\.(\d{4})", s)
    if m:
        try:
            return date(int(m[3]), int(m[2]), int(m[1]))
        except ValueError:
            return None
    # z. B. "Tue Nov 10 16:46:16 CET 2026"
    m = re.match(r"^[A-Za-z]{3},?\s+([A-Za-z]{3})\s+(\d{1,2})\s+[\d:]+\s+\S+\s+(\d{4})$", s)
    if m and m[1].lower() in _MONTHS:
        try:
            return date(int(m[3]), _MONTHS[m[1].lower()], int(m[2]))
        except ValueError:
            return None
    # RFC 822: "Tue, 10 Nov 2026 14:00:00 +0100"
    m = re.match(r"^[A-Za-z]{3},\s+(\d{1,2})\s+([A-Za-z]{3})\s+(\d{4})", s)
    if m and m[2].lower() in _MONTHS:
        try:
            return date(int(m[3]), _MONTHS[m[2].lower()], int(m[1]))
        except ValueError:
            return None
    return None


def _as_list(v: Any) -> list[Any]:
    if v is None:
        return []
    return v if isinstance(v, list) else [v]


def _types(obj: dict[str, Any]) -> list[str]:
    return [str(t).rsplit("/", 1)[-1] for t in _as_list(obj.get("@type"))]


def extract_jsonld(html: str) -> list[dict[str, Any]]:
    """Alle JSON-LD-Objekte einer Seite (flach, inkl. ``@graph``). Defekte Blöcke werden übersprungen."""
    soup = BeautifulSoup(html, "lxml")
    out: list[dict[str, Any]] = []

    def walk(node: Any) -> None:
        if isinstance(node, list):
            for n in node:
                walk(n)
        elif isinstance(node, dict):
            if "@graph" in node:
                walk(node["@graph"])
            out.append(node)

    for tag in soup.find_all("script", attrs={"type": re.compile(r"application/ld\+json", re.I)}):
        raw = tag.string or tag.get_text() or ""
        raw = raw.strip()
        if not raw:
            continue
        try:
            walk(json.loads(raw))
        except json.JSONDecodeError:
            try:  # häufig: Steuerzeichen im JSON
                walk(json.loads(re.sub(r"[\x00-\x1f]+", " ", raw)))
            except json.JSONDecodeError:
                continue
    return out


def find_job_postings(html: str) -> list[dict[str, Any]]:
    return [o for o in extract_jsonld(html) if "JobPosting" in _types(o)]


def _text(v: Any) -> str | None:
    if v is None:
        return None
    if isinstance(v, dict):
        v = v.get("name") or v.get("value") or v.get("@value")
    if isinstance(v, list):
        v = ", ".join(str(x) for x in v if x)
    return clean_ws(str(v)) if v not in (None, "") else None


def _decimal(v: Any) -> Decimal | None:
    if v in (None, ""):
        return None
    try:
        s = str(v).strip().replace(" ", "").replace(" ", "")
        if re.match(r"^\d{1,3}(\.\d{3})+(,\d+)?$", s):  # deutsches Zahlenformat
            s = s.replace(".", "").replace(",", ".")
        elif "," in s and "." not in s:
            s = s.replace(",", ".")
        d = Decimal(s)
        return d if d > 0 else None
    except (InvalidOperation, ValueError):
        return None


def _country(v: Any) -> str | None:
    t = _text(v)
    if not t:
        return None
    return COUNTRY_NAMES.get(t.lower(), t.upper() if len(t) == 2 else None)


def _locations(obj: dict[str, Any]) -> list[RawLocation]:
    locs: list[RawLocation] = []
    for place in _as_list(obj.get("jobLocation")):
        if isinstance(place, str):
            locs.append(RawLocation(locality=clean_ws(place), raw=clean_ws(place)))
            continue
        if not isinstance(place, dict):
            continue
        addr = place.get("address")
        if isinstance(addr, str):
            locs.append(RawLocation(locality=clean_ws(addr), raw=clean_ws(addr)))
            continue
        if not isinstance(addr, dict):
            name = _text(place.get("name"))
            if name:
                locs.append(RawLocation(locality=name, raw=name))
            continue
        locality = _text(addr.get("addressLocality"))
        plz = _text(addr.get("postalCode"))
        region = _text(addr.get("addressRegion"))
        country = _country(addr.get("addressCountry"))
        geo = place.get("geo") if isinstance(place.get("geo"), dict) else {}
        lat = lon = None
        try:
            if geo.get("latitude") not in (None, "") and geo.get("longitude") not in (None, ""):
                lat, lon = float(geo["latitude"]), float(geo["longitude"])
                if abs(lat) < 0.001 and abs(lon) < 0.001:
                    lat = lon = None
        except (TypeError, ValueError):
            lat = lon = None
        if not (locality or plz or region or country):
            continue
        raw = ", ".join(x for x in (plz, locality, region, country) if x)
        locs.append(RawLocation(locality=locality, postal_code=plz, region=region, country=country, raw=raw, lat=lat, lon=lon))
    return locs


def _salary(obj: dict[str, Any], p: ParsedPosting) -> None:
    for key, origin in (("baseSalary", "unknown"), ("estimatedSalary", "portal_estimate")):
        sal = obj.get(key)
        if isinstance(sal, list):
            sal = sal[0] if sal else None
        if not isinstance(sal, dict):
            continue
        currency = _text(sal.get("currency"))
        value = sal.get("value")
        name = _text(sal.get("name"))
        vmin = vmax = None
        unit = None
        if isinstance(value, dict):
            unit = _text(value.get("unitText"))
            vmin = _decimal(value.get("minValue")) or _decimal(value.get("value"))
            vmax = _decimal(value.get("maxValue")) or _decimal(value.get("value"))
            name = name or _text(value.get("name"))
        elif value is not None:
            vmin = vmax = _decimal(value)
            unit = _text(sal.get("unitText"))
        else:
            vmin, vmax = _decimal(sal.get("minValue")), _decimal(sal.get("maxValue"))
            unit = _text(sal.get("unitText"))
        if vmin or vmax:
            p.salary_min, p.salary_max = vmin, vmax
            p.salary_currency = (currency or "")[:3].upper() or None
            p.salary_period = (unit or "").upper()[:8] or None
            p.salary_origin = origin
        if name and not p.salary_text:
            p.salary_text = name[:200]
            p.salary_origin = p.salary_origin or origin
        if p.salary_min or p.salary_text:
            return


def posting_from_jsonld(obj: dict[str, Any], *, source_key: str, url: str) -> ParsedPosting:
    """Bildet ein JobPosting-Objekt auf Rumpfdaten ab. Fehlende Angaben bleiben unbekannt (None)."""
    title = _text(obj.get("title")) or _text(obj.get("name"))
    if not title:
        raise ParseError("JobPosting ohne Titel")
    p = ParsedPosting(source_key=source_key, url=url, title=title)
    p.canonical_url = clean_url(_text(obj.get("url"))) or clean_url(url)
    org = obj.get("hiringOrganization")
    if isinstance(org, dict):
        p.employer_name = _text(org.get("name"))
        p.employer_url = clean_url(_text(org.get("sameAs")) or _text(org.get("url")))
    elif isinstance(org, str):
        p.employer_name = clean_ws(org)
    ident = obj.get("identifier")
    if isinstance(ident, dict):
        p.reference = _text(ident.get("value"))
    elif isinstance(ident, (str, int)):
        p.reference = clean_ws(str(ident))
    p.locations = _locations(obj)
    for et in _as_list(obj.get("employmentType")):
        token = str(et).rsplit("/", 1)[-1].upper().replace("-", "_").replace(" ", "_")
        token = re.sub(r"(?<=[A-Z])(?=TIME$)", "_", token) if token in ("FULLTIME", "PARTTIME") else token
        mapped = EMPLOYMENT_MAP.get(token)
        if not mapped:
            continue
        slot, value = mapped
        if slot == "working_time" and value not in p.working_time:
            p.working_time.append(value)
        elif slot == "employment" and value not in p.employment_types:
            p.employment_types.append(value)
        elif slot == "contract":
            p.contract_term = value
        elif slot == "kind":
            p.kind = value
    jlt = _text(obj.get("jobLocationType"))
    if jlt and "TELECOMMUTE" in jlt.upper():
        # mit konkretem Arbeitsort werten wir das als hybrid, ohne als remote
        p.remote_type = "hybrid" if any(loc.locality or loc.postal_code for loc in p.locations) else "remote"
    p.date_posted = parse_date(obj.get("datePosted"))
    p.valid_through = parse_date(obj.get("validThrough"))
    p.occupation_label = _text(obj.get("occupationalCategory"))
    p.occupation_field = _text(obj.get("industry"))
    _salary(obj, p)
    p.description_text = html_to_text(_text_raw(obj.get("description")))
    hints: dict[str, Any] = {}
    for k in ("skills", "qualifications", "educationRequirements", "experienceRequirements", "responsibilities"):
        v = obj.get(k)
        if v:
            hints[k] = v
    p.structured_hints = hints
    # stabiler Rohinhalt: fachliche Felder ohne dynamische Anteile (z. B. Logos, Tracking-URLs)
    p.raw_payload = {
        k: obj.get(k)
        for k in ("title", "description", "datePosted", "validThrough", "employmentType", "jobLocation",
                  "jobLocationType", "baseSalary", "identifier", "occupationalCategory", "skills",
                  "qualifications", "educationRequirements", "experienceRequirements")
        if obj.get(k) is not None
    }
    p.raw_payload["hiringOrganization"] = p.employer_name
    return p


def _text_raw(v: Any) -> str | None:
    if v is None:
        return None
    if isinstance(v, dict):
        v = v.get("@value") or v.get("value")
    return str(v) if v not in (None, "") else None


def parse_job_page(html: str, *, source_key: str, url: str) -> ParsedPosting:
    """Erwartet genau ein JobPosting im HTML einer Anzeigenseite."""
    postings = find_job_postings(html)
    if not postings:
        raise ParseError("kein JobPosting-JSON-LD gefunden")
    return posting_from_jsonld(postings[0], source_key=source_key, url=url)
