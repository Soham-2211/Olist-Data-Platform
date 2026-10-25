"""SQLite warehouse connection with the UDFs the SQL models rely on.

SQLite keeps the project dependency-free and the whole warehouse in one file.
The SQL is written to be portable: swapping in DuckDB or Postgres only needs
these UDFs re-implemented (both have unaccent / math built in).
"""
from __future__ import annotations

import math
import sqlite3
import unicodedata
from pathlib import Path


def unaccent(s):
    if s is None:
        return None
    return "".join(c for c in unicodedata.normalize("NFKD", s) if not unicodedata.combining(c))


def norm_city(s):
    """'São Paulo', 'sao-paulo', 'sa£o paulo' -> 'sao paulo'."""
    if s is None:
        return None
    s = unaccent(s).lower().replace("£", "").replace("-", " ").replace("`", "'")
    return " ".join(s.split())


def haversine_km(lat1, lng1, lat2, lng2):
    if None in (lat1, lng1, lat2, lng2):
        return None
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp, dl = p2 - p1, math.radians(lng2 - lng1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 6371.0 * 2 * math.asin(math.sqrt(a))


def connect(path: str | Path) -> sqlite3.Connection:
    con = sqlite3.connect(path, isolation_level=None)  # autocommit; we manage transactions explicitly
    con.execute("PRAGMA journal_mode=WAL")
    con.execute("PRAGMA synchronous=NORMAL")
    con.execute("PRAGMA temp_store=MEMORY")
    con.create_function("unaccent", 1, unaccent, deterministic=True)
    con.create_function("norm_city", 1, norm_city, deterministic=True)
    con.create_function("haversine_km", 4, haversine_km, deterministic=True)
    con.create_function("ln", 1, lambda x: math.log(x) if x and x > 0 else None, deterministic=True)
    return con


def table_exists(con: sqlite3.Connection, name: str) -> bool:
    return con.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (name,)).fetchone() is not None


def row_count(con: sqlite3.Connection, name: str) -> int:
    return con.execute(f'SELECT COUNT(*) FROM "{name}"').fetchone()[0]
