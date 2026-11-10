"""BA-Statistik: „Arbeitsmarkt nach Berufen (KldB 2010) – Deutschland, West/Ost und Länder (Monatszahlen)“.

Das Produkt gibt es nur für Deutschland, West/Ost und die Länder – **nicht** für Kreise. Es werden deshalb keine
Kreiswerte erzeugt und Landeswerte nie auf Kreise verteilt.

Übernommen wird je Region der Bestand des Berichtsmonats für Arbeitslose, Arbeitsuchende und gemeldete Arbeitsstellen:

* Tabellen 1.x („Übersicht“, alle Anforderungsniveaus): Zeile „Insgesamt“ (``dim_key = ''``) sowie die Zeilen
  „Gesamt“ der Berufshauptgruppen (2-Steller) und Berufsgruppen (3-Steller).
* Tabellen 2.x („Detailansicht“, ohne Helfer): nur die Berufsgattungen (5-Steller) – deren Anforderungsniveau ist
  Teil des Schlüssels und damit eindeutig.

Nicht übernommen: die Aufgliederung nach Anforderungsniveau in 1.x, die Aggregate „ohne Helfer“ (2- bis 4-Steller)
in 2.x – sie hätten denselben Schlüssel wie die Gesamtwerte, aber eine andere Grundgesamtheit –, die
Vorjahres-/Veränderungsspalten, der Zugang an Arbeitsstellen sowie die Regionen West-/Ostdeutschland.

Zeichen: ``*`` anonymisiert, ``x`` nicht sinnvoll (laut Blatt III). ``-`` steht für „nichts vorhanden“; die
Arbeitsmappe erklärt das Zeichen nicht selbst, ihre Veränderungsspalten rechnen aber durchgängig mit 0
(z. B. Bestand 20, Vorjahr „-“, Veränderung 20). Es wird als echter Nullwert (``zero``) gespeichert.
"""
from __future__ import annotations

import re
from collections import Counter
from datetime import date, datetime
from pathlib import Path
from typing import Any

from .common import (
    COUNTRY_KEY,
    KLDB_VERSION,
    MARKERS_BA,
    STATE_KEYS,
    ImportProblem,
    ParsedRelease,
    ValueRow,
    as_date,
    check_unrecognized,
    classify_cell,
    fmt_date,
    is_xlsx,
    month_bounds,
    open_workbook,
    require_sheet,
)

DATASET_KEY = "ba_berufe"
IND_ALO = "arbeitslose_beruf"
IND_ASU = "arbeitsuchende_beruf"
IND_STELLEN = "gemeldete_stellen_beruf"

_TABLE_SHEET = re.compile(r"^[12]\.\d{1,2}$")
_REGION = re.compile(r"^(?:(\d{2})\s+)?(.+)$")
_FOOTER = ("©", "Datenstand", "1)", "Erstellungsdatum", "Quelle")
_SKIPPED_REGIONS = ("Westdeutschland", "Ostdeutschland")


def _region(label: Any, sheet: str) -> tuple[str, str, str] | None:
    """Regionsangabe aus Zelle A6 → (Ebene, Schlüssel, Name); ``None`` für West-/Ostdeutschland."""
    if not isinstance(label, str) or not label.strip():
        raise ImportProblem(f"Berufe-Heft, Blatt {sheet}: Regionsangabe in Zelle A6 fehlt.")
    m = _REGION.match(label.strip())
    assert m is not None
    prefix, name = m.group(1), m.group(2).strip()
    if name == "Deutschland":
        return "country", COUNTRY_KEY, name
    if name in _SKIPPED_REGIONS:
        return None
    key = STATE_KEYS.get(name)
    if key is None:
        raise ImportProblem(f"Berufe-Heft, Blatt {sheet}: unbekannte Region {label!r}.")
    if prefix and prefix != key:
        raise ImportProblem(f"Berufe-Heft, Blatt {sheet}: Schlüssel {prefix} passt nicht zum Land {name} ({key}).")
    return "state", key, name


