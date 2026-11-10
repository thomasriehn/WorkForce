"""Datenmodell (SQLAlchemy 2).

Leitlinien:
* Technische Zeitstempel in UTC (``timestamptz``); fachliche Bezugsdaten als lokales Datum (Europe/Berlin).
* Amtliche Schlüssel sind Zeichenketten mit führenden Nullen (Kreis = 5 Stellen, Gemeinde = 8 Stellen).
* Quellanzeige (``source_posting``) ≠ zusammengeführte Anzeige (``merged_posting``).
* Inhaltsversionen (``posting_version``) sind unveränderlich; Beobachtungen (``observation``) sind kompakt.
"""
from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from typing import Any

from geoalchemy2 import Geometry
from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    Computed,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    SmallInteger,
    String,
    Text,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import ARRAY, JSONB, TSVECTOR
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    type_annotation_map = {dict[str, Any]: JSONB, list[str]: ARRAY(Text), list[int]: ARRAY(Integer)}


def _now() -> Any:
    return func.now()


TS = DateTime(timezone=True)

# --- Wertebereiche (als CHECK-Constraints, bewusst keine PG-Enums) ------------------------------
SOURCE_CONFIG_STATUS = ("candidate", "active", "disabled", "permission_required")
RUN_STATUS = ("queued", "running", "paused", "complete", "partial", "blocked", "failed", "cancelled")
RUN_FINAL = ("complete", "partial", "blocked", "failed", "cancelled")
RUN_TRIGGER = ("scheduled", "catchup", "manual", "test")
SCOPE_MODE = ("full", "new_only")
POSTING_STATUS = ("active", "not_reobserved", "presumed_removed", "ended", "stale")
IN_STOCK = ("active", "not_reobserved")
CHANGE_KIND = ("initial", "enrichment", "content", "parser", "mixed")
POLARITY = ("required", "desired", "negated", "unclear")
GEO_CLASS = ("resolved", "partial", "unresolved", "remote_nationwide", "foreign", "none")
VALUE_STATUS = ("ok", "zero", "suppressed", "unknown", "not_available", "not_collected")
JOB_STATUS = ("queued", "running", "done", "failed", "cancelled")


def _in(col: str, values: tuple[str, ...]) -> str:
    return f"{col} IN ({', '.join(repr(v) for v in values)})"


# ================================================================================================
# Benutzer
# ================================================================================================
class User(Base):
    __tablename__ = "app_user"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    username: Mapped[str] = mapped_column(String(80), unique=True)
    password_hash: Mapped[str] = mapped_column(Text)
    role: Mapped[str] = mapped_column(String(16), default="reader")
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, server_default=text("true"))
    failed_logins: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    locked_until: Mapped[datetime | None] = mapped_column(TS)
    created_at: Mapped[datetime] = mapped_column(TS, server_default=_now())
    last_login_at: Mapped[datetime | None] = mapped_column(TS)
    __table_args__ = (CheckConstraint("role IN ('admin','reader')", name="ck_user_role"),)


class UserSession(Base):
    __tablename__ = "user_session"
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("app_user.id", ondelete="CASCADE"), index=True)
    token_hash: Mapped[str] = mapped_column(String(64), unique=True)
    csrf_token: Mapped[str] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(TS, server_default=_now())
    expires_at: Mapped[datetime] = mapped_column(TS)
    user: Mapped[User] = relationship()


class SavedSearch(Base):
    __tablename__ = "saved_search"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("app_user.id", ondelete="CASCADE"), index=True)
    name: Mapped[str] = mapped_column(String(120))
    params: Mapped[dict[str, Any]] = mapped_column(JSONB)
    created_at: Mapped[datetime] = mapped_column(TS, server_default=_now())
    __table_args__ = (UniqueConstraint("user_id", "name", name="uq_saved_search_user_name"),)


class AuditLog(Base):
    __tablename__ = "audit_log"
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    at: Mapped[datetime] = mapped_column(TS, server_default=_now(), index=True)
    username: Mapped[str | None] = mapped_column(String(80))
    action: Mapped[str] = mapped_column(String(80))
    details: Mapped[dict[str, Any] | None] = mapped_column(JSONB)


# ================================================================================================
# Quellenregister, Suchbereiche, Scanläufe
# ================================================================================================
class Source(Base):
    """Quellenregister: Konfigurationsstatus getrennt vom Ergebnis des letzten Laufs."""

    __tablename__ = "source"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    key: Mapped[str] = mapped_column(String(64), unique=True)
    name: Mapped[str] = mapped_column(String(160))
    domain: Mapped[str] = mapped_column(String(160))
    entry_url: Mapped[str | None] = mapped_column(Text)
    country: Mapped[str] = mapped_column(String(2), default="DE", server_default="DE")
    segment: Mapped[str | None] = mapped_column(Text)  # fachliche Abdeckung
    is_career_page: Mapped[bool] = mapped_column(Boolean, default=False, server_default=text("false"))
    access_method: Mapped[str | None] = mapped_column(String(64))  # z. B. html_embedded_state, sitemap_jsonld
    adapter_key: Mapped[str | None] = mapped_column(String(64))
    adapter_version: Mapped[str | None] = mapped_column(String(32))
    allowed_domains: Mapped[list[str]] = mapped_column(ARRAY(Text), default=list, server_default="{}")
    terms_url: Mapped[str | None] = mapped_column(Text)
    robots_url: Mapped[str | None] = mapped_column(Text)
    legal_checked_on: Mapped[date | None] = mapped_column(Date)
    legal_notes: Mapped[str | None] = mapped_column(Text)  # Fundstellen, Einschränkungen
    attribution: Mapped[str | None] = mapped_column(Text)
    config_status: Mapped[str] = mapped_column(String(24), default="candidate", server_default="candidate")
    status_reason: Mapped[str | None] = mapped_column(Text)  # konkreter Ausfall-/Deaktivierungsgrund
    request_interval_seconds: Mapped[float] = mapped_column(Numeric(6, 2), default=3.0, server_default="3.0")
    max_pages_per_run: Mapped[int] = mapped_column(Integer, default=400, server_default="400")
    max_details_per_run: Mapped[int] = mapped_column(Integer, default=500, server_default="500")
    created_at: Mapped[datetime] = mapped_column(TS, server_default=_now())
    updated_at: Mapped[datetime] = mapped_column(TS, server_default=_now(), onupdate=_now())
    scopes: Mapped[list[SearchScope]] = relationship(back_populates="source", order_by="SearchScope.id")
    __table_args__ = (CheckConstraint(_in("config_status", SOURCE_CONFIG_STATUS), name="ck_source_config_status"),)


