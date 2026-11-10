"""Kommandozeile ``workforce`` – Betrieb und Administration aus derselben Codebasis wie Web/Worker/Scheduler."""
from __future__ import annotations

import argparse
import getpass
import json
import sys
from datetime import date
from pathlib import Path
from typing import Any

from sqlalchemy import select

from .config import get_settings
from .db import session_scope


def _print(obj: Any) -> None:
    print(json.dumps(obj, ensure_ascii=False, indent=2, default=str))


def cmd_migrate(args: argparse.Namespace) -> int:
    from alembic import command
    from alembic.config import Config

    cfg = Config(str(Path(__file__).resolve().parent.parent / "alembic.ini"))
    command.upgrade(cfg, "head")
    return cmd_seed(args)


def cmd_seed(args: argparse.Namespace) -> int:
    """Stammdaten: Quellenregister, Merkmalswörterbuch, Statistik-Datensätze/-Kennzahlen (idempotent, keine Demo-Daten)."""
    from sqlalchemy.dialects.postgresql import insert as pg_insert

    from .models import Feature
    from .normalize.features import feature_dictionary
    from .sources.registry import seed_registry

    with session_scope() as db:
        created = seed_registry(db)
        for f in feature_dictionary():
            db.execute(pg_insert(Feature).values(**f).on_conflict_do_update(index_elements=["key"], set_={k: f[k] for k in ("type", "label", "synonyms", "rule_version")}))
        try:
            from .stats.runner import seed_reference

            seed_reference(db)
        except ImportError:
            pass
    _print({"seed": "ok", **created})
    return 0


def cmd_user(args: argparse.Namespace) -> int:
    from .models import User
    from .security import generate_password, hash_password

    with session_scope() as db:
        if args.action == "list":
            _print([{"username": u.username, "role": u.role, "active": u.is_active, "last_login": u.last_login_at} for u in db.execute(select(User).order_by(User.username)).scalars()])
            return 0
        user = db.execute(select(User).where(User.username == args.username)).scalar_one_or_none()
        if args.action == "create":
            if user is not None:
                print("Benutzer existiert bereits.", file=sys.stderr)
                return 1
            if args.password_stdin:
                password = sys.stdin.readline().rstrip("\n")
            elif args.generate or not sys.stdin.isatty():
                password = generate_password()
                print(f"Generiertes Passwort für {args.username} (wird nur jetzt angezeigt): {password}")
            else:
                password = getpass.getpass("Passwort (mind. 12 Zeichen): ")
                if password != getpass.getpass("Passwort wiederholen: "):
                    print("Passwörter stimmen nicht überein.", file=sys.stderr)
                    return 1
            db.add(User(username=args.username, role=args.role, password_hash=hash_password(password)))
            print(f"Benutzer {args.username} ({args.role}) angelegt.")
            return 0
        if user is None:
            print("Benutzer nicht gefunden.", file=sys.stderr)
            return 1
        if args.action == "reset-password":
            password = generate_password()
            user.password_hash = hash_password(password)
            user.failed_logins, user.locked_until = 0, None
            print(f"Neues Passwort für {args.username} (wird nur jetzt angezeigt): {password}")
        elif args.action == "disable":
            user.is_active = False
            print("Benutzer deaktiviert.")
    return 0


def cmd_source(args: argparse.Namespace) -> int:
    from .models import Source
    from .sources.manage import SourceError, activate, deactivate, source_health

    with session_scope() as db:
        if args.action == "list":
            rows = []
            for s in db.execute(select(Source).order_by(Source.name)).scalars():
                h = source_health(db, s)
                rows.append({"key": s.key, "name": s.name, "status": s.config_status, "adapter": s.adapter_key or "–", "health": h["health"],
                             "stock": h["stock"], "geprüft": s.legal_checked_on, "grund": (s.status_reason or "")[:110]})
            _print(rows)
            return 0
        src = db.execute(select(Source).where(Source.key == args.key)).scalar_one_or_none()
        if src is None:
            print("Quelle nicht gefunden.", file=sys.stderr)
            return 1
        try:
            if args.action == "activate":
                activate(db, src, basis=args.basis or "", permission_reference=args.permission, username="cli")
                print(f"Quelle {src.key} freigegeben.")
            elif args.action == "deactivate":
                deactivate(db, src, reason=args.reason or "", username="cli", status=args.status)
                print(f"Quelle {src.key} deaktiviert ({args.status}).")
            elif args.action == "show":
                _print({"key": src.key, "name": src.name, "status": src.config_status, "status_reason": src.status_reason, "terms_url": src.terms_url,
                        "robots_url": src.robots_url, "legal_checked_on": src.legal_checked_on, "legal_notes": src.legal_notes, **source_health(db, src)})
        except SourceError as exc:
            print(f"Nicht möglich: {exc}", file=sys.stderr)
            return 1
    return 0


