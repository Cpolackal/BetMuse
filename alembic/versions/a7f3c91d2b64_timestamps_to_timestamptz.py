"""timestamps to timestamptz

Convert every DateTime column from `timestamp` (naive) to `timestamptz`.

The application has always written timezone-aware UTC datetimes, but into naive
columns, so Postgres silently converted them using the *session* timezone and
later compared naive values against aware ones the same way. That only worked
while the server ran in UTC. Existing values are therefore interpreted as UTC
here, which is correct for any database whose session timezone was UTC when
the rows were written (the postgres docker image default). If yours was not,
adjust the USING clause before running.

Note: ALTER COLUMN TYPE rewrites the table and its indexes under an ACCESS
EXCLUSIVE lock; market_snapshots is the large one, so run during a quiet window.

Revision ID: a7f3c91d2b64
Revises: 8e2a2865f144
Create Date: 2026-11-12 00:00:00.000000

"""
from collections.abc import Sequence

from alembic import op

revision: str = 'a7f3c91d2b64'
down_revision: str | Sequence[str] | None = '8e2a2865f144'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

COLUMNS = (
    ('market_meta', 'open_time'),
    ('market_meta', 'close_time'),
    ('market_snapshots', 'snapshot_time'),
    ('match_events', 'ts'),
    ('market_links', 'linked_at'),
)


def upgrade() -> None:
    for table, column in COLUMNS:
        op.execute(
            f'ALTER TABLE {table} ALTER COLUMN {column} '
            f"TYPE timestamptz USING {column} AT TIME ZONE 'UTC'"
        )


def downgrade() -> None:
    for table, column in COLUMNS:
        op.execute(
            f'ALTER TABLE {table} ALTER COLUMN {column} '
            f"TYPE timestamp USING {column} AT TIME ZONE 'UTC'"
        )
