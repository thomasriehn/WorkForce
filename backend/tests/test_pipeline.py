"""Fachliche Kernrisiken der Erfassung: Idempotenz, Versionen, Status, Fehlersignale (alles synthetisch)."""
from __future__ import annotations

from datetime import date, timedelta

import pytest
from sqlalchemy import func, select

from workforce.crawl.fetcher import BlockedError, TransientError
from workforce.models import ActivityPeriod, MergedPosting, Observation, PostingEvent, PostingVersion, ScanError, ScanRun, SourcePosting
from workforce.sources.base import ParseError

from .helpers import FakeAdapter, make_source, posting, run_scan

D0 = date(2026, 11, 2)


def count(db, model, *where):
    return db.execute(select(func.count()).select_from(model).where(*where)).scalar_one()


def test_identical_daily_run_is_idempotent(db):
    """Abnahme 3: wiederholter identischer Tageslauf erzeugt keine doppelten Anzeigen/Versionen/Beobachtungen."""
    _, scope = make_source(db)
    pages = [[posting("a1"), posting("a2", title="Erzieher (m/w/d)")], [posting("a3", title="Gärtner (m/w/d)")]]
    r1 = run_scan(db, scope, D0, FakeAdapter(pages))
    assert r1.status == "complete" and r1.list_complete and r1.is_baseline
    before = (count(db, SourcePosting), count(db, PostingVersion), count(db, Observation), count(db, MergedPosting), count(db, PostingEvent))
    assert before[:4] == (3, 3, 3, 3)
    # derselbe logische Tag: es gibt genau einen Lauf, erneutes Ausführen ändert nichts
    r1b = run_scan(db, scope, D0, FakeAdapter(pages))
    assert r1b.id == r1.id and count(db, ScanRun) == 1
    # nächster Tag, identischer Inhalt: neue Beobachtungen, aber keine neuen Anzeigen/Versionen
    r2 = run_scan(db, scope, D0 + timedelta(days=1), FakeAdapter(pages))
    assert r2.status == "complete" and not r2.is_baseline
    assert (count(db, SourcePosting), count(db, PostingVersion), count(db, MergedPosting)) == (3, 3, 3)
    assert count(db, Observation) == 6 and r2.postings_new == 0 and r2.postings_changed == 0


def test_content_change_creates_version_tracking_param_does_not(db):
    """Abnahme 5: geänderte Qualifikationsanforderung ⇒ fachliche Version; Trackingparameter allein ⇒ keine."""
    _, scope = make_source(db)
    text1 = "Ihr Profil\n- Abgeschlossene Berufsausbildung erforderlich\n- Kenntnisse in Python sind von Vorteil"
    text2 = "Ihr Profil\n- Abgeschlossenes Studium (Bachelor) erforderlich\n- Kenntnisse in Python sind zwingend erforderlich"
    run_scan(db, scope, D0, FakeAdapter([[posting("x1", description=text1)]]))
    sp = db.execute(select(SourcePosting)).scalar_one()
    v1 = db.get(PostingVersion, sp.current_version_id)
    assert "qual:berufsausbildung" in v1.feature_required_keys and "skill:python" in v1.feature_keys
    # gleicher Inhalt, nur Trackingparameter in der URL und anderes Abrufdatum
    p_same = posting("x1", description=text1)
    p_same.url += "?utm_source=newsletter&track=feed-jobs"
    run_scan(db, scope, D0 + timedelta(days=1), FakeAdapter([[p_same]]))
    assert count(db, PostingVersion) == 1
    run_scan(db, scope, D0 + timedelta(days=2), FakeAdapter([[posting("x1", description=text2)]]))
    db.expire_all()
    versions = db.execute(select(PostingVersion).order_by(PostingVersion.version_no)).scalars().all()
    assert [v.change_kind for v in versions] == ["initial", "content"]
    assert versions[0].valid_to == D0 + timedelta(days=2) and versions[1].valid_to is None
    assert "qual:bachelor" in versions[1].feature_required_keys and "skill:python" in versions[1].feature_required_keys
    # die historische Version bleibt unverändert erhalten
    assert "qual:berufsausbildung" in versions[0].feature_required_keys
    ev = db.execute(select(PostingEvent).where(PostingEvent.event_type == "content_change")).scalar_one()
    assert "feature_keys" in ev.details["changed"] or "feature_required_keys" in ev.details["changed"]


