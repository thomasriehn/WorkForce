"""API (Login, Rollen, CSRF, Export), Scheduler (ein logischer Tageslauf, Zeitzonen) und Jobqueue."""
from __future__ import annotations

from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select

from workforce.api.app import create_app
from workforce.api.postings import csv_cell, safe_url
from workforce.config import get_settings
from workforce.jobs import queue
from workforce.jobs.scheduler import plan
from workforce.models import Job, ScanRun, Source, User
from workforce.security import hash_password
from workforce.sources.registry import seed_registry

from .helpers import FakeAdapter, make_regions, make_source, posting, run_scan

BERLIN = ZoneInfo("Europe/Berlin")
D0 = date(2026, 11, 2)


@pytest.fixture
def client(db):
    for name, role in (("chefin", "admin"), ("leser", "reader")):
        db.add(User(username=name, role=role, password_hash=hash_password("ein-langes-testpasswort")))
    db.commit()
    return TestClient(create_app())


def login(client: TestClient, user: str) -> dict:
    r = client.post("/api/auth/login", json={"username": user, "password": "ein-langes-testpasswort"})
    assert r.status_code == 200, r.text
    return {"X-CSRF-Token": r.json()["csrf_token"]}


def test_login_roles_csrf_and_lockout(client, db):
    assert client.get("/api/postings").status_code == 401 and client.get("/api/dashboard").status_code == 401
    assert client.get("/healthz").json()["status"] == "ok"
    assert client.post("/api/auth/login", json={"username": "chefin", "password": "falsch"}).status_code == 401
    seed_registry(db)
    db.commit()
    sid = db.execute(select(Source.id).where(Source.key == "service_bund_rss")).scalar_one()
    pr = db.execute(select(Source.id).where(Source.key == "interamt")).scalar_one()
    ba = db.execute(select(Source.id).where(Source.key == "ba_jobsuche")).scalar_one()
    h = login(client, "leser")
    assert client.get("/api/sources").status_code == 200  # Leser dürfen lesen
    assert client.post(f"/api/sources/{sid}/activate", json={"basis": "x" * 30}, headers=h).status_code == 403  # aber nichts ändern
    assert client.get("/api/users").status_code == 403
    h = login(client, "chefin")
    body = {"basis": "robots.txt und Impressum am 10.11.2026 geprüft; offizieller RSS-Feed"}
    assert client.post(f"/api/sources/{sid}/activate", json=body).status_code == 403  # ohne CSRF-Token
    assert client.post(f"/api/sources/{sid}/activate", json={"basis": "ok"}, headers=h).status_code == 422  # Vermerk zu knapp
    r = client.post(f"/api/sources/{sid}/activate", json=body, headers=h)
    assert r.status_code == 200 and r.json()["config_status"] == "active" and "Freigabe am" in r.json()["status_reason"]
    # Quelle mit Erlaubnisvorbehalt: ohne Nachweis keine Freigabe; Quelle ohne Adapter gar nicht
    assert client.post(f"/api/sources/{pr}/activate", json=body, headers=h).status_code == 422
    assert client.post(f"/api/sources/{pr}/activate", json=dict(body, permission_reference="Schreiben der DVZ vom 01.12.2026"), headers=h).status_code == 200
    r = client.post(f"/api/sources/{ba}/activate", json=dict(body, permission_reference="irgendein Nachweis"), headers=h)
    assert r.status_code == 422 and "kein Adapter" in r.json()["detail"]
    assert client.post(f"/api/sources/{ba}/runs", json={"test": True}, headers=h).status_code == 422
    # Register trennt Konfigurationsstatus und technischen Zustand
    reg = {s["key"]: s for s in client.get("/api/sources").json()["sources"]}
    assert reg["service_bund_rss"]["config_status"] == "active" and reg["service_bund_rss"]["health"] == "never_run"
    assert reg["stepstone"]["config_status"] == "permission_required" and reg["stepstone"]["adapter_available"] is False and reg["stepstone"]["health"] == "inactive"
    assert reg["monster"]["config_status"] == "disabled" and len(reg) == 16
    # Benutzeranlage: generiertes Passwort, kein Standardpasswort
    r = client.post("/api/users", json={"username": "neu.leser", "role": "reader"}, headers=h)
    assert r.status_code == 200 and len(r.json()["generated_password"]) >= 20
    assert client.post("/api/users", json={"username": "kurz", "role": "reader", "password": "123"}, headers=h).status_code == 422
    # Sperre nach wiederholten Fehlversuchen
    for _ in range(get_settings().login_max_failures):
        client.post("/api/auth/login", json={"username": "leser", "password": "falsch"})
    assert client.post("/api/auth/login", json={"username": "leser", "password": "ein-langes-testpasswort"}).status_code == 401


