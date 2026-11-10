"""Import der Verwaltungsgebiete 1:250 000 (BKG VG250, Stand 31.12.) aus dem GeoPackage.

Das GeoPackage ist eine SQLite-Datei. Sie wird mit ``sqlite3`` gelesen; die Geometrien liegen als
GeoPackage-Binary vor (Kopf ``GP`` + Umhüllende + WKB). Der Kopf wird hier abgetrennt, das WKB verarbeitet PostGIS
(``ST_GeomFromWKB`` → ``ST_Transform`` → ``ST_Multi``). GDAL/geopandas werden nicht benötigt.

Fachliche Regeln:

* Nur Landflächen: Zeilen mit Geofaktor ``GF = 4`` („mit Struktur Land“). Die Wasserflächen-Teile (``GF = 2``)
  derselben Einheit würden die Einheit sonst doppelt führen. Mehrere Zeilen je Schlüssel werden zusammengefasst.
* Länder (2-stelliger Schlüssel) und Kreise (5-stellig) → ``region``; Gemeinden (8-stellig) → ``geo_place`` mit
  einem Punkt auf der Fläche als angenähertem Ortsmittelpunkt; dazu Aliaszeilen für Kreisnamen.
* Ein neuerer Gebietsstand wird aktuell, ältere Zeilen bleiben mit ``is_current = false`` erhalten.
* ``geom_simple``: Die Grenzen einer Ebene werden als gemeinsames Liniennetz vereinfacht
  (``ST_SimplifyPreserveTopology`` je Linienzug zwischen zwei Knoten) und neu zu Flächen zusammengesetzt, damit
  Nachbarkreise dieselbe Grenze behalten. ``ST_CoverageSimplify`` wird bewusst nicht verwendet: Es setzt GEOS ≥ 3.12
  voraus, das im eingesetzten PostGIS-Image (GEOS 3.9) fehlt, und ließe sich dort nicht prüfen. Scheitert das
  Verfahren, wird je Fläche topologieerhaltend vereinfacht und das im Ergebnis vermerkt.
"""
from __future__ import annotations

import logging
import re
import sqlite3
import struct
import tempfile
import zipfile
from collections import Counter, defaultdict
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Any

from sqlalchemy import text as sql
from sqlalchemy.exc import DBAPIError
from sqlalchemy.orm import Session

from ..normalize.text import fold
from ..stats.common import (
    FileContext,
    ImportProblem,
    ParsedRelease,
    extract_member,
    fmt_date,
    is_zip,
    parse_german_date,
    store_release,
    summarize,
)

log = logging.getLogger(__name__)

DATASET_KEY = "vg250"
LAYERS = {"state": "vg250_lan", "district": "vg250_krs", "municipality": "vg250_gem"}
KEY_LENGTH = {"state": 2, "district": 5, "municipality": 8}
LAND_GF = 4
GV_TAG = "GV-ISys"  # Kennung der Ergänzungen aus dem Gemeindeverzeichnis in geo_place.source_note
SIMPLIFY_SRID = 25832           # ETRS89 / UTM 32N – Toleranz in Metern
SIMPLIFY_TOLERANCE_M = 150.0
STATES_EXPECTED = 16            # Plausibilitätsgrenzen
DISTRICTS_RANGE = (380, 420)
MUNICIPALITIES_RANGE = (9000, 13000)
DATENQUELLEN_URL = "https://sgx.geodatenzentrum.de/web_public/gdz/datenquellen/datenquellen_vg_nuts.pdf"
_IDENT = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
_ENVELOPE_BYTES = {0: 0, 1: 32, 2: 48, 3: 48, 4: 64}


def source_note(year: int, gebietsstand: date, *, simplified: bool) -> str:
    """Quellenvermerk laut Nutzungsbedingungen des BKG, mit Veränderungshinweis."""
    change = ("Geometrien nach WGS 84 (EPSG:4326) transformiert, Landflächen je Einheit zusammengefasst"
              + (" und für die Kartendarstellung vereinfacht" if simplified else ""))
    return (f"© BKG ({year}) dl-de/by-2-0 (Daten verändert), Datenquellen: {DATENQUELLEN_URL} – "
            f"VG250, Gebietsstand {fmt_date(gebietsstand)}; {change}.")


