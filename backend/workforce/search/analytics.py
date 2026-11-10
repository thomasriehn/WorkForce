"""Auswertungen auf der gemeinsamen Bezugsbasis: Trefferliste, Karte, Summen, Zeitreihen, Vergleichbarkeit.

Zählregeln (siehe docs/methodik.md):
* Deutschlandweit zählt jede zusammengeführte Anzeige genau einmal.
* Kreiskarte: Anzeige mit ``k`` eindeutig zugeordneten Kreisen zählt je Kreis ``1/k`` („anteilig gezählte
  Anzeigen“) – nur wenn **alle** Arbeitsorte zugeordnet sind (``geo_class = resolved``).
* „Unterschiedliche Anzeigen mit Bezug zum Kreis“ zählt jede Anzeige je Kreis ganz (nicht addierbar).
* Teilweise ungeklärte Mehrfachstandorte, ungeklärte Orte und deutschlandweite Remote-Angebote werden
  getrennt ausgewiesen und keinem Ort zugeschlagen.
"""
from __future__ import annotations

from dataclasses import replace
from datetime import date, timedelta
from decimal import Decimal
from typing import Any

from sqlalchemy import text as sql
from sqlalchemy.orm import Session

from ..config import AGGREGATE_VERSION, CLASSIFIER_VERSION, DEDUP_RULE_VERSION, GEO_RULE_VERSION, get_settings
from .query import Filters, build_where, order_clause

POP_INDICATOR = "bev_15_bis_unter_65"
LIST_COLUMNS = """
mp.id, mp.status, mp.first_seen_date, mp.first_seen_baseline, mp.last_seen_date, mp.member_count, mp.source_ids,
pv.title, pv.employer_name, pv.kind, pv.remote_type, pv.working_time, pv.contract_term, pv.date_posted, pv.apply_until,
pv.valid_through, pv.kldb_code, pv.kldb_source, pv.kldb_confidence, pv.occupation_label, pv.kreis_keys, pv.state_keys,
pv.geo_class, pv.loc_total, pv.loc_unresolved, pv.feature_keys, pv.feature_required_keys, pv.is_agency, pv.salary_min,
pv.salary_max, pv.salary_currency, pv.salary_period, pv.salary_origin, pv.salary_text, pv.detail_level,
(SELECT string_agg(DISTINCT coalesce(nullif(concat_ws(' ', pl.postal_code, pl.locality), ''), pl.raw_text), '; ')
   FROM posting_location pl WHERE pl.version_id = pv.id) AS places,
(SELECT sp.original_url FROM source_posting sp WHERE sp.id = mp.primary_source_posting_id) AS original_url
"""


def _f(v: Any) -> Any:
    return float(v) if isinstance(v, Decimal) else v


def reference_date(db: Session) -> date:
    """Jüngstes logisches Datum mit einem regulären Lauf (sonst heute, lokale Zeit)."""
    from datetime import datetime

    d = db.execute(sql("SELECT max(logical_date) FROM scan_run WHERE NOT is_test AND status IN ('complete','partial')")).scalar_one_or_none()
    return d or datetime.now(get_settings().tz).date()


def search_postings(db: Session, f: Filters, *, page: int = 1, page_size: int = 25, sort: str | None = None) -> dict[str, Any]:
    where, params = build_where(f)
    total = db.execute(sql(f"SELECT count(*) {where}"), params).scalar_one()
    page = max(1, page)
    page_size = max(1, min(200, page_size))
    rows = db.execute(
        sql(f"SELECT {LIST_COLUMNS} {where} ORDER BY {order_clause(f, sort)} LIMIT :limit OFFSET :offset"),
        {**params, "limit": page_size, "offset": (page - 1) * page_size},
    ).mappings().all()
    return {"total": total, "page": page, "page_size": page_size, "items": [{k: _f(v) for k, v in r.items()} for r in rows], "scope": f.describe_scope()}


