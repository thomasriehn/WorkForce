"""Quellenverwaltung, Scanläufe, Zusammenführungen, Benutzer, Statistikimporte (schreibend nur für Administratoren)."""
from __future__ import annotations

import shutil
import tempfile
from pathlib import Path
from typing import Any

from fastapi import APIRouter, File, Form, HTTPException, Query, UploadFile
from pydantic import BaseModel, Field
from sqlalchemy import select, text as sql

from ..config import VERSION, get_settings
from ..jobs import queue
from ..jobs.scheduler import enqueue_run
from ..models import MergeCandidate, ScanError, ScanRun, ScanTask, SearchScope, Source, SourcePosting, User
from ..pipeline import dedup
from ..pipeline.run import create_run, local_today, request_control
from ..security import generate_password, hash_password
from ..sources.adapters import ADAPTERS
from ..sources.manage import SourceError, activate, deactivate, new_scope_version, source_health
from .deps import Admin, CurrentUser, Db, audit

router = APIRouter(prefix="/api", tags=["admin"])


def _source_out(db, s: Source, detail: bool = False) -> dict[str, Any]:
    adapter = ADAPTERS.get(s.adapter_key or "")
    out: dict[str, Any] = {
        "id": s.id, "key": s.key, "name": s.name, "domain": s.domain, "entry_url": s.entry_url, "country": s.country, "segment": s.segment,
        "is_career_page": s.is_career_page, "access_method": s.access_method, "adapter_key": s.adapter_key, "adapter_version": s.adapter_version,
        "adapter_available": adapter is not None, "discovery_mode": adapter.discovery_mode if adapter else None,
        "store_excerpts": adapter.store_excerpts if adapter else None, "allowed_domains": s.allowed_domains,
        "terms_url": s.terms_url, "robots_url": s.robots_url, "legal_checked_on": s.legal_checked_on, "legal_notes": s.legal_notes, "attribution": s.attribution,
        "config_status": s.config_status, "status_reason": s.status_reason,
        "budget": {"request_interval_seconds": float(s.request_interval_seconds), "max_pages_per_run": s.max_pages_per_run, "max_details_per_run": s.max_details_per_run},
        "updated_at": s.updated_at, **source_health(db, s),
        "scopes": [{"id": sc.id, "key": sc.key, "version": sc.version, "name": sc.name, "mode": sc.mode, "params": sc.params, "is_active": sc.is_active,
                    "page_budget": sc.page_budget, "note": sc.note, "created_at": sc.created_at, "retired_at": sc.retired_at}
                   for sc in s.scopes if detail or sc.is_active],
    }
    return out


def _get_source(db, source_id: int) -> Source:
    s = db.get(Source, source_id)
    if s is None:
        raise HTTPException(404, "Quelle nicht gefunden")
    return s


@router.get("/sources")
def sources(db: Db, user: CurrentUser) -> dict:
    rows = db.execute(select(Source).order_by(Source.name)).scalars().all()
    s = get_settings()
    return {"sources": [_source_out(db, r) for r in rows],
            "crawler": {"user_agent": s.user_agent, "contact_configured": bool(s.crawler_contact.strip()), "scan_time": s.scan_time, "timezone": s.timezone},
            "status_labels": {"candidate": "vorgemerkt", "active": "aktiv (freigegeben)", "disabled": "deaktiviert", "permission_required": "Erlaubnis erforderlich"},
            "health_labels": {"ok": "letzter Lauf vollständig", "degraded": "letzter Lauf unvollständig", "blocked": "blockiert", "failing": "fehlgeschlagen",
                              "running": "läuft", "never_run": "noch kein Lauf", "inactive": "nicht aktiv"}}


@router.get("/sources/{source_id}")
def source_detail(source_id: int, db: Db, user: CurrentUser) -> dict:
    return _source_out(db, _get_source(db, source_id), detail=True)


class ActivateIn(BaseModel):
    basis: str
    permission_reference: str | None = None


class DeactivateIn(BaseModel):
    reason: str
    status: str = "disabled"


class BudgetIn(BaseModel):
    request_interval_seconds: float | None = Field(None, ge=1, le=600)
    max_pages_per_run: int | None = Field(None, ge=1, le=5000)
    max_details_per_run: int | None = Field(None, ge=0, le=20000)


class ScopeIn(BaseModel):
    key: str = Field(pattern=r"^[a-z0-9_\-]{1,80}$")
    name: str = Field(min_length=1, max_length=200)
    params: dict[str, Any] = {}
    mode: str = "full"
    page_budget: int | None = Field(None, ge=1, le=5000)
    note: str | None = None


