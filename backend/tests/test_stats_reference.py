"""Referenzdaten: VG250 (winziges synthetisches GeoPackage), GV-ISys und KldB 2010 – samt ihren Verbrauchern.

Die Verbraucher sind echt: ``GeoMatcher`` (Punkt-in-Polygon, Ortsnamen, PLZ), ``OccupationClassifier`` und der
Endpunkt ``/api/geo/kreise.geojson``.
"""
from __future__ import annotations

import struct
from datetime import UTC, date, datetime
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text as sql

from workforce.api.app import create_app
from workforce.config import get_settings
from workforce.geo import vg250
from workforce.geo.matcher import GeoMatcher
from workforce.models import User
from workforce.normalize.occupation import OccupationClassifier
from workforce.normalize.text import fold, normalize_title
from workforce.security import hash_password
from workforce.sources.base import RawLocation
from workforce.stats.runner import ImportProblem, import_file

from .fixtures.stats import synthetic as syn
from .fixtures.stats.synthetic import small_thresholds  # noqa: F401 – pytest-Fixture


@pytest.fixture(autouse=True)
def _data_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(get_settings(), "data_dir", tmp_path / "data")


def scalar(db, query: str, **params):
    return db.execute(sql(query), params).scalar()


# --------------------------------------------------------------------------------------------------------
# GeoPackage-Binary
# --------------------------------------------------------------------------------------------------------
def test_gpkg_geometry_header():
    blob = syn.gpkg_geometry([syn.square(400, 5700)])
    srs, wkb = vg250.split_gpkg_geometry(blob)
    assert srs == 25832 and wkb[:5] == struct.pack("<BI", 1, 6)
    # ohne Umhüllende, Big-Endian-Kopf
    plain = b"GP" + bytes([0, 0]) + struct.pack(">i", 4326) + wkb
    assert vg250.split_gpkg_geometry(plain) == (4326, wkb)
    # Umhüllende mit Z (48 Bytes)
    env_z = b"GP" + bytes([0, 0b00000101]) + struct.pack("<i", 25832) + b"\0" * 48 + wkb
    assert vg250.split_gpkg_geometry(env_z) == (25832, wkb)
    for bad in (b"XX" + blob[2:], blob[:6], b"GP" + bytes([0, 0b00010001]) + blob[4:], b"GP" + bytes([0, 0b00100001]) + blob[4:]):
        with pytest.raises(ImportProblem):
            vg250.split_gpkg_geometry(bad)


def test_district_aliases_rules():
    districts = {"14713": ("Leipzig", "Kreisfreie Stadt", "ja", None), "14729": ("Leipzig", "Landkreis", "ja", None),
                 "05158": ("Mettmann", "Kreis", "ja", None), "03241": ("Region Hannover", "Landkreis", "nein", None),
                 "09478": ("Lichtenfels", "Landkreis", "ja", None)}
    municipalities = {"leipzig": {"14713"}, "mettmann": {"05158"}, "lichtenfels": {"09478", "06635"}}
    aliases = dict(vg250.district_aliases(districts, municipalities))
    assert aliases["Landkreis Leipzig"] == "14729" and aliases["Kreis Leipzig"] == "14729"
    assert aliases["Kreisfreie Stadt Leipzig"] == "14713"
    assert "Leipzig" not in aliases           # bloßer Name ist unter den Kreisen mehrdeutig
    assert aliases["Mettmann"] == "05158" and aliases["Landkreis Mettmann"] == "05158"
    assert aliases["Region Hannover"] == "03241" and "Landkreis Region Hannover" not in aliases
    assert "Lichtenfels" not in aliases       # gleichnamige Gemeinde liegt (auch) in einem anderen Kreis
    assert aliases["Landkreis Lichtenfels"] == "09478"


