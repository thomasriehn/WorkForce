"""Erzeuger für SYNTHETISCHE Testdateien im Aufbau der amtlichen Quellen (frei erfundene Werte und Namen).

Die Funktionen bilden nur das Layout nach (Blattnamen, Kopfzeilen, Schlüsselformate, Fehlwertzeichen), das die
Importer prüfen. Es werden keine veröffentlichten Zahlen übernommen. Gebietsschlüssel haben das amtliche Format,
sind aber – bis auf die 16 Länderschlüssel, die der Aufbau der BA-Dateien vorgibt – erfunden (Kreise ``xx9nn``).
"""
from __future__ import annotations

import sqlite3
import struct
import zipfile
from datetime import date, datetime
from pathlib import Path
from typing import Any

import pytest
from openpyxl import Workbook

MARK = "SYNTHETISCHE TESTDATEN – frei erfunden, keine amtlichen Zahlen"
STATES = [("01", "Schleswig-Holstein"), ("02", "Hamburg"), ("03", "Niedersachsen"), ("04", "Bremen"),
          ("05", "Nordrhein-Westfalen"), ("06", "Hessen"), ("07", "Rheinland-Pfalz"), ("08", "Baden-Württemberg"),
          ("09", "Bayern"), ("10", "Saarland"), ("11", "Berlin"), ("12", "Brandenburg"), ("13", "Mecklenburg-Vorpommern"),
          ("14", "Sachsen"), ("15", "Sachsen-Anhalt"), ("16", "Thüringen")]
# Blattreihenfolge des Berufe-Hefts: Deutschland, West, Ost, dann die Länder in der Reihenfolge der BA
BERUFE_REGIONS = ["Deutschland", "Westdeutschland", "Ostdeutschland", "Schleswig-Holstein", "Hamburg", "Niedersachsen",
                  "Bremen", "Nordrhein-Westfalen", "Hessen", "Rheinland-Pfalz", "Baden-Württemberg", "Bayern", "Saarland",
                  "Berlin", "Brandenburg", "Mecklenburg-Vorpommern", "Sachsen", "Sachsen-Anhalt", "Thüringen"]
AGE_GROUPS = [("ALT000B03", "unter 3 Jahre"), ("ALT003B06", "3 bis unter 6 Jahre"), ("ALT006B10", "6 bis unter 10 Jahre"),
              ("ALT010B15", "10 bis unter 15 Jahre"), ("ALT015B18", "15 bis unter 18 Jahre"), ("ALT018B20", "18 bis unter 20 Jahre"),
              ("ALT020B25", "20 bis unter 25 Jahre"), ("ALT025B30", "25 bis unter 30 Jahre"), ("ALT030B35", "30 bis unter 35 Jahre"),
              ("ALT035B40", "35 bis unter 40 Jahre"), ("ALT040B45", "40 bis unter 45 Jahre"), ("ALT045B50", "45 bis unter 50 Jahre"),
              ("ALT050B55", "50 bis unter 55 Jahre"), ("ALT055B60", "55 bis unter 60 Jahre"), ("ALT060B65", "60 bis unter 65 Jahre"),
              ("ALT065B75", "65 bis unter 75 Jahre"), ("ALT075UM", "75 Jahre und mehr")]
WORKING_AGE_CODES = [c for c, _ in AGE_GROUPS[4:15]]


@pytest.fixture
def small_thresholds(monkeypatch: pytest.MonkeyPatch) -> None:
    """Senkt die Plausibilitätsgrenzen (rund 400 Kreise usw.), damit kleine synthetische Dateien importierbar sind."""
    from workforce.geo import vg250
    from workforce.stats import ba_kreise, bevoelkerung, gv_isys, kldb

    monkeypatch.setattr(ba_kreise, "DISTRICTS_RANGE", (1, 50))
    monkeypatch.setattr(bevoelkerung, "DISTRICTS_RANGE", (1, 50))
    monkeypatch.setattr(gv_isys, "MUNICIPALITIES_RANGE", (1, 50))
    monkeypatch.setattr(gv_isys, "DISTRICTS_RANGE", (1, 50))
    monkeypatch.setattr(kldb, "MIN_CLASSES_5", 1)
    monkeypatch.setattr(kldb, "MIN_TITLES", 1)
    monkeypatch.setattr(vg250, "STATES_EXPECTED", 2)
    monkeypatch.setattr(vg250, "DISTRICTS_RANGE", (1, 50))
    monkeypatch.setattr(vg250, "MUNICIPALITIES_RANGE", (1, 50))