def test_parser_change_is_flagged_separately(db):
    """Neue Parser-/Klassifikationsregeln bei unverändertem Rohinhalt sind keine fachliche Änderung."""
    _, scope = make_source(db)
    p1 = posting("p1", description="Ihr Profil\n- Python erforderlich")
    run_scan(db, scope, D0, FakeAdapter([[p1]]))
    p2 = posting("p1", description="Ihr Profil\n- Python erforderlich")
    p2.working_time = ["vollzeit"]  # der „neue Parser“ erkennt zusätzlich die Arbeitszeit
    p2.raw_payload = p1.raw_payload
    run_scan(db, scope, D0 + timedelta(days=1), FakeAdapter([[p2]], version="fake-2"))
    kinds = db.execute(select(PostingVersion.change_kind).order_by(PostingVersion.version_no)).scalars().all()
    assert kinds == ["initial", "parser"]
    assert count(db, PostingEvent, PostingEvent.event_type == "content_change") == 0
    assert count(db, PostingEvent, PostingEvent.event_type == "parser_change") == 1


def test_missing_only_after_three_complete_scans(db):
    """Abnahme 6/Status: erst nach drei vollständigen vergleichbaren Scans „vermutlich entfernt“."""
    _, scope = make_source(db)
    both = [[posting("k1"), posting("k2", title="Koch (m/w/d)")]]
    only1 = [[posting("k1")]]
    run_scan(db, scope, D0, FakeAdapter(both))
    states = []
    for i in range(1, 4):
        run_scan(db, scope, D0 + timedelta(days=i), FakeAdapter(only1))
        db.expire_all()
        states.append(db.execute(select(SourcePosting.status).where(SourcePosting.source_key == "k2")).scalar_one())
    assert states == ["not_reobserved", "not_reobserved", "presumed_removed"]
    sp = db.execute(select(SourcePosting).where(SourcePosting.source_key == "k2")).scalar_one()
    assert "Ableitung" in sp.status_reason
    period = db.execute(select(ActivityPeriod).where(ActivityPeriod.source_posting_id == sp.id)).scalar_one()
    assert period.end_date == D0 and period.end_reason == "presumed_removed"  # Bestand endet am letzten Sichtungstag
    left = db.execute(select(PostingEvent).where(PostingEvent.event_type == "left_stock")).scalar_one()
    assert left.effective_date == D0 + timedelta(days=1)
    # Wiederauftauchen derselben Quell-ID = Reaktivierung, keine neue Anzeige
    run_scan(db, scope, D0 + timedelta(days=4), FakeAdapter(both))
    db.expire_all()
    sp = db.execute(select(SourcePosting).where(SourcePosting.source_key == "k2")).scalar_one()
    assert sp.status == "active" and count(db, SourcePosting) == 2
    assert count(db, PostingEvent, PostingEvent.event_type == "reactivation") == 1
    assert count(db, ActivityPeriod, ActivityPeriod.source_posting_id == sp.id) == 2