class RunIn(BaseModel):
    scope_key: str | None = None
    test: bool = False
    page_limit: int | None = Field(None, ge=1, le=500)


class CareerSourceIn(BaseModel):
    key: str = Field(pattern=r"^[a-z0-9_]{3,60}$")
    name: str = Field(min_length=2, max_length=160)
    domain: str = Field(pattern=r"^[a-z0-9.\-]{4,160}$")
    sitemap_url: str
    url_pattern: str
    id_pattern: str | None = None
    terms_url: str | None = None
    legal_notes: str = Field(min_length=20)


@router.post("/sources/{source_id}/activate")
def source_activate(source_id: int, body: ActivateIn, db: Db, admin: Admin) -> dict:
    s = _get_source(db, source_id)
    try:
        activate(db, s, basis=body.basis, permission_reference=body.permission_reference, username=admin.username)
    except SourceError as exc:
        raise HTTPException(422, str(exc)) from exc
    return _source_out(db, s)


@router.post("/sources/{source_id}/deactivate")
def source_deactivate(source_id: int, body: DeactivateIn, db: Db, admin: Admin) -> dict:
    s = _get_source(db, source_id)
    try:
        deactivate(db, s, reason=body.reason, username=admin.username, status=body.status)
    except SourceError as exc:
        raise HTTPException(422, str(exc)) from exc
    return _source_out(db, s)


@router.patch("/sources/{source_id}/budget")
def source_budget(source_id: int, body: BudgetIn, db: Db, admin: Admin) -> dict:
    s = _get_source(db, source_id)
    for k, v in body.model_dump(exclude_none=True).items():
        setattr(s, k, v)
    audit(db, admin, "source_budget", source=s.key, **body.model_dump(exclude_none=True))
    db.flush()
    return _source_out(db, s)


@router.post("/sources/{source_id}/scopes")
def scope_save(source_id: int, body: ScopeIn, db: Db, admin: Admin) -> dict:
    s = _get_source(db, source_id)
    try:
        new_scope_version(db, s, body.key, name=body.name, params=body.params, mode=body.mode, page_budget=body.page_budget, note=body.note, username=admin.username)
    except SourceError as exc:
        raise HTTPException(422, str(exc)) from exc
    db.flush()
    db.refresh(s)
    return _source_out(db, s, detail=True)


@router.post("/sources/career-page")
def career_page_create(body: CareerSourceIn, db: Db, admin: Admin) -> dict:
    """Öffentliche Karriereseite eines Arbeitgebers als eigenständige Quelle vormerken (Freigabe gesondert)."""
    import re

    from ..crawl.netguard import ForbiddenTarget, check_url

    if db.execute(select(Source.id).where(Source.key == body.key)).first():
        raise HTTPException(409, "Schlüssel bereits vergeben")
    try:
        check_url(body.sitemap_url, [body.domain])
        re.compile(body.url_pattern)
        if body.id_pattern:
            re.compile(body.id_pattern)
    except ForbiddenTarget as exc:
        raise HTTPException(422, f"Sitemap-URL nicht zulässig: {exc}") from exc
    except re.error as exc:
        raise HTTPException(422, f"Ungültiger regulärer Ausdruck: {exc}") from exc
    s = Source(key=body.key, name=body.name, domain=body.domain, entry_url=f"https://{body.domain}/", segment="Arbeitgeber-Karriereseite", is_career_page=True,
               access_method="sitemap_jsonld", adapter_key="career_page", adapter_version=ADAPTERS["career_page"].version, allowed_domains=[body.domain],
               terms_url=body.terms_url, robots_url=f"https://{body.domain}/robots.txt", legal_notes=body.legal_notes, config_status="candidate",
               status_reason="Vorgemerkt. Vor der Freigabe robots.txt und Nutzungsbedingungen dieser Domain prüfen.", request_interval_seconds=5,
               max_pages_per_run=20, max_details_per_run=200)
    db.add(s)
    db.flush()
    db.add(SearchScope(source_id=s.id, key="alle", version=1, name="Alle Stellen laut Sitemap", mode="full", is_active=True,
                       params={"sitemap_urls": [body.sitemap_url], "url_pattern": body.url_pattern, "id_pattern": body.id_pattern}))
    audit(db, admin, "career_page_create", source=body.key, domain=body.domain)
    db.flush()
    db.refresh(s)
    return _source_out(db, s, detail=True)


