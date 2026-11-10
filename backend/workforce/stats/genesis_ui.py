"""Export „CSV (Flat)“ über die öffentliche Tabellenansicht von GENESIS-Online bzw. der Regionaldatenbank.

Beide Angebote sind JavaScript-Anwendungen ohne statische Datei-URL. Es wird deshalb – wie ein Mensch – die
öffentliche Seite geöffnet, die Schaltfläche „Download“ betätigt und im Dialog „CSV (Flat)“ gewählt. Es gibt
keine Anmeldung, keinen API-Schlüssel und keinen eigenen Aufruf der Webservice-Schnittstelle.

Höflichkeitsregeln:

* robots.txt des Hosts wird vorab über den :class:`~workforce.crawl.fetcher.Fetcher` gelesen; nicht erlaubte Pfade
  werden auch im Browser nicht geladen.
* Der Browser meldet sich mit dem identifizierbaren User-Agent der Anwendung.
* Jede Anfrage an einen Host außerhalb der Erlaubnisliste wird blockiert (Schriften, Statistik-Skripte Dritter …).
* Ein Seitenaufruf und ein Download je Prüfung; kein Durchprobieren von Stichtagen.
"""
from __future__ import annotations

import logging
import os
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlsplit

from ..config import Settings
from ..crawl.fetcher import Fetcher, FetchError
from ..crawl.netguard import host_allowed
from ..crawl.robots import RobotsPolicy
from .common import ImportProblem, safe_name

log = logging.getLogger(__name__)

FALLBACK_CHROMIUM = Path("/opt/pw-browsers/chromium")
DOWNLOAD_BUTTON = 'button.statistic-table-toolbar-button[title="Download"]'
FORMAT_BUTTON = "CSV (Flat)"


@dataclass(frozen=True)
class UiSource:
    key: str
    name: str
    host: str
    table_code: str
    table_url: str


SOURCES: tuple[UiSource, ...] = (
    UiSource("genesis", "GENESIS-Online (Statistisches Bundesamt)", "genesis.destatis.de", "12411-0017",
             "https://genesis.destatis.de/datenbank/online/table/12411-0017/table-toolbar"),
    UiSource("regionalstatistik", "Regionaldatenbank Deutschland (Statistische Ämter des Bundes und der Länder)",
             "www.regionalstatistik.de", "12411-02-03-4",
             "https://www.regionalstatistik.de/datenbank/online/table/12411-02-03-4/table-toolbar"),
)


class UiError(ImportProblem):
    """Die öffentliche Oberfläche ließ sich nicht wie erwartet bedienen."""


def robots_policy(fetcher: Fetcher, host: str) -> RobotsPolicy:
    """robots.txt des Hosts über den höflichen Abruf lesen (5xx/429/unerreichbar ⇒ alles gesperrt)."""
    try:
        res = fetcher.get(f"https://{host}/robots.txt", check_robots=False)
    except FetchError as exc:
        log.warning("robots.txt nicht abrufbar", extra={"host": host, "error": str(exc)})
        return RobotsPolicy(None, None)
    return RobotsPolicy(res.text if res.status == 200 else None, res.status)


def _launch(playwright: object, proxy: dict[str, str] | None) -> object:
    chromium = playwright.chromium  # type: ignore[attr-defined]
    kwargs: dict[str, object] = {"headless": True}
    if proxy:
        kwargs["proxy"] = proxy
    try:
        return chromium.launch(**kwargs)
    except Exception as exc:  # Playwright meldet fehlende Browser als allgemeinen Fehler
        if not FALLBACK_CHROMIUM.exists():
            raise UiError("Für den Abruf der Bevölkerungstabelle wird ein Chromium-Browser benötigt "
                          f"(„playwright install chromium“): {str(exc).splitlines()[0]}") from exc
        log.info("Playwright-Browser nicht gefunden – verwende %s", FALLBACK_CHROMIUM)
        return chromium.launch(executable_path=str(FALLBACK_CHROMIUM), **kwargs)


