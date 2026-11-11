"""Öffentliche Schnittstelle der Statistik-Importe: beschreiben, Stammdaten anlegen, automatisch abrufen, Datei importieren.

* :func:`describe` – Übersicht je Datensatz (Auffindungsweg, automatischer Abruf aktiv?, letzter Datenstand).
* :func:`seed_reference` – legt Datensätze und Kennzahlen an (idempotent).
* :func:`run_imports` – sucht auf den offiziellen Seiten nach der neuesten Datei, lädt sie höflich und importiert
  sie, wenn sie neu ist. Ein Fehler bei einem Datensatz hält die übrigen nicht auf.
* :func:`import_file` – geprüfter Import einer lokalen Datei (manueller Ausweichweg und Kern von ``run_imports``).
"""
from __future__ import annotations

import logging
import sqlite3
import tempfile
import zipfile
from collections.abc import Callable
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

from sqlalchemy import select
from sqlalchemy import text as sql
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import Session

from ..config import Settings, get_settings
from ..crawl.fetcher import BlockedError, Fetcher, FetchError, RobotsDisallowed, RobotsStore
from ..db import session_scope
from ..geo import vg250
from ..models import AppState, RobotsCache, StatDataset, StatIndicator, StatRelease
from . import ba_berufe, ba_kreise, bevoelkerung, discovery, genesis_ui, gv_isys, kldb
from .catalog import DATASET_BY_KEY, DATASETS, INDICATORS, Dataset
from .common import (
    FileContext,
    ImportProblem,
    ParsedRelease,
    current_release,
    known_region_keys,
    safe_name,
    sha256_file,
    store_release,
    summarize,
    unknown_region_keys,
)

log = logging.getLogger(__name__)

__all__ = ["ImportProblem", "describe", "import_file", "run_imports", "seed_reference"]

# Reihenfolge der automatischen Abrufe: erst Gebietsstand, dann Ortsreferenz und Klassifikation, dann Statistik.
ORDER = ("vg250", "gv_isys", "kldb2010", "ba_arbeitslose_kreise", "ba_berufe", "bevoelkerung_kreise_alter")
STATE_PREFIX = "stats_import:"
HOST_STATE_PREFIX = "host:"
# statistik.arbeitsagentur.de sperrte bei der Erkundung nach 5–6 Abrufen binnen weniger Minuten für 20–30 Minuten:
# deshalb größerer Abstand, je Lauf nur „eine Seite + eine Datei“ je Produkt und nach einer Sperre eine feste Pause.
BA_MIN_INTERVAL_SECONDS = 30.0
BLOCK_PAUSE = timedelta(minutes=30)


# --------------------------------------------------------------------------------------------------------
# Stammdaten und Übersicht
# --------------------------------------------------------------------------------------------------------
def _ba_disabled_reason(spec: Dataset) -> str:
    return ("Der automatische Abruf von statistik.arbeitsagentur.de ist durch WF_STATS_BA_AUTO=false deaktiviert. Die Datei "
            f"kann von Hand unter {spec.landing_url} heruntergeladen und über die Oberfläche (Statistik → Datei "
            f"importieren) oder die Kommandozeile (workforce stats import {spec.key} --file <Datei>) importiert werden. "
            "Mit WF_STATS_BA_AUTO=true lässt sich der automatische Abruf nach eigener Prüfung freigeben.")


def _auto_status(spec: Dataset, settings: Settings) -> tuple[bool, str | None]:
    if spec.ba_host and not settings.stats_ba_auto:
        return False, _ba_disabled_reason(spec)
    if not settings.crawler_contact.strip() and not settings.is_test:
        return False, ("WF_CRAWLER_CONTACT ist nicht gesetzt – ohne Kontaktangabe im User-Agent erfolgt kein automatischer "
                       f"Abruf. Manueller Import: Datei von {spec.landing_url} laden und importieren.")
    return True, None


