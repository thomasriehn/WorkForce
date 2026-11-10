"""Destatis Gemeindeverzeichnis GV-ISys: „Alle politisch selbständigen Gemeinden mit ausgewählten Merkmalen“.

Die Quartalsausgabe (XLSX) ergänzt die Ortsreferenz:

* ``geo_place`` (Gemeinden): PLZ des Verwaltungssitzes, Einwohnerzahl sowie – nur wenn VG250 keine geliefert
  hat – die Mittelpunktkoordinaten. Gemeinden, die in ``geo_place`` noch fehlen, werden nur angelegt, wenn ihr Kreis
  zum geladenen Gebietsstand gehört (oder noch gar kein Gebietsstand geladen ist).
* ``postal_code``: PLZ → Gemeinde/Kreis.

Einschränkung: Die Datei nennt je Gemeinde nur **die PLZ des Verwaltungssitzes**. Weitere Postleitzahlen einer
Gemeinde (alle Großstädte!) und Ortsteile fehlen; eine PLZ ohne Verwaltungssitz ist nicht enthalten.

Gebietsstand: Das Verzeichnis ist meist jünger als die Kreisgeometrien (VG250, Stand 31.12.). Einträge, deren
Kreisschlüssel im geladenen Gebietsstand nicht vorkommt, werden nicht in die Ortsreferenz geschrieben, sondern im
Ergebnis gemeldet – sonst entstünden Zuordnungen zu Kreisen, die die Karte nicht kennt.
"""
from __future__ import annotations

import re
from collections import Counter
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any

from sqlalchemy import text as sql
from sqlalchemy.orm import Session

from ..normalize.text import fold
from .common import (
    FileContext,
    ImportProblem,
    ParsedRelease,
    find_release,
    fmt_date,
    is_xlsx,
    known_region_keys,
    open_workbook,
    parse_german_date,
    store_release,
    summarize,
)

DATASET_KEY = "gv_isys"
SOURCE_TAG = "GV-ISys"
MUNICIPALITIES_RANGE = (9000, 13000)  # Plausibilitätsgrenzen
DISTRICTS_RANGE = (380, 420)
_SHEET = re.compile(r"^Onlineprodukt_Gemeinden(\d{2})(\d{2})(\d{4})$")
_TITLE_DATE = re.compile(r"am (\d{2}\.\d{2}\.\d{4})")
_EXPECTED_HEAD = {  # (Zeile, Spalte) 0-basiert im Kopfbereich → erwarteter Textanfang
    (2, 0): "Satzart", (2, 7): "Gemeindename", (2, 9): "Bevölkerung", (2, 13): "Postleitzahl",
    (2, 14): "Geografische Mittelpunktkoordinaten", (3, 2): "Land", (3, 4): "Kreis", (3, 6): "Gem",
    (3, 9): "insgesamt", (3, 14): "Längengrad", (3, 15): "Breitengrad",
}


@dataclass
class Municipality:
    ags: str
    kreis_key: str
    state_key: str
    name_full: str
    name: str
    population: int | None
    plz: str | None
    lon: Decimal | None
    lat: Decimal | None


@dataclass
class ParsedGv:
    gebietsstand: date
    municipalities: list[Municipality] = field(default_factory=list)
    district_rows: int = 0
    notes: list[str] = field(default_factory=list)
    info: dict[str, Any] = field(default_factory=dict)


def base_name(full: str) -> str:
    """„Flensburg, Stadt“ → „Flensburg“ (Namenszusatz hinter dem letzten Komma abtrennen)."""
    head, sep, _zusatz = full.rpartition(", ")
    return head.strip() if sep and head.strip() else full.strip()


def _coord(cell: Any) -> Decimal | None:
    if cell is None:
        return None
    s = str(cell).strip().replace(",", ".")
    if not s:
        return None
    try:
        d = Decimal(s)
    except InvalidOperation as exc:
        raise ImportProblem(f"GV-ISys: Koordinate {cell!r} ist keine Zahl.") from exc
    return d


