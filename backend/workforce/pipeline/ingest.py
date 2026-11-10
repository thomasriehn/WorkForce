"""Ingest: Quellanzeigen, unveränderliche Inhaltsversionen und kompakte Beobachtungen.

Idempotenz: Ein wiederholter identischer Lauf erzeugt weder neue Anzeigen noch Versionen noch
Beobachtungen (eindeutige Schlüssel + Hash-Vergleich). Der Volltext wird nur flüchtig verarbeitet.
"""
from __future__ import annotations

import logging
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select, text as sql
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import Session

from ..config import CLASSIFIER_VERSION, GEO_RULE_VERSION, Settings, get_settings
from ..geo.matcher import GeoMatch, GeoMatcher, summarize_geo
from ..models import (
    IN_STOCK,
    ActivityPeriod,
    Employer,
    Observation,
    PostingEvent,
    PostingFeature,
    PostingLocation,
    PostingScope,
    PostingVersion,
    ScanRun,
    Source,
    SourcePosting,
)
from ..normalize.features import classify_employment, classify_kind, detect_agency, extract_features
from ..normalize.occupation import OccupationClassifier
from ..normalize.text import clean_url, fold, is_deep_link, normalize_employer, normalize_title, stable_hash
from ..sources.base import ListItem, ParsedPosting, SourceAdapter
from . import dedup

log = logging.getLogger(__name__)