def test_search_endpoints_export_and_injection_safety(client, db):
    make_regions(db)
    _, scope = make_source(db)
    evil = posting("e1", '=HYPERLINK("http://evil.example";"klick") <script>alert(1)</script>', "@SUM(A1) GmbH", place="Musterstadt")
    evil.url = "javascript:alert(1)"
    run_scan(db, scope, D0, FakeAdapter([[evil, posting("ok", "C++ Entwickler (m/w/d)", "Amt für Größe", place="Beispielhausen", description="Ihr Profil\n- C++ erforderlich")]]))
    login(client, "leser")
    r = client.get("/api/postings", params={"q": "c++ größe", "features": "skill:cpp"})
    assert r.status_code == 200 and r.json()["total"] == 1 and r.json()["items"][0]["title"] == "C++ Entwickler (m/w/d)"
    assert "nicht gespeichert" in r.json()["scope"]["not_searched"]
    allr = client.get("/api/postings", params={"sort": "title"}).json()
    bad = next(i for i in allr["items"] if "HYPERLINK" in i["title"])
    assert bad["original_url"] is None  # kein javascript:-Verweis an die Oberfläche
    assert client.get("/api/postings", params={"q": "-nur -ausschluss"}).status_code == 422
    csv_text = client.get("/api/postings/export.csv").text
    assert "'=HYPERLINK" in csv_text and "'@SUM" in csv_text and "javascript:" not in csv_text  # Formeln als Text maskiert
    assert csv_cell("+49 123") == "'+49 123" and csv_cell(None) == "" and safe_url("data:text/html,x") is None
    detail = client.get(f"/api/postings/{bad['id']}").json()
    assert detail["members"][0]["original_url"] is None and "besetzt" in " ".join(detail["notes"])
    for path in ("/api/dashboard", "/api/map/metrics", "/api/map/change?days=30", "/api/timeseries", "/api/facets", "/api/meta/filters",
                 "/api/geo/kreise.geojson", "/api/regions", "/api/regions/91001", "/api/stats/overview", "/api/sources", "/api/runs", "/api/system/status"):
        resp = client.get(path)
        assert resp.status_code == 200, (path, resp.text[:300])
    assert client.get("/api/map/change?days=13").status_code == 422
    geo = client.get("/api/geo/kreise.geojson").json()
    assert len(geo["features"]) == 3 and geo["features"][0]["geometry"]["type"] == "MultiPolygon"
    assert client.get("/api/postings", params={"place": "Musterstadt", "radius_km": 20}).json()["near"]["approximate"] is True
    assert client.get("/api/postings", params={"place": "Atlantis", "radius_km": 20}).status_code == 422
    sec = client.get("/api/postings").headers
    assert "default-src 'self'" in sec["content-security-policy"] and sec["x-content-type-options"] == "nosniff"
    # gespeicherte Suchen gehören dem jeweiligen Benutzer
    h = login(client, "leser")
    sid = client.post("/api/saved-searches", json={"name": "Pflege Leipzig", "params": {"q": "pflege"}}, headers=h).json()["id"]
    h2 = login(client, "chefin")
    assert client.get("/api/saved-searches").json() == [] and client.delete(f"/api/saved-searches/{sid}", headers=h2).status_code == 404