# --------------------------------------------------------------------------------------------------------
# GeoPackage lesen
# --------------------------------------------------------------------------------------------------------
def split_gpkg_geometry(blob: bytes) -> tuple[int, bytes]:
    """Trennt den GeoPackage-Binary-Kopf ab und liefert ``(srs_id, wkb)``.

    Aufbau: ``'GP'``, Version (1 Byte), Flags (1 Byte), ``srs_id`` (int32), Umhüllende (0/32/48/64 Bytes), WKB.
    Flags: Bit 0 = Byteordnung des Kopfes, Bits 1–3 = Art der Umhüllenden, Bit 4 = leere Geometrie,
    Bit 5 = erweiterter Typ (wird nicht unterstützt).
    """
    if not isinstance(blob, bytes | bytearray | memoryview) or len(blob) < 8:
        raise ImportProblem("GeoPackage: Geometrie fehlt oder ist zu kurz.")
    blob = bytes(blob)
    if blob[:2] != b"GP":
        raise ImportProblem("GeoPackage: Geometrie beginnt nicht mit der Kennung „GP“.")
    flags = blob[3]
    if flags & 0b00100000:
        raise ImportProblem("GeoPackage: erweiterte Geometrietypen werden nicht unterstützt.")
    env = (flags >> 1) & 0b111
    if env not in _ENVELOPE_BYTES:
        raise ImportProblem(f"GeoPackage: ungültige Umhüllenden-Kennung {env}.")
    if flags & 0b00010000:
        raise ImportProblem("GeoPackage: leere Geometrie.")
    srs_id = struct.unpack("<i" if flags & 1 else ">i", blob[4:8])[0]
    wkb = blob[8 + _ENVELOPE_BYTES[env]:]
    if len(wkb) < 9 or wkb[0] not in (0, 1):
        raise ImportProblem("GeoPackage: WKB-Teil der Geometrie ist nicht lesbar.")
    return srs_id, wkb


def _quote(identifier: str) -> str:
    if not _IDENT.match(identifier):
        raise ImportProblem(f"GeoPackage: unerwarteter Tabellen-/Spaltenname {identifier!r}.")
    return f'"{identifier}"'


@dataclass
class Layer:
    level: str
    table: str
    geom_column: str
    srid: int
    columns: set[str]


@dataclass
class Package:
    con: sqlite3.Connection
    gebietsstand: date
    layers: dict[str, Layer]


@contextmanager
def open_package(path: Path) -> Iterator[Package]:
    """Öffnet ``.gpkg`` oder das ZIP des BKG (mit genau einem ``.gpkg``) nur lesend."""
    with tempfile.TemporaryDirectory(prefix="wf-vg250-") as tmp:
        stand_zip: date | None = None
        gpkg = path
        if is_zip(path):
            with zipfile.ZipFile(path) as z:
                members = [i for i in z.infolist() if not i.is_dir() and i.filename.lower().endswith(".gpkg")]
                if len(members) != 1:
                    raise ImportProblem(f"Im ZIP wurde nicht genau ein GeoPackage (.gpkg) gefunden ({len(members)}). "
                                        "Bitte die Variante „Format: geopackage, Inhalt: Ebenen“ verwenden.")
                for info in z.infolist():
                    if Path(info.filename).name.lower() == "aktualitaet.txt" and info.file_size < 200:
                        stand_zip = parse_german_date(z.read(info).decode("utf-8", errors="replace"))
                gpkg = extract_member(z, members[0], Path(tmp) / "vg250.gpkg")
        with gpkg.open("rb") as fh:
            if fh.read(16) != b"SQLite format 3\x00":
                raise ImportProblem("Die Datei ist kein GeoPackage (keine SQLite-Datei).")
        try:
            con = sqlite3.connect(f"file:{gpkg}?mode=ro", uri=True)
        except sqlite3.Error as exc:
            raise ImportProblem(f"GeoPackage konnte nicht geöffnet werden: {exc}") from exc
        try:
            con.execute("PRAGMA query_only = ON")
            con.execute("PRAGMA trusted_schema = OFF")
            yield _describe(con, stand_zip)
        except sqlite3.Error as exc:
            raise ImportProblem(f"GeoPackage konnte nicht gelesen werden: {exc}") from exc
        finally:
            con.close()


