"""Gemeinsame Bausteine der Statistik-Importer: Fehlwertbehandlung, Datenstände/Revisionen, Dateiablage."""
from __future__ import annotations

import hashlib
import logging
import re
import shutil
import zipfile
from collections import Counter
from collections.abc import Iterable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any

from sqlalchemy import func, insert, select, update
from sqlalchemy import text as sql
from sqlalchemy.orm import Session

from ..config import Settings
from ..models import StatRelease, StatValue

log = logging.getLogger(__name__)

KLDB_VERSION = "KldB 2010/2020"
COUNTRY_KEY = "DE"

MONTHS = {
    "januar": 1, "februar": 2, "märz": 3, "maerz": 3, "april": 4, "mai": 5, "juni": 6, "juli": 7, "august": 8,
    "september": 9, "oktober": 10, "november": 11, "dezember": 12,
}
MONTH_NAMES = ["Januar", "Februar", "März", "April", "Mai", "Juni", "Juli", "August", "September", "Oktober",
               "November", "Dezember"]

# Amtliche Ländernamen → zweistelliger Länderschlüssel
STATE_KEYS = {
    "Schleswig-Holstein": "01", "Hamburg": "02", "Niedersachsen": "03", "Bremen": "04", "Nordrhein-Westfalen": "05",
    "Hessen": "06", "Rheinland-Pfalz": "07", "Baden-Württemberg": "08", "Bayern": "09", "Saarland": "10",
    "Berlin": "11", "Brandenburg": "12", "Mecklenburg-Vorpommern": "13", "Sachsen": "14", "Sachsen-Anhalt": "15",
    "Thüringen": "16",
}

# Zeichenerklärungen der Herausgeber → value_status. „zero“ nur für Zeichen, die ausdrücklich „nichts vorhanden“
# bedeuten; alle anderen Zeichen ergeben value = NULL.
MARKERS_BA: dict[str, str] = {
    "*": "suppressed",       # anonymisiert (Zahlenwerte 1 oder 2 bzw. daraus errechenbare Werte)
    "x": "not_available",    # „nicht sinnvoll“ bzw. Quote wird nicht veröffentlicht
    "X": "not_available",
    "...": "not_available",  # Angabe fällt später an
    "…": "not_available",
    ".": "suppressed",       # Zahlenwert unbekannt oder geheim zu halten
    "-": "zero",             # nichts vorhanden
    "–": "zero",
}
MARKERS_DESTATIS: dict[str, str] = {
    "-": "zero",             # nichts vorhanden, genau Null
    "–": "zero",
    ".": "suppressed",       # Zahlenwert unbekannt oder geheim zu halten
    "/": "unknown",          # keine Angabe, da Zahlenwert nicht sicher genug
    "...": "not_available",  # Angabe fällt später an
    "…": "not_available",
    "x": "not_available",    # Tabellenfach gesperrt, weil Aussage nicht sinnvoll
    "X": "not_available",
}


class ImportProblem(Exception):
    """Prüf- oder Auffindungsproblem mit einer klaren deutschen Meldung; es wurde nichts geschrieben."""


# --------------------------------------------------------------------------------------------------------
# Werte
# --------------------------------------------------------------------------------------------------------
@dataclass(slots=True)
class ValueRow:
    indicator_key: str
    region_level: str
    region_key: str
    region_name: str | None
    value: Decimal | None
    value_status: str
    raw_value: str | None
    dim_key: str = ""
    dim_label: str | None = None
    classification_version: str | None = None


_NUM_DE = re.compile(r"^[+-]?\d{1,3}(\.\d{3})*(,\d+)?$|^[+-]?\d+(,\d+)?$")
_NUM_EN = re.compile(r"^[+-]?\d+(\.\d+)?$")


def _number_from_text(s: str) -> Decimal | None:
    if _NUM_EN.match(s):
        return Decimal(s)
    if _NUM_DE.match(s):
        return Decimal(s.replace(".", "").replace(",", "."))
    return None


