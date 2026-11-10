"""Tägliche Aggregate je Kreis – reproduzierbar aus der Historie neu berechenbar, mit Regelversionen.

Die letzten Tage werden nächtlich neu berechnet, weil ein Wegfall erst nach mehreren vollständigen
Scans feststeht und der Bestand dann rückwirkend korrigiert wird (siehe Methodik).
"""
from __future__ import annotations

from dataclasses import replace
from datetime import date, timedelta
from typing import Any

from sqlalchemy import text as sql
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import Session

from ..config import AGGREGATE_VERSION, CLASSIFIER_VERSION, DEDUP_RULE_VERSION, GEO_RULE_VERSION, get_settings
from ..models import DailyAggregate
from ..search.analytics import _kreis_counts, coverage_at, totals
from ..search.query import KIND_GROUPS, Filters


def compute_day(db: Session, d: date, *, include_synthetic: bool = False) -> int:
    """Berechnet die Aggregate eines Tages neu (ersetzt vorhandene Zeilen des Tages)."""
    db.execute(sql("DELETE FROM daily_aggregate WHERE agg_date = :d"), {"d": d})
    cov = coverage_at(db, d)
    basis: dict[str, Any] = {
        str(sid): {"name": c["name"], "complete": sorted(f"{k} v{v}" for k, v in c["complete"]), "incomplete": c["incomplete"]}
        for sid, c in cov.items()
    }
    rows = 0
    for kg in KIND_GROUPS:
        f = Filters(kind_group=kg, as_of=d, include_synthetic=include_synthetic)
        counts = _kreis_counts(db, f)
        tot = totals(db, f)
        ev = dict(db.execute(sql(
            "SELECT e.event_type || CASE WHEN e.baseline THEN '#baseline' ELSE '' END, count(DISTINCT e.merged_posting_id) FROM posting_event e "
            "JOIN merged_posting mp ON mp.id = e.merged_posting_id JOIN posting_version pv ON pv.id = coalesce(e.version_id, mp.current_version_id) "
            "WHERE e.effective_date = :d AND (:syn OR NOT mp.is_synthetic) AND (CAST(:kinds AS text[]) IS NULL OR pv.kind = ANY(:kinds)) GROUP BY 1"),
            {"d": d, "kinds": KIND_GROUPS[kg], "syn": include_synthetic}).all())
        observed = db.execute(sql(
            "SELECT count(DISTINCT sp.merged_posting_id) FROM observation o JOIN scan_run r ON r.id = o.run_id "
            "JOIN source_posting sp ON sp.id = o.source_posting_id JOIN posting_version pv ON pv.id = sp.current_version_id "
            "WHERE r.logical_date = :d AND NOT r.is_test AND (:syn OR NOT sp.is_synthetic) AND (CAST(:kinds AS text[]) IS NULL OR pv.kind = ANY(:kinds))"),
            {"d": d, "kinds": KIND_GROUPS[kg], "syn": include_synthetic}).scalar_one()
        common = dict(agg_date=d, kind_group=kg, basis=basis, dedup_rule_version=DEDUP_RULE_VERSION, classifier_version=CLASSIFIER_VERSION,
                      geo_rule_version=GEO_RULE_VERSION, aggregate_version=AGGREGATE_VERSION)
        payload = [dict(common, region_key="__ALL__", weighted_count=tot["total"], distinct_count=tot["total"],
                        first_seen_count=int(ev.get("first_seen", 0)), changed_count=int(ev.get("content_change", 0)),
                        left_count=int(ev.get("left_stock", 0)), observed_count=int(observed or 0))]
        for special, key in (("partial", "__PARTIAL__"), ("unresolved", "__UNRESOLVED__"), ("remote_nationwide", "__REMOTE__"), ("foreign", "__FOREIGN__"), ("none", "__NONE__")):
            n = tot["geo"].get(special, 0)
            if n:
                payload.append(dict(common, region_key=key, weighted_count=n, distinct_count=n, first_seen_count=0, changed_count=0, left_count=0, observed_count=0))
        for key, (weighted, distinct) in counts.items():
            payload.append(dict(common, region_key=key, weighted_count=round(weighted, 4), distinct_count=distinct, first_seen_count=0,
                                changed_count=0, left_count=0, observed_count=0))
        db.execute(pg_insert(DailyAggregate), payload)
        rows += len(payload)
    db.flush()
    return rows


def compute_range(db: Session, d_from: date, d_to: date, *, include_synthetic: bool = False) -> dict[str, Any]:
    n = 0
    d = d_from
    while d <= d_to:
        n += compute_day(db, d, include_synthetic=include_synthetic)
        db.commit()
        d += timedelta(days=1)
    return {"from": d_from.isoformat(), "to": d_to.isoformat(), "rows": n}


def nightly(db: Session, today: date) -> dict[str, Any]:
    """Neuberechnung des Korrekturfensters (Wegfallschwelle + Veraltungsfrist) bis heute."""
    s = get_settings()
    first = db.execute(sql("SELECT min(logical_date) FROM scan_run WHERE NOT is_test")).scalar_one_or_none()
    if first is None:
        return {"rows": 0, "note": "noch keine Läufe"}
    start = max(first, today - timedelta(days=s.stale_after_days + s.missing_scans_threshold + 2))
    return compute_range(db, start, today)


_ = replace