def _month_columns(month: date) -> list[datetime]:
    """24 Monatsspalten: Vorjahr und laufendes Jahr (wie in den BA-Zeitreihenheften)."""
    return [datetime(y, m, 1) for y in (month.year - 1, month.year) for m in range(1, 13)]


# --------------------------------------------------------------------------------------------------------
# BA: Arbeitslose und Arbeitslosenquoten (ZIP mit zwei Arbeitsmappen)
# --------------------------------------------------------------------------------------------------------
def _ba_kreise_book(kind: str, month: date, districts: list[tuple[str, str, Any, Any]], *, rate_basis: bool = True,
                    sheet_name: str = "Gesamt", country: Any = None) -> Workbook:
    wb = Workbook()
    wb.active.title = "Deckblatt"
    wb["Deckblatt"]["A1"] = MARK
    imp = wb.create_sheet("Impressum")
    imp["A4"] = "Impressum"
    imp["A8"], imp["C8"] = "Titel:", ("Arbeitslose - Zeitreihe" if kind == "count" else "Arbeitslosenquoten - Zeitreihe")
    imp["A10"], imp["C10"] = "Region:", "Deutschland"
    imp["A12"], imp["C12"] = "Berichtsmonat:", datetime(month.year, month.month, 1)
    imp["A14"], imp["C14"] = "Erstellungsdatum:", datetime(month.year, month.month, 27)
    imp["A18"], imp["C18"] = "Nächster Veröffentlichungstermin:", datetime(month.year + (month.month == 12), month.month % 12 + 1, 28)
    imp["A20"], imp["C20"] = "Hinweis:", MARK
    ws = wb.create_sheet(sheet_name)
    ws["AA1"] = "Arbeitsmarktstatistik"
    ws["A3"] = "Bestand an Arbeitslosen - Gesamt" if kind == "count" else "Arbeitslosenquoten - hier: Arbeitslosenquote - Gesamt"
    ws["A4"] = "Länder, Regierungsbezirke, Kreise und Gemeinden (Gebietsstand = Datenstand)"
    ws["A5"] = f"Zeitreihe, Datenstand: {month:%m/%Y} ({MARK})"
    ws["A6"] = "Rechtskreis Insgesamt"
    if kind == "rate" and rate_basis:
        ws["A7"] = "Arbeitslosenquote bezogen auf alle zivilen Erwerbspersonen."
    ws["B9"] = "Jahresdurchschnitte"
    cols = _month_columns(month)
    for j, d in enumerate(cols):
        ws.cell(row=10, column=4 + j, value=d)
    ws.cell(row=10, column=2, value="Jahresdurch-schnitt")
    ws.cell(row=10, column=3, value="Gleitender JD (synthetisch)")
    ws.cell(row=11, column=1, value="Region")
    ws.cell(row=11, column=2, value=month.year - 1)
    ws.cell(row=11, column=3, value=month.year)
    for j in range(24):
        ws.cell(row=11, column=4 + j, value=j + 1)
    current = 12 + month.month - 1  # 0-basierter Index der Berichtsmonatsspalte innerhalb der 24 Monatsspalten

    def line(label: str, cell: Any, base: float) -> list[Any]:
        row: list[Any] = [label, base, base]
        for j in range(24):
            if j < current:
                row.append(base + 7 if kind == "count" else round(base + 0.7, 1))  # Vormonate: bewusst andere Werte
            elif j == current:
                row.append(cell)
            else:
                row.append(None if kind == "count" else "...")  # künftige Monate
        return row

    state_cells = [(1000 + 10 * i) if kind == "count" else round(5.0 + i / 10, 1) for i in range(len(STATES))]
    total = country if country is not None else (sum(state_cells) if kind == "count" else 5.5)
    r = 12
    for values in [line("Deutschland", total, 99999)]:
        for c, v in enumerate(values, start=1):
            ws.cell(row=r, column=c, value=v)
    r += 1
    for (key, name), cell in zip(STATES, state_cells, strict=True):
        rows = [line(f"{key} {name}", cell, 500)]
        if key == "03":
            rows.append(line("039 Statistische Region Testhausen (synthetisch)", 77, 70))
        for dkey, dname, count_cell, rate_cell in districts:
            if dkey[:2] == key:
                rows.append(line(f"{dkey} {dname}", count_cell if kind == "count" else rate_cell, 300))
                rows.append(line(f"{dkey}001 Testgemeinde (synthetisch)", "*" if kind == "count" else "x", 3))
        for values in rows:
            for c, v in enumerate(values, start=1):
                ws.cell(row=r, column=c, value=v)
            r += 1
    ws.cell(row=r, column=1, value=f"Erstellungsdatum: 27.{month:%m.%Y}, {MARK}")
    # Blatt mit der bekannten Falle: künftige Monate sind hier mit 0 gefüllt – es darf nie gelesen werden
    trap = wb.create_sheet("Übersicht_Kreise")
    trap["A3"] = "Bestand an Arbeitslosen - Insgesamt" if kind == "count" else "Arbeitslosenquoten - Insgesamt"
    trap["A11"] = "Region"
    for i, (dkey, dname, _, _) in enumerate(districts):
        trap.cell(row=12 + i, column=1, value=f"{dkey} {dname}")
        for j in range(24):
            trap.cell(row=12 + i, column=4 + j, value=0)
    return wb