def classify_cell(cell: Any, markers: dict[str, str], unrecognized: Counter[str] | None = None) -> tuple[Decimal | None, str, str | None]:
    """Übersetzt eine Quellzelle in ``(value, value_status, raw_value)``.

    * Zahl ≠ 0 → ``ok``; Zahl = 0 → ``zero`` (echter Nullwert).
    * Zeichen laut Zeichenerklärung → Status aus ``markers``; ``value`` nur bei ``zero`` (= 0), sonst ``None``.
    * Leere Zelle → ``unknown`` (ohne Wert). Unbekannter Text → ``unknown``; er wird in ``unrecognized`` gezählt,
      damit der Aufrufer bei gehäuftem Auftreten abbrechen kann.
    """
    if cell is None:
        return None, "unknown", None
    if isinstance(cell, bool):
        raise ImportProblem(f"Unerwarteter Wahrheitswert in einer Wertzelle: {cell!r}")
    if isinstance(cell, int | float | Decimal):
        try:
            num = cell if isinstance(cell, Decimal) else Decimal(repr(cell) if isinstance(cell, float) else str(cell))
        except InvalidOperation as exc:
            raise ImportProblem(f"Nicht lesbarer Zahlenwert: {cell!r}") from exc
        if not num.is_finite():
            return None, "unknown", str(cell)
        return (num, "zero" if num == 0 else "ok", str(cell))
    raw = str(cell)
    s = raw.strip()
    if s == "":
        return None, "unknown", raw
    status = markers.get(s)
    if status is not None:
        return (Decimal(0) if status == "zero" else None), status, raw
    num = _number_from_text(s)
    if num is not None:
        return num, ("zero" if num == 0 else "ok"), raw
    if unrecognized is not None:
        unrecognized[s] += 1
    return None, "unknown", raw


def check_unrecognized(unrecognized: Counter[str], total: int, what: str) -> list[str]:
    """Viele unbekannte Zeichen deuten auf ein geändertes Dateiformat → Abbruch. Einzelne werden gemeldet."""
    n = sum(unrecognized.values())
    if n and n > max(5, total * 0.02):
        sample = ", ".join(repr(k) for k, _ in unrecognized.most_common(5))
        raise ImportProblem(f"{what}: {n} von {total} Wertzellen enthalten unbekannte Zeichen ({sample}). "
                            "Das Dateiformat hat sich vermutlich geändert; es wurde nichts importiert.")
    if n:
        return [f"{what}: {n} Wertzelle(n) mit unbekanntem Zeichen als „unbekannt“ gespeichert: "
                + ", ".join(f"{k!r}×{v}" for k, v in unrecognized.most_common(5))]
    return []


# --------------------------------------------------------------------------------------------------------
# Datum/Zeitraum
# --------------------------------------------------------------------------------------------------------
def month_bounds(year: int, month: int) -> tuple[date, date]:
    start = date(year, month, 1)
    nxt = date(year + (month == 12), month % 12 + 1, 1)
    return start, nxt - timedelta(days=1)


def as_date(value: Any) -> date | None:
    """Excel-Datumszelle oder Text ``TT.MM.JJJJ``/ISO → Datum."""
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    if isinstance(value, str):
        return parse_german_date(value) or _iso_date(value.strip())
    return None


def _iso_date(s: str) -> date | None:
    try:
        return date.fromisoformat(s[:10])
    except ValueError:
        return None


def parse_german_date(text_value: str) -> date | None:
    m = re.search(r"(\d{2})\.(\d{2})\.(\d{4})", text_value or "")
    if not m:
        return None
    try:
        return date(int(m.group(3)), int(m.group(2)), int(m.group(1)))
    except ValueError:
        return None


def fmt_date(d: date) -> str:
    return d.strftime("%d.%m.%Y")


# --------------------------------------------------------------------------------------------------------
# Dateien
# --------------------------------------------------------------------------------------------------------
def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def is_zip(path: Path) -> bool:
    try:
        return zipfile.is_zipfile(path)
    except OSError:
        return False


def is_xlsx(path: Path) -> bool:
    """XLSX = ZIP-Container mit ``xl/workbook.xml``."""
    if not is_zip(path):
        return False
    try:
        with zipfile.ZipFile(path) as z:
            return "xl/workbook.xml" in z.namelist()
    except zipfile.BadZipFile:
        return False


MAX_MEMBER_BYTES = 600_000_000  # Schutz vor Dekompressionsbomben in hochgeladenen Archiven


def extract_member(z: zipfile.ZipFile, info: zipfile.ZipInfo, dest: Path) -> Path:
    """Entpackt genau ein Archivmitglied unter einem festen Zielnamen (kein Pfad aus dem Archiv wird verwendet)."""
    if info.file_size > MAX_MEMBER_BYTES:
        raise ImportProblem(f"Archivmitglied {info.filename!r} ist mit {info.file_size} Bytes unerwartet groß.")
    written = 0
    with z.open(info) as src, dest.open("wb") as out:
        for chunk in iter(lambda: src.read(1 << 20), b""):
            written += len(chunk)
            if written > MAX_MEMBER_BYTES:
                raise ImportProblem(f"Archivmitglied {info.filename!r} überschreitet die zulässige Größe.")
            out.write(chunk)
    return dest