def export_rows(db: Session, f: Filters, sort: str | None = None, limit: int = 50_000) -> list[dict[str, Any]]:
    where, params = build_where(f)
    rows = db.execute(sql(f"SELECT {LIST_COLUMNS} {where} ORDER BY {order_clause(f, sort)} LIMIT :limit"), {**params, "limit": limit}).mappings().all()
    return [dict(r) for r in rows]


def totals(db: Session, f: Filters) -> dict[str, Any]:
    """Summen der Bezugsbasis: deutschlandweit einmal je Anzeige, aufgeschlüsselt nach geografischer Zuordnung."""
    where, params = build_where(f)
    rows = db.execute(sql(f"SELECT pv.geo_class, count(*) AS n {where} GROUP BY pv.geo_class"), params).all()
    by = {r[0]: int(r[1]) for r in rows}
    return {
        "total": sum(by.values()),
        "geo": {k: by.get(k, 0) for k in ("resolved", "partial", "unresolved", "remote_nationwide", "foreign", "none")},
        "labels": {
            "resolved": "alle Arbeitsorte einem Kreis zugeordnet (in der anteiligen Karte enthalten)",
            "partial": "geografisch teilweise ungeklärt (nicht in der anteiligen Karte)",
            "unresolved": "Arbeitsort ungeklärt",
            "remote_nationwide": "deutschlandweit remote (keinem Ort zugeordnet)",
            "foreign": "Arbeitsort im Ausland",
            "none": "ohne Ortsangabe",
        },
    }


def population_15_65(db: Session) -> tuple[dict[str, float], dict[str, Any] | None]:
    """Jüngster importierter Stand der Bevölkerung 15 bis unter 65 je Kreis (nur aus passenden Altersgruppen)."""
    rel = db.execute(sql(
        "SELECT r.id, r.period_key, r.period_end, r.revision, r.published_on, r.retrieved_at, r.gebietsstand, d.name, d.attribution "
        "FROM stat_release r JOIN stat_dataset d ON d.key = r.dataset_key "
        "WHERE r.is_current AND EXISTS (SELECT 1 FROM stat_value v WHERE v.release_id = r.id AND v.indicator_key = :ind AND v.region_level = 'district') "
        "ORDER BY r.period_end DESC, r.revision DESC LIMIT 1"), {"ind": POP_INDICATOR}).mappings().first()
    if rel is None:
        return {}, None
    vals = db.execute(sql(
        "SELECT region_key, value FROM stat_value WHERE release_id = :r AND indicator_key = :ind AND region_level = 'district' "
        "AND value_status = 'ok' AND value > 0"), {"r": rel["id"], "ind": POP_INDICATOR}).all()
    return {k: float(v) for k, v in vals}, {k: (v.isoformat() if hasattr(v, "isoformat") else v) for k, v in dict(rel).items()}


def _kreis_counts(db: Session, f: Filters) -> dict[str, tuple[float, int]]:
    where, params = build_where(f, ignore_kreise=True)
    rows = db.execute(sql(
        f"WITH snap AS (SELECT pv.kreis_keys, pv.geo_class {where}) "
        "SELECT k, coalesce(sum(1.0 / cardinality(kreis_keys)) FILTER (WHERE geo_class = 'resolved'), 0), count(*) "
        "FROM snap, unnest(kreis_keys) AS k GROUP BY k"), params).all()
    return {r[0]: (float(r[1]), int(r[2])) for r in rows}