class Ingestor:
    def __init__(self, db: Session, source: Source, adapter: SourceAdapter, run: ScanRun, settings: Settings | None = None):
        self.db = db
        self.source = source
        self.adapter = adapter
        self.run = run
        self.settings = settings or get_settings()
        self.geo = GeoMatcher(db)
        self.occupations = OccupationClassifier(db)
        self._employers: dict[str, int] = {}
        self.stats = {"new": 0, "changed": 0, "extracted": 0, "reactivated": 0}

    # --------------------------------------------------------------------------------------------
    def _employer_id(self, name: str | None, is_agency: bool | None) -> int | None:
        norm = normalize_employer(name)
        if not name or not norm:
            return None
        if norm in self._employers:
            return self._employers[norm]
        stmt = (
            pg_insert(Employer)
            .values(name=name.strip()[:500], name_norm=norm, is_staffing_agency=is_agency)
            .on_conflict_do_update(index_elements=["name_norm"], set_={"name_norm": norm})
            .returning(Employer.id)
        )
        eid = self.db.execute(stmt).scalar_one()
        self._employers[norm] = eid
        return eid

    def get_or_create_posting(self, item: ListItem) -> tuple[SourcePosting, bool]:
        """Legt die Quellanzeige an (stabile Quell-ID) oder liefert die vorhandene."""
        now = datetime.now(UTC)
        run = self.run
        stmt = (
            pg_insert(SourcePosting)
            .values(
                source_id=self.source.id, source_key=item.source_key[:200], original_url=item.url,
                canonical_url=clean_url(item.url), first_seen_at=now, first_seen_date=run.logical_date,
                first_seen_run_id=run.id, first_seen_baseline=run.is_baseline, last_seen_at=now,
                last_seen_date=run.logical_date, status="active", is_synthetic=bool(getattr(self, "synthetic", False)),
            )
            .on_conflict_do_nothing(index_elements=["source_id", "source_key"])
            .returning(SourcePosting.id)
        )
        new_id = self.db.execute(stmt).scalar_one_or_none()
        if new_id is not None:
            sp = self.db.get(SourcePosting, new_id)
            assert sp is not None
            self.db.add(ActivityPeriod(source_posting_id=sp.id, start_date=run.logical_date))
            self.stats["new"] += 1
            return sp, True
        sp = self.db.execute(
            select(SourcePosting).where(SourcePosting.source_id == self.source.id, SourcePosting.source_key == item.source_key[:200])
        ).scalar_one()
        return sp, False

    def observe(self, item: ListItem, scope_id: int, *, seen_list: bool = True) -> SourcePosting:
        """Beobachtung einer Anzeige in der Liste/im Feed dieses Laufs."""
        run = self.run
        now = datetime.now(UTC)
        sp, created = self.get_or_create_posting(item)
        if not created:
            if sp.status not in IN_STOCK:
                self._reactivate(sp)
            elif sp.status != "active":
                sp.status, sp.status_reason, sp.status_changed_at = "active", "erneut beobachtet", now
            if run.logical_date >= sp.last_seen_date:
                sp.last_seen_at, sp.last_seen_date = now, run.logical_date
            sp.gone_confirmations = 0
        if item.lastmod and item.lastmod != sp.list_hash and self.adapter.detail_mode != "none":
            # geändertes lastmod der Sitemap = Änderungssignal => Detailprüfung fällig
            if sp.list_hash is not None:
                sp.detail_due = True
            sp.list_hash = item.lastmod[:64]
        self.db.execute(
            pg_insert(PostingScope)
            .values(source_posting_id=sp.id, scope_id=scope_id, first_run_id=run.id, last_seen_run_id=run.id,
                    last_seen_date=run.logical_date, missed_complete_runs=0)
            .on_conflict_do_update(
                index_elements=["source_posting_id", "scope_id"],
                set_={"last_seen_run_id": run.id, "last_seen_date": run.logical_date, "missed_complete_runs": 0},
            )
        )
        if item.posting is not None:
            self.apply_parsed(sp, item.posting)
        self._record_observation(sp, seen_list=seen_list, seen_detail=False)
        return sp

    def _record_observation(self, sp: SourcePosting, *, seen_list: bool, seen_detail: bool) -> None:
        stmt = pg_insert(Observation).values(
            run_id=self.run.id, source_posting_id=sp.id, version_id=sp.current_version_id, seen_list=seen_list, seen_detail=seen_detail
        )
        update: dict[str, Any] = {"version_id": sp.current_version_id}
        if seen_list:
            update["seen_list"] = True
        if seen_detail:
            update["seen_detail"] = True
        self.db.execute(stmt.on_conflict_do_update(index_elements=["run_id", "source_posting_id"], set_=update))

    def _reactivate(self, sp: SourcePosting) -> None:
        now = datetime.now(UTC)
        previous = sp.status
        sp.status, sp.status_reason, sp.status_changed_at = "active", f"Reaktivierung (zuvor: {previous})", now
        sp.gone_confirmations = 0
        open_period = self.db.execute(
            select(ActivityPeriod).where(ActivityPeriod.source_posting_id == sp.id, ActivityPeriod.end_date.is_(None))
        ).scalar_one_or_none()
        if open_period is None:
            self.db.add(ActivityPeriod(source_posting_id=sp.id, start_date=self.run.logical_date))
        self.db.add(PostingEvent(
            event_date=self.run.logical_date, effective_date=self.run.logical_date, event_type="reactivation",
            merged_posting_id=sp.merged_posting_id, source_posting_id=sp.id, run_id=self.run.id,
            details={"previous_status": previous},
        ))
        self.stats["reactivated"] += 1
        self.db.flush()
        if sp.merged_posting_id:
            dedup.refresh_merged(self.db, sp.merged_posting_id)

    # --------------------------------------------------------------------------------------------
    def build_version(self, sp: SourcePosting, p: ParsedPosting) -> tuple[PostingVersion, list[GeoMatch]]:
        """Erzeugt (noch nicht gespeichert) die Versionszeile samt abgeleiteter Merkmale."""
        store_ev = self.adapter.store_excerpts
        title = p.title.strip()[:500]
        title_norm = normalize_title(title)
        employer_norm = normalize_employer(p.employer_name)
        emp = classify_employment(title, p.description_text)
        working_time = sorted(set(p.working_time) | set(emp["working_time"]))
        contract_term = p.contract_term or emp["contract_term"]
        remote_type = p.remote_type or emp["remote_type"]
        kind = classify_kind(title, p.kind)
        is_agency = p.is_agency if p.is_agency is not None else detect_agency(p.employer_name, p.description_text)
        feats = extract_features(p.description_text, title=title, hints=p.structured_hints, store_evidence=store_ev) if p.detail_level == "detail" else []
        matches = [self.geo.match(loc) for loc in p.locations]
        geo = summarize_geo(matches, remote_type)
        occ = self.occupations.classify(p.occupation_label, title)
        employer_url = clean_url(p.employer_url)
        if employer_url and not is_deep_link(employer_url):
            employer_url = None  # bloße Startseiten taugen nicht als Zielverweis einer Stelle
        positive = sorted({f.key for f in feats if f.polarity in ("required", "desired", "unclear")})
        required = sorted({f.key for f in feats if f.polarity == "required"})
        content = {
            "title": title_norm, "employer": employer_norm, "reference": (p.reference or "").strip() or None,
            "employer_url": employer_url, "kind": kind,
            "locations": sorted((fold(loc.locality), loc.postal_code or "", (loc.country or "").upper()) for loc in p.locations),
            "employment_types": sorted(p.employment_types), "working_time": working_time, "contract_term": contract_term,
            "remote_type": remote_type, "occupation_label": fold(p.occupation_label),
            "salary": [str(p.salary_min or ""), str(p.salary_max or ""), p.salary_currency, p.salary_period, p.salary_text],
            "apply_until": p.apply_until, "valid_through": p.valid_through,
            "features": sorted((f.key, f.polarity) for f in feats),
        }
        excerpts = []
        if store_ev:
            seen: set[str] = set()
            for f in feats:
                if f.evidence and f.polarity in ("required", "desired", "negated") and f.evidence not in seen:
                    seen.add(f.evidence)
                    excerpts.append(f.evidence[:220])
                if len(excerpts) >= 6:
                    break
        quality: dict[str, Any] = dict(p.quality)
        quality.update({
            "detail_level": p.detail_level,
            "has_employer": bool(p.employer_name), "has_location": bool(p.locations),
            "date_posted_known": p.date_posted is not None,
            "geo_class": geo["geo_class"],
            "excerpts_stored": store_ev,
        })
        if occ and occ.confidence < 0.7:
            quality["kldb_uncertain"] = True
        feature_labels = " ".join(sorted({f.label for f in feats if f.polarity != "negated"}))
        v = PostingVersion(
            source_posting_id=sp.id, detail_level=p.detail_level, content_hash=stable_hash(content),
            raw_hash=stable_hash(p.raw_payload) if p.raw_payload is not None else None,
            parser_version=self.adapter.version, classifier_version=CLASSIFIER_VERSION, geo_rule_version=GEO_RULE_VERSION,
            run_id=self.run.id, valid_from=self.run.logical_date,
            title=title, title_norm=title_norm, employer_name=(p.employer_name or None), employer_norm=employer_norm or None,
            reference=content["reference"], employer_url=employer_url, is_agency=is_agency, kind=kind,
            employment_types=sorted(p.employment_types), working_time=working_time, contract_term=contract_term,
            remote_type=remote_type, occupation_label=p.occupation_label, occupation_field=p.occupation_field,
            kldb_code=occ.code if occ else None, kldb_source=occ.source if occ else None,
            kldb_confidence=occ.confidence if occ else None, requirement_level=occ.requirement_level if occ else None,
            salary_min=p.salary_min, salary_max=p.salary_max, salary_currency=p.salary_currency, salary_period=p.salary_period,
            salary_origin=p.salary_origin if (p.salary_min or p.salary_max or p.salary_text) else None, salary_text=p.salary_text,
            date_posted=p.date_posted, apply_until=p.apply_until, valid_through=p.valid_through,
            excerpts=excerpts, quality=quality,
            kreis_keys=geo["kreis_keys"], state_keys=geo["state_keys"], loc_total=geo["loc_total"],
            loc_unresolved=geo["loc_unresolved"], geo_class=geo["geo_class"],
            feature_keys=positive, feature_required_keys=required,
            search_a=fold(title), search_b=fold(p.employer_name),
            search_c=fold(" ".join(x for x in (p.occupation_label, p.occupation_field, occ.name if occ else None, feature_labels,
                                               " ".join(loc.locality or "" for loc in p.locations)) if x)),
        )
        for i, (loc, m) in enumerate(zip(p.locations, matches, strict=True)):
            v.locations.append(PostingLocation(
                ordinal=i, raw_text=(loc.raw or loc.locality or "")[:300] or None, locality=loc.locality, postal_code=(loc.postal_code or None),
                region_text=loc.region, country=(loc.country or None), kreis_key=m.kreis_key, state_key=m.state_key, ags=m.ags,
                gebietsstand=m.gebietsstand, match_method=m.method, precision=m.precision, confidence=m.confidence,
                point=f"SRID=4326;POINT({m.lon} {m.lat})" if m.lat is not None and m.lon is not None else None,
                point_origin=m.point_origin,
            ))
        for f in feats:
            v.features.append(PostingFeature(
                feature_key=f.key, type=f.type, label=f.label, polarity=f.polarity, origin=f.origin,
                rule_version=CLASSIFIER_VERSION, confidence=f.confidence, evidence=f.evidence if store_ev else None, detail=f.detail,
            ))
        return v, matches

    def apply_parsed(self, sp: SourcePosting, p: ParsedPosting) -> PostingVersion | None:
        """Übernimmt extrahierte Rumpfdaten; erzeugt nur bei tatsächlicher Änderung eine neue Version."""
        now = datetime.now(UTC)
        run = self.run
        self.stats["extracted"] += 1
        new_v, _ = self.build_version(sp, p)
        cur = self.db.get(PostingVersion, sp.current_version_id) if sp.current_version_id else None
        list_hash = new_v.content_hash if p.detail_level == "list" else None
        if p.detail_level == "detail":
            sp.last_detail_check_at = now
            sp.detail_due = False
        if cur is not None:
            if p.detail_level == "list" and cur.detail_level == "detail":
                # Listendaten können eine Detailversion nicht ersetzen; Änderung => Detailprüfung fällig
                if sp.list_hash and list_hash != sp.list_hash:
                    sp.detail_due = True
                sp.list_hash = list_hash
                return None
            if new_v.content_hash == cur.content_hash:
                sp.raw_hash = new_v.raw_hash or sp.raw_hash
                if list_hash:
                    sp.list_hash = list_hash
                return None
            if cur.detail_level == "list" and p.detail_level == "detail":
                kind = "enrichment"
            elif new_v.raw_hash and sp.raw_hash and new_v.raw_hash == sp.raw_hash:
                kind = "parser"  # Rohinhalt unverändert => Unterschied stammt aus Parser-/Klassifikationsregeln
            elif cur.parser_version != new_v.parser_version or cur.classifier_version != new_v.classifier_version:
                kind = "mixed"  # Inhalt und Regeln geändert – nicht trennbar, wird gesondert gekennzeichnet
            else:
                kind = "content"
            new_v.version_no = cur.version_no + 1
            new_v.change_kind = kind
            cur.valid_to = run.logical_date
        else:
            new_v.version_no = 1
            new_v.change_kind = "initial"
        self.db.add(new_v)
        self.db.flush()
        sp.current_version_id = new_v.id
        sp.raw_hash = new_v.raw_hash
        if list_hash:
            sp.list_hash = list_hash
        sp.canonical_url = p.canonical_url or sp.canonical_url
        sp.employer_id = self._employer_id(p.employer_name, new_v.is_agency)
        if cur is not None and new_v.change_kind in ("content", "parser", "mixed"):
            self.stats["changed"] += 1 if new_v.change_kind == "content" else 0
            self.db.add(PostingEvent(
                event_date=run.logical_date, effective_date=run.logical_date,
                event_type="content_change" if new_v.change_kind == "content" else "parser_change",
                merged_posting_id=sp.merged_posting_id, source_posting_id=sp.id, version_id=new_v.id, run_id=run.id,
                details={"change_kind": new_v.change_kind, "changed": _diff(cur, new_v)},
            ))
        self.db.flush()
        dedup.assign_cluster(self.db, sp, new_v, run_id=run.id, logical_date=run.logical_date)
        return new_v

    def ingest_detail(self, sp: SourcePosting, p: ParsedPosting) -> PostingVersion | None:
        v = self.apply_parsed(sp, p)
        self._record_observation(sp, seen_list=False, seen_detail=True)
        return v

    def detail_unchanged(self, sp: SourcePosting) -> None:
        """Detailseite per bedingtem Abruf unverändert (HTTP 304)."""
        sp.last_detail_check_at = datetime.now(UTC)
        sp.detail_due = False
        self._record_observation(sp, seen_list=False, seen_detail=True)

    def detail_gone(self, sp: SourcePosting, status_code: int) -> None:
        """Echte Nichtverfügbarkeit (HTTP 404/410) – zählt je Kalendertag höchstens einmal."""
        if sp.gone_last_date != self.run.logical_date:
            sp.gone_confirmations += 1
            sp.gone_last_date = self.run.logical_date
        sp.detail_due = False
        sp.last_detail_check_at = datetime.now(UTC)
        sp.status_reason = f"Detailseite nicht verfügbar (HTTP {status_code}), Bestätigung {sp.gone_confirmations}"

    def detail_ended(self, sp: SourcePosting, reason: str) -> None:
        """Eindeutiger Ablaufhinweis der Quelle auf der Detailseite."""
        from .status import leave_stock

        sp.detail_due = False
        sp.last_detail_check_at = datetime.now(UTC)
        if sp.status in IN_STOCK:
            leave_stock(self.db, sp, "ended", reason, self.run.logical_date, end_date=self.run.logical_date, run_id=self.run.id)