@router.post("/sources/{source_id}/runs")
def run_start(source_id: int, body: RunIn, db: Db, admin: Admin) -> dict:
    """Manueller Lauf oder begrenzter Testlauf. Je Suchbereich und Tag gibt es nur einen logischen Lauf."""
    s = _get_source(db, source_id)
    if not s.adapter_key:
        raise HTTPException(422, "Für diese Quelle ist kein Adapter implementiert.")
    if s.config_status != "active" and not (body.test and s.config_status == "candidate"):
        raise HTTPException(422, f"Quelle ist nicht freigegeben (Status: {s.config_status}). Testläufe sind nur für vorgemerkte Quellen möglich.")
    if not get_settings().crawler_contact.strip():
        raise HTTPException(422, "WF_CRAWLER_CONTACT ist nicht gesetzt – ohne Kontaktangabe werden keine Scans gestartet.")
    scopes = [sc for sc in s.scopes if sc.is_active and (body.scope_key is None or sc.key == body.scope_key)]
    if not scopes:
        raise HTTPException(404, "Kein aktiver Suchbereich gefunden")
    started = []
    for sc in scopes:
        run, created = create_run(db, sc, local_today(), "manual", page_limit=body.page_limit or (2 if body.test else None), is_test=body.test)
        if created:
            enqueue_run(db, run, priority=50)
        started.append({"run_id": run.id, "scope": sc.key, "created": created, "status": run.status,
                        "note": None if created else "Für heute existiert bereits ein Lauf dieses Suchbereichs (Wiederholung über „Wiederholen“)."})
    audit(db, admin, "run_start", source=s.key, test=body.test, runs=[r["run_id"] for r in started])
    return {"runs": started}


def _run_out(r: ScanRun) -> dict[str, Any]:
    return {c: getattr(r, c) for c in (
        "id", "source_id", "scope_id", "scope_key", "scope_version", "logical_date", "trigger", "mode", "is_test", "is_baseline", "page_limit", "parser_version",
        "classifier_version", "status", "status_detail", "control", "list_complete", "detail_complete", "attempts", "created_at", "started_at", "finished_at",
        "window_start", "window_end", "pages_fetched", "requests_made", "partitions_total", "partitions_done", "reported_total", "ids_found", "postings_extracted",
        "postings_new", "postings_changed", "details_fetched", "details_pending", "error_count", "coverage")}


@router.get("/runs")
def runs(db: Db, user: CurrentUser, source_id: int | None = None, limit: int = Query(50, ge=1, le=500), include_tests: bool = True) -> list[dict]:
    q = select(ScanRun).order_by(ScanRun.id.desc()).limit(limit)
    if source_id is not None:
        q = q.where(ScanRun.source_id == source_id)
    if not include_tests:
        q = q.where(ScanRun.is_test.is_(False))
    names = dict(db.execute(select(Source.id, Source.name)).all())
    return [dict(_run_out(r), source_name=names.get(r.source_id)) for r in db.execute(q).scalars().all()]


@router.get("/runs/{run_id}")
def run_detail(run_id: int, db: Db, user: CurrentUser) -> dict:
    r = db.get(ScanRun, run_id)
    if r is None:
        raise HTTPException(404, "Lauf nicht gefunden")
    tasks = db.execute(select(ScanTask).where(ScanTask.run_id == run_id).order_by(ScanTask.id)).scalars().all()
    errors = db.execute(select(ScanError).where(ScanError.run_id == run_id).order_by(ScanError.id.desc()).limit(200)).scalars().all()
    return dict(_run_out(r), source_name=r.source.name,
                tasks=[{"id": t.id, "kind": t.kind, "partition_key": t.partition_key, "status": t.status, "status_detail": t.status_detail, "pages_fetched": t.pages_fetched,
                        "ids_found": t.ids_found, "reported_total": t.reported_total, "started_at": t.started_at, "finished_at": t.finished_at} for t in tasks],
                errors=[{"at": e.at, "kind": e.kind, "url": e.url, "message": e.message} for e in errors])


@router.post("/runs/{run_id}/{action}")
def run_control(run_id: int, action: str, db: Db, admin: Admin) -> dict:
    r = db.get(ScanRun, run_id)
    if r is None:
        raise HTTPException(404, "Lauf nicht gefunden")
    try:
        request_control(db, r, action)
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc
    if r.status == "queued":
        enqueue_run(db, r, priority=50)
    audit(db, admin, f"run_{action}", run_id=run_id)
    return _run_out(r)


