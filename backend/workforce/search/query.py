"""Suche und gemeinsame Bezugsbasis für Liste, Karte, Summen und Diagramme.

Alle Auswertungen bauen auf derselben Auswahl auf (``snapshot``): zusammengeführte Anzeigen im
beobachteten Bestand – aktuell oder zu einem Stichtag – mit den Merkmalen der damals gültigen Version.
Dadurch wirken Filter überall identisch.

Freitext: Phrasen in Anführungszeichen, UND/ODER (auch AND/OR), Ausschluss mit ``-`` oder NICHT,
Klammern, Präfixsuche mit ``*``. Umlaute und Bezeichnungen wie C++, C#, .NET werden gefaltet.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import date
from typing import Any

from ..models import IN_STOCK
from ..normalize.text import fold

KIND_GROUPS: dict[str, list[str] | None] = {
    "jobs": ["job", "trainee", "werkstudent", "minijob", "abschlussarbeit"],
    "ausbildung": ["ausbildung", "duales_studium"],
    "praktikum": ["praktikum"],
    "all": None,
}
SORTS = {
    "first_seen": "mp.first_seen_date DESC, mp.id DESC",
    "date_posted": "pv.date_posted DESC NULLS LAST, mp.id DESC",
    "title": "pv.title_norm ASC, mp.id ASC",
    "employer": "pv.employer_norm ASC NULLS LAST, mp.id ASC",
    "apply_until": "pv.apply_until ASC NULLS LAST, mp.id ASC",
    "last_seen": "mp.last_seen_date DESC, mp.id DESC",
}
# Lokale Synonyme für die Suche (Abfrageerweiterung, nachvollziehbar und ohne externen Dienst)
SYNONYMS: dict[str, list[str]] = {
    "krankenschwester": ["pflegefachkraft", "pflegefachfrau", "pflegefachmann", "krankenpfleger"],
    "krankenpfleger": ["pflegefachkraft", "pflegefachmann", "krankenschwester"],
    "pflegefachkraft": ["pflegefachfrau", "pflegefachmann", "krankenpfleger", "altenpfleger"],
    "softwareentwickler": ["software developer", "software engineer", "programmierer", "softwareingenieur", "anwendungsentwickler"],
    "programmierer": ["softwareentwickler", "software developer", "entwickler"],
    "entwickler": ["developer"],
    "developer": ["entwickler"],
    "admin": ["administrator", "systemadministrator"],
    "systemadministrator": ["administrator", "sysadmin", "it administrator"],
    "azubi": ["auszubildende", "ausbildung"],
    "sekretaerin": ["assistenz", "sekretariat", "bueroassistenz"],
    "sachbearbeiter": ["sachbearbeitung", "sachbearbeiterin"],
    "erzieher": ["erzieherin", "paedagogische fachkraft"],
    "lkw fahrer": ["berufskraftfahrer", "kraftfahrer"],
    "ingenieur": ["ingenieurin", "engineer"],
    "jurist": ["volljurist", "juristin", "rechtsanwalt"],
    "buchhalter": ["buchhalterin", "finanzbuchhalter", "bilanzbuchhalter"],
    "hausmeister": ["haustechniker", "facility manager"],
    "it": ["edv", "informatik"],
    "ki": ["kuenstliche intelligenz", "machine learning"],
}


class QueryError(ValueError):
    pass


_TOKEN = re.compile(r'"([^"]*)"|(\()|(\))|([^\s()"]+)')


def _lexeme(term: str, prefix: bool = False) -> str | None:
    words = fold(term).split()
    if not words:
        return None
    if prefix:
        words[-1] += ":*"
    return "(" + " <-> ".join(words) + ")" if len(words) > 1 else words[0]


def _term(raw: str, expand: bool = True) -> str | None:
    prefix = raw.endswith("*") and len(raw) > 2
    base = _lexeme(raw.rstrip("*"), prefix)
    if base is None:
        return None
    key = fold(raw.rstrip("*"))
    alts = [base]
    if expand and not prefix:
        for syn in SYNONYMS.get(key, []):
            lx = _lexeme(syn)
            if lx and lx not in alts:
                alts.append(lx)
    return "(" + " | ".join(alts) + ")" if len(alts) > 1 else base


def parse_query(q: str | None, *, expand_synonyms: bool = True) -> str | None:
    """Wandelt die Sucheingabe in einen tsquery-Ausdruck (nur a–z, 0–9 und Operatoren)."""
    if not q or not q.strip():
        return None
    tokens: list[tuple[str, str]] = []
    for m in _TOKEN.finditer(q.strip()):
        if m.group(1) is not None:
            tokens.append(("PHRASE", m.group(1)))
        elif m.group(2):
            tokens.append(("LP", "("))
        elif m.group(3):
            tokens.append(("RP", ")"))
        else:
            w = m.group(4)
            up = w.upper()
            if up in ("AND", "UND", "&", "&&"):
                tokens.append(("AND", w))
            elif up in ("OR", "ODER", "|", "||"):
                tokens.append(("OR", w))
            elif up in ("NOT", "NICHT"):
                tokens.append(("NOT", w))
            elif w.startswith("-") and len(w) > 1:
                tokens.append(("NOT", "-"))
                tokens.append(("TERM", w[1:]))
            else:
                tokens.append(("TERM", w))
    pos = 0
    neg_depth = 0
    positives = 0

    def peek() -> str | None:
        return tokens[pos][0] if pos < len(tokens) else None

    def unary() -> str | None:
        nonlocal pos, neg_depth, positives
        kind = peek()
        if kind is None:
            return None
        if kind == "NOT":
            pos += 1
            neg_depth += 1
            inner = unary()
            neg_depth -= 1
            return f"!{inner}" if inner else None
        if kind == "LP":
            pos += 1
            inner = or_expr()
            if peek() == "RP":
                pos += 1
            return f"({inner})" if inner else None
        if kind in ("PHRASE", "TERM"):
            val = tokens[pos][1]
            pos += 1
            lex = _lexeme(val) if kind == "PHRASE" else _term(val, expand_synonyms)
            if lex and neg_depth == 0:
                positives += 1
            return lex
        pos += 1  # verwaister Operator / schließende Klammer
        return None

    def and_expr() -> str | None:
        nonlocal pos
        parts: list[str] = []
        while peek() not in (None, "OR", "RP"):
            if peek() == "AND":
                pos += 1
                continue
            u = unary()
            if u:
                parts.append(u)
        return " & ".join(parts) if parts else None

    def or_expr() -> str | None:
        nonlocal pos
        parts: list[str] = []
        first = and_expr()
        if first:
            parts.append(first)
        while peek() == "OR":
            pos += 1
            nxt = and_expr()
            if nxt:
                parts.append(nxt)
        if not parts:
            return None
        return " | ".join(f"({p})" if " & " in p and len(parts) > 1 else p for p in parts)

    out = or_expr()
    if out and positives == 0:
        raise QueryError("Eine Suche nur aus Ausschlüssen ist nicht möglich – bitte mindestens einen Suchbegriff angeben.")
    return out


@dataclass
class Filters:
    q: str | None = None
    fuzzy: bool = False
    kldb: list[str] = field(default_factory=list)  # Codes oder Präfixe (Berufsgruppen)
    features: list[str] = field(default_factory=list)
    features_mode: str = "and"
    features_required_only: bool = False
    states: list[str] = field(default_factory=list)
    kreise: list[str] = field(default_factory=list)
    near: tuple[float, float] | None = None  # (lat, lon) – angenäherter Ortsmittelpunkt
    radius_km: float | None = None
    near_info: dict[str, Any] | None = None
    date_from: date | None = None
    date_to: date | None = None
    date_field: str = "first_seen"  # first_seen | date_posted
    statuses: list[str] = field(default_factory=lambda: list(IN_STOCK))
    sources: list[int] = field(default_factory=list)
    kind_group: str = "jobs"
    remote: list[str] = field(default_factory=list)
    working_time: list[str] = field(default_factory=list)
    contract_term: str | None = None
    geo_classes: list[str] = field(default_factory=list)
    employer: str | None = None
    as_of: date | None = None
    include_synthetic: bool = False

    def describe_scope(self) -> dict[str, Any]:
        """Für die Oberfläche: worauf sich Suche und Zahlen beziehen."""
        return {
            "searched_fields": ["Titel", "Arbeitgeber", "Berufsangabe/Berufsklasse", "gespeicherte Merkmale (Qualifikationen, Kenntnisse)", "Arbeitsorte"],
            "not_searched": "Der Volltext der Anzeigen wird nicht gespeichert und daher nicht durchsucht.",
            "basis": f"Bestand am {self.as_of:%d.%m.%Y}" if self.as_of else "aktuell beobachteter Bestand" if set(self.statuses) <= set(IN_STOCK) else "Anzeigen im gewählten Status",
            "kind_group": self.kind_group,
        }


def build_where(f: Filters, *, ignore_kreise: bool = False, ignore_dates: bool = False) -> tuple[str, dict[str, Any]]:
    """Liefert ``FROM … WHERE …`` (Aliasse ``mp``, ``pv``) und Parameter für die gemeinsame Bezugsbasis."""
    p: dict[str, Any] = {}
    cond: list[str] = []
    if f.as_of is None:
        frm = "FROM merged_posting mp JOIN posting_version pv ON pv.id = mp.current_version_id"
        cond.append("mp.status = ANY(:statuses)")
        p["statuses"] = list(f.statuses) or list(IN_STOCK)
        if f.sources:
            cond.append("EXISTS (SELECT 1 FROM source_posting sp WHERE sp.merged_posting_id = mp.id AND sp.source_id = ANY(:sources) AND sp.status = ANY(:statuses))")
            p["sources"] = list(f.sources)
    else:
        frm = ("FROM merged_posting mp JOIN posting_version pv ON pv.source_posting_id = mp.primary_source_posting_id "
               "AND pv.valid_from <= :as_of AND (pv.valid_to IS NULL OR pv.valid_to > :as_of)")
        p["as_of"] = f.as_of
        src = ""
        if f.sources:
            src = " AND sp.source_id = ANY(:sources)"
            p["sources"] = list(f.sources)
        cond.append("EXISTS (SELECT 1 FROM source_posting sp JOIN activity_period ap ON ap.source_posting_id = sp.id "
                    f"WHERE sp.merged_posting_id = mp.id AND ap.start_date <= :as_of AND (ap.end_date IS NULL OR ap.end_date >= :as_of){src})")
    if not f.include_synthetic:
        cond.append("NOT mp.is_synthetic")
    tsq = parse_query(f.q)
    if tsq:
        p["tsq"] = tsq
        text_cond = "pv.tsv @@ (to_tsquery('simple', :tsq) || to_tsquery('german', :tsq))"
        if f.fuzzy:
            p["qfold"] = fold(re.sub(r'["()*]|\b(?:AND|OR|NOT|UND|ODER|NICHT)\b', " ", f.q or ""))
            if p["qfold"]:
                text_cond = f"({text_cond} OR :qfold <% pv.search_a OR :qfold <% pv.search_b)"
        cond.append(text_cond)
    kinds = KIND_GROUPS.get(f.kind_group, KIND_GROUPS["jobs"])
    if kinds is not None:
        cond.append("pv.kind = ANY(:kinds)")
        p["kinds"] = kinds
    if f.kldb:
        cond.append("pv.kldb_code LIKE ANY(:kldb)")
        p["kldb"] = [re.sub(r"[^0-9]", "", c) + "%" for c in f.kldb if re.sub(r"[^0-9]", "", c)]
    if f.features:
        col = "pv.feature_required_keys" if f.features_required_only else "pv.feature_keys"
        cond.append(f"{col} {'&&' if f.features_mode == 'or' else '@>'} CAST(:features AS text[])")
        p["features"] = list(f.features)
    if f.states:
        cond.append("pv.state_keys && CAST(:states AS text[])")
        p["states"] = list(f.states)
    if f.kreise and not ignore_kreise:
        cond.append("pv.kreis_keys && CAST(:kreise AS text[])")
        p["kreise"] = list(f.kreise)
    if f.near and f.radius_km:
        cond.append("EXISTS (SELECT 1 FROM posting_location pl WHERE pl.version_id = pv.id AND pl.point IS NOT NULL AND "
                    "ST_DWithin(pl.point::geography, ST_SetSRID(ST_MakePoint(:near_lon, :near_lat), 4326)::geography, :radius_m))")
        p.update(near_lat=f.near[0], near_lon=f.near[1], radius_m=float(f.radius_km) * 1000.0)
    if not ignore_dates:
        col = "pv.date_posted" if f.date_field == "date_posted" else "mp.first_seen_date"
        if f.date_from:
            cond.append(f"{col} >= :date_from")
            p["date_from"] = f.date_from
        if f.date_to:
            cond.append(f"{col} <= :date_to")
            p["date_to"] = f.date_to
    if f.remote:
        cond.append("coalesce(pv.remote_type, 'unknown') = ANY(:remote)")
        p["remote"] = list(f.remote)
    if f.working_time:
        cond.append("pv.working_time && CAST(:working_time AS text[])")
        p["working_time"] = list(f.working_time)
    if f.contract_term:
        cond.append("pv.contract_term = :contract_term")
        p["contract_term"] = f.contract_term
    if f.geo_classes:
        cond.append("pv.geo_class = ANY(:geo_classes)")
        p["geo_classes"] = list(f.geo_classes)
    if f.employer:
        cond.append("pv.employer_norm = :employer_norm")
        from ..normalize.text import normalize_employer

        p["employer_norm"] = normalize_employer(f.employer)
    return f"{frm} WHERE {' AND '.join(cond)}", p


def order_clause(f: Filters, sort: str | None) -> str:
    if (sort in (None, "relevance")) and parse_query(f.q):
        return "ts_rank_cd(pv.tsv, to_tsquery('simple', :tsq) || to_tsquery('german', :tsq)) DESC, mp.first_seen_date DESC, mp.id DESC"
    return SORTS.get(sort or "first_seen", SORTS["first_seen"])
