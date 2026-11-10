"""Lauf-Engine: führt einen logischen Scanlauf aus (Entdeckung → Detailprüfung → Abschluss).

* Ein logischer Tageslauf je Suchbereich und lokalem Datum (eindeutiger Index); Wiederholungen setzen
  an Checkpoints fort und sind idempotent.
* Seitenlimits, Trefferobergrenzen, wiederholte/leere Seiten, Parserfehler ⇒ ``partial``.
* Sperrsignale (HTTP 403/429, CAPTCHA, robots.txt) ⇒ ``blocked``; kein Umgehungsversuch.
* Nur ``complete`` + vollständige Listenentdeckung zählt als verpasste Sichtung (siehe ``status``).
"""
from __future__ import annotations

import logging
from collections.abc import Callable
from datetime import UTC, date, datetime, timedelta
from typing import Any

import httpx
from sqlalchemy import and_, func, or_, select, text as sql
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import Session

from ..config import CLASSIFIER_VERSION, Settings, get_settings
from ..crawl.fetcher import BlockedError, FetchError, Fetcher, RobotsDisallowed, RobotsStore
from ..db import get_engine, session_scope
from ..models import (
    IN_STOCK,
    RUN_FINAL,
    FetchCache,
    OpsWarning,
    RobotsCache,
    ScanError,
    ScanRun,
    ScanTask,
    SearchScope,
    Source,
    SourcePosting,
    TimelineNote,
)
from ..sources.adapters import get_adapter
from ..sources.base import ListItem, ParseError, SourceAdapter
from .ingest import Ingestor
from .status import apply_run_outcome

log = logging.getLogger(__name__)
MAX_CONSECUTIVE_DETAIL_FAILURES = 5


class RunRefused(Exception):
    """Lauf darf nicht starten (Quelle nicht freigegeben, Kontaktangabe fehlt, …)."""


def local_today(settings: Settings | None = None) -> date:
    settings = settings or get_settings()
    return datetime.now(settings.tz).date()


def create_run(db: Session, scope: SearchScope, logical_date: date, trigger: str, *, page_limit: int | None = None, is_test: bool = False) -> tuple[ScanRun, bool]:
    """Legt den logischen Lauf an oder liefert den bestehenden (idempotent je Suchbereich und Datum)."""
    if not is_test:
        existing = db.execute(select(ScanRun).where(ScanRun.scope_id == scope.id, ScanRun.logical_date == logical_date, ScanRun.is_test.is_(False))).scalar_one_or_none()
        if existing is not None:
            return existing, False
    has_complete = db.execute(select(ScanRun.id).where(ScanRun.scope_id == scope.id, ScanRun.is_test.is_(False), ScanRun.status == "complete").limit(1)).first()
    run = ScanRun(
        source_id=scope.source_id, scope_id=scope.id, scope_key=scope.key, scope_version=scope.version, logical_date=logical_date,
        trigger="test" if is_test else trigger, mode=scope.mode, is_test=is_test, is_baseline=has_complete is None,
        page_limit=page_limit, status="queued",
    )
    db.add(run)
    db.flush()
    return run, True


def _db_robots_store() -> RobotsStore:
    def load(host: str) -> tuple[datetime, int | None, str | None] | None:
        with session_scope() as s:
            row = s.get(RobotsCache, host)
            return (row.fetched_at, row.status_code, row.body) if row else None

    def save(host: str, at: datetime, status: int | None, body: str | None) -> None:
        with session_scope() as s:
            s.execute(pg_insert(RobotsCache).values(host=host, fetched_at=at, status_code=status, body=body).on_conflict_do_update(
                index_elements=["host"], set_={"fetched_at": at, "status_code": status, "body": body}))

    return RobotsStore(load, save)


def _cache_get(key: str) -> tuple[str | None, str | None] | None:
    with session_scope() as s:
        row = s.get(FetchCache, key)
        return (row.etag, row.last_modified) if row else None


def _cache_put(key: str, url: str, etag: str | None, last_modified: str | None, status: int) -> None:
    with session_scope() as s:
        now = datetime.now(UTC)
        s.execute(pg_insert(FetchCache).values(url_hash=key, url=url, etag=etag, last_modified=last_modified, fetched_at=now, status_code=status)
                  .on_conflict_do_update(index_elements=["url_hash"], set_={"etag": etag, "last_modified": last_modified, "fetched_at": now, "status_code": status}))