class SearchScope(Base):
    """Versionierter Suchbereich. Geänderte Parameter => neue Version (neue Zeile), alte wird deaktiviert."""

    __tablename__ = "search_scope"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    source_id: Mapped[int] = mapped_column(ForeignKey("source.id", ondelete="CASCADE"), index=True)
    key: Mapped[str] = mapped_column(String(80))
    version: Mapped[int] = mapped_column(Integer, default=1)
    name: Mapped[str] = mapped_column(String(200))
    params: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    mode: Mapped[str] = mapped_column(String(16), default="full", server_default="full")
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, server_default=text("true"))
    page_budget: Mapped[int | None] = mapped_column(Integer)  # überschreibt Quellenbudget
    note: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(TS, server_default=_now())
    retired_at: Mapped[datetime | None] = mapped_column(TS)
    source: Mapped[Source] = relationship(back_populates="scopes")
    __table_args__ = (
        UniqueConstraint("source_id", "key", "version", name="uq_scope_source_key_version"),
        CheckConstraint(_in("mode", SCOPE_MODE), name="ck_scope_mode"),
        Index("uq_scope_one_active", "source_id", "key", unique=True, postgresql_where=text("is_active")),
    )


class ScanRun(Base):
    """Ein logischer Lauf je Quelle, Suchbereich(sversion) und lokalem Tagesdatum."""

    __tablename__ = "scan_run"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    source_id: Mapped[int] = mapped_column(ForeignKey("source.id", ondelete="CASCADE"), index=True)
    scope_id: Mapped[int] = mapped_column(ForeignKey("search_scope.id", ondelete="CASCADE"), index=True)
    scope_key: Mapped[str] = mapped_column(String(80))
    scope_version: Mapped[int] = mapped_column(Integer)
    logical_date: Mapped[date] = mapped_column(Date, index=True)
    trigger: Mapped[str] = mapped_column(String(16), default="scheduled")
    mode: Mapped[str] = mapped_column(String(16), default="full")
    is_test: Mapped[bool] = mapped_column(Boolean, default=False, server_default=text("false"))
    is_baseline: Mapped[bool] = mapped_column(Boolean, default=False, server_default=text("false"))
    page_limit: Mapped[int | None] = mapped_column(Integer)
    parser_version: Mapped[str | None] = mapped_column(String(32))
    classifier_version: Mapped[str | None] = mapped_column(String(32))
    status: Mapped[str] = mapped_column(String(16), default="queued", index=True)
    status_detail: Mapped[str | None] = mapped_column(Text)
    control: Mapped[str | None] = mapped_column(String(16))  # pause | cancel (angeforderte Steuerung)
    list_complete: Mapped[bool | None] = mapped_column(Boolean)
    detail_complete: Mapped[bool | None] = mapped_column(Boolean)
    attempts: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    created_at: Mapped[datetime] = mapped_column(TS, server_default=_now())
    started_at: Mapped[datetime | None] = mapped_column(TS)
    finished_at: Mapped[datetime | None] = mapped_column(TS)
    window_start: Mapped[datetime | None] = mapped_column(TS)  # tatsächliches Beobachtungsfenster
    window_end: Mapped[datetime | None] = mapped_column(TS)
    pages_fetched: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    requests_made: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    partitions_total: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    partitions_done: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    reported_total: Mapped[int | None] = mapped_column(Integer)  # vom Portal gemeldete Trefferzahl
    ids_found: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    postings_extracted: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    postings_new: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    postings_changed: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    details_fetched: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    details_pending: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    error_count: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    coverage: Mapped[dict[str, Any] | None] = mapped_column(JSONB)  # überprüfbare Abdeckungssignale
    status_applied: Mapped[bool] = mapped_column(Boolean, default=False, server_default=text("false"))
    source: Mapped[Source] = relationship()
    scope: Mapped[SearchScope] = relationship()
    tasks: Mapped[list[ScanTask]] = relationship(back_populates="run", order_by="ScanTask.id")
    __table_args__ = (
        CheckConstraint(_in("status", RUN_STATUS), name="ck_run_status"),
        CheckConstraint(_in("trigger", RUN_TRIGGER), name="ck_run_trigger"),
        # genau ein logischer Tageslauf je Suchbereich und Datum (Testläufe ausgenommen)
        Index("uq_run_scope_day", "scope_id", "logical_date", unique=True, postgresql_where=text("NOT is_test")),
        Index("ix_run_source_date", "source_id", "logical_date"),
    )


class ScanTask(Base):
    """Teilauftrag eines Laufs (Partition der Listenentdeckung oder Detailphase) mit Checkpoint."""

    __tablename__ = "scan_task"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    run_id: Mapped[int] = mapped_column(ForeignKey("scan_run.id", ondelete="CASCADE"), index=True)
    kind: Mapped[str] = mapped_column(String(16))  # list | detail
    partition_key: Mapped[str] = mapped_column(String(200))
    status: Mapped[str] = mapped_column(String(16), default="pending")  # pending|running|done|partial|blocked|failed
    status_detail: Mapped[str | None] = mapped_column(Text)
    checkpoint: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    pages_fetched: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    ids_found: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    reported_total: Mapped[int | None] = mapped_column(Integer)
    started_at: Mapped[datetime | None] = mapped_column(TS)
    finished_at: Mapped[datetime | None] = mapped_column(TS)
    run: Mapped[ScanRun] = relationship(back_populates="tasks")
    __table_args__ = (UniqueConstraint("run_id", "kind", "partition_key", name="uq_task_run_kind_partition"),)


class ScanError(Base):
    """Technisches Fehlerprotokoll (unterliegt der konfigurierbaren Aufbewahrung technischer Logs)."""

    __tablename__ = "scan_error"
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    run_id: Mapped[int] = mapped_column(ForeignKey("scan_run.id", ondelete="CASCADE"), index=True)
    task_id: Mapped[int | None] = mapped_column(ForeignKey("scan_task.id", ondelete="SET NULL"))
    at: Mapped[datetime] = mapped_column(TS, server_default=_now(), index=True)
    kind: Mapped[str] = mapped_column(String(32))  # timeout|http_403|captcha|parse|robots|cap|repeat|empty|...
    url: Mapped[str | None] = mapped_column(Text)
    message: Mapped[str | None] = mapped_column(Text)


