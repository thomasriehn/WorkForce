"""Bevölkerung nach Kreisen und Altersgruppen zum Stichtag 31.12. (Fortschreibung des Bevölkerungsstandes).

Quelle ist der Export „CSV (Flat)“ der öffentlichen Tabellenansicht – entweder GENESIS-Online, Tabelle 12411-0017
(Kreise × Altersgruppen), oder ersatzweise Regionaldatenbank Deutschland, Tabelle 12411-02-03-4 (zusätzlich
Geschlecht sowie Deutschland-, Länder- und Regierungsbezirkszeilen). Beide liefern dieselben Spalten
``time``, ``<n>_variable_code``, ``<n>_variable_attribute_code/-label``, ``value``.

Besonderheiten:

* Jeder Stichtag der Datei wird ein eigener Datenstand. Weil die ZIP-Hülle bei jedem Abruf neu erzeugt wird,
  dient als Prüfsumme der sortierte Zeileninhalt des Stichtags, nicht die Datei.
* Die Tabellen führen auch aufgelöste Kreise; für sie steht am Stichtag in allen Feldern ``-``. Solche Gebiete
  werden als ``not_available`` gespeichert (kein Nullwert). Ein einzelnes ``-`` bei einem bestehenden Gebiet
  bedeutet laut Zeichenerklärung „nichts vorhanden“ und wird als echter Nullwert gespeichert.
* ``bev_15_bis_unter_65`` ist eine **eigene Berechnung**: Sie wird nur gespeichert, wenn die vorhandenen
  Altersgruppen den Bereich 15 bis unter 65 lückenlos und überschneidungsfrei abdecken und keine der dafür
  nötigen Zellen fehlt oder gesperrt ist.
"""
from __future__ import annotations

import csv
import hashlib
import io
import re
import zipfile
from collections import Counter, defaultdict
from datetime import date
from decimal import Decimal
from pathlib import Path
from typing import Any

from .common import (
    COUNTRY_KEY,
    MARKERS_DESTATIS,
    MAX_MEMBER_BYTES,
    ImportProblem,
    ParsedRelease,
    ValueRow,
    check_unrecognized,
    classify_cell,
    is_xlsx,
    is_zip,
)

DATASET_KEY = "bevoelkerung_kreise_alter"
IND_TOTAL = "bev_gesamt"
IND_AGE = "bev_altersgruppe"
IND_WORKING_AGE = "bev_15_bis_unter_65"
WORKING_AGE = (15, 65)
# Plausibilitätsgrenze: Zahl der Kreise mit Werten je Stichtag (1995: 440 … seit 2021: 400)
DISTRICTS_RANGE = (350, 480)

_REQUIRED = ("statistics_code", "time_code", "time", "1_variable_code", "1_variable_attribute_code",
             "1_variable_attribute_label", "value", "value_unit", "value_variable_code")
_AGE_CODE = re.compile(r"^ALT(\d{3})B(\d{2,3})$")
_AGE_OPEN = re.compile(r"^ALT(\d{3})UM$")
_AGE_LABEL = re.compile(r"^(\d{1,3}) bis unter (\d{1,3}) Jahren?$")
_AGE_LABEL_UNDER = re.compile(r"^unter (\d{1,3}) Jahren?$")
_AGE_LABEL_OPEN = re.compile(r"^(\d{1,3}) Jahre und (?:mehr|älter)$")
_TABLE_CODE = re.compile(r"(\d{5}-\d{2}-\d{2}-\d(?:-B)?|\d{5}-\d{4})")
_REGION_LEVELS = {"KREISE": "district", "DLAND": "state", "DINSG": "country"}
OPEN_END = 999


def age_bounds(code: str, label: str) -> tuple[int, int] | None:
    """Altersgrenzen ``[von, bis)`` aus Schlüssel (``ALT015B18``) oder Bezeichnung; ``bis = 999`` = „und mehr“."""
    if m := _AGE_CODE.match(code):
        return int(m.group(1)), int(m.group(2))
    if m := _AGE_OPEN.match(code):
        return int(m.group(1)), OPEN_END
    lab = label.strip()
    if m := _AGE_LABEL.match(lab):
        return int(m.group(1)), int(m.group(2))
    if m := _AGE_LABEL_UNDER.match(lab):
        return 0, int(m.group(1))
    if m := _AGE_LABEL_OPEN.match(lab):
        return int(m.group(1)), OPEN_END
    return None


def age_dim_key(bounds: tuple[int, int]) -> str:
    lo, hi = bounds
    return f"{lo:03d}-UM" if hi == OPEN_END else f"{lo:03d}-{hi:03d}"