def _find_columns(head: list[tuple[Any, ...]], sheet: str, day: date) -> tuple[int, int, int]:
    """Spalten „Bestand im Berichtsmonat“ für Arbeitslose, Arbeitsuchende, gemeldete Arbeitsstellen."""
    what = f"Berufe-Heft, Blatt {sheet}"
    for i, row in enumerate(head):
        cells = {j: c.strip() for j, c in enumerate(row) if isinstance(c, str)}
        alo = [j for j, c in cells.items() if c == "Arbeitslose"]
        asu = [j for j, c in cells.items() if c.startswith("Arbeitsuchende")]
        st = [j for j, c in cells.items() if c == "Gemeldete Arbeitsstellen"]
        if len(alo) == 1 and len(asu) == 1 and len(st) == 1:
            cols = (alo[0], asu[0], st[0])
            if not cols[0] < cols[1] < cols[2] or i + 3 >= len(head):
                break
            sub = head[i + 1]
            if not all(isinstance(sub[c], str) and sub[c].strip() == "Bestand" for c in (cols[0], cols[2])):
                raise ImportProblem(f"{what}: Unter „Arbeitslose“/„Gemeldete Arbeitsstellen“ steht nicht „Bestand“.")
            dates = head[i + 3]
            for c in cols:
                if as_date(dates[c]) != day or not isinstance(dates[c], datetime | date):
                    raise ImportProblem(f"{what}: Die Bestandsspalte ist nicht mit dem Berichtstag {fmt_date(day)} überschrieben.")
            return cols
    raise ImportProblem(f"{what}: Kopfzeile mit „Arbeitslose“, „Arbeitsuchende“ und „Gemeldete Arbeitsstellen“ nicht gefunden.")


def _read_sheet(ws: Any, sheet: str, month: date, unrecognized: Counter[str]) -> tuple[tuple[str, str, str] | None, str, list[ValueRow], date]:
    what = f"Berufe-Heft, Blatt {sheet}"
    rows = ws.iter_rows(values_only=True)
    head: list[tuple[Any, ...]] = []
    for row in rows:
        head.append(tuple(row))
        if len(head) == 15:
            break
    if len(head) < 15:
        raise ImportProblem(f"{what}: Tabellenkopf unvollständig.")
    title = str(head[2][0] or "")
    if not title.startswith("Arbeitsmarktdaten nach Zielberufen"):
        raise ImportProblem(f"{what}: Unerwarteter Tabellentitel {title[:60]!r}.")
    view = str(head[3][0] or "").strip()
    if view not in ("Übersicht", "Detailansicht"):
        raise ImportProblem(f"{what}: Weder „Übersicht“ noch „Detailansicht“ (Zelle A4: {view!r}).")
    day = as_date(head[6][0])
    if day is None or (day.year, day.month) != (month.year, month.month):
        raise ImportProblem(f"{what}: Berichtstag in Zelle A7 ({head[6][0]!r}) passt nicht zum Berichtsmonat {month:%m/%Y}.")
    region = _region(head[5][0], sheet)
    c_alo, c_asu, c_st = _find_columns(head, sheet, day)
    numbers = head[14]
    if numbers[c_alo] != 1:
        raise ImportProblem(f"{what}: Spaltennummerierung in Zeile 15 nicht wie erwartet.")
    if region is None:
        return None, view, [], day
    level, key, region_name = region
    out: list[ValueRow] = []
    seen_total = False
    for row in rows:
        a, b = row[0], row[1]
        a_txt = a.strip() if isinstance(a, str) else a
        if isinstance(a_txt, str) and a_txt.startswith(_FOOTER):
            break
        dim_key: str | None = None
        dim_label: str | None = None
        if view == "Übersicht":
            niveau = row[c_alo - 1]
            if not (isinstance(niveau, str) and niveau.strip() == "Gesamt"):
                continue  # Aufgliederung nach Anforderungsniveau wird nicht übernommen
            if a_txt == "Insgesamt":
                dim_key, dim_label, seen_total = "", "Insgesamt", True
            elif isinstance(a_txt, str) and a_txt.isdigit() and len(a_txt) in (2, 3):
                dim_key, dim_label = a_txt, (b.strip() if isinstance(b, str) else None)
            else:
                raise ImportProblem(f"{what}: Unerwartete Zeile „Gesamt“ mit Schlüssel {a!r}.")
        else:
            if a_txt is None:
                continue  # Zeile „Gesamt“ (ohne Helfer) bzw. Leerzeile
            if not (isinstance(a_txt, str) and a_txt.isdigit() and 2 <= len(a_txt) <= 5):
                raise ImportProblem(f"{what}: Unerwarteter Berufsschlüssel {a!r}.")
            if len(a_txt) != 5:
                continue  # Aggregate ohne Helfer werden nicht übernommen
            dim_key, dim_label = a_txt, (b.strip() if isinstance(b, str) else None)
        if dim_key != "" and not dim_label:
            raise ImportProblem(f"{what}: Berufsbezeichnung zu Schlüssel {dim_key} fehlt.")
        for indicator, col in ((IND_ALO, c_alo), (IND_ASU, c_asu), (IND_STELLEN, c_st)):
            value, status, raw = classify_cell(row[col] if col < len(row) else None, MARKERS_BA, unrecognized)
            if value is not None and value < 0:
                raise ImportProblem(f"{what}: Negativer Bestand bei {dim_key or 'Insgesamt'}: {raw!r}.")
            out.append(ValueRow(indicator, level, key, region_name, value, status, raw, dim_key=dim_key,
                                dim_label=dim_label, classification_version=KLDB_VERSION))
    if view == "Übersicht" and not seen_total:
        raise ImportProblem(f"{what}: Zeile „Insgesamt“ nicht gefunden.")
    if not out:
        raise ImportProblem(f"{what}: Keine Datenzeilen gefunden.")
    return region, view, out, day