# --------------------------------------------------------------------------------------------------------
# VG250
# --------------------------------------------------------------------------------------------------------
def test_vg250_import_regions_places_and_matching(db, tmp_path, small_thresholds):  # noqa: F811
    f = syn.vg250_gpkg(tmp_path / "SYNTHETISCH_DE_VG250.gpkg")
    res = import_file("vg250", f)
    assert res["status"] == "imported" and res["period_key"] == "2023-12-31"
    assert (res["states"], res["districts"], res["municipalities"]) == (2, 3, 5)
    assert res["simplify_method"] == "shared_borders" and res["is_current"] is True and res["dissolved_units"] == 1
    assert res["warnings"] == []

    rows = {r["key"]: r for r in db.execute(sql(
        "SELECT key, level, name, type_label, parent_key, gebietsstand, is_current, area_km2, source_note, GeometryType(geom) AS gt, "
        "ST_SRID(geom) AS srid, ST_IsValid(geom) AS valid, ST_NumGeometries(geom) AS parts, ST_Contains(geom, centroid) AS inside, "
        "ST_IsValid(geom_simple) AS simple_valid, GeometryType(geom_simple) AS simple_gt FROM region")).mappings()}
    assert set(rows) == {"91", "92", "91001", "91002", "92001"}
    assert {r["level"] for r in rows.values()} == {"state", "district"}
    for r in rows.values():
        assert (r["gt"], r["srid"], r["valid"], r["inside"], r["simple_valid"], r["simple_gt"]) == ("MULTIPOLYGON", 4326, True, True, True, "MULTIPOLYGON")
        assert r["gebietsstand"] == date(2023, 12, 31) and r["is_current"]
    assert (rows["91001"]["name"], rows["91001"]["type_label"], rows["91001"]["parent_key"]) == ("Testhausen", "Kreisfreie Stadt", "91")
    assert rows["91"]["parent_key"] is None and rows["92"]["type_label"] == "Freistaat"
    # nur Landflächen: die Wasserfläche (GF = 2) des Nordkreises zählt nicht mit; zwei Landteile werden zusammengefasst
    assert 98 < float(rows["91002"]["area_km2"]) < 102
    assert 196 < float(rows["92001"]["area_km2"]) < 204 and rows["92001"]["parts"] == 1
    note = rows["91001"]["source_note"]
    assert f"© BKG ({datetime.now(UTC).year}) dl-de/by-2-0 (Daten verändert), Datenquellen: https://sgx.geodatenzentrum.de/" in note
    assert "Gebietsstand 31.12.2023" in note and "transformiert" in note and "vereinfacht" in note
    # vereinfachte Nachbarflächen überlappen nicht
    assert scalar(db, "SELECT coalesce(sum(ST_Area(ST_Intersection(a.geom_simple, b.geom_simple))), 0) FROM region a JOIN region b "
                      "ON a.level = 'district' AND b.level = 'district' AND a.key < b.key") < 1e-9

    places = db.execute(sql("SELECT name, name_norm, kind, ags, kreis_key, state_key, lat, lon, population, gebietsstand FROM geo_place")).mappings().all()
    munis = {p["ags"]: p for p in places if p["kind"] == "municipality"}
    assert set(munis) == {"91001000", "91002001", "91002002", "92001001", "92001002"}
    for ags, p in munis.items():
        assert p["name_norm"] == fold(p["name"]) and p["kreis_key"] == ags[:5] and p["state_key"] == ags[:2]
        assert p["gebietsstand"] == date(2023, 12, 31) and p["population"] is None
        # Punkt auf der Gemeindefläche liegt im richtigen Kreis
        assert scalar(db, "SELECT key FROM region WHERE level = 'district' AND ST_Contains(geom, ST_SetSRID(ST_MakePoint(:lon, :lat), 4326))",
                      lon=float(p["lon"]), lat=float(p["lat"])) == ags[:5]
    assert munis["91002002"]["name"] == "Altdorf am Testbach" and munis["91002002"]["name_norm"] == "altdorf am testbach"
    aliases = {(p["name"], p["kreis_key"]) for p in places if p["kind"] == "district"}
    assert aliases == {("Kreisfreie Stadt Testhausen", "91001"), ("Testhausen", "91001"), ("Landkreis Nordkreis", "91002"),
                       ("Kreis Nordkreis", "91002"), ("Nordkreis", "91002"), ("Region Südheim", "92001")}
    assert all(p["name_norm"] == fold(p["name"]) and p["ags"] is None for p in places if p["kind"] == "district")

    # Verbraucher 1: Punkt-in-Polygon über den GeoMatcher
    m = GeoMatcher(db)
    lat, lon = db.execute(sql("SELECT ST_Y(centroid), ST_X(centroid) FROM region WHERE key = '91002'")).one()
    hit = m.match(RawLocation(lat=lat, lon=lon, country="DE"))
    assert (hit.kreis_key, hit.state_key, hit.method, hit.gebietsstand) == ("91002", "91", "source_coordinates", date(2023, 12, 31))
    wlat, wlon = db.execute(sql("SELECT ST_Y(p), ST_X(p) FROM (SELECT ST_Transform(ST_SetSRID(ST_MakePoint(425000, 5705000), 25832), 4326) AS p) x")).one()
    assert m.match(RawLocation(lat=wlat, lon=wlon)).kreis_key is None  # Punkt auf der Wasserfläche gehört zu keinem Kreis
    # Verbraucher 2: Ortsnamen
    town = m.match(RawLocation(locality="Testhausen", country="DE"))
    assert (town.kreis_key, town.ags, town.precision, town.point_origin) == ("91001", "91001000", "municipality", "place_centroid")
    assert m.match(RawLocation(locality="Altdorf am Testbach")).kreis_key == "91002"
    lk = m.match(RawLocation(locality="Landkreis Nordkreis"))
    assert (lk.kreis_key, lk.precision) == ("91002", "district")
    assert m.match(RawLocation(locality="Kreis Nordkreis")).kreis_key == "91002"
    assert m.match(RawLocation(locality="Region Südheim")).kreis_key == "92001"
    amb = m.match(RawLocation(locality="Neudorf"))  # gleichnamige Gemeinden in zwei Kreisen → nicht raten
    assert amb.kreis_key is None and amb.method == "ambiguous_name"

    rel = db.execute(sql("SELECT period_key, period_end, gebietsstand, revision, published_on, row_count FROM stat_release WHERE dataset_key = 'vg250'")).one()
    assert rel == ("2023-12-31", date(2023, 12, 31), date(2023, 12, 31), 1, None, 10)
    assert f"© BKG ({datetime.now(UTC).year})" in scalar(db, "SELECT attribution FROM stat_dataset WHERE key = 'vg250'")

    # identischer Import ändert nichts
    before = (scalar(db, "SELECT count(*) FROM region"), scalar(db, "SELECT count(*) FROM geo_place"), scalar(db, "SELECT max(id) FROM geo_place"))
    again = import_file("vg250", f)
    assert again["status"] == "unchanged"
    assert before == (scalar(db, "SELECT count(*) FROM region"), scalar(db, "SELECT count(*) FROM geo_place"), scalar(db, "SELECT max(id) FROM geo_place"))