def tiling(groups: dict[str, tuple[int, int]], lo: int, hi: int) -> tuple[list[str] | None, str]:
    """Altersgruppen, die ``[lo, hi)`` exakt (ohne Lücke/Überschneidung) abdecken – sonst ``None`` mit Begründung."""
    inside = sorted(((b, k) for k, b in groups.items() if b[0] < hi and b[1] > lo), key=lambda t: t[0])
    if not inside:
        return None, f"keine Altersgruppe im Bereich {lo} bis unter {hi}"
    pos = lo
    keys: list[str] = []
    for (g_lo, g_hi), key in inside:
        if g_lo < pos:
            return None, f"Altersgruppe {key} überschneidet sich mit dem Bereich davor oder ragt über {lo} hinaus"
        if g_lo > pos:
            return None, f"Lücke zwischen {pos} und {g_lo} Jahren"
        if g_hi > hi:
            return None, f"Altersgruppe {key} reicht über {hi} Jahre hinaus"
        keys.append(key)
        pos = g_hi
    if pos != hi:
        return None, f"Lücke zwischen {pos} und {hi} Jahren"
    return keys, "ok"


def _read_csv(path: Path, name: str) -> tuple[str, str]:
    """Liefert (Dateiname der CSV, Text). Akzeptiert die ZIP-Hülle des Exports oder die CSV selbst."""
    if is_xlsx(path):
        raise ImportProblem("Bitte den Export „CSV (Flat)“ der Tabelle verwenden – die XLSX-Ausgabe wird nicht unterstützt.")
    if is_zip(path):
        with zipfile.ZipFile(path) as z:
            members = [i for i in z.infolist() if not i.is_dir() and i.filename.lower().endswith(".csv")]
            if len(members) != 1:
                raise ImportProblem(f"Im ZIP wurde nicht genau eine CSV-Datei gefunden ({len(members)}).")
            if members[0].file_size > MAX_MEMBER_BYTES:
                raise ImportProblem("Die CSV-Datei im ZIP ist unerwartet groß.")
            raw = z.read(members[0])
            member = Path(members[0].filename).name
    else:
        raw, member = path.read_bytes(), name
    try:
        return member, raw.decode("utf-8-sig")
    except UnicodeDecodeError as exc:
        raise ImportProblem(f"Die CSV-Datei ist nicht UTF-8-kodiert: {exc}") from exc


def parse(path: Path, name: str) -> tuple[list[ParsedRelease], dict[str, Any], list[str]]:
    member, text = _read_csv(path, name)
    lines = text.splitlines()
    if not lines:
        raise ImportProblem("Die CSV-Datei ist leer.")
    header = next(csv.reader([lines[0]], delimiter=";"))
    idx = {h.strip(): i for i, h in enumerate(header)}
    missing = [c for c in _REQUIRED if c not in idx]
    if missing:
        raise ImportProblem("Das ist kein Export „CSV (Flat)“ der GENESIS-Tabellenansicht – es fehlen die Spalten "
                            f"{', '.join(missing)}. Bitte im Download-Dialog „CSV (Flat)“ wählen.")
    n_vars = max(n for n in range(1, 9) if f"{n}_variable_code" in idx)
    for n in range(1, n_vars + 1):
        for suffix in ("variable_code", "variable_attribute_code", "variable_attribute_label"):
            if f"{n}_{suffix}" not in idx:
                raise ImportProblem(f"Spalte {n}_{suffix} fehlt im Export.")
    reader = csv.reader(io.StringIO("\n".join(lines[1:])), delimiter=";")
    by_time: dict[str, list[list[str]]] = defaultdict(list)
    width = len(header)
    for ln, row in enumerate(reader, start=2):
        if not row:
            continue
        if len(row) != width:
            raise ImportProblem(f"Zeile {ln} der CSV hat {len(row)} statt {width} Spalten.")
        by_time[row[idx["time"]]].append(row)
    if not by_time:
        raise ImportProblem("Die CSV-Datei enthält keine Datenzeilen.")

    table = (_TABLE_CODE.search(member) or _TABLE_CODE.search(name))
    table_code = table.group(1) if table else None
    releases: list[ParsedRelease] = []
    warnings: list[str] = []
    info: dict[str, Any] = {"table": table_code, "csv_member": member, "periods": {}}
    for time_value in sorted(by_time):
        rel, rel_info, rel_warn = _parse_period(time_value, by_time[time_value], idx, n_vars, header, table_code)
        releases.append(rel)
        info["periods"][rel.period_key] = rel_info
        warnings.extend(rel_warn)
    return releases, info, warnings