@pytest.mark.parametrize("failure", ["timeout", "captcha", "http403", "layout", "cap", "page_limit", "repeat", "coverage"])
def test_failures_never_archive_postings(db, failure):
    """Abnahme 6: Timeout, CAPTCHA, 403, Layoutänderung, Trefferlimit, unvollständige Pagination ⇒ kein Nachfrageeinbruch."""
    _, scope = make_source(db)
    full = [[posting(f"n{i}", title=f"Stelle {i}") for i in range(6)], [posting(f"n{i}", title=f"Stelle {i}") for i in range(6, 12)]]
    run_scan(db, scope, D0, FakeAdapter(full))
    assert count(db, SourcePosting, SourcePosting.status == "active") == 12

    def boom(exc):
        def behaviour(i):
            if i == 0:
                raise exc
        return behaviour

    expected = {"timeout": "failed", "captcha": "blocked", "http403": "blocked", "layout": "failed", "cap": "partial",
                "page_limit": "partial", "repeat": "partial", "coverage": "partial"}[failure]
    for day in range(1, 6):  # fünf Tage in Folge gestört – mehr als die Schwelle von drei Scans
        d = D0 + timedelta(days=day)
        if failure == "timeout":
            run = run_scan(db, scope, d, FakeAdapter(full, behaviour=boom(TransientError("Timeout", url="https://portal.example/l"))))
        elif failure == "captcha":
            run = run_scan(db, scope, d, FakeAdapter(full, behaviour=boom(BlockedError("Bot-Schutz/CAPTCHA erkannt", url="https://portal.example/l", status=200))))
        elif failure == "http403":
            run = run_scan(db, scope, d, FakeAdapter(full, behaviour=boom(BlockedError("HTTP 403", url="https://portal.example/l", status=403))))
        elif failure == "layout":
            run = run_scan(db, scope, d, FakeAdapter(full, behaviour=boom(ParseError("Trefferliste nicht gefunden"))))
        elif failure == "cap":
            run = run_scan(db, scope, d, FakeAdapter(full[:1], reported_total=50_000, capped=True))
        elif failure == "page_limit":
            run = run_scan(db, scope, d, FakeAdapter(full, reported_total=12), page_limit=1)
        elif failure == "repeat":
            run = run_scan(db, scope, d, FakeAdapter([full[0], full[0], full[1]]))
        else:
            run = run_scan(db, scope, d, FakeAdapter(full[:1], complete=False))
        assert run.status == expected, run.status_detail
        assert run.status != "complete"
    db.expire_all()
    # keine einzige Anzeige wurde archiviert oder als entfernt gewertet
    assert count(db, SourcePosting, SourcePosting.status.in_(("presumed_removed", "ended"))) == 0
    assert count(db, PostingEvent, PostingEvent.event_type == "left_stock") == 0
    assert count(db, ActivityPeriod, ActivityPeriod.end_date.isnot(None)) == 0
    if expected != "partial" or failure in ("cap", "repeat"):
        assert count(db, ScanError) >= 5


def test_new_only_scope_never_counts_misses_but_honours_announced_end(db):
    """Feed-artige Quelle (nur neue Anzeigen): Fehlen ist kein Signal; Ende laut angekündigtem Veröffentlichungsende."""
    _, scope = make_source(db, mode="new_only")
    p = posting("f1")
    p.valid_through = D0 + timedelta(days=5)
    run_scan(db, scope, D0, FakeAdapter([[p, posting("f2", title="Ohne Enddatum")]]))
    for i in range(1, 6):
        run_scan(db, scope, D0 + timedelta(days=i), FakeAdapter([[posting(f"neu{i}", title=f"Neu {i}")]]))
    db.expire_all()
    assert db.execute(select(SourcePosting.status).where(SourcePosting.source_key == "f1")).scalar_one() == "active"
    assert db.execute(select(SourcePosting.status).where(SourcePosting.source_key == "f2")).scalar_one() == "active"
    run_scan(db, scope, D0 + timedelta(days=6), FakeAdapter([[posting("neu6", title="Neu 6")]]))
    db.expire_all()
    sp = db.execute(select(SourcePosting).where(SourcePosting.source_key == "f1")).scalar_one()
    assert sp.status == "ended" and "Veröffentlichungsende" in sp.status_reason
    # ohne Enddatum: nach Ablauf der Frist „unbekannt/veraltet“, nicht „entfernt“
    run_scan(db, scope, D0 + timedelta(days=20), FakeAdapter([[posting("neu20", title="Neu 20")]]))
    db.expire_all()
    assert db.execute(select(SourcePosting.status).where(SourcePosting.source_key == "f2")).scalar_one() == "stale"


