"""BA-Statistik: „Arbeitslose und Arbeitslosenquoten – Deutschland, Länder, Kreise und Gemeinden (Zeitreihe)“.

Die Monatsausgabe ist ein ZIP mit zwei Arbeitsmappen (Bestand an Arbeitslosen / Arbeitslosenquoten). Importiert wird
aus dem Blatt ``Gesamt`` ausschließlich die Spalte des Berichtsmonats (laut Blatt ``Impressum``) für Deutschland,
die Länder (2-stelliger Schlüssel) und die Kreise (5-stelliger Schlüssel). Regierungsbezirke (3-stellig) und
Gemeinden (8-stellig) werden nicht übernommen. Das Produkt enthält keine Arbeitsuchenden.

Bekannte Falle: Im Blatt ``Übersicht_Kreise`` der Bestandsmappe sind künftige Monate mit 0 gefüllt – deshalb wird
nie eine andere Spalte als die des Berichtsmonats gelesen.
"""
from __future__ import annotations

import re
import tempfile
import zipfile
from collections import Counter
from dataclasses import dataclass, field
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any

from .common import (
    COUNTRY_KEY,
    MARKERS_BA,
    ImportProblem,
    ParsedRelease,
    ValueRow,
    as_date,
    check_unrecognized,
    classify_cell,
    extract_member,
    fmt_date,
    is_xlsx,
    is_zip,
    month_bounds,
    open_workbook,
    require_sheet,
)

DATASET_KEY = "ba_arbeitslose_kreise"
IND_COUNT = "arbeitslose"
IND_RATE = "arbeitslosenquote_alle_zivilen_ep"

_KEY_NAME = re.compile(r"^(\d{2,12})\s+(.+)$")
_MEMBER = re.compile(r"^(\d{6})_Heft_pol_SGBI_(Arbeitslose|ArbeitslosenQuoten)\.xlsx$")
_FOOTER = ("Erstellungsdatum", "©", "Datenstand", "Quelle")
RATE_BASIS = "Arbeitslosenquote bezogen auf alle zivilen Erwerbspersonen"
DISTRICTS_RANGE = (380, 420)  # Plausibilitätsgrenze für die Zahl der Kreise und kreisfreien Städte


@dataclass
class _Book:
    kind: str  # count | rate
    member: str
    month: date
    created: date | None
    next_release: date | None
    gebietsstand_is_datenstand: bool
    rows: list[tuple[str, str, str, Any]] = field(default_factory=list)  # (level, key, name, zelle)
    skipped: Counter[str] = field(default_factory=Counter)


def _impressum(wb: Any, member: str) -> dict[str, Any]:
    ws = require_sheet(wb, "Impressum", f"BA-Kreisdaten ({member})")
    out: dict[str, Any] = {}
    for row in ws.iter_rows(min_row=1, max_row=40, max_col=6, values_only=True):
        label = row[0]
        if isinstance(label, str) and label.strip().endswith(":"):
            value = next((c for c in row[1:] if c is not None), None)
            out[label.strip().rstrip(":").strip()] = value
    return out


