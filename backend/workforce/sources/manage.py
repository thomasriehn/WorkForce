"""Verwaltung des Quellenregisters: Freigabe mit Vermerk, Deaktivierung, versionierte Suchbereiche, Gesundheitszustand."""
from __future__ import annotations

from datetime import UTC, date, datetime
from typing import Any

from sqlalchemy import select, text as sql
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import Session

from ..config import get_settings
from ..models import AuditLog, ScanRun, SearchScope, Source, TimelineNote
from .adapters import ADAPTERS


class SourceError(ValueError):
    pass


def activate(db: Session, source: Source, *, basis: str, permission_reference: str | None, username: str) -> None:
    """Gibt eine Quelle frei. Der Vermerk dokumentiert, worauf der Betreiber die Freigabe stützt."""
    if not source.adapter_key or source.adapter_key not in ADAPTERS:
        raise SourceError("Für diese Quelle ist kein Adapter implementiert – sie kann nur vorgemerkt bleiben.")
    if not get_settings().crawler_contact.strip():
        raise SourceError("WF_CRAWLER_CONTACT ist nicht gesetzt. Ohne Kontaktangabe im User-Agent wird keine Quelle freigegeben.")
    if len((basis or "").strip()) < 20:
        raise SourceError("Bitte einen aussagekräftigen Freigabevermerk angeben (mindestens 20 Zeichen): Was wurde geprüft, worauf stützt sich die Freigabe?")
    if source.config_status == "permission_required" and len((permission_reference or "").strip()) < 10:
        raise SourceError("Diese Quelle erfordert eine Erlaubnis des Betreibers. Bitte den Nachweis angeben (z. B. Datum und Absender der schriftlichen Zustimmung).")
    previous = source.config_status
    stamp = f"{datetime.now(UTC):%Y-%m-%d %H:%M} UTC"
    note = f"Freigabe am {stamp} durch {username}: {basis.strip()}"
    if permission_reference:
        note += f" | Erlaubnisnachweis: {permission_reference.strip()}"
    source.config_status = "active"
    source.status_reason = note
    source.legal_checked_on = date.today()
    db.add(AuditLog(username=username, action="source_activate", details={"source": source.key, "previous": previous, "basis": basis, "permission": permission_reference}))
    db.execute(pg_insert(TimelineNote).values(note_date=datetime.now(get_settings().tz).date(), kind="source_added", source_id=source.id,
                                              message=f"Quelle freigegeben: {source.name}").on_conflict_do_nothing())


def deactivate(db: Session, source: Source, *, reason: str, username: str, status: str = "disabled") -> None:
    if status not in ("disabled", "permission_required", "candidate"):
        raise SourceError("ungültiger Zielstatus")
    if len((reason or "").strip()) < 5:
        raise SourceError("Bitte einen konkreten Deaktivierungsgrund angeben.")
    previous = source.config_status
    source.config_status = status
    source.status_reason = f"{reason.strip()} (gesetzt am {datetime.now(UTC):%Y-%m-%d} durch {username})"
    db.add(AuditLog(username=username, action="source_deactivate", details={"source": source.key, "previous": previous, "status": status, "reason": reason}))
    db.execute(pg_insert(TimelineNote).values(note_date=datetime.now(get_settings().tz).date(), kind="source_removed", source_id=source.id,
                                              message=f"Quelle deaktiviert: {source.name} – {reason.strip()}").on_conflict_do_nothing())


def new_scope_version(db: Session, source: Source, key: str, *, name: str, params: dict[str, Any], mode: str, page_budget: int | None,
                      note: str | None, username: str) -> SearchScope:
    """Geänderter Suchbereich = neue Version. Der erste Lauf der neuen Version ist eine Bestandsaufnahme."""
    if mode not in ("full", "new_only"):
        raise SourceError("mode muss full oder new_only sein")
    current = db.execute(select(SearchScope).where(SearchScope.source_id == source.id, SearchScope.key == key, SearchScope.is_active)).scalar_one_or_none()
    last_version = db.execute(sql("SELECT coalesce(max(version), 0) FROM search_scope WHERE source_id = :s AND key = :k"), {"s": source.id, "k": key}).scalar_one()
    if current is not None:
        if current.params == params and current.mode == mode and current.page_budget == page_budget:
            current.name, current.note = name, note
            return current
        current.is_active = False
        current.retired_at = datetime.now(UTC)
        db.flush()
    scope = SearchScope(source_id=source.id, key=key, version=int(last_version) + 1, name=name, params=params, mode=mode, page_budget=page_budget, note=note, is_active=True)
    db.add(scope)
    db.flush()
    db.add(AuditLog(username=username, action="scope_version", details={"source": source.key, "scope": key, "version": scope.version}))
    if current is not None:
        db.execute(pg_insert(TimelineNote).values(note_date=datetime.now(get_settings().tz).date(), kind="scope_changed", source_id=source.id,
                                                  message=f"Suchbereich „{key}“ von {source.name} geändert (Version {scope.version}) – Zeitvergleiche über diesen Wechsel sind eingeschränkt").on_conflict_do_nothing())
    return scope


def source_health(db: Session, source: Source) -> dict[str, Any]:
    """Technischer Gesundheitszustand – getrennt vom Konfigurationsstatus."""
    last = db.execute(select(ScanRun).where(ScanRun.source_id == source.id, ScanRun.is_test.is_(False)).order_by(ScanRun.logical_date.desc(), ScanRun.id.desc()).limit(1)).scalar_one_or_none()
    last_ok = db.execute(select(ScanRun).where(ScanRun.source_id == source.id, ScanRun.is_test.is_(False), ScanRun.status == "complete").order_by(ScanRun.logical_date.desc(), ScanRun.id.desc()).limit(1)).scalar_one_or_none()
    counts = db.execute(sql(
        "SELECT count(*) FILTER (WHERE status IN ('active','not_reobserved')) AS stock, count(*) AS total, "
        "count(*) FILTER (WHERE detail_due AND status IN ('active','not_reobserved')) AS details_pending, max(last_seen_at) AS last_seen "
        "FROM source_posting WHERE source_id = :s AND NOT is_synthetic"), {"s": source.id}).mappings().one()
    if source.config_status != "active":
        health = "inactive"
    elif last is None:
        health = "never_run"
    elif last.status == "complete":
        health = "ok"
    elif last.status in ("queued", "running", "paused"):
        health = "running"
    elif last.status == "blocked":
        health = "blocked"
    elif last.status == "partial":
        health = "degraded"
    else:
        health = "failing"
    return {
        "health": health,
        "last_run": {"id": last.id, "status": last.status, "status_detail": last.status_detail, "logical_date": last.logical_date, "finished_at": last.finished_at,
                     "list_complete": last.list_complete, "detail_complete": last.detail_complete} if last else None,
        "last_complete_run": {"id": last_ok.id, "logical_date": last_ok.logical_date, "finished_at": last_ok.finished_at} if last_ok else None,
        "data_as_of": counts["last_seen"], "stock": int(counts["stock"]), "postings_total": int(counts["total"]), "details_pending": int(counts["details_pending"]),
    }