# ================================================================================================
# Anzeigen
# ================================================================================================
class Employer(Base):
    __tablename__ = "employer"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(Text)
    name_norm: Mapped[str] = mapped_column(Text, unique=True)
    is_staffing_agency: Mapped[bool | None] = mapped_column(Boolean)  # None = unbekannt
    created_at: Mapped[datetime] = mapped_column(TS, server_default=_now())


class MergedPosting(Base):
    """Zusammengeführte Anzeige (portalübergreifend). Jede Quellanzeige gehört zu genau einer."""

    __tablename__ = "merged_posting"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    primary_source_posting_id: Mapped[int | None] = mapped_column(
        ForeignKey("source_posting.id", use_alter=True, name="fk_merged_primary_sp", ondelete="SET NULL")
    )
    current_version_id: Mapped[int | None] = mapped_column(
        ForeignKey("posting_version.id", use_alter=True, name="fk_merged_current_version", ondelete="SET NULL"),
        index=True,
    )
    status: Mapped[str] = mapped_column(String(20), default="active", index=True)
    first_seen_at: Mapped[datetime] = mapped_column(TS)
    first_seen_date: Mapped[date] = mapped_column(Date, index=True)
    first_seen_baseline: Mapped[bool] = mapped_column(Boolean, default=False, server_default=text("false"))
    last_seen_at: Mapped[datetime] = mapped_column(TS)
    last_seen_date: Mapped[date] = mapped_column(Date)
    member_count: Mapped[int] = mapped_column(Integer, default=1, server_default="1")
    source_ids: Mapped[list[int]] = mapped_column(ARRAY(Integer), default=list, server_default="{}")
    dedup_rule_version: Mapped[str | None] = mapped_column(String(32))
    is_synthetic: Mapped[bool] = mapped_column(Boolean, default=False, server_default=text("false"))
    created_at: Mapped[datetime] = mapped_column(TS, server_default=_now())
    updated_at: Mapped[datetime] = mapped_column(TS, server_default=_now(), onupdate=_now())
    __table_args__ = (
        CheckConstraint(_in("status", POSTING_STATUS), name="ck_merged_status"),
        Index("ix_merged_source_ids", "source_ids", postgresql_using="gin"),
    )


class SourcePosting(Base):
    """Quellanzeige: eine Anzeige auf genau einem Portal (stabile Quell-ID)."""

    __tablename__ = "source_posting"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    source_id: Mapped[int] = mapped_column(ForeignKey("source.id", ondelete="RESTRICT"), index=True)
    source_key: Mapped[str] = mapped_column(String(200))
    original_url: Mapped[str] = mapped_column(Text)
    canonical_url: Mapped[str | None] = mapped_column(Text)
    employer_id: Mapped[int | None] = mapped_column(ForeignKey("employer.id", ondelete="SET NULL"), index=True)
    merged_posting_id: Mapped[int | None] = mapped_column(
        ForeignKey("merged_posting.id", ondelete="SET NULL"), index=True
    )
    current_version_id: Mapped[int | None] = mapped_column(
        ForeignKey("posting_version.id", use_alter=True, name="fk_sp_current_version", ondelete="SET NULL")
    )
    first_seen_at: Mapped[datetime] = mapped_column(TS)
    first_seen_date: Mapped[date] = mapped_column(Date)
    first_seen_run_id: Mapped[int | None] = mapped_column(ForeignKey("scan_run.id", ondelete="SET NULL"))
    first_seen_baseline: Mapped[bool] = mapped_column(Boolean, default=False, server_default=text("false"))
    last_seen_at: Mapped[datetime] = mapped_column(TS)
    last_seen_date: Mapped[date] = mapped_column(Date)
    last_detail_check_at: Mapped[datetime | None] = mapped_column(TS)
    detail_due: Mapped[bool] = mapped_column(Boolean, default=True, server_default=text("true"))
    list_hash: Mapped[str | None] = mapped_column(String(64))  # Hash der Listendaten (Änderungssignal)
    raw_hash: Mapped[str | None] = mapped_column(String(64))  # Hash des stabilen Rohinhalts (zuletzt gesehen)
    status: Mapped[str] = mapped_column(String(20), default="active", index=True)
    status_reason: Mapped[str | None] = mapped_column(Text)
    status_changed_at: Mapped[datetime | None] = mapped_column(TS)
    gone_confirmations: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    gone_last_date: Mapped[date | None] = mapped_column(Date)
    is_synthetic: Mapped[bool] = mapped_column(Boolean, default=False, server_default=text("false"))
    source: Mapped[Source] = relationship()
    __table_args__ = (
        UniqueConstraint("source_id", "source_key", name="uq_sp_source_key"),
        CheckConstraint(_in("status", POSTING_STATUS), name="ck_sp_status"),
        Index("ix_sp_canonical_url", "canonical_url"),
        Index("ix_sp_detail_due", "source_id", postgresql_where=text("detail_due")),
    )


