"""Statistik-Importe (BA-Kreisdaten, BA-Berufe, Bevölkerung) gegen SYNTHETISCHE Dateien im Originalaufbau.

Geprüft werden die abnahmerelevanten Regeln: Berichtszeitraum aus der Datei, Fehlwerte bleiben Fehlwerte, echter
Nullwert, wiederholter Import ohne Wirkung, Korrektur als neue Revision, unbekannte Gebietsschlüssel werden gemeldet,
bei Prüffehlern wird nichts geschrieben, „15 bis unter 65“ nur bei exakter Abdeckung.
"""
from __future__ import annotations

import hashlib
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest
from sqlalchemy import text as sql

from workforce.config import get_settings
from workforce.search import analytics
from workforce.stats import bevoelkerung
from workforce.stats.common import MARKERS_BA, MARKERS_DESTATIS, classify_cell
from workforce.stats.runner import ImportProblem, import_file

from .fixtures.stats import synthetic as syn
from .fixtures.stats.synthetic import small_thresholds  # noqa: F401 – pytest-Fixture

MONTH = date(2024, 3, 1)
DISTRICTS = [
    ("01901", "Testkreis Alpha (synthetisch)", 4321, 6.5),
    ("01902", "Testkreis Beta (synthetisch)", 0, "x"),        # echter Nullwert; Quote nicht veröffentlicht
    ("05901", "Testkreis Gamma (synthetisch)", "*", "..."),   # anonymisiert; Angabe fällt später an
    ("14901", "Testkreis Delta (synthetisch)", None, 12),      # leere Zelle; Quote als ganze Zahl
]


@pytest.fixture(autouse=True)
def _data_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(get_settings(), "data_dir", tmp_path / "data")


def values(db: Any, release_id: int) -> dict[tuple[str, str, str, str], tuple[Decimal | None, str, str | None]]:
    rows = db.execute(sql("SELECT indicator_key, region_level, region_key, dim_key, value, value_status, raw_value "
                          "FROM stat_value WHERE release_id = :r"), {"r": release_id}).all()
    return {(r[0], r[1], r[2], r[3]): (r[4], r[5], r[6]) for r in rows}


def counts(db: Any) -> tuple[int, int]:
    return (db.execute(sql("SELECT count(*) FROM stat_release")).scalar(), db.execute(sql("SELECT count(*) FROM stat_value")).scalar())


# --------------------------------------------------------------------------------------------------------
# Fehlwertzeichen
# --------------------------------------------------------------------------------------------------------
@pytest.mark.parametrize(("cell", "markers", "status"), [
    ("*", MARKERS_BA, "suppressed"), ("* ", MARKERS_BA, "suppressed"), ("x", MARKERS_BA, "not_available"),
    ("x ", MARKERS_BA, "not_available"), ("...", MARKERS_BA, "not_available"), (".", MARKERS_BA, "suppressed"),
    (".", MARKERS_DESTATIS, "suppressed"), ("/", MARKERS_DESTATIS, "unknown"), ("...", MARKERS_DESTATIS, "not_available"),
    ("x", MARKERS_DESTATIS, "not_available"), (None, MARKERS_BA, "unknown"), ("", MARKERS_BA, "unknown"),
    ("unsinn", MARKERS_BA, "unknown"),
])
def test_marker_never_becomes_a_number(cell, markers, status):
    value, got, raw = classify_cell(cell, markers)
    assert (value, got) == (None, status)
    assert raw == cell  # Originaltext der Zelle bleibt erhalten


def test_true_zero_and_numbers():
    assert classify_cell(0, MARKERS_BA) == (Decimal(0), "zero", "0")
    assert classify_cell("0", MARKERS_DESTATIS) == (Decimal(0), "zero", "0")
    assert classify_cell("-", MARKERS_DESTATIS) == (Decimal(0), "zero", "-")  # „nichts vorhanden“ laut Zeichenerklärung
    assert classify_cell("- ", MARKERS_BA) == (Decimal(0), "zero", "- ")
    assert classify_cell(8.1, MARKERS_BA) == (Decimal("8.1"), "ok", "8.1")
    assert classify_cell("19137", MARKERS_DESTATIS) == (Decimal(19137), "ok", "19137")
    assert classify_cell("1.234,5", MARKERS_DESTATIS)[0] == Decimal("1234.5")
    assert classify_cell("1.234", MARKERS_DESTATIS)[0] == Decimal(1234) and classify_cell("8,1", MARKERS_BA)[0] == Decimal("8.1")
    assert classify_cell("12.5", MARKERS_BA)[0] == Decimal("12.5")


