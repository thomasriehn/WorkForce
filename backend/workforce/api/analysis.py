"""Karte, Zeitvergleiche, Zeitreihen, Dashboard, Regionen und amtliche Kontextdaten."""
from __future__ import annotations

import json
from dataclasses import replace
from datetime import UTC, date, datetime, timedelta
from typing import Any

from fastapi import APIRouter, HTTPException, Query, Response
from sqlalchemy import text as sql

from ..config import get_settings
from ..search import analytics
from .deps import CurrentUser, Db, FiltersDep

router = APIRouter(prefix="/api", tags=["analysis"])


@router.get("/geo/kreise.geojson")
def kreise_geojson(db: Db, user: CurrentUser, response: Response) -> Response:
    """Lokal ausgelieferte, vereinfachte Kreisgrenzen (VG250) – keine externen Kartenkacheln nötig."""
    rows = db.execute(sql(
        "SELECT key, name, type_label, parent_key, gebietsstand, ST_AsGeoJSON(coalesce(geom_simple, geom), 5) AS g "
        "FROM region WHERE level = 'district' AND is_current AND geom IS NOT NULL ORDER BY key")).mappings().all()
    states = dict(db.execute(sql("SELECT key, name FROM region WHERE level = 'state' AND is_current")).all())
    feats = [{"type": "Feature", "id": r["key"], "geometry": json.loads(r["g"]),
              "properties": {"key": r["key"], "name": r["name"], "type": r["type_label"], "state_key": r["parent_key"],
                             "state": states.get(r["parent_key"]), "gebietsstand": r["gebietsstand"].isoformat()}} for r in rows]
    meta = db.execute(sql("SELECT source_note, max(gebietsstand) FROM region WHERE level = 'district' AND is_current GROUP BY 1 LIMIT 1")).first()
    body = json.dumps({"type": "FeatureCollection", "features": feats,
                       "attribution": meta[0] if meta else None, "gebietsstand": meta[1].isoformat() if meta else None}, ensure_ascii=False)
    return Response(body, media_type="application/geo+json", headers={"Cache-Control": "private, max-age=3600"})


@router.get("/map/metrics")
def map_metrics(f: FiltersDep, db: Db, user: CurrentUser) -> dict:
    out = analytics.map_metrics(db, f)
    out["reference_date"] = (f.as_of or analytics.reference_date(db)).isoformat()
    out["scope"] = f.describe_scope()
    out["coverage"] = _coverage_summary(db)
    return out


@router.get("/map/change")
def map_change(f: FiltersDep, db: Db, user: CurrentUser, days: int = Query(30), metric: str = "weighted") -> dict:
    if days not in (7, 30, 90):
        raise HTTPException(422, "days muss 7, 30 oder 90 sein")
    if metric not in ("weighted", "distinct"):
        raise HTTPException(422, "metric muss weighted oder distinct sein")
    return analytics.map_change(db, f, days, metric=metric)


@router.get("/timeseries")
def timeseries(f: FiltersDep, db: Db, user: CurrentUser, days: int = Query(90, ge=7, le=730)) -> dict:
    ref = analytics.reference_date(db)
    return analytics.timeseries(db, replace(f, as_of=None), ref - timedelta(days=days - 1), ref)


@router.get("/facets")
def facets(f: FiltersDep, db: Db, user: CurrentUser) -> dict:
    return analytics.facets(db, f)


def _coverage_summary(db) -> dict[str, Any]:
    rows = db.execute(sql(
        "SELECT s.id, s.name, s.config_status, s.segment, "
        "(SELECT max(r.logical_date) FROM scan_run r WHERE r.source_id = s.id AND NOT r.is_test AND r.status = 'complete') AS last_complete, "
        "(SELECT r.status FROM scan_run r WHERE r.source_id = s.id AND NOT r.is_test ORDER BY r.logical_date DESC, r.id DESC LIMIT 1) AS last_status, "
        "(SELECT count(*) FROM source_posting sp WHERE sp.source_id = s.id AND sp.status IN ('active','not_reobserved') AND NOT sp.is_synthetic) AS stock "
        "FROM source s WHERE s.config_status = 'active' OR EXISTS (SELECT 1 FROM source_posting sp WHERE sp.source_id = s.id) ORDER BY s.name")).mappings().all()
    return {"sources": [dict(r) for r in rows],
            "note": "Die Zahlen beziehen sich ausschließlich auf die aufgeführten Quellen und deren Suchbereiche – keine Vollerhebung des Stellenmarkts."}