NEW_DISTRICTS = [("91003", "Neukreis", "Landkreis", "ja", [(4, [syn.square(400, 5700, 20, 10)])]),
                 ("92001", "Region Südheim", "Landkreis", "nein", [(4, [syn.square(400, 5690, 20, 10)])])]
NEW_MUNICIPALITIES = [("91003001", "Testhausen", "Stadt", [(4, [syn.square(400, 5700)])]),
                      ("91003002", "Neudorf", "Gemeinde", [(4, [syn.square(410, 5700)])]),
                      ("92001001", "Neudorf", "Gemeinde", [(4, [syn.square(400, 5690)])]),
                      ("92001002", "Südheim", "Stadt", [(4, [syn.square(410, 5690)])])]


@pytest.fixture
def client(db):
    db.add(User(username="leserin", role="reader", password_hash=hash_password("ein-langes-testpasswort")))
    db.commit()
    c = TestClient(create_app())
    assert c.post("/api/auth/login", json={"username": "leserin", "password": "ein-langes-testpasswort"}).status_code == 200
    return c


def test_vg250_newer_gebietsstand_keeps_history_and_geojson(db, tmp_path, small_thresholds, client):  # noqa: F811
    import_file("vg250", syn.vg250_gpkg(tmp_path / "SYNTHETISCH_2023.gpkg"))
    geo = client.get("/api/geo/kreise.geojson").json()
    assert [f["id"] for f in geo["features"]] == ["91001", "91002", "92001"] and geo["gebietsstand"] == "2023-12-31"
    feat = geo["features"][1]
    assert feat["geometry"]["type"] == "MultiPolygon" and feat["properties"]["state"] == "Testland Nord"
    assert feat["properties"]["type"] == "Landkreis" and "© BKG" in geo["attribution"]
    x, y = feat["geometry"]["coordinates"][0][0][0]
    assert 7 < x < 9 and 51 < y < 52 and len(str(x).split(".")[1]) <= 5  # WGS 84, höchstens 5 Nachkommastellen

    # Gebietsreform: 91001 + 91002 → 91003; als ZIP mit aktualitaet.txt wie beim BKG
    newer = syn.vg250_gpkg(tmp_path / "SYNTHETISCH_vg250_2024.zip", date(2024, 12, 31), districts=NEW_DISTRICTS,
                           municipalities=NEW_MUNICIPALITIES, as_zip=True)
    res = import_file("vg250", newer)
    assert res["status"] == "imported" and res["period_key"] == "2024-12-31" and res["is_current"] is True
    assert res["places_removed"] == 3 and res["places_added"] == 2 and res["places_updated"] == 2
    stand = dict(db.execute(sql("SELECT gebietsstand, count(*) FILTER (WHERE is_current) || '/' || count(*) FROM region GROUP BY 1")).all())
    assert stand == {date(2023, 12, 31): "0/5", date(2024, 12, 31): "4/4"}  # alte Zeilen bleiben, sind aber nicht mehr aktuell
    assert set(db.execute(sql("SELECT key FROM region WHERE level = 'district' AND is_current")).scalars()) == {"91003", "92001"}
    assert scalar(db, "SELECT ST_AsText(geom) IS NOT NULL FROM region WHERE key = '91001' AND NOT is_current") is True
    places = dict(db.execute(sql("SELECT ags, kreis_key FROM geo_place WHERE kind = 'municipality'")).all())
    assert places == {"91003001": "91003", "91003002": "91003", "92001001": "92001", "92001002": "92001"}
    assert scalar(db, "SELECT count(*) FROM geo_place WHERE kind = 'district' AND kreis_key IN ('91001', '91002')") == 0
    geo = client.get("/api/geo/kreise.geojson").json()
    assert [f["id"] for f in geo["features"]] == ["91003", "92001"] and geo["gebietsstand"] == "2024-12-31"
    m = GeoMatcher(db)
    assert m.match(RawLocation(locality="Testhausen")).kreis_key == "91003"
    assert m.match(RawLocation(locality="Landkreis Neukreis")).kreis_key == "91003"
    assert [r[0] for r in db.execute(sql("SELECT period_key FROM stat_release WHERE dataset_key = 'vg250' ORDER BY 1"))] == ["2023-12-31", "2024-12-31"]

    # ein älterer Stand nachträglich: wird als nicht aktuell abgelegt, Ortsreferenz und Karte bleiben
    older = import_file("vg250", syn.vg250_gpkg(tmp_path / "SYNTHETISCH_2022.gpkg", date(2022, 12, 31)))
    assert older["is_current"] is False and any("neuerer Gebietsstand" in w for w in older["warnings"])
    assert set(db.execute(sql("SELECT key FROM region WHERE level = 'district' AND is_current")).scalars()) == {"91003", "92001"}
    assert scalar(db, "SELECT count(*) FROM region WHERE gebietsstand = '2022-12-31' AND NOT is_current") == 5
    assert dict(db.execute(sql("SELECT ags, kreis_key FROM geo_place WHERE kind = 'municipality'")).all()) == places


