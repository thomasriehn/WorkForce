"""Textnormalisierung: Faltung für die Suche, Titel-/Arbeitgebernormalisierung, URL-Bereinigung, Hashes."""
from __future__ import annotations

import hashlib
import html as _html
import json
import re
import unicodedata
from typing import Any
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from bs4 import BeautifulSoup

_UMLAUT = str.maketrans({"ä": "ae", "ö": "oe", "ü": "ue", "ß": "ss", "Ä": "ae", "Ö": "oe", "Ü": "ue"})

# Bezeichnungen mit Sonderzeichen, die ein Standard-Tokenizer zerstören würde (C++, C#, .NET …)
SPECIAL_TOKENS: list[tuple[re.Pattern[str], str]] = [
    (re.compile(r"(?<![a-z0-9])c\+\+(?![a-z0-9+])", re.I), " cplusplus "),
    (re.compile(r"(?<![a-z0-9])c#(?![a-z0-9])", re.I), " csharp "),
    (re.compile(r"(?<![a-z0-9])f#(?![a-z0-9])", re.I), " fsharp "),
    (re.compile(r"(?<![a-z0-9])asp\.net(?![a-z0-9])", re.I), " aspdotnet dotnet "),
    (re.compile(r"(?<![a-z0-9])\.net(?![a-z0-9])", re.I), " dotnet "),
    (re.compile(r"(?<![a-z0-9])node\.js(?![a-z0-9])", re.I), " nodejs "),
    (re.compile(r"(?<![a-z0-9])vue\.js(?![a-z0-9])", re.I), " vuejs "),
    (re.compile(r"(?<![a-z0-9])react\.js(?![a-z0-9])", re.I), " reactjs "),
    (re.compile(r"(?<![a-z0-9])sap\s*s/4\s*hana(?![a-z0-9])", re.I), " saps4hana "),
    (re.compile(r"(?<![a-z0-9])ci/cd(?![a-z0-9])", re.I), " cicd "),
]

_GENDER = re.compile(
    r"\(\s*(?:[mwfdx]|gn|div|all genders|alle geschlechter)(?:\s*[/|,*]\s*(?:[mwfdx]|gn|div|divers))+\s*\)"
    r"|\b[mwfd]\s*/\s*[mwfd]\s*/\s*[mwfdx]\b|\(\s*all genders\s*\)|\(\s*gn\s*\)|\(\s*m/w\s*\)",
    re.I,
)
_GENDER_SUFFIX = re.compile(r"(?<=[a-zäöüß])(?:\*|:|_|/-?|\(-?)(?:in|innen|r|n|e|er)\)?(?=\b|[^a-zäöüß])", re.I)
_WS = re.compile(r"\s+")
_LEGAL = re.compile(
    r"\b(gmbh\s*&\s*co\.?\s*kgaa|gmbh\s*&\s*co\.?\s*kg|gmbh|ggmbh|mbh|ag\s*&\s*co\.?\s*kg|kgaa|ag|se|kg|ohg|gbr|ug"
    r"|e\.\s?v\.|e\.\s?k\.|eg|ev|a\.?ö\.?r\.?|k\.?d\.?ö\.?r\.?|inc\.?|ltd\.?|limited|plc|s\.a\.|sarl|b\.v\.)\b",
    re.I,
)
TRACKING_PARAMS = re.compile(
    r"^(utm_.*|gclid|fbclid|msclkid|mc_[ce]id|track(ing)?|trk|ref(errer)?|source|src|cid|sid|session(id)?|jsessionid"
    r"|_ga|_gl|pk_.*|piwik_.*|campaign|medium|channel|wt_.*|hsfp|z|s_kwcid|yclid|origin|from)$",
    re.I,
)


def fold(text: str | None) -> str:
    """Suchfaltung: Sondertoken, Kleinschreibung, Umlaute → ae/oe/ue/ss, Akzente entfernen."""
    if not text:
        return ""
    t = text
    for rx, repl in SPECIAL_TOKENS:
        t = rx.sub(repl, t)
    t = t.translate(_UMLAUT).lower()
    t = unicodedata.normalize("NFKD", t)
    t = "".join(ch for ch in t if not unicodedata.combining(ch))
    t = re.sub(r"[^a-z0-9]+", " ", t)
    return _WS.sub(" ", t).strip()


def strip_gender(title: str) -> str:
    t = _GENDER.sub(" ", title)
    t = _GENDER_SUFFIX.sub("", t)
    return _WS.sub(" ", t).strip(" -–|/,")