def _describe(con: sqlite3.Connection, stand_zip: date | None) -> Package:
    tables = {r[0] for r in con.execute("SELECT name FROM sqlite_master WHERE type IN ('table', 'view')")}
    for needed in ("gpkg_contents", "gpkg_geometry_columns", "gpkg_spatial_ref_sys"):
        if needed not in tables:
            raise ImportProblem(f"Die Datei ist kein GeoPackage (Tabelle {needed} fehlt).")
    layers: dict[str, Layer] = {}
    stands: set[date] = set()
    for level, table in LAYERS.items():
        if table not in tables:
            raise ImportProblem(f"GeoPackage: Ebene {table} fehlt (erwartet: VG250 „Ebenen“ mit Ländern, Kreisen, Gemeinden).")
        row = con.execute("SELECT column_name, srs_id FROM gpkg_geometry_columns WHERE table_name = ?", (table,)).fetchone()
        if row is None:
            raise ImportProblem(f"GeoPackage: Ebene {table} ist nicht als Geometrietabelle registriert.")
        srs = con.execute("SELECT organization, organization_coordsys_id FROM gpkg_spatial_ref_sys WHERE srs_id = ?", (row[1],)).fetchone()
        if srs is None or str(srs[0]).upper() != "EPSG":
            raise ImportProblem(f"GeoPackage: Koordinatenreferenzsystem der Ebene {table} ist kein EPSG-System.")
        columns = {r[1] for r in con.execute(f"PRAGMA table_info({_quote(table)})")}
        missing = {"GF", "AGS", "GEN", "BEZ"} - columns
        if missing:
            raise ImportProblem(f"GeoPackage: In Ebene {table} fehlen die Attribute {', '.join(sorted(missing))}.")
        layers[level] = Layer(level, table, str(row[0]), int(srs[1]), columns)
        desc = con.execute("SELECT description FROM gpkg_contents WHERE table_name = ?", (table,)).fetchone()
        if desc and isinstance(desc[0], str):
            m = re.search(r"\d{4}-\d{2}-\d{2}", desc[0])
            if m:
                try:
                    stands.add(date.fromisoformat(m.group(0)))
                except ValueError:
                    pass
    if len(stands) > 1:
        raise ImportProblem(f"GeoPackage: Die Ebenen nennen unterschiedliche Stände ({', '.join(sorted(map(str, stands)))}).")
    stand = next(iter(stands), None)
    if stand and stand_zip and stand != stand_zip:
        raise ImportProblem(f"Gebietsstand laut GeoPackage ({fmt_date(stand)}) und laut aktualitaet.txt "
                            f"({fmt_date(stand_zip)}) widersprechen sich.")
    stand = stand or stand_zip
    if stand is None:
        raise ImportProblem("Der Gebietsstand ist weder im GeoPackage (gpkg_contents.description) noch in "
                            "dokumentation/aktualitaet.txt angegeben.")
    return Package(con, stand, layers)


def _attributes(pkg: Package, level: str) -> list[tuple[str, str, str, str | None, int | None]]:
    """(Schlüssel, Name, Bezeichnung, NBD, Einwohner) der Landflächen einer Ebene – ohne Geometrie."""
    layer = pkg.layers[level]
    nbd = "NBD" if "NBD" in layer.columns else "NULL"
    ewz = "EWZ" if "EWZ" in layer.columns else "NULL"
    rows = pkg.con.execute(
        f"SELECT AGS, GEN, BEZ, {nbd}, {ewz} FROM {_quote(layer.table)} WHERE GF = ? ORDER BY AGS", (LAND_GF,)).fetchall()
    out = []
    n = KEY_LENGTH[level]
    for ags, gen, bez, nbd_v, ewz_v in rows:
        key = str(ags or "").strip()
        if not (len(key) == n and key.isdigit()):
            raise ImportProblem(f"VG250, Ebene {layer.table}: Schlüssel {ags!r} ist nicht {n}-stellig.")
        if not isinstance(gen, str) or not gen.strip():
            raise ImportProblem(f"VG250, Ebene {layer.table}: Name zu Schlüssel {key} fehlt.")
        pop = int(ewz_v) if isinstance(ewz_v, int | float) and ewz_v >= 0 else None
        out.append((key, gen.strip(), str(bez or "").strip(), str(nbd_v).strip().lower() if nbd_v is not None else None, pop))
    return out


def _unit_attributes(rows: list[tuple[str, str, str, str | None, int | None]], what: str) -> dict[str, tuple[str, str, str | None, int | None]]:
    """Fasst mehrere Zeilen je Schlüssel zusammen (Attribute müssen übereinstimmen; Einwohner nur einmal)."""
    out: dict[str, tuple[str, str, str | None, int | None]] = {}
    for key, gen, bez, nbd, pop in rows:
        if key in out:
            if out[key][0] != gen:
                raise ImportProblem(f"{what}: Schlüssel {key} trägt unterschiedliche Namen ({out[key][0]!r}, {gen!r}).")
            continue
        out[key] = (gen, bez, nbd, pop)
    return out


