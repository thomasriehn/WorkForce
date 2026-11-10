"""Klassifikation der Berufe 2010 – überarbeitete Fassung 2020 (Bundesagentur für Arbeit).

Zwei Arbeitsmappen, die einzeln importiert werden:

* Systematisches Verzeichnis → ``kldb_class`` (alle Ebenen, 1- bis 5-Steller, Langbezeichnungen).
* Alphabetisches Verzeichnis der Berufsbenennungen → ``occupation_title`` (Benennung → 5-Steller).

Welche der beiden Dateien vorliegt, wird an den Tabellenblättern erkannt. Der „Berichtszeitraum“ des Datenstands
ist das Erstellungsdatum laut Datei (z. B. ``alphabet-2026-01-20``).
"""
from __future__ import annotations

import re
from collections import Counter
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path
from typing import Any

from sqlalchemy import delete, select
from sqlalchemy import text as sql
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import Session

from ..models import KldbClass, OccupationTitle, StatRelease
from ..normalize.text import normalize_title
from .common import (
    KLDB_VERSION,
    FileContext,
    ImportProblem,
    ParsedRelease,
    as_date,
    find_release,
    fmt_date,
    is_xlsx,
    open_workbook,
    store_release,
    summarize,
)

DATASET_KEY = "kldb2010"
ORIGIN = "kldb_alphabetisch"
SHEET_SYSTEMATIK = "Systematik_Langbezeichnungen"
SHEET_ALPHABET = "alphabet_Verz_Berufsb"
MIN_CLASSES_5 = 1000   # Plausibilitätsgrenzen (Fassung 2020: 1.300 Berufsgattungen, rund 18.900 Benennungen)
MIN_TITLES = 5000
_FOOTER = ("Erstellungsdatum", "©", "Quelle")
_VERSION_TITLE = re.compile(r"Klassifikation der Berufe 2010\s*[–-]\s*überarbeitete Fassung 2020")


@dataclass
class ParsedKldb:
    kind: str  # systematik | alphabet
    created: date
    classes: list[tuple[str, int, str]] = field(default_factory=list)  # (code, level, name)
    titles: list[tuple[str, str, str]] = field(default_factory=list)   # (title, title_norm, code)
    info: dict[str, Any] = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)


def _created(wb: Any, what: str) -> date:
    """Erstellungsdatum aus dem Impressum, ersatzweise aus der Fußzeile des Datenblatts."""
    if "Impressum" in wb.sheetnames:
        for row in wb["Impressum"].iter_rows(min_row=1, max_row=40, max_col=6, values_only=True):
            if isinstance(row[0], str) and row[0].strip().startswith("Erstellungsdatum"):
                d = as_date(next((c for c in row[1:] if c is not None), None))
                if d:
                    return d
    raise ImportProblem(f"{what}: Erstellungsdatum im Blatt „Impressum“ nicht gefunden.")


def _check_version(sheet: Any, what: str) -> None:
    texts = [str(c) for row in sheet.iter_rows(min_row=1, max_row=4, max_col=4, values_only=True) for c in row if isinstance(c, str)]
    if not any(_VERSION_TITLE.search(t) for t in texts):
        raise ImportProblem(f"{what}: Die Datei weist sich nicht als „Klassifikation der Berufe 2010 – überarbeitete "
                            "Fassung 2020“ aus. Andere Fassungen werden nicht unterstützt.")


def parse(path: Path, name: str) -> ParsedKldb:
    if not is_xlsx(path):
        raise ImportProblem("Für die KldB 2010 wird die Excel-Arbeitsmappe (.xlsx) des systematischen oder des "
                            "alphabetischen Verzeichnisses benötigt.")
    with open_workbook(path) as wb:
        if SHEET_SYSTEMATIK in wb.sheetnames:
            return _parse_systematik(wb)
        if SHEET_ALPHABET in wb.sheetnames:
            return _parse_alphabet(wb)
        raise ImportProblem("Weder das Blatt „Systematik_Langbezeichnungen“ (systematisches Verzeichnis) noch "
                            "„alphabet_Verz_Berufsb“ (alphabetisches Verzeichnis) gefunden.")