def _freshness(db) -> dict[str, Any]:
    stats = db.execute(sql(
        "SELECT DISTINCT ON (d.key) d.key, d.name, d.publisher, r.period_key, r.period_end, r.revision, r.published_on, r.retrieved_at "
        "FROM stat_dataset d JOIN stat_release r ON r.dataset_key = d.key AND r.is_current ORDER BY d.key, r.period_end DESC")).mappings().all()
    today = datetime.now(get_settings().tz).date()
    return {"statistics": [dict(r, age_days=(today - r["period_end"]).days) for r in stats]}


@router.get("/dashboard")
def dashboard(db: Db, user: CurrentUser) -> dict:
    from ..search.query import Filters

    ref = analytics.reference_date(db)
    out: dict[str, Any] = {"reference_date": ref.isoformat(), "generated_at": datetime.now(UTC)}
    out["totals"] = {kg: analytics.totals(db, Filters(kind_group=kg)) for kg in ("jobs", "ausbildung", "praktikum")}
    out["coverage"] = _coverage_summary(db)
    out["changes"] = {}
    for days in (7, 30, 90):
        ch = analytics.map_change(db, Filters(kind_group="jobs"), days)
        out["changes"][str(days)] = {"total": ch["total"], "basis": ch["basis"], "message": ch.get("message")}
    metrics = analytics.map_metrics(db, Filters(kind_group="jobs"))
    names = dict(db.execute(sql("SELECT key, name FROM region WHERE level = 'district' AND is_current")).all())
    top = sorted(metrics["regions"], key=lambda r: -r["weighted"])[:10]
    out["top_regions"] = [dict(r, name=names.get(r["key"], r["key"])) for r in top]
    out["top_regions_label"] = "Kreise mit den meisten anteilig gezählten Anzeigen (Hotspots der erfassten Nachfrage – kein Nachweis eines Fachkräfteengpasses)"
    out["freshness"] = _freshness(db)
    out["warnings"] = [dict(r) for r in db.execute(sql("SELECT id, kind, message, created_at FROM ops_warning WHERE resolved_at IS NULL ORDER BY created_at DESC LIMIT 20")).mappings().all()]
    out["notes"] = [dict(r) for r in db.execute(sql("SELECT note_date, kind, message FROM timeline_note ORDER BY note_date DESC, id DESC LIMIT 10")).mappings().all()]
    out["timeseries"] = analytics.timeseries(db, Filters(kind_group="jobs"), ref - timedelta(days=59), ref)
    out["disclaimer"] = ("WorkForce beobachtet Stellenanzeigen als Hinweis auf Arbeitskräftebedarf. Die Zahlen sind weder die Anzahl offener "
                         "Arbeitsplätze noch ein amtlicher Nachweis von Fachkräftemangel.")
    return out


# --- Regionen -----------------------------------------------------------------------------------------
@router.get("/regions")
def regions(db: Db, user: CurrentUser, level: str = "district", q: str | None = None) -> list[dict]:
    if level not in ("district", "state"):
        raise HTTPException(422, "level muss district oder state sein")
    rows = db.execute(sql(
        "SELECT key, name, type_label, parent_key, gebietsstand FROM region WHERE level = :l AND is_current "
        "AND (CAST(:q AS text) IS NULL OR lower(name) LIKE '%' || lower(CAST(:q AS text)) || '%' OR key LIKE CAST(:q AS text) || '%') ORDER BY name LIMIT 500"),
        {"l": level, "q": q}).mappings().all()
    return [dict(r) for r in rows]


