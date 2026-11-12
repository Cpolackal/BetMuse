from sqlalchemy.orm import declarative_base

Base = declarative_base()

# Imported last for its side effect: registers the tables on Base.metadata (Alembic reads it).
from app.db import models  # noqa: E402, F401