def seed_reference(db: Session) -> None:
    """Legt Datensätze und Kennzahlen an bzw. aktualisiert ihre Beschreibung (idempotent, ohne Commit)."""
    year = db.execute(sql("SELECT extract(year FROM max(retrieved_at))::int FROM stat_release WHERE dataset_key = 'vg250'")).scalar()
    for d in DATASETS:
        row = {"key": d.key, "name": d.name, "publisher": d.publisher, "dataset_code": d.dataset_code,
               "landing_url": d.landing_url, "licence": d.licence, "licence_url": d.licence_url,
               "attribution": d.attribution.replace("{jahr}", str(year) if year else "Jahr des letzten Datenbezugs"),
               "update_cycle": d.update_cycle, "notes": d.notes}
        db.execute(pg_insert(StatDataset).values(**row).on_conflict_do_update(
            index_elements=["key"], set_={k: v for k, v in row.items() if k != "key"}))
    for i in INDICATORS:
        row = {"key": i.key, "name": i.name, "definition": i.definition, "unit": i.unit,
               "population_group": i.population_group, "dataset_key": i.dataset_key}
        db.execute(pg_insert(StatIndicator).values(**row).on_conflict_do_update(
            index_elements=["key"], set_={k: v for k, v in row.items() if k != "key"}))
    db.flush()


def describe() -> list[dict]:
    """Je Datensatz: Schlüssel, Name, Herausgeber, Auffindungsweg, automatischer Abruf aktiv?, letzter Datenstand."""
    settings = get_settings()
    out: list[dict] = []
    with session_scope() as db:
        states = {s.key: s for s in db.execute(select(AppState).where(AppState.key.like(f"{STATE_PREFIX}%"))).scalars()}
        for key in ORDER:
            spec = DATASET_BY_KEY[key]
            enabled, reason = _auto_status(spec, settings)
            rel = db.execute(select(StatRelease).where(StatRelease.dataset_key == key, StatRelease.is_current)
                             .order_by(StatRelease.period_end.desc(), StatRelease.retrieved_at.desc()).limit(1)).scalar_one_or_none()
            state = states.get(STATE_PREFIX + key)
            out.append({
                "key": key, "name": spec.name, "publisher": spec.publisher, "landing_url": spec.landing_url,
                "update_cycle": spec.update_cycle, "discovery": spec.discovery, "auto_enabled": enabled,
                "auto_disabled_reason": reason, "manual_file": spec.file_hint, "licence": spec.licence,
                "licence_url": spec.licence_url,
                "last_release": None if rel is None else {
                    "period_key": rel.period_key, "period_end": rel.period_end, "revision": rel.revision,
                    "retrieved_at": rel.retrieved_at, "published_on": rel.published_on, "gebietsstand": rel.gebietsstand,
                    "import_method": rel.import_method, "file_name": rel.file_name},
                "last_check": (state.value if state else None),
            })
    return _jsonable(out)


# --------------------------------------------------------------------------------------------------------
# Dateiimport
# --------------------------------------------------------------------------------------------------------
def _store_statistics(db: Session, dataset_key: str, releases: list[ParsedRelease], ctx: FileContext,
                      info: dict[str, Any], warnings: list[str]) -> dict[str, Any]:
    results = [store_release(db, dataset_key, r, ctx) for r in releases]
    values = [v for r in releases for v in r.values]
    unknown = unknown_region_keys(db, values)
    out = summarize(dataset_key, ctx, results, unknown_region_keys=unknown, **info)
    out["warnings"] = list(warnings)
    if unknown:
        out["warnings"].append(
            f"{len(unknown)} Gebietsschlüssel der Datei fehlen im geladenen Gebietsstand (z. B. nach einer Gebietsreform): "
            f"{', '.join(unknown[:10])}{' …' if len(unknown) > 10 else ''}. Die Werte wurden unverändert importiert.")
    elif not any(known_region_keys(db).values()):
        out["warnings"].append("Der Gebietsstand (VG250) ist noch nicht geladen – Gebietsschlüssel wurden nicht gegengeprüft.")
    return out


def _import_ba_kreise(db: Session, ctx: FileContext) -> dict[str, Any]:
    release, info, warnings = ba_kreise.parse(ctx.path, ctx.name)
    return _store_statistics(db, ba_kreise.DATASET_KEY, [release], ctx, info, warnings)


def _import_ba_berufe(db: Session, ctx: FileContext) -> dict[str, Any]:
    release, info, warnings = ba_berufe.parse(ctx.path, ctx.name)
    out = _store_statistics(db, ba_berufe.DATASET_KEY, [release], ctx, info, warnings)
    known = set(db.execute(sql("SELECT code FROM kldb_class")).scalars().all())
    if known:
        codes = {v.dim_key for v in release.values if v.dim_key}
        unknown = sorted(codes - known)
        out["unknown_kldb_codes"] = unknown[:50]
        if unknown:
            out["warnings"].append(f"{len(unknown)} Berufsschlüssel der Datei fehlen in der geladenen KldB-Systematik.")
    return out