# --------------------------------------------------------------------------------------------------------
# BA: Arbeitslose und Arbeitslosenquoten (Kreise)
# --------------------------------------------------------------------------------------------------------
def test_ba_kreise_period_from_file_values_and_markers(db, tmp_path, small_thresholds):  # noqa: F811
    f = syn.ba_kreise_zip(tmp_path / "SYNTHETISCH_arbeitslose-quoten.zip", MONTH, DISTRICTS)
    res = import_file("ba_arbeitslose_kreise", f, original_name="SYNTHETISCH_arbeitslose-quoten.zip")
    assert res["status"] == "imported" and res["period_key"] == "2024-03" and res["revision"] == 1
    assert res["regions"] == {"country": 1, "state": 16, "district": 4}
    assert res["skipped_rows"] == {"regierungsbezirk": 1, "gemeinde": 4}

    rel = db.execute(sql("SELECT * FROM stat_release")).mappings().one()
    # Berichtszeitraum stammt aus der Datei (März 2024), nicht aus dem Abrufdatum (heute)
    assert (rel["period_key"], rel["period_start"], rel["period_end"]) == ("2024-03", date(2024, 3, 1), date(2024, 3, 31))
    assert rel["published_on"] is None  # die Datei nennt kein Veröffentlichungsdatum → unbekannt
    assert datetime.now(UTC) - rel["retrieved_at"] < timedelta(minutes=5)
    assert rel["file_sha256"] == hashlib.sha256(f.read_bytes()).hexdigest() and rel["import_method"] == "manual"
    assert rel["gebietsstand"] == date(2024, 3, 31) and rel["is_current"] and rel["row_count"] == 42
    assert "Erstellungsdatum laut Datei: 27.03.2024" in rel["notes"]
    stored = get_settings().data_dir / rel["stored_path"]
    assert stored.is_file() and stored.name == f"{rel['file_sha256'][:8]}_SYNTHETISCH_arbeitslose-quoten.zip"
    assert stored.parent == get_settings().downloads_dir / "ba_arbeitslose_kreise" / "2024-03"

    v = values(db, rel["id"])
    assert v[("arbeitslose", "district", "01901", "")] == (Decimal(4321), "ok", "4321")
    assert v[("arbeitslose", "district", "01902", "")] == (Decimal(0), "zero", "0")           # echter Nullwert
    assert v[("arbeitslose", "district", "05901", "")] == (None, "suppressed", "*")             # anonymisiert, nie 0
    assert v[("arbeitslose", "district", "14901", "")] == (None, "unknown", None)               # leere Zelle
    assert v[("arbeitslosenquote_alle_zivilen_ep", "district", "01901", "")] == (Decimal("6.5"), "ok", "6.5")
    assert v[("arbeitslosenquote_alle_zivilen_ep", "district", "01902", "")] == (None, "not_available", "x")
    assert v[("arbeitslosenquote_alle_zivilen_ep", "district", "05901", "")] == (None, "not_available", "...")
    assert v[("arbeitslosenquote_alle_zivilen_ep", "district", "14901", "")][0] == Decimal(12)
    assert v[("arbeitslose", "state", "01", "")][0] == Decimal(1000) and v[("arbeitslose", "country", "DE", "")][1] == "ok"
    # nur der Berichtsmonat: weder die Vormonatsspalten (…7) noch die mit 0 gefüllten Folgemonate der „Übersicht_Kreise“
    assert not [k for k, (val, _, _) in v.items() if val in (Decimal(307), Decimal("300.7"))]
    assert {k[1] for k in v} == {"country", "state", "district"} and len(v) == 42
    names = dict(db.execute(sql("SELECT region_key, region_name FROM stat_value WHERE indicator_key = 'arbeitslose'")).all())
    assert names["01901"] == "Testkreis Alpha (synthetisch)" and names["01"] == "Schleswig-Holstein"
    # Arbeitslose ≠ Arbeitsuchende: eigene Kennzahl, eigene Definition – und dieses Produkt liefert dafür keine Werte
    ind = dict(db.execute(sql("SELECT key, definition FROM stat_indicator")).all())
    assert "§ 16 SGB III" in ind["arbeitslose"] and "§ 15 SGB III" in ind["arbeitsuchende"]
    assert ind["arbeitslose"] != ind["arbeitsuchende"]
    assert db.execute(sql("SELECT count(*) FROM stat_value WHERE indicator_key = 'arbeitsuchende'")).scalar() == 0