# --------------------------------------------------------------------------------------------------------
# Aliasnamen der Kreise
# --------------------------------------------------------------------------------------------------------
def district_aliases(districts: dict[str, tuple[str, str, str | None, int | None]],
                     municipality_kreise: dict[str, set[str]]) -> list[tuple[str, str]]:
    """Namensvarianten der Kreise → ``[(Name, Kreisschlüssel)]``.

    * amtlicher Name („Landkreis Leipzig“, „Region Hannover“) sowie „Kreis X“/„Landkreis X“ als Gegenstück;
    * der bloße Name („Mettmann“) nur, wenn er unter den Kreisen eindeutig ist und keine gleichnamige Gemeinde in
      einem anderen Kreis liegt – sonst würde der Alias eine bislang eindeutige Ortsangabe mehrdeutig machen.
    """
    bare_count = Counter(fold(gen) for gen, _, _, _ in districts.values())
    cands: dict[str, dict[str, str]] = defaultdict(dict)  # name_norm → {Kreis: Name}
    for key, (gen, bez, nbd, _) in districts.items():
        names: list[str] = []
        part_of_name = nbd != "nein" and bool(bez)
        if part_of_name:
            names.append(f"{bez} {gen}")
            if bez in ("Landkreis", "Kreis"):
                names.append(f"{'Kreis' if bez == 'Landkreis' else 'Landkreis'} {gen}")
        norm = fold(gen)
        elsewhere = municipality_kreise.get(norm, set()) - {key}
        if bare_count[norm] == 1 and not elsewhere:
            names.append(gen)
        for name in names:
            cands[fold(name)].setdefault(key, name)
    out: list[tuple[str, str]] = []
    for norm, by_kreis in sorted(cands.items()):
        if norm and len(by_kreis) == 1:
            key, name = next(iter(by_kreis.items()))
            out.append((name, key))
    return out


# --------------------------------------------------------------------------------------------------------
# Import
# --------------------------------------------------------------------------------------------------------
def import_vg250(db: Session, ctx: FileContext) -> dict[str, Any]:
    with open_package(ctx.path) as pkg:
        stand = pkg.gebietsstand
        attrs = {level: _attributes(pkg, level) for level in LAYERS}
        states = _unit_attributes(attrs["state"], "VG250, Länder")
        districts = _unit_attributes(attrs["district"], "VG250, Kreise")
        municipalities = _unit_attributes(attrs["municipality"], "VG250, Gemeinden")
        if len(states) != STATES_EXPECTED:
            raise ImportProblem(f"VG250: {len(states)} Länder mit Landfläche (GF = 4) gefunden (erwartet: 16). Es wurde nichts importiert.")
        if not DISTRICTS_RANGE[0] <= len(districts) <= DISTRICTS_RANGE[1]:
            raise ImportProblem(f"VG250: {len(districts)} Kreise gefunden (erwartet: rund 400). Es wurde nichts importiert.")
        if not MUNICIPALITIES_RANGE[0] <= len(municipalities) <= MUNICIPALITIES_RANGE[1]:
            raise ImportProblem(f"VG250: {len(municipalities)} Gemeinden gefunden (erwartet: rund 10.900). Es wurde nichts importiert.")
        orphans = sorted(k for k in districts if k[:2] not in states)
        if orphans:
            raise ImportProblem(f"VG250: Kreise ohne zugehöriges Land: {', '.join(orphans[:5])}.")
        orphans = sorted(a for a in municipalities if a[:5] not in districts)
        if orphans:
            raise ImportProblem(f"VG250: {len(orphans)} Gemeinden ohne zugehörigen Kreis (z. B. {orphans[0]}).")

        period_key = stand.isoformat()
        release = ParsedRelease(
            period_key=period_key, period_end=stand, period_start=None, gebietsstand=stand,
            row_count=len(states) + len(districts) + len(municipalities),
            notes=[f"Gebietsstand laut Datei: {fmt_date(stand)}",
                   f"{len(states)} Länder, {len(districts)} Kreise, {len(municipalities)} Gemeinden (Landflächen, GF = 4)"])
        rel = store_release(db, DATASET_KEY, release, ctx)
        extra: dict[str, Any] = {"gebietsstand": stand, "states": len(states), "districts": len(districts),
                                 "municipalities": len(municipalities)}
        warnings: list[str] = []
        if rel["status"] == "imported":
            _load_geometries(db, pkg)
            extra.update(_write(db, stand, ctx.now.year, states, districts, municipalities, warnings))
    out = summarize(DATASET_KEY, ctx, [rel], **extra)
    out["warnings"] = warnings
    return out