def _import_population(db: Session, ctx: FileContext) -> dict[str, Any]:
    releases, info, warnings = bevoelkerung.parse(ctx.path, ctx.name)
    return _store_statistics(db, bevoelkerung.DATASET_KEY, releases, ctx, info, warnings)


def _import_gv(db: Session, ctx: FileContext) -> dict[str, Any]:
    return gv_isys.apply(db, gv_isys.parse(ctx.path, ctx.name), ctx)


def _import_kldb(db: Session, ctx: FileContext) -> dict[str, Any]:
    return kldb.apply(db, kldb.parse(ctx.path, ctx.name), ctx)


IMPORTERS: dict[str, Callable[[Session, FileContext], dict[str, Any]]] = {
    "vg250": vg250.import_vg250,
    "gv_isys": _import_gv,
    "kldb2010": _import_kldb,
    "ba_arbeitslose_kreise": _import_ba_kreise,
    "ba_berufe": _import_ba_berufe,
    "bevoelkerung_kreise_alter": _import_population,
}


def import_file(dataset_key: str, path: Path, *, method: str = "manual", original_name: str | None = None,
                file_url: str | None = None) -> dict:
    """Geprüfter Import einer lokalen Datei. Bei jedem Prüfproblem: :class:`ImportProblem`, nichts wird geschrieben."""
    return _import(dataset_key, Path(path), method=method, original_name=original_name, file_url=file_url)


def _import(dataset_key: str, path: Path, *, method: str, original_name: str | None, file_url: str | None,
            published_on: date | None = None) -> dict:
    spec = DATASET_BY_KEY.get(dataset_key)
    if spec is None:
        raise ImportProblem(f"Unbekannter Datensatz {dataset_key!r}. Bekannt sind: {', '.join(ORDER)}.")
    if not path.is_file():
        raise ImportProblem(f"Datei nicht gefunden: {path}")
    if path.stat().st_size == 0:
        raise ImportProblem("Die Datei ist leer.")
    settings = get_settings()
    ctx = FileContext(path=path, name=safe_name(original_name or path.name), sha256=sha256_file(path), method=method,
                      file_url=file_url, settings=settings, now=datetime.now(UTC), published_on=published_on)
    try:
        with session_scope() as db:
            seed_reference(db)
            result = IMPORTERS[dataset_key](db, ctx)
            if dataset_key == "vg250" and result.get("status") == "imported":
                seed_reference(db)  # Jahr des letzten Datenbezugs im Quellenvermerk nachführen
    except ImportProblem:
        raise
    except (zipfile.BadZipFile, sqlite3.Error, UnicodeDecodeError, IndexError, KeyError, TypeError, ValueError, EOFError) as exc:
        log.exception("Statistikdatei nicht lesbar", extra={"dataset": dataset_key, "file": ctx.name})
        raise ImportProblem(f"Die Datei hat nicht das für „{spec.name}“ erwartete Format und wurde nicht importiert "
                            f"({type(exc).__name__}: {exc}). Erwartet wird: {spec.file_hint}.") from exc
    log.info("Statistikimport", extra={"dataset": dataset_key, "status": result.get("status"), "period": result.get("period_key"),
                                       "rows": result.get("rows")})
    return _jsonable(result)


# --------------------------------------------------------------------------------------------------------
# Automatischer Abruf
# --------------------------------------------------------------------------------------------------------
def make_fetcher(spec: Dataset, settings: Settings, robots: RobotsStore) -> Fetcher:
    """Höflicher Abruf für genau einen Datensatz (nur dessen offizielle Hosts). In Tests ersetzbar.

    Bei HTTP 429 wird nicht mehrfach nachgefasst: Die Statistikseiten sperren minutenlang; der nächste geplante
    Lauf versucht es erneut.
    """
    polite = settings.model_copy(update={"http_max_retries": 0 if spec.ba_host else 1,
                                         "http_backoff_base_seconds": max(20.0, settings.http_backoff_base_seconds)})
    interval = float(settings.stats_request_interval_seconds)
    if spec.ba_host:
        interval = max(interval, BA_MIN_INTERVAL_SECONDS)
    return Fetcher(spec.hosts, interval_seconds=interval, settings=polite, robots_store=robots)