# --- Zusammenführungen -----------------------------------------------------------------------------
@router.get("/merges/candidates")
def merge_candidates(db: Db, user: CurrentUser, state: str = "open", limit: int = Query(100, ge=1, le=500)) -> list[dict]:
    rows = db.execute(sql(
        "SELECT c.id, c.reason, c.score, c.rule_version, c.state, c.created_at, a.id AS a_id, a.merged_posting_id AS a_merged, va.title AS a_title, va.employer_name AS a_employer, "
        "sa.name AS a_source, b.id AS b_id, b.merged_posting_id AS b_merged, vb.title AS b_title, vb.employer_name AS b_employer, sb.name AS b_source "
        "FROM merge_candidate c JOIN source_posting a ON a.id = c.a_source_posting_id JOIN source_posting b ON b.id = c.b_source_posting_id "
        "LEFT JOIN posting_version va ON va.id = a.current_version_id LEFT JOIN posting_version vb ON vb.id = b.current_version_id "
        "JOIN source sa ON sa.id = a.source_id JOIN source sb ON sb.id = b.source_id WHERE c.state = :st ORDER BY c.score DESC, c.id DESC LIMIT :lim"),
        {"st": state, "lim": limit}).mappings().all()
    return [dict(r, score=float(r["score"])) for r in rows]


@router.post("/merges/candidates/{cand_id}/{decision}")
def merge_decide(cand_id: int, decision: str, db: Db, admin: Admin) -> dict:
    from datetime import UTC, datetime

    c = db.get(MergeCandidate, cand_id)
    if c is None or decision not in ("merge", "reject"):
        raise HTTPException(404, "Kandidat nicht gefunden oder Entscheidung ungültig")
    if decision == "merge":
        a, b = db.get(SourcePosting, c.a_source_posting_id), db.get(SourcePosting, c.b_source_posting_id)
        if a is None or b is None or a.merged_posting_id is None or b.merged_posting_id is None:
            raise HTTPException(422, "Anzeigen sind (noch) nicht zusammenführbar")
        dedup.merge_manual(db, b.id, a.merged_posting_id, admin.username)
        c.state = "merged"
    else:
        from sqlalchemy.dialects.postgresql import insert as pg_insert

        from ..models import MergeBlock

        db.execute(pg_insert(MergeBlock).values(a_source_posting_id=c.a_source_posting_id, b_source_posting_id=c.b_source_posting_id, created_by=admin.username).on_conflict_do_nothing())
        c.state = "rejected"
    c.decided_at, c.decided_by = datetime.now(UTC), admin.username
    audit(db, admin, f"merge_{decision}", candidate=cand_id)
    return {"id": c.id, "state": c.state}


@router.post("/merges/split/{source_posting_id}")
def merge_split(source_posting_id: int, db: Db, admin: Admin) -> dict:
    try:
        new_id = dedup.split_member(db, source_posting_id, admin.username)
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc
    audit(db, admin, "merge_split", source_posting_id=source_posting_id, new_merged_id=new_id)
    return {"merged_posting_id": new_id}


# --- Betrieb ---------------------------------------------------------------------------------------
@router.get("/system/status")
def system_status(db: Db, user: CurrentUser) -> dict:
    s = get_settings()
    jobs = db.execute(sql("SELECT status, count(*) FROM job GROUP BY 1")).all()
    recent = db.execute(sql("SELECT id, kind, status, attempts, created_at, started_at, finished_at, last_error, result FROM job ORDER BY id DESC LIMIT 25")).mappings().all()
    counts = db.execute(sql(
        "SELECT (SELECT count(*) FROM source_posting WHERE NOT is_synthetic) AS source_postings, (SELECT count(*) FROM merged_posting WHERE NOT is_synthetic) AS merged_postings, "
        "(SELECT count(*) FROM posting_version) AS versions, (SELECT count(*) FROM observation) AS observations, (SELECT count(*) FROM region WHERE level='district' AND is_current) AS districts, "
        "(SELECT count(*) FROM geo_place) AS places, (SELECT count(*) FROM kldb_class) AS kldb_classes, (SELECT count(*) FROM occupation_title) AS occupation_titles, "
        "(SELECT count(*) FROM merged_posting WHERE is_synthetic) AS synthetic_postings")).mappings().one()
    return {"version": VERSION, "env": s.env, "timezone": s.timezone, "scan_time": s.scan_time, "jobs": {k: int(v) for k, v in jobs}, "recent_jobs": [dict(r) for r in recent],
            "counts": dict(counts), "warnings": [dict(r) for r in db.execute(sql("SELECT id, kind, message, created_at FROM ops_warning WHERE resolved_at IS NULL ORDER BY created_at DESC")).mappings().all()],
            "settings": {"missing_scans_threshold": s.missing_scans_threshold, "stale_after_days": s.stale_after_days, "detail_recheck_days": s.detail_recheck_days,
                         "technical_log_retention_days": s.technical_log_retention_days, "small_count_threshold": s.small_count_threshold}}