def test_scheduler_one_logical_run_per_day_dst_and_catchup(db):
    """Zeitplan 03:15 Europe/Berlin; je Suchbereich und lokalem Datum genau ein Lauf; verpasster Lauf wird nachgeholt."""
    src, scope = make_source(db, adapter_key="service_bund_rss")
    make_source(db, "inaktiv", status="candidate", adapter_key="service_bund_rss", domain="x.example")
    n = lambda: db.execute(select(func.count()).select_from(ScanRun)).scalar_one()  # noqa: E731
    assert plan(db, datetime(2026, 11, 2, 3, 14, tzinfo=BERLIN))["runs_created"] == 0  # vor der Zeit
    out = plan(db, datetime(2026, 11, 2, 3, 15, tzinfo=BERLIN))
    assert out["runs_created"] == 1 and out["jobs"] == 1 and n() == 1  # nur die freigegebene Quelle
    for minute in (16, 45):  # Wiederholte Planung (Neustart) erzeugt nichts doppelt
        assert plan(db, datetime(2026, 11, 2, 3, minute, tzinfo=BERLIN))["runs_created"] == 0
    run = db.execute(select(ScanRun)).scalar_one()
    assert run.logical_date == date(2026, 11, 2) and run.trigger == "scheduled"
    assert db.execute(select(func.count()).select_from(Job).where(Job.kind == "scan_run")).scalar_one() == 1
    # Dienst war aus und startet mittags: Lauf des heutigen Tages wird nachgeholt, vergangene Tage nicht
    out = plan(db, datetime(2026, 11, 5, 12, 0, tzinfo=BERLIN))
    assert out["runs_created"] == 1 and n() == 2
    late = db.execute(select(ScanRun).order_by(ScanRun.id.desc()).limit(1)).scalar_one()
    assert late.logical_date == date(2026, 11, 5) and late.trigger == "catchup"
    # Sommer-/Winterzeit: maßgeblich ist das lokale Datum (29.03.2026 Umstellung auf MESZ, 25.10.2026 zurück)
    for day in (date(2026, 3, 29), date(2026, 10, 25)):
        before = n()
        t = datetime(day.year, day.month, day.day, 3, 20, tzinfo=BERLIN)
        assert plan(db, t)["runs_created"] == 1 and plan(db, t + timedelta(hours=2))["runs_created"] == 0 and n() == before + 1
    # technische Zeitstempel sind UTC
    assert run.created_at.utcoffset() == timedelta(0)


def test_job_queue_locking_retry_and_recovery(db):
    a = queue.enqueue(db, "scan_run", {"run_id": 1}, dedupe_key="scan:1", lock_key="source:1")
    assert queue.enqueue(db, "scan_run", {"run_id": 1}, dedupe_key="scan:1", lock_key="source:1") is None  # idempotent
    b = queue.enqueue(db, "scan_run", {"run_id": 2}, dedupe_key="scan:2", lock_key="source:1")
    c = queue.enqueue(db, "aggregate", {}, lock_key="aggregate")
    db.commit()
    first = queue.claim(db, "w1")
    second = queue.claim(db, "w2")
    assert first == a.id and second == c.id  # gleicher lock_key läuft nie parallel
    assert queue.claim(db, "w3") is None
    assert queue.finish(db, a.id, ok=False, error="Netz weg") == "queued"  # Wiederholung mit Wartezeit
    db.expire_all()
    job_a = db.get(Job, a.id)
    assert job_a.attempts == 1 and job_a.run_after > datetime.now(job_a.run_after.tzinfo)
    assert queue.claim(db, "w1") == b.id
    # verwaister Job (kein Heartbeat) wird kontrolliert wieder eingereiht
    db.execute(Job.__table__.update().where(Job.id == b.id).values(heartbeat_at=datetime.now(BERLIN) - timedelta(hours=1)))
    db.commit()
    assert queue.recover_stale(db, 600) == 1
    db.expire_all()
    assert db.get(Job, b.id).status == "queued" and "verwaist" in db.get(Job, b.id).last_error
    queue.finish(db, c.id, ok=True, result={"rows": 3})
    assert db.get(Job, c.id).status == "done"