def _latest_stats(db, level: str, key: str) -> list[dict[str, Any]]:
    rows = db.execute(sql(
        "SELECT DISTINCT ON (v.indicator_key, v.dim_key) v.indicator_key, i.name, i.unit, i.definition, i.population_group, v.dim_key, v.dim_label, "
        "v.value, v.value_status, v.raw_value, r.period_key, r.period_end, r.revision, r.published_on, r.retrieved_at, r.gebietsstand, "
        "d.name AS dataset, d.publisher, d.attribution, d.licence, d.landing_url, "
        "(SELECT count(*) FROM stat_release x WHERE x.dataset_key = r.dataset_key AND x.period_key = r.period_key) AS revisions "
        "FROM stat_value v JOIN stat_release r ON r.id = v.release_id AND r.is_current JOIN stat_indicator i ON i.key = v.indicator_key "
        "JOIN stat_dataset d ON d.key = r.dataset_key WHERE v.region_level = :l AND v.region_key = :k AND v.dim_key = '' "
        "ORDER BY v.indicator_key, v.dim_key, r.period_end DESC"), {"l": level, "k": key}).mappings().all()
    today = datetime.now(get_settings().tz).date()
    return [dict(r, value=float(r["value"]) if r["value"] is not None else None, age_days=(today - r["period_end"]).days) for r in rows]


@router.get("/regions/{key}")
def region_detail(key: str, f: FiltersDep, db: Db, user: CurrentUser, days: int = Query(90, ge=7, le=730)) -> dict:
    level = "district" if len(key) == 5 else "state"
    reg = db.execute(sql("SELECT key, name, type_label, parent_key, gebietsstand, area_km2, source_note FROM region WHERE level = :l AND key = :k AND is_current"),
                     {"l": level, "k": key}).mappings().first()
    if reg is None:
        raise HTTPException(404, "Region nicht gefunden")
    rf = replace(f, kreise=[key], states=[]) if level == "district" else replace(f, states=[key], kreise=[])
    ref = analytics.reference_date(db)
    out: dict[str, Any] = {"region": dict(reg, area_km2=float(reg["area_km2"]) if reg["area_km2"] is not None else None), "level": level}
    if reg["parent_key"]:
        out["region"]["state_name"] = db.execute(sql("SELECT name FROM region WHERE level = 'state' AND key = :k AND is_current"), {"k": reg["parent_key"]}).scalar_one_or_none()
    out["totals"] = analytics.totals(db, rf)
    if level == "district":
        m = next((r for r in analytics.map_metrics(db, f)["regions"] if r["key"] == key), None)
        out["metrics"] = m or {"key": key, "weighted": 0.0, "distinct": 0, "rate_per_1000": None, "population_15_65": analytics.population_15_65(db)[0].get(key), "low_count": True}
    out["timeseries"] = analytics.timeseries(db, replace(rf, as_of=None), ref - timedelta(days=days - 1), ref)
    out["facets"] = analytics.facets(db, rf)
    out["context"] = _latest_stats(db, level, key)
    out["context_note"] = ("Arbeitslose und Arbeitsuchende sind unterschiedliche Größen. Berufsbezogene Anzeigenzahlen werden nicht mit allen "
                           "Arbeitslosen/Arbeitsuchenden verrechnet; die Größen stehen getrennt nebeneinander.")
    return out


# --- Amtliche Statistik -----------------------------------------------------------------------------
@router.get("/stats/overview")
def stats_overview(db: Db, user: CurrentUser) -> dict:
    datasets = [dict(r) for r in db.execute(sql("SELECT * FROM stat_dataset ORDER BY name")).mappings().all()]
    indicators = [dict(r) for r in db.execute(sql("SELECT * FROM stat_indicator ORDER BY name")).mappings().all()]
    releases = db.execute(sql(
        "SELECT r.id, r.dataset_key, r.period_key, r.period_start, r.period_end, r.revision, r.is_current, r.published_on, r.retrieved_at, r.file_url, "
        "r.file_name, r.file_sha256, r.gebietsstand, r.import_method, r.row_count, r.notes FROM stat_release r ORDER BY r.dataset_key, r.period_end DESC, r.revision DESC LIMIT 500")).mappings().all()
    today = datetime.now(get_settings().tz).date()
    return {"datasets": datasets, "indicators": indicators,
            "releases": [dict(r, age_days=(today - r["period_end"]).days) for r in releases],
            "note": "Monats- und Jahresstatistiken werden nicht interpoliert. Der nächtliche Abruf prüft nur auf neue Veröffentlichungen; "
                    "der Berichtszeitraum bleibt unverändert. Bei unbekanntem Veröffentlichungsdatum wird keine damalige Verfügbarkeit behauptet."}