def _parse_period(time_value: str, rows: list[list[str]], idx: dict[str, int], n_vars: int, header: list[str],
                  table_code: str | None) -> tuple[ParsedRelease, dict[str, Any], list[str]]:
    try:
        stichtag = date.fromisoformat(time_value)
    except ValueError as exc:
        raise ImportProblem(f"Stichtag {time_value!r} in Spalte „time“ ist kein Datum (JJJJ-MM-TT).") from exc
    what = f"Bevölkerung, Stichtag {stichtag:%d.%m.%Y}"
    skipped: Counter[str] = Counter()
    unrecognized: Counter[str] = Counter()
    # (Ebene, Schlüssel) → {Altersschlüssel: (Zelle, Bezeichnung)}
    cells: dict[tuple[str, str], dict[str, tuple[str, str]]] = defaultdict(dict)
    names: dict[tuple[str, str], str] = {}
    age_labels: dict[str, str] = {}
    for row in rows:
        if row[idx["statistics_code"]] != "12411" or row[idx["value_variable_code"]] != "BEVSTD":
            raise ImportProblem(f"{what}: Die Datei enthält andere Merkmale als den Bevölkerungsstand der Statistik 12411 "
                                f"({row[idx['statistics_code']]}/{row[idx['value_variable_code']]}).")
        if row[idx["time_code"]] != "STAG":
            raise ImportProblem(f"{what}: Zeitangabe ist kein Stichtag (time_code = {row[idx['time_code']]!r}).")
        if row[idx["value_unit"]] != "Anzahl":
            raise ImportProblem(f"{what}: Unerwartete Einheit {row[idx['value_unit']]!r}.")
        region: tuple[str, str, str] | None = None
        age: tuple[str, str] | None = None
        use = True
        for n in range(1, n_vars + 1):
            var = row[idx[f"{n}_variable_code"]]
            code = row[idx[f"{n}_variable_attribute_code"]]
            label = row[idx[f"{n}_variable_attribute_label"]]
            if var in ("KREISE", "DLAND", "DINSG", "REGBEZ"):
                region = (var, code, label)
            elif var.startswith("ALT"):
                age = (code, label)
            elif var == "GES":
                if code != "":
                    use = False  # nur „Insgesamt“; Aufgliederung nach Geschlecht wird nicht übernommen
                    skipped["geschlecht"] += 1
            else:
                raise ImportProblem(f"{what}: Unbekanntes Gliederungsmerkmal {var!r} – diese Tabelle wird nicht unterstützt.")
        if region is None or age is None:
            raise ImportProblem(f"{what}: Gebiets- oder Altersmerkmal fehlt in der Datei.")
        if not use:
            continue
        var, code, label = region
        if var == "KREISE" and len(code) == 5 and code.isdigit():
            rk = ("district", code)
        elif var == "DLAND" and len(code) == 2 and code.isdigit():
            rk = ("state", code)
        elif var == "DINSG":
            rk = ("country", COUNTRY_KEY)
        else:
            skipped["regierungsbezirk" if var == "REGBEZ" else f"{var.lower()}_{len(code)}stellig"] += 1
            continue
        if age[0] in cells[rk]:
            raise ImportProblem(f"{what}: Gebiet {code} / Altersgruppe {age[0] or 'Insgesamt'} kommt mehrfach vor.")
        cells[rk][age[0]] = (row[idx["value"]], age[1])
        names[rk] = label
        age_labels.setdefault(age[0], age[1])

    if "" not in age_labels or age_labels[""].strip() != "Insgesamt":
        raise ImportProblem(f"{what}: Die Gesamtzeile „Insgesamt“ der Altersgruppen fehlt.")
    groups: dict[str, tuple[int, int]] = {}
    dim_keys: dict[str, str] = {"": ""}
    for code, label in age_labels.items():
        if code == "":
            continue
        bounds = age_bounds(code, label)
        if bounds is None:
            dim_keys[code] = code[:64]
        else:
            dim_keys[code] = age_dim_key(bounds)
            groups[dim_keys[code]] = bounds
    if len(set(dim_keys.values())) != len(dim_keys):
        raise ImportProblem(f"{what}: Altersgruppen sind nicht eindeutig.")
    tile_keys, tile_reason = tiling(groups, *WORKING_AGE)

    values: list[ValueRow] = []
    with_data = Counter()
    without_data = Counter()
    derived = 0
    derived_missing: list[str] = []
    expected_ages = set(age_labels)
    for (level, key), by_age in sorted(cells.items()):
        if set(by_age) != expected_ages:
            raise ImportProblem(f"{what}: Für Gebiet {key} fehlen Altersgruppen in der Datei.")
        all_dash = all(c.strip() in ("-", "–") for c, _ in by_age.values())
        (without_data if all_dash else with_data)[level] += 1
        parsed: dict[str, ValueRow] = {}
        for code, (cell, label) in by_age.items():
            if all_dash:
                value, status = None, "not_available"  # Gebiet besteht am Stichtag nicht
                raw: str | None = cell
            else:
                value, status, raw = classify_cell(cell, MARKERS_DESTATIS, unrecognized)
            if value is not None and (value < 0 or value != value.to_integral_value()):
                raise ImportProblem(f"{what}: Unplausibler Bevölkerungswert für {key}: {cell!r}.")
            vr = ValueRow(IND_TOTAL if code == "" else IND_AGE, level, key, names[(level, key)], value, status, raw,
                          dim_key=dim_keys[code], dim_label=None if code == "" else label)
            parsed[dim_keys[code]] = vr
            values.append(vr)
        if tile_keys is not None and not all_dash:
            parts = [parsed[k] for k in tile_keys]
            if all(p.value_status in ("ok", "zero") and p.value is not None for p in parts):
                total = sum((p.value for p in parts if p.value is not None), Decimal(0))
                values.append(ValueRow(IND_WORKING_AGE, level, key, names[(level, key)], total,
                                       "zero" if total == 0 else "ok", None))
                derived += 1
            else:
                derived_missing.append(key)

    if not DISTRICTS_RANGE[0] <= with_data["district"] <= DISTRICTS_RANGE[1]:
        raise ImportProblem(f"{what}: {with_data['district']} Kreise mit Werten gefunden (erwartet: rund 400). "
                            "Es wurde nichts importiert.")
    warnings = check_unrecognized(unrecognized, len(values), what)
    if tile_keys is None:
        warnings.append(f"{what}: „Bevölkerung 15 bis unter 65“ nicht berechnet – {tile_reason}.")
    elif derived_missing:
        warnings.append(f"{what}: „Bevölkerung 15 bis unter 65“ für {len(derived_missing)} Gebiet(e) nicht berechnet, "
                        f"weil benötigte Altersgruppen fehlen oder gesperrt sind: {', '.join(derived_missing[:10])}"
                        + (" …" if len(derived_missing) > 10 else ""))

    # Prüfsumme über den sortierten Inhalt (die ZIP-Hülle des Exports wird bei jedem Abruf neu erzeugt)
    h = hashlib.sha256()
    h.update((";".join(header) + "\n").encode("utf-8"))
    for line in sorted(";".join(r) for r in rows):
        h.update(line.encode("utf-8") + b"\n")
    notes = [f"Stichtag laut Datei: {stichtag:%d.%m.%Y}"]
    if table_code:
        notes.append(f"Tabelle {table_code}")
    source = "Regionaldatenbank Deutschland (Statistische Ämter des Bundes und der Länder)" if n_vars >= 3 \
        else "GENESIS-Online (Statistisches Bundesamt)"
    notes.append(f"Exportformat „CSV (Flat)“ mit {n_vars} Gliederungsmerkmalen – {source}")
    if without_data:
        notes.append(f"{sum(without_data.values())} Gebiete ohne Wert am Stichtag (in der Quelle durchgängig „-“, "
                     "z. B. aufgelöste Kreise) als nicht verfügbar gespeichert")
    if tile_keys is not None:
        notes.append("Bevölkerung 15 bis unter 65: eigene Berechnung aus den Altersgruppen " + ", ".join(tile_keys))
    flags = Counter(r[idx["value_q"]] for r in rows) if "value_q" in idx else Counter()
    if flags:
        notes.append("Qualitätskennzeichen: " + ", ".join(f"{k or 'ohne'}×{v}" for k, v in sorted(flags.items())))
    notes.append("Gebietsstand in der Datei nicht ausdrücklich angegeben")
    release = ParsedRelease(period_key=stichtag.isoformat(), period_start=stichtag, period_end=stichtag,
                            checksum=h.hexdigest(), values=values, notes=notes)
    rel_info = {"regions_with_values": dict(with_data), "regions_without_values": dict(without_data),
                "age_groups": sorted(k for k in dim_keys.values() if k), "skipped_rows": dict(skipped),
                "working_age_groups": tile_keys, "working_age_regions": derived,
                "working_age_not_computed": derived_missing}
    return release, rel_info, warnings
