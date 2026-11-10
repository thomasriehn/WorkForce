"""Zuordnung von Berufsangaben zur KldB 2010 (überarbeitete Fassung 2020) – lokal und nachvollziehbar.

Quelle der Zuordnung wird gespeichert (``portal_field`` | ``title_exact`` | ``title_fuzzy``) samt Konfidenz.
Unsichere Zuordnungen bleiben als solche sichtbar. Die KldB-Zuordnung belegt **keinen** ausdrücklich
verlangten Abschluss; das Anforderungsniveau (5. Stelle) wird getrennt ausgewiesen.
"""
from __future__ import annotations

import re
from dataclasses import dataclass

from sqlalchemy import text as sql
from sqlalchemy.orm import Session

from .text import normalize_title

_SPLIT = re.compile(r"\s+(?:fuer|im|in der|in|bei|am|als|mit|zur|zum|fur)\s+|\s+-\s+|\s*[|,(]\s*")
_NOISE = re.compile(r"\b(?:senior|junior|lead|leitende[rn]?|stellvertretende[rn]?|stv|teamleiter|teamleitung|mitarbeiter|mitarbeitende[rn]?|in vollzeit|in teilzeit|vollzeit|teilzeit|ab sofort|befristet|unbefristet|\d{4})\b")


@dataclass
class OccupationMatch:
    code: str
    name: str | None
    source: str
    confidence: float

    @property
    def requirement_level(self) -> int | None:
        return int(self.code[4]) if len(self.code) == 5 and self.code[4] in "1234" else None


class OccupationClassifier:
    FUZZY_MIN = 0.62

    def __init__(self, db: Session):
        self.db = db
        self._cache: dict[tuple[str, str], OccupationMatch | None] = {}
        self._available: bool | None = None

    def available(self) -> bool:
        if self._available is None:
            self._available = bool(self.db.execute(sql("SELECT 1 FROM occupation_title LIMIT 1")).first())
        return self._available

    def _exact(self, norm: str) -> tuple[str, str | None, int] | None:
        rows = self.db.execute(
            sql("SELECT ot.kldb_code, k.name, count(*) OVER () FROM occupation_title ot LEFT JOIN kldb_class k ON k.code = ot.kldb_code "
                "WHERE ot.title_norm = :n ORDER BY (ot.origin = 'synonym_local') DESC, ot.kldb_code LIMIT 1"), {"n": norm}).first()
        return (rows[0], rows[1], rows[2]) if rows else None

    def _fuzzy(self, norm: str) -> tuple[str, str | None, float] | None:
        row = self.db.execute(
            sql("SELECT ot.kldb_code, k.name, similarity(ot.title_norm, :n) AS s FROM occupation_title ot "
                "LEFT JOIN kldb_class k ON k.code = ot.kldb_code WHERE ot.title_norm % :n ORDER BY s DESC, length(ot.title_norm) LIMIT 1"),
            {"n": norm}).first()
        return (row[0], row[1], float(row[2])) if row else None

    def classify(self, label: str | None, title: str | None) -> OccupationMatch | None:
        if not self.available():
            return None
        key = (label or "", title or "")
        if key not in self._cache:
            self._cache[key] = self._classify(label, title)
        return self._cache[key]

    def _classify(self, label: str | None, title: str | None) -> OccupationMatch | None:
        if label:
            hit = self._exact(normalize_title(label))
            if hit:
                return OccupationMatch(hit[0], hit[1], "portal_field", 0.9 if hit[2] == 1 else 0.75)
        if not title:
            return None
        norm = normalize_title(title)
        variants = [norm]
        head = _SPLIT.split(norm)[0].strip()
        if head and head != norm:
            variants.append(head)
        for v in list(variants):
            cleaned = re.sub(r"\s+", " ", _NOISE.sub(" ", v)).strip()
            if cleaned and cleaned not in variants:
                variants.append(cleaned)
        for i, v in enumerate(variants):
            if len(v) < 4:
                continue
            hit = self._exact(v)
            if hit:
                conf = (0.85 if hit[2] == 1 else 0.7) - 0.05 * i
                return OccupationMatch(hit[0], hit[1], "title_exact", round(conf, 3))
        self.db.execute(sql("SELECT set_limit(CAST(:l AS real))"), {"l": self.FUZZY_MIN})
        for v in variants[-1:] + variants[:1]:
            if len(v) < 6 or len(v) > 80:
                continue
            fz = self._fuzzy(v)
            if fz and fz[2] >= self.FUZZY_MIN:
                return OccupationMatch(fz[0], fz[1], "title_fuzzy", round(min(0.69, fz[2] * 0.75), 3))
        return None
