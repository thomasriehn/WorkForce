"""Statusableitung für Quellanzeigen und zusammengeführte Anzeigen.

Zustände: ``active`` (aktiv beobachtet), ``not_reobserved`` (nicht erneut beobachtet),
``presumed_removed`` (vermutlich entfernt – eine Ableitung), ``ended`` (ausdrücklich als beendet
beobachtet bzw. von der Quelle angekündigtes Veröffentlichungsende erreicht), ``stale`` (unbekannt/veraltet).

Nur **vollständige, vergleichbare** Scans desselben Suchbereichs (gleiche Suchbereichsversion, Modus
``full``) zählen als verpasste Sichtung. CAPTCHA, HTTP 403, Timeout, Parserfehler, Seitenlimits,
Suchbereichswechsel und Läufe, die nur neue Anzeigen melden, sind keine Schließungsnachweise.
Eine entfernte Anzeige belegt nicht, dass die Stelle besetzt wurde.
"""
from __future__ import annotations

import logging
from datetime import UTC, date, datetime, timedelta

from sqlalchemy import select, text as sql
from sqlalchemy.orm import Session

from ..config import Settings, get_settings
from ..models import IN_STOCK, ActivityPeriod, PostingEvent, PostingVersion, ScanRun, SourcePosting
from . import dedup

log = logging.getLogger(__name__)

_DESIRED_SQL = """
WITH m AS (
    SELECT ps.source_posting_id, min(ps.missed_complete_runs) AS misses
    FROM posting_scope ps JOIN search_scope sc ON sc.id = ps.scope_id
    WHERE sc.is_active AND sc.mode = 'full'
    GROUP BY 1
)
SELECT id, cur, want FROM (
    SELECT sp.id, sp.status AS cur,
        CASE
            WHEN pv.valid_through IS NOT NULL AND pv.valid_through < :today AND sp.last_seen_date <= pv.valid_through
                 AND (m.misses IS NULL OR m.misses >= 1) THEN 'ended'
            WHEN sp.gone_confirmations >= :gone THEN 'presumed_removed'
            WHEN m.misses >= :threshold THEN 'presumed_removed'
            WHEN m.misses >= 1 THEN 'not_reobserved'
            WHEN sp.last_seen_date < :stale_before
                 AND NOT (m.misses IS NULL AND pv.valid_through IS NOT NULL AND pv.valid_through >= :today) THEN 'stale'
            ELSE 'active'
        END AS want
    FROM source_posting sp
    LEFT JOIN posting_version pv ON pv.id = sp.current_version_id
    LEFT JOIN m ON m.source_posting_id = sp.id
    WHERE sp.source_id = :source_id AND sp.status IN ('active', 'not_reobserved')
) t WHERE cur <> want
"""


def leave_stock(db: Session, sp: SourcePosting, status: str, reason: str, logical_date: date, *, end_date: date, run_id: int | None = None) -> None:
    """Quellanzeige verlässt den beobachteten Bestand (Zeitraum schließen, Ereignis auf Ebene der Zusammenführung)."""
    now = datetime.now(UTC)
    sp.status, sp.status_reason, sp.status_changed_at = status, reason, now
    period = db.execute(select(ActivityPeriod).where(ActivityPeriod.source_posting_id == sp.id, ActivityPeriod.end_date.is_(None))).scalar_one_or_none()
    if period is not None:
        # Am Tag der Feststellung zählt die Anzeige nicht mehr zum Bestand: so stimmen der aktuelle Bestand
        # (Status) und der Stichtagsbestand von heute (Zeiträume) stets überein.
        period.end_date = min(end_date, logical_date - timedelta(days=1))
        period.end_reason = status
    db.flush()
    if sp.merged_posting_id is None:
        return
    still = db.execute(
        select(SourcePosting.id).where(SourcePosting.merged_posting_id == sp.merged_posting_id, SourcePosting.status.in_(IN_STOCK)).limit(1)
    ).first()
    dedup.refresh_merged(db, sp.merged_posting_id)
    if still is None:
        db.add(PostingEvent(
            event_date=logical_date, effective_date=end_date + timedelta(days=1), event_type="left_stock",
            merged_posting_id=sp.merged_posting_id, source_posting_id=sp.id, run_id=run_id,
            details={"status": status, "reason": reason},
        ))


def apply_run_outcome(db: Session, run: ScanRun, settings: Settings | None = None) -> dict[str, int]:
    """Wertet einen beendeten Lauf aus. Verpasste Sichtungen zählen nur bei vollständiger Listenentdeckung."""
    settings = settings or get_settings()
    counted = 0
    if not run.is_test and not run.status_applied:
        if run.status == "complete" and run.list_complete and run.mode == "full":
            counted = db.execute(sql(
                "UPDATE posting_scope SET missed_complete_runs = missed_complete_runs + 1 "
                "WHERE scope_id = :scope AND last_seen_date < :d AND (last_seen_run_id IS NULL OR last_seen_run_id <> :run)"),
                {"scope": run.scope_id, "d": run.logical_date, "run": run.id}).rowcount or 0
        run.status_applied = True
        db.flush()
    changed = recompute_statuses(db, run.source_id, run.logical_date, settings, run_id=run.id)
    return {"missed_counted": counted, "status_changes": changed}


def recompute_statuses(db: Session, source_id: int, today: date, settings: Settings | None = None, run_id: int | None = None) -> int:
    settings = settings or get_settings()
    rows = db.execute(sql(_DESIRED_SQL), {
        "today": today, "source_id": source_id, "threshold": settings.missing_scans_threshold,
        "gone": settings.gone_confirmations, "stale_before": today - timedelta(days=settings.stale_after_days),
    }).all()
    n = 0
    for sp_id, _cur, want in rows:
        sp = db.get(SourcePosting, sp_id)
        if sp is None:
            continue
        n += 1
        if want in IN_STOCK:
            sp.status, sp.status_changed_at = want, datetime.now(UTC)
            sp.status_reason = ("in vollständigem Scan des Suchbereichs nicht erneut beobachtet" if want == "not_reobserved" else "beobachtet")
            if sp.merged_posting_id:
                dedup.refresh_merged(db, sp.merged_posting_id)
            continue
        v = db.get(PostingVersion, sp.current_version_id) if sp.current_version_id else None
        end = sp.last_seen_date
        if want == "ended":
            reason = f"Veröffentlichungsende laut Quelle ({v.valid_through:%d.%m.%Y}) erreicht" if v and v.valid_through else "beendet laut Quelle"
            if v and v.valid_through and v.valid_through > end:
                end = v.valid_through
        elif want == "presumed_removed":
            if sp.gone_confirmations >= settings.gone_confirmations:
                reason = f"Detailseite an {sp.gone_confirmations} Tagen nicht verfügbar (HTTP 404/410)"
            else:
                reason = (f"in {settings.missing_scans_threshold} vollständigen vergleichbaren Scans des Suchbereichs nicht mehr beobachtet "
                          "(Ableitung, kein Nachweis einer Besetzung)")
        else:
            reason = f"seit über {settings.stale_after_days} Tagen kein vergleichbarer Scan – Zustand unbekannt"
        leave_stock(db, sp, want, reason, today, end_date=end, run_id=run_id)
    db.flush()
    return n