def ba_kreise_zip(path: Path, month: date, districts: list[tuple[str, str, Any, Any]], *, rate_basis: bool = True,
                  only: str | None = None, sheet_name: str = "Gesamt", rate_month: date | None = None, country: Any = None) -> Path:
    """ZIP der Monatsausgabe. ``districts``: (Schlüssel, Name, Zelle Bestand, Zelle Quote) – Zellen dürfen Zeichen sein."""
    tmp = path.parent
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as z:
        for kind, stem in (("count", "Arbeitslose"), ("rate", "ArbeitslosenQuoten")):
            if only and only != kind:
                continue
            m = rate_month if (kind == "rate" and rate_month) else month
            wb = _ba_kreise_book(kind, m, districts, rate_basis=rate_basis, sheet_name=sheet_name,
                                 country=country if kind == "count" else None)
            f = tmp / f"_tmp_{kind}.xlsx"
            wb.save(f)
            z.write(f, f"{m:%Y%m}_Heft_pol_SGBI_{stem}.xlsx")
            f.unlink()
        z.writestr("SYNTHETISCH.txt", MARK)
    return path


# --------------------------------------------------------------------------------------------------------
# BA: Arbeitsmarkt nach Berufen (eine Arbeitsmappe, Tabellen 1.x und 2.x)
# --------------------------------------------------------------------------------------------------------
BERUFE_OVERVIEW = [  # (Schlüssel, Bezeichnung, Niveau, Arbeitslose, Arbeitsuchende, Stellen)
    ("Insgesamt", None, "Gesamt", 1000, 1700, 300),
    (None, None, "   Helfer", 400, 600, 50),
    (None, None, "   Fachkraft", 500, 900, 200),
    (None, None, "keine Angabe", 100, 200, None),
    ("43", "Informatik- und andere IKT-Berufe (synthetisch)", "Gesamt", 120, 210, 80),
    (None, None, "Fachkraft", 70, 120, 50),
    (None, None, "Experte", 50, 90, 30),
    ("431", "Informatik (synthetisch)", "Gesamt", 60, 100, 40),
    (None, None, "Fachkraft", 60, 100, 40),
]
BERUFE_DETAIL = [  # (Schlüssel, Bezeichnung, Arbeitslose, Arbeitsuchende, Stellen)
    (None, "Gesamt", 600, 1100, 250),
    ("43", "Informatik- und andere IKT-Berufe (synthetisch)", 111, 199, 77),   # ohne Helfer – wird nicht übernommen
    ("431", "Informatik (synthetisch)", 55, 99, 33),
    ("4310", "Berufe in der Informatik (o.S.) (synthetisch)", 44, 88, 22),
    ("43102", "Informatik (o.S.) - Fachkraft (synthetisch)", 30, 55, 12),
    ("43104", "Informatik (o.S.) - Experte (synthetisch)", 14, 33, 10),
]


