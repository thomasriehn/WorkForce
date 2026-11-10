"""Stellensuche: Trefferliste, CSV-Export, Anzeigendetail, gespeicherte Suchen, Filterstammdaten."""
from __future__ import annotations

import csv
import io
from typing import Any

from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field
from sqlalchemy import select, text as sql

from ..models import MergedPosting, MergeLink, PostingEvent, PostingVersion, SavedSearch, Source, SourcePosting
from ..search import analytics
from ..search.query import KIND_GROUPS, SORTS
from .deps import CurrentUser, Db, FiltersDep

router = APIRouter(prefix="/api", tags=["postings"])

STATUS_LABELS = {
    "active": "aktiv beobachtet", "not_reobserved": "nicht erneut beobachtet", "presumed_removed": "vermutlich entfernt",
    "ended": "als beendet beobachtet", "stale": "unbekannt/veraltet",
}
KIND_LABELS = {"job": "Stelle", "ausbildung": "Ausbildung", "duales_studium": "Duales Studium", "praktikum": "Praktikum", "trainee": "Trainee/Volontariat",
               "werkstudent": "Werkstudent/stud. Hilfskraft", "minijob": "Minijob", "abschlussarbeit": "Abschlussarbeit"}


def safe_url(url: str | None) -> str | None:
    """Nur http(s)-Verweise werden an die Oberfläche gegeben (kein javascript:, data: …)."""
    if url and url.lower().startswith(("https://", "http://")):
        return url
    return None


def csv_cell(value: Any) -> str:
    """Schutz vor CSV-/Formel-Injection: Zellen mit Formelbeginn werden als Text maskiert."""
    if value is None:
        return ""
    if isinstance(value, (list, tuple)):
        value = ", ".join(str(v) for v in value)
    s = str(value).replace("\r", " ").replace("\n", " ")
    if s[:1] in ("=", "+", "-", "@", "\t", "|"):
        s = "'" + s
    return s


@router.get("/postings")
def list_postings(f: FiltersDep, db: Db, user: CurrentUser, page: int = Query(1, ge=1), page_size: int = Query(25, ge=1, le=200), sort: str | None = None) -> dict:
    if sort and sort not in SORTS and sort != "relevance":
        raise HTTPException(422, f"sort muss eines von {['relevance', *SORTS]} sein")
    res = analytics.search_postings(db, f, page=page, page_size=page_size, sort=sort)
    for it in res["items"]:
        it["original_url"] = safe_url(it.get("original_url"))
        it["status_label"] = STATUS_LABELS.get(it["status"], it["status"])
        it["kind_label"] = KIND_LABELS.get(it["kind"], it["kind"])
    res["totals"] = analytics.totals(db, f)
    res["near"] = f.near_info
    return res


@router.get("/postings/export.csv")
def export_csv(f: FiltersDep, db: Db, user: CurrentUser, sort: str | None = None) -> StreamingResponse:
    rows = analytics.export_rows(db, f, sort)
    names = dict(db.execute(select(Source.id, Source.name)).all())
    buf = io.StringIO()
    buf.write("﻿")
    w = csv.writer(buf, delimiter=";", quoting=csv.QUOTE_ALL)
    w.writerow(["ID", "Titel", "Arbeitgeber", "Arbeitsorte", "Kreisschlüssel", "Art", "Status", "Erstmals beobachtet", "Zuletzt beobachtet",
                "Veröffentlicht laut Quelle", "Bewerbungsfrist", "KldB", "Remote", "Arbeitszeit", "Befristung", "Merkmale", "Quellen", "Originalverweis"])
    for r in rows:
        w.writerow([csv_cell(x) for x in (
            r["id"], r["title"], r["employer_name"], r["places"], r["kreis_keys"], KIND_LABELS.get(r["kind"], r["kind"]), STATUS_LABELS.get(r["status"], r["status"]),
            r["first_seen_date"], r["last_seen_date"], r["date_posted"] or "unbekannt", r["apply_until"], r["kldb_code"], r["remote_type"] or "unbekannt",
            r["working_time"], r["contract_term"], r["feature_keys"], [names.get(s, s) for s in (r["source_ids"] or [])], safe_url(r["original_url"]))])
    buf.seek(0)
    return StreamingResponse(iter([buf.getvalue()]), media_type="text/csv; charset=utf-8",
                             headers={"Content-Disposition": 'attachment; filename="workforce-anzeigen.csv"', "X-Content-Type-Options": "nosniff"})


