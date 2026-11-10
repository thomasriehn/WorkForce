"""Lokaler Login: Argon2-Passworthashes, serverseitige Sitzungen (Token nur als SHA-256 gespeichert), CSRF-Token."""
from __future__ import annotations

import hashlib
import secrets
from datetime import UTC, datetime, timedelta

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError
from sqlalchemy import select
from sqlalchemy.orm import Session

from .config import get_settings
from .models import User, UserSession

_ph = PasswordHasher()
_DUMMY = _ph.hash("workforce-dummy-password")
MIN_PASSWORD_LENGTH = 12


def hash_password(password: str) -> str:
    if len(password) < MIN_PASSWORD_LENGTH:
        raise ValueError(f"Passwort muss mindestens {MIN_PASSWORD_LENGTH} Zeichen lang sein")
    return _ph.hash(password)


def verify_password(stored: str, password: str) -> bool:
    try:
        return _ph.verify(stored, password)
    except (VerificationError, InvalidHashError):
        return False


def generate_password() -> str:
    return secrets.token_urlsafe(18)


def _token_hash(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def authenticate(db: Session, username: str, password: str) -> User | None:
    """Prüft Zugangsdaten mit Sperre nach wiederholten Fehlversuchen (gleichförmige Laufzeit)."""
    s = get_settings()
    now = datetime.now(UTC)
    user = db.execute(select(User).where(User.username == username.strip())).scalar_one_or_none()
    if user is None or not user.is_active:
        verify_password(_DUMMY, password)
        return None
    if user.locked_until and user.locked_until > now:
        verify_password(_DUMMY, password)
        return None
    if not verify_password(user.password_hash, password):
        user.failed_logins += 1
        if user.failed_logins >= s.login_max_failures:
            user.locked_until = now + timedelta(minutes=s.login_lock_minutes)
            user.failed_logins = 0
        return None
    user.failed_logins, user.locked_until, user.last_login_at = 0, None, now
    return user


def create_session(db: Session, user: User) -> tuple[str, str]:
    s = get_settings()
    token, csrf = secrets.token_urlsafe(32), secrets.token_urlsafe(24)
    db.add(UserSession(user_id=user.id, token_hash=_token_hash(token), csrf_token=csrf, expires_at=datetime.now(UTC) + timedelta(hours=s.session_hours)))
    db.flush()
    return token, csrf


def session_for(db: Session, token: str | None) -> UserSession | None:
    if not token:
        return None
    sess = db.execute(select(UserSession).where(UserSession.token_hash == _token_hash(token))).scalar_one_or_none()
    if sess is None or sess.expires_at < datetime.now(UTC) or not sess.user.is_active:
        return None
    return sess


def end_session(db: Session, token: str | None) -> None:
    if token:
        sess = db.execute(select(UserSession).where(UserSession.token_hash == _token_hash(token))).scalar_one_or_none()
        if sess is not None:
            db.delete(sess)