def _str(cell: Any) -> str:
    return "" if cell is None else str(cell).strip()


def parse(path: Path, name: str) -> ParsedGv:
    what = "GV-ISys"
    if not is_xlsx(path):
        raise ImportProblem("Für das Gemeindeverzeichnis wird die Excel-Arbeitsmappe (.xlsx) der Quartalsausgabe benötigt.")
    with open_workbook(path) as wb:
        sheets = [(s, _SHEET.match(s)) for s in wb.sheetnames]
        data = [(s, m) for s, m in sheets if m]
        if len(data) != 1:
            raise ImportProblem(f"{what}: Datenblatt „Onlineprodukt_GemeindenTTMMJJJJ“ nicht (eindeutig) gefunden "
                                f"(Blätter: {', '.join(wb.sheetnames[:6])}).")
        sheet, m = data[0]
        try:
            stand_sheet = date(int(m.group(3)), int(m.group(2)), int(m.group(1)))
        except ValueError as exc:
            raise ImportProblem(f"{what}: Datum im Blattnamen {sheet!r} ist ungültig.") from exc
        ws = wb[sheet]
        rows = ws.iter_rows(max_col=20, values_only=True)
        head = []
        for row in rows:
            head.append(tuple(row) + (None,) * (20 - len(row)))
            if len(head) == 6:
                break
        if len(head) < 6:
            raise ImportProblem(f"{what}: Tabellenkopf unvollständig.")
        for (r, c), expected in _EXPECTED_HEAD.items():
            if not _str(head[r][c]).startswith(expected):
                raise ImportProblem(f"{what}: Spaltenkopf in Zeile {r + 1}, Spalte {c + 1} lautet {head[r][c]!r} "
                                    f"(erwartet: „{expected}…“). Das Dateiformat hat sich geändert.")
        tm = _TITLE_DATE.search(_str(head[0][0]))
        stand_title = parse_german_date(tm.group(1)) if tm else None
        if stand_title is None:
            raise ImportProblem(f"{what}: Gebietsstand in der Titelzeile nicht gefunden: {head[0][0]!r}.")
        if stand_title != stand_sheet:
            raise ImportProblem(f"{what}: Gebietsstand laut Titel ({fmt_date(stand_title)}) und laut Blattname "
                                f"({fmt_date(stand_sheet)}) widersprechen sich.")
        out = ParsedGv(gebietsstand=stand_title)
        out.notes.append(f"Gebietsstand laut Datei: {fmt_date(stand_title)}")
        for label, col in (("Bevölkerungsstand", 9), ("Koordinaten", 14)):
            if _str(head[4][col]):
                out.notes.append(f"{label}: {_str(head[4][col])}")
        if "Inhalt" in wb.sheetnames:
            for row in wb["Inhalt"].iter_rows(min_row=30, max_row=45, max_col=1, values_only=True):
                if _str(row[0]).startswith("Erscheinungsmonat"):
                    out.notes.append(f"{_str(row[0])} (laut Datei; genaues Veröffentlichungsdatum nicht angegeben)")
        satzarten: Counter[str] = Counter()
        seen: set[str] = set()
        for row in rows:
            satzart = _str(row[0])
            if not satzart:
                continue
            if not satzart.isdigit():
                if satzart.startswith(("Quelle", "©", "1)", "2)", "3)")):
                    break
                continue  # Fußnotenfortsetzungen
            satzarten[satzart] += 1
            if satzart != "60":
                continue
            land, rb, kreis, gem = _str(row[2]), _str(row[3]), _str(row[4]), _str(row[6])
            ags = land + rb + kreis + gem
            if not (len(ags) == 8 and ags.isdigit()):
                raise ImportProblem(f"{what}: Gemeindeschlüssel {ags!r} ist nicht achtstellig (Zeile „{_str(row[7])}“).")
            if ags in seen:
                raise ImportProblem(f"{what}: Gemeindeschlüssel {ags} kommt mehrfach vor.")
            seen.add(ags)
            full = _str(row[7])
            if not full:
                raise ImportProblem(f"{what}: Gemeindename zu {ags} fehlt.")
            pop_cell = row[9]
            if pop_cell is None or _str(pop_cell) == "":
                population = None
            elif isinstance(pop_cell, int | float) and float(pop_cell) == int(pop_cell) and pop_cell >= 0:
                population = int(pop_cell)
            else:
                raise ImportProblem(f"{what}: Einwohnerzahl {pop_cell!r} zu {ags} ist keine ganze Zahl.")
            plz = _str(row[13]) or None
            if plz is not None and not (len(plz) == 5 and plz.isdigit()):
                raise ImportProblem(f"{what}: Postleitzahl {plz!r} zu {ags} ist nicht fünfstellig.")
            lon, lat = _coord(row[14]), _coord(row[15])
            if lon is None or lat is None or (lon == 0 and lat == 0):
                lon = lat = None  # 0/0 steht für „keine Koordinate“
            elif not (Decimal(5) < lon < Decimal(16) and Decimal(47) < lat < Decimal(56)):
                raise ImportProblem(f"{what}: Koordinate ({lon}, {lat}) zu {ags} liegt nicht in Deutschland.")
            out.municipalities.append(Municipality(ags, ags[:5], ags[:2], full, base_name(full), population, plz, lon, lat))
    n = len(out.municipalities)
    if not MUNICIPALITIES_RANGE[0] <= n <= MUNICIPALITIES_RANGE[1]:
        raise ImportProblem(f"{what}: {n} Gemeinden gefunden (erwartet: rund 10.900). Es wurde nichts importiert.")
    out.district_rows = satzarten["40"]
    if not DISTRICTS_RANGE[0] <= out.district_rows <= DISTRICTS_RANGE[1]:
        raise ImportProblem(f"{what}: {out.district_rows} Kreiszeilen gefunden (erwartet: rund 400). Es wurde nichts importiert.")
    out.info = {"municipalities": n, "district_rows": out.district_rows,
                "with_postal_code": sum(1 for g in out.municipalities if g.plz),
                "with_population": sum(1 for g in out.municipalities if g.population is not None),
                "with_coordinates": sum(1 for g in out.municipalities if g.lat is not None),
                "population_sum": sum(g.population or 0 for g in out.municipalities)}
    return out