def _load_geometries(db: Session, pkg: Package) -> None:
    """Lädt die Landflächen aller drei Ebenen in eine temporäre Tabelle (Geometrie im Quell-Bezugssystem)."""
    db.execute(sql("DROP TABLE IF EXISTS _vg250_raw"))
    db.execute(sql("CREATE TEMP TABLE _vg250_raw (level text, key text, geom geometry) ON COMMIT DROP"))
    for level, layer in pkg.layers.items():
        known = db.execute(sql("SELECT 1 FROM spatial_ref_sys WHERE srid = :s"), {"s": layer.srid}).first()
        if not known:
            raise ImportProblem(f"VG250: Das Bezugssystem EPSG:{layer.srid} der Ebene {layer.table} ist in PostGIS nicht bekannt.")
        cur = pkg.con.execute(
            f"SELECT AGS, {_quote(layer.geom_column)} FROM {_quote(layer.table)} WHERE GF = ?", (LAND_GF,))
        batch: list[dict[str, Any]] = []

        def flush(rows: list[dict[str, Any]], level: str = level, layer: Layer = layer) -> None:
            try:
                db.execute(sql("INSERT INTO _vg250_raw (level, key, geom) VALUES (:level, :key, ST_GeomFromWKB(:wkb, :srid))"), rows)
            except DBAPIError as exc:
                raise ImportProblem(f"VG250, Ebene {layer.table}: Geometrie konnte nicht gelesen werden ({exc.orig}).") from exc

        size = 0
        for ags, blob in cur:
            srs_id, wkb = split_gpkg_geometry(blob)
            if srs_id != layer.srid and srs_id > 0:
                raise ImportProblem(f"VG250, Ebene {layer.table}: Geometrie von {ags} trägt srs_id {srs_id} statt {layer.srid}.")
            batch.append({"level": level, "key": str(ags).strip(), "wkb": wkb, "srid": layer.srid})
            size += len(wkb)
            if len(batch) >= 200 or size > 8_000_000:
                flush(batch)
                batch, size = [], 0
        if batch:
            flush(batch)
    bad = db.execute(sql("SELECT level, key, GeometryType(geom) FROM _vg250_raw "
                         "WHERE GeometryType(geom) NOT IN ('POLYGON', 'MULTIPOLYGON') LIMIT 1")).first()
    if bad:
        raise ImportProblem(f"VG250: Geometrie von {bad[1]} ist keine Fläche ({bad[2]}).")


class _SimplifyFailed(Exception):
    pass