def cmd_scan(args: argparse.Namespace) -> int:
    """Führt einen Lauf direkt im Vordergrund aus (manuell oder als begrenzter Testlauf)."""
    from .logging_setup import setup_logging
    from .models import ScanRun, SearchScope, Source
    from .pipeline.run import RunRefused, create_run, execute_run, local_today

    setup_logging("workforce.cli")
    run_ids = []
    with session_scope() as db:
        src = db.execute(select(Source).where(Source.key == args.key)).scalar_one_or_none()
        if src is None:
            print("Quelle nicht gefunden.", file=sys.stderr)
            return 1
        scopes = db.execute(select(SearchScope).where(SearchScope.source_id == src.id, SearchScope.is_active)).scalars().all()
        for sc in scopes:
            if args.scope and sc.key != args.scope:
                continue
            run, created = create_run(db, sc, local_today(), "manual", page_limit=args.pages or (2 if args.test else None), is_test=args.test)
            if not created and run.status in ("partial", "blocked", "failed") and args.retry:
                run.control, run.status = "retry", "queued"
            run_ids.append(run.id)
    rc = 0
    for rid in run_ids:
        try:
            execute_run(rid)
        except RunRefused as exc:
            print(f"Lauf {rid} abgelehnt: {exc}", file=sys.stderr)
            rc = 1
        with session_scope() as db:
            r = db.get(ScanRun, rid)
            assert r is not None
            _print({"run_id": r.id, "status": r.status, "detail": r.status_detail, "list_complete": r.list_complete, "detail_complete": r.detail_complete,
                    "pages": r.pages_fetched, "requests": r.requests_made, "ids_found": r.ids_found, "new": r.postings_new, "changed": r.postings_changed,
                    "errors": r.error_count, "coverage": r.coverage})
    return rc


def cmd_aggregate(args: argparse.Namespace) -> int:
    from .pipeline import aggregate
    from .pipeline.run import local_today

    with session_scope() as db:
        if args.date_from:
            _print(aggregate.compute_range(db, date.fromisoformat(args.date_from), date.fromisoformat(args.date_to or args.date_from)))
        else:
            _print(aggregate.nightly(db, local_today()))
    return 0


def cmd_stats(args: argparse.Namespace) -> int:
    from .logging_setup import setup_logging
    from .stats import runner

    setup_logging("workforce.cli")
    if args.action == "list":
        _print(runner.describe())
    elif args.action == "import":
        if args.file:
            _print(runner.import_file(args.dataset, Path(args.file), method="manual", original_name=Path(args.file).name))
        else:
            _print(runner.run_imports([args.dataset] if args.dataset and args.dataset != "all" else None))
    return 0


def cmd_geo(args: argparse.Namespace) -> int:
    from .pipeline.ingest import rematch_unresolved

    with session_scope() as db:
        _print({"rematched_versions": rematch_unresolved(db)})
    return 0


def cmd_synthetic(args: argparse.Namespace) -> int:
    from .synthetic import load, purge

    if not args.confirm_synthetic:
        print("Synthetische Daten werden nur mit --confirm-synthetic geladen/gelöscht. Sie sind gekennzeichnet und standardmäßig ausgeblendet.", file=sys.stderr)
        return 1
    if args.action == "load":
        _print(load(postings=args.postings, days=args.days, seed=args.seed))
    else:
        _print(purge())
    return 0