def ba_berufe_xlsx(path: Path, month: date, overrides: dict[tuple[str, str, str, str], Any] | None = None, *,
                   skip_region: str | None = None, sheet_day: date | None = None) -> Path:
    """Berufe-Heft. ``overrides``: (Region, 'Übersicht'|'Detailansicht', Schlüssel, 'alo'|'asu'|'stellen') → Zelle."""
    overrides = overrides or {}
    day = datetime(month.year, month.month, 15)
    prev = datetime(month.year - 1, month.month, 15)
    wb = Workbook()
    wb.active.title = "Deckblatt"
    wb["Deckblatt"]["A1"] = MARK
    imp = wb.create_sheet("I")
    imp["A4"] = "Impressum"
    imp["A8"], imp["C8"] = "Titel:", "Arbeitsmarkt nach Berufen"
    imp["A12"], imp["C12"] = "Berichtsmonat:", day
    imp["A14"], imp["C14"] = "Erstellungsdatum:", datetime(month.year, month.month, 26)
    imp["A30"] = MARK
    wb.create_sheet("III")["A112"] = "Zeichenerklärung"
    state_key = {n: k for k, n in STATES}
    for series, view in ((1, "Übersicht"), (2, "Detailansicht")):
        off = 3 if series == 1 else 2  # erste Wertspalte (0-basiert): D bzw. C
        for n, region in enumerate(BERUFE_REGIONS, start=1):
            if region == skip_region:
                continue
            ws = wb.create_sheet(f"{series}.{n}")
            ws.cell(row=1, column=off + 16, value="Arbeitsmarktstatistik")
            ws["A3"] = "Arbeitsmarktdaten nach Zielberufen: Arbeitslose, Arbeitsuchende und gemeldete Arbeitsstellen"
            ws["A4"] = view
            ws["A5"] = f"Ausgewiesenes Anforderungsniveau ({MARK})"
            ws["A6"] = f"{state_key[region]} {region}" if series == 1 and region in state_key else region
            ws["A7"] = datetime(sheet_day.year, sheet_day.month, sheet_day.day) if sheet_day else day
            ws["A9"] = "Berufe nach der Klassifikation der Berufe 2010 (KldB 2010)"
            for block, title in enumerate(("Arbeitslose", "Arbeitsuchende 1)", "Gemeldete Arbeitsstellen")):
                c = off + 1 + 4 * block
                ws.cell(row=11, column=c, value=title)
                if block != 1:
                    ws.cell(row=12, column=c, value="Bestand")
                ws.cell(row=13, column=c, value=day)
                ws.cell(row=14, column=c, value=day)
                ws.cell(row=14, column=c + 1, value=prev)
                ws.cell(row=14, column=c + 2, value="absolut")
                ws.cell(row=14, column=c + 3, value="in %")
            ws.cell(row=12, column=off + 13, value="Zugang gleitende Jahressumme")
            for j in range(16):
                ws.cell(row=15, column=off + 1 + j, value=j + 1)
            r = 16
            code = ""
            rows = BERUFE_OVERVIEW if series == 1 else BERUFE_DETAIL
            for item in rows:
                if series == 1:
                    key, name, niveau, alo, asu, st = item  # type: ignore[misc]
                    if key:
                        code = key
                    ws.cell(row=r, column=1, value=key)
                    ws.cell(row=r, column=2, value=name)
                    ws.cell(row=r, column=3, value=niveau)
                    is_total = niveau == "Gesamt"
                else:
                    key, name, alo, asu, st = item  # type: ignore[misc]
                    code = key or ""
                    ws.cell(row=r, column=1, value=key)
                    ws.cell(row=r, column=2, value=name)
                    is_total = True
                for block, (ind, cell) in enumerate((("alo", alo), ("asu", asu), ("stellen", st))):
                    if is_total and (region, view, code, ind) in overrides:
                        cell = overrides[(region, view, code, ind)]
                    c = off + 1 + 4 * block
                    ws.cell(row=r, column=c, value=cell)
                    ws.cell(row=r, column=c + 1, value="- ")  # Vorjahr (wird nicht gelesen)
                    ws.cell(row=r, column=c + 3, value="x ")
                r += 1
            ws.cell(row=r, column=1, value="© niemand – " + MARK)
            ws.cell(row=r + 1, column=1, value=f"Datenstand: {month:%m/%Y}")
            ws.cell(row=r + 2, column=1, value="1) Arbeitsuchende sind arbeitslose Arbeitsuchende und nicht-arbeitslose Arbeitsuchende")
    wb.save(path)
    return path