def test_reimport_is_noop_and_corrected_file_becomes_revision(db, tmp_path, small_thresholds):  # noqa: F811
    first = syn.ba_kreise_zip(tmp_path / "SYNTHETISCH_a.zip", MONTH, DISTRICTS)
    r1 = import_file("ba_arbeitslose_kreise", first)
    before = counts(db)
    again = import_file("ba_arbeitslose_kreise", first)
    assert again["status"] == "unchanged" and again["revision"] == 1 and again["rows"] == 0
    assert counts(db) == before == (1, 42)

    corrected = [("01901", "Testkreis Alpha (synthetisch)", 4400, 6.6), *DISTRICTS[1:]]
    second = syn.ba_kreise_zip(tmp_path / "SYNTHETISCH_b.zip", MONTH, corrected)
    r2 = import_file("ba_arbeitslose_kreise", second)
    assert r2["status"] == "imported" and r2["revision"] == 2 and r2["releases"][0]["replaced_revision"] == 1
    rels = db.execute(sql("SELECT id, revision, is_current FROM stat_release ORDER BY revision")).all()
    assert [(r[1], r[2]) for r in rels] == [(1, False), (2, True)]
    # die ursprünglichen Werte bleiben rekonstruierbar
    old = values(db, r1["releases"][0]["release_id"])
    new = values(db, r2["releases"][0]["release_id"])
    assert old[("arbeitslose", "district", "01901", "")][0] == Decimal(4321) and len(old) == 42
    assert new[("arbeitslose", "district", "01901", "")][0] == Decimal(4400)
    series = db.execute(sql(
        "SELECT r.revision, v.value FROM stat_value v JOIN stat_release r ON r.id = v.release_id "
        "WHERE v.indicator_key = 'arbeitslose' AND v.region_key = '01901' ORDER BY r.revision")).all()
    assert [(a, int(b)) for a, b in series] == [(1, 4321), (2, 4400)]
    current = db.execute(sql(
        "SELECT v.value FROM stat_value v JOIN stat_release r ON r.id = v.release_id AND r.is_current "
        "WHERE v.indicator_key = 'arbeitslose' AND v.region_key = '01901'")).scalars().all()
    assert [int(x) for x in current] == [4400]
    # die erste Datei erneut: bekannt, also keine dritte Revision
    assert import_file("ba_arbeitslose_kreise", first)["status"] == "unchanged"
    assert counts(db) == (2, 84)
    # ein anderer Monat ist ein eigener Datenstand (Revision 1)
    april = syn.ba_kreise_zip(tmp_path / "SYNTHETISCH_c.zip", date(2024, 4, 1), DISTRICTS)
    r3 = import_file("ba_arbeitslose_kreise", april)
    assert (r3["period_key"], r3["revision"]) == ("2024-04", 1)


def test_unknown_region_keys_are_reported_not_dropped(db, tmp_path, small_thresholds):  # noqa: F811
    for key, _ in syn.STATES:
        db.execute(sql("INSERT INTO region (country, level, key, name, gebietsstand, is_current) VALUES ('DE', 'state', :k, :n, '2023-12-31', true)"), {"k": key, "n": f"Land {key}"})
    for key in ("01901", "01902"):
        db.execute(sql("INSERT INTO region (country, level, key, name, parent_key, gebietsstand, is_current) "
                       "VALUES ('DE', 'district', :k, :n, '01', '2023-12-31', true)"), {"k": key, "n": f"Kreis {key}"})
    db.commit()
    res = import_file("ba_arbeitslose_kreise", syn.ba_kreise_zip(tmp_path / "SYNTHETISCH_a.zip", MONTH, DISTRICTS))
    assert res["unknown_region_keys"] == ["05901", "14901"] and res["unknown_region_count"] == 2
    assert any("05901" in w for w in res["warnings"])
    # importiert wurden sie trotzdem – unverändert, nicht umgeschlüsselt
    keys = set(db.execute(sql("SELECT region_key FROM stat_value WHERE region_level = 'district'")).scalars().all())
    assert keys == {"01901", "01902", "05901", "14901"}