def apply(db: Session, parsed: ParsedGv, ctx: FileContext) -> dict[str, Any]:
    period_key = parsed.gebietsstand.isoformat()
    if find_release(db, DATASET_KEY, period_key, ctx.sha256) is None:
        newer = db.execute(sql("SELECT max(period_end) FROM stat_release WHERE dataset_key = :d AND period_end > :p"),
                           {"d": DATASET_KEY, "p": parsed.gebietsstand}).scalar()
        if newer is not None:
            raise ImportProblem(f"Es ist bereits ein neuerer Stand des Gemeindeverzeichnisses importiert ({fmt_date(newer)}); "
                                f"die ältere Ausgabe vom {fmt_date(parsed.gebietsstand)} wird nicht übernommen.")
    release = ParsedRelease(period_key=period_key, period_end=parsed.gebietsstand, period_start=None,
                            gebietsstand=parsed.gebietsstand, row_count=len(parsed.municipalities), notes=list(parsed.notes))
    rel = store_release(db, DATASET_KEY, release, ctx)
    extra: dict[str, Any] = dict(parsed.info)
    warnings: list[str] = []
    if rel["status"] == "imported":
        extra.update(_write_reference(db, parsed, warnings))
    out = summarize(DATASET_KEY, ctx, [rel], **extra)
    out["warnings"] = warnings
    return out


