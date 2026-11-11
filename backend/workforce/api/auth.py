from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request, Response
from pydantic import BaseModel

from ..config import get_settings
from ..security import authenticate, create_session, end_session, session_for
from .deps import COOKIE, Db, audit

router = APIRouter(prefix="/api/auth", tags=["auth"])


class LoginIn(BaseModel):
    username: str
    password: str


def _user_out(user, csrf: str) -> dict:
    return {"username": user.username, "role": user.role, "csrf_token": csrf}


@router.post("/login")
def login(body: LoginIn, response: Response, db: Db) -> dict:
    s = get_settings()
    user = authenticate(db, body.username, body.password)
    if user is None:
        db.commit()  # Fehlversuchszähler festschreiben
        raise HTTPException(401, "Benutzername oder Passwort falsch (oder Konto vorübergehend gesperrt)")
    token, csrf = create_session(db, user)
    audit(db, user, "login")
    # Die Request-Dependency schließt ihre Transaktion erst nach dem Senden der
    # Antwort. Das Cookie darf erst herausgehen, wenn Folgeanfragen die Sitzung
    # bereits sehen können (sonst sofortiges 401 direkt nach erfolgreichem Login).
    db.commit()
    response.set_cookie(COOKIE, token, httponly=True, secure=s.cookie_secure, samesite="lax", max_age=s.session_hours * 3600, path="/")
    return _user_out(user, csrf)


@router.post("/logout")
def logout(request: Request, response: Response, db: Db) -> dict:
    end_session(db, request.cookies.get(COOKIE))
    db.commit()  # Widerruf muss vor der Bestätigung auch für parallele Anfragen gelten.
    response.delete_cookie(COOKIE, path="/")
    return {"ok": True}


@router.get("/me")
def me(request: Request, db: Db) -> dict:
    sess = session_for(db, request.cookies.get(COOKIE))
    if sess is None:
        raise HTTPException(401, "Nicht angemeldet")
    return _user_out(sess.user, sess.csrf_token)