def export_flat_csv(source: UiSource, dest_dir: Path, settings: Settings, fetcher: Fetcher,
                    heartbeat: Callable[[], None] | None = None) -> tuple[Path, str]:
    """Lädt den Export „CSV (Flat)“ der Tabelle in ``dest_dir`` und liefert ``(Pfad, Dateiname)``."""
    beat = heartbeat or (lambda: None)
    agent = settings.crawler_name
    policy = robots_policy(fetcher, source.host)
    path = urlsplit(source.table_url).path
    if not policy.allowed(path, agent):
        raise UiError(f"{source.name}: robots.txt erlaubt den Abruf der Tabellenseite nicht (oder ist nicht verfügbar).")
    beat()
    try:
        from playwright.sync_api import Error as PwError
        from playwright.sync_api import TimeoutError as PwTimeout
        from playwright.sync_api import sync_playwright
    except ImportError as exc:  # pragma: no cover – playwright ist eine feste Abhängigkeit
        raise UiError("Das Paket „playwright“ ist nicht installiert.") from exc

    blocked: list[str] = []

    def guard(route: object) -> None:
        url = route.request.url  # type: ignore[attr-defined]
        parts = urlsplit(url)
        if parts.scheme in ("data", "blob", "about"):
            route.continue_()  # type: ignore[attr-defined]
            return
        target = parts.path + (f"?{parts.query}" if parts.query else "")
        if parts.scheme != "https" or not host_allowed(parts.hostname or "", (source.host,)) or not policy.allowed(target, agent):
            blocked.append(parts.netloc + parts.path[:60])
            route.abort()  # type: ignore[attr-defined]
            return
        route.continue_()  # type: ignore[attr-defined]

    proxy_url = os.environ.get("HTTPS_PROXY") or os.environ.get("https_proxy")
    proxy = {"server": proxy_url} if proxy_url else None
    try:
        with sync_playwright() as pw:
            browser = _launch(pw, proxy)
            try:
                context = browser.new_context(accept_downloads=True, locale="de-DE", user_agent=settings.user_agent)  # type: ignore[attr-defined]
                context.route("**/*", guard)
                page = context.new_page()
                page.set_default_timeout(60_000)
                response = page.goto(source.table_url, wait_until="domcontentloaded", timeout=90_000)
                if response is not None and response.status in (401, 403, 429):
                    raise UiError(f"{source.name}: Die Tabellenseite antwortet mit HTTP {response.status} – kein weiterer Versuch.")
                beat()
                button = page.locator(DOWNLOAD_BUTTON).first
                try:
                    button.wait_for(state="visible", timeout=90_000)
                except PwTimeout:
                    button = page.get_by_role("button", name="Download", exact=True).first
                    button.wait_for(state="visible", timeout=15_000)
                try:
                    page.wait_for_load_state("networkidle", timeout=30_000)
                except PwTimeout:
                    pass  # die Anwendung lädt gelegentlich weiter nach; der Download-Dialog funktioniert trotzdem
                page.wait_for_timeout(3_000)
                if source.table_code not in page.content():
                    raise UiError(f"{source.name}: Die geöffnete Seite zeigt nicht die Tabelle {source.table_code}.")
                beat()
                button.click()
                dialog = page.get_by_role("dialog")
                dialog.wait_for(state="visible", timeout=30_000)
                with page.expect_download(timeout=180_000) as dl:
                    dialog.get_by_role("button", name=FORMAT_BUTTON, exact=True).click()
                download = dl.value
                name = safe_name(download.suggested_filename or f"{source.table_code}_de_flat.zip")
                target = dest_dir / name
                download.save_as(str(target))
                beat()
            finally:
                browser.close()  # type: ignore[attr-defined]
    except PwTimeout as exc:
        raise UiError(f"{source.name}: Die Oberfläche hat nicht rechtzeitig reagiert (Schaltfläche „Download“/„{FORMAT_BUTTON}“ "
                      f"nicht gefunden oder kein Download): {str(exc).splitlines()[0]}") from exc
    except PwError as exc:
        raise UiError(f"{source.name}: Browserfehler beim Abruf der Tabelle: {str(exc).splitlines()[0]}") from exc
    size = target.stat().st_size if target.exists() else 0
    if size == 0:
        raise UiError(f"{source.name}: Der Download ist leer.")
    if size > settings.stats_max_download_bytes:
        target.unlink(missing_ok=True)
        raise UiError(f"{source.name}: Der Download überschreitet die zulässige Größe ({size} Bytes).")
    if blocked:
        log.info("Im Browser blockierte Anfragen", extra={"count": len(blocked), "examples": sorted(set(blocked))[:5]})
    return target, name