def robots_store() -> RobotsStore:
    """robots.txt-Zwischenspeicher über Läufe hinweg (Tabelle ``robots_cache``) – spart je Lauf einen Abruf pro Host.

    Nicht verfügbare robots.txt (5xx, 429, kein Abruf möglich) wird nicht dauerhaft gespeichert, damit eine
    vorübergehende Störung nicht einen ganzen Tag lang als „alles gesperrt“ nachwirkt.
    """
    def load(host: str) -> tuple[datetime, int | None, str | None] | None:
        with session_scope() as db:
            row = db.get(RobotsCache, host)
            return (row.fetched_at, row.status_code, row.body) if row else None

    def save(host: str, at: datetime, status: int | None, body: str | None) -> None:
        if status is None or status == 429 or status >= 500:
            return
        with session_scope() as db:
            db.execute(pg_insert(RobotsCache).values(host=host, fetched_at=at, status_code=status, body=body).on_conflict_do_update(
                index_elements=["host"], set_={"fetched_at": at, "status_code": status, "body": body}))

    return RobotsStore(load, save)


def _state_get(key: str) -> dict[str, Any]:
    with session_scope() as db:
        row = db.get(AppState, STATE_PREFIX + key)
        return dict(row.value) if row else {}


def _state_put(key: str, value: dict[str, Any]) -> None:
    with session_scope() as db:
        stmt = pg_insert(AppState).values(key=STATE_PREFIX + key, value=_jsonable(value))
        db.execute(stmt.on_conflict_do_update(index_elements=["key"], set_={"value": stmt.excluded.value, "updated_at": sql("now()")}))


def _page(fetcher: Fetcher, url: str, what: str) -> str:
    res = fetcher.get(url)
    if res.status != 200:
        raise ImportProblem(f"{what}: Die Seite {url} antwortet mit HTTP {res.status}.")
    return res.text


def _has_release_for_url(dataset_key: str, url: str) -> bool:
    with session_scope() as db:
        return db.execute(select(StatRelease.id).where(StatRelease.dataset_key == dataset_key, StatRelease.file_url == url).limit(1)).first() is not None


def _fetch_and_import(spec: Dataset, cand: discovery.Candidate, fetcher: Fetcher, settings: Settings, state: dict[str, Any],
                      beat: Callable[[], None]) -> dict[str, Any]:
    """Lädt eine gefundene Datei (bedingt, falls genau diese URL schon importiert ist) und importiert sie."""
    files = state.setdefault("files", {})
    known = files.get(cand.slot) or {}
    conditional = known.get("url") == cand.url and _has_release_for_url(spec.key, cand.url)
    with tempfile.TemporaryDirectory(prefix="wf-stats-") as tmp:
        dest = Path(tmp) / safe_name(cand.name)
        beat()
        res = fetcher.download(cand.url, dest, settings.stats_max_download_bytes,
                               if_none_match=known.get("etag") if conditional else None,
                               if_modified_since=known.get("last_modified") if conditional else None)
        beat()
        if res.not_modified:
            return {"dataset": spec.key, "status": "unchanged", "file_url": cand.url, "file_name": cand.name,
                    "message": "Die Datei auf dem Server ist seit dem letzten Import unverändert (HTTP 304).",
                    "page_period_hint": cand.period_hint}
        if res.status != 200:
            raise ImportProblem(f"{spec.name}: Der Download {cand.url} antwortet mit HTTP {res.status}.")
        result = _import(spec.key, dest, method="auto", original_name=cand.name, file_url=cand.url, published_on=cand.published_on)
    files[cand.slot] = {"url": cand.url, "etag": res.headers.get("etag"), "last_modified": res.headers.get("last-modified")}
    result["file_url"] = cand.url
    result["page_period_hint"] = cand.period_hint
    return result


def _combine(spec: Dataset, results: list[dict[str, Any]]) -> dict[str, Any]:
    if len(results) == 1:
        return results[0]
    return {"dataset": spec.key, "status": "imported" if any(r.get("status") == "imported" for r in results) else "unchanged",
            "files": results, "warnings": [w for r in results for w in r.get("warnings", [])]}


