"""Portalübergreifende Zusammenführung von Quellanzeigen (``DEDUP_RULE_VERSION``).

Regeln in absteigender Stärke – ein ähnlicher Titel allein genügt nie:
* R1 ``employer_reference``: gleicher Arbeitgeber + gleiche Stellenreferenz des Arbeitgebers (0,95)
* R2 ``employer_url``: identischer Arbeitgeber-Zielverweis (Deep-Link, ohne Trackingparameter) (0,90)
* R3 ``employer_title_location``: gleicher Arbeitgeber, gleicher normalisierter Titel, gleiche Anzeigenart,
  gleiche Kreis-Menge, Veröffentlichungsdaten höchstens 45 Tage auseinander, keine Personalvermittlung (0,82)

Schutzregeln: disjunkte Arbeitsorte (Niederlassungen), Personalvermittler und zwei gleichzeitig aktive
Anzeigen derselben Quelle werden nicht automatisch vereinigt, sondern als unsicherer Kandidat vorgemerkt.
Jede Entscheidung wird mit Grund, Konfidenz und Regelversion gespeichert und ist umkehrbar.
"""
from __future__ import annotations

import logging
from datetime import UTC, date, datetime, timedelta
from typing import Any

from sqlalchemy import select, text as sql, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import Session

from ..config import DEDUP_RULE_VERSION
from ..models import IN_STOCK, MergeBlock, MergeCandidate, MergedPosting, MergeLink, PostingEvent, PostingVersion, SourcePosting

log = logging.getLogger(__name__)
AUTO_MERGE_MIN = 0.8
DATE_WINDOW_DAYS = 45
STATUS_RANK = {"active": 5, "not_reobserved": 4, "stale": 3, "ended": 2, "presumed_removed": 1}

_CAND_SQL = """
SELECT sp.id AS sp_id, sp.source_id, sp.status, sp.merged_posting_id, pv.id AS version_id, pv.title_norm, pv.employer_norm,
       pv.reference, pv.employer_url, pv.kind, pv.kreis_keys, pv.is_agency, pv.date_posted,
       similarity(pv.title_norm, CAST(:title AS text)) AS title_sim
FROM posting_version pv
JOIN source_posting sp ON sp.current_version_id = pv.id
WHERE sp.id <> :sp_id AND sp.merged_posting_id IS NOT NULL AND sp.is_synthetic = :synthetic
  AND ( (pv.employer_norm = CAST(:employer AS text) AND pv.reference = CAST(:reference AS text) AND CAST(:reference AS text) IS NOT NULL)
     OR (pv.employer_url = CAST(:employer_url AS text) AND CAST(:employer_url AS text) IS NOT NULL)
     OR (pv.employer_norm = CAST(:employer AS text) AND CAST(:employer AS text) IS NOT NULL AND (pv.title_norm = CAST(:title AS text) OR pv.title_norm % CAST(:title AS text))) )
ORDER BY sp.first_seen_at, sp.id
LIMIT 50
"""


def _blocked(db: Session, a: int, b: int) -> bool:
    lo, hi = min(a, b), max(a, b)
    return db.get(MergeBlock, (lo, hi)) is not None


def evaluate_pair(v: PostingVersion, sp: SourcePosting, c: dict[str, Any]) -> tuple[str, float] | None:
    """Bewertet ein Kandidatenpaar → (Grund, Konfidenz) oder None. Konfidenz < 0,8 = nur Kandidat."""
    same_employer = bool(v.employer_norm) and v.employer_norm == c["employer_norm"]
    my_kreise, their_kreise = set(v.kreis_keys or []), set(c["kreis_keys"] or [])
    disjoint = bool(my_kreise) and bool(their_kreise) and not (my_kreise & their_kreise)
    same_source_parallel = sp.source_id == c["source_id"] and sp.status in IN_STOCK and c["status"] in IN_STOCK
    agency = bool(v.is_agency) or bool(c["is_agency"])
    result: tuple[str, float] | None = None
    ref = (v.reference or "").strip()
    if same_employer and ref and len(ref) >= 3 and ref == (c["reference"] or "").strip():
        result = ("employer_reference", 0.95)
    elif v.employer_url and v.employer_url == c["employer_url"]:
        result = ("employer_url", 0.90)
    elif same_employer and v.title_norm and v.title_norm == c["title_norm"] and v.kind == c["kind"]:
        dates_ok = True
        if v.date_posted and c["date_posted"]:
            dates_ok = abs((v.date_posted - c["date_posted"]).days) <= DATE_WINDOW_DAYS
        if my_kreise and my_kreise == their_kreise and dates_ok:
            result = ("employer_title_location", 0.82)
        elif my_kreise & their_kreise:
            result = ("employer_title_overlap", 0.6)
    elif same_employer and (c["title_sim"] or 0) >= 0.85 and (my_kreise & their_kreise) and v.kind == c["kind"]:
        result = ("employer_similar_title", 0.5)
    if result is None:
        return None
    reason, conf = result
    # Schutzregeln: echte parallele Ausschreibungen nicht unbegründet vereinigen
    if conf >= AUTO_MERGE_MIN:
        if disjoint:
            return (reason + "+disjoint_locations", 0.55)
        if same_source_parallel:
            return (reason + "+parallel_same_source", 0.6)
        if agency and reason == "employer_title_location":
            return (reason + "+agency", 0.6)
    return reason, conf