def _diff(old: PostingVersion, new: PostingVersion) -> list[str]:
    fields = ("title_norm", "employer_norm", "reference", "employer_url", "kind", "working_time", "contract_term", "remote_type",
              "salary_min", "salary_max", "salary_text", "apply_until", "valid_through", "feature_keys", "feature_required_keys",
              "kreis_keys", "occupation_label")
    changed = [f for f in fields if getattr(old, f) != getattr(new, f)]
    old_feats = {(f.feature_key, f.polarity) for f in old.features}
    new_feats = {(f.feature_key, f.polarity) for f in new.features}
    if old_feats != new_feats and "feature_keys" not in changed:
        changed.append("feature_polarity")
    old_locs = sorted((loc.locality or "", loc.postal_code or "") for loc in old.locations)
    new_locs = sorted((loc.locality or "", loc.postal_code or "") for loc in new.locations)
    if old_locs != new_locs:
        changed.append("locations")
    return changed


def rematch_unresolved(db: Session, limit: int = 200_000) -> int:
    """Nachgeoreferenzierung nach Import/Aktualisierung der Ortsreferenz.

    Ergänzt ausschließlich bisher fehlende Zuordnungen aktueller Versionen; belegte Zuordnungen bleiben
    unverändert (historische Ortszuordnungen werden nicht überschrieben).
    """
    from ..sources.base import RawLocation

    geo = GeoMatcher(db)
    rows = db.execute(sql(
        "SELECT DISTINCT pv.id FROM posting_version pv JOIN posting_location pl ON pl.version_id = pv.id "
        "WHERE pv.valid_to IS NULL AND pl.kreis_key IS NULL AND pl.precision IN ('unresolved') LIMIT :lim"), {"lim": limit}).scalars().all()
    n = 0
    for vid in rows:
        v = db.get(PostingVersion, vid)
        if v is None:
            continue
        matches: list[GeoMatch] = []
        for loc in v.locations:
            if loc.kreis_key is None and loc.precision == "unresolved":
                m = geo.match(RawLocation(locality=loc.locality, postal_code=loc.postal_code, region=loc.region_text, country=loc.country))
                loc.kreis_key, loc.state_key, loc.ags = m.kreis_key, m.state_key, m.ags
                loc.match_method, loc.precision, loc.confidence, loc.gebietsstand = m.method, m.precision, m.confidence, m.gebietsstand
                if m.lat is not None and m.lon is not None:
                    loc.point = f"SRID=4326;POINT({m.lon} {m.lat})"
                    loc.point_origin = m.point_origin
                matches.append(m)
            else:
                matches.append(GeoMatch(kreis_key=loc.kreis_key, state_key=loc.state_key, precision=loc.precision, method=loc.match_method,
                                        nationwide=loc.precision == "country"))
        geo_sum = summarize_geo(matches, v.remote_type)
        v.kreis_keys, v.state_keys = geo_sum["kreis_keys"], geo_sum["state_keys"]
        v.loc_total, v.loc_unresolved, v.geo_class = geo_sum["loc_total"], geo_sum["loc_unresolved"], geo_sum["geo_class"]
        v.geo_rule_version = GEO_RULE_VERSION
        q = dict(v.quality or {})
        q["geo_class"] = v.geo_class
        q["geo_rematched"] = True
        v.quality = q
        n += 1
        if n % 500 == 0:
            db.flush()
    db.flush()
    return n