def test_vg250_ew_population_and_validation(db, tmp_path, monkeypatch):
    f = syn.vg250_gpkg(tmp_path / "SYNTHETISCH_ew.gpkg", with_ewz=True)
    with pytest.raises(ImportProblem, match="erwartet: 16"):  # Plausibilitätsgrenzen der echten Datei
        import_file("vg250", f)
    assert scalar(db, "SELECT count(*) FROM region") == 0 and scalar(db, "SELECT count(*) FROM stat_release") == 0
    monkeypatch.setattr(vg250, "STATES_EXPECTED", 2)
    monkeypatch.setattr(vg250, "DISTRICTS_RANGE", (1, 50))
    monkeypatch.setattr(vg250, "MUNICIPALITIES_RANGE", (1, 50))
    res = import_file("vg250", f)
    assert res["with_population"] == 5
    assert dict(db.execute(sql("SELECT ags, population FROM geo_place WHERE kind = 'municipality' ORDER BY ags LIMIT 2")).all()) == {
        "91001000": 1000, "91002001": 2000}  # Einwohner der Landfläche, nicht der Wasserflächen-Zeile

    cases = {
        "kein Gebietsstand": (syn.vg250_gpkg(tmp_path / "SYNTHETISCH_a.gpkg", description="ohne Datum"), "Gebietsstand"),
        "Widerspruch": (syn.vg250_gpkg(tmp_path / "SYNTHETISCH_b.zip", date(2021, 12, 31), description="2020-12-31", as_zip=True), "widersprechen"),
        "Kreis ohne Land": (syn.vg250_gpkg(tmp_path / "SYNTHETISCH_c.gpkg", date(2021, 12, 31), districts=[
            *syn.VG_DISTRICTS, ("93001", "Fremdkreis", "Landkreis", "ja", [(4, [syn.square(430, 5700)])])]), "ohne zugehöriges Land"),
        "Gemeinde ohne Kreis": (syn.vg250_gpkg(tmp_path / "SYNTHETISCH_d.gpkg", date(2021, 12, 31), municipalities=[
            *syn.VG_MUNICIPALITIES, ("91009001", "Irgendwo", "Gemeinde", [(4, [syn.square(430, 5700)])])]), "ohne zugehörigen Kreis"),
    }
    for path, pattern in cases.values():
        with pytest.raises(ImportProblem, match=pattern):
            import_file("vg250", path)
    text_file = tmp_path / "SYNTHETISCH_kein.gpkg"
    text_file.write_text("kein GeoPackage")
    with pytest.raises(ImportProblem, match="kein GeoPackage"):
        import_file("vg250", text_file)
    assert scalar(db, "SELECT count(*) FROM stat_release") == 1 and scalar(db, "SELECT count(DISTINCT gebietsstand) FROM region") == 1