def _read_book(path: Path, member: str) -> _Book:
    what = f"BA-Kreisdaten ({member})"
    with open_workbook(path) as wb:
        imp = _impressum(wb, member)
        month = as_date(imp.get("Berichtsmonat"))
        if month is None:
            raise ImportProblem(f"{what}: Berichtsmonat im Blatt „Impressum“ nicht gefunden.")
        ws = require_sheet(wb, "Gesamt", what)
        head: list[tuple[Any, ...]] = []
        book: _Book | None = None
        col: int | None = None
        for row in ws.iter_rows(values_only=True):
            if book is None:
                head.append(row)
                if len(head) > 30:
                    raise ImportProblem(f"{what}: Kopfzeile „Region“ im Blatt „Gesamt“ nicht gefunden.")
                if not (isinstance(row[0], str) and row[0].strip() == "Region"):
                    continue
                if len(head) < 2:
                    raise ImportProblem(f"{what}: Kopf des Blatts „Gesamt“ ist unvollständig.")
                title = str(head[2][0] or "") if len(head) > 2 else ""
                texts = " ".join(str(c) for r in head for c in r if isinstance(c, str))
                if title.startswith("Bestand an Arbeitslosen"):
                    kind = "count"
                elif title.startswith("Arbeitslosenquoten"):
                    kind = "rate"
                    if RATE_BASIS not in texts:
                        raise ImportProblem(f"{what}: Der Hinweis „{RATE_BASIS}“ fehlt – die Bezugsgröße der Quote ist "
                                            "damit nicht belegt.")
                else:
                    raise ImportProblem(f"{what}: Unerwarteter Tabellentitel im Blatt „Gesamt“: {title!r}.")
                if "Rechtskreis Insgesamt" not in texts:
                    raise ImportProblem(f"{what}: Das Blatt „Gesamt“ weist nicht „Rechtskreis Insgesamt“ aus.")
                dates = head[-2]
                cols = [j for j, c in enumerate(dates) if isinstance(c, datetime | date)
                        and (as_date(c).year, as_date(c).month) == (month.year, month.month)]  # type: ignore[union-attr]
                if len(cols) != 1:
                    raise ImportProblem(f"{what}: Spalte des Berichtsmonats {month:%m/%Y} in der Kopfzeile nicht "
                                        f"eindeutig gefunden ({len(cols)} Treffer).")
                col = cols[0]
                book = _Book(kind=kind, member=member, month=date(month.year, month.month, 1),
                             created=as_date(imp.get("Erstellungsdatum")),
                             next_release=as_date(imp.get("Nächster Veröffentlichungstermin")),
                             gebietsstand_is_datenstand="Gebietsstand = Datenstand" in texts)
                continue
            assert col is not None
            a = row[0]
            if a is None:
                continue
            if not isinstance(a, str):
                raise ImportProblem(f"{what}: Unerwarteter Inhalt in der Regionsspalte: {a!r}.")
            label = a.strip()
            cell = row[col] if col < len(row) else None
            if label == "Deutschland":
                book.rows.append(("country", COUNTRY_KEY, label, cell))
                continue
            m = _KEY_NAME.match(label)
            if not m:
                if label.startswith(_FOOTER):
                    break
                raise ImportProblem(f"{what}: Zeile ohne Gebietsschlüssel im Blatt „Gesamt“: {label[:60]!r}.")
            key, name = m.group(1), m.group(2).strip()
            if len(key) == 2:
                book.rows.append(("state", key, name, cell))
            elif len(key) == 5:
                book.rows.append(("district", key, name, cell))
            elif len(key) == 3:
                book.skipped["regierungsbezirk"] += 1
            elif len(key) == 8:
                book.skipped["gemeinde"] += 1
            else:
                raise ImportProblem(f"{what}: Gebietsschlüssel mit unerwarteter Länge: {key!r}.")
    if book is None:
        raise ImportProblem(f"{what}: Kopfzeile „Region“ im Blatt „Gesamt“ nicht gefunden.")
    return book


def _check_counts(book: _Book) -> None:
    levels = Counter(r[0] for r in book.rows)
    what = f"BA-Kreisdaten ({book.member})"
    if levels["country"] != 1:
        raise ImportProblem(f"{what}: Zeile „Deutschland“ {levels['country']}-mal gefunden (erwartet: 1).")
    if levels["state"] != 16:
        raise ImportProblem(f"{what}: {levels['state']} Länderzeilen gefunden (erwartet: 16).")
    if not DISTRICTS_RANGE[0] <= levels["district"] <= DISTRICTS_RANGE[1]:
        raise ImportProblem(f"{what}: {levels['district']} Kreiszeilen gefunden (erwartet: rund 400). "
                            "Es wurde nichts importiert.")
    keys = [(r[0], r[1]) for r in book.rows]
    if len(set(keys)) != len(keys):
        dup = next(k for k, n in Counter(keys).items() if n > 1)
        raise ImportProblem(f"{what}: Gebietsschlüssel {dup[1]} kommt mehrfach vor.")