class PostingVersion(Base):
    """Unveränderliche Inhaltsversion einer Quellanzeige (Rumpfdaten + strukturierte Extraktion).

    ``valid_from``/``valid_to`` sind logische Tagesdaten; historische Filter greifen auf die damals gültige
    Version zu. Volltext der Anzeige wird nicht gespeichert, nur kurze Belegauszüge.
    """

    __tablename__ = "posting_version"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    source_posting_id: Mapped[int] = mapped_column(ForeignKey("source_posting.id", ondelete="CASCADE"))
    version_no: Mapped[int] = mapped_column(Integer)
    change_kind: Mapped[str] = mapped_column(String(16), default="initial")
    detail_level: Mapped[str] = mapped_column(String(8), default="list")  # list | detail
    content_hash: Mapped[str] = mapped_column(String(64))
    raw_hash: Mapped[str | None] = mapped_column(String(64))
    parser_version: Mapped[str] = mapped_column(String(32))
    classifier_version: Mapped[str] = mapped_column(String(32))
    geo_rule_version: Mapped[str] = mapped_column(String(32))
    created_at: Mapped[datetime] = mapped_column(TS, server_default=_now())
    run_id: Mapped[int | None] = mapped_column(ForeignKey("scan_run.id", ondelete="SET NULL"))
    valid_from: Mapped[date] = mapped_column(Date)
    valid_to: Mapped[date | None] = mapped_column(Date)  # exklusiv; NULL = aktuell

    # --- Rumpfdaten -----------------------------------------------------------------------------
    title: Mapped[str] = mapped_column(Text)
    title_norm: Mapped[str] = mapped_column(Text)
    employer_name: Mapped[str | None] = mapped_column(Text)
    employer_norm: Mapped[str | None] = mapped_column(Text)
    reference: Mapped[str | None] = mapped_column(Text)  # Stellenreferenz des Arbeitgebers
    employer_url: Mapped[str | None] = mapped_column(Text)  # Arbeitgeber-Zielverweis (normalisiert)
    is_agency: Mapped[bool | None] = mapped_column(Boolean)  # Personalvermittlung/Zeitarbeit; None = unbekannt
    kind: Mapped[str] = mapped_column(String(20), default="job")  # job|ausbildung|duales_studium|praktikum|trainee|...
    employment_types: Mapped[list[str]] = mapped_column(ARRAY(Text), default=list, server_default="{}")
    working_time: Mapped[list[str]] = mapped_column(ARRAY(Text), default=list, server_default="{}")
    contract_term: Mapped[str | None] = mapped_column(String(16))  # befristet|unbefristet|None
    remote_type: Mapped[str | None] = mapped_column(String(16))  # remote|hybrid|onsite|None
    occupation_label: Mapped[str | None] = mapped_column(Text)  # Berufsangabe der Quelle
    occupation_field: Mapped[str | None] = mapped_column(Text)
    kldb_code: Mapped[str | None] = mapped_column(String(5), index=True)
    kldb_source: Mapped[str | None] = mapped_column(String(24))  # portal_field|title_exact|title_fuzzy
    kldb_confidence: Mapped[float | None] = mapped_column(Numeric(4, 3))
    requirement_level: Mapped[int | None] = mapped_column(SmallInteger)  # KldB-Anforderungsniveau 1–4
    salary_min: Mapped[Decimal | None] = mapped_column(Numeric(12, 2))
    salary_max: Mapped[Decimal | None] = mapped_column(Numeric(12, 2))
    salary_currency: Mapped[str | None] = mapped_column(String(3))
    salary_period: Mapped[str | None] = mapped_column(String(8))  # HOUR|DAY|WEEK|MONTH|YEAR
    salary_origin: Mapped[str | None] = mapped_column(String(20))  # employer|portal_estimate|unknown
    salary_text: Mapped[str | None] = mapped_column(Text)  # z. B. Tarif-/Besoldungsgruppe
    date_posted: Mapped[date | None] = mapped_column(Date)  # Veröffentlichungsdatum laut Quelle
    apply_until: Mapped[date | None] = mapped_column(Date)
    valid_through: Mapped[date | None] = mapped_column(Date)  # von der Quelle angekündigtes Veröffentlichungsende
    excerpts: Mapped[list[str]] = mapped_column(ARRAY(Text), default=list, server_default="{}")
    quality: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict, server_default="{}")

    # --- Georeferenz (denormalisiert für Filter und Zählregeln) ------------------------------------
    kreis_keys: Mapped[list[str]] = mapped_column(ARRAY(Text), default=list, server_default="{}")
    state_keys: Mapped[list[str]] = mapped_column(ARRAY(Text), default=list, server_default="{}")
    loc_total: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    loc_unresolved: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    geo_class: Mapped[str] = mapped_column(String(20), default="none", server_default="none")

    # --- Merkmale (denormalisiert) ------------------------------------------------------------------
    feature_keys: Mapped[list[str]] = mapped_column(ARRAY(Text), default=list, server_default="{}")
    feature_required_keys: Mapped[list[str]] = mapped_column(ARRAY(Text), default=list, server_default="{}")

    # --- Suche ---------------------------------------------------------------------------------------
    search_a: Mapped[str] = mapped_column(Text, default="", server_default="")  # Titel (gefaltet)
    search_b: Mapped[str] = mapped_column(Text, default="", server_default="")  # Arbeitgeber (gefaltet)
    search_c: Mapped[str] = mapped_column(Text, default="", server_default="")  # Merkmale/Beruf/Auszüge
    tsv: Mapped[Any] = mapped_column(
        TSVECTOR,
        Computed(
            "setweight(to_tsvector('simple', search_a), 'A') || setweight(to_tsvector('german', search_a), 'A') || "
            "setweight(to_tsvector('simple', search_b), 'B') || "
            "setweight(to_tsvector('simple', search_c), 'C') || setweight(to_tsvector('german', search_c), 'C')",
            persisted=True,
        ),
    )

    locations: Mapped[list[PostingLocation]] = relationship(
        back_populates="version", order_by="PostingLocation.ordinal", cascade="all, delete-orphan"
    )
    features: Mapped[list[PostingFeature]] = relationship(back_populates="version", cascade="all, delete-orphan")
    __table_args__ = (
        UniqueConstraint("source_posting_id", "version_no", name="uq_version_sp_no"),
        CheckConstraint(_in("change_kind", CHANGE_KIND), name="ck_version_change_kind"),
        CheckConstraint(_in("geo_class", GEO_CLASS), name="ck_version_geo_class"),
        Index("ix_version_sp_valid", "source_posting_id", "valid_from"),
        Index("ix_version_tsv", "tsv", postgresql_using="gin"),
        Index("ix_version_title_trgm", "search_a", postgresql_using="gin", postgresql_ops={"search_a": "gin_trgm_ops"}),
        Index("ix_version_employer_trgm", "search_b", postgresql_using="gin", postgresql_ops={"search_b": "gin_trgm_ops"}),
        Index("ix_version_features", "feature_keys", postgresql_using="gin"),
        Index("ix_version_kreise", "kreis_keys", postgresql_using="gin"),
        Index("ix_version_states", "state_keys", postgresql_using="gin"),
        Index("ix_version_reference", "employer_norm", "reference", postgresql_where=text("reference IS NOT NULL")),
        Index("ix_version_employer_url", "employer_url", postgresql_where=text("employer_url IS NOT NULL")),
        Index("ix_version_emp_title", "employer_norm", "title_norm"),
        Index("ix_version_valid_from", "valid_from", "change_kind"),
    )


