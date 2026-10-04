"""Create an empty research-tree LatticeDB database.

The structure is specified in research_tree.sql (one TABLE per node label).
LatticeDB has no DDL, so creating a database means: create the file, write the
Meta singleton, and declare the property and full-text indexes. The SQL spec is
loaded into an in-memory SQLite database only to check that every indexed
property is a column of its table, so this file and the spec cannot drift.

Usage:
    python schema/create_db.py [DB_PATH]
"""

from __future__ import annotations

import argparse
import sqlite3
import sys
from datetime import datetime, timezone
from pathlib import Path

from latticedb import Database

SCHEMA_VERSION = 6
SPEC_PATH = Path(__file__).with_name("research_tree.sql")
DEFAULT_DB_PATH = Path("research_tree.db")

# Node label for each spec table. rel_* tables are edge types, not labels.
LABELS = {
    "meta": "Meta",
    "project": "Project",
    "hypothesis": "Hypothesis",
    "experiment": "Experiment",
    "branch": "Branch",
    "run": "Run",
    "document": "Document",
    "decision": "Decision",
    "task": "Task",
}

PROPERTY_INDEXES = [(table, "id") for table in LABELS if table != "meta"] + [
    ("hypothesis", "status"),
    ("hypothesis", "project_id"),
    ("experiment", "project_id"),
    ("experiment", "verdict"),
    ("document", "path"),
    ("task", "status"),
    ("branch", "status"),
]

FTS_INDEXES = [
    ("hypothesis", "statement"),
    ("document", "summary"),
]


def spec_columns(spec_path: Path) -> dict[str, set[str]]:
    con = sqlite3.connect(":memory:")
    try:
        con.executescript(spec_path.read_text(encoding="utf-8"))
        tables = [r[0] for r in con.execute("SELECT name FROM sqlite_master WHERE type = 'table'")]
        return {t: {r[1] for r in con.execute(f"PRAGMA table_info({t})")} for t in tables}
    finally:
        con.close()


def check_spec(columns: dict[str, set[str]]) -> None:
    node_tables = {t for t in columns if not t.startswith("rel_")}
    if node_tables != set(LABELS):
        raise SystemExit(f"spec tables {sorted(node_tables)} do not match LABELS {sorted(LABELS)}")
    for table, prop in PROPERTY_INDEXES + FTS_INDEXES:
        if prop not in columns[table]:
            raise SystemExit(f"indexed property {table}.{prop} is not a column in {SPEC_PATH.name}")


def create_db(db_path: Path) -> None:
    check_spec(spec_columns(SPEC_PATH))
    # LatticeDB keeps a write-ahead log next to the file; refuse to touch either.
    existing = [p for p in (db_path, Path(f"{db_path}-wal")) if p.exists()]
    if existing:
        raise SystemExit(f"refusing to overwrite existing database files: {', '.join(map(str, existing))}")

    now = datetime.now(timezone.utc).isoformat()
    with Database(db_path, create=True) as db:
        for table, prop in PROPERTY_INDEXES:
            db.create_node_property_index(LABELS[table], prop)
        for table, prop in FTS_INDEXES:
            db.create_node_fts_index(LABELS[table], prop)
        with db.write() as txn:
            txn.create_node(
                labels=[LABELS["meta"]],
                properties={"schema_version": SCHEMA_VERSION, "data_version": 0, "updated_at": now},
            )
            txn.commit()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("db_path", nargs="?", type=Path, default=DEFAULT_DB_PATH)
    args = parser.parse_args(argv)
    create_db(args.db_path)
    print(f"created {args.db_path} (schema_version={SCHEMA_VERSION})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