# --------------------------------------------------------------------------------------------------------
# GV-ISys
# --------------------------------------------------------------------------------------------------------
GEMEINDEN = [
    {"ags": "91001000", "name": "Testhausen, Stadt", "pop": 50000, "plz": "99001", "lon": "8,5", "lat": "51,4"},
    {"ags": "91002001", "name": "Neudorf", "pop": 1200, "plz": "99002", "lon": "8,6", "lat": "51,4"},
    {"ags": "91002009", "name": "Neugemeinde", "pop": 77, "plz": "99002", "lon": "8,7", "lat": "51,45"},   # neu, Kreis bekannt
    {"ags": "92001001", "name": "Neudorf", "pop": 800, "plz": "99003", "lon": "8,5", "lat": "51,3"},
    {"ags": "92001002", "name": "Südheim, Stadt", "pop": 0, "plz": None, "lon": "0", "lat": "0"},          # ohne PLZ, 0/0 = keine Koordinate
    {"ags": "93001001", "name": "Fremdstadt, Stadt", "pop": 5, "plz": "99009", "lon": "9,1", "lat": "51,0"},  # Kreis fehlt im Gebietsstand
]


def test_gv_isys_enriches_places_and_fills_postal_codes(db, tmp_path, small_thresholds):  # noqa: F811
    import_file("vg250", syn.vg250_gpkg(tmp_path / "SYNTHETISCH_2023.gpkg"))
    vg_lat = scalar(db, "SELECT lat FROM geo_place WHERE ags = '91001000'")
    f = syn.gv_isys_xlsx(tmp_path / "SYNTHETISCH_AuszugGV.xlsx", date(2024, 3, 31), GEMEINDEN)
    res = import_file("gv_isys", f)
    assert res["status"] == "imported" and res["period_key"] == "2024-03-31"
    assert (res["places_enriched"], res["places_added"], res["postal_codes"], res["distinct_postal_codes"]) == (4, 1, 4, 3)
    assert res["skipped_unknown_kreis"] == {"93001": 1} and res["unknown_region_keys"] == ["93001"]
    assert res["places_not_in_file"] == ["91002002"]
    rel = db.execute(sql("SELECT period_end, gebietsstand, published_on, notes FROM stat_release WHERE dataset_key = 'gv_isys'")).one()
    assert rel[:3] == (date(2024, 3, 31), date(2024, 3, 31), None) and "Erscheinungsmonat: Februar 2024" in rel[3]

    p = {r["ags"]: r for r in db.execute(sql("SELECT * FROM geo_place WHERE kind = 'municipality'")).mappings()}
    assert (p["91001000"]["postal_code"], p["91001000"]["population"], p["91001000"]["name"]) == ("99001", 50000, "Testhausen")
    assert p["91001000"]["lat"] == vg_lat  # Koordinate aus VG250 bleibt
    assert "© BKG" in p["91001000"]["source_note"] and "GV-ISys" in p["91001000"]["source_note"]
    assert (p["92001002"]["postal_code"], p["92001002"]["population"]) == (None, 0)
    new = p["91002009"]
    assert (new["name"], new["name_norm"], new["kreis_key"], float(new["lat"]), float(new["lon"])) == ("Neugemeinde", "neugemeinde", "91002", 51.45, 8.7)
    assert "93001001" not in p and p["91002002"]["postal_code"] is None
    plz = {(r[0], r[1], r[2]) for r in db.execute(sql("SELECT plz, ags, kreis_key FROM postal_code")).all()}
    assert plz == {("99001", "91001000", "91001"), ("99002", "91002001", "91002"), ("99002", "91002009", "91002"), ("99003", "92001001", "92001")}
    # nur die PLZ des Verwaltungssitzes – die Einschränkung steht in den Datensatzhinweisen
    assert "PLZ des Verwaltungssitzes" in scalar(db, "SELECT notes FROM stat_dataset WHERE key = 'gv_isys'")

    m = GeoMatcher(db)
    hit = m.match(RawLocation(locality="Neudorf", postal_code="99003"))  # Namensdublette über die PLZ aufgelöst
    assert (hit.kreis_key, hit.method) == ("92001", "place_name+plz")
    only_plz = m.match(RawLocation(postal_code="99002"))
    assert (only_plz.kreis_key, only_plz.method) == ("91002", "plz_unique")

    assert import_file("gv_isys", f)["status"] == "unchanged"
    # neuere Ausgabe ersetzt die PLZ-Zeilen (keine Altlasten), ältere wird danach abgelehnt
    newer = [dict(GEMEINDEN[0], plz="99111"), *GEMEINDEN[1:]]
    import_file("gv_isys", syn.gv_isys_xlsx(tmp_path / "SYNTHETISCH_AuszugGV_neu.xlsx", date(2024, 6, 30), newer))
    assert set(db.execute(sql("SELECT plz FROM postal_code WHERE ags = '91001000'")).scalars()) == {"99111"}
    assert scalar(db, "SELECT count(*) FROM postal_code") == 4 and scalar(db, "SELECT postal_code FROM geo_place WHERE ags = '91001000'") == "99111"
    assert scalar(db, "SELECT source_note FROM geo_place WHERE ags = '91001000'").count("GV-ISys") == 1
    with pytest.raises(ImportProblem, match="neuerer Stand"):
        import_file("gv_isys", syn.gv_isys_xlsx(tmp_path / "SYNTHETISCH_alt.xlsx", date(2023, 12, 31), GEMEINDEN))
    # VG250 erneut (berichtigte Datei): Ergänzungen aus GV-ISys bleiben erhalten
    import_file("vg250", syn.vg250_gpkg(tmp_path / "SYNTHETISCH_2023_korrigiert.gpkg", municipalities=[
        *syn.VG_MUNICIPALITIES[:4], ("92001002", "Südheim am Testbach", "Stadt", [(4, [syn.square(410, 5690)])])]))
    kept = db.execute(sql("SELECT postal_code, population, source_note FROM geo_place WHERE ags = '91001000'")).one()
    assert kept[:2] == ("99111", 50000) and "GV-ISys" in kept[2]
    assert scalar(db, "SELECT name FROM geo_place WHERE ags = '92001002'") == "Südheim am Testbach"
    assert scalar(db, "SELECT count(*) FROM geo_place WHERE ags = '91002009'") == 1  # jüngere GV-ISys-Gemeinde bleibt