def _simplify_shared_borders(db: Session, level: str) -> None:
    """Vereinfacht die Grenzen einer Ebene als gemeinsames Liniennetz und setzt die Flächen neu zusammen.

    Alle Flächengrenzen werden vereinigt (gemeinsame Abschnitte gibt es danach nur einmal), zwischen den Knoten zu
    Linienzügen verschmolzen, je Linienzug vereinfacht (die Knoten bleiben erhalten) und wieder zu Flächen
    polygonisiert. Jede neue Fläche gehört zu der Einheit, mit der sie sich überwiegend deckt. Nachbarn teilen
    sich dadurch exakt dieselbe vereinfachte Grenze – ohne Lücken oder Überlappungen.
    """
    params = {"tol": SIMPLIFY_TOLERANCE_M, "srid": SIMPLIFY_SRID, "level": level}
    db.execute(sql("DROP TABLE IF EXISTS _vg250_m"))
    db.execute(sql("DROP TABLE IF EXISTS _vg250_face"))
    db.execute(sql("CREATE TEMP TABLE _vg250_m ON COMMIT DROP AS "
                   "SELECT key, ST_Transform(g_4326, :srid) AS g FROM _vg250_unit WHERE level = :level"), params)
    db.execute(sql("CREATE INDEX ON _vg250_m USING gist (g)"))
    db.execute(sql(
        "CREATE TEMP TABLE _vg250_face ON COMMIT DROP AS "
        "SELECT (ST_Dump(ST_Polygonize(s.g))).geom AS g FROM ("
        "  SELECT ST_Union(ST_SimplifyPreserveTopology(l.g, :tol)) AS g FROM ("
        "    SELECT (ST_Dump(ST_LineMerge(ST_Union(ST_Boundary(g))))).geom AS g FROM _vg250_m) l) s"), params)
    db.execute(sql("CREATE INDEX ON _vg250_face USING gist (g)"))
    db.execute(sql(
        "UPDATE _vg250_unit u SET g_simple = ST_Multi(ST_CollectionExtract(ST_MakeValid(ST_Transform(r.g, 4326)), 3)) "
        "FROM (SELECT a.key, ST_Union(a.g) AS g FROM ("
        "        SELECT f.g, best.key, best.share FROM _vg250_face f CROSS JOIN LATERAL ("
        "          SELECT m.key, ST_Area(ST_Intersection(m.g, f.g)) / NULLIF(ST_Area(f.g), 0) AS share "
        "          FROM _vg250_m m WHERE m.g && f.g AND ST_Intersects(m.g, f.g) ORDER BY 2 DESC NULLS LAST LIMIT 1) best"
        "      ) a WHERE a.share > 0.5 GROUP BY a.key) r "
        "WHERE u.level = :level AND u.key = r.key"), params)
    bad = db.execute(sql(
        "SELECT count(*) FROM _vg250_unit WHERE level = :level AND (g_simple IS NULL OR ST_IsEmpty(g_simple) "
        "OR NOT ST_IsValid(g_simple) "
        "OR ST_Area(g_simple::geography) NOT BETWEEN 0.9 * ST_Area(g_4326::geography) AND 1.1 * ST_Area(g_4326::geography))"),
        params).scalar()
    if bad:
        raise _SimplifyFailed(f"{bad} Einheiten der Ebene {level} ohne brauchbare vereinfachte Fläche")


def _simplify(db: Session, warnings: list[str]) -> str:
    """Füllt ``_vg250_unit.g_simple`` (EPSG:4326) für Länder und Kreise; liefert das verwendete Verfahren."""
    try:
        with db.begin_nested():
            for level in ("state", "district"):
                _simplify_shared_borders(db, level)
        return "shared_borders"
    except (DBAPIError, _SimplifyFailed) as exc:
        log.warning("Vereinfachung über gemeinsame Grenzen nicht möglich – Vereinfachung je Fläche", extra={"error": str(exc)[:300]})
    db.execute(sql(
        "UPDATE _vg250_unit SET g_simple = ST_Multi(ST_CollectionExtract(ST_MakeValid(ST_Transform("
        "ST_SimplifyPreserveTopology(ST_Transform(g_4326, :srid), :tol), 4326)), 3)) WHERE level IN ('state', 'district')"),
        {"tol": SIMPLIFY_TOLERANCE_M, "srid": SIMPLIFY_SRID})
    # sehr kleine Einheiten, die dabei verloren gingen, behalten ihre Originalgeometrie
    db.execute(sql("UPDATE _vg250_unit SET g_simple = g_4326 WHERE level IN ('state', 'district') "
                   "AND (g_simple IS NULL OR ST_IsEmpty(g_simple))"))
    warnings.append("Die Kartengrenzen konnten nicht als gemeinsames Liniennetz vereinfacht werden und wurden je Fläche "
                    "vereinfacht. Zwischen Nachbarkreisen können dadurch haarfeine Lücken/Überlappungen entstehen.")
    return "preserve_topology"