@contextmanager
def open_workbook(path: Path) -> Iterator[Any]:
    """Öffnet eine Arbeitsmappe nur lesend (Werte statt Formeln) und schließt sie zuverlässig."""
    import openpyxl
    from openpyxl.utils.exceptions import InvalidFileException

    try:
        wb = openpyxl.load_workbook(path, read_only=True, data_only=True)
    except (InvalidFileException, zipfile.BadZipFile, KeyError, OSError, ValueError) as exc:
        raise ImportProblem(f"Die Datei ist keine lesbare Excel-Arbeitsmappe (.xlsx): {exc}") from exc
    try:
        yield wb
    finally:
        wb.close()


def require_sheet(wb: Any, name: str, what: str) -> Any:
    if name not in wb.sheetnames:
        raise ImportProblem(f"{what}: Tabellenblatt „{name}“ fehlt (vorhanden: {', '.join(wb.sheetnames[:12])} …).")
    return wb[name]


def safe_name(name: str) -> str:
    cleaned = re.sub(r"[^A-Za-z0-9._-]+", "_", Path(name).name).strip("._")
    return cleaned[:120] or "datei"


def keep_source_file(settings: Settings, dataset_key: str, period_key: str, checksum: str, path: Path, name: str) -> str | None:
    """Bewahrt die Quelldatei unter ``downloads/<datensatz>/<zeitraum>/<sha8>_<name>`` auf (relativ zu ``data_dir``)."""
    if not settings.stats_keep_source_files:
        return None
    try:
        target_dir = settings.downloads_dir / safe_name(dataset_key) / safe_name(period_key)
        target_dir.mkdir(parents=True, exist_ok=True)
        target = target_dir / f"{checksum[:8]}_{safe_name(name)}"
        if not target.exists():
            tmp = target.with_suffix(target.suffix + ".teil")
            shutil.copyfile(path, tmp)
            tmp.replace(target)
        return str(target.relative_to(settings.data_dir))
    except OSError as exc:
        log.warning("Quelldatei konnte nicht aufbewahrt werden", extra={"dataset": dataset_key, "error": repr(exc)})
        return None


# --------------------------------------------------------------------------------------------------------
# Datenstände
# --------------------------------------------------------------------------------------------------------
@dataclass
class ParsedRelease:
    """Ein aus einer Datei gelesener Datenstand für genau einen Berichtszeitraum."""

    period_key: str
    period_end: date
    period_start: date | None = None
    checksum: str | None = None  # None = SHA-256 der Datei
    gebietsstand: date | None = None
    published_on: date | None = None
    values: list[ValueRow] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)
    row_count: int | None = None  # für Referenzdatensätze ohne stat_value-Zeilen


@dataclass
class FileContext:
    """Angaben zur gerade importierten Datei."""

    path: Path
    name: str
    sha256: str
    method: str
    file_url: str | None
    settings: Settings
    now: datetime = field(default_factory=lambda: datetime.now(UTC))
    published_on: date | None = None  # nur wenn die offizielle Seite das Datum nennt (automatischer Abruf)
    source_hint: str | None = None


def find_release(db: Session, dataset_key: str, period_key: str, checksum: str) -> StatRelease | None:
    return db.execute(select(StatRelease).where(
        StatRelease.dataset_key == dataset_key, StatRelease.period_key == period_key,
        StatRelease.file_sha256 == checksum)).scalar_one_or_none()


def current_release(db: Session, dataset_key: str, period_key: str | None = None) -> StatRelease | None:
    q = select(StatRelease).where(StatRelease.dataset_key == dataset_key, StatRelease.is_current)
    if period_key is not None:
        q = q.where(StatRelease.period_key == period_key)
    return db.execute(q.order_by(StatRelease.period_end.desc(), StatRelease.revision.desc()).limit(1)).scalar_one_or_none()