def test_gv_isys_without_vg250_and_validation(db, tmp_path, small_thresholds):  # noqa: F811
    with pytest.raises(ImportProblem, match="Spaltenkopf"):
        import_file("gv_isys", syn.gv_isys_xlsx(tmp_path / "SYNTHETISCH_a.xlsx", date(2024, 3, 31), GEMEINDEN, break_header=True))
    with pytest.raises(ImportProblem, match="widersprechen"):
        import_file("gv_isys", syn.gv_isys_xlsx(tmp_path / "SYNTHETISCH_b.xlsx", date(2024, 3, 31), GEMEINDEN, title_stand=date(2023, 3, 31)))
    with pytest.raises(ImportProblem, match="mehrfach"):
        import_file("gv_isys", syn.gv_isys_xlsx(tmp_path / "SYNTHETISCH_c.xlsx", date(2024, 3, 31), [*GEMEINDEN, GEMEINDEN[0]]))
    with pytest.raises(ImportProblem, match="fünfstellig"):
        import_file("gv_isys", syn.gv_isys_xlsx(tmp_path / "SYNTHETISCH_d.xlsx", date(2024, 3, 31), [dict(GEMEINDEN[0], plz="9901")]))
    assert scalar(db, "SELECT count(*) FROM stat_release") == 0 and scalar(db, "SELECT count(*) FROM postal_code") == 0
    # ohne geladenen Gebietsstand legt das Gemeindeverzeichnis die Orte selbst an (Name ohne Zusatz „, Stadt“)
    res = import_file("gv_isys", syn.gv_isys_xlsx(tmp_path / "SYNTHETISCH_e.xlsx", date(2024, 3, 31), GEMEINDEN))
    assert res["places_added"] == 6 and res["places_enriched"] == 0 and res["skipped_unknown_kreis"] == {}
    row = db.execute(sql("SELECT name, name_norm, kreis_key, postal_code, population, lat FROM geo_place WHERE ags = '93001001'")).one()
    assert row[:5] == ("Fremdstadt", "fremdstadt", "93001", "99009", 5) and float(row[5]) == 51.0
    assert scalar(db, "SELECT lat FROM geo_place WHERE ags = '92001002'") is None


