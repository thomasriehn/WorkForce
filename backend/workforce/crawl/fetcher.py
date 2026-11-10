"""Höflicher HTTP-Abruf: identifizierbarer User-Agent, robots.txt, Abrufabstände, Timeouts, Backoff,
``Retry-After``, bedingte Abrufe (ETag/Last-Modified) und Schutz der Weiterleitungen.

Keine CAPTCHA-/Login-Umgehung, keine Proxyrotation: Sperrsignale beenden den Lauf als ``blocked``.
"""
from __future__ import annotations

import hashlib
import logging
import random
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from email.utils import parsedate_to_datetime
from pathlib import Path
from urllib.parse import urljoin, urlsplit

import httpx

from ..config import Settings, get_settings
from .netguard import ForbiddenTarget, check_url
from .robots import RobotsPolicy

log = logging.getLogger(__name__)

CHALLENGE_MARKERS = (
    "just a moment...",
    "cf-chl-",
    "captcha-delivery.com",
    "please enable js and disable any ad blocker",
    "human verification",
    "awswafcookiedomainlist",
    "g-recaptcha",
    "hcaptcha",
    "are you a robot",
    "sicherheitsabfrage",
)


class FetchError(Exception):
    kind = "fetch"

    def __init__(self, message: str, url: str | None = None, status: int | None = None):
        super().__init__(message)
        self.url = url
        self.status = status


class BlockedError(FetchError):
    """Zugriff verweigert oder Bot-Schutz: HTTP 401/403/429, CAPTCHA, zu langes Retry-After."""

    kind = "blocked"


class RobotsDisallowed(FetchError):
    kind = "robots"


class TransientError(FetchError):
    """Timeout/5xx nach ausgeschöpften Wiederholungen."""

    kind = "transient"


class TargetForbidden(FetchError):
    kind = "forbidden_target"


@dataclass
class FetchResult:
    url: str
    final_url: str
    status: int
    content: bytes = b""
    headers: dict[str, str] = field(default_factory=dict)
    not_modified: bool = False
    fetched_at: datetime = field(default_factory=lambda: datetime.now(UTC))

    @property
    def text(self) -> str:
        ctype = self.headers.get("content-type", "")
        enc = "utf-8"
        if "charset=" in ctype:
            enc = ctype.split("charset=", 1)[1].split(";")[0].strip() or "utf-8"
        try:
            return self.content.decode(enc, errors="replace")
        except LookupError:
            return self.content.decode("utf-8", errors="replace")

    @property
    def gone(self) -> bool:
        return self.status in (404, 410)


def looks_like_challenge(status: int, body: bytes) -> bool:
    head = body[:6000].decode("utf-8", errors="ignore").lower()
    return any(m in head for m in CHALLENGE_MARKERS) and (status in (200, 202, 401, 403, 405, 429, 503))


def parse_retry_after(value: str | None, now: datetime | None = None) -> float | None:
    if not value:
        return None
    value = value.strip()
    if value.isdigit():
        return float(value)
    try:
        dt = parsedate_to_datetime(value)
    except (TypeError, ValueError):
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=UTC)
    return max(0.0, (dt - (now or datetime.now(UTC))).total_seconds())


