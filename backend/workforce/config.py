"""Zentrale Konfiguration (Umgebungsvariablen mit Präfix ``WF_``).

Alle Werte sind über ``.env`` / Docker-Compose-Umgebung änderbar. Secrets gehören nicht ins Repository.
"""
from __future__ import annotations

from datetime import time
from functools import lru_cache
from pathlib import Path
from zoneinfo import ZoneInfo

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="WF_", env_file=".env", extra="ignore")

    env: str = "production"  # production | development | test
    database_url: str = "postgresql+psycopg://workforce:workforce@db:5432/workforce"
    data_dir: Path = Path("/data")
    static_dir: Path = Path("/app/static")

    # --- Zeitplan -----------------------------------------------------------------
    timezone: str = "Europe/Berlin"
    scan_time: str = "03:15"  # lokale Uhrzeit des Tageslaufs
    scheduler_tick_seconds: int = 30
    stats_check_time: str = "05:30"  # lokale Uhrzeit der Prüfung auf neue Statistikveröffentlichungen

    # --- Crawler-Höflichkeit ------------------------------------------------------
    crawler_name: str = "WorkForceBot"
    crawler_version: str = "0.1"
    # Kontaktangabe des Betreibers (URL oder E-Mail). Ohne Kontakt werden keine Scans gestartet.
    crawler_contact: str = ""
    http_timeout_seconds: float = 30.0
    http_max_retries: int = 3
    http_backoff_base_seconds: float = 4.0
    http_backoff_max_seconds: float = 120.0
    retry_after_max_seconds: int = 600  # längeres Retry-After => Lauf wird als blockiert beendet
    default_request_interval_seconds: float = 3.0
    robots_cache_hours: int = 24
    detail_recheck_days: int = 7
    max_response_bytes: int = 15_000_000

    # --- Amtliche Statistik -------------------------------------------------------
    # Automatischer Abruf von statistik.arbeitsagentur.de nur nach ausdrücklicher Betreiberentscheidung:
    # Die allgemeinen Nutzungsbedingungen der BA (Nr. 2a (3)) untersagen „Robots, Webspider oder ähnliche
    # Technologien“; die Statistikdateien selbst dürfen mit Quellenangabe gespeichert und genutzt werden.
    # Ohne diese Freigabe werden BA-Dateien manuell heruntergeladen und über Oberfläche/CLI importiert.
    stats_ba_auto: bool = False
    stats_request_interval_seconds: float = 10.0
    stats_max_download_bytes: int = 400_000_000
    stats_keep_source_files: bool = True

    # --- Fachliche Regeln ---------------------------------------------------------
    missing_scans_threshold: int = 3  # vollständige vergleichbare Scans bis „vermutlich entfernt“
    stale_after_days: int = 14  # ohne vergleichbaren Scan => „unbekannt/veraltet“
    gone_confirmations: int = 2  # bestätigte echte Nichtverfügbarkeit (404/410) an verschiedenen Tagen

    # --- Betrieb ------------------------------------------------------------------
    worker_concurrency: int = 2
    job_heartbeat_seconds: int = 30
    job_stale_after_seconds: int = 600
    technical_log_retention_days: int = 90
    stale_source_warn_hours: int = 36
    stock_change_warn_percent: float = 30.0
    small_count_threshold: int = 5  # „geringe Fallzahl“ in Karte/Tabellen

    # --- Web ----------------------------------------------------------------------
    session_hours: int = 12
    cookie_secure: bool = True  # hinter TLS-Reverse-Proxy; für lokalen HTTP-Test auf false setzen
    login_max_failures: int = 8
    login_lock_minutes: int = 15
    allow_demo_data: bool = False  # synthetische Daten nur ausdrücklich und nie automatisch

    log_level: str = "INFO"
    log_json: bool = True

    @field_validator("scan_time", "stats_check_time")
    @classmethod
    def _valid_time(cls, v: str) -> str:
        time.fromisoformat(v)
        return v

    @property
    def tz(self) -> ZoneInfo:
        return ZoneInfo(self.timezone)

    @property
    def scan_time_local(self) -> time:
        return time.fromisoformat(self.scan_time)

    @property
    def stats_check_time_local(self) -> time:
        return time.fromisoformat(self.stats_check_time)

    @property
    def user_agent(self) -> str:
        contact = self.crawler_contact.strip()
        suffix = f"; +{contact}" if contact else ""
        return f"{self.crawler_name}/{self.crawler_version} (selbst gehostete Arbeitsmarktbeobachtung{suffix})"

    @property
    def downloads_dir(self) -> Path:
        return self.data_dir / "downloads"

    @property
    def exports_dir(self) -> Path:
        return self.data_dir / "exports"

    @property
    def is_test(self) -> bool:
        return self.env == "test"


@lru_cache
def get_settings() -> Settings:
    return Settings()


VERSION = "0.1.0"
# Regel-/Logikversionen – werden an Versionen, Zusammenführungen und Aggregaten gespeichert.
DEDUP_RULE_VERSION = "dedup-1"
CLASSIFIER_VERSION = "klass-1"
GEO_RULE_VERSION = "geo-1"
AGGREGATE_VERSION = "agg-1"

_ = Field  # re-export guard for linters
