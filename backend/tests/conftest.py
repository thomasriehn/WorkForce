"""Testumgebung: echte PostgreSQL/PostGIS-Testdatenbank (keine Mocks für SQL), externe Webseiten nie live.

Die Datenbank wird über ``WF_TEST_DATABASE_URL`` bestimmt, per Alembic migriert und vor jedem Test geleert.
Alle Anzeigen in den Tests sind synthetisch (frei erfundene Arbeitgeber und Texte).
"""
from __future__ import annotations

import os
from collections.abc import Iterator

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url

TEST_URL = os.environ.get("WF_TEST_DATABASE_URL", "postgresql+psycopg://workforce:devpass@127.0.0.1:55432/wf_test")
os.environ["WF_DATABASE_URL"] = TEST_URL
os.environ["WF_ENV"] = "test"
os.environ["WF_CRAWLER_CONTACT"] = "https://example.invalid/kontakt"
os.environ.setdefault("WF_DATA_DIR", "/tmp/wf-test-data")
os.environ["WF_COOKIE_SECURE"] = "false"

from workforce import db as wf_db  # noqa: E402
from workforce.config import get_settings  # noqa: E402


@pytest.fixture(scope="session", autouse=True)
def _database() -> Iterator[None]:
    url = make_url(TEST_URL)
    admin = create_engine(url.set(database="postgres"), isolation_level="AUTOCOMMIT")
    with admin.connect() as c:
        c.execute(text(f'DROP DATABASE IF EXISTS "{url.database}" WITH (FORCE)'))
        c.execute(text(f'CREATE DATABASE "{url.database}"'))
    admin.dispose()
    from alembic import command
    from alembic.config import Config

    cfg = Config(os.path.join(os.path.dirname(__file__), "..", "alembic.ini"))
    command.upgrade(cfg, "head")
    get_settings.cache_clear()
    wf_db.reset_engine()
    yield
    wf_db.reset_engine()


@pytest.fixture(autouse=True)
def _clean() -> Iterator[None]:
    eng = wf_db.get_engine()
    with eng.begin() as c:
        tables = c.execute(text("SELECT tablename FROM pg_tables WHERE schemaname='public' AND tablename NOT IN ('alembic_version','spatial_ref_sys')")).scalars().all()
        c.execute(text("TRUNCATE " + ", ".join(f'"{t}"' for t in tables) + " RESTART IDENTITY CASCADE"))
    yield


@pytest.fixture
def db() -> Iterator[object]:
    s = wf_db.session_factory()()
    try:
        yield s
    finally:
        s.rollback()
        s.close()