def _version_out(v: PostingVersion) -> dict[str, Any]:
    return {
        "id": v.id, "version_no": v.version_no, "change_kind": v.change_kind, "detail_level": v.detail_level, "valid_from": v.valid_from, "valid_to": v.valid_to,
        "parser_version": v.parser_version, "classifier_version": v.classifier_version, "geo_rule_version": v.geo_rule_version,
        "title": v.title, "employer_name": v.employer_name, "reference": v.reference, "employer_url": safe_url(v.employer_url), "is_agency": v.is_agency,
        "kind": v.kind, "kind_label": KIND_LABELS.get(v.kind, v.kind), "employment_types": v.employment_types, "working_time": v.working_time,
        "contract_term": v.contract_term, "remote_type": v.remote_type, "occupation_label": v.occupation_label, "occupation_field": v.occupation_field,
        "kldb_code": v.kldb_code, "kldb_source": v.kldb_source, "kldb_confidence": float(v.kldb_confidence) if v.kldb_confidence is not None else None,
        "requirement_level": v.requirement_level,
        "salary": {"min": float(v.salary_min) if v.salary_min else None, "max": float(v.salary_max) if v.salary_max else None, "currency": v.salary_currency,
                   "period": v.salary_period, "origin": v.salary_origin, "text": v.salary_text},
        "date_posted": v.date_posted, "apply_until": v.apply_until, "valid_through": v.valid_through, "excerpts": v.excerpts, "quality": v.quality,
        "geo_class": v.geo_class, "kreis_keys": v.kreis_keys,
        "locations": [{"raw": loc.raw_text, "locality": loc.locality, "postal_code": loc.postal_code, "country": loc.country, "kreis_key": loc.kreis_key,
                       "state_key": loc.state_key, "match_method": loc.match_method, "precision": loc.precision,
                       "confidence": float(loc.confidence) if loc.confidence is not None else None, "gebietsstand": loc.gebietsstand,
                       "point_origin": loc.point_origin} for loc in v.locations],
        "features": [{"key": ft.feature_key, "type": ft.type, "label": ft.label, "polarity": ft.polarity, "origin": ft.origin, "rule_version": ft.rule_version,
                      "confidence": float(ft.confidence) if ft.confidence is not None else None, "evidence": ft.evidence, "detail": ft.detail}
                     for ft in sorted(v.features, key=lambda x: (x.type, x.label))],
    }


@router.get("/postings/{posting_id}")
def posting_detail(posting_id: int, db: Db, user: CurrentUser) -> dict:
    mp = db.get(MergedPosting, posting_id)
    if mp is None:
        raise HTTPException(404, "Anzeige nicht gefunden")
    current = db.get(PostingVersion, mp.current_version_id) if mp.current_version_id else None
    names = dict(db.execute(select(Source.id, Source.name)).all())
    members = []
    for sp in db.execute(select(SourcePosting).where(SourcePosting.merged_posting_id == mp.id).order_by(SourcePosting.first_seen_at)).scalars().all():
        link = db.execute(select(MergeLink).where(MergeLink.source_posting_id == sp.id, MergeLink.is_active)).scalar_one_or_none()
        versions = db.execute(select(PostingVersion).where(PostingVersion.source_posting_id == sp.id).order_by(PostingVersion.version_no.desc())).scalars().all()
        periods = db.execute(sql("SELECT start_date, end_date, end_reason FROM activity_period WHERE source_posting_id = :i ORDER BY start_date"), {"i": sp.id}).mappings().all()
        members.append({
            "source_posting_id": sp.id, "source_id": sp.source_id, "source_name": names.get(sp.source_id), "source_key": sp.source_key,
            "original_url": safe_url(sp.original_url), "canonical_url": safe_url(sp.canonical_url), "status": sp.status,
            "status_label": STATUS_LABELS.get(sp.status, sp.status), "status_reason": sp.status_reason, "first_seen_at": sp.first_seen_at,
            "first_seen_baseline": sp.first_seen_baseline, "last_seen_at": sp.last_seen_at, "last_detail_check_at": sp.last_detail_check_at,
            "is_primary": sp.id == mp.primary_source_posting_id,
            "merge": {"reason": link.reason, "confidence": float(link.confidence), "rule_version": link.rule_version, "decided_by": link.decided_by,
                      "created_at": link.created_at} if link else None,
            "periods": [dict(p) for p in periods],
            "versions": [_version_out(v) for v in versions],
        })
    events = db.execute(select(PostingEvent).where(PostingEvent.merged_posting_id == mp.id).order_by(PostingEvent.at.desc()).limit(200)).scalars().all()
    return {
        "id": mp.id, "status": mp.status, "status_label": STATUS_LABELS.get(mp.status, mp.status), "first_seen_date": mp.first_seen_date,
        "first_seen_baseline": mp.first_seen_baseline, "last_seen_date": mp.last_seen_date, "member_count": mp.member_count,
        "dedup_rule_version": mp.dedup_rule_version, "is_synthetic": mp.is_synthetic,
        "current": _version_out(current) if current else None, "members": members,
        "events": [{"at": e.at, "event_date": e.event_date, "effective_date": e.effective_date, "type": e.event_type, "baseline": e.baseline,
                    "source_posting_id": e.source_posting_id, "details": e.details} for e in events],
        "notes": [
            "Eine Anzeige kann mehrere Stellen betreffen; derselbe Bedarf kann auf mehreren Portalen erscheinen.",
            "Eine entfernte Anzeige belegt nicht, dass die Stelle besetzt wurde.",
            "„Erstmals beobachtet“ ist kein Veröffentlichungsdatum.",
        ],
    }


