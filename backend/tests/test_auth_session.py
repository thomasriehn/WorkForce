"""Sitzungen müssen bereits beim Senden der HTTP-Antwort für Folgeanfragen sichtbar sein."""
from __future__ import annotations

from http.cookies import SimpleCookie
from threading import Event

import pytest
from fastapi import Request
from fastapi.testclient import TestClient
from sqlalchemy import func, select

from workforce.api.app import create_app
from workforce.api.deps import COOKIE
from workforce.config import get_settings
from workforce.db import get_db, session_scope
from workforce.models import User, UserSession
from workforce.security import hash_password, session_for

PASSWORD = "synthetisches-testpasswort"


@pytest.mark.parametrize("secure", [False, True])
def test_login_session_is_committed_before_response_and_logout_is_immediate(db, monkeypatch, secure):
    """Reale PostgreSQL-Verbindung beobachtet die Sitzung, bevor der Client HTTP 200 erhält.

    TestClient allein wartet auf den Dependency-Abbau und würde den Fehler verdecken.
    Deshalb wird die Antwortgrenze geprüft und der Dependency-Abbau gezielt verzögert.
    """
    monkeypatch.setattr(get_settings(), "cookie_secure", secure)
    db.add(User(username="session-test", role="reader", password_hash=hash_password(PASSWORD)))
    db.commit()
    app = create_app()
    sent = Event()
    observed = {}
    token = None

    def delayed_cleanup(request: Request):
        with session_scope() as session:
            yield session
            if request.url.path in ("/api/auth/login", "/api/auth/logout"):
                assert sent.wait(5), "Antwort wurde nicht rechtzeitig gesendet"

    app.dependency_overrides[get_db] = delayed_cleanup

    async def probe(scope, receive, send):
        async def observe(message):
            nonlocal token
            path = scope.get("path")
            if message["type"] == "http.response.start" and path in ("/api/auth/login", "/api/auth/logout"):
                try:
                    if path == "/api/auth/login":
                        cookies = SimpleCookie()
                        for key, value in message["headers"]:
                            if key.lower() == b"set-cookie":
                                cookies.load(value.decode("latin-1"))
                        token = cookies[COOKIE].value
                        assert bool(cookies[COOKIE]["secure"]) == secure
                        assert cookies[COOKIE]["httponly"] and cookies[COOKIE]["samesite"] == "lax"
                    with session_scope() as independent:
                        observed[path] = session_for(independent, token) is not None
                finally:
                    sent.set()
            await send(message)

        await app(scope, receive, observe)

    with TestClient(probe, base_url="https://workforce.test" if secure else "http://workforce.test") as client:
        response = client.post("/api/auth/login", json={"username": "session-test", "password": PASSWORD})
        assert response.status_code == 200
        assert observed["/api/auth/login"], "Login meldet Erfolg, bevor die Sitzung für Folgeanfragen sichtbar ist"
        assert client.get("/api/auth/me").json()["username"] == "session-test"
        assert client.get("/api/postings").status_code == 200
        sent.clear()
        response = client.post("/api/auth/logout")
        assert response.status_code == 200
        assert not observed["/api/auth/logout"], "Logout meldet Erfolg, bevor die Sitzung entfernt ist"
        assert client.get("/api/auth/me").status_code == 401


def test_failed_login_commit_does_not_send_a_successful_response_or_cookie(db, monkeypatch):
    db.add(User(username="session-test", role="reader", password_hash=hash_password(PASSWORD)))
    db.commit()
    app = create_app()

    def fail_commit():
        raise RuntimeError("Synthetischer Datenbankfehler beim Speichern der Sitzung")

    def failing_db():
        with session_scope() as session:
            monkeypatch.setattr(session, "commit", fail_commit)
            yield session

    app.dependency_overrides[get_db] = failing_db
    with TestClient(app, raise_server_exceptions=False) as client:
        response = client.post("/api/auth/login", json={"username": "session-test", "password": PASSWORD})
    assert response.status_code == 500
    assert "set-cookie" not in response.headers
    assert db.scalar(select(func.count()).select_from(UserSession)) == 0