def store_release(db: Session, dataset_key: str, parsed: ParsedRelease, ctx: FileContext) -> dict[str, Any]:
    """Legt den Datenstand an – oder tut nichts, wenn genau diese Datei für den Zeitraum schon importiert ist.

    Andere Datei für denselben Zeitraum ⇒ Revision ``max+1`` wird aktuell, die bisherige bleibt mit allen
    Werten erhalten (``is_current = false``).
    """
    checksum = parsed.checksum or ctx.sha256
    existing = find_release(db, dataset_key, parsed.period_key, checksum)
    if existing is not None:
        return {"status": "unchanged", "period_key": parsed.period_key, "revision": existing.revision,
                "release_id": existing.id, "is_current": existing.is_current, "rows": existing.row_count,
                "message": "Diese Datei ist für den Berichtszeitraum bereits importiert – keine Änderung."}
    seen: set[tuple[str, str, str, str]] = set()
    for v in parsed.values:
        key = (v.indicator_key, v.region_level, v.region_key, v.dim_key)
        if key in seen:
            raise ImportProblem(f"Die Datei enthält den Wert {key} mehrfach – der Import wäre nicht eindeutig.")
        seen.add(key)
        if v.value_status not in ("ok", "zero") and v.value is not None:
            raise ImportProblem(f"Interner Prüffehler: Fehlwert {key} trägt einen Zahlenwert.")
    max_rev = db.execute(select(func.max(StatRelease.revision)).where(
        StatRelease.dataset_key == dataset_key, StatRelease.period_key == parsed.period_key)).scalar()
    revision = (max_rev or 0) + 1
    if max_rev:
        db.execute(update(StatRelease).where(
            StatRelease.dataset_key == dataset_key, StatRelease.period_key == parsed.period_key,
            StatRelease.is_current).values(is_current=False))
        db.flush()
    notes = list(parsed.notes)
    if checksum != ctx.sha256:
        notes.append(f"Prüfsumme über den Inhalt des Berichtszeitraums; SHA-256 der Datei: {ctx.sha256}")
    stored = keep_source_file(ctx.settings, dataset_key, parsed.period_key, checksum, ctx.path, ctx.name)
    rel = StatRelease(
        dataset_key=dataset_key, period_key=parsed.period_key, period_start=parsed.period_start,
        period_end=parsed.period_end, revision=revision, is_current=True,
        published_on=parsed.published_on or ctx.published_on, retrieved_at=ctx.now, file_url=ctx.file_url,
        file_name=ctx.name, file_sha256=checksum, stored_path=stored, gebietsstand=parsed.gebietsstand,
        import_method=ctx.method[:16],
        row_count=parsed.row_count if parsed.row_count is not None else len(parsed.values),
        notes=" | ".join(n for n in notes if n) or None)
    db.add(rel)
    db.flush()
    rows = [{"release_id": rel.id, "indicator_key": v.indicator_key, "region_level": v.region_level,
             "region_key": v.region_key, "region_name": v.region_name, "gebietsstand": parsed.gebietsstand,
             "dim_key": v.dim_key, "dim_label": v.dim_label, "classification_version": v.classification_version,
             "value": v.value, "value_status": v.value_status, "raw_value": v.raw_value} for v in parsed.values]
    for i in range(0, len(rows), 5000):
        db.execute(insert(StatValue), rows[i:i + 5000])
    status_counts = Counter(v.value_status for v in parsed.values)
    return {"status": "imported", "period_key": parsed.period_key, "revision": revision, "release_id": rel.id,
            "is_current": True, "rows": rel.row_count, "period_start": parsed.period_start, "period_end": parsed.period_end,
            "gebietsstand": parsed.gebietsstand, "published_on": rel.published_on, "stored_path": stored,
            "value_status": dict(status_counts), "replaced_revision": max_rev or None}


# --------------------------------------------------------------------------------------------------------
# Gebietsschlüssel
# --------------------------------------------------------------------------------------------------------
def known_region_keys(db: Session) -> dict[str, set[str]]:
    """Aktuelle Gebietsschlüssel je Ebene (leer, solange VG250 nicht geladen ist)."""
    out: dict[str, set[str]] = {"state": set(), "district": set()}
    for level, key in db.execute(sql("SELECT level, key FROM region WHERE country = 'DE' AND is_current")).all():
        out.setdefault(level, set()).add(key)
    return out


def unknown_region_keys(db: Session, values: Iterable[ValueRow]) -> list[str]:
    """Schlüssel aus der Statistik, die im geladenen Gebietsstand fehlen (z. B. nach Gebietsreformen).

    Es wird nichts verworfen oder umgeschlüsselt – die Schlüssel werden nur gemeldet. Gebiete, für die die Quelle
    überhaupt keinen Wert ausweist, zählen nicht dazu.
    """
    known = known_region_keys(db)
    unknown: set[str] = set()
    for v in values:
        if v.region_level not in ("state", "district") or v.value_status == "not_available":
            continue
        level_keys = known.get(v.region_level) or set()
        if level_keys and v.region_key not in level_keys:
            unknown.add(v.region_key)
    return sorted(unknown)


def summarize(dataset_key: str, ctx: FileContext, releases: list[dict[str, Any]], **extra: Any) -> dict[str, Any]:
    """Einheitliches Ergebnis eines Dateiimports."""
    imported = [r for r in releases if r["status"] == "imported"]
    newest = max(releases, key=lambda r: r["period_key"]) if releases else None
    out: dict[str, Any] = {
        "dataset": dataset_key, "status": "imported" if imported else "unchanged", "file_name": ctx.name,
        "file_sha256": ctx.sha256, "import_method": ctx.method,
        "period_key": newest["period_key"] if newest else None, "revision": newest["revision"] if newest else None,
        "rows": sum(int(r.get("rows") or 0) for r in imported), "releases": releases,
        "unknown_region_keys": [], "unknown_region_count": 0, "warnings": [],
    }
    out.update(extra)
    out["unknown_region_count"] = len(out["unknown_region_keys"])
    return out
