"""Adapter-Schnittstelle für Quellen.

Ein Adapter trennt **Entdeckung** (Liste/Feed/Sitemap) von der **Detailprüfung** (Anzeigenseite).
Er liefert nur öffentlich sichtbare Rumpfdaten; Ansprechpartner/Kontaktdaten werden nicht erfasst.
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Iterator
from dataclasses import dataclass, field
from datetime import date, datetime
from decimal import Decimal
from typing import Any

from ..crawl.fetcher import Fetcher, FetchResult


class ParseError(Exception):
    """Seite entspricht nicht dem erwarteten Aufbau (Layoutänderung) – kein Schließungsnachweis."""


@dataclass
class RawLocation:
    locality: str | None = None
    postal_code: str | None = None
    region: str | None = None
    country: str | None = None
    raw: str | None = None
    lat: float | None = None  # nur wenn von der Quelle angegeben – nie erfunden
    lon: float | None = None


@dataclass
class ParsedPosting:
    source_key: str
    url: str
    title: str
    canonical_url: str | None = None
    employer_name: str | None = None
    reference: str | None = None
    employer_url: str | None = None
    is_agency: bool | None = None
    locations: list[RawLocation] = field(default_factory=list)
    employment_types: list[str] = field(default_factory=list)
    working_time: list[str] = field(default_factory=list)
    contract_term: str | None = None
    remote_type: str | None = None
    kind: str | None = None
    occupation_label: str | None = None
    occupation_field: str | None = None
    salary_min: Decimal | None = None
    salary_max: Decimal | None = None
    salary_currency: str | None = None
    salary_period: str | None = None
    salary_origin: str | None = None
    salary_text: str | None = None
    date_posted: date | None = None
    apply_until: date | None = None
    valid_through: date | None = None
    description_text: str | None = None  # flüchtig: nur für die Extraktion, wird nicht gespeichert
    structured_hints: dict[str, Any] = field(default_factory=dict)  # z. B. JSON-LD skills/qualifications
    raw_payload: Any = None  # stabiler Rohinhalt für den Roh-Hash (ohne dynamische Elemente)
    detail_level: str = "detail"
    quality: dict[str, Any] = field(default_factory=dict)


@dataclass
class ListItem:
    source_key: str
    url: str
    lastmod: str | None = None
    posting: ParsedPosting | None = None  # falls die Liste bereits Rumpfdaten liefert
    published_at: datetime | None = None


@dataclass
class ListPage:
    items: list[ListItem]
    reported_total: int | None = None
    is_last: bool = True
    next_checkpoint: dict[str, Any] | None = None
    capped: bool = False  # Trefferobergrenze der Quelle erreicht
    signals: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class Partition:
    key: str
    params: dict[str, Any] = field(default_factory=dict)


@dataclass
class CoverageAssessment:
    list_complete: bool
    signals: dict[str, Any] = field(default_factory=dict)
    note: str | None = None


class SourceAdapter(ABC):
    key: str = ""
    version: str = "1"
    access_method: str = ""
    default_domains: tuple[str, ...] = ()
    #: 'full' = die Entdeckung zählt den gesamten Suchbereich auf (Fehlen ist ein Signal);
    #: 'new_only' = es werden nur neue Anzeigen gemeldet (Fehlen ist KEIN Schließungssignal).
    discovery_mode: str = "full"
    #: 'required' | 'optional' | 'none'
    detail_mode: str = "required"
    #: Dürfen kurze Belegauszüge aus dem Anzeigentext gespeichert werden?
    store_excerpts: bool = True

    def partitions(self, params: dict[str, Any]) -> list[Partition]:
        return [Partition("all")]

    @abstractmethod
    def list_pages(
        self, fetcher: Fetcher, params: dict[str, Any], partition: Partition, checkpoint: dict[str, Any] | None
    ) -> Iterator[ListPage]:
        """Liefert Listenseiten ab dem Checkpoint. Fehler als Ausnahme (FetchError/ParseError)."""

    def assess_coverage(self, pages: list[dict[str, Any]], previous: dict[str, Any] | None) -> CoverageAssessment:
        """Bewertet die Vollständigkeit der Entdeckung anhand überprüfbarer Signale."""
        return CoverageAssessment(list_complete=True)

    def parse_detail(self, result: FetchResult, item_key: str) -> ParsedPosting:
        raise NotImplementedError

    def is_explicitly_ended(self, result: FetchResult) -> bool:
        """Eindeutiger Ablaufhinweis auf der Detailseite (nicht: 403/CAPTCHA/Fehlerseite)."""
        return False