class _HostPacer:
    """Mindestabstand zwischen Abrufen je Host (prozessweit, threadsicher)."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._host_locks: dict[str, threading.Lock] = {}
        self._last: dict[str, float] = {}

    def host_lock(self, host: str) -> threading.Lock:
        with self._lock:
            return self._host_locks.setdefault(host, threading.Lock())

    def wait(self, host: str, interval: float, sleep: Callable[[float], None], clock: Callable[[], float]) -> None:
        last = self._last.get(host)
        if last is not None:
            delta = clock() - last
            if delta < interval:
                sleep(interval - delta)

    def mark(self, host: str, clock: Callable[[], float]) -> None:
        self._last[host] = clock()


_PACER = _HostPacer()


class RobotsStore:
    """robots.txt-Cache (Speicher + optional Datenbank über Callbacks)."""

    def __init__(
        self,
        load: Callable[[str], tuple[datetime, int | None, str | None] | None] | None = None,
        save: Callable[[str, datetime, int | None, str | None], None] | None = None,
    ):
        self._mem: dict[str, tuple[datetime, RobotsPolicy]] = {}
        self._load = load
        self._save = save

    def get(self, host: str, max_age: timedelta) -> RobotsPolicy | None:
        now = datetime.now(UTC)
        hit = self._mem.get(host)
        if hit and now - hit[0] < max_age:
            return hit[1]
        if self._load:
            row = self._load(host)
            if row and now - row[0] < max_age:
                pol = RobotsPolicy(row[2], row[1])
                self._mem[host] = (row[0], pol)
                return pol
        return None

    def put(self, host: str, status: int | None, body: str | None) -> RobotsPolicy:
        now = datetime.now(UTC)
        pol = RobotsPolicy(body, status)
        self._mem[host] = (now, pol)
        if self._save:
            self._save(host, now, status, body)
        return pol


class Fetcher:
    """Abruf für genau eine Quelle (erlaubte Domains, Abrufabstand, Budget)."""

    def __init__(
        self,
        allowed_domains: tuple[str, ...] | list[str],
        *,
        interval_seconds: float | None = None,
        settings: Settings | None = None,
        transport: httpx.BaseTransport | None = None,
        robots_store: RobotsStore | None = None,
        sleep: Callable[[float], None] = time.sleep,
        clock: Callable[[], float] = time.monotonic,
        resolve_dns: bool = True,
        cache_get: Callable[[str], tuple[str | None, str | None] | None] | None = None,
        cache_put: Callable[[str, str, str | None, str | None, int], None] | None = None,
    ):
        self.settings = settings or get_settings()
        self.allowed_domains = tuple(allowed_domains)
        self.interval = float(interval_seconds if interval_seconds is not None else self.settings.default_request_interval_seconds)
        self.robots = robots_store or RobotsStore()
        self._sleep = sleep
        self._clock = clock
        self._resolve = resolve_dns and transport is None
        self._cache_get = cache_get
        self._cache_put = cache_put
        self.requests_made = 0
        self._robots_failed: dict[str, float] = {}
        self.agent_token = self.settings.crawler_name
        self._client = httpx.Client(
            transport=transport,
            timeout=httpx.Timeout(self.settings.http_timeout_seconds),
            follow_redirects=False,  # Weiterleitungen werden einzeln geprüft
            headers={
                "User-Agent": self.settings.user_agent,
                "Accept-Language": "de-DE,de;q=0.9",
                "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.5",
            },
        )

    def close(self) -> None:
        self._client.close()

    # ------------------------------------------------------------------------------------------
    def _check(self, url: str) -> str:
        try:
            return check_url(url, self.allowed_domains, resolve=self._resolve)
        except ForbiddenTarget as exc:
            raise TargetForbidden(str(exc), url=url) from exc

    def _robots_for(self, url: str) -> RobotsPolicy:
        parts = urlsplit(url)
        host = parts.netloc
        pol = self.robots.get(host, timedelta(hours=self.settings.robots_cache_hours))
        if pol is not None:
            return pol
        failed_until = self._robots_failed.get(host)
        if failed_until is not None and self._clock() < failed_until:
            return RobotsPolicy(None, None)
        robots_url = f"https://{host}/robots.txt"
        status: int | None = None
        body: str | None = None
        attempt = 0
        while True:  # vorübergehende Störungen (Verbindungsabbruch, 5xx) mit Backoff wiederholen
            attempt += 1
            try:
                resp = self._raw_get(robots_url, {}, max_redirects=3)
                status = resp.status_code
                body = resp.text if resp.status_code == 200 else None
                if status == 200 and looks_like_challenge(status, resp.content):
                    status, body = 403, None  # Challenge statt robots.txt => keine Freigabe ableitbar
            except TargetForbidden as exc:
                log.warning("robots.txt nicht abrufbar", extra={"host": host, "error": repr(exc)})
                status = None
                break
            except httpx.HTTPError as exc:
                log.warning("robots.txt nicht abrufbar", extra={"host": host, "error": repr(exc), "attempt": attempt})
                status = None
            if status is not None and status < 500 and status != 429:
                break
            if attempt > self.settings.http_max_retries:
                break
            self._backoff(attempt, None)
        # 401/403 auf robots.txt werten wir – strenger als RFC 9309 – als Sperrsignal.
        if status in (401, 403):
            status = 503
        if status is None or status >= 500 or status == 429:
            # Nicht erreichbar => für diesen Lauf vollständig gesperrt (RFC 9309), aber nicht einen Tag lang zwischenspeichern:
            # der nächste Lauf prüft erneut.
            self._robots_failed[host] = self._clock() + 600.0
            return RobotsPolicy(None, status)
        return self.robots.put(host, status, body)

    def _effective_interval(self, pol: RobotsPolicy | None) -> float:
        delay = pol.crawl_delay(self.agent_token) if pol else None
        return max(self.interval, delay or 0.0)

    def _raw_get(self, url: str, headers: dict[str, str], max_redirects: int = 5) -> httpx.Response:
        """Ein GET inkl. geprüfter Weiterleitungen (ohne robots-/Retry-Logik)."""
        current = self._check(url)
        for _ in range(max_redirects + 1):
            host = urlsplit(current).netloc
            lock = _PACER.host_lock(host)
            with lock:
                _PACER.wait(host, self.interval, self._sleep, self._clock)
                try:
                    with self._client.stream("GET", current, headers=headers) as resp:
                        chunks: list[bytes] = []
                        size = 0
                        for chunk in resp.iter_bytes():
                            size += len(chunk)
                            if size > self.settings.max_response_bytes:
                                raise FetchError("Antwort überschreitet die maximale Größe", url=current)
                            chunks.append(chunk)
                        resp._content = b"".join(chunks)  # noqa: SLF001 – gestreamten Inhalt bereitstellen
                finally:
                    _PACER.mark(host, self._clock)
                    self.requests_made += 1
            if resp.status_code in (301, 302, 303, 307, 308) and "location" in resp.headers:
                current = self._check(urljoin(current, resp.headers["location"]))
                continue
            return resp
        raise FetchError("zu viele Weiterleitungen", url=url)

    # ------------------------------------------------------------------------------------------
    def get(self, url: str, *, conditional: bool = False, check_robots: bool = True) -> FetchResult:
        """Ruft eine URL ab. 404/410 werden als Ergebnis geliefert, Sperren/Fehler als Ausnahme."""
        s = self.settings
        url = self._check(url)
        pol: RobotsPolicy | None = None
        if check_robots:
            pol = self._robots_for(url)
            parts = urlsplit(url)
            target = parts.path + (f"?{parts.query}" if parts.query else "")
            if not pol.allowed(target, self.agent_token):
                raise RobotsDisallowed("laut robots.txt nicht erlaubt (oder robots.txt nicht verfügbar)", url=url)
        saved_interval = self.interval
        self.interval = self._effective_interval(pol)
        headers: dict[str, str] = {}
        cache_key = hashlib.sha256(url.encode()).hexdigest()
        if conditional and self._cache_get:
            cached = self._cache_get(cache_key)
            if cached:
                if cached[0]:
                    headers["If-None-Match"] = cached[0]
                if cached[1]:
                    headers["If-Modified-Since"] = cached[1]
        try:
            attempt = 0
            while True:
                attempt += 1
                try:
                    resp = self._raw_get(url, headers)
                except (httpx.TimeoutException, httpx.TransportError) as exc:
                    if attempt > s.http_max_retries:
                        raise TransientError(f"Netzwerkfehler/Timeout: {exc!r}", url=url) from exc
                    self._backoff(attempt, None)
                    continue
                status = resp.status_code
                body = resp.content
                if status == 304:
                    return FetchResult(url=url, final_url=str(resp.url), status=304, not_modified=True,
                                       headers=dict(resp.headers))
                if looks_like_challenge(status, body):
                    raise BlockedError("Bot-Schutz/CAPTCHA erkannt – kein Umgehungsversuch", url=url, status=status)
                if status in (401, 403):
                    raise BlockedError(f"HTTP {status}", url=url, status=status)
                if status == 429 or 500 <= status < 600:
                    retry_after = parse_retry_after(resp.headers.get("retry-after"))
                    if retry_after is not None and retry_after > s.retry_after_max_seconds:
                        raise BlockedError(
                            f"HTTP {status} mit Retry-After {int(retry_after)} s (über Grenze)", url=url, status=status
                        )
                    if attempt > s.http_max_retries:
                        if status == 429:
                            raise BlockedError("HTTP 429 trotz Backoff", url=url, status=status)
                        raise TransientError(f"HTTP {status} nach {attempt} Versuchen", url=url, status=status)
                    self._backoff(attempt, retry_after)
                    continue
                if conditional and self._cache_put and status == 200:
                    self._cache_put(cache_key, url, resp.headers.get("etag"), resp.headers.get("last-modified"), status)
                return FetchResult(url=url, final_url=str(resp.url), status=status, content=body,
                                   headers={k.lower(): v for k, v in resp.headers.items()})
        finally:
            self.interval = saved_interval

    def _backoff(self, attempt: int, retry_after: float | None) -> None:
        s = self.settings
        delay = min(s.http_backoff_max_seconds, s.http_backoff_base_seconds * (2 ** (attempt - 1)))
        delay += random.uniform(0, delay * 0.25)
        if retry_after is not None:
            delay = max(delay, retry_after)
        log.info("Backoff", extra={"seconds": round(delay, 1), "attempt": attempt})
        self._sleep(delay)

    # ------------------------------------------------------------------------------------------
    def _raw_download(self, url: str, headers: dict[str, str], dest: Path, max_bytes: int,
                      max_redirects: int = 5) -> tuple[httpx.Response, bytes, int]:
        """Ein GET mit geprüften Weiterleitungen; ein 200er-Inhalt wird gestreamt nach ``dest`` geschrieben.

        Liefert ``(Antwort, Anfang des Inhalts, Größe)``. Andere Statuscodes schreiben keine Datei.
        """
        current = self._check(url)
        for _ in range(max_redirects + 1):
            host = urlsplit(current).netloc
            head = b""
            size = 0
            with _PACER.host_lock(host):
                _PACER.wait(host, self.interval, self._sleep, self._clock)
                try:
                    with self._client.stream("GET", current, headers=headers) as resp:
                        if resp.status_code == 200:
                            declared = resp.headers.get("content-length", "")
                            if declared.isdigit() and int(declared) > max_bytes:
                                raise FetchError(f"Datei überschreitet die maximale Größe ({declared} > {max_bytes} Bytes)", url=current)
                            with dest.open("wb") as out:
                                for chunk in resp.iter_bytes():
                                    size += len(chunk)
                                    if size > max_bytes:
                                        raise FetchError(f"Datei überschreitet die maximale Größe von {max_bytes} Bytes", url=current)
                                    if len(head) < 6000:
                                        head += chunk[: 6000 - len(head)]
                                    out.write(chunk)
                        else:
                            for chunk in resp.iter_bytes():
                                if len(head) < 6000:
                                    head += chunk[: 6000 - len(head)]
                finally:
                    _PACER.mark(host, self._clock)
                    self.requests_made += 1
            if resp.status_code in (301, 302, 303, 307, 308) and "location" in resp.headers:
                current = self._check(urljoin(current, resp.headers["location"]))
                continue
            return resp, head, size
        raise FetchError("zu viele Weiterleitungen", url=url)

    def download(self, url: str, dest_path: Path | str, max_bytes: int | None = None, *, if_none_match: str | None = None,
                 if_modified_since: str | None = None, check_robots: bool = True) -> FetchResult:
        """Lädt eine (große) Datei gestreamt nach ``dest_path`` – mit denselben Prüfungen wie :meth:`get`.

        robots.txt, Abrufabstand je Host, geprüfte Weiterleitungen, Backoff/``Retry-After`` und Sperrsignale gelten
        unverändert. ``if_none_match``/``if_modified_since`` erlauben einen bedingten Abruf (304 ⇒ ``not_modified``,
        es wird nichts geschrieben). Die Datei erscheint erst nach vollständigem Abruf unter ``dest_path``; der
        Inhalt steht nicht in ``FetchResult.content``. Andere Statuscodes als 200/304 werden ohne Datei geliefert.
        """
        s = self.settings
        limit = int(max_bytes if max_bytes is not None else s.stats_max_download_bytes)
        dest = Path(dest_path)
        part = dest.with_name(dest.name + ".teil")
        url = self._check(url)
        pol: RobotsPolicy | None = None
        if check_robots:
            pol = self._robots_for(url)
            parts = urlsplit(url)
            target = parts.path + (f"?{parts.query}" if parts.query else "")
            if not pol.allowed(target, self.agent_token):
                raise RobotsDisallowed("laut robots.txt nicht erlaubt (oder robots.txt nicht verfügbar)", url=url)
        headers: dict[str, str] = {"Accept": "*/*"}
        if if_none_match:
            headers["If-None-Match"] = if_none_match
        if if_modified_since:
            headers["If-Modified-Since"] = if_modified_since
        saved_interval = self.interval
        self.interval = self._effective_interval(pol)
        try:
            attempt = 0
            while True:
                attempt += 1
                try:
                    resp, head, size = self._raw_download(url, headers, part, limit)
                except (httpx.TimeoutException, httpx.TransportError) as exc:
                    if attempt > s.http_max_retries:
                        raise TransientError(f"Netzwerkfehler/Timeout: {exc!r}", url=url) from exc
                    self._backoff(attempt, None)
                    continue
                status = resp.status_code
                hdrs = {k.lower(): v for k, v in resp.headers.items()}
                if status == 304:
                    return FetchResult(url=url, final_url=str(resp.url), status=304, not_modified=True, headers=hdrs)
                if looks_like_challenge(status, head) and (status != 200 or "html" in hdrs.get("content-type", "")):
                    raise BlockedError("Bot-Schutz/CAPTCHA erkannt – kein Umgehungsversuch", url=url, status=status)
                if status in (401, 403):
                    raise BlockedError(f"HTTP {status}", url=url, status=status)
                if status == 429 or 500 <= status < 600:
                    retry_after = parse_retry_after(resp.headers.get("retry-after"))
                    if retry_after is not None and retry_after > s.retry_after_max_seconds:
                        raise BlockedError(
                            f"HTTP {status} mit Retry-After {int(retry_after)} s (über Grenze)", url=url, status=status
                        )
                    if attempt > s.http_max_retries:
                        if status == 429:
                            raise BlockedError("HTTP 429 trotz Backoff", url=url, status=status)
                        raise TransientError(f"HTTP {status} nach {attempt} Versuchen", url=url, status=status)
                    self._backoff(attempt, retry_after)
                    continue
                if status == 200:
                    part.replace(dest)
                    hdrs["x-wf-bytes"] = str(size)
                return FetchResult(url=url, final_url=str(resp.url), status=status, headers=hdrs)
        finally:
            self.interval = saved_interval
            part.unlink(missing_ok=True)