def _auto_files(spec: Dataset, settings: Settings, robots: RobotsStore, state: dict[str, Any], beat: Callable[[], None]) -> dict[str, Any]:
    fetcher = make_fetcher(spec, settings, robots)
    try:
        if spec.key == "ba_arbeitslose_kreise":
            cands = [discovery.ba_kreise(_page(fetcher, spec.landing_url, spec.name), spec.landing_url)]
        elif spec.key == "ba_berufe":
            cands = [discovery.ba_berufe(_page(fetcher, spec.landing_url, spec.name), spec.landing_url)]
        elif spec.key == "vg250":
            cands = [discovery.vg250(_page(fetcher, spec.landing_url, spec.name), spec.landing_url)]
        elif spec.key == "kldb2010":
            cands = discovery.kldb(_page(fetcher, spec.landing_url, spec.name), spec.landing_url)
        elif spec.key == "gv_isys":
            pub_url, stand = discovery.gv_isys_publication_page(_page(fetcher, spec.landing_url, spec.name), spec.landing_url)
            beat()
            cands = [discovery.gv_isys_file(_page(fetcher, pub_url, spec.name), pub_url, stand)]
        else:  # pragma: no cover
            raise ImportProblem(f"Für {spec.key} ist kein automatischer Abruf eingerichtet.")
        return _combine(spec, [_fetch_and_import(spec, c, fetcher, settings, state, beat) for c in cands])
    finally:
        fetcher.close()


def _auto_population(spec: Dataset, settings: Settings, robots: RobotsStore, state: dict[str, Any], beat: Callable[[], None]) -> dict[str, Any]:
    """Bevölkerung: erst GENESIS-Online, bei Störung die Regionaldatenbank (gleiche Oberfläche, andere Tabelle)."""
    problems: list[str] = []
    fetcher = make_fetcher(spec, settings, robots)
    try:
        for source in genesis_ui.SOURCES:
            try:
                with tempfile.TemporaryDirectory(prefix="wf-stats-") as tmp:
                    path, name = genesis_ui.export_flat_csv(source, Path(tmp), settings, fetcher, beat)
                    if problems:
                        # Ausweichquelle nur übernehmen, wenn sie einen Stichtag liefert, der noch fehlt
                        releases, _, _ = bevoelkerung.parse(path, name)
                        with session_scope() as db:
                            missing = [r.period_key for r in releases if current_release(db, spec.key, r.period_key) is None]
                        if not missing:
                            return {"dataset": spec.key, "status": "unchanged", "source": source.key,
                                    "message": "Die Ausweichquelle liefert keinen neueren Stichtag als bereits importiert.",
                                    "warnings": [f"Hauptquelle nicht nutzbar: {'; '.join(problems)}"]}
                    result = _import(spec.key, path, method="auto", original_name=name, file_url=source.table_url)
                result["source"] = source.key
                result["file_url"] = source.table_url
                if problems:
                    result.setdefault("warnings", []).append(
                        f"Hauptquelle nicht nutzbar ({'; '.join(problems)}); Daten stammen aus der Ausweichquelle {source.name}.")
                return result
            except (ImportProblem, FetchError) as exc:
                problems.append(f"{source.name}: {exc}")
                log.warning("Bevölkerungsabruf fehlgeschlagen", extra={"source": source.key, "error": str(exc)})
                beat()
    finally:
        fetcher.close()
    raise ImportProblem("Bevölkerungstabelle konnte nicht abgerufen werden – " + " | ".join(problems))


def _host_block(spec: Dataset, now: datetime) -> tuple[str, datetime] | None:
    """Läuft für einen Host des Datensatzes noch die Pause nach einer Sperre?"""
    for host in spec.hosts:
        until = _state_get(HOST_STATE_PREFIX + host).get("blocked_until")
        try:
            if until and datetime.fromisoformat(until) > now:
                return host, datetime.fromisoformat(until)
        except ValueError:
            continue
    return None