def map_metrics(db: Session, f: Filters) -> dict[str, Any]:
    """Kennzahlen je Kreis. Der Kreisfilter wirkt hier nicht (die Karte zeigt immer alle Kreise)."""
    s = get_settings()
    counts = _kreis_counts(db, f)
    pop, pop_release = population_15_65(db)
    regions = []
    for key, (weighted, distinct) in sorted(counts.items()):
        denom = pop.get(key)
        regions.append({
            "key": key, "weighted": round(weighted, 4), "distinct": distinct,
            # kein Quotient bei fehlendem oder nullwertigem Nenner
            "rate_per_1000": round(weighted / denom * 1000, 4) if denom else None,
            "population_15_65": denom, "low_count": distinct < s.small_count_threshold,
        })
    f_tot = replace(f, kreise=[])
    return {
        "as_of": f.as_of.isoformat() if f.as_of else None, "regions": regions, "totals": totals(db, f_tot),
        "weighted_sum": round(sum(r["weighted"] for r in regions), 4), "population_release": pop_release,
        "small_count_threshold": s.small_count_threshold,
        "rule_versions": {"dedup": DEDUP_RULE_VERSION, "classifier": CLASSIFIER_VERSION, "geo": GEO_RULE_VERSION, "aggregate": AGGREGATE_VERSION},
        "formulas": {
            "weighted": "Σ über Anzeigen mit vollständig zugeordneten Arbeitsorten: 1 / (Anzahl unterschiedlicher Kreise der Anzeige)",
            "distinct": "Anzahl unterschiedlicher zusammengeführter Anzeigen mit mindestens einem Arbeitsort im Kreis (nicht addierbar)",
            "rate_per_1000": "anteilig gezählte Anzeigen / Bevölkerung 15 bis unter 65 Jahre × 1.000 (nur bei vorhandenem Nenner > 0)",
        },
    }


# ---------------------------------------------------------------------------------------------------
def coverage_at(db: Session, d: date) -> dict[int, dict[str, Any]]:
    """Abdeckung je Quelle am Tag ``d``: welche Suchbereichsversionen wurden vollständig gescannt?"""
    rows = db.execute(sql(
        "SELECT DISTINCT ON (r.scope_id) r.source_id, r.scope_id, r.scope_key, r.scope_version, r.status, r.list_complete, r.logical_date, "
        "r.parser_version, s.name FROM scan_run r JOIN source s ON s.id = r.source_id "
        "WHERE NOT r.is_test AND r.logical_date BETWEEN :d1 AND :d ORDER BY r.scope_id, r.logical_date DESC, r.id DESC"),
        {"d": d, "d1": d - timedelta(days=1)}).mappings().all()
    out: dict[int, dict[str, Any]] = {}
    for r in rows:
        src = out.setdefault(r["source_id"], {"name": r["name"], "complete": set(), "incomplete": [], "parsers": set()})
        if r["status"] == "complete" and r["list_complete"]:
            src["complete"].add((r["scope_key"], r["scope_version"]))
        else:
            src["incomplete"].append(f"{r['scope_key']} v{r['scope_version']}: {r['status']}")
        if r["parser_version"]:
            src["parsers"].add(r["parser_version"])
    return out


def comparable_basis(db: Session, d_now: date, d_then: date, sources: list[int] | None = None) -> dict[str, Any]:
    """Bestimmt, welche Quellen an beiden Tagen mit denselben Suchbereichsversionen vollständig erfasst wurden."""
    now, then = coverage_at(db, d_now), coverage_at(db, d_then)
    comparable: list[int] = []
    excluded: list[dict[str, Any]] = []
    hints: list[str] = []
    for sid in sorted(set(now) | set(then)):
        if sources and sid not in sources:
            continue
        a, b = now.get(sid), then.get(sid)
        name = (a or b or {}).get("name")
        if b is None:
            excluded.append({"source_id": sid, "name": name, "reason": f"am {d_then:%d.%m.%Y} noch nicht erfasst (neue Quelle)"})
        elif a is None:
            excluded.append({"source_id": sid, "name": name, "reason": f"am {d_now:%d.%m.%Y} kein Lauf"})
        elif not a["complete"] or a["incomplete"]:
            excluded.append({"source_id": sid, "name": name, "reason": f"am {d_now:%d.%m.%Y} kein vollständiger Lauf ({'; '.join(a['incomplete']) or 'kein Lauf'})"})
        elif not b["complete"] or b["incomplete"]:
            excluded.append({"source_id": sid, "name": name, "reason": f"am {d_then:%d.%m.%Y} kein vollständiger Lauf ({'; '.join(b['incomplete']) or 'kein Lauf'})"})
        elif a["complete"] != b["complete"]:
            excluded.append({"source_id": sid, "name": name, "reason": "Suchbereich zwischen den Stichtagen geändert"})
        else:
            comparable.append(sid)
            if a["parsers"] != b["parsers"]:
                hints.append(f"{name}: Parserversion geändert ({', '.join(sorted(b['parsers']))} → {', '.join(sorted(a['parsers']))})")
    notes = db.execute(sql("SELECT note_date, kind, message FROM timeline_note WHERE note_date > :a AND note_date <= :b ORDER BY note_date"),
                       {"a": d_then, "b": d_now}).mappings().all()
    return {"date_now": d_now.isoformat(), "date_then": d_then.isoformat(), "comparable_sources": comparable, "excluded": excluded,
            "hints": hints, "notes": [{"date": n["note_date"].isoformat(), "kind": n["kind"], "message": n["message"]} for n in notes],
            "comparable": bool(comparable)}


