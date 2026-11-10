"""Gemeinsame API-Abhängigkeiten: Anmeldung, Rollen, CSRF-Schutz, Filterparameter."""
from __future__ import annotations

import hmac
import re
from datetime import date
from typing import Annotated, Any

from fastapi import Depends, HTTPException, Query, Request
from sqlalchemy import text as sql
from sqlalchemy.orm import Session

from ..db import get_db
from ..models import POSTING_STATUS, AuditLog, User, UserSession
from ..normalize.text import fold
from ..search.query import KIND_GROUPS, Filters, QueryError, parse_query
from ..security import session_for

COOKIE = "wf_session"
Db = Annotated[Session, Depends(get_db)]


def current_session(request: Request, db: Db) -> UserSession:
    sess = session_for(db, request.cookies.get(COOKIE))
    if sess is None:
        raise HTTPException(401, "Nicht angemeldet")
    if request.method not in ("GET", "HEAD", "OPTIONS"):
        sent = request.headers.get("x-csrf-token", "")
        if not hmac.compare_digest(sent, sess.csrf_token):
            raise HTTPException(403, "CSRF-Token fehlt oder ist ungültig")
    return sess


def current_user(sess: Annotated[UserSession, Depends(current_session)]) -> User:
    return sess.user


def require_admin(user: Annotated[User, Depends(current_user)]) -> User:
    if user.role != "admin":
        raise HTTPException(403, "Administratorrechte erforderlich")
    return user


CurrentUser = Annotated[User, Depends(current_user)]
Admin = Annotated[User, Depends(require_admin)]


def audit(db: Session, user: User | None, action: str, **details: Any) -> None:
    db.add(AuditLog(username=user.username if user else None, action=action, details=details or None))


def _multi(values: list[str] | None) -> list[str]:
    out: list[str] = []
    for v in values or []:
        out.extend(x.strip() for x in v.split(",") if x.strip())
    return out


def resolve_place(db: Session, place: str | None, plz: str | None) -> dict[str, Any] | None:
    """Ortsmittelpunkt für die Umkreissuche aus der lokalen Ortsreferenz (angenähert, keine Geocoding-API)."""
    if plz and re.fullmatch(r"\d{5}", plz.strip()):
        row = db.execute(sql("SELECT name, lat, lon, kreis_key FROM geo_place WHERE postal_code = :p AND lat IS NOT NULL ORDER BY population DESC NULLS LAST LIMIT 1"),
                         {"p": plz.strip()}).mappings().first()
        if row:
            return {"name": f"{plz.strip()} {row['name']}", "lat": float(row["lat"]), "lon": float(row["lon"]), "approximate": True,
                    "note": "Mittelpunkt der Gemeinde mit diesem Verwaltungssitz-PLZ (angenähert)"}
    if place and place.strip():
        rows = db.execute(sql("SELECT name, lat, lon, kreis_key, population FROM geo_place WHERE name_norm = :n AND lat IS NOT NULL ORDER BY population DESC NULLS LAST LIMIT 3"),
                          {"n": fold(place)}).mappings().all()
        if rows:
            r = rows[0]
            note = "Gemeindemittelpunkt (angenähert)"
            if len(rows) > 1:
                note += f"; Ortsname mehrdeutig – verwendet wurde die einwohnerstärkste Gemeinde ({r['name']}, Kreis {r['kreis_key']})"
            return {"name": r["name"], "lat": float(r["lat"]), "lon": float(r["lon"]), "approximate": True, "note": note}
    return None


def filters_dep(
    db: Db,
    q: str | None = None,
    fuzzy: bool = False,
    kldb: Annotated[list[str] | None, Query()] = None,
    features: Annotated[list[str] | None, Query()] = None,
    features_mode: str = "and",
    features_required: bool = False,
    states: Annotated[list[str] | None, Query()] = None,
    kreise: Annotated[list[str] | None, Query()] = None,
    place: str | None = None,
    plz: str | None = None,
    radius_km: float | None = Query(None, ge=1, le=300),
    date_from: date | None = None,
    date_to: date | None = None,
    date_field: str = "first_seen",
    status: Annotated[list[str] | None, Query()] = None,
    sources: Annotated[list[str] | None, Query()] = None,
    kind_group: str = "jobs",
    remote: Annotated[list[str] | None, Query()] = None,
    working_time: Annotated[list[str] | None, Query()] = None,
    contract_term: str | None = None,
    geo_class: Annotated[list[str] | None, Query()] = None,
    employer: str | None = None,
    as_of: date | None = None,
    synthetic: bool = False,
) -> Filters:
    try:
        parse_query(q)
    except QueryError as exc:
        raise HTTPException(422, str(exc)) from exc
    if q and len(q) > 500:
        raise HTTPException(422, "Suchanfrage zu lang")
    if kind_group not in KIND_GROUPS:
        raise HTTPException(422, f"kind_group muss eines von {sorted(KIND_GROUPS)} sein")
    statuses = [s for s in _multi(status) if s in POSTING_STATUS]
    f = Filters(
        q=q, fuzzy=fuzzy, kldb=_multi(kldb), features=_multi(features), features_mode="or" if features_mode == "or" else "and",
        features_required_only=features_required, states=[s.zfill(2) for s in _multi(states)], kreise=[k.zfill(5) for k in _multi(kreise)],
        date_from=date_from, date_to=date_to, date_field="date_posted" if date_field == "date_posted" else "first_seen",
        sources=[int(x) for x in _multi(sources) if x.isdigit()], kind_group=kind_group,
        remote=[r for r in _multi(remote) if r in ("remote", "hybrid", "onsite", "unknown")],
        working_time=[w for w in _multi(working_time) if w in ("vollzeit", "teilzeit")],
        contract_term=contract_term if contract_term in ("befristet", "unbefristet") else None,
        geo_classes=_multi(geo_class), employer=employer, as_of=as_of, include_synthetic=synthetic,
    )
    if statuses:
        f.statuses = statuses
    if radius_km and (place or plz):
        center = resolve_place(db, place, plz)
        if center is None:
            raise HTTPException(422, "Ort/PLZ für die Umkreissuche nicht in der lokalen Ortsreferenz gefunden")
        f.near, f.radius_km = (center["lat"], center["lon"]), radius_km
        f.near_info = center
    return f


FiltersDep = Annotated[Filters, Depends(filters_dep)]