def test_no_contact_data_is_persisted(db):
    """Ansprechpartner- und Kontaktdaten gehören nicht zum Erfassungsumfang – auch nicht über Belegauszüge."""
    from sqlalchemy import text as sql

    _, scope = make_source(db)
    text = ("Ihr Profil\n- Abgeschlossenes Studium (Bachelor) erforderlich, Nachweise an bewerbung@example.invalid oder Tel. 030 12345678\n"
            "- Sehr gute Englischkenntnisse erforderlich\n"
            "Für Rückfragen zur Berufserfahrung steht Ihnen Frau Erika Mustermann (erika.mustermann@example.invalid, +49 30 259359220) zur Verfügung.")
    run_scan(db, scope, D0, FakeAdapter([[posting("c1", "Referent (m/w/d)", "Behörde Test", description=text)]]))
    dump = " ".join(str(r) for r in db.execute(sql(
        "SELECT pv.title, pv.excerpts::text, pv.quality::text, pv.search_a, pv.search_b, pv.search_c, coalesce(string_agg(pf.evidence || ' ' || coalesce(pf.detail, ''), ' | '), '') "
        "FROM posting_version pv LEFT JOIN posting_feature pf ON pf.version_id = pv.id GROUP BY pv.id")).all())
    for secret in ("example.invalid", "12345678", "259359220", "Mustermann", "mustermann"):
        assert secret not in dump, secret
    v = db.execute(select(PostingVersion)).scalar_one()
    assert {"qual:bachelor", "lang:en", "exp:berufserfahrung"} <= set(v.feature_keys)  # die Merkmale selbst bleiben erhalten
    assert any("Bachelor" in e and "[…]" in e for e in v.excerpts)