def _run_dataset(spec: Dataset, settings: Settings, robots: RobotsStore, scheduled: bool, beat: Callable[[], None]) -> dict[str, Any]:
    enabled, reason = _auto_status(spec, settings)
    if not enabled:
        return {"dataset": spec.key, "status": "skipped", "reason": reason, "landing_url": spec.landing_url}
    state = _state_get(spec.key)
    now = datetime.now(UTC)
    block = _host_block(spec, now)
    if block is not None:
        local = block[1].astimezone(settings.tz)
        return {"dataset": spec.key, "status": "skipped", "landing_url": spec.landing_url,
                "reason": (f"{block[0]} hat zuletzt einen Abruf abgelehnt; bis {local:%d.%m.%Y %H:%M} Uhr wird dieser Host nicht erneut "
                           "angefragt. Die Datei kann in der Zwischenzeit von Hand geladen und importiert werden.")}
    last = state.get("last_success_at")
    if scheduled and spec.min_check_days > 1 and last:
        try:
            due = datetime.fromisoformat(last) + timedelta(days=spec.min_check_days)
        except ValueError:
            due = now
        if now < due:
            return {"dataset": spec.key, "status": "skipped",
                    "reason": (f"Zuletzt am {datetime.fromisoformat(last):%d.%m.%Y} geprüft; dieser Datensatz wird höchstens alle "
                               f"{spec.min_check_days} Tage automatisch geprüft (nächste Prüfung ab {due:%d.%m.%Y}).")}
    state["last_check_at"] = now.isoformat()
    try:
        if spec.key == "bevoelkerung_kreise_alter":
            result = _auto_population(spec, settings, robots, state, beat)
        else:
            result = _auto_files(spec, settings, robots, state, beat)
        state["last_success_at"] = now.isoformat()
        state["last_status"] = result.get("status")
        state.pop("last_error", None)
        return result
    except RobotsDisallowed as exc:
        state["last_status"], state["last_error"] = "blocked", str(exc)
        return {"dataset": spec.key, "status": "blocked", "error": f"robots.txt erlaubt den Abruf nicht: {exc.url}",
                "landing_url": spec.landing_url}
    except BlockedError as exc:
        state["last_status"], state["last_error"] = "blocked", str(exc)
        host = urlsplit(exc.url or spec.landing_url).hostname or spec.hosts[0]
        until = now + BLOCK_PAUSE
        _state_put(HOST_STATE_PREFIX + host, {"blocked_until": until.isoformat(), "reason": str(exc), "dataset": spec.key})
        return {"dataset": spec.key, "status": "blocked", "landing_url": spec.landing_url,
                "error": (f"Der Server hat den Abruf abgelehnt ({exc}); es wird nicht weiter nachgefasst und {host} für "
                          f"{int(BLOCK_PAUSE.total_seconds() // 60)} Minuten nicht mehr angefragt. Der nächste geplante Lauf "
                          "versucht es erneut; alternativ die Datei von Hand laden und importieren.")}
    except (ImportProblem, FetchError) as exc:
        state["last_status"], state["last_error"] = "failed", str(exc)
        return {"dataset": spec.key, "status": "failed", "error": str(exc), "landing_url": spec.landing_url}
    finally:
        try:
            _state_put(spec.key, state)
        except Exception:  # der Prüfvermerk darf den Lauf nicht abbrechen
            log.exception("Prüfvermerk konnte nicht gespeichert werden", extra={"dataset": spec.key})


def run_imports(dataset_keys: list[str] | None = None, heartbeat: Callable[[], None] | None = None) -> dict:
    """Prüft die offiziellen Seiten auf neue Dateien und importiert sie. Ergebnis je Datensatz (auch ``skipped`` mit Grund)."""
    settings = get_settings()
    beat = heartbeat or (lambda: None)
    scheduled = not dataset_keys
    keys = list(ORDER) if scheduled else [k for k in ORDER if k in dataset_keys] + [k for k in dataset_keys if k not in ORDER]
    robots = robots_store()
    results: dict[str, Any] = {}
    for key in keys:
        beat()
        spec = DATASET_BY_KEY.get(key)
        if spec is None:
            results[key] = {"dataset": key, "status": "failed", "error": f"Unbekannter Datensatz. Bekannt sind: {', '.join(ORDER)}."}
            continue
        try:
            results[key] = _run_dataset(spec, settings, robots, scheduled, beat)
        except Exception as exc:  # ein Datensatz darf die übrigen nicht aufhalten
            log.exception("Statistikabruf fehlgeschlagen", extra={"dataset": key})
            results[key] = {"dataset": key, "status": "failed", "error": f"Unerwarteter Fehler: {type(exc).__name__}: {exc}"}
        log.info("Statistikabruf", extra={"dataset": key, "status": results[key].get("status")})
    beat()
    return _jsonable(results)


def _jsonable(obj: Any) -> Any:
    """Macht Ergebnisse JSON-tauglich (Job-Ergebnis, Audit-Log): Datum → ISO-Text, Decimal → Zahl."""
    if isinstance(obj, dict):
        return {str(k): _jsonable(v) for k, v in obj.items()}
    if isinstance(obj, list | tuple | set | frozenset):
        return [_jsonable(v) for v in (sorted(obj) if isinstance(obj, set | frozenset) else obj)]
    if isinstance(obj, datetime | date):
        return obj.isoformat()
    if isinstance(obj, Decimal):
        return int(obj) if obj == obj.to_integral_value() else float(obj)
    if isinstance(obj, Path):
        return str(obj)
    return obj