@router.post("/system/warnings/{warning_id}/resolve")
def warning_resolve(warning_id: int, db: Db, admin: Admin) -> dict:
    db.execute(sql("UPDATE ops_warning SET resolved_at = now() WHERE id = :i AND resolved_at IS NULL"), {"i": warning_id})
    return {"ok": True}


@router.post("/system/jobs/{kind}")
def job_trigger(kind: str, db: Db, admin: Admin, dataset: str | None = None) -> dict:
    if kind not in ("aggregate", "stats_check", "maintenance", "geo_rematch"):
        raise HTTPException(422, "unbekannte Jobart")
    payload: dict[str, Any] = {"datasets": [dataset]} if dataset else {}
    job = queue.enqueue(db, kind, payload, dedupe_key=f"manual:{kind}:{dataset or ''}", lock_key=kind, priority=60, max_attempts=1)
    audit(db, admin, "job_trigger", kind=kind, dataset=dataset)
    return {"queued": job is not None, "job_id": job.id if job else None}


@router.post("/stats/upload")
def stats_upload(db: Db, admin: Admin, dataset: str = Form(...), file: UploadFile = File(...)) -> dict:
    """Validierter manueller Dateiimport als Ausweichweg (automatische Importe bleiben das Ziel)."""
    from ..stats.runner import ImportProblem, import_file

    suffix = Path(file.filename or "upload").suffix.lower()
    if suffix not in (".xlsx", ".csv", ".zip", ".gpkg"):
        raise HTTPException(422, "Nur .xlsx, .csv, .zip oder .gpkg")
    with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp:
        shutil.copyfileobj(file.file, tmp)
        path = Path(tmp.name)
    try:
        result = import_file(dataset, path, method="manual", original_name=Path(file.filename or "").name)
    except ImportProblem as exc:
        raise HTTPException(422, str(exc)) from exc
    finally:
        path.unlink(missing_ok=True)
    audit(db, admin, "stats_upload", dataset=dataset, file=file.filename, result=result)
    return result


# --- Benutzer --------------------------------------------------------------------------------------
class UserIn(BaseModel):
    username: str = Field(pattern=r"^[A-Za-z0-9._\-@]{3,80}$")
    role: str = "reader"
    password: str | None = None


@router.get("/users")
def users(db: Db, admin: Admin) -> list[dict]:
    return [{"id": u.id, "username": u.username, "role": u.role, "is_active": u.is_active, "created_at": u.created_at, "last_login_at": u.last_login_at}
            for u in db.execute(select(User).order_by(User.username)).scalars().all()]


@router.post("/users")
def user_create(body: UserIn, db: Db, admin: Admin) -> dict:
    if body.role not in ("admin", "reader"):
        raise HTTPException(422, "role muss admin oder reader sein")
    if db.execute(select(User.id).where(User.username == body.username)).first():
        raise HTTPException(409, "Benutzername bereits vergeben")
    password = body.password or generate_password()
    try:
        user = User(username=body.username, role=body.role, password_hash=hash_password(password))
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc
    db.add(user)
    db.flush()
    audit(db, admin, "user_create", username=body.username, role=body.role)
    return {"id": user.id, "username": user.username, "role": user.role, "generated_password": None if body.password else password,
            "note": "Das generierte Passwort wird nur dieses eine Mal angezeigt."}


@router.patch("/users/{user_id}")
def user_update(user_id: int, db: Db, admin: Admin, is_active: bool | None = None, role: str | None = None, reset_password: bool = False) -> dict:
    u = db.get(User, user_id)
    if u is None:
        raise HTTPException(404, "Benutzer nicht gefunden")
    if u.id == admin.id and (is_active is False or (role and role != "admin")):
        raise HTTPException(422, "Das eigene Administratorkonto kann nicht deaktiviert oder herabgestuft werden.")
    out: dict[str, Any] = {"id": u.id}
    if is_active is not None:
        u.is_active = is_active
    if role in ("admin", "reader"):
        u.role = role
    if reset_password:
        pw = generate_password()
        u.password_hash = hash_password(pw)
        db.execute(sql("DELETE FROM user_session WHERE user_id = :u"), {"u": u.id})
        out["generated_password"] = pw
    audit(db, admin, "user_update", username=u.username, is_active=is_active, role=role, reset_password=reset_password)
    return dict(out, username=u.username, role=u.role, is_active=u.is_active)