# --------------------------------------------------------------------------------------------------------
# GENESIS / Regionaldatenbank: Export „CSV (Flat)“
# --------------------------------------------------------------------------------------------------------
def genesis_flat(path: Path, stichtag: date, regions: dict[str, tuple[str, dict[str, str]]], *,
                 age_groups: list[tuple[str, str]] | None = None, layout: str = "genesis", as_zip: bool = True,
                 extra_rows: list[list[str]] | None = None, zip_comment: bytes = b"") -> Path:
    """``regions``: Schlüssel → (Name, {Altersschlüssel: Wert als Text}); der Schlüssel ``''`` ist „Insgesamt“.

    ``layout='regio'`` erzeugt die Variante der Regionaldatenbank (zusätzliches Merkmal Geschlecht sowie
    Deutschland-/Länderzeilen; Schlüssel ``DG`` = Deutschland, 2-stellig = Land, 8-stellig = Teilgebiet).
    """
    ages = [("", "Insgesamt"), *(age_groups if age_groups is not None else AGE_GROUPS)]
    regio = layout == "regio"
    head = ["statistics_code", "statistics_label", "time_code", "time_label", "time",
            "1_variable_code", "1_variable_label", "1_variable_attribute_code", "1_variable_attribute_label",
            "2_variable_code", "2_variable_label", "2_variable_attribute_code", "2_variable_attribute_label"]
    if regio:
        head += ["3_variable_code", "3_variable_label", "3_variable_attribute_code", "3_variable_attribute_label"]
    head += ["value", "value_unit", "value_variable_code", "value_variable_label", "value_q"]
    lines = [";".join(head)]
    for key, (name, cells) in regions.items():
        var = "KREISE"
        if regio and key == "DG":
            var = "DINSG"
        elif regio and len(key) == 2:
            var = "DLAND"
        elif regio and len(key) == 3:
            var = "REGBEZ"
        for code, label in ages:
            value = cells.get(code, "0")
            sexes = [("", "Insgesamt"), ("GESM", "männlich")] if regio else [("", "")]
            for sex_code, sex_label in sexes:
                row = ["12411", "Fortschreibung des Bevölkerungsstandes (SYNTHETISCH)", "STAG", "Stichtag", stichtag.isoformat(),
                       var, "Kreise", key, name]
                if regio:
                    row += ["GES", "Geschlecht", sex_code, sex_label]
                row += ["ALTX20", "Altersgruppen", code, label,
                        value if sex_code == "" else "1", "Anzahl", "BEVSTD", "Bevölkerungsstand",
                        "e" if value.strip().isdigit() else ""]
                lines.append(";".join(row))
    for row in extra_rows or []:
        lines.append(";".join(row))
    data = ("﻿" + "\n".join(lines) + "\n").encode("utf-8")
    table = "12411-02-03-4" if regio else "12411-0017"
    if as_zip:
        with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as z:
            z.writestr(f"{table}_de_flat.csv", data)
            z.comment = zip_comment
    else:
        path.write_bytes(data)
    return path


def age_cells(base: int, **special: str) -> dict[str, str]:
    """17 Altersgruppen mit erfundenen Werten ``base + i`` und passender Gesamtsumme; ``special`` überschreibt Zellen."""
    cells = {code: str(base + i) for i, (code, _) in enumerate(AGE_GROUPS)}
    cells[""] = str(sum(int(v) for v in cells.values()))
    cells.update(special)
    return cells


# --------------------------------------------------------------------------------------------------------
# Destatis GV-ISys (Quartalsausgabe)
# --------------------------------------------------------------------------------------------------------
def gv_isys_xlsx(path: Path, stand: date, gemeinden: list[dict[str, Any]], *, title_stand: date | None = None,
                 break_header: bool = False) -> Path:
    """``gemeinden``: dicts mit ags (8-stellig), name, pop, plz, lon, lat (Koordinaten als Text mit Dezimalkomma)."""
    wb = Workbook()
    wb.active.title = "Inhalt"
    inhalt = wb["Inhalt"]
    inhalt["A9"] = "Gemeindeverzeichnis"
    inhalt["A10"] = MARK
    inhalt["A37"] = f"Gebietsstand: {stand:%d.%m.%Y} (synthetisch)"
    inhalt["A38"] = "Erscheinungsmonat: Februar 2024"
    ws = wb.create_sheet(f"Onlineprodukt_Gemeinden{stand:%d%m%Y}")
    ws["A1"] = f"Gemeinden in Deutschland nach Fläche, Bevölkerung und Postleitzahl am {(title_stand or stand):%d.%m.%Y} ({MARK})"
    heads3 = {1: "Satzart", 2: "Textkennzeichen", 3: "Amtlicher Regionalschlüssel (ARS)", 8: "Gemeindename", 9: "Fläche km2 1)",
              10: "Bevölkerung auf Grundlage des Zensus 2022 2)", 14: "Postleitzahl3)", 15: "Geografische Mittelpunktkoordinaten",
              17: "Reisegebiete", 19: "Grad der Verstädterung"}
    heads4 = {3: "Land", 4: "RB", 5: "Kreis", 6: "VB", 7: "Gem", 10: "insgesamt", 11: "männlich", 12: "weiblich", 13: "je km2",
              15: "Längengrad", 16: "Breitengrad"}
    heads5 = {3: f"Gebietsstand am {stand:%d.%m.%Y}", 9: "31.12.2023 (Jahr)", 10: "31.12.2023 (Jahr)", 15: "Zuordnungsstand am 31.12.2022"}
    if break_header:
        heads3[14] = "Telefonvorwahl"
    for row, heads in ((3, heads3), (4, heads4), (5, heads5)):
        for col, text in heads.items():
            ws.cell(row=row, column=col, value=text)
    r = 7
    seen_land: set[str] = set()
    seen_kreis: set[str] = set()
    for g in gemeinden:
        ags = g["ags"]
        land, rb, kreis, gem = ags[:2], ags[2], ags[3:5], ags[5:]
        if land not in seen_land:
            seen_land.add(land)
            for c, v in enumerate(["10", None, land, None, None, None, None, f"Testland {land} (synthetisch)"], start=1):
                ws.cell(row=r, column=c, value=v)
            r += 1
        if ags[:5] not in seen_kreis:
            seen_kreis.add(ags[:5])
            for c, v in enumerate(["40", "44", land, rb, kreis, None, None, f"Testkreis {ags[:5]} (synthetisch)"], start=1):
                ws.cell(row=r, column=c, value=v)
            r += 1
        for c, v in enumerate(["50", "50", land, rb, kreis, "0000", None, g["name"]], start=1):
            ws.cell(row=r, column=c, value=v)
        r += 1
        row = ["60", "63", land, rb, kreis, "0000", gem, g["name"], 12.5, g.get("pop"), None, None, None, g.get("plz"),
               g.get("lon"), g.get("lat"), "X01", "Testgebiet", "02", "mittlere Besiedlungsdichte"]
        for c, v in enumerate(row, start=1):
            ws.cell(row=r, column=c, value=v)
        r += 1
    ws.cell(row=r + 1, column=1, value="Quelle: SYNTHETISCH – kein Auszug aus dem Gemeindeverzeichnis-Informationssystem GV-ISys")
    ws.cell(row=r + 3, column=1, value="3) Die Gemeinde kann mehrere Postleitzahlen (PLZ) haben; hier ist die PLZ des Verwaltungssitzes angegeben.")
    wb.save(path)
    return path