def default_fetcher(source: Source, adapter: SourceAdapter, settings: Settings) -> Fetcher:
    domains = tuple(source.allowed_domains or adapter.default_domains)
    return Fetcher(domains, interval_seconds=float(source.request_interval_seconds), settings=settings,
                   robots_store=_db_robots_store(), cache_get=_cache_get, cache_put=_cache_put)


def _error(db: Session, run: ScanRun, task: ScanTask | None, kind: str, url: str | None, message: str) -> None:
    db.add(ScanError(run_id=run.id, task_id=task.id if task else None, kind=kind[:32], url=url, message=message[:2000]))
    run.error_count += 1


def _error_kind(exc: Exception) -> str:
    if isinstance(exc, BlockedError):
        if exc.status in (401, 403, 429):
            return f"http_{exc.status}"
        return "captcha" if "CAPTCHA" in str(exc) or "Bot-Schutz" in str(exc) else "blocked"
    if isinstance(exc, RobotsDisallowed):
        return "robots"
    if isinstance(exc, ParseError):
        return "parse"
    if isinstance(exc, FetchError):
        return exc.kind
    if isinstance(exc, httpx.TimeoutException):
        return "timeout"
    return "error"


class RunEngine:
    def __init__(self, db: Session, run: ScanRun, *, settings: Settings | None = None,
                 fetcher_factory: Callable[[Source, SourceAdapter, Settings], Fetcher] | None = None,
                 heartbeat: Callable[[], None] | None = None, adapter: SourceAdapter | None = None):
        self.db = db
        self.run = run
        self.settings = settings or get_settings()
        self.source: Source = run.source
        self.scope: SearchScope = run.scope
        if not self.source.adapter_key and adapter is None:
            raise RunRefused("für diese Quelle ist kein Adapter implementiert")
        self.adapter = adapter or get_adapter(self.source.adapter_key or "")
        self.fetcher = (fetcher_factory or default_fetcher)(self.source, self.adapter, self.settings)
        self.heartbeat = heartbeat or (lambda: None)
        self.ing = Ingestor(db, self.source, self.adapter, run, self.settings)
        self.blocked: str | None = None
        self.stop_reason: str | None = None
        self.signals: list[dict[str, Any]] = []

    # --- Vorbedingungen ---------------------------------------------------------------------------
    def check_allowed(self) -> None:
        if not self.settings.crawler_contact.strip() and not self.settings.is_test:
            raise RunRefused("WF_CRAWLER_CONTACT ist nicht gesetzt – ohne Kontaktangabe im User-Agent werden keine Scans gestartet")
        status = self.source.config_status
        if status == "active":
            return
        if status == "candidate" and self.run.is_test:
            return  # begrenzter Testlauf zur technischen Prüfung vor der Freigabe
        raise RunRefused(f"Quelle ist nicht freigegeben (Konfigurationsstatus: {status}). Grund: {self.source.status_reason or '–'}")

    def _control(self) -> str | None:
        self.db.refresh(self.run, attribute_names=["control"])
        return self.run.control

    def _page_budget(self) -> int:
        limits = [self.scope.page_budget or self.source.max_pages_per_run]
        if self.run.page_limit:
            limits.append(self.run.page_limit)
        return min(limits)

    # --- Listenentdeckung -------------------------------------------------------------------------
    def _list_phase(self) -> None:
        run, db = self.run, self.db
        params = dict(self.scope.params or {})
        partitions = self.adapter.partitions(params)
        run.partitions_total = len(partitions)
        budget = self._page_budget()
        for part in partitions:
            task = db.execute(select(ScanTask).where(ScanTask.run_id == run.id, ScanTask.kind == "list", ScanTask.partition_key == part.key)).scalar_one_or_none()
            if task is None:
                task = ScanTask(run_id=run.id, kind="list", partition_key=part.key, status="pending")
                db.add(task)
                db.flush()
            if task.status == "done":
                if task.checkpoint and task.checkpoint.get("_signals"):
                    self.signals.append(task.checkpoint["_signals"])
                continue
            task.status, task.started_at = "running", task.started_at or datetime.now(UTC)
            checkpoint = {k: v for k, v in (task.checkpoint or {}).items() if not k.startswith("_")} or None
            db.commit()
            seen_ids: set[str] = set()
            prev_ids: set[str] = set()
            try:
                finished = False
                for page in self.adapter.list_pages(self.fetcher, params, part, checkpoint):
                    self.heartbeat()
                    ids = {i.source_key for i in page.items}
                    if page.items and (ids == prev_ids or ids <= seen_ids):
                        _error(db, run, task, "repeat", None, "Seite wiederholt bereits gelieferte Anzeigen – Pagination endet nicht sauber")
                        task.status, task.status_detail = "partial", "wiederholte Seite"
                        break
                    if not page.items and not page.is_last:
                        _error(db, run, task, "empty", None, "leere Seite vor dem Ende der Liste")
                        task.status, task.status_detail = "partial", "leere Seite"
                        break
                    for item in page.items:
                        self.ing.observe(item, self.scope.id)
                    seen_ids |= ids
                    prev_ids = ids
                    task.pages_fetched += 1
                    task.ids_found += len(ids)
                    run.pages_fetched += 1
                    if page.reported_total is not None:
                        task.reported_total = page.reported_total
                    if page.signals:
                        self.signals.append(page.signals)
                    cp = dict(page.next_checkpoint or {})
                    if page.signals:
                        cp["_signals"] = page.signals
                    task.checkpoint = cp or None
                    run.requests_made = self.fetcher.requests_made
                    db.commit()
                    if page.capped:
                        _error(db, run, task, "cap", None, f"Trefferobergrenze der Quelle erreicht (gemeldet: {page.reported_total})")
                        task.status, task.status_detail = "partial", "Trefferobergrenze"
                        break
                    if page.is_last:
                        finished = True
                        break
                    ctl = self._control()
                    if ctl in ("pause", "cancel"):
                        self.stop_reason = ctl
                        task.status = "pending"
                        break
                    if run.pages_fetched >= budget:
                        task.status, task.status_detail = "partial", f"Seitenlimit ({budget}) erreicht"
                        self.stop_reason = "page_limit"
                        break
                else:
                    finished = True
                if finished:
                    task.status, task.finished_at = "done", datetime.now(UTC)
                    run.partitions_done += 1
                db.commit()
            except (BlockedError, RobotsDisallowed) as exc:
                db.rollback()
                _error(db, run, task, _error_kind(exc), exc.url, str(exc))
                task.status, task.status_detail = "blocked", str(exc)[:500]
                self.blocked = str(exc)
                db.commit()
            except (FetchError, ParseError, httpx.HTTPError) as exc:
                db.rollback()
                _error(db, run, task, _error_kind(exc), getattr(exc, "url", None), str(exc))
                task.status, task.status_detail = "failed", str(exc)[:500]
                db.commit()
            if self.blocked or self.stop_reason:
                break

    # --- Detailprüfung ------------------------------------------------------------------------------
    def _detail_limit(self) -> int:
        limit = self.source.max_details_per_run
        if self.run.page_limit:
            limit = min(limit, max(3, self.run.page_limit * 5))
        return limit

    def _detail_candidates(self, limit: int) -> list[SourcePosting]:
        recheck_before = datetime.now(UTC) - timedelta(days=self.settings.detail_recheck_days)
        q = (
            select(SourcePosting)
            .where(SourcePosting.source_id == self.source.id,
                   or_(and_(SourcePosting.status.in_(IN_STOCK), or_(SourcePosting.detail_due.is_(True), SourcePosting.last_detail_check_at < recheck_before)),
                       # nicht mehr verfügbare Detailseiten, die die Liste weiterhin nennt: erneut prüfen
                       and_(SourcePosting.detail_due.is_(True), SourcePosting.gone_confirmations > 0)))
            .order_by(SourcePosting.current_version_id.isnot(None), SourcePosting.last_detail_check_at.asc().nulls_first(), SourcePosting.id)
            .limit(limit)
        )
        return list(self.db.execute(q).scalars().all())

    def _detail_phase(self) -> None:
        run, db = self.run, self.db
        if self.adapter.detail_mode == "none":
            run.detail_complete = True
            return
        failures = 0
        for sp in self._detail_candidates(self._detail_limit()):
            self.heartbeat()
            try:
                res = self.fetcher.get(sp.original_url, conditional=sp.current_version_id is not None)
                run.details_fetched += 1
                if res.not_modified:
                    self.ing.detail_unchanged(sp)
                elif res.gone:
                    self.ing.detail_gone(sp, res.status)
                elif res.status != 200:
                    _error(db, run, None, f"http_{res.status}", sp.original_url, "unerwarteter Status der Detailseite")
                elif self.adapter.is_explicitly_ended(res):
                    self.ing.detail_ended(sp, "Ablaufhinweis der Quelle auf der Detailseite")
                else:
                    self.ing.ingest_detail(sp, self.adapter.parse_detail(res, sp.source_key))
                failures = 0
                run.requests_made = self.fetcher.requests_made
                db.commit()
            except (BlockedError, RobotsDisallowed) as exc:
                db.rollback()
                _error(db, run, None, _error_kind(exc), exc.url, str(exc))
                self.blocked = str(exc)
                db.commit()
                break
            except (FetchError, ParseError, httpx.HTTPError) as exc:
                db.rollback()
                _error(db, run, None, _error_kind(exc), sp.original_url, str(exc))
                db.commit()
                failures += 1
                if failures >= MAX_CONSECUTIVE_DETAIL_FAILURES:
                    self.stop_reason = self.stop_reason or "detail_failures"
                    break
            ctl = self._control()
            if ctl in ("pause", "cancel"):
                self.stop_reason = ctl
                break
        pending = db.execute(select(func.count()).select_from(SourcePosting).where(
            SourcePosting.source_id == self.source.id, SourcePosting.status.in_(IN_STOCK), SourcePosting.detail_due.is_(True))).scalar_one()
        run.details_pending = int(pending)
        run.detail_complete = pending == 0

    # --- Ablauf -------------------------------------------------------------------------------------
    def execute(self) -> ScanRun:
        run, db = self.run, self.db
        now = datetime.now(UTC)
        run.status, run.control = "running", None
        run.started_at = run.started_at or now
        run.window_start = run.window_start or now
        run.attempts += 1
        run.parser_version, run.classifier_version = self.adapter.version, CLASSIFIER_VERSION
        stock_before = self._stock()
        db.commit()
        try:
            self._list_phase()
            if not self.blocked and self.stop_reason not in ("pause", "cancel"):
                self._detail_phase()
        finally:
            self.fetcher.close()
        return self._finalize(stock_before)

    def _stock(self) -> int:
        return int(self.db.execute(select(func.count()).select_from(SourcePosting).where(
            SourcePosting.source_id == self.source.id, SourcePosting.status.in_(IN_STOCK))).scalar_one())

    def _finalize(self, stock_before: int) -> ScanRun:
        run, db = self.run, self.db
        tasks = db.execute(select(ScanTask).where(ScanTask.run_id == run.id, ScanTask.kind == "list")).scalars().all()
        all_done = bool(tasks) and all(t.status == "done" for t in tasks)
        previous = db.execute(
            select(ScanRun.coverage).where(ScanRun.scope_id == run.scope_id, ScanRun.is_test.is_(False), ScanRun.id != run.id,
                                           ScanRun.status.in_(("complete", "partial"))).order_by(ScanRun.logical_date.desc(), ScanRun.id.desc()).limit(1)
        ).scalar_one_or_none()
        assessment = self.adapter.assess_coverage(self.signals, (previous or {}).get("signals") if previous else None)
        run.list_complete = all_done and assessment.list_complete
        run.ids_found = sum(t.ids_found for t in tasks)
        totals = [t.reported_total for t in tasks if t.reported_total is not None]
        run.reported_total = sum(totals) if totals else None
        run.postings_extracted += self.ing.stats["extracted"]
        run.postings_new += self.ing.stats["new"]
        run.postings_changed += self.ing.stats["changed"]
        run.requests_made = self.fetcher.requests_made
        if self.stop_reason == "pause":
            run.status, run.status_detail = "paused", "pausiert – Fortsetzung am selben logischen Datum möglich"
            db.commit()
            return run
        if self.stop_reason == "cancel":
            run.status, run.status_detail = "cancelled", "vom Administrator abgebrochen"
        elif self.blocked:
            run.status, run.status_detail = "blocked", self.blocked[:500]
        elif not tasks or all(t.status == "failed" for t in tasks):
            run.status, run.status_detail = "failed", "; ".join(t.status_detail or "" for t in tasks)[:500] or "keine Listenseite verarbeitet"
        elif run.list_complete:
            run.status = "complete"
            run.status_detail = assessment.note if run.detail_complete else f"{assessment.note or 'Liste vollständig'}; Detailanreicherung unvollständig ({run.details_pending} offen)"
        else:
            reasons = [t.status_detail for t in tasks if t.status != "done" and t.status_detail]
            if all_done and not assessment.list_complete:
                reasons.append(assessment.note or "Abdeckung nicht belegbar")
            run.status, run.status_detail = "partial", "; ".join(r for r in reasons if r)[:500] or "Suchbereich nur teilweise abgearbeitet"
        run.window_end = run.finished_at = datetime.now(UTC)
        run.coverage = {
            "signals": assessment.signals or (self.signals[-1] if self.signals else {}), "note": assessment.note,
            "list_complete": run.list_complete, "detail_complete": run.detail_complete, "details_pending": run.details_pending,
            "reported_total": run.reported_total, "ids_found": run.ids_found,
            "tasks": {t.partition_key: {"status": t.status, "pages": t.pages_fetched, "ids": t.ids_found, "detail": t.status_detail} for t in tasks},
            "discovery_mode": self.adapter.discovery_mode,
        }
        db.commit()
        outcome = apply_run_outcome(db, run, self.settings)
        self._notes_and_warnings(stock_before, outcome)
        db.commit()
        log.info("Lauf beendet", extra={"run_id": run.id, "source": self.source.key, "status": run.status, "ids_found": run.ids_found,
                                        "new": run.postings_new, "pages": run.pages_fetched, "errors": run.error_count})
        return run

    def _notes_and_warnings(self, stock_before: int, outcome: dict[str, int]) -> None:
        run, db, s = self.run, self.db, self.settings
        if run.is_test:
            return
        if run.is_baseline and run.status in ("complete", "partial"):
            kind = "scope_changed" if self.scope.version > 1 else "source_added"
            msg = (f"Bestandsaufnahme: {self.source.name}, Suchbereich „{self.scope.name}“ (Version {self.scope.version}). "
                   "Erstmals gesehene Anzeigen dieses Laufs gelten nicht als neu veröffentlicht.")
            db.execute(pg_insert(TimelineNote).values(note_date=run.logical_date, kind=kind, source_id=self.source.id, message=msg).on_conflict_do_nothing())
        prev_parser = db.execute(select(ScanRun.parser_version).where(
            ScanRun.scope_id == run.scope_id, ScanRun.id != run.id, ScanRun.is_test.is_(False), ScanRun.parser_version.isnot(None)
        ).order_by(ScanRun.id.desc()).limit(1)).scalar_one_or_none()
        if prev_parser and prev_parser != run.parser_version:
            db.execute(pg_insert(TimelineNote).values(
                note_date=run.logical_date, kind="parser_changed", source_id=self.source.id,
                message=f"Parserwechsel {self.source.name}: {prev_parser} → {run.parser_version}").on_conflict_do_nothing())
        if run.status == "blocked":
            _warn(db, "blocked", f"blocked:{self.source.id}", self.source.id, f"{self.source.name}: Lauf blockiert – {run.status_detail}")
        elif run.status == "complete":
            db.execute(sql("UPDATE ops_warning SET resolved_at = now() WHERE resolved_at IS NULL AND dedupe_key IN (:a, :b)"),
                       {"a": f"blocked:{self.source.id}", "b": f"stale:{self.source.id}"})
        stock_after = self._stock()
        if stock_before >= 50 and not run.is_baseline:
            change = (stock_after - stock_before) / stock_before * 100
            if abs(change) >= s.stock_change_warn_percent:
                _warn(db, "stock_change", f"stock:{self.source.id}:{run.logical_date}", self.source.id,
                      f"{self.source.name}: Bestand änderte sich um {change:+.1f} % ({stock_before} → {stock_after}) – bitte Lauf und Abdeckung prüfen")