def parse(path: Path, name: str) -> tuple[ParsedRelease, dict[str, Any], list[str]]:
    if not is_xlsx(path):
        raise ImportProblem("Für diesen Datensatz wird die Excel-Arbeitsmappe (.xlsx) der Monatsausgabe benötigt.")
    unrecognized: Counter[str] = Counter()
    values: list[ValueRow] = []
    regions: dict[str, set[str]] = {"Übersicht": set(), "Detailansicht": set()}
    skipped_regions: set[str] = set()
    with open_workbook(path) as wb:
        imp = require_sheet(wb, "I", "Berufe-Heft")
        meta: dict[str, Any] = {}
        for row in imp.iter_rows(min_row=1, max_row=40, max_col=6, values_only=True):
            if isinstance(row[0], str) and row[0].strip().endswith(":"):
                meta[row[0].strip().rstrip(":")] = next((c for c in row[1:] if c is not None), None)
        if "Arbeitsmarkt nach Berufen" not in str(meta.get("Titel") or ""):
            raise ImportProblem(f"Berufe-Heft: Unerwarteter Titel im Impressum: {meta.get('Titel')!r}.")
        month = as_date(meta.get("Berichtsmonat"))
        if month is None:
            raise ImportProblem("Berufe-Heft: Berichtsmonat im Blatt „I“ (Impressum) nicht gefunden.")
        sheets = [s for s in wb.sheetnames if _TABLE_SHEET.match(s)]
        if not sheets:
            raise ImportProblem("Berufe-Heft: Keine Tabellenblätter 1.x/2.x gefunden.")
        days: set[date] = set()
        for sheet in sheets:
            region, view, rows, day = _read_sheet(wb[sheet], sheet, month, unrecognized)
            days.add(day)
            if region is None:
                skipped_regions.add(sheet)
                continue
            if region[1] in regions[view]:
                raise ImportProblem(f"Berufe-Heft: Region {region[2]} kommt in der {view} mehrfach vor (Blatt {sheet}).")
            regions[view].add(region[1])
            values.extend(rows)
    expected = {COUNTRY_KEY, *STATE_KEYS.values()}
    for view, keys in regions.items():
        missing = sorted(expected - keys)
        if missing:
            raise ImportProblem(f"Berufe-Heft: In der {view} fehlen Regionen: {', '.join(missing)}.")
    warnings = check_unrecognized(unrecognized, len(values), "Berufe-Heft")
    start, end = month_bounds(month.year, month.month)
    notes = [f"Berichtsmonat laut Impressum: {month:%m/%Y}"]
    if len(days) == 1:
        notes.append(f"Zähltag laut Tabellen: {fmt_date(next(iter(days)))}")
    if as_date(meta.get("Erstellungsdatum")):
        notes.append(f"Erstellungsdatum laut Datei: {fmt_date(as_date(meta.get('Erstellungsdatum')))}")  # type: ignore[arg-type]
    if as_date(meta.get("Nächster Veröffentlichungstermin")):
        notes.append("nächster Veröffentlichungstermin laut Datei: "
                     f"{fmt_date(as_date(meta.get('Nächster Veröffentlichungstermin')))}")  # type: ignore[arg-type]
    notes.append("Regionen: Deutschland und Länder; West-/Ostdeutschland nicht übernommen; keine Kreisebene im Produkt")
    release = ParsedRelease(period_key=f"{start:%Y-%m}", period_start=start, period_end=end, values=values, notes=notes)
    info = {"regions": {"country": 1, "state": len(STATE_KEYS)}, "skipped_sheets": sorted(skipped_regions),
            "dims": dict(Counter(len(v.dim_key) for v in values if v.indicator_key == IND_ALO))}
    return release, info, warnings