def _parse_systematik(wb: Any) -> ParsedKldb:
    what = "KldB 2010, systematisches Verzeichnis"
    ws = wb[SHEET_SYSTEMATIK]
    _check_version(ws, what)
    out = ParsedKldb(kind="systematik", created=_created(wb, what))
    in_data = False
    seen: set[str] = set()
    for row in ws.iter_rows(max_col=3, values_only=True):
        a, b, c = (list(row) + [None, None, None])[:3]
        if not in_data:
            if isinstance(a, str) and a.strip() == "KldB 2010" and isinstance(b, str) and b.strip().startswith("Langbezeichnungen"):
                in_data = True
            continue
        if a is None and b is None:
            continue
        code = str(a).strip() if a is not None else ""
        if code.startswith(_FOOTER):
            break
        if not (code.isdigit() and 1 <= len(code) <= 5):
            raise ImportProblem(f"{what}: Unerwarteter Schlüssel {a!r}.")
        if not isinstance(b, str) or not b.strip():
            raise ImportProblem(f"{what}: Bezeichnung zu Schlüssel {code} fehlt.")
        if isinstance(c, str) and c.strip().startswith("KldB2010_") and c.strip() != f"KldB2010_{len(code)}":
            raise ImportProblem(f"{what}: Ebene {c!r} passt nicht zur Stellenzahl des Schlüssels {code}.")
        if code in seen:
            raise ImportProblem(f"{what}: Schlüssel {code} kommt mehrfach vor.")
        seen.add(code)
        out.classes.append((code, len(code), b.strip()))
    if not in_data:
        raise ImportProblem(f"{what}: Kopfzeile „KldB 2010 | Langbezeichnungen …“ nicht gefunden.")
    levels = Counter(lv for _, lv, _ in out.classes)
    if levels[1] != 10 or levels[5] < MIN_CLASSES_5:
        raise ImportProblem(f"{what}: Unplausible Anzahl an Positionen je Ebene {dict(sorted(levels.items()))} "
                            "(erwartet: 10 Berufsbereiche und rund 1.300 Berufsgattungen).")
    orphans = [code for code, lv, _ in out.classes if lv > 1 and code[:-1] not in seen]
    if orphans:
        raise ImportProblem(f"{what}: Zu {len(orphans)} Schlüsseln fehlt die übergeordnete Position (z. B. {orphans[0]}).")
    out.info = {"kind": "systematik", "levels": {str(k): v for k, v in sorted(levels.items())}}
    return out


def _parse_alphabet(wb: Any) -> ParsedKldb:
    what = "KldB 2010, alphabetisches Verzeichnis"
    ws = wb[SHEET_ALPHABET]
    _check_version(ws, what)
    out = ParsedKldb(kind="alphabet", created=_created(wb, what))
    in_data = False
    seen: set[tuple[str, str]] = set()
    dupes = empty_norm = 0
    for row in ws.iter_rows(max_col=2, values_only=True):
        a, b = (list(row) + [None, None])[:2]
        if not in_data:
            if isinstance(a, str) and a.strip() == "Berufsbenennungen" and isinstance(b, str) and b.strip().startswith("KldB 2010"):
                in_data = True
            continue
        if a is None and b is None:
            continue
        title = str(a).strip() if a is not None else ""
        if title.startswith(_FOOTER) and (b is None or not str(b).strip().isdigit()):
            break
        code = str(b).strip() if b is not None else ""
        if not title or not (code.isdigit() and len(code) == 5):
            raise ImportProblem(f"{what}: Unerwartete Zeile {title[:50]!r} / {b!r} (erwartet: Benennung und 5-stelliger Schlüssel).")
        norm = normalize_title(title)
        if not norm:
            empty_norm += 1
            continue
        if (norm, code) in seen:
            dupes += 1
            continue
        seen.add((norm, code))
        out.titles.append((title, norm, code))
    if not in_data:
        raise ImportProblem(f"{what}: Kopfzeile „Berufsbenennungen | KldB 2010 (5-Steller)“ nicht gefunden.")
    if len(out.titles) < MIN_TITLES:
        raise ImportProblem(f"{what}: Nur {len(out.titles)} Berufsbenennungen gefunden (erwartet: rund 18.900). "
                            "Es wurde nichts importiert.")
    out.info = {"kind": "alphabet", "titles": len(out.titles), "duplicate_rows_skipped": dupes,
                "rows_without_normalized_title": empty_norm,
                "ambiguous_titles": sum(1 for n in Counter(t[1] for t in out.titles).values() if n > 1)}
    return out