def _warn(db: Session, kind: str, key: str, source_id: int | None, message: str) -> None:
    exists = db.execute(select(OpsWarning.id).where(OpsWarning.dedupe_key == key, OpsWarning.resolved_at.is_(None))).first()
    if exists is None:
        db.add(OpsWarning(kind=kind, dedupe_key=key, source_id=source_id, message=message))


def execute_run(run_id: int, *, settings: Settings | None = None,
                fetcher_factory: Callable[[Source, SourceAdapter, Settings], Fetcher] | None = None,
                heartbeat: Callable[[], None] | None = None, adapter: SourceAdapter | None = None) -> str:
    """Führt einen Lauf aus bzw. setzt ihn fort. Gibt den Abschlussstatus zurück."""
    settings = settings or get_settings()
    with session_scope() as db:
        run = db.get(ScanRun, run_id)
        if run is None:
            raise ValueError(f"Lauf {run_id} existiert nicht")
        if run.status in RUN_FINAL and run.status not in ("partial", "blocked", "failed"):
            return run.status
        if run.status in ("partial", "blocked", "failed") and run.finished_at is not None and run.control != "retry":
            return run.status
        # Schutz vor überlappenden Läufen derselben Quelle/Konfiguration (auch über Prozesse hinweg):
        # sitzungsgebundene Advisory-Sperre auf eigener Verbindung, da der Lauf seitenweise committet.
        lock_conn = get_engine().connect()
        try:
            lock_key = f"scan:{run.source_id}:{run.scope_key}"
            got = lock_conn.execute(sql("SELECT pg_try_advisory_lock(hashtext(:k))"), {"k": lock_key}).scalar_one()
            if not got:
                raise RunRefused("für diese Quelle und diesen Suchbereich läuft bereits ein Scan")
            try:
                engine = RunEngine(db, run, settings=settings, fetcher_factory=fetcher_factory, heartbeat=heartbeat, adapter=adapter)
                engine.check_allowed()
            except RunRefused as exc:
                run.status, run.status_detail, run.finished_at = "failed", str(exc), datetime.now(UTC)
                db.commit()
                raise
            if run.control == "retry":
                for t in db.execute(select(ScanTask).where(ScanTask.run_id == run.id, ScanTask.status.in_(("partial", "blocked", "failed")))).scalars():
                    t.status = "pending"
                run.finished_at = None
            engine.execute()
            return run.status
        finally:
            try:
                lock_conn.execute(sql("SELECT pg_advisory_unlock_all()"))
            finally:
                lock_conn.close()