def test_ba_kreise_validation_problems_write_nothing(db, tmp_path, monkeypatch):
    from workforce.stats import ba_kreise

    tiny = syn.ba_kreise_zip(tmp_path / "SYNTHETISCH_a.zip", MONTH, DISTRICTS)
    with pytest.raises(ImportProblem, match="rund 400"):  # Plausibilitätsgrenze der echten Dateien
        import_file("ba_arbeitslose_kreise", tiny)
    monkeypatch.setattr(ba_kreise, "DISTRICTS_RANGE", (1, 50))
    cases = {
        "blatt": syn.ba_kreise_zip(tmp_path / "SYNTHETISCH_b.zip", MONTH, DISTRICTS, sheet_name="Anders"),
        "bezugsgröße": syn.ba_kreise_zip(tmp_path / "SYNTHETISCH_c.zip", MONTH, DISTRICTS, rate_basis=False),
        "nur eine mappe": syn.ba_kreise_zip(tmp_path / "SYNTHETISCH_d.zip", MONTH, DISTRICTS, only="count"),
        "monate": syn.ba_kreise_zip(tmp_path / "SYNTHETISCH_e.zip", MONTH, DISTRICTS, rate_month=date(2024, 2, 1)),
        "doppelt": syn.ba_kreise_zip(tmp_path / "SYNTHETISCH_f.zip", MONTH, [*DISTRICTS, DISTRICTS[0]]),
        "negativ": syn.ba_kreise_zip(tmp_path / "SYNTHETISCH_g.zip", MONTH, [("01901", "Testkreis", -5, 1.0)]),
    }
    patterns = {"blatt": "Gesamt", "bezugsgröße": "zivilen Erwerbspersonen", "nur eine mappe": "2 –", "monate": "Berichtsmonat",
                "doppelt": "mehrfach", "negativ": "Negativer Wert"}
    for name, path in cases.items():
        with pytest.raises(ImportProblem, match=patterns[name]):
            import_file("ba_arbeitslose_kreise", path)
    garbage = tmp_path / "SYNTHETISCH_kaputt.zip"
    garbage.write_bytes(b"das ist kein ZIP")
    with pytest.raises(ImportProblem, match="ZIP-Datei"):
        import_file("ba_arbeitslose_kreise", garbage)
    single = tmp_path / "SYNTHETISCH_einzeln.xlsx"
    syn._ba_kreise_book("count", MONTH, DISTRICTS).save(single)
    with pytest.raises(ImportProblem, match="ZIP-Datei"):
        import_file("ba_arbeitslose_kreise", single)
    with pytest.raises(ImportProblem, match="Unbekannter Datensatz"):
        import_file("gibt_es_nicht", tiny)
    with pytest.raises(ImportProblem, match="nicht gefunden"):
        import_file("ba_arbeitslose_kreise", tmp_path / "fehlt.zip")
    assert counts(db) == (0, 0)
    assert not (get_settings().downloads_dir / "ba_arbeitslose_kreise").exists()  # auch keine Datei abgelegt