# --------------------------------------------------------------------------------------------------------
# KldB 2010 (Fassung 2020): systematisches und alphabetisches Verzeichnis
# --------------------------------------------------------------------------------------------------------
KLDB_TITLE = "Klassifikation der Berufe 2010 – überarbeitete Fassung 2020"
KLDB_CLASSES = [("4", "Naturwissenschaft, Geografie und Informatik (synthetisch)"), ("43", "Informatik- und andere IKT-Berufe (synthetisch)"),
                ("431", "Informatik (synthetisch)"), ("4310", "Berufe in der Informatik (synthetisch)"),
                ("43102", "Berufe in der Informatik - fachlich ausgerichtete Tätigkeiten (synthetisch)"),
                ("43104", "Berufe in der Informatik - hoch komplexe Tätigkeiten (synthetisch)"),
                ("8", "Gesundheit, Soziales, Lehre und Erziehung (synthetisch)"), ("81", "Medizinische Gesundheitsberufe (synthetisch)"),
                ("813", "Gesundheits- und Krankenpflege (synthetisch)"), ("8130", "Berufe in der Krankenpflege (synthetisch)"),
                ("81302", "Berufe in der Krankenpflege - fachlich ausgerichtete Tätigkeiten (synthetisch)")]
KLDB_TITLES = [("Testinformatiker/in", "43102"), ("Software-Prüfingenieur/in (erfunden)", "43104"),
               ("Musterpflegefachkraft", "81302"), ("Probeberuf/Probeberufin", "81302"), ("Testinformatiker/in", "43102")]


def kldb_systematik_xlsx(path: Path, classes: list[tuple[str, str]] | None = None, *, created: date = date(2020, 12, 1),
                         title: str = KLDB_TITLE) -> Path:
    wb = Workbook()
    wb.active.title = "Impressum"
    imp = wb["Impressum"]
    imp["A4"] = "Impressum"
    imp["A8"], imp["C8"] = "Titel:", f"{title}\nSystematisches Verzeichnis ({MARK})"
    imp["A11"], imp["C11"] = "Erstellungsdatum:", datetime(created.year, created.month, created.day)
    ws = wb.create_sheet("Systematik_Langbezeichnungen")
    ws["C1"] = title
    ws["A3"] = f"Systematik (Langbezeichnungen) – {MARK}"
    ws["A5"], ws["B5"], ws["C5"] = "KldB 2010", "Langbezeichnungen der Systematikpositionen", "Filter zur Auswahl der Ebenen"
    rows = list(classes if classes is not None else KLDB_CLASSES)
    have = {c for c, _ in rows}
    rows += [(str(d), f"Testbereich {d} (synthetisch)") for d in range(10) if str(d) not in have]
    for i, (code, name) in enumerate(sorted(rows), start=6):
        ws.cell(row=i, column=1, value=code)
        ws.cell(row=i, column=2, value=name)
        ws.cell(row=i, column=3, value=f"KldB2010_{len(code)}")
    ws.cell(row=len(rows) + 7, column=1, value=f"Erstellungsdatum: {created:%d.%m.%Y}, SYNTHETISCH")
    wb.save(path)
    return path