class PostingLocation(Base):
    """Arbeitsort einer Inhaltsversion mit Zuordnungsquelle und -genauigkeit (historisch erhalten)."""

    __tablename__ = "posting_location"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    version_id: Mapped[int] = mapped_column(ForeignKey("posting_version.id", ondelete="CASCADE"), index=True)
    ordinal: Mapped[int] = mapped_column(SmallInteger, default=0)
    raw_text: Mapped[str | None] = mapped_column(Text)
    locality: Mapped[str | None] = mapped_column(Text)
    postal_code: Mapped[str | None] = mapped_column(String(10))
    region_text: Mapped[str | None] = mapped_column(Text)
    country: Mapped[str | None] = mapped_column(String(2))
    kreis_key: Mapped[str | None] = mapped_column(String(5), index=True)
    state_key: Mapped[str | None] = mapped_column(String(2))
    ags: Mapped[str | None] = mapped_column(String(8))  # achtstelliger Gemeindeschlüssel, falls bestimmt
    gebietsstand: Mapped[date | None] = mapped_column(Date)
    match_method: Mapped[str] = mapped_column(String(32), default="unresolved")
    precision: Mapped[str] = mapped_column(String(20), default="unresolved")
    confidence: Mapped[float | None] = mapped_column(Numeric(4, 3))
    point: Mapped[Any | None] = mapped_column(Geometry("POINT", srid=4326, spatial_index=True))
    point_origin: Mapped[str | None] = mapped_column(String(20))  # source | place_centroid (angenähert)
    version: Mapped[PostingVersion] = relationship(back_populates="locations")


class Feature(Base):
    """Wörterbuch normalisierter Merkmale (Abschlüsse, Kenntnisse, Zertifikate, Sprachen …)."""

    __tablename__ = "feature"
    key: Mapped[str] = mapped_column(String(80), primary_key=True)  # z. B. skill:cpp
    type: Mapped[str] = mapped_column(String(20), index=True)  # qual|exp|skill|cert|lang|license
    label: Mapped[str] = mapped_column(Text)
    synonyms: Mapped[list[str]] = mapped_column(ARRAY(Text), default=list, server_default="{}")
    rule_version: Mapped[str] = mapped_column(String(32))


class PostingFeature(Base):
    """Abgeleitetes Merkmal einer Version mit Herkunft, Regelversion, Polarität und kurzem Beleg."""

    __tablename__ = "posting_feature"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    version_id: Mapped[int] = mapped_column(ForeignKey("posting_version.id", ondelete="CASCADE"), index=True)
    feature_key: Mapped[str] = mapped_column(String(80), index=True)
    type: Mapped[str] = mapped_column(String(20))
    label: Mapped[str] = mapped_column(Text)
    polarity: Mapped[str] = mapped_column(String(12))
    origin: Mapped[str] = mapped_column(String(24))  # rule_text|portal_field|jsonld|kldb
    rule_version: Mapped[str] = mapped_column(String(32))
    confidence: Mapped[float | None] = mapped_column(Numeric(4, 3))
    evidence: Mapped[str | None] = mapped_column(Text)  # kurzer Beleg (max. ~200 Zeichen)
    detail: Mapped[str | None] = mapped_column(Text)  # z. B. „3 Jahre“, Sprachniveau
    version: Mapped[PostingVersion] = relationship(back_populates="features")
    __table_args__ = (CheckConstraint(_in("polarity", POLARITY), name="ck_feature_polarity"),)


class Observation(Base):
    """Kompakter Beobachtungsdatensatz: Quellanzeige wurde in einem logischen Lauf gesehen."""

    __tablename__ = "observation"
    run_id: Mapped[int] = mapped_column(ForeignKey("scan_run.id", ondelete="CASCADE"), primary_key=True)
    source_posting_id: Mapped[int] = mapped_column(
        ForeignKey("source_posting.id", ondelete="CASCADE"), primary_key=True
    )
    version_id: Mapped[int | None] = mapped_column(ForeignKey("posting_version.id", ondelete="SET NULL"))
    seen_list: Mapped[bool] = mapped_column(Boolean, default=False, server_default=text("false"))
    seen_detail: Mapped[bool] = mapped_column(Boolean, default=False, server_default=text("false"))
    observed_at: Mapped[datetime] = mapped_column(TS, server_default=_now())
    __table_args__ = (Index("ix_observation_sp", "source_posting_id", "run_id"),)


class PostingScope(Base):
    """Zugehörigkeit einer Quellanzeige zu einem Suchbereich; zählt verpasste vollständige Scans."""

    __tablename__ = "posting_scope"
    source_posting_id: Mapped[int] = mapped_column(
        ForeignKey("source_posting.id", ondelete="CASCADE"), primary_key=True
    )
    scope_id: Mapped[int] = mapped_column(ForeignKey("search_scope.id", ondelete="CASCADE"), primary_key=True)
    first_run_id: Mapped[int | None] = mapped_column(ForeignKey("scan_run.id", ondelete="SET NULL"))
    last_seen_run_id: Mapped[int | None] = mapped_column(ForeignKey("scan_run.id", ondelete="SET NULL"))
    last_seen_date: Mapped[date] = mapped_column(Date)
    missed_complete_runs: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    __table_args__ = (Index("ix_posting_scope_scope", "scope_id", "missed_complete_runs"),)


class ActivityPeriod(Base):
    """Zeitraum, in dem eine Quellanzeige zum beobachteten Bestand zählt (offen = im Bestand)."""

    __tablename__ = "activity_period"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    source_posting_id: Mapped[int] = mapped_column(ForeignKey("source_posting.id", ondelete="CASCADE"))
    start_date: Mapped[date] = mapped_column(Date)
    end_date: Mapped[date | None] = mapped_column(Date)  # inklusiv: letzter Tag im Bestand
    end_reason: Mapped[str | None] = mapped_column(String(20))
    __table_args__ = (
        Index("uq_period_open", "source_posting_id", unique=True, postgresql_where=text("end_date IS NULL")),
        Index("ix_period_sp", "source_posting_id", "start_date"),
        Index("ix_period_dates", "start_date", "end_date"),
    )


class MergeLink(Base):
    """Zuordnung Quellanzeige → zusammengeführte Anzeige mit Entscheidungsgrund (nachvollziehbar, umkehrbar)."""

    __tablename__ = "merge_link"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    merged_posting_id: Mapped[int] = mapped_column(ForeignKey("merged_posting.id", ondelete="CASCADE"), index=True)
    source_posting_id: Mapped[int] = mapped_column(ForeignKey("source_posting.id", ondelete="CASCADE"), index=True)
    matched_source_posting_id: Mapped[int | None] = mapped_column(ForeignKey("source_posting.id", ondelete="SET NULL"))
    reason: Mapped[str] = mapped_column(String(40))  # singleton|employer_reference|employer_url|employer_title_location|manual
    confidence: Mapped[float] = mapped_column(Numeric(4, 3), default=1.0)
    rule_version: Mapped[str] = mapped_column(String(32))
    decided_by: Mapped[str] = mapped_column(String(80), default="auto")
    created_at: Mapped[datetime] = mapped_column(TS, server_default=_now())
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, server_default=text("true"))
    undone_at: Mapped[datetime | None] = mapped_column(TS)
    undone_by: Mapped[str | None] = mapped_column(String(80))
    __table_args__ = (
        Index("uq_merge_link_active", "source_posting_id", unique=True, postgresql_where=text("is_active")),
    )