# --------------------------------------------------------------------------------------------------------
# BA: Arbeitsmarkt nach Berufen
# --------------------------------------------------------------------------------------------------------
def test_ba_berufe_levels_dims_and_markers(db, tmp_path):
    overrides = {
        ("Bremen", "Detailansicht", "43104", "stellen"): "- ",   # nichts vorhanden → echter Nullwert
        ("Bremen", "Detailansicht", "43104", "alo"): "* ",       # anonymisiert
        ("Sachsen", "Übersicht", "43", "asu"): "x ",             # nicht sinnvoll
        ("Hamburg", "Übersicht", "Insgesamt", "asu"): 2222,
    }
    f = syn.ba_berufe_xlsx(tmp_path / "SYNTHETISCH_berufe-heft.xlsx", MONTH, overrides)
    res = import_file("ba_berufe", f)
    assert res["status"] == "imported" and res["period_key"] == "2024-03"
    assert res["skipped_sheets"] == ["1.2", "1.3", "2.2", "2.3"]  # West-/Ostdeutschland
    rel = db.execute(sql("SELECT * FROM stat_release")).mappings().one()
    assert (rel["period_start"], rel["period_end"], rel["published_on"]) == (date(2024, 3, 1), date(2024, 3, 31), None)
    assert "Datumsangabe der Tabellen: 15.03.2024" in rel["notes"]
    v = values(db, rel["id"])
    # nur Deutschland und Länder – das Produkt hat keine Kreisebene, und es wird keine erzeugt
    assert {k[1] for k in v} == {"country", "state"}
    assert {k[2] for k in v if k[1] == "state"} == {s for s, _ in syn.STATES}
    # Arbeitslose und Arbeitsuchende getrennt (Insgesamt = dim_key '')
    assert v[("arbeitslose_beruf", "country", "DE", "")][0] == Decimal(1000)
    assert v[("arbeitsuchende_beruf", "country", "DE", "")][0] == Decimal(1700)
    assert v[("gemeldete_stellen_beruf", "country", "DE", "")][0] == Decimal(300)
    assert v[("arbeitsuchende_beruf", "state", "02", "")][0] == Decimal(2222)
    # „Arbeitsuchende“ insgesamt: feinste belegte Ebene sind die Länder – als eigene Kennzahl neben „Arbeitslose“
    asu = {k[2]: val for k, (val, _, _) in v.items() if k[0] == "arbeitsuchende"}
    assert len(asu) == 17 and asu["DE"] == Decimal(1700) and asu["02"] == Decimal(2222)
    assert {k[1] for k in v if k[0] == "arbeitsuchende"} == {"country", "state"} and {k[3] for k in v if k[0] == "arbeitsuchende"} == {""}
    # 2-/3-Steller aus der Übersicht (alle Anforderungsniveaus = 120), nicht der Wert „ohne Helfer“ (111) der Detailansicht
    assert v[("arbeitslose_beruf", "country", "DE", "43")][0] == Decimal(120)
    assert {k[3] for k in v if k[2] == "DE"} == {"", "43", "431", "43102", "43104"}  # kein 4-Steller, keine Niveau-Zeilen
    assert v[("gemeldete_stellen_beruf", "state", "04", "43104")] == (Decimal(0), "zero", "- ")
    assert v[("arbeitslose_beruf", "state", "04", "43104")] == (None, "suppressed", "* ")
    assert v[("arbeitsuchende_beruf", "state", "14", "43")] == (None, "not_available", "x ")
    row = db.execute(sql("SELECT dim_label, classification_version, region_name FROM stat_value WHERE region_key = '14' AND dim_key = '43102' LIMIT 1")).one()
    assert row == ("Informatik (o.S.) - Fachkraft (synthetisch)", "KldB 2010/2020", "Sachsen")
    assert res["unknown_region_keys"] == []
    assert import_file("ba_berufe", f)["status"] == "unchanged"


def test_ba_berufe_validation(db, tmp_path):
    with pytest.raises(ImportProblem, match="fehlen Regionen: 14"):
        import_file("ba_berufe", syn.ba_berufe_xlsx(tmp_path / "SYNTHETISCH_a.xlsx", MONTH, skip_region="Sachsen"))
    with pytest.raises(ImportProblem, match="passt nicht zum Berichtsmonat"):
        import_file("ba_berufe", syn.ba_berufe_xlsx(tmp_path / "SYNTHETISCH_b.xlsx", MONTH, sheet_day=date(2024, 2, 15)))
    kreise = syn.ba_kreise_zip(tmp_path / "SYNTHETISCH_c.zip", MONTH, DISTRICTS)
    with pytest.raises(ImportProblem, match="Excel-Arbeitsmappe"):
        import_file("ba_berufe", kreise)
    assert counts(db) == (0, 0)


