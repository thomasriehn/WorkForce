"""Lokale Georeferenzierung: Arbeitsort → Gemeinde → Kreis (ohne externe Geocoding-API).

Regeln (``GEO_RULE_VERSION``):
1. Von der Quelle gelieferte Koordinaten → Punkt-in-Polygon gegen die Kreisgrenzen (VG250).
2. Ortsname exakt (normalisiert) in der Ortsreferenz; bei Mehrdeutigkeit entscheiden Bundesland-Angabe
   und PLZ-Nähe. Bleibt es mehrdeutig, wird **nicht** zugeordnet.
3. Kreisname („Landkreis Leipzig“) → Kreis; Bundeslandname → nur Land (für die Kreiskarte ungeklärt).
4. Alles andere bleibt in der eigenen Kategorie „ungeklärt“. Es werden keine Koordinaten erfunden;
   Ortsmittelpunkte sind als angenähert gekennzeichnet.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date
from typing import Any

from sqlalchemy import text as sql
from sqlalchemy.orm import Session

from ..normalize.text import fold
from ..sources.base import RawLocation

STATE_NAMES = {
    "schleswig holstein": "01", "hamburg": "02", "niedersachsen": "03", "bremen": "04", "nordrhein westfalen": "05",
    "hessen": "06", "rheinland pfalz": "07", "baden wuerttemberg": "08", "bayern": "09", "saarland": "10",
    "berlin": "11", "brandenburg": "12", "mecklenburg vorpommern": "13", "sachsen": "14", "sachsen anhalt": "15",
    "thueringen": "16", "nrw": "05", "bw": "08", "by": "09", "mv": "13", "sh": "01", "rlp": "07",
}
NATIONWIDE = re.compile(r"^(deutschland(weit)?|bundesweit|bundesgebiet|germany|remote|home ?office|ueberall|verschiedene (stand)?orte|mehrere (stand)?orte)$")
FOREIGN_COUNTRIES = {"AT", "CH", "FR", "NL", "BE", "LU", "PL", "CZ", "DK", "IT", "ES", "GB", "UK", "US", "SE", "NO"}
_SUFFIX = re.compile(r"\s+(?:bei|b\.|nahe|naehe|raum|grossraum|region|umgebung|und umgebung|area)\s+.*$|\s*\(.*?\)\s*$")
_PREFIX = re.compile(r"^(?:raum|grossraum|region|kreis|landkreis|lk|stadt|hansestadt|landeshauptstadt|kreisfreie stadt|gemeinde|bundesstadt)\s+")


@dataclass
class GeoMatch:
    kreis_key: str | None = None
    state_key: str | None = None
    ags: str | None = None
    method: str = "unresolved"
    precision: str = "unresolved"  # coordinates|municipality|district|state|country|foreign|unresolved
    confidence: float | None = None
    lat: float | None = None
    lon: float | None = None
    point_origin: str | None = None
    gebietsstand: date | None = None
    nationwide: bool = False


def _candidates(db: Session, name_norm: str) -> list[dict[str, Any]]:
    rows = db.execute(
        sql("SELECT name, kind, ags, kreis_key, state_key, postal_code, population, lat, lon, gebietsstand "
            "FROM geo_place WHERE country='DE' AND name_norm = :n"),
        {"n": name_norm},
    ).mappings().all()
    return [dict(r) for r in rows]


# Amtliche Namenszusätze, hinter denen ein Kurzname stehen kann: „Frankfurt am Main“, „Halle (Saale)“,
# „Salzwedel, Hansestadt“, „Mühlhausen/Thüringen“ …
_QUALIFIER = re.compile(r"^\s*(?:\(|,|/|\s(?:am|an|a\.|im|in|i\.|ob|bei|b\.|vor|v\.|auf|unter|über)\b)", re.I)


def _alias_candidates(db: Session, locality: str) -> list[dict[str, Any]]:
    """Gemeinden, deren amtlicher Name aus dem angegebenen Kurznamen plus Namenszusatz besteht."""
    short = locality.strip()
    base = fold(short)
    if len(base) < 4:
        return []
    rows = db.execute(
        sql("SELECT name, kind, ags, kreis_key, state_key, postal_code, population, lat, lon, gebietsstand "
            "FROM geo_place WHERE country='DE' AND kind = 'municipality' AND name_norm LIKE :p LIMIT 200"),
        {"p": base.replace("%", "").replace("_", " ") + " %"},
    ).mappings().all()
    out = []
    for r in rows:
        name = r["name"] or ""
        if name.lower().startswith(short.lower()) and _QUALIFIER.match(name[len(short):]):
            out.append(dict(r))
    return out


def _name_variants(locality: str) -> list[str]:
    base = fold(locality)
    variants = [base]
    stripped = _SUFFIX.sub("", base).strip()
    if stripped and stripped not in variants:
        variants.append(stripped)
    for v in list(variants):
        p = _PREFIX.sub("", v).strip()
        if p and p not in variants:
            variants.append(p)
    for v in list(variants):
        # „Berlin Mitte“, „Taunusstein Hahn“: Ortsteil abtrennen (nur als nachrangige Variante)
        if " " in v:
            first = v.split(" ")[0]
            if len(first) >= 4 and first not in variants:
                variants.append(first)
    return variants


def _plz_score(plz: str | None, cand_plz: str | None) -> int:
    if not plz or not cand_plz:
        return 0
    n = 0
    for a, b in zip(plz, cand_plz, strict=False):
        if a != b:
            break
        n += 1
    return n


class GeoMatcher:
    """Hält kleine Caches je Lauf; alle Daten kommen aus den lokal importierten Referenztabellen."""

    def __init__(self, db: Session):
        self.db = db
        self._cache: dict[tuple[Any, ...], GeoMatch] = {}
        self._have_regions: bool | None = None

    def _regions_loaded(self) -> bool:
        if self._have_regions is None:
            self._have_regions = bool(self.db.execute(sql("SELECT 1 FROM region WHERE level='district' AND is_current LIMIT 1")).first())
        return self._have_regions

    def _by_point(self, lat: float, lon: float) -> GeoMatch | None:
        row = self.db.execute(
            sql("SELECT key, parent_key, gebietsstand FROM region WHERE level='district' AND is_current "
                "AND ST_Contains(geom, ST_SetSRID(ST_MakePoint(:lon,:lat),4326)) LIMIT 1"),
            {"lat": lat, "lon": lon},
        ).first()
        if not row:
            return None
        return GeoMatch(kreis_key=row[0], state_key=row[1] or row[0][:2], method="source_coordinates", precision="coordinates",
                        confidence=0.97, lat=lat, lon=lon, point_origin="source", gebietsstand=row[2])

    def _by_plz(self, plz: str) -> list[dict[str, Any]]:
        rows = self.db.execute(sql("SELECT DISTINCT kreis_key, ags FROM postal_code WHERE country='DE' AND plz=:p"), {"p": plz}).mappings().all()
        return [dict(r) for r in rows]

    def match(self, loc: RawLocation) -> GeoMatch:
        key = (loc.locality, loc.postal_code, loc.region, loc.country, loc.lat, loc.lon)
        if key not in self._cache:
            self._cache[key] = self._match(loc)
        return self._cache[key]

    def _match(self, loc: RawLocation) -> GeoMatch:
        country = (loc.country or "").upper() or None
        if country and country != "DE" and (country in FOREIGN_COUNTRIES or len(country) == 2):
            return GeoMatch(method="country_field", precision="foreign", confidence=0.9)
        state_hint = STATE_NAMES.get(fold(loc.region)) if loc.region else None
        plz = loc.postal_code if loc.postal_code and re.fullmatch(r"\d{5}", loc.postal_code) else None
        if not self._regions_loaded():
            return GeoMatch(method="no_reference_data", state_key=state_hint)
        # 1) Koordinaten der Quelle
        if loc.lat is not None and loc.lon is not None:
            hit = self._by_point(loc.lat, loc.lon)
            if hit:
                return hit
        name = loc.locality or ""
        folded = fold(name)
        if folded and NATIONWIDE.match(folded):
            return GeoMatch(method="nationwide_term", precision="country", nationwide=True, confidence=0.9)
        # 2) Ortsname
        variants = _name_variants(name) if name else []
        for i, variant in enumerate(variants):
            cands = _candidates(self.db, variant)
            alias = False
            if i == 0 and (not cands or len({c["kreis_key"] for c in cands}) > 1):
                # kein oder kein eindeutiger exakter Treffer: Kurznamen amtlicher Namen mit Zusatz einbeziehen
                # („Frankfurt“ → „Frankfurt am Main“, „Langenfeld“ → auch „Langenfeld (Rheinland)“); PLZ/Land entscheiden.
                extra = [c for c in _alias_candidates(self.db, name) if c["ags"] not in {x["ags"] for x in cands}]
                alias = bool(extra)
                cands = cands + extra
            if not cands:
                continue
            if state_hint:
                narrowed = [c for c in cands if c["state_key"] == state_hint]
                cands = narrowed or cands
            chosen: dict[str, Any] | None = None
            method = "place_name"
            kreise = {c["kreis_key"] for c in cands}
            if len(kreise) == 1:
                chosen = max(cands, key=lambda c: (c["kind"] == "municipality", c["population"] or 0))
            elif plz:
                plz_kreise = {r["kreis_key"] for r in self._by_plz(plz)}
                inter = [c for c in cands if c["kreis_key"] in plz_kreise]
                if len({c["kreis_key"] for c in inter}) == 1:
                    chosen, method = inter[0], "place_name+plz"
                else:
                    scored = sorted(((_plz_score(plz, c["postal_code"]), c) for c in cands), key=lambda t: -t[0])
                    if scored[0][0] >= 2 and (len(scored) == 1 or scored[0][0] > scored[1][0]):
                        chosen, method = scored[0][1], "place_name+plz_prefix"
            if chosen is None:
                # eindeutig dominierende Großstadt (z. B. „Frankfurt“, „München“) – nur mit deutlichem Abstand
                ranked = sorted(cands, key=lambda c: -(c["population"] or 0))
                if (ranked[0]["population"] or 0) >= 100_000 and (ranked[0]["population"] or 0) >= 20 * max(1, ranked[1]["population"] or 0):
                    chosen, method = ranked[0], "place_name_dominant"
            if chosen is None:
                return GeoMatch(method="ambiguous_name", state_key=state_hint, confidence=0.0)
            conf = {"place_name": 0.9, "place_name+plz": 0.93, "place_name+plz_prefix": 0.85, "place_name_dominant": 0.7}[method]
            via_alias = alias and fold(chosen["name"]) != variant
            if i > 0 or via_alias:
                conf -= 0.1  # nur über eine verkürzte Namensvariante bzw. einen Kurznamen gefunden
            if via_alias:
                method += "+short_name"
            precision = "district" if chosen["kind"] == "district" else "municipality"
            lat = float(chosen["lat"]) if chosen["lat"] is not None else None
            lon = float(chosen["lon"]) if chosen["lon"] is not None else None
            return GeoMatch(kreis_key=chosen["kreis_key"], state_key=chosen["state_key"], ags=chosen["ags"], method=method,
                            precision=precision, confidence=round(conf, 3), lat=lat, lon=lon,
                            point_origin="place_centroid" if lat is not None else None, gebietsstand=chosen["gebietsstand"])
        # 3) nur PLZ
        if plz:
            rows = self._by_plz(plz)
            kreise = {r["kreis_key"] for r in rows}
            if len(kreise) == 1:
                k = next(iter(kreise))
                return GeoMatch(kreis_key=k, state_key=k[:2], method="plz_unique", precision="district", confidence=0.85)
            if len(kreise) > 1:
                return GeoMatch(method="ambiguous_plz", state_key=state_hint, confidence=0.0)
        # 4) Bundesland als Ortsangabe
        st = STATE_NAMES.get(folded) or state_hint
        if st:
            return GeoMatch(state_key=st, method="state_name", precision="state", confidence=0.8)
        return GeoMatch(method="unknown_place")


def summarize_geo(matches: list[GeoMatch], remote_type: str | None) -> dict[str, Any]:
    """Leitet die Zählklasse einer Anzeige aus ihren Arbeitsorten ab (siehe Methodik, Zählregeln)."""
    domestic = [m for m in matches if m.precision != "foreign"]
    specific = [m for m in domestic if not m.nationwide]
    kreise = sorted({m.kreis_key for m in specific if m.kreis_key})
    states = sorted({m.state_key for m in specific if m.state_key})
    unresolved = sum(1 for m in specific if not m.kreis_key)
    if not matches:
        geo_class = "remote_nationwide" if remote_type == "remote" else "none"
    elif not domestic:
        geo_class = "foreign"
    elif not specific:
        # nur „bundesweit/Deutschland“: als deutschlandweites Remote-Angebot nur, wenn remote belegt ist
        geo_class = "remote_nationwide" if remote_type == "remote" else "unresolved"
    elif kreise and unresolved == 0:
        geo_class = "resolved"
    elif kreise:
        geo_class = "partial"
    else:
        geo_class = "unresolved"
    return {"kreis_keys": kreise, "state_keys": states, "loc_total": len(specific), "loc_unresolved": unresolved, "geo_class": geo_class}