def _change(now: float, then: float) -> dict[str, Any]:
    out: dict[str, Any] = {"now": round(now, 4), "then": round(then, 4), "abs": round(now - then, 4), "pct": None, "pct_note": None}
    if then > 0:
        out["pct"] = round((now - then) / then * 100, 2)
    else:
        out["pct_note"] = "Ausgangswert 0 – nur absolute Veränderung"
    return out


def map_change(db: Session, f: Filters, days: int, *, metric: str = "weighted") -> dict[str, Any]:
    """Veränderung je Kreis über ``days`` Tage – nur auf vergleichbarer Abdeckung (gleiche Quellen/Suchbereiche)."""
    d_now = f.as_of or reference_date(db)
    d_then = d_now - timedelta(days=days)
    basis = comparable_basis(db, d_now, d_then, f.sources or None)
    result: dict[str, Any] = {"days": days, "metric": metric, "basis": basis, "regions": [], "total": None}
    if not basis["comparable"]:
        result["message"] = "Kein Vergleich möglich: Für die beiden Stichtage liegt keine vergleichbare Abdeckung vor."
        return result
    srcs = basis["comparable_sources"]
    f_now, f_then = replace(f, as_of=d_now, sources=srcs), replace(f, as_of=d_then, sources=srcs)
    c_now, c_then = _kreis_counts(db, f_now), _kreis_counts(db, f_then)
    idx = 0 if metric == "weighted" else 1
    s = get_settings()
    for key in sorted(set(c_now) | set(c_then)):
        a, b = c_now.get(key, (0.0, 0)), c_then.get(key, (0.0, 0))
        row = {"key": key, **_change(float(a[idx]), float(b[idx])), "low_count": max(a[1], b[1]) < s.small_count_threshold}
        result["regions"].append(row)
    w_now, p_now = build_where(replace(f_now, kreise=[]))
    w_then, p_then = build_where(replace(f_then, kreise=[]))
    t_now = db.execute(sql(f"SELECT count(*) {w_now}"), p_now).scalar_one()
    t_then = db.execute(sql(f"SELECT count(*) {w_then}"), p_then).scalar_one()
    result["total"] = _change(float(t_now), float(t_then))
    return result


# ---------------------------------------------------------------------------------------------------
def _is_default(f: Filters) -> bool:
    return not any([f.q, f.kldb, f.features, f.states, f.kreise, f.near, f.sources, f.remote, f.working_time, f.contract_term,
                    f.geo_classes, f.employer, f.date_from, f.date_to, f.include_synthetic])