# --------------------------------------------------------------------------------------------------------
# Bevölkerung nach Altersgruppen
# --------------------------------------------------------------------------------------------------------
STICHTAG = date(2023, 12, 31)
ALL_DASH = {code: "-" for code in ["", *(c for c, _ in syn.AGE_GROUPS)]}
POPULATION = {
    "01901": ("Testkreis Alpha (synthetisch)", syn.age_cells(100)),
    "01902": ("Testkreis Beta (synthetisch)", syn.age_cells(200, ALT030B35=".")),                  # benötigte Gruppe gesperrt
    "05901": ("Testkreis Gamma (synthetisch)", syn.age_cells(300, ALT000B03="-")),                 # echter Nullwert außerhalb 15–65
    "14901": ("Testkreis Delta (bis 31.12.2019) (synthetisch)", ALL_DASH),                         # aufgelöster Kreis
    "14902": ("Testkreis Epsilon (synthetisch)", syn.age_cells(400, ALT075UM="/", ALT065B75="...", ALT010B15="x")),
}


def test_population_period_markers_and_working_age(db, tmp_path, small_thresholds):  # noqa: F811
    f = syn.genesis_flat(tmp_path / "SYNTHETISCH_12411-0017_de_flat.zip", STICHTAG, POPULATION)
    res = import_file("bevoelkerung_kreise_alter", f)
    assert res["status"] == "imported" and res["period_key"] == "2023-12-31" and res["table"] == "12411-0017"
    rel = db.execute(sql("SELECT * FROM stat_release")).mappings().one()
    assert (rel["period_start"], rel["period_end"], rel["published_on"], rel["gebietsstand"]) == (STICHTAG, STICHTAG, None, None)
    assert "eigene Berechnung aus den Altersgruppen 015-018" in rel["notes"]
    v = values(db, rel["id"])
    expected = sum(100 + i for i in range(4, 15))  # Gruppen 15–18 … 60–65
    assert v[("bev_15_bis_unter_65", "district", "01901", "")] == (Decimal(expected), "ok", None)
    assert v[("bev_gesamt", "district", "01901", "")][0] == Decimal(sum(100 + i for i in range(17)))
    assert v[("bev_altersgruppe", "district", "01901", "015-018")] == (Decimal(104), "ok", "104")
    assert v[("bev_altersgruppe", "district", "01901", "075-UM")][0] == Decimal(116)
    # gesperrte benötigte Altersgruppe: Fehlwert bleibt Fehlwert, und der abgeleitete Wert fehlt ganz
    assert v[("bev_altersgruppe", "district", "01902", "030-035")] == (None, "suppressed", ".")
    assert ("bev_15_bis_unter_65", "district", "01902", "") not in v
    # „-“ bei einem bestehenden Kreis = nichts vorhanden (echter Nullwert); Summe wird trotzdem gebildet
    assert v[("bev_altersgruppe", "district", "05901", "000-003")] == (Decimal(0), "zero", "-")
    assert v[("bev_15_bis_unter_65", "district", "05901", "")][0] == Decimal(sum(300 + i for i in range(4, 15)))
    # aufgelöster Kreis: durchgängig „-“ → nicht verfügbar, kein Nullwert, kein abgeleiteter Wert
    assert {v[k][1] for k in v if k[2] == "14901"} == {"not_available"} and all(v[k][0] is None for k in v if k[2] == "14901")
    assert ("bev_15_bis_unter_65", "district", "14901", "") not in v
    # weitere Zeichen außerhalb des benötigten Bereichs
    assert v[("bev_altersgruppe", "district", "14902", "075-UM")] == (None, "unknown", "/")
    assert v[("bev_altersgruppe", "district", "14902", "065-075")] == (None, "not_available", "...")
    assert v[("bev_altersgruppe", "district", "14902", "010-015")] == (None, "not_available", "x")
    assert ("bev_15_bis_unter_65", "district", "14902", "") in v
    label = db.execute(sql("SELECT dim_label FROM stat_value WHERE dim_key = '015-018' LIMIT 1")).scalar()
    assert label == "15 bis unter 18 Jahre"
    assert res["periods"]["2023-12-31"]["working_age_not_computed"] == ["01902"]
    assert res["periods"]["2023-12-31"]["regions_without_values"] == {"district": 1}
    assert any("01902" in w for w in res["warnings"])

    # der Leser der Anwendung bekommt nur echte, positive Nenner
    pop, release = analytics.population_15_65(db)
    assert set(pop) == {"01901", "05901", "14902"} and pop["01901"] == float(expected)
    assert release["period_key"] == "2023-12-31"
    definition = db.execute(sql("SELECT definition, name FROM stat_indicator WHERE key = 'bev_15_bis_unter_65'")).one()
    assert "Eigene Berechnung aus den Altersgruppen" in definition[0] and "eigene Berechnung" in definition[1]

    # Der Export wird bei jedem Abruf neu verpackt: gleiche Zeilen in anderer ZIP-Hülle sind kein neuer Datenstand
    again = syn.genesis_flat(tmp_path / "SYNTHETISCH_erneut.zip", STICHTAG, dict(reversed(POPULATION.items())), zip_comment=b"anders")
    assert hashlib.sha256(again.read_bytes()).hexdigest() != hashlib.sha256(f.read_bytes()).hexdigest()
    assert import_file("bevoelkerung_kreise_alter", again)["status"] == "unchanged"
    assert counts(db)[0] == 1
    # berichtigter Wert → Revision 2
    changed = dict(POPULATION, **{"01901": ("Testkreis Alpha (synthetisch)", syn.age_cells(100, ALT015B18="999"))})
    r2 = import_file("bevoelkerung_kreise_alter", syn.genesis_flat(tmp_path / "SYNTHETISCH_korrektur.zip", STICHTAG, changed))
    assert r2["revision"] == 2
    assert analytics.population_15_65(db)[0]["01901"] == float(expected - 104 + 999)