@router.get("/meta/filters")
def meta_filters(db: Db, user: CurrentUser) -> dict:
    sources = db.execute(sql("SELECT id, key, name, config_status, adapter_key IS NOT NULL AS has_adapter FROM source ORDER BY name")).mappings().all()
    states = db.execute(sql("SELECT key, name FROM region WHERE level = 'state' AND is_current ORDER BY name")).mappings().all()
    feats = db.execute(sql("SELECT key, type, label, synonyms FROM feature ORDER BY type, label")).mappings().all()
    groups = db.execute(sql("SELECT code, name, level FROM kldb_class WHERE level <= 2 ORDER BY code")).mappings().all()
    return {
        "sources": [dict(r) for r in sources], "states": [dict(r) for r in states], "features": [dict(r) for r in feats],
        "kldb_groups": [dict(r) for r in groups], "kind_groups": list(KIND_GROUPS), "kind_labels": KIND_LABELS, "status_labels": STATUS_LABELS,
        "sorts": ["relevance", *SORTS],
        "feature_types": {"qual": "Formaler Abschluss", "exp": "Erfahrung", "skill": "Fachliche Kenntnisse", "cert": "Zertifikat", "lang": "Sprache", "license": "Berechtigung"},
    }


@router.get("/meta/kldb")
def kldb_search(db: Db, user: CurrentUser, q: str = Query(..., min_length=2, max_length=80)) -> list[dict]:
    from ..normalize.text import fold

    rows = db.execute(sql(
        "SELECT code, name, level FROM kldb_class WHERE code LIKE :pfx OR lower(name) LIKE :like ORDER BY level, code LIMIT 30"),
        {"pfx": q.strip() + "%", "like": f"%{q.strip().lower()}%"}).mappings().all()
    titles = db.execute(sql(
        "SELECT DISTINCT ot.kldb_code AS code, ot.title AS name, 5 AS level FROM occupation_title ot WHERE ot.title_norm LIKE :like ORDER BY 2 LIMIT 20"),
        {"like": f"%{fold(q)}%"}).mappings().all()
    return [dict(r) for r in rows] + [dict(r, from_title=True) for r in titles]


class SavedSearchIn(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    params: dict[str, Any]


@router.get("/saved-searches")
def saved_list(db: Db, user: CurrentUser) -> list[dict]:
    rows = db.execute(select(SavedSearch).where(SavedSearch.user_id == user.id).order_by(SavedSearch.name)).scalars().all()
    return [{"id": r.id, "name": r.name, "params": r.params, "created_at": r.created_at} for r in rows]


@router.post("/saved-searches")
def saved_create(body: SavedSearchIn, db: Db, user: CurrentUser) -> dict:
    existing = db.execute(select(SavedSearch).where(SavedSearch.user_id == user.id, SavedSearch.name == body.name)).scalar_one_or_none()
    if existing is not None:
        existing.params = body.params
        return {"id": existing.id, "name": existing.name, "updated": True}
    row = SavedSearch(user_id=user.id, name=body.name, params=body.params)
    db.add(row)
    db.flush()
    return {"id": row.id, "name": row.name, "updated": False}


@router.delete("/saved-searches/{search_id}")
def saved_delete(search_id: int, db: Db, user: CurrentUser) -> dict:
    row = db.get(SavedSearch, search_id)
    if row is None or row.user_id != user.id:
        raise HTTPException(404, "Gespeicherte Suche nicht gefunden")
    db.delete(row)
    return {"ok": True}