def request_control(db: Session, run: ScanRun, action: str) -> None:
    """Pause/Abbruch anfordern bzw. Wiederholung/Fortsetzung vorbereiten."""
    if action in ("pause", "cancel"):
        if run.status == "queued" and action == "cancel":
            run.status, run.finished_at, run.status_detail = "cancelled", datetime.now(UTC), "vor dem Start abgebrochen"
        elif run.status == "paused" and action == "cancel":
            run.status, run.finished_at, run.status_detail = "cancelled", datetime.now(UTC), "abgebrochen"
        elif run.status == "running":
            run.control = action
        else:
            raise ValueError(f"Aktion {action!r} im Status {run.status!r} nicht möglich")
    elif action == "resume":
        if run.status != "paused":
            raise ValueError("nur pausierte Läufe können fortgesetzt werden")
        run.status, run.control = "queued", None
    elif action == "retry":
        if run.status not in ("partial", "blocked", "failed"):
            raise ValueError("nur unvollständige, blockierte oder fehlgeschlagene Läufe können wiederholt werden")
        if run.logical_date != local_today():
            raise ValueError("Wiederholung nur am selben logischen Tag möglich – vergangene Tage können nicht nachbeobachtet werden")
        run.control = "retry"
        run.status = "queued"
    else:
        raise ValueError(f"unbekannte Aktion {action!r}")


def make_test_item(key: str, url: str) -> ListItem:  # kleine Hilfe für Tests
    return ListItem(source_key=key, url=url)
