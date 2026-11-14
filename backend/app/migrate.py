"""Tiny additive schema migrations (SQLite/Postgres): add new nullable/defaulted columns in place,
so an existing database keeps its data when the models gain fields."""
from __future__ import annotations

import logging

from sqlalchemy import inspect, text

from .db import engine

log = logging.getLogger("zeromdr.migrate")

# (table, column, DDL type + default)
COLUMNS = [
    ("merchants", "busy_mode", "BOOLEAN NOT NULL DEFAULT 0"),
    ("campaigns", "tag_bid_paise", "INTEGER"),
    ("holds", "verified", "BOOLEAN NOT NULL DEFAULT 0"),
    ("holds", "sent_at", "TIMESTAMP"),
    ("advertisers", "gstin", "VARCHAR(20)"),
    ("advertisers", "kyc_status", "VARCHAR(12) NOT NULL DEFAULT 'pending'"),
    ("advertisers", "kyc_note", "TEXT"),
    ("advertisers", "kyc_method", "VARCHAR(20)"),
    ("advertisers", "kyc_verified_at", "TIMESTAMP"),
]


def run() -> None:
    insp = inspect(engine)
    tables = set(insp.get_table_names())
    with engine.begin() as conn:
        for table, column, ddl in COLUMNS:
            if table not in tables:
                continue  # created fresh by create_all with every column
            if column not in {c["name"] for c in insp.get_columns(table)}:
                conn.execute(text(f"ALTER TABLE {table} ADD COLUMN {column} {ddl}"))
                log.info("migrated: %s.%s added", table, column)