def test_interrupted_run_resumes_from_checkpoint_without_duplicates(db):
    """Abnahme 3: unterbrochene Läufe (Pause, Absturz, Seitenlimit) werden kontrolliert am Checkpoint fortgesetzt."""
    from sqlalchemy import text as sql

    from workforce import db as wf_db
    from workforce.config import get_settings
    from workforce.models import ScanTask
    from workforce.pipeline.run import execute_run, request_control

    from .helpers import fetcher_factory

    _, scope = make_source(db)
    pages = [[posting(f"r{p}{i}", f"Stelle {p}-{i}") for i in range(3)] for p in range(4)]
    today = date.today()
    fetched: list[int] = []

    def pause_after_second_page(i: int) -> None:
        fetched.append(i)
        if i == 1:  # Administrator fordert während des Laufs eine Pause an
            with wf_db.session_scope() as s:
                s.execute(sql("UPDATE scan_run SET control = 'pause'"))

    run = run_scan(db, scope, today, FakeAdapter(pages, behaviour=pause_after_second_page))
    assert run.status == "paused" and run.pages_fetched == 2 and count(db, SourcePosting) == 6
    task = db.execute(select(ScanTask)).scalar_one()
    assert task.checkpoint["page"] == 2  # Checkpoint zeigt auf die nächste Seite
    # Fortsetzung: nur die fehlenden Seiten werden gelesen
    request_control(db, run, "resume")
    db.commit()
    fetched.clear()
    execute_run(run.id, settings=get_settings(), fetcher_factory=fetcher_factory(), adapter=FakeAdapter(pages, behaviour=fetched.append))
    db.expire_all()
    run = db.get(ScanRun, run.id)
    assert fetched == [2, 3] and run.status == "complete" and run.pages_fetched == 4 and run.attempts == 2
    assert (count(db, SourcePosting), count(db, PostingVersion), count(db, Observation), count(db, ScanRun)) == (12, 12, 12, 1)

    # Absturz mitten im Lauf: Status bleibt „running“; die erneute Ausführung setzt am Checkpoint fort
    _, scope2 = make_source(db, "zweite", domain="z.example")
    pages2 = [[posting(f"z{p}{i}", f"Z {p}-{i}", domain="z.example") for i in range(2)] for p in range(3)]

    class Crash(RuntimeError):
        pass

    def crash_on_third(i: int) -> None:
        if i == 2:
            raise Crash("Prozess beendet")

    with pytest.raises(Crash):
        run_scan(db, scope2, today, FakeAdapter(pages2, behaviour=crash_on_third))
    db.expire_all()
    run2 = db.execute(select(ScanRun).where(ScanRun.scope_id == scope2.id)).scalar_one()
    assert run2.status == "running" and run2.pages_fetched == 2
    again: list[int] = []
    execute_run(run2.id, settings=get_settings(), fetcher_factory=fetcher_factory(), adapter=FakeAdapter(pages2, behaviour=again.append))
    db.expire_all()
    assert again == [2] and db.get(ScanRun, run2.id).status == "complete"
    assert count(db, Observation, Observation.run_id == run2.id) == 6

    # Seitenlimit ⇒ partiell; kontrollierte Wiederholung am selben Tag vervollständigt denselben logischen Lauf
    _, scope3 = make_source(db, "dritte", domain="d.example")
    pages3 = [[posting(f"d{p}{i}", f"D {p}-{i}", domain="d.example") for i in range(2)] for p in range(3)]
    run3 = run_scan(db, scope3, today, FakeAdapter(pages3), page_limit=1)
    assert run3.status == "partial" and "Seitenlimit" in run3.status_detail
    run3.page_limit = None
    request_control(db, run3, "retry")
    db.commit()
    execute_run(run3.id, settings=get_settings(), fetcher_factory=fetcher_factory(), adapter=FakeAdapter(pages3))
    db.expire_all()
    run3 = db.get(ScanRun, run3.id)
    assert run3.status == "complete" and count(db, Observation, Observation.run_id == run3.id) == 6 and count(db, ScanRun, ScanRun.scope_id == scope3.id) == 1
    # abgeschlossene Läufe werden nicht erneut ausgeführt
    assert execute_run(run3.id, settings=get_settings(), fetcher_factory=fetcher_factory(), adapter=FakeAdapter(pages3, behaviour=lambda i: (_ for _ in ()).throw(AssertionError("darf nicht laufen")))) == "complete"


def test_overlapping_runs_of_same_source_are_refused(db):
    """Schutz vor überlappenden Läufen derselben Quelle und Konfiguration."""
    from workforce.config import get_settings
    from workforce.pipeline.run import RunRefused, create_run, execute_run

    from .helpers import fetcher_factory

    _, scope = make_source(db)
    run, _ = create_run(db, scope, D0, "manual")
    test_run, _ = create_run(db, scope, D0, "manual", page_limit=1, is_test=True)
    db.commit()
    outcome: list[str] = []

    def nested(i: int) -> None:  # während der erste Lauf arbeitet, startet ein zweiter für dieselbe Quelle/Konfiguration
        try:
            execute_run(test_run.id, settings=get_settings(), fetcher_factory=fetcher_factory(), adapter=FakeAdapter([[posting("n1")]]))
            outcome.append("lief")
        except RunRefused as exc:
            outcome.append(str(exc))

    execute_run(run.id, settings=get_settings(), fetcher_factory=fetcher_factory(), adapter=FakeAdapter([[posting("a1")]], behaviour=nested))
    assert outcome and "läuft bereits" in outcome[0]
    db.expire_all()
    assert db.get(ScanRun, run.id).status == "complete" and count(db, SourcePosting) == 1