def cmd_run(args: argparse.Namespace) -> int:
    if args.component == "worker":
        from .jobs.worker import main as run

        run()
    elif args.component == "scheduler":
        from .jobs.scheduler import main as run

        run()
    else:
        import uvicorn

        from .logging_setup import setup_logging

        setup_logging("workforce.web")
        uvicorn.run("workforce.api.app:app", host="0.0.0.0", port=8000, proxy_headers=True, forwarded_allow_ips="*", log_config=None, access_log=False)  # noqa: S104
    return 0


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="workforce", description="WorkForce – Betrieb und Administration")
    sub = p.add_subparsers(dest="cmd", required=True)
    sub.add_parser("migrate", help="Datenbankmigrationen ausführen und Stammdaten ergänzen").set_defaults(fn=cmd_migrate)
    sub.add_parser("seed", help="Stammdaten ergänzen (Quellenregister, Wörterbücher)").set_defaults(fn=cmd_seed)
    for comp in ("web", "worker", "scheduler"):
        sub.add_parser(comp, help=f"Prozess „{comp}“ starten").set_defaults(fn=cmd_run, component=comp)
    u = sub.add_parser("user", help="Benutzer verwalten")
    u.add_argument("action", choices=["create", "list", "reset-password", "disable"])
    u.add_argument("username", nargs="?")
    u.add_argument("--role", choices=["admin", "reader"], default="reader")
    u.add_argument("--generate", action="store_true", help="zufälliges Passwort erzeugen und einmalig anzeigen")
    u.add_argument("--password-stdin", action="store_true")
    u.set_defaults(fn=cmd_user)
    s = sub.add_parser("source", help="Quellenregister: anzeigen, freigeben, deaktivieren")
    s.add_argument("action", choices=["list", "show", "activate", "deactivate"])
    s.add_argument("key", nargs="?")
    s.add_argument("--basis", help="Freigabevermerk: was wurde geprüft, worauf stützt sich die Freigabe")
    s.add_argument("--permission", help="Nachweis der Erlaubnis (bei Status permission_required)")
    s.add_argument("--reason")
    s.add_argument("--status", default="disabled", choices=["disabled", "permission_required", "candidate"])
    s.set_defaults(fn=cmd_source)
    sc = sub.add_parser("scan", help="Lauf im Vordergrund ausführen")
    sc.add_argument("key")
    sc.add_argument("--scope")
    sc.add_argument("--test", action="store_true", help="begrenzter Testlauf (zählt nicht als Tageslauf)")
    sc.add_argument("--pages", type=int, help="Seitenlimit")
    sc.add_argument("--retry", action="store_true", help="unvollständigen heutigen Lauf wiederholen")
    sc.set_defaults(fn=cmd_scan)
    a = sub.add_parser("aggregate", help="Tagesaggregate (neu) berechnen")
    a.add_argument("--from", dest="date_from")
    a.add_argument("--to", dest="date_to")
    a.set_defaults(fn=cmd_aggregate)
    st = sub.add_parser("stats", help="Amtliche Regional-/Geodaten: Importe")
    st.add_argument("action", choices=["list", "import"])
    st.add_argument("dataset", nargs="?", help="Datensatzschlüssel oder 'all'")
    st.add_argument("--file", help="manueller Import aus lokaler Datei")
    st.set_defaults(fn=cmd_stats)
    sub.add_parser("geo-rematch", help="Fehlende Ortszuordnungen nach Referenzimport ergänzen").set_defaults(fn=cmd_geo)
    sy = sub.add_parser("synthetic", help="Ausdrücklich synthetische Daten für Skalierungstests")
    sy.add_argument("action", choices=["load", "purge"])
    sy.add_argument("--postings", type=int, default=100_000)
    sy.add_argument("--days", type=int, default=30)
    sy.add_argument("--seed", type=int, default=42)
    sy.add_argument("--confirm-synthetic", action="store_true")
    sy.set_defaults(fn=cmd_synthetic)
    return p


def main(argv: list[str] | None = None) -> None:
    args = build_parser().parse_args(argv)
    if args.cmd in ("user", "source") and args.action not in ("list",) and not args.__dict__.get("username") and not args.__dict__.get("key"):
        print("Bitte Benutzername bzw. Quellenschlüssel angeben.", file=sys.stderr)
        raise SystemExit(2)
    get_settings()
    raise SystemExit(args.fn(args))


if __name__ == "__main__":
    main()
