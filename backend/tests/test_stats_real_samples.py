"""Optionaler Test mit ECHTEN, einmalig heruntergeladenen Originaldateien (nicht im Repository).

Läuft nur, wenn ``WF_REAL_SAMPLES_DIR`` auf das Verzeichnis mit den Proben zeigt (Unterordner ``A_ba_kreise``,
``B_ba_berufe``, ``C_genesis_12411``, ``D_regionalstatistik``, ``E_vg250``, ``F_kldb``, ``G_gvisys``). Es findet kein
Netzzugriff statt. Geprüft werden plausible Invarianten, keine einzelnen amtlichen Werte – mit Ausnahme der Summen,
die sich aus den Dateien selbst gegenseitig bestätigen.

Aufruf (Ausgabe der Kennzahlen mit ``-s``)::

    WF_REAL_SAMPLES_DIR=/pfad/zu/stats uv run pytest tests/test_stats_real_samples.py -s
"""
from __future__ import annotations

import os
from datetime import date
from pathlib import Path

import pytest
from sqlalchemy import text as sql

from workforce.config import get_settings
from workforce.geo.matcher import GeoMatcher
from workforce.normalize.occupation import OccupationClassifier
from workforce.search import analytics
from workforce.sources.base import RawLocation
from workforce.stats.runner import import_file

SAMPLES = os.environ.get("WF_REAL_SAMPLES_DIR")
pytestmark = [pytest.mark.skipif(not SAMPLES, reason="WF_REAL_SAMPLES_DIR ist nicht gesetzt (echte Probedateien nicht vorhanden)"),
              pytest.mark.timeout(600)]

FILES = {
    "vg250": "E_vg250/vg250_12-31.utm32s.gpkg.ebenen.zip",
    "gv_isys": "G_gvisys/AuszugGV3QAktuell.xlsx",
    "kldb_systematik": "F_kldb/Systematisches-Verzeichnis-KldB-2020.xlsx",
    "kldb_alphabet": "F_kldb/Alphabetisches-Verzeichnis-Berufsbenennungen.xlsx",
    "ba_kreise": "A_ba_kreise/arbeitslose-quoten-dlk-0-zip.zip",
    "ba_berufe": "B_ba_berufe/berufe-heft-kldb2010-dwol-0-202610-xlsx.xlsx",
    "bevoelkerung": "C_genesis_12411/12411-0017_de_flat.zip",
    "bevoelkerung_regio": "D_regionalstatistik/12411-02-03-4_de_flat.zip",
    "bevoelkerung_mehrere": "C_genesis_12411/multi_2stichtage/12411-0017_de_flat.zip",
}


def sample(key: str) -> Path:
    path = Path(SAMPLES or "") / FILES[key]
    if not path.is_file():
        pytest.skip(f"Probedatei fehlt: {path}")
    return path


def scalar(db, query: str, **params):
    return db.execute(sql(query), params).scalar()


@pytest.fixture(autouse=True)
def _data_dir(tmp_path, monkeypatch):
    monkeypatch.setattr(get_settings(), "data_dir", tmp_path / "data")
    monkeypatch.setattr(get_settings(), "stats_keep_source_files", False)  # die großen Originale nicht kopieren