def _write(db: Session, stand: date, year: int, states: dict[str, Any], districts: dict[str, Any],
           municipalities: dict[str, Any], warnings: list[str]) -> dict[str, Any]:
    db.execute(sql("DROP TABLE IF EXISTS _vg250_unit"))
    db.execute(sql(
        "CREATE TEMP TABLE _vg250_unit ON COMMIT DROP AS "
        "SELECT level, key, count(*) AS parts, "
        "CASE WHEN count(*) = 1 THEN (array_agg(geom))[1] ELSE ST_Union(geom) END AS g_src "
        "FROM _vg250_raw GROUP BY level, key"))
    db.execute(sql("ALTER TABLE _vg250_unit ADD COLUMN g_4326 geometry, ADD COLUMN g_simple geometry, ADD COLUMN pt geometry"))
    db.execute(sql("UPDATE _vg250_unit SET g_4326 = ST_Multi(ST_CollectionExtract(ST_MakeValid(ST_Transform(g_src, 4326)), 3)) "
                   "WHERE level IN ('state', 'district')"))
    db.execute(sql("UPDATE _vg250_unit SET pt = ST_PointOnSurface(g_4326) WHERE level IN ('state', 'district')"))
    db.execute(sql("UPDATE _vg250_unit SET pt = ST_Transform(ST_PointOnSurface(ST_MakeValid(g_src)), 4326) WHERE level = 'municipality'"))
    empty = db.execute(sql("SELECT key FROM _vg250_unit WHERE (level <> 'municipality' AND (g_4326 IS NULL OR ST_IsEmpty(g_4326))) "
                           "OR pt IS NULL OR ST_IsEmpty(pt) LIMIT 1")).scalar()
    if empty:
        raise ImportProblem(f"VG250: Für {empty} ließ sich keine gültige Fläche bilden.")
    dissolved = db.execute(sql("SELECT count(*) FROM _vg250_unit WHERE parts > 1")).scalar() or 0
    method = _simplify(db, warnings)
    note = source_note(year, stand, simplified=True)

    newest = db.execute(sql("SELECT max(gebietsstand) FROM region WHERE country = 'DE' AND level IN ('state', 'district')")).scalar()
    is_current = newest is None or stand >= newest
    if is_current:
        db.execute(sql("UPDATE region SET is_current = false WHERE country = 'DE' AND level IN ('state', 'district') "
                       "AND gebietsstand <> :g AND is_current"), {"g": stand})
    rows = [{"level": "state", "key": k, "name": v[0], "type": v[1] or None, "parent": None} for k, v in states.items()]
    rows += [{"level": "district", "key": k, "name": v[0], "type": v[1] or None, "parent": k[:2]} for k, v in districts.items()]
    db.execute(sql("DROP TABLE IF EXISTS _vg250_attr"))
    db.execute(sql("CREATE TEMP TABLE _vg250_attr (level text, key text, name text, type_label text, parent_key text) ON COMMIT DROP"))
    db.execute(sql("INSERT INTO _vg250_attr VALUES (:level, :key, :name, :type, :parent)"), rows)
    db.execute(sql("DELETE FROM region WHERE country = 'DE' AND level IN ('state', 'district') AND gebietsstand = :g "
                   "AND (level, key) NOT IN (SELECT level, key FROM _vg250_attr)"), {"g": stand})
    db.execute(sql(
        "INSERT INTO region (country, level, key, name, type_label, parent_key, gebietsstand, is_current, geom, geom_simple, "
        "centroid, area_km2, source_note) "
        "SELECT 'DE', a.level, a.key, a.name, a.type_label, a.parent_key, :g, :cur, u.g_4326, u.g_simple, u.pt, "
        "round((ST_Area(u.g_4326::geography) / 1000000.0)::numeric, 3), :note "
        "FROM _vg250_attr a JOIN _vg250_unit u ON u.level = a.level AND u.key = a.key "
        "ON CONFLICT ON CONSTRAINT uq_region_key_stand DO UPDATE SET name = excluded.name, type_label = excluded.type_label, "
        "parent_key = excluded.parent_key, is_current = excluded.is_current, geom = excluded.geom, "
        "geom_simple = excluded.geom_simple, centroid = excluded.centroid, area_km2 = excluded.area_km2, "
        "source_note = excluded.source_note"), {"g": stand, "cur": is_current, "note": note})
    written = db.execute(sql("SELECT level, count(*) FROM region WHERE country = 'DE' AND gebietsstand = :g GROUP BY level"),
                         {"g": stand}).all()
    if dict(written) != {"state": len(states), "district": len(districts)}:
        raise ImportProblem(f"VG250: Nicht alle Gebietseinheiten konnten geschrieben werden ({dict(written)}).")
    out: dict[str, Any] = {"is_current": is_current, "simplify_method": method, "simplify_tolerance_m": SIMPLIFY_TOLERANCE_M,
                           "dissolved_units": int(dissolved)}
    out["geojson_bytes_simple"] = int(db.execute(sql(
        "SELECT coalesce(sum(length(ST_AsGeoJSON(geom_simple, 5))), 0) FROM region WHERE country = 'DE' AND level = 'district' "
        "AND gebietsstand = :g"), {"g": stand}).scalar() or 0)
    if not is_current:
        warnings.append(f"Es ist bereits ein neuerer Gebietsstand ({fmt_date(newest)}) geladen; der Stand {fmt_date(stand)} "
                        "wurde als nicht aktuell abgelegt, die Ortsreferenz bleibt unverändert.")
        return out
    out.update(_write_places(db, stand, note, districts, municipalities))
    return out