class MergeCandidate(Base):
    """Unsicherer Dublettenkandidat – bleibt getrennt, bis er manuell entschieden wird."""

    __tablename__ = "merge_candidate"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    a_source_posting_id: Mapped[int] = mapped_column(ForeignKey("source_posting.id", ondelete="CASCADE"), index=True)
    b_source_posting_id: Mapped[int] = mapped_column(ForeignKey("source_posting.id", ondelete="CASCADE"), index=True)
    reason: Mapped[str] = mapped_column(String(60))
    score: Mapped[float] = mapped_column(Numeric(4, 3))
    rule_version: Mapped[str] = mapped_column(String(32))
    state: Mapped[str] = mapped_column(String(12), default="open")  # open|merged|rejected
    created_at: Mapped[datetime] = mapped_column(TS, server_default=_now())
    decided_at: Mapped[datetime | None] = mapped_column(TS)
    decided_by: Mapped[str | None] = mapped_column(String(80))
    __table_args__ = (UniqueConstraint("a_source_posting_id", "b_source_posting_id", name="uq_merge_candidate_pair"),)


class MergeBlock(Base):
    """Manuell getrenntes Paar: darf von den automatischen Regeln nicht erneut vereinigt werden."""

    __tablename__ = "merge_block"
    a_source_posting_id: Mapped[int] = mapped_column(ForeignKey("source_posting.id", ondelete="CASCADE"), primary_key=True)
    b_source_posting_id: Mapped[int] = mapped_column(ForeignKey("source_posting.id", ondelete="CASCADE"), primary_key=True)
    created_at: Mapped[datetime] = mapped_column(TS, server_default=_now())
    created_by: Mapped[str | None] = mapped_column(String(80))


class PostingEvent(Base):
    """Fachliche Ereignisse (Grundlage für Zeitreihen und Änderungsverlauf)."""

    __tablename__ = "posting_event"
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    at: Mapped[datetime] = mapped_column(TS, server_default=_now())
    event_date: Mapped[date] = mapped_column(Date)  # Datum der Feststellung
    effective_date: Mapped[date] = mapped_column(Date)  # fachlich wirksames Datum (z. B. Tag nach letzter Sichtung)
    event_type: Mapped[str] = mapped_column(String(24))
    # first_seen|additional_source|republication|reactivation|content_change|parser_change|left_stock
    merged_posting_id: Mapped[int | None] = mapped_column(ForeignKey("merged_posting.id", ondelete="CASCADE"), index=True)
    source_posting_id: Mapped[int | None] = mapped_column(ForeignKey("source_posting.id", ondelete="CASCADE"), index=True)
    version_id: Mapped[int | None] = mapped_column(ForeignKey("posting_version.id", ondelete="SET NULL"))
    run_id: Mapped[int | None] = mapped_column(ForeignKey("scan_run.id", ondelete="SET NULL"))
    baseline: Mapped[bool] = mapped_column(Boolean, default=False, server_default=text("false"))
    details: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    __table_args__ = (Index("ix_event_type_date", "event_type", "effective_date"),)


class TimelineNote(Base):
    """Vermerke zur Vergleichbarkeit (neue Quelle, geänderter Suchbereich, Parser-/Regelwechsel)."""

    __tablename__ = "timeline_note"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    note_date: Mapped[date] = mapped_column(Date, index=True)
    kind: Mapped[str] = mapped_column(String(32))  # source_added|scope_changed|parser_changed|rules_changed|gap
    source_id: Mapped[int | None] = mapped_column(ForeignKey("source.id", ondelete="CASCADE"))
    message: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(TS, server_default=_now())
    __table_args__ = (UniqueConstraint("note_date", "kind", "source_id", "message", name="uq_timeline_note"),)


# ================================================================================================
# Regionen und Ortsreferenz
# ================================================================================================
class Region(Base):
    """Gebietseinheit mit amtlichem Schlüssel und Gebietsstand (Länder, Kreise/kreisfreie Städte)."""

    __tablename__ = "region"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    country: Mapped[str] = mapped_column(String(2), default="DE")
    level: Mapped[str] = mapped_column(String(12))  # country|state|district
    key: Mapped[str] = mapped_column(String(12))  # DE: '14' (Land), '14713' (Kreis) – immer Zeichenkette
    name: Mapped[str] = mapped_column(Text)
    type_label: Mapped[str | None] = mapped_column(Text)  # z. B. Kreisfreie Stadt, Landkreis
    parent_key: Mapped[str | None] = mapped_column(String(12))
    gebietsstand: Mapped[date] = mapped_column(Date)
    is_current: Mapped[bool] = mapped_column(Boolean, default=True, server_default=text("true"))
    geom: Mapped[Any | None] = mapped_column(Geometry("MULTIPOLYGON", srid=4326, spatial_index=True))
    geom_simple: Mapped[Any | None] = mapped_column(Geometry("MULTIPOLYGON", srid=4326, spatial_index=False))
    centroid: Mapped[Any | None] = mapped_column(Geometry("POINT", srid=4326, spatial_index=False))
    area_km2: Mapped[float | None] = mapped_column(Numeric(12, 3))
    source_note: Mapped[str | None] = mapped_column(Text)
    __table_args__ = (
        UniqueConstraint("country", "level", "key", "gebietsstand", name="uq_region_key_stand"),
        Index("ix_region_current", "country", "level", "key", postgresql_where=text("is_current")),
    )


