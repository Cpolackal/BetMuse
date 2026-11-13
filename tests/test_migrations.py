"""Run the real Alembic migrations against a scratch database."""

import os
import subprocess
import sys
from pathlib import Path

import pytest
from sqlalchemy import bindparam, create_engine, text

ROOT = Path(__file__).resolve().parent.parent
TZ_MIGRATION = "a7f3c91d2b64"
BEFORE_TZ = "8e2a2865f144"

TIME_COLUMNS = [
    ("market_meta", "open_time"), ("market_meta", "close_time"), ("market_snapshots", "snapshot_time"),
    ("match_events", "ts"), ("market_links", "linked_at"),
]


def alembic(url: str, *args: str) -> None:
    env = {**os.environ, "DATABASE_URL": url}
    r = subprocess.run([sys.executable, "-m", "alembic", *args], cwd=ROOT, env=env, capture_output=True, text=True)
    assert r.returncode == 0, r.stderr[-2000:]


@pytest.fixture
def scratch_url(pg_url):
    admin = create_engine(pg_url, isolation_level="AUTOCOMMIT")
    with admin.connect() as c:
        c.execute(text("DROP DATABASE IF EXISTS migrate_test"))
        c.execute(text("CREATE DATABASE migrate_test"))
    yield pg_url.rsplit("/", 1)[0] + "/migrate_test"
    with admin.connect() as c:
        c.execute(text("DROP DATABASE IF EXISTS migrate_test WITH (FORCE)"))
    admin.dispose()


def column_types(engine) -> dict[tuple[str, str], str]:
    with engine.connect() as c:
        rows = c.execute(text(
            "SELECT table_name, column_name, data_type FROM information_schema.columns "
            "WHERE (table_name, column_name) IN :cols"
        ).bindparams(bindparam("cols", expanding=True)), {"cols": TIME_COLUMNS})
        return {(t, col): dt for t, col, dt in rows}


def test_timestamptz_migration_round_trip(scratch_url):
    alembic(scratch_url, "upgrade", BEFORE_TZ)
    engine = create_engine(scratch_url)
    with engine.begin() as c:
        c.execute(text("SET TIME ZONE 'America/New_York'"))  # must not influence the conversion
        c.execute(text("INSERT INTO market_meta (ticker, open_time, close_time) "
                       "VALUES ('T', '2026-01-01 12:00:00', '2026-01-15 00:00:00')"))
        c.execute(text("INSERT INTO market_snapshots (ticker, snapshot_time) VALUES ('T', '2026-01-01 13:30:00')"))
        c.execute(text("INSERT INTO match_events (event_id, ts) VALUES (1, '2026-01-01 14:00:00')"))
        c.execute(text("INSERT INTO market_links (ticker, linked_at) VALUES ('T', '2026-01-01 15:00:00')"))
    assert set(column_types(engine).values()) == {"timestamp without time zone"}

    alembic(scratch_url, "upgrade", "head")
    assert set(column_types(engine).values()) == {"timestamp with time zone"}
    with engine.connect() as c:
        c.execute(text("SET TIME ZONE 'Asia/Tokyo'"))
        # Existing naive values are interpreted as UTC, whatever the session zone.
        got = c.execute(text(
            "SELECT open_time = '2026-01-01 12:00:00+00', close_time = '2026-01-15 00:00:00+00' FROM market_meta"
        )).one()
        assert tuple(got) == (True, True)
        assert c.execute(text("SELECT snapshot_time = '2026-01-01 13:30:00+00' FROM market_snapshots")).scalar()
        assert c.execute(text("SELECT ts = '2026-01-01 14:00:00+00' FROM match_events")).scalar()
        assert c.execute(text("SELECT linked_at = '2026-01-01 15:00:00+00' FROM market_links")).scalar()

    alembic(scratch_url, "downgrade", BEFORE_TZ)
    assert set(column_types(engine).values()) == {"timestamp without time zone"}
    with engine.connect() as c:
        assert c.execute(text("SELECT open_time = '2026-01-01 12:00:00' FROM market_meta")).scalar()
    engine.dispose()
