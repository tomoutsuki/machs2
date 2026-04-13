from contextlib import contextmanager
from typing import Generator

import psycopg2
from psycopg2.extras import RealDictCursor

from app.core.settings import settings


@contextmanager
def get_conn() -> Generator:
    conn = psycopg2.connect(settings.database_dsn)
    try:
        yield conn
    finally:
        conn.close()


@contextmanager
def get_cursor(commit: bool = False) -> Generator:
    with get_conn() as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            yield cur
        if commit:
            conn.commit()