def test_real_samples_end_to_end(db):
    # --- Gebietsstand -------------------------------------------------------------------------------
    vg = import_file("vg250", sample("vg250"))
    assert vg["status"] == "imported" and (vg["states"], vg["districts"]) == (16, 400)
    assert 10_500 < vg["municipalities"] < 11_500 and vg["simplify_method"] == "shared_borders" and vg["warnings"] == []
    stand = date.fromisoformat(vg["period_key"])
    assert (stand.month, stand.day) == (12, 31)
    geo = db.execute(sql(
        "SELECT count(*), sum(area_km2), bool_and(ST_IsValid(geom) AND ST_IsValid(geom_simple)), sum(length(ST_AsGeoJSON(geom_simple, 5))), "
        "sum(ST_NPoints(geom)), sum(ST_NPoints(geom_simple)) FROM region WHERE level = 'district' AND is_current")).one()
    assert geo[0] == 400 and 356_000 < float(geo[1]) < 358_500 and geo[2] is True
    assert geo[3] < 3_000_000  # vereinfachtes Kreis-GeoJSON bleibt klein genug für die Karte
    overlap = scalar(db, "SELECT coalesce(sum(ST_Area(ST_Intersection(a.geom_simple, b.geom_simple)::geography)), 0) FROM region a JOIN region b "
                         "ON a.level = 'district' AND b.level = 'district' AND a.is_current AND b.is_current AND a.key < b.key "
                         "AND ST_Intersects(a.geom_simple, b.geom_simple)")
    assert overlap < 1_000  # m² – Nachbarkreise teilen sich dieselbe vereinfachte Grenze
    leipzig = db.execute(sql("SELECT r.name, r.type_label, s.name, r.area_km2 FROM region r JOIN region s ON s.level = 'state' AND s.key = r.parent_key "
                             "AND s.is_current WHERE r.level = 'district' AND r.key = '14713' AND r.is_current")).one()
    assert leipzig[:3] == ("Leipzig", "Kreisfreie Stadt", "Sachsen") and 290 < float(leipzig[3]) < 305
    m = GeoMatcher(db)
    assert m.match(RawLocation(lat=51.3397, lon=12.3731)).kreis_key == "14713"   # Leipzig, Innenstadt
    assert m.match(RawLocation(lat=52.52, lon=13.405)).kreis_key == "11000"      # Berlin
    assert m.match(RawLocation(lat=54.5, lon=6.5)).kreis_key is None             # offene Nordsee – Wasserflächen zählen nicht
    assert m.match(RawLocation(locality="Landkreis Leipzig")).kreis_key == "14729"
    assert m.match(RawLocation(locality="Leipzig")).kreis_key == "14713"
    assert m.match(RawLocation(locality="Region Hannover")).kreis_key == "03241"
    assert import_file("vg250", sample("vg250"))["status"] == "unchanged"
    print(f"\nVG250 {vg['period_key']}: 16 Länder, {vg['districts']} Kreise, {vg['municipalities']} Gemeinden, {vg['district_aliases']} Kreis-Aliase; "
          f"Fläche {float(geo[1]):.0f} km²; Stützpunkte {geo[4]} → {geo[5]}; GeoJSON (5 Nachkommastellen) {geo[3]} Bytes; Überlappung {overlap:.1f} m²")

    # --- Gemeindeverzeichnis ---------------------------------------------------------------------------
    gv = import_file("gv_isys", sample("gv_isys"))
    assert gv["status"] == "imported" and 10_500 < gv["municipalities"] < 11_500 and 380 <= gv["district_rows"] <= 420
    assert 80_000_000 < gv["population_sum"] < 86_000_000 and gv["places_enriched"] > 10_000
    assert scalar(db, "SELECT count(*) FROM postal_code") == gv["postal_codes"] > 10_000
    lpz = db.execute(sql("SELECT postal_code, population FROM geo_place WHERE ags = '14713000'")).one()
    assert lpz[0] and lpz[0].startswith("04") and lpz[1] > 500_000
    print(f"GV-ISys {gv['period_key']}: {gv['municipalities']} Gemeinden, Bevölkerung {gv['population_sum']}, ergänzt {gv['places_enriched']}, neu {gv['places_added']}, "
          f"PLZ-Zeilen {gv['postal_codes']} ({gv['distinct_postal_codes']} verschiedene), nicht übernommen {gv['skipped_unknown_kreis']}, "
          f"ohne Eintrag im Verzeichnis {gv['places_not_in_file_count']}")

    # --- KldB -------------------------------------------------------------------------------------------
    ks = import_file("kldb2010", sample("kldb_systematik"))
    ka = import_file("kldb2010", sample("kldb_alphabet"))
    assert ks["levels"] == {"1": 10, "2": 37, "3": 144, "4": 702, "5": 1300}
    assert ka["titles"] > 18_000 and ka["unknown_kldb_codes"] == [] and ka["warnings"] == []
    clf = OccupationClassifier(db)
    hit = clf.classify(None, "Altenpfleger (m/w/d)")
    assert hit is not None and hit.code.startswith("821") and hit.source == "title_exact"
    dev = clf.classify(None, "Softwareentwickler/in")
    assert dev is not None and dev.code.startswith("434") and dev.requirement_level in (2, 3, 4)
    print(f"KldB: {sum(ks['levels'].values())} Systematikpositionen {ks['levels']}, {ka['titles']} Berufsbenennungen "
          f"({ka['ambiguous_titles']} mehrdeutig); Altenpfleger → {hit.code}, Softwareentwickler/in → {dev.code}")

    # --- BA: Kreise -------------------------------------------------------------------------------------
    bk = import_file("ba_arbeitslose_kreise", sample("ba_kreise"))
    assert bk["status"] == "imported" and bk["regions"]["state"] == 16 and 380 <= bk["regions"]["district"] <= 420
    rid = bk["releases"][0]["release_id"]
    total = scalar(db, "SELECT value FROM stat_value WHERE release_id = :r AND indicator_key = 'arbeitslose' AND region_level = 'country'", r=rid)
    by_state = scalar(db, "SELECT sum(value) FROM stat_value WHERE release_id = :r AND indicator_key = 'arbeitslose' AND region_level = 'state'", r=rid)
    by_kreis = scalar(db, "SELECT sum(value) FROM stat_value WHERE release_id = :r AND indicator_key = 'arbeitslose' AND region_level = 'district'", r=rid)
    assert total == by_state == by_kreis and 1_500_000 < total < 6_000_000  # Länder- und Kreissummen ergeben den Bundeswert
    rate = scalar(db, "SELECT value FROM stat_value WHERE release_id = :r AND indicator_key = 'arbeitslosenquote_alle_zivilen_ep' AND region_level = 'country'", r=rid)
    assert 2 < rate < 15
    rates = db.execute(sql("SELECT min(value), max(value), count(*) FILTER (WHERE value IS NULL) FROM stat_value WHERE release_id = :r "
                           "AND indicator_key = 'arbeitslosenquote_alle_zivilen_ep' AND region_level = 'district'"), {"r": rid}).one()
    assert 0.5 < rates[0] < rates[1] < 25
    assert scalar(db, "SELECT count(*) FROM stat_value WHERE indicator_key = 'arbeitsuchende'") == 0  # das Produkt enthält keine Arbeitsuchenden
    lz = db.execute(sql("SELECT indicator_key, value, region_name FROM stat_value WHERE release_id = :r AND region_key = '14713' ORDER BY 1"), {"r": rid}).all()
    print(f"BA Kreise {bk['period_key']}: {bk['regions']}, Arbeitslose Deutschland {int(total)} (= Summe Länder = Summe Kreise), Quote {rate} %, "
          f"Kreisquoten {rates[0]}–{rates[1]} %, unbekannte Schlüssel {bk['unknown_region_keys']}; Leipzig: {[(a, float(b)) for a, b, _ in lz]}")

    # --- BA: Berufe -------------------------------------------------------------------------------------
    bb = import_file("ba_berufe", sample("ba_berufe"))
    rid_b = bb["releases"][0]["release_id"]
    assert bb["status"] == "imported" and bb["period_key"] == bk["period_key"] and bb["unknown_kldb_codes"] == []
    levels = dict(db.execute(sql("SELECT region_level, count(DISTINCT region_key) FROM stat_value WHERE release_id = :r GROUP BY 1"), {"r": rid_b}).all())
    assert levels == {"country": 1, "state": 16}  # keine Kreisebene – und keine erfundene
    de = dict(db.execute(sql("SELECT indicator_key, value FROM stat_value WHERE release_id = :r AND region_level = 'country' AND dim_key = ''"), {"r": rid_b}).all())
    assert de["arbeitslose_beruf"] == total  # gleicher Berichtsmonat: beide BA-Produkte nennen denselben Bundeswert
    assert de["arbeitsuchende"] == de["arbeitsuchende_beruf"]
    assert dict(db.execute(sql("SELECT region_level, count(*) FROM stat_value WHERE indicator_key = 'arbeitsuchende' GROUP BY 1")).all()) == {
        "country": 1, "state": 16}  # Arbeitsuchende nur für Deutschland und Länder – keine Kreiswerte
    assert de["arbeitsuchende_beruf"] > de["arbeitslose_beruf"] > de["gemeldete_stellen_beruf"] > 0
    states_sum = scalar(db, "SELECT sum(value) FROM stat_value WHERE release_id = :r AND region_level = 'state' AND dim_key = '' AND indicator_key = 'arbeitsuchende_beruf'", r=rid_b)
    # Bei den Arbeitsuchenden liegt die Ländersumme laut Quelle leicht unter dem Bundeswert (nicht zuordenbare Fälle)
    assert 0.99 * float(de["arbeitsuchende_beruf"]) < float(states_sum) <= float(de["arbeitsuchende_beruf"])
    alo_states = scalar(db, "SELECT sum(value) FROM stat_value WHERE release_id = :r AND region_level = 'state' AND dim_key = '' AND indicator_key = 'arbeitslose_beruf'", r=rid_b)
    assert alo_states == de["arbeitslose_beruf"]
    status = dict(db.execute(sql("SELECT value_status, count(*) FROM stat_value WHERE release_id = :r GROUP BY 1"), {"r": rid_b}).all())
    assert set(status) <= {"ok", "zero", "suppressed"} and status["suppressed"] > 0
    assert scalar(db, "SELECT count(*) FROM stat_value WHERE release_id = :r AND value_status <> 'ok' AND value_status <> 'zero' AND value IS NOT NULL", r=rid_b) == 0
    print(f"BA Berufe {bb['period_key']}: {bb['rows']} Werte, {levels}, Deutschland { {k: int(v) for k, v in de.items()} }, Status {status}, Schlüssellängen {bb['dims']}")

    # --- Bevölkerung -------------------------------------------------------------------------------------
    bv = import_file("bevoelkerung_kreise_alter", sample("bevoelkerung"))
    period = bv["period_key"]
    info = bv["periods"][period]
    assert bv["status"] == "imported" and info["regions_with_values"]["district"] == 400 == info["working_age_regions"]
    assert len(info["age_groups"]) == 17 and info["working_age_groups"][0] == "015-018" and info["working_age_groups"][-1] == "060-065"
    rid_p = bv["releases"][0]["release_id"]
    tot = scalar(db, "SELECT sum(value) FROM stat_value WHERE release_id = :r AND indicator_key = 'bev_gesamt'", r=rid_p)
    ages = scalar(db, "SELECT sum(value) FROM stat_value WHERE release_id = :r AND indicator_key = 'bev_altersgruppe'", r=rid_p)
    work = scalar(db, "SELECT sum(value) FROM stat_value WHERE release_id = :r AND indicator_key = 'bev_15_bis_unter_65'", r=rid_p)
    assert tot == ages == gv["population_sum"]  # Altersgruppen ergeben die Gesamtzahl; identisch mit dem Gemeindeverzeichnis (gleicher Stichtag)
    assert 0.55 < float(work) / float(tot) < 0.70
    assert scalar(db, "SELECT count(*) FROM stat_value WHERE release_id = :r AND value_status = 'not_available' AND value IS NULL", r=rid_p) == \
        18 * info["regions_without_values"]["district"]
    pop, rel = analytics.population_15_65(db)
    assert len(pop) == 400 and rel["period_key"] == period and set(pop) == set(db.execute(sql("SELECT key FROM region WHERE level = 'district' AND is_current")).scalars())
    print(f"Bevölkerung {period}: 400 Kreise mit Werten, {info['regions_without_values']} ohne; insgesamt {int(tot)}, 15 bis unter 65: {int(work)}; "
          f"Leipzig 15–<65: {int(pop['14713'])}; unbekannte Schlüssel {bv['unknown_region_keys']}")

    # derselbe Stichtag in einer anderen Exportdatei (zwei Stichtage) ist kein neuer Datenstand; der zweite Stichtag kommt hinzu
    multi = import_file("bevoelkerung_kreise_alter", sample("bevoelkerung_mehrere"))
    by_period = {r["period_key"]: r["status"] for r in multi["releases"]}
    assert by_period[period] == "unchanged" and sorted(by_period.values()) == ["imported", "unchanged"]
    # Ausweichquelle Regionaldatenbank: gleiche Kreiswerte, zusätzlich Länder und Deutschland
    regio = import_file("bevoelkerung_kreise_alter", sample("bevoelkerung_regio"))
    assert regio["status"] == "imported" and regio["revision"] == 2 and regio["table"] == "12411-02-03-4"
    rid_r = regio["releases"][0]["release_id"]
    diff = scalar(db, "SELECT count(*) FROM stat_value a JOIN stat_value b ON b.release_id = :b AND b.indicator_key = a.indicator_key "
                      "AND b.region_level = a.region_level AND b.region_key = a.region_key AND b.dim_key = a.dim_key "
                      "WHERE a.release_id = :a AND a.region_level = 'district' AND a.value IS DISTINCT FROM b.value", a=rid_p, b=rid_r)
    assert diff == 0
    de_total = scalar(db, "SELECT value FROM stat_value WHERE release_id = :r AND indicator_key = 'bev_gesamt' AND region_level = 'country'", r=rid_r)
    assert de_total == tot
    print(f"Regionaldatenbank {regio['period_key']}: Revision {regio['revision']}, Kreiswerte identisch mit GENESIS, Deutschland {int(de_total)}, "
          f"übersprungen {regio['periods'][regio['period_key']]['skipped_rows']}")