def test_working_age_only_for_exact_tiling(db, tmp_path, small_thresholds):  # noqa: F811
    region = {"01901": ("Testkreis Alpha (synthetisch)", syn.age_cells(100))}
    gap = [g for g in syn.AGE_GROUPS if g[0] != "ALT030B35"]
    overlap = [*syn.AGE_GROUPS, ("ALT015B25", "15 bis unter 25 Jahre")]
    beyond = [("ALT000B15", "unter 15 Jahre"), ("ALT015B45", "15 bis unter 45 Jahre"), ("ALT045B70", "45 bis unter 70 Jahre"), ("ALT070UM", "70 Jahre und mehr")]
    for i, (groups, reason) in enumerate(((gap, "Lücke zwischen 30 und 35"), (overlap, "überschneidet"), (beyond, "reicht über 65"))):
        f = syn.genesis_flat(tmp_path / f"SYNTHETISCH_{i}.csv", date(2020 + i, 12, 31), region, age_groups=groups, as_zip=False)
        res = import_file("bevoelkerung_kreise_alter", f)
        assert res["status"] == "imported"
        assert db.execute(sql("SELECT count(*) FROM stat_value WHERE indicator_key = 'bev_15_bis_unter_65'")).scalar() == 0
        assert any(reason in w for w in res["warnings"]), res["warnings"]
    # gröbere, aber exakt passende Gruppen (über die Bezeichnung erkannt) werden akzeptiert
    coarse = [("A", "unter 15 Jahre"), ("B", "15 bis unter 40 Jahre"), ("C", "40 bis unter 65 Jahre"), ("D", "65 Jahre und mehr")]
    cells = {"": "100", "A": "10", "B": "30", "C": "40", "D": "20"}
    f = syn.genesis_flat(tmp_path / "SYNTHETISCH_grob.csv", date(2019, 12, 31), {"01901": ("Testkreis", cells)}, age_groups=coarse, as_zip=False)
    import_file("bevoelkerung_kreise_alter", f)
    got = db.execute(sql("SELECT v.value FROM stat_value v JOIN stat_release r ON r.id = v.release_id "
                         "WHERE v.indicator_key = 'bev_15_bis_unter_65' AND r.period_key = '2019-12-31'")).scalars().all()
    assert [int(x) for x in got] == [70]