def normalize_title(title: str | None) -> str:
    """Normalisierter Titel für Abgleich und Dublettenerkennung (ohne Gender-Zusätze)."""
    if not title:
        return ""
    return fold(strip_gender(title))


def normalize_employer(name: str | None) -> str:
    if not name:
        return ""
    t = _LEGAL.sub(" ", name)
    return fold(t)


def clean_ws(text: str | None) -> str | None:
    if text is None:
        return None
    t = _WS.sub(" ", _html.unescape(text)).strip()
    return t or None


def html_to_text(fragment: str | None) -> str:
    """HTML → Klartext mit Zeilenumbrüchen an Block- und Listenelementen (nur für die Extraktion)."""
    if not fragment:
        return ""
    if "<" not in fragment:
        return _html.unescape(fragment)
    soup = BeautifulSoup(fragment, "lxml")
    for tag in soup(["script", "style", "noscript"]):
        tag.decompose()
    for br in soup.find_all("br"):
        br.replace_with("\n")
    for tag in soup.find_all(["p", "div", "li", "ul", "ol", "h1", "h2", "h3", "h4", "h5", "tr", "section"]):
        tag.insert_before("\n")
        tag.insert_after("\n")
    text = soup.get_text(" ")
    text = re.sub(r"[ \t\xa0]+", " ", text)
    text = re.sub(r" ?\n ?", "\n", text)
    return re.sub(r"\n{2,}", "\n", text).strip()


def clean_url(url: str | None) -> str | None:
    """Kanonisiert eine URL: Trackingparameter und Fragment entfernen, Parameter sortieren."""
    if not url:
        return None
    url = url.strip()
    parts = urlsplit(url)
    if parts.scheme not in ("http", "https") or not parts.netloc:
        return None
    query = [(k, v) for k, v in parse_qsl(parts.query, keep_blank_values=True) if not TRACKING_PARAMS.match(k)]
    query.sort()
    path = re.sub(r";jsessionid=[^/?#]*", "", parts.path, flags=re.I) or "/"
    return urlunsplit(("https", parts.netloc.lower(), path, urlencode(query), ""))


def is_deep_link(url: str | None) -> bool:
    """Arbeitgeber-Zielverweise taugen nur als Dublettenmerkmal, wenn sie keine bloße Startseite sind."""
    if not url:
        return False
    parts = urlsplit(url)
    return len(parts.path.strip("/")) >= 6 or bool(parts.query)


def stable_hash(obj: Any) -> str:
    """SHA-256 über eine kanonische JSON-Darstellung (sortierte Schlüssel)."""
    data = json.dumps(obj, sort_keys=True, ensure_ascii=False, separators=(",", ":"), default=str)
    return hashlib.sha256(data.encode("utf-8")).hexdigest()


def short_evidence(text: str, start: int, end: int, width: int = 180) -> str:
    """Kurzer Belegauszug rund um eine Fundstelle (ein Satz/Aufzählungspunkt, gekürzt)."""
    left = max(text.rfind("\n", 0, start), text.rfind(". ", 0, start))
    left = 0 if left < 0 else left + 1
    right_candidates = [p for p in (text.find("\n", end), text.find(". ", end)) if p >= 0]
    right = min(right_candidates) + 1 if right_candidates else len(text)
    snippet = _WS.sub(" ", text[left:right]).strip()
    if len(snippet) > width:
        rel = max(0, start - left - width // 3)
        snippet = ("…" if rel > 0 else "") + snippet[rel : rel + width].strip() + "…"
    return snippet


_EMAIL = re.compile(r"[\w.+-]+@[\w-]+(?:\.[\w-]+)+")
_PHONE = re.compile(r"(?:(?:\+49|0049)[\s()/-]*|\b0)\d{2,5}[\s/()-]+\d[\d\s/-]{3,}\d")
_CONTACT_LINE = re.compile(r"ansprechpartner|ansprechperson|ansprechpersonen|rückfragen|auskünfte\s+erteilt|auskunft\s+erteilt|fragen\s+beantwortet|kontakt\s*:|steht\s+ihnen\s+(?:frau|herr)", re.I)


def sanitize_evidence(snippet: str | None) -> str | None:
    """Belegauszüge enthalten keine Ansprechpartner-/Kontaktdaten: Kontaktzeilen entfallen, Adressen/Nummern werden entfernt."""
    if not snippet:
        return None
    if _CONTACT_LINE.search(snippet):
        return None
    cleaned = _PHONE.sub("[…]", _EMAIL.sub("[…]", snippet))
    return cleaned.strip() or None