def assign_cluster(db: Session, sp: SourcePosting, v: PostingVersion, *, run_id: int | None, logical_date: date) -> int:
    """Ordnet eine Quellanzeige einer zusammengeführten Anzeige zu (oder legt eine neue an)."""
    if sp.merged_posting_id is not None:
        refresh_merged(db, sp.merged_posting_id)
        return sp.merged_posting_id
    cands = db.execute(sql(_CAND_SQL), {
        "sp_id": sp.id, "employer": v.employer_norm, "reference": v.reference, "employer_url": v.employer_url,
        "title": v.title_norm or "", "synthetic": sp.is_synthetic,
    }).mappings().all()
    best: tuple[dict[str, Any], str, float] | None = None
    for c in cands:
        if _blocked(db, sp.id, c["sp_id"]):
            continue
        res = evaluate_pair(v, sp, dict(c))
        if res is None:
            continue
        reason, conf = res
        if conf >= AUTO_MERGE_MIN:
            if best is None or conf > best[2]:
                best = (dict(c), reason, conf)
        else:
            lo, hi = min(sp.id, c["sp_id"]), max(sp.id, c["sp_id"])
            db.execute(pg_insert(MergeCandidate).values(
                a_source_posting_id=lo, b_source_posting_id=hi, reason=reason[:60], score=conf, rule_version=DEDUP_RULE_VERSION,
            ).on_conflict_do_nothing(index_elements=["a_source_posting_id", "b_source_posting_id"]))
    now = datetime.now(UTC)
    if best is not None:
        c, reason, conf = best
        mp_id = int(c["merged_posting_id"])
        mp = db.get(MergedPosting, mp_id)
        assert mp is not None
        was_in_stock = mp.status in IN_STOCK
        _link(db, mp_id, sp, reason, conf, matched=c["sp_id"])
        db.add(PostingEvent(
            event_date=logical_date, effective_date=logical_date,
            event_type="additional_source" if was_in_stock else "republication",
            merged_posting_id=mp_id, source_posting_id=sp.id, version_id=v.id, run_id=run_id, baseline=sp.first_seen_baseline,
            details={"reason": reason, "confidence": conf, "matched_source_posting_id": c["sp_id"], "rule_version": DEDUP_RULE_VERSION},
        ))
    else:
        mp = MergedPosting(
            status=sp.status, first_seen_at=sp.first_seen_at, first_seen_date=sp.first_seen_date,
            first_seen_baseline=sp.first_seen_baseline, last_seen_at=sp.last_seen_at, last_seen_date=sp.last_seen_date,
            member_count=1, source_ids=[sp.source_id], dedup_rule_version=DEDUP_RULE_VERSION, is_synthetic=sp.is_synthetic,
        )
        db.add(mp)
        db.flush()
        mp_id = mp.id
        _link(db, mp_id, sp, "singleton", 1.0, matched=None)
        db.add(PostingEvent(
            at=now, event_date=logical_date, effective_date=logical_date, event_type="first_seen", merged_posting_id=mp_id,
            source_posting_id=sp.id, version_id=v.id, run_id=run_id, baseline=sp.first_seen_baseline,
        ))
    db.flush()
    refresh_merged(db, mp_id)
    return mp_id


def _link(db: Session, mp_id: int, sp: SourcePosting, reason: str, conf: float, *, matched: int | None, decided_by: str = "auto") -> None:
    db.execute(update(MergeLink).where(MergeLink.source_posting_id == sp.id, MergeLink.is_active).values(
        is_active=False, undone_at=datetime.now(UTC), undone_by=decided_by))
    db.add(MergeLink(merged_posting_id=mp_id, source_posting_id=sp.id, matched_source_posting_id=matched, reason=reason[:40],
                     confidence=conf, rule_version=DEDUP_RULE_VERSION, decided_by=decided_by))
    sp.merged_posting_id = mp_id
    db.flush()


