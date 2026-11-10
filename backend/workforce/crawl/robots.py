"""robots.txt-Auswertung nach RFC 9309 (längste Übereinstimmung, ``*`` und ``$``), inkl. Crawl-delay."""
from __future__ import annotations

import re
from dataclasses import dataclass, field


@dataclass
class _Group:
    agents: list[str] = field(default_factory=list)
    rules: list[tuple[bool, str]] = field(default_factory=list)  # (allow, pattern)
    crawl_delay: float | None = None


def _compile(pattern: str) -> re.Pattern[str]:
    anchored = pattern.endswith("$")
    if anchored:
        pattern = pattern[:-1]
    rx = "".join(".*" if ch == "*" else re.escape(ch) for ch in pattern)
    return re.compile("^" + rx + ("$" if anchored else ""))


class RobotsPolicy:
    """Geparste robots.txt. ``status`` steuert das Verhalten bei fehlender/gestörter Datei."""

    def __init__(self, text: str | None, status_code: int | None = 200):
        self.status_code = status_code
        self.groups: list[_Group] = []
        self.sitemaps: list[str] = []
        if text:
            self._parse(text)

    def _parse(self, text: str) -> None:
        current: _Group | None = None
        last_was_agent = False
        for raw in text.splitlines():
            line = raw.split("#", 1)[0].strip()
            if not line or ":" not in line:
                continue
            key, value = (p.strip() for p in line.split(":", 1))
            key = key.lower()
            if key == "user-agent":
                if not last_was_agent or current is None:
                    current = _Group()
                    self.groups.append(current)
                current.agents.append(value.lower())
                last_was_agent = True
                continue
            last_was_agent = False
            if key == "sitemap":
                self.sitemaps.append(value)
            elif current is not None:
                if key in ("allow", "disallow"):
                    if value == "" and key == "disallow":
                        continue  # leeres Disallow = alles erlaubt
                    if value:
                        current.rules.append((key == "allow", value))
                elif key == "crawl-delay":
                    try:
                        current.crawl_delay = float(value)
                    except ValueError:
                        pass

    def _groups_for(self, agent_token: str) -> list[_Group]:
        token = agent_token.lower()
        specific = [g for g in self.groups if any(a != "*" and a in token for a in g.agents)]
        if specific:
            return specific
        return [g for g in self.groups if "*" in g.agents]

    def allowed(self, path_and_query: str, agent_token: str) -> bool:
        # RFC 9309: 4xx (außer 429) => keine Einschränkung; 5xx/429/unerreichbar => vollständig gesperrt
        if self.status_code is None or self.status_code >= 500 or self.status_code == 429:
            return False
        if self.status_code >= 400:
            return True
        best: tuple[int, bool] | None = None
        for g in self._groups_for(agent_token):
            for allow, pattern in g.rules:
                if _compile(pattern).match(path_and_query):
                    cand = (len(pattern), allow)
                    if best is None or cand[0] > best[0] or (cand[0] == best[0] and allow and not best[1]):
                        best = cand
        return True if best is None else best[1]

    def crawl_delay(self, agent_token: str) -> float | None:
        delays = [g.crawl_delay for g in self._groups_for(agent_token) if g.crawl_delay is not None]
        return max(delays) if delays else None