def test_tiling_rules():
    g = {"015-018": (15, 18), "018-065": (18, 65)}
    assert bevoelkerung.tiling(g, 15, 65)[0] == ["015-018", "018-065"]
    assert bevoelkerung.tiling({"010-018": (10, 18), "018-065": (18, 65)}, 15, 65)[0] is None      # ragt unter 15
    assert bevoelkerung.tiling({"015-018": (15, 18), "020-065": (20, 65)}, 15, 65)[0] is None      # Lücke
    assert bevoelkerung.tiling({"015-040": (15, 40), "030-065": (30, 65)}, 15, 65)[0] is None      # Überschneidung
    assert bevoelkerung.tiling({"015-060": (15, 60)}, 15, 65)[0] is None                           # endet zu früh
    assert bevoelkerung.tiling({"000-015": (0, 15), "065-UM": (65, 999)}, 15, 65)[0] is None       # nichts im Bereich
    assert bevoelkerung.age_bounds("ALT015B18", "") == (15, 18) and bevoelkerung.age_bounds("ALT075UM", "") == (75, 999)
    assert bevoelkerung.age_bounds("", "unter 3 Jahre") == (0, 3) and bevoelkerung.age_bounds("X", "kein Alter") is None


def test_population_regionaldatenbank_layout_and_two_stichtage(db, tmp_path, small_thresholds):  # noqa: F811
    regions = {
        "DG": ("Deutschland", syn.age_cells(9000)),
        "01": ("Schleswig-Holstein", syn.age_cells(5000)),
        "011": ("Statistische Region Test (synthetisch)", syn.age_cells(4000)),
        "01901": ("Testkreis Alpha (synthetisch)", syn.age_cells(100)),
        "01901001": ("Teilgebiet (synthetisch)", syn.age_cells(50)),  # 8-stellige Untereinheit – würde doppelt zählen
    }
    other = syn.genesis_flat(tmp_path / "SYNTHETISCH_x.csv", date(2022, 12, 31), {"01901": ("Testkreis Alpha (synthetisch)", syn.age_cells(90))},
                             layout="regio", as_zip=False)
    extra = [line.split(";") for line in other.read_text(encoding="utf-8-sig").splitlines()[1:]]
    f = syn.genesis_flat(tmp_path / "SYNTHETISCH_12411-02-03-4_de_flat.zip", STICHTAG, regions, layout="regio", extra_rows=extra)
    res = import_file("bevoelkerung_kreise_alter", f)
    assert res["table"] == "12411-02-03-4" and [r["period_key"] for r in res["releases"]] == ["2022-12-31", "2023-12-31"]
    assert res["periods"]["2023-12-31"]["skipped_rows"] == {"geschlecht": 90, "regierungsbezirk": 18, "kreise_8stellig": 18}
    rel = db.execute(sql("SELECT id, notes FROM stat_release WHERE period_key = '2023-12-31'")).one()
    v = values(db, rel[0])
    assert {(k[1], k[2]) for k in v} == {("country", "DE"), ("state", "01"), ("district", "01901")}
    assert v[("bev_gesamt", "district", "01901", "")][0] == Decimal(sum(100 + i for i in range(17)))  # „Insgesamt“, nicht „männlich“
    assert v[("bev_15_bis_unter_65", "state", "01", "")][0] == Decimal(sum(5000 + i for i in range(4, 15)))
    assert "Regionaldatenbank" in rel[1]
    assert counts(db)[0] == 2


def test_population_validation(db, tmp_path, small_thresholds, monkeypatch):  # noqa: F811
    bad = tmp_path / "SYNTHETISCH_falsch.csv"
    bad.write_text("Tabelle: 12411-0017\nkein;flat;export\n", encoding="utf-8")
    with pytest.raises(ImportProblem, match="CSV \\(Flat\\)"):
        import_file("bevoelkerung_kreise_alter", bad)
    wrong_stat = syn.genesis_flat(tmp_path / "SYNTHETISCH_a.csv", STICHTAG, {"01901": ("T", syn.age_cells(1))}, as_zip=False)
    wrong_stat.write_text(wrong_stat.read_text(encoding="utf-8-sig").replace("BEVSTD", "ANDERES"), encoding="utf-8")
    with pytest.raises(ImportProblem, match="andere Merkmale"):
        import_file("bevoelkerung_kreise_alter", wrong_stat)
    monkeypatch.setattr(bevoelkerung, "DISTRICTS_RANGE", (350, 480))
    with pytest.raises(ImportProblem, match="rund 400"):
        import_file("bevoelkerung_kreise_alter", syn.genesis_flat(tmp_path / "SYNTHETISCH_b.zip", STICHTAG, POPULATION))
    assert counts(db) == (0, 0)