def refresh_merged(db: Session, mp_id: int) -> None:
    """Leitet Zustand und Zeiger der zusammengeführten Anzeige aus ihren Mitgliedern ab."""
    mp = db.get(MergedPosting, mp_id)
    if mp is None:
        return
    members = db.execute(select(SourcePosting).where(SourcePosting.merged_posting_id == mp_id).order_by(SourcePosting.first_seen_at, SourcePosting.id)).scalars().all()
    if not members:
        db.delete(mp)
        return
    with_version = [m for m in members if m.current_version_id is not None] or members
    primary = with_version[0]
    mp.primary_source_posting_id = primary.id
    mp.current_version_id = primary.current_version_id
    mp.status = max((m.status for m in members), key=lambda s: STATUS_RANK.get(s, 0))
    first = min(members, key=lambda m: (m.first_seen_at, m.id))
    mp.first_seen_at, mp.first_seen_date, mp.first_seen_baseline = first.first_seen_at, first.first_seen_date, first.first_seen_baseline
    last = max(members, key=lambda m: m.last_seen_at)
    mp.last_seen_at, mp.last_seen_date = last.last_seen_at, last.last_seen_date
    mp.member_count = len(members)
    mp.source_ids = sorted({m.source_id for m in members})
    mp.dedup_rule_version = DEDUP_RULE_VERSION
    db.flush()


def split_member(db: Session, source_posting_id: int, username: str) -> int:
    """Macht eine Zusammenführung rückgängig: Quellanzeige wird wieder eigenständig (und bleibt es)."""
    sp = db.get(SourcePosting, source_posting_id)
    if sp is None or sp.merged_posting_id is None:
        raise ValueError("Quellanzeige nicht gefunden oder nicht zugeordnet")
    old_id = sp.merged_posting_id
    others = db.execute(select(SourcePosting.id).where(SourcePosting.merged_posting_id == old_id, SourcePosting.id != sp.id)).scalars().all()
    if not others:
        raise ValueError("Anzeige ist nicht mit anderen zusammengeführt")
    for other in others:
        lo, hi = min(sp.id, other), max(sp.id, other)
        db.execute(pg_insert(MergeBlock).values(a_source_posting_id=lo, b_source_posting_id=hi, created_by=username).on_conflict_do_nothing())
    mp = MergedPosting(status=sp.status, first_seen_at=sp.first_seen_at, first_seen_date=sp.first_seen_date,
                       first_seen_baseline=sp.first_seen_baseline, last_seen_at=sp.last_seen_at, last_seen_date=sp.last_seen_date,
                       member_count=1, source_ids=[sp.source_id], dedup_rule_version=DEDUP_RULE_VERSION, is_synthetic=sp.is_synthetic)
    db.add(mp)
    db.flush()
    _link(db, mp.id, sp, "manual_split", 1.0, matched=None, decided_by=username)
    db.execute(update(PostingEvent).where(PostingEvent.source_posting_id == sp.id).values(merged_posting_id=mp.id))
    refresh_merged(db, mp.id)
    refresh_merged(db, old_id)
    return mp.id


def merge_manual(db: Session, source_posting_id: int, target_merged_id: int, username: str) -> None:
    """Manuelle Zusammenführung (z. B. Bestätigung eines unsicheren Kandidaten)."""
    sp = db.get(SourcePosting, source_posting_id)
    target = db.get(MergedPosting, target_merged_id)
    if sp is None or target is None:
        raise ValueError("Anzeige nicht gefunden")
    old_id = sp.merged_posting_id
    if old_id == target_merged_id:
        return
    for other in db.execute(select(SourcePosting.id).where(SourcePosting.merged_posting_id == target_merged_id)).scalars().all():
        lo, hi = min(sp.id, other), max(sp.id, other)
        blk = db.get(MergeBlock, (lo, hi))
        if blk is not None:
            db.delete(blk)
    _link(db, target_merged_id, sp, "manual", 1.0, matched=None, decided_by=username)
    db.execute(update(PostingEvent).where(PostingEvent.source_posting_id == sp.id).values(merged_posting_id=target_merged_id))
    refresh_merged(db, target_merged_id)
    if old_id is not None:
        refresh_merged(db, old_id)


def recheck_window(d: date) -> date:
    return d - timedelta(days=DATE_WINDOW_DAYS)