@router.get("/stats/map")
def stats_map(db: Db, user: CurrentUser, indicator: str, period: str | None = None, revision: int | None = None, dim: str = "") -> dict:
    ind = db.execute(sql("SELECT * FROM stat_indicator WHERE key = :k"), {"k": indicator}).mappings().first()
    if ind is None:
        raise HTTPException(404, "Kennzahl nicht gefunden")
    rel = db.execute(sql(
        "SELECT r.*, d.name AS dataset_name, d.publisher, d.attribution, d.licence, d.licence_url, d.landing_url FROM stat_release r JOIN stat_dataset d ON d.key = r.dataset_key "
        "WHERE EXISTS (SELECT 1 FROM stat_value v WHERE v.release_id = r.id AND v.indicator_key = :k AND v.region_level = 'district') "
        "AND (CAST(:p AS text) IS NULL OR r.period_key = CAST(:p AS text)) AND ((CAST(:rev AS int) IS NULL AND r.is_current) OR r.revision = CAST(:rev AS int)) "
        "ORDER BY r.period_end DESC, r.revision DESC LIMIT 1"), {"k": indicator, "p": period, "rev": revision}).mappings().first()
    periods = db.execute(sql(
        "SELECT DISTINCT r.period_key, r.period_end, r.revision, r.is_current FROM stat_release r WHERE EXISTS "
        "(SELECT 1 FROM stat_value v WHERE v.release_id = r.id AND v.indicator_key = :k AND v.region_level = 'district') ORDER BY r.period_end DESC, r.revision DESC LIMIT 200"),
        {"k": indicator}).mappings().all()
    if rel is None:
        return {"indicator": dict(ind), "release": None, "values": [], "periods": [dict(p) for p in periods], "message": "Für diese Kennzahl liegen keine Kreisdaten vor."}
    vals = db.execute(sql("SELECT region_key, value, value_status, raw_value FROM stat_value WHERE release_id = :r AND indicator_key = :k AND region_level = 'district' AND dim_key = :dim"),
                      {"r": rel["id"], "k": indicator, "dim": dim}).all()
    today = datetime.now(get_settings().tz).date()
    release = {k: rel[k] for k in ("id", "dataset_key", "dataset_name", "publisher", "period_key", "period_start", "period_end", "revision", "is_current",
                                   "published_on", "retrieved_at", "file_url", "file_sha256", "gebietsstand", "attribution", "licence", "licence_url", "landing_url")}
    release["age_days"] = (today - rel["period_end"]).days
    return {"indicator": dict(ind), "release": release, "periods": [dict(p) for p in periods],
            # Fehlwerte bleiben Fehlwerte (value = null + Status) und werden nie als 0 ausgegeben
            "values": [{"key": k, "value": float(v) if v is not None else None, "status": st, "raw": raw} for k, v, st, raw in vals],
            "status_labels": {"ok": "Wert", "zero": "echter Nullwert", "suppressed": "aus Geheimhaltungsgründen unterdrückt", "unknown": "unbekannt",
                              "not_available": "nicht verfügbar", "not_collected": "nicht erhoben"}}


@router.get("/stats/series")
def stats_series(db: Db, user: CurrentUser, indicator: str, region_key: str, level: str = "district", dim: str = "", all_revisions: bool = False) -> dict:
    rows = db.execute(sql(
        "SELECT r.period_key, r.period_end, r.revision, r.is_current, r.published_on, r.retrieved_at, v.value, v.value_status FROM stat_value v "
        "JOIN stat_release r ON r.id = v.release_id WHERE v.indicator_key = :k AND v.region_level = :l AND v.region_key = :r AND v.dim_key = :dim "
        "AND (:allrev OR r.is_current) ORDER BY r.period_end, r.revision"), {"k": indicator, "l": level, "r": region_key, "dim": dim, "allrev": all_revisions}).mappings().all()
    return {"indicator": indicator, "region_key": region_key,
            "points": [dict(r, value=float(r["value"]) if r["value"] is not None else None) for r in rows]}


_ = date