def _write_places(db: Session, stand: date, region_note: str, districts: dict[str, Any], municipalities: dict[str, Any]) -> dict[str, Any]:
    """Ortsreferenz: Gemeinden nach AGS aktualisieren/anlegen, entfallene entfernen, Kreis-Aliase neu aufbauen."""
    note = region_note.split(" – ")[0] + f" – VG250, Gebietsstand {fmt_date(stand)}; Koordinate: Punkt auf der Gemeindefläche (angenäherter Ortsmittelpunkt)."
    points = {key: (lat, lon) for key, lat, lon in db.execute(sql(
        "SELECT key, round(ST_Y(pt)::numeric, 6), round(ST_X(pt)::numeric, 6) FROM _vg250_unit WHERE level = 'municipality'")).all()}
    existing = {ags: pid for pid, ags in db.execute(sql(
        "SELECT id, ags FROM geo_place WHERE country = 'DE' AND kind = 'municipality' AND ags IS NOT NULL")).all()}
    updates: list[dict[str, Any]] = []
    inserts: list[dict[str, Any]] = []
    by_norm: dict[str, set[str]] = defaultdict(set)
    for ags, (gen, _bez, _nbd, pop) in municipalities.items():
        lat, lon = points[ags]
        norm = fold(gen)
        by_norm[norm].add(ags[:5])
        row = {"name": gen, "norm": norm, "ags": ags, "kreis": ags[:5], "state": ags[:2], "pop": pop, "lat": lat, "lon": lon,
               "stand": stand, "note": note}
        if ags in existing:
            updates.append({**row, "id": existing[ags]})
        else:
            inserts.append(row)
    if updates:
        db.execute(sql(
            "UPDATE geo_place SET name = :name, name_norm = :norm, kreis_key = :kreis, state_key = :state, "
            "population = coalesce(:pop, population), lat = :lat, lon = :lon, gebietsstand = :stand, "
            f"source_note = :note || CASE WHEN position(' | {GV_TAG}' in coalesce(source_note, '')) > 0 "
            f"THEN substr(source_note, position(' | {GV_TAG}' in source_note)) ELSE '' END WHERE id = :id"), updates)
    if inserts:
        db.execute(sql(
            "INSERT INTO geo_place (country, name, name_norm, kind, ags, kreis_key, state_key, population, lat, lon, gebietsstand, "
            "source_note) VALUES ('DE', :name, :norm, 'municipality', :ags, :kreis, :state, :pop, :lat, :lon, :stand, :note)"), inserts)
    gone = [pid for ags, pid in existing.items() if ags not in municipalities]
    removed = 0
    if gone:
        removed = db.execute(sql("DELETE FROM geo_place WHERE id = ANY(:ids) AND (gebietsstand IS NULL OR gebietsstand <= :g)"),
                             {"ids": gone, "g": stand}).rowcount
    db.execute(sql("DELETE FROM geo_place WHERE country = 'DE' AND kind = 'district'"))
    centers = {key: (lat, lon) for key, lat, lon in db.execute(sql(
        "SELECT key, round(ST_Y(pt)::numeric, 6), round(ST_X(pt)::numeric, 6) FROM _vg250_unit WHERE level = 'district'")).all()}
    alias_note = region_note.split(" – ")[0] + f" – VG250, Gebietsstand {fmt_date(stand)}; Kreisname, Koordinate: Punkt auf der Kreisfläche."
    aliases = [{"name": name, "norm": fold(name), "kreis": key, "state": key[:2], "lat": centers[key][0], "lon": centers[key][1],
                "stand": stand, "note": alias_note} for name, key in district_aliases(districts, by_norm)]
    if aliases:
        db.execute(sql(
            "INSERT INTO geo_place (country, name, name_norm, kind, ags, kreis_key, state_key, lat, lon, gebietsstand, source_note) "
            "VALUES ('DE', :name, :norm, 'district', NULL, :kreis, :state, :lat, :lon, :stand, :note)"), aliases)
    return {"places_updated": len(updates), "places_added": len(inserts), "places_removed": int(removed or 0),
            "district_aliases": len(aliases), "with_population": sum(1 for v in municipalities.values() if v[3] is not None)}