class Place(Base):
    """Lokale Ortsreferenz (Gemeinden und Aliasnamen) für die Zuordnung Ort → Gemeinde → Kreis."""

    __tablename__ = "geo_place"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    country: Mapped[str] = mapped_column(String(2), default="DE")
    name: Mapped[str] = mapped_column(Text)
    name_norm: Mapped[str] = mapped_column(Text, index=True)
    kind: Mapped[str] = mapped_column(String(16), default="municipality")  # municipality|alias|district
    ags: Mapped[str | None] = mapped_column(String(8))
    kreis_key: Mapped[str | None] = mapped_column(String(5), index=True)
    state_key: Mapped[str | None] = mapped_column(String(2))
    postal_code: Mapped[str | None] = mapped_column(String(5), index=True)  # PLZ des Verwaltungssitzes
    population: Mapped[int | None] = mapped_column(Integer)
    lat: Mapped[float | None] = mapped_column(Numeric(9, 6))
    lon: Mapped[float | None] = mapped_column(Numeric(9, 6))
    gebietsstand: Mapped[date | None] = mapped_column(Date)
    source_note: Mapped[str | None] = mapped_column(Text)
    __table_args__ = (Index("ix_place_name_trgm", "name_norm", postgresql_using="gin", postgresql_ops={"name_norm": "gin_trgm_ops"}),)


class PostalCode(Base):
    """PLZ-Referenz: welche Gemeinden/Kreise zu einer PLZ gehören (mehrdeutig möglich)."""

    __tablename__ = "postal_code"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    country: Mapped[str] = mapped_column(String(2), default="DE")
    plz: Mapped[str] = mapped_column(String(5), index=True)
    ags: Mapped[str | None] = mapped_column(String(8))
    kreis_key: Mapped[str] = mapped_column(String(5))
    place_name: Mapped[str | None] = mapped_column(Text)
    source_note: Mapped[str | None] = mapped_column(Text)
    __table_args__ = (UniqueConstraint("country", "plz", "ags", "kreis_key", name="uq_postal_code"),)


# ================================================================================================
# Berufsklassifikation
# ================================================================================================
class KldbClass(Base):
    """KldB 2010 (überarbeitete Fassung 2020): Systematik (1- bis 5-Steller)."""

    __tablename__ = "kldb_class"
    code: Mapped[str] = mapped_column(String(5), primary_key=True)
    level: Mapped[int] = mapped_column(SmallInteger)  # Anzahl Stellen
    name: Mapped[str] = mapped_column(Text)
    version: Mapped[str] = mapped_column(String(24), default="KldB 2010/2020")


class OccupationTitle(Base):
    """Berufsbenennungen (alphabetisches Verzeichnis + lokale Synonyme) → KldB-5-Steller."""

    __tablename__ = "occupation_title"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    title: Mapped[str] = mapped_column(Text)
    title_norm: Mapped[str] = mapped_column(Text, index=True)
    kldb_code: Mapped[str] = mapped_column(String(5), index=True)
    origin: Mapped[str] = mapped_column(String(24), default="kldb_alphabetisch")  # kldb_alphabetisch|synonym_local
    __table_args__ = (
        UniqueConstraint("title_norm", "kldb_code", name="uq_occupation_title"),
        Index("ix_occupation_title_trgm", "title_norm", postgresql_using="gin", postgresql_ops={"title_norm": "gin_trgm_ops"}),
    )


# ================================================================================================
# Amtliche Statistik
# ================================================================================================
class StatDataset(Base):
    __tablename__ = "stat_dataset"
    key: Mapped[str] = mapped_column(String(64), primary_key=True)
    name: Mapped[str] = mapped_column(Text)
    publisher: Mapped[str] = mapped_column(Text)
    dataset_code: Mapped[str | None] = mapped_column(Text)  # Datensatzkennung des Herausgebers
    landing_url: Mapped[str | None] = mapped_column(Text)
    licence: Mapped[str | None] = mapped_column(Text)
    licence_url: Mapped[str | None] = mapped_column(Text)
    attribution: Mapped[str | None] = mapped_column(Text)
    update_cycle: Mapped[str | None] = mapped_column(String(16))  # monthly|yearly|irregular
    notes: Mapped[str | None] = mapped_column(Text)


class StatIndicator(Base):
    __tablename__ = "stat_indicator"
    key: Mapped[str] = mapped_column(String(64), primary_key=True)
    name: Mapped[str] = mapped_column(Text)
    definition: Mapped[str | None] = mapped_column(Text)
    unit: Mapped[str] = mapped_column(String(32))
    population_group: Mapped[str | None] = mapped_column(Text)  # betroffene Bevölkerungsgruppe
    dataset_key: Mapped[str | None] = mapped_column(ForeignKey("stat_dataset.key", ondelete="SET NULL"))


class StatRelease(Base):
    """Ein importierter Datenstand (Datei) für einen Berichtszeitraum. Korrekturen => neue Revision."""

    __tablename__ = "stat_release"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    dataset_key: Mapped[str] = mapped_column(ForeignKey("stat_dataset.key", ondelete="CASCADE"), index=True)
    period_key: Mapped[str] = mapped_column(String(32))  # z. B. 2026-10 (Monat) oder 2025-12-31 (Stichtag)
    period_start: Mapped[date | None] = mapped_column(Date)
    period_end: Mapped[date] = mapped_column(Date)  # Stichtag bzw. Ende des Berichtszeitraums
    revision: Mapped[int] = mapped_column(Integer, default=1)
    is_current: Mapped[bool] = mapped_column(Boolean, default=True, server_default=text("true"))
    published_on: Mapped[date | None] = mapped_column(Date)  # None = unbekannt
    retrieved_at: Mapped[datetime] = mapped_column(TS, server_default=_now())
    file_url: Mapped[str | None] = mapped_column(Text)
    file_name: Mapped[str | None] = mapped_column(Text)
    file_sha256: Mapped[str] = mapped_column(String(64))
    stored_path: Mapped[str | None] = mapped_column(Text)  # aufbewahrte Quelldatei (relativ zu data_dir)
    gebietsstand: Mapped[date | None] = mapped_column(Date)
    import_method: Mapped[str] = mapped_column(String(16), default="auto")  # auto|manual
    row_count: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    notes: Mapped[str | None] = mapped_column(Text)
    dataset: Mapped[StatDataset] = relationship()
    __table_args__ = (
        UniqueConstraint("dataset_key", "period_key", "revision", name="uq_release_period_revision"),
        UniqueConstraint("dataset_key", "period_key", "file_sha256", name="uq_release_period_checksum"),
        Index("uq_release_current", "dataset_key", "period_key", unique=True, postgresql_where=text("is_current")),
    )