def _event_where(f: Filters) -> tuple[str, dict[str, Any]]:
    """Bedingungen für Ereignisse: gleiche fachliche Filter, aber ohne Bestandsbedingung."""
    where, params = build_where(replace(f, as_of=None, statuses=["active", "not_reobserved", "presumed_removed", "ended", "stale"], sources=[]), ignore_dates=True)
    cond = where.split(" WHERE ", 1)[1]
    frm = ("FROM posting_event e JOIN merged_posting mp ON mp.id = e.merged_posting_id "
           "JOIN posting_version pv ON pv.id = coalesce(e.version_id, mp.current_version_id)")
    if f.sources:
        cond += " AND e.source_posting_id IN (SELECT id FROM source_posting WHERE source_id = ANY(:sources))"
        params["sources"] = list(f.sources)
    return f"{frm} WHERE {cond}", params


def run_quality(db: Session, d_from: date, d_to: date) -> dict[str, dict[str, Any]]:
    rows = db.execute(sql(
        "SELECT logical_date, count(*) FILTER (WHERE status = 'complete' AND list_complete) AS ok, "
        "count(*) FILTER (WHERE status IN ('partial','blocked','failed','cancelled') OR (status = 'complete' AND NOT coalesce(list_complete, false))) AS bad, count(*) AS n "
        "FROM scan_run WHERE NOT is_test AND logical_date BETWEEN :a AND :b GROUP BY 1"), {"a": d_from, "b": d_to}).all()
    out = {}
    for d, ok, bad, n in rows:
        out[d.isoformat()] = {"runs": n, "complete": ok, "incomplete": bad, "quality": "complete" if bad == 0 and ok > 0 else ("partial" if ok > 0 or bad > 0 else "none")}
    return out