# --------------------------------------------------------------------------------------------------------
# KldB 2010
# --------------------------------------------------------------------------------------------------------
def test_kldb_import_and_classifier(db, tmp_path, small_thresholds):  # noqa: F811
    s = syn.kldb_systematik_xlsx(tmp_path / "SYNTHETISCH_Systematisches-Verzeichnis.xlsx")
    res = import_file("kldb2010", s)
    assert res["status"] == "imported" and res["period_key"] == "systematik-2020-12-01" and res["kind"] == "systematik"
    classes = {r[0]: (r[1], r[2], r[3]) for r in db.execute(sql("SELECT code, level, name, version FROM kldb_class")).all()}
    assert len(classes) == 19 and all(level == len(code) for code, (level, _, _) in classes.items())
    assert classes["43102"] == (5, "Berufe in der Informatik - fachlich ausgerichtete Tätigkeiten (synthetisch)", "KldB 2010/2020")
    assert {lv for lv, _, _ in classes.values()} == {1, 2, 3, 4, 5} and "0" in classes

    a = syn.kldb_alphabet_xlsx(tmp_path / "SYNTHETISCH_Alphabetisches-Verzeichnis.xlsx")
    res = import_file("kldb2010", a)
    assert res["period_key"] == "alphabet-2026-01-20" and res["titles_added"] == 4 and res["duplicate_rows_skipped"] == 1
    assert res["unknown_kldb_codes"] == [] and res["warnings"] == []
    titles = db.execute(sql("SELECT title, title_norm, kldb_code, origin FROM occupation_title ORDER BY title")).all()
    assert len(titles) == 4 and all(t[1] == normalize_title(t[0]) and t[3] == "kldb_alphabetisch" for t in titles)
    assert ("Testinformatiker/in", "testinformatiker", "43102", "kldb_alphabetisch") in [tuple(t) for t in titles]

    clf = OccupationClassifier(db)
    hit = clf.classify(None, "Testinformatiker (m/w/d)")
    assert hit is not None and (hit.code, hit.source, hit.requirement_level) == ("43102", "title_exact", 2)
    assert hit.name == "Berufe in der Informatik - fachlich ausgerichtete Tätigkeiten (synthetisch)"
    portal = clf.classify("Musterpflegefachkraft", None)
    assert portal is not None and (portal.code, portal.source) == ("81302", "portal_field")

    # wiederholter Import: nichts ändert sich
    n = scalar(db, "SELECT count(*) FROM occupation_title"), scalar(db, "SELECT max(id) FROM occupation_title")
    assert import_file("kldb2010", a)["status"] == "unchanged" and import_file("kldb2010", s)["status"] == "unchanged"
    assert n == (scalar(db, "SELECT count(*) FROM occupation_title"), scalar(db, "SELECT max(id) FROM occupation_title"))
    assert scalar(db, "SELECT count(*) FROM stat_release WHERE dataset_key = 'kldb2010'") == 2

    # neuere Ausgabe: entfallene Benennungen verschwinden, neue kommen hinzu, lokale Synonyme bleiben unberührt
    db.execute(sql("INSERT INTO occupation_title (title, title_norm, kldb_code, origin) VALUES ('Hausinterner Titel', 'hausinterner titel', '43104', 'synonym_local')"))
    db.commit()
    newer = [("Testinformatiker/in", "43102"), ("Neuberuf (erfunden)", "81302"), ("Unbekanntschlüssel/in", "99999")]
    res = import_file("kldb2010", syn.kldb_alphabet_xlsx(tmp_path / "SYNTHETISCH_Alphabet_neu.xlsx", newer, created=date(2027, 1, 15)))
    assert (res["titles_added"], res["titles_removed"]) == (2, 3) and res["unknown_kldb_codes"] == ["99999"]
    got = {(t[0], t[1]) for t in db.execute(sql("SELECT title, origin FROM occupation_title")).all()}
    assert got == {("Testinformatiker/in", "kldb_alphabetisch"), ("Neuberuf (erfunden)", "kldb_alphabetisch"),
                   ("Unbekanntschlüssel/in", "kldb_alphabetisch"), ("Hausinterner Titel", "synonym_local")}
    with pytest.raises(ImportProblem, match="neuerer Stand"):
        import_file("kldb2010", syn.kldb_alphabet_xlsx(tmp_path / "SYNTHETISCH_Alphabet_alt.xlsx", created=date(2025, 1, 1)))