def kldb_alphabet_xlsx(path: Path, titles: list[tuple[str, str]] | None = None, *, created: date = date(2026, 1, 20)) -> Path:
    wb = Workbook()
    wb.active.title = "Impressum"
    imp = wb["Impressum"]
    imp["A8"], imp["B8"] = "Titel:", f"{KLDB_TITLE}\nalphabetisches Verzeichnis der Berufsbenennungen ({MARK})"
    imp["A11"], imp["B11"] = "Erstellungsdatum:", datetime(created.year, created.month, created.day)
    ws = wb.create_sheet("alphabet_Verz_Berufsb")
    ws["B1"] = KLDB_TITLE
    ws["A3"] = f"Alphabetisches Verzeichnis der Berufsbenennungen – {MARK}"
    ws["A5"], ws["B5"] = "Berufsbenennungen", "KldB 2010 (5-Steller)"
    rows = titles if titles is not None else KLDB_TITLES
    for i, (title, code) in enumerate(rows, start=6):
        ws.cell(row=i, column=1, value=title)
        ws.cell(row=i, column=2, value=code)
    ws.cell(row=len(rows) + 7, column=1, value=f"Erstellungsdatum: {created:%d.%m.%Y}, SYNTHETISCH")
    ws.cell(row=len(rows) + 7, column=2, value="SYNTHETISCH – nicht von der Statistik der Bundesagentur für Arbeit")
    wb.save(path)
    return path


# --------------------------------------------------------------------------------------------------------
# BKG VG250 als GeoPackage (SQLite) – winzige erfundene Geometrien in ETRS89 / UTM 32N
# --------------------------------------------------------------------------------------------------------
def square(x_km: float, y_km: float, w_km: float = 10, h_km: float = 10) -> list[tuple[float, float]]:
    x0, y0, x1, y1 = x_km * 1000, y_km * 1000, (x_km + w_km) * 1000, (y_km + h_km) * 1000
    return [(x0, y0), (x1, y0), (x1, y1), (x0, y1), (x0, y0)]


def gpkg_geometry(rings: list[list[tuple[float, float]]], srs_id: int = 25832) -> bytes:
    """GeoPackage-Binary: Kopf (``GP``, Version 0, Flags: Little Endian + Umhüllende xy) + WKB-MultiPolygon."""
    xs = [x for ring in rings for x, _ in ring]
    ys = [y for ring in rings for _, y in ring]
    wkb = struct.pack("<BII", 1, 6, len(rings))
    for ring in rings:
        wkb += struct.pack("<BII", 1, 3, 1) + struct.pack("<I", len(ring)) + b"".join(struct.pack("<dd", x, y) for x, y in ring)
    return b"GP" + bytes([0, 0b00000011]) + struct.pack("<i", srs_id) + struct.pack("<dddd", min(xs), max(xs), min(ys), max(ys)) + wkb


# Erfundene Gebiete: zwei „Länder“ (91, 92), drei „Kreise“, fünf „Gemeinden“; Kacheln von 10 km Kantenlänge.
VG_STATES = [("91", "Testland Nord", "Land", [square(400, 5700, 20, 10)]), ("92", "Testland Süd", "Freistaat", [square(400, 5690, 20, 10)])]
VG_DISTRICTS = [
    # (Schlüssel, GEN, BEZ, NBD, Zeilen [(GF, Ringe)])
    ("91001", "Testhausen", "Kreisfreie Stadt", "ja", [(4, [square(400, 5700)])]),
    ("91002", "Nordkreis", "Landkreis", "ja", [(4, [square(410, 5700)]), (2, [square(420, 5700)])]),  # GF 2 = Wasserfläche
    ("92001", "Region Südheim", "Landkreis", "nein", [(4, [square(400, 5690)]), (4, [square(410, 5690)])]),  # zwei Landteile
]
VG_MUNICIPALITIES = [
    ("91001000", "Testhausen", "Stadt", [(4, [square(400, 5700)])]),
    ("91002001", "Neudorf", "Gemeinde", [(4, [square(410, 5700, 5, 10)])]),
    ("91002002", "Altdorf am Testbach", "Gemeinde", [(4, [square(415, 5700, 5, 10)]), (2, [square(420, 5700, 5, 10)])]),
    ("92001001", "Neudorf", "Gemeinde", [(4, [square(400, 5690)])]),
    ("92001002", "Südheim", "Stadt", [(4, [square(410, 5690)])]),
]


