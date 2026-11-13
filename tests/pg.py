"""Throwaway-Postgres fixtures for DB tests.

Uses TEST_DATABASE_URL if set (the schema is created/dropped on it, so point it
at a scratch database!). Otherwise starts a private server from locally
installed Postgres binaries (initdb/pg_ctl) in a temp dir, and skips the DB
tests if none are available.
"""

import os
import shutil
import socket
import subprocess
import tempfile
from pathlib import Path

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker


def _find_bin(name: str) -> str | None:
    if found := shutil.which(name):
        return found
    for root in sorted(Path("/opt/homebrew/opt").glob("postgresql@*/bin"), reverse=True):
        if (root / name).exists():
            return str(root / name)
    return None


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


@pytest.fixture(scope="session")
def pg_url():
    if url := os.environ.get("TEST_DATABASE_URL"):
        yield url
        return
    initdb, pg_ctl = _find_bin("initdb"), _find_bin("pg_ctl")
    if not (initdb and pg_ctl):
        pytest.skip("no Postgres available (set TEST_DATABASE_URL or install postgres)")
    data = tempfile.mkdtemp(prefix="betmuse-pg-")
    port = _free_port()
    subprocess.run([initdb, "-D", data, "-U", "test", "--auth=trust", "-E", "UTF8"], check=True, capture_output=True)
    subprocess.run(
        [pg_ctl, "-D", data, "-o", f"-p {port} -k {data} -c listen_addresses=127.0.0.1 -c timezone=UTC", "-w", "start",
         "-l", f"{data}/log"],
        check=True, capture_output=True,
    )
    try:
        yield f"postgresql+psycopg2://test@127.0.0.1:{port}/postgres"
    finally:
        subprocess.run([pg_ctl, "-D", data, "-m", "immediate", "stop"], capture_output=True)
        shutil.rmtree(data, ignore_errors=True)


@pytest.fixture(scope="session")
def pg_engine(pg_url):
    from app.db.base import Base

    engine = create_engine(pg_url)
    Base.metadata.drop_all(engine)
    Base.metadata.create_all(engine)
    yield engine
    Base.metadata.drop_all(engine)
    engine.dispose()


@pytest.fixture
def db(pg_engine):
    """A session on a clean database (all tables truncated before each test)."""
    from app.db.base import Base

    with pg_engine.begin() as conn:
        conn.execute(text("TRUNCATE " + ", ".join(t.name for t in Base.metadata.sorted_tables) + " RESTART IDENTITY"))
    session = sessionmaker(bind=pg_engine)()
    yield session
    session.close()