def timeseries(db: Session, f: Filters, d_from: date, d_to: date, *, max_points: int = 45) -> dict[str, Any]:
    """Bestand, erstmals beobachtete, fachlich geänderte und aus dem Bestand gefallene Anzeigen je Tag."""
    d_to = min(d_to, reference_date(db))
    if d_from > d_to:
        d_from = d_to
    n_days = (d_to - d_from).days + 1
    step = max(1, -(-n_days // max_points))
    dates = [d_to - timedelta(days=i) for i in range(0, n_days, step)][::-1]
    stock: dict[str, int | None] = {}
    use_agg = _is_default(f)
    if use_agg:
        rows = db.execute(sql("SELECT agg_date, distinct_count FROM daily_aggregate WHERE region_key = '__ALL__' AND kind_group = :kg "
                              "AND agg_date BETWEEN :a AND :b"), {"kg": f.kind_group, "a": d_from, "b": d_to}).all()
        agg = {r[0]: int(r[1]) for r in rows}
    for d in dates:
        if use_agg and d in agg:
            stock[d.isoformat()] = agg[d]
            continue
        where, params = build_where(replace(f, as_of=d), ignore_dates=True)
        stock[d.isoformat()] = int(db.execute(sql(f"SELECT count(*) {where}"), params).scalar_one())
    ew, ep = _event_where(f)
    ev_rows = db.execute(sql(
        f"SELECT e.effective_date, e.event_type, e.baseline, count(DISTINCT e.merged_posting_id) {ew} "
        "AND e.effective_date BETWEEN :ev_a AND :ev_b AND e.event_type IN ('first_seen','content_change','left_stock','republication','reactivation') "
        "GROUP BY 1, 2, 3"), {**ep, "ev_a": d_from, "ev_b": d_to}).all()
    events: dict[str, dict[str, int]] = {}
    for d, etype, baseline, n in ev_rows:
        key = "baseline" if etype == "first_seen" and baseline else etype
        events.setdefault(d.isoformat(), {})[key] = events.get(d.isoformat(), {}).get(key, 0) + int(n)
    quality = run_quality(db, d_from, d_to)
    first_run = db.execute(sql("SELECT min(logical_date) FROM scan_run WHERE NOT is_test")).scalar_one_or_none()
    points = []
    for i in range(n_days):
        d = d_from + timedelta(days=i)
        iso = d.isoformat()
        ev = events.get(iso, {})
        q = quality.get(iso, {"quality": "none", "runs": 0})
        points.append({
            "date": iso, "stock": stock.get(iso), "first_seen": ev.get("first_seen", 0), "baseline": ev.get("baseline", 0),
            "changed": ev.get("content_change", 0), "left": ev.get("left_stock", 0), "republished": ev.get("republication", 0),
            "reactivated": ev.get("reactivation", 0), "run_quality": q["quality"],
            "before_start": bool(first_run and d < first_run) or first_run is None,
        })
    notes = db.execute(sql("SELECT note_date, kind, message FROM timeline_note WHERE note_date BETWEEN :a AND :b ORDER BY note_date"), {"a": d_from, "b": d_to}).mappings().all()
    s = get_settings()
    return {
        "from": d_from.isoformat(), "to": d_to.isoformat(), "points": points, "sampled_every_days": step,
        "notes": [{"date": n["note_date"].isoformat(), "kind": n["kind"], "message": n["message"]} for n in notes],
        "provisional_days": s.missing_scans_threshold,
        "definitions": {
            "stock": "bekannter Bestand: zusammengeführte Anzeigen, die am Tag zum beobachteten Bestand zählten (rückwirkend korrigiert, sobald ein Wegfall bestätigt ist)",
            "first_seen": "erstmals beobachtete Anzeigen – ohne die Bestandsaufnahme (Erstlauf einer Quelle/eines Suchbereichs)",
            "baseline": "bei einer Bestandsaufnahme erstmals gesehene Anzeigen – keine Neuveröffentlichungen",
            "changed": "Anzeigen mit fachlicher Inhaltsänderung (ohne Parser-/Regelwechsel)",
            "left": "aus dem Bestand gefallen (vermutlich entfernt, beendet laut Quelle oder veraltet) – datiert auf den Tag nach der letzten Sichtung",
            "run_quality": "complete = alle Läufe des Tages vollständig; partial = mindestens ein unvollständiger Lauf; none = kein Lauf (Datenlücke)",
        },
    }


def facets(db: Session, f: Filters, limit: int = 12) -> dict[str, Any]:
    where, params = build_where(f)
    occ = db.execute(sql(
        f"SELECT pv.kldb_code, k.name, count(*) AS n {where} AND pv.kldb_code IS NOT NULL "
        .replace(" WHERE ", " LEFT JOIN kldb_class k ON k.code = pv.kldb_code WHERE ", 1) + "GROUP BY 1, 2 ORDER BY n DESC LIMIT :lim"), {**params, "lim": limit}).all()
    feats = db.execute(sql(
        f"WITH snap AS (SELECT pv.feature_keys, pv.feature_required_keys {where}) "
        "SELECT k, count(*) AS n, count(*) FILTER (WHERE k = ANY(feature_required_keys)) AS req FROM snap, unnest(feature_keys) AS k "
        "GROUP BY k ORDER BY n DESC LIMIT :lim"), {**params, "lim": limit}).all()
    labels = dict(db.execute(sql("SELECT key, label FROM feature")).all())
    employers = db.execute(sql(f"SELECT pv.employer_name, count(*) AS n {where} AND pv.employer_name IS NOT NULL GROUP BY 1 ORDER BY n DESC LIMIT :lim"),
                           {**params, "lim": limit}).all()
    kinds = db.execute(sql(f"SELECT pv.kind, count(*) {where} GROUP BY 1 ORDER BY 2 DESC"), params).all()
    unclassified = db.execute(sql(f"SELECT count(*) {where} AND pv.kldb_code IS NULL"), params).scalar_one()
    return {
        "occupations": [{"kldb_code": r[0], "name": r[1], "count": int(r[2])} for r in occ],
        "occupations_unclassified": int(unclassified),
        "features": [{"key": r[0], "label": labels.get(r[0], r[0]), "count": int(r[1]), "required": int(r[2])} for r in feats],
        "employers": [{"name": r[0], "count": int(r[1])} for r in employers],
        "kinds": [{"kind": r[0], "count": int(r[1])} for r in kinds],
    }