def vg250_gpkg(path: Path, stand: date = date(2023, 12, 31), *, districts: list[Any] | None = None,
               municipalities: list[Any] | None = None, states: list[Any] | None = None, with_ewz: bool = False,
               description: str | None = None, as_zip: bool = False) -> Path:
    """Winziges GeoPackage im Aufbau von ``DE_VG250.gpkg`` (Ebenen vg250_lan/krs/gem, Attribute GF, AGS, GEN, BEZ, NBD)."""
    gpkg = path.with_suffix(".gpkg") if as_zip else path
    gpkg.unlink(missing_ok=True)
    con = sqlite3.connect(gpkg)
    con.executescript("""
        PRAGMA application_id = 1196444487;
        CREATE TABLE gpkg_spatial_ref_sys (srs_name TEXT, srs_id INTEGER PRIMARY KEY, organization TEXT, organization_coordsys_id INTEGER, definition TEXT, description TEXT);
        CREATE TABLE gpkg_contents (table_name TEXT PRIMARY KEY, data_type TEXT, identifier TEXT, description TEXT, last_change TEXT, min_x REAL, min_y REAL, max_x REAL, max_y REAL, srs_id INTEGER);
        CREATE TABLE gpkg_geometry_columns (table_name TEXT, column_name TEXT, geometry_type_name TEXT, srs_id INTEGER, z TINYINT, m TINYINT);
        CREATE TABLE synthetisch_hinweis (text TEXT);
    """)
    con.execute("INSERT INTO synthetisch_hinweis VALUES (?)", (MARK,))
    con.execute("INSERT INTO gpkg_spatial_ref_sys VALUES ('ETRS89 / UTM zone 32N', 25832, 'EPSG', 25832, 'undefined', NULL)")
    ewz = ", EWZ INTEGER" if with_ewz else ""
    for table in ("vg250_lan", "vg250_krs", "vg250_gem"):
        con.execute(f"CREATE TABLE {table} (id INTEGER PRIMARY KEY, geom BLOB, GF SMALLINT, BSG SMALLINT, ARS TEXT, AGS TEXT, "
                    f"GEN TEXT, BEZ TEXT, NBD TEXT{ewz})")
        con.execute("INSERT INTO gpkg_contents (table_name, data_type, identifier, description, srs_id) VALUES (?, 'features', ?, ?, 25832)",
                    (table, table, description if description is not None else stand.isoformat()))
        con.execute("INSERT INTO gpkg_geometry_columns VALUES (?, 'geom', 'MULTIPOLYGON', 25832, 0, 0)", (table,))

    def add(table: str, key: str, gen: str, bez: str, nbd: str, parts: list[tuple[int, list[Any]]], pop: int | None = None) -> None:
        for gf, rings in parts:
            cols = "geom, GF, BSG, ARS, AGS, GEN, BEZ, NBD" + (", EWZ" if with_ewz else "")
            vals: list[Any] = [gpkg_geometry(rings), gf, 1, key, key, gen, bez, nbd]
            if with_ewz:
                vals.append(pop if gf == 4 else 0)
            con.execute(f"INSERT INTO {table} ({cols}) VALUES ({', '.join('?' * len(vals))})", vals)

    for key, gen, bez, rings in (states if states is not None else VG_STATES):
        add("vg250_lan", key, gen, bez, "ja", [(4, rings)])
    for key, gen, bez, nbd, parts in (districts if districts is not None else VG_DISTRICTS):
        add("vg250_krs", key, gen, bez, nbd, parts)
    for i, (key, gen, bez, parts) in enumerate(municipalities if municipalities is not None else VG_MUNICIPALITIES):
        add("vg250_gem", key, gen, bez, "ja", parts, pop=1000 * (i + 1))
    con.commit()
    con.close()
    if as_zip:
        with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as z:
            z.write(gpkg, "vg250_ebenen_1231/DE_VG250.gpkg")
            z.writestr("dokumentation/aktualitaet.txt", f"{stand:%d.%m.%Y}\r\n")
            z.writestr("SYNTHETISCH.txt", MARK)
        gpkg.unlink()
    return path