def apply(db: Session, parsed: ParsedKldb, ctx: FileContext) -> dict[str, Any]:
    period_key = f"{parsed.kind}-{parsed.created.isoformat()}"
    release = ParsedRelease(
        period_key=period_key, period_end=parsed.created, period_start=None,
        row_count=len(parsed.classes) if parsed.kind == "systematik" else len(parsed.titles),
        notes=[(f"{'Systematisches' if parsed.kind == 'systematik' else 'Alphabetisches'} Verzeichnis, "
                f"Erstellungsdatum laut Datei: {fmt_date(parsed.created)}"), KLDB_VERSION])
    if find_release(db, DATASET_KEY, period_key, ctx.sha256) is None:
        newer = db.execute(select(StatRelease).where(
            StatRelease.dataset_key == DATASET_KEY, StatRelease.period_key.like(f"{parsed.kind}-%"),
            StatRelease.period_end > parsed.created).limit(1)).scalar_one_or_none()
        if newer is not None:
            raise ImportProblem(f"Es ist bereits ein neuerer Stand dieses Verzeichnisses importiert "
                                f"({fmt_date(newer.period_end)}); die ältere Datei vom {fmt_date(parsed.created)} wird nicht übernommen.")
    rel = store_release(db, DATASET_KEY, release, ctx)
    extra: dict[str, Any] = dict(parsed.info)
    warnings = list(parsed.warnings)
    if rel["status"] == "imported":
        if parsed.kind == "systematik":
            rows = [{"code": c, "level": lv, "name": n, "version": KLDB_VERSION} for c, lv, n in parsed.classes]
            for i in range(0, len(rows), 2000):
                stmt = pg_insert(KldbClass).values(rows[i:i + 2000])
                db.execute(stmt.on_conflict_do_update(index_elements=["code"], set_={
                    "level": stmt.excluded.level, "name": stmt.excluded.name, "version": stmt.excluded.version}))
            extra["classes_total"] = db.execute(sql("SELECT count(*) FROM kldb_class")).scalar()
        else:
            existing = {(tn, code): (oid, origin) for oid, tn, code, origin in db.execute(
                select(OccupationTitle.id, OccupationTitle.title_norm, OccupationTitle.kldb_code, OccupationTitle.origin)).all()}
            wanted = {(tn, code) for _, tn, code in parsed.titles}
            new_rows = [{"title": t, "title_norm": tn, "kldb_code": code, "origin": ORIGIN}
                        for t, tn, code in parsed.titles if (tn, code) not in existing]
            stale = [oid for key, (oid, origin) in existing.items() if origin == ORIGIN and key not in wanted]
            for i in range(0, len(stale), 5000):
                db.execute(delete(OccupationTitle).where(OccupationTitle.id.in_(stale[i:i + 5000])))
            for i in range(0, len(new_rows), 5000):
                db.execute(pg_insert(OccupationTitle).values(new_rows[i:i + 5000]).on_conflict_do_nothing(
                    index_elements=["title_norm", "kldb_code"]))
            extra.update(titles_added=len(new_rows), titles_removed=len(stale))
            known = set(db.execute(select(KldbClass.code).where(KldbClass.level == 5)).scalars().all())
            if known:
                unknown = sorted({code for _, _, code in parsed.titles} - known)
                extra["unknown_kldb_codes"] = unknown[:50]
                if unknown:
                    warnings.append(f"{len(unknown)} Schlüssel des alphabetischen Verzeichnisses fehlen in der geladenen Systematik.")
            else:
                warnings.append("Systematisches Verzeichnis ist noch nicht geladen – Schlüssel wurden nicht gegengeprüft.")
    out = summarize(DATASET_KEY, ctx, [rel], **extra)
    out["warnings"] = warnings
    return out