def test_kldb_classifier_fuzzy_path_with_loaded_titles(db, tmp_path, small_thresholds):  # noqa: F811
    import_file("kldb2010", syn.kldb_alphabet_xlsx(tmp_path / "SYNTHETISCH_Alphabetisches-Verzeichnis.xlsx"))
    clf = OccupationClassifier(db)
    assert clf.classify(None, "Zirkusdirektor für Raumfahrt") is None           # kein Treffer, aber auch kein SQL-Fehler
    near = clf.classify(None, "Musterpflegefachkraft II")                       # unscharfer Treffer (hohe Ähnlichkeit)
    assert near is not None and (near.code, near.source) == ("81302", "title_fuzzy") and near.confidence < 0.7  # bleibt als unsicher gekennzeichnet
    assert clf.classify(None, "Musterpflegehelfer im Nachtdienst der Klinik") is None  # geringe Ähnlichkeit ⇒ lieber keine Zuordnung


def test_kldb_validation(db, tmp_path, monkeypatch):
    from workforce.stats import kldb

    s = syn.kldb_systematik_xlsx(tmp_path / "SYNTHETISCH_a.xlsx")
    with pytest.raises(ImportProblem, match="Unplausible Anzahl"):  # echte Datei: 1.300 Berufsgattungen
        import_file("kldb2010", s)
    with pytest.raises(ImportProblem, match="rund 18.900"):
        import_file("kldb2010", syn.kldb_alphabet_xlsx(tmp_path / "SYNTHETISCH_b.xlsx"))
    with pytest.raises(ImportProblem, match="Fassung 2020"):
        import_file("kldb2010", syn.kldb_systematik_xlsx(tmp_path / "SYNTHETISCH_c.xlsx", title="Klassifikation der Berufe 1988"))
    monkeypatch.setattr(kldb, "MIN_CLASSES_5", 1)
    with pytest.raises(ImportProblem, match="übergeordnete Position"):
        import_file("kldb2010", syn.kldb_systematik_xlsx(tmp_path / "SYNTHETISCH_d.xlsx", [*syn.KLDB_CLASSES, ("77777", "Waise (synthetisch)")]))
    other = syn.gv_isys_xlsx(tmp_path / "SYNTHETISCH_e.xlsx", date(2024, 3, 31), GEMEINDEN)
    with pytest.raises(ImportProblem, match="Weder das Blatt"):
        import_file("kldb2010", other)
    assert scalar(db, "SELECT count(*) FROM kldb_class") == 0 and scalar(db, "SELECT count(*) FROM stat_release") == 0