class StatValue(Base):
    """Einzelwert: Gebiet × Kennzahl × Berichtszeitraum (× Beruf/Altersgruppe), mit Fehlwertstatus."""

    __tablename__ = "stat_value"
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    release_id: Mapped[int] = mapped_column(ForeignKey("stat_release.id", ondelete="CASCADE"), index=True)
    indicator_key: Mapped[str] = mapped_column(ForeignKey("stat_indicator.key", ondelete="CASCADE"))
    region_level: Mapped[str] = mapped_column(String(12))  # country|state|district
    region_key: Mapped[str] = mapped_column(String(12))
    region_name: Mapped[str | None] = mapped_column(Text)  # Name laut Quelle (für Prüfzwecke)
    gebietsstand: Mapped[date | None] = mapped_column(Date)
    dim_key: Mapped[str] = mapped_column(String(64), default="", server_default="")  # z. B. Altersgruppe/KldB-Code
    dim_label: Mapped[str | None] = mapped_column(Text)
    classification_version: Mapped[str | None] = mapped_column(String(24))
    value: Mapped[Decimal | None] = mapped_column(Numeric(18, 4))
    value_status: Mapped[str] = mapped_column(String(16), default="ok")
    raw_value: Mapped[str | None] = mapped_column(Text)
    __table_args__ = (
        UniqueConstraint("release_id", "indicator_key", "region_level", "region_key", "dim_key", name="uq_stat_value"),
        CheckConstraint(_in("value_status", VALUE_STATUS), name="ck_stat_value_status"),
        Index("ix_stat_value_lookup", "indicator_key", "region_level", "region_key"),
    )


# ================================================================================================
# Aggregate, Jobs, Infrastruktur
# ================================================================================================
class DailyAggregate(Base):
    """Tägliches Aggregat je Kreis (reproduzierbar aus Historie neu berechenbar; mit Regelversionen)."""

    __tablename__ = "daily_aggregate"
    agg_date: Mapped[date] = mapped_column(Date, primary_key=True)
    region_key: Mapped[str] = mapped_column(String(16), primary_key=True)  # Kreis-AGS oder __DE__/__REMOTE__/…
    kind_group: Mapped[str] = mapped_column(String(16), primary_key=True)  # job|ausbildung|praktikum|all
    weighted_count: Mapped[Decimal] = mapped_column(Numeric(14, 4), default=0)
    distinct_count: Mapped[int] = mapped_column(Integer, default=0)
    first_seen_count: Mapped[int] = mapped_column(Integer, default=0)
    changed_count: Mapped[int] = mapped_column(Integer, default=0)
    left_count: Mapped[int] = mapped_column(Integer, default=0)
    observed_count: Mapped[int] = mapped_column(Integer, default=0)  # am Tag tatsächlich beobachtet
    basis: Mapped[dict[str, Any] | None] = mapped_column(JSONB)  # Quellen/Suchbereichsversionen/Laufstatus
    dedup_rule_version: Mapped[str] = mapped_column(String(32))
    classifier_version: Mapped[str] = mapped_column(String(32))
    geo_rule_version: Mapped[str] = mapped_column(String(32))
    aggregate_version: Mapped[str] = mapped_column(String(32))
    computed_at: Mapped[datetime] = mapped_column(TS, server_default=_now())


class Job(Base):
    """Persistente Jobverwaltung in PostgreSQL (Sperren via SKIP LOCKED, Wiederholungszähler, Checkpoints)."""

    __tablename__ = "job"
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    kind: Mapped[str] = mapped_column(String(32))
    payload: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    status: Mapped[str] = mapped_column(String(12), default="queued")
    priority: Mapped[int] = mapped_column(Integer, default=100)
    dedupe_key: Mapped[str | None] = mapped_column(String(160))
    lock_key: Mapped[str | None] = mapped_column(String(160))  # gegenseitiger Ausschluss (z. B. source:ba)
    run_after: Mapped[datetime] = mapped_column(TS, server_default=_now())
    attempts: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    max_attempts: Mapped[int] = mapped_column(Integer, default=3, server_default="3")
    locked_by: Mapped[str | None] = mapped_column(String(80))
    heartbeat_at: Mapped[datetime | None] = mapped_column(TS)
    checkpoint: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    result: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    last_error: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(TS, server_default=_now())
    started_at: Mapped[datetime | None] = mapped_column(TS)
    finished_at: Mapped[datetime | None] = mapped_column(TS)
    __table_args__ = (
        CheckConstraint(_in("status", JOB_STATUS), name="ck_job_status"),
        Index("ix_job_queue", "status", "priority", "run_after"),
        Index("uq_job_dedupe_open", "dedupe_key", unique=True, postgresql_where=text("status IN ('queued','running')")),
    )


class RobotsCache(Base):
    __tablename__ = "robots_cache"
    host: Mapped[str] = mapped_column(String(200), primary_key=True)
    fetched_at: Mapped[datetime] = mapped_column(TS)
    status_code: Mapped[int | None] = mapped_column(Integer)
    body: Mapped[str | None] = mapped_column(Text)


class FetchCache(Base):
    """HTTP-Cache-Metadaten (ETag/Last-Modified) – es werden keine Seiteninhalte archiviert."""

    __tablename__ = "fetch_cache"
    url_hash: Mapped[str] = mapped_column(String(64), primary_key=True)
    url: Mapped[str] = mapped_column(Text)
    etag: Mapped[str | None] = mapped_column(Text)
    last_modified: Mapped[str | None] = mapped_column(Text)
    fetched_at: Mapped[datetime] = mapped_column(TS)
    status_code: Mapped[int | None] = mapped_column(Integer)


class OpsWarning(Base):
    """Betriebswarnungen (veraltete Quelle, ungewöhnlich große Bestandsänderung, Blockade …)."""

    __tablename__ = "ops_warning"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    kind: Mapped[str] = mapped_column(String(32))
    dedupe_key: Mapped[str] = mapped_column(String(160))
    source_id: Mapped[int | None] = mapped_column(ForeignKey("source.id", ondelete="CASCADE"))
    message: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(TS, server_default=_now())
    resolved_at: Mapped[datetime | None] = mapped_column(TS)
    __table_args__ = (Index("uq_warning_open", "dedupe_key", unique=True, postgresql_where=text("resolved_at IS NULL")),)


class AppState(Base):
    """Kleine Schlüssel-Wert-Ablage (z. B. zuletzt geplanter Tageslauf, Importstände)."""

    __tablename__ = "app_state"
    key: Mapped[str] = mapped_column(String(80), primary_key=True)
    value: Mapped[dict[str, Any]] = mapped_column(JSONB)
    updated_at: Mapped[datetime] = mapped_column(TS, server_default=_now(), onupdate=_now())