def _write_reference(db: Session, parsed: ParsedGv, warnings: list[str]) -> dict[str, Any]:
    districts = known_region_keys(db).get("district") or set()
    note = (f"{SOURCE_TAG} (Statistisches Bundesamt), Gebietsstand {fmt_date(parsed.gebietsstand)}: "
            "PLZ des Verwaltungssitzes, Einwohnerzahl")
    existing = {ags: (pid, lat) for pid, ags, lat in db.execute(sql(
        "SELECT id, ags, lat FROM geo_place WHERE country = 'DE' AND kind = 'municipality' AND ags IS NOT NULL")).all()}
    updates: list[dict[str, Any]] = []
    inserts: list[dict[str, Any]] = []
    plz_rows: list[dict[str, Any]] = []
    unknown_kreise: Counter[str] = Counter()
    for g in parsed.municipalities:
        kreis_known = not districts or g.kreis_key in districts
        hit = existing.get(g.ags)
        if hit is not None:
            updates.append({"id": hit[0], "plz": g.plz, "pop": g.population, "lat": g.lat, "lon": g.lon, "note": note})
        elif kreis_known:
            inserts.append({"name": g.name, "norm": fold(g.name), "ags": g.ags, "kreis": g.kreis_key, "state": g.state_key,
                            "plz": g.plz, "pop": g.population, "lat": g.lat, "lon": g.lon, "stand": parsed.gebietsstand,
                            "note": note + ", Name, Koordinaten (angenäherter Ortsmittelpunkt)"})
        if not kreis_known:
            unknown_kreise[g.kreis_key] += 1
            continue
        if g.plz:
            plz_rows.append({"plz": g.plz, "ags": g.ags, "kreis": g.kreis_key, "name": g.name, "note": note})
    if updates:
        db.execute(sql(
            "UPDATE geo_place SET postal_code = :plz, population = coalesce(:pop, population), "
            "lat = coalesce(lat, :lat), lon = coalesce(lon, :lon), "
            "source_note = CASE WHEN source_note IS NULL OR source_note = '' THEN :note "
            f"ELSE split_part(source_note, ' | {SOURCE_TAG}', 1) || ' | ' || :note END WHERE id = :id"), updates)
    if inserts:
        db.execute(sql(
            "INSERT INTO geo_place (country, name, name_norm, kind, ags, kreis_key, state_key, postal_code, population, lat, lon, "
            "gebietsstand, source_note) VALUES ('DE', :name, :norm, 'municipality', :ags, :kreis, :state, :plz, :pop, :lat, :lon, "
            ":stand, :note)"), inserts)
    db.execute(sql("DELETE FROM postal_code WHERE country = 'DE' AND source_note LIKE :tag"), {"tag": f"{SOURCE_TAG}%"})
    if plz_rows:
        db.execute(sql(
            "INSERT INTO postal_code (country, plz, ags, kreis_key, place_name, source_note) "
            "VALUES ('DE', :plz, :ags, :kreis, :name, :note) ON CONFLICT ON CONSTRAINT uq_postal_code DO NOTHING"), plz_rows)
    in_file = {g.ags for g in parsed.municipalities}
    not_in_file = sorted(set(existing) - in_file)
    if unknown_kreise:
        warnings.append(
            f"{sum(unknown_kreise.values())} Gemeinde(n) mit Kreisschlüsseln, die im geladenen Gebietsstand fehlen "
            f"({', '.join(sorted(unknown_kreise))}), wurden nicht in die Ortsreferenz übernommen (anderer Gebietsstand).")
    if not_in_file:
        warnings.append(f"{len(not_in_file)} Gemeinde(n) der Ortsreferenz kommen im Gemeindeverzeichnis nicht vor "
                        "(anderer Gebietsstand) und bleiben ohne PLZ/Einwohnerzahl.")
    return {"places_enriched": len(updates), "places_added": len(inserts), "postal_codes": len(plz_rows),
            "distinct_postal_codes": len({r["plz"] for r in plz_rows}),
            "skipped_unknown_kreis": dict(sorted(unknown_kreise.items())),
            "unknown_region_keys": sorted(unknown_kreise),
            "places_not_in_file": not_in_file[:50], "places_not_in_file_count": len(not_in_file)}