def parse(path: Path, name: str) -> tuple[ParsedRelease, dict[str, Any], list[str]]:
    """Liest die Monatsausgabe (ZIP mit beiden Arbeitsmappen)."""
    if is_xlsx(path) or not is_zip(path):
        raise ImportProblem(
            "Für diesen Datensatz wird die vollständige ZIP-Datei der Monatsausgabe benötigt (sie enthält die "
            "Arbeitsmappe mit dem Bestand an Arbeitslosen und die Arbeitsmappe mit den Arbeitslosenquoten). "
            "Eine einzelne Arbeitsmappe kann nicht importiert werden, weil Bestand und Quote zum selben Datenstand gehören.")
    books: dict[str, _Book] = {}
    with zipfile.ZipFile(path) as z, tempfile.TemporaryDirectory(prefix="wf-ba-kreise-") as tmp:
        members = [i for i in z.infolist() if not i.is_dir() and i.filename.lower().endswith(".xlsx")]
        if len(members) != 2:
            raise ImportProblem(f"Im ZIP wurden {len(members)} Arbeitsmappen gefunden (erwartet: 2 – Arbeitslose und "
                                "Arbeitslosenquoten).")
        for n, info in enumerate(members):
            member = Path(info.filename).name
            book = _read_book(extract_member(z, info, Path(tmp) / f"mappe{n}.xlsx"), member)
            m = _MEMBER.match(member)
            if m and m.group(1) != f"{book.month:%Y%m}":
                raise ImportProblem(f"Dateiname {member!r} und Berichtsmonat laut Impressum ({book.month:%m/%Y}) "
                                    "widersprechen sich.")
            if book.kind in books:
                raise ImportProblem("Das ZIP enthält zwei Arbeitsmappen derselben Art.")
            _check_counts(book)
            books[book.kind] = book
    if set(books) != {"count", "rate"}:
        raise ImportProblem("Das ZIP muss je eine Arbeitsmappe „Bestand an Arbeitslosen“ und „Arbeitslosenquoten“ enthalten.")
    count, rate = books["count"], books["rate"]
    if count.month != rate.month:
        raise ImportProblem(f"Die beiden Arbeitsmappen haben unterschiedliche Berichtsmonate "
                            f"({count.month:%m/%Y} und {rate.month:%m/%Y}).")
    if {(r[0], r[1]) for r in count.rows} != {(r[0], r[1]) for r in rate.rows}:
        raise ImportProblem("Die beiden Arbeitsmappen enthalten unterschiedliche Gebietseinheiten.")

    start, end = month_bounds(count.month.year, count.month.month)
    unrecognized: Counter[str] = Counter()
    values: list[ValueRow] = []
    for book, indicator in ((count, IND_COUNT), (rate, IND_RATE)):
        for level, key, region_name, cell in book.rows:
            value, status, raw = classify_cell(cell, MARKERS_BA, unrecognized)
            if value is not None and value < 0:
                raise ImportProblem(f"Negativer Wert für {key} ({indicator}): {raw!r}.")
            if indicator == IND_RATE and value is not None and value > 100:
                raise ImportProblem(f"Arbeitslosenquote über 100 % für {key}: {raw!r}.")
            values.append(ValueRow(indicator, level, key, region_name, value, status, raw))
    warnings = check_unrecognized(unrecognized, len(values), "BA-Kreisdaten")

    # Plausibilitätshinweis (kein Abbruch): Summe der Länder = Deutschland
    by = {(v.indicator_key, v.region_level, v.region_key): v for v in values}
    total = by[(IND_COUNT, "country", COUNTRY_KEY)].value
    states = [v.value for v in values if v.indicator_key == IND_COUNT and v.region_level == "state"]
    if total is not None and all(s is not None for s in states) and sum(states, Decimal(0)) != total:
        warnings.append(f"Summe der Länderwerte ({sum(states, Decimal(0))}) weicht vom Deutschlandwert ({total}) ab.")

    notes = [f"Berichtsmonat laut Impressum: {count.month:%m/%Y}"]
    if count.created:
        notes.append(f"Erstellungsdatum laut Datei: {fmt_date(count.created)}")
    if count.next_release:
        notes.append(f"nächster Veröffentlichungstermin laut Datei: {fmt_date(count.next_release)}")
    gebietsstand = end if count.gebietsstand_is_datenstand else None
    if gebietsstand:
        notes.append("Gebietsstand = Datenstand (laut Datei)")
    notes.append("übernommen: Deutschland, Länder, Kreise aus Blatt „Gesamt“ (Rechtskreis insgesamt), nur Berichtsmonat")
    release = ParsedRelease(period_key=f"{start:%Y-%m}", period_start=start, period_end=end, gebietsstand=gebietsstand,
                            values=values, notes=notes)
    info = {"regions": dict(Counter(r[0] for r in count.rows)),
            "skipped_rows": {"regierungsbezirk": count.skipped["regierungsbezirk"], "gemeinde": count.skipped["gemeinde"]},
            "members": [count.member, rate.member]}
    return release, info, warnings
