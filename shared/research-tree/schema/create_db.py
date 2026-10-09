"""Create an empty research-tree LatticeDB database.

The structure is specified in research_tree.sql (one TABLE per node label).
LatticeDB has no DDL, so creating a database means: create the file, write the
Meta singleton, and declare the property and full-text indexes. The SQL spec is
loaded into an in-memory SQLite database only to check that every indexed
property is a column of its table, so this file and the spec cannot drift.

Usage:
    python schema/create_db.py [DB_PATH]
    python schema/create_db.py --upgrade DB_PATH     # an existing database, after a backup
"""

from __future__ import annotations

import argparse
import sqlite3
import sys
from datetime import datetime, timezone
from pathlib import Path

from latticedb import Database, LatticeAlreadyExistsError

SCHEMA_VERSION = 18
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
    "evaluation": "Evaluation",
    "obligation": "Obligation",
    "reservation": "Reservation",
}

PROPERTY_INDEXES = [(table, "id") for table in LABELS if table != "meta"] + [
    ("hypothesis", "status"),
    ("hypothesis", "project_id"),
    ("experiment", "project_id"),
    ("experiment", "verdict"),
    ("document", "path"),
    ("task", "status"),
    ("branch", "status"),
    ("evaluation", "fingerprint"),
    ("obligation", "fingerprint"),
    ("reservation", "submission_key"),
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


# Indexes each version added; upgrading creates the missing ones.
ADDED_INDEXES = {7: [("evaluation", "id"), ("evaluation", "fingerprint")],
                 8: [("obligation", "id"), ("obligation", "fingerprint")],
                 9: [("reservation", "id"), ("reservation", "submission_key")]}


def upgrade_db(db_path: Path) -> int:
    """Bring an existing database to SCHEMA_VERSION in place (plans/design 10 §2.5): back the research directory up
    first and stop every writer. Only additions: new labels get their indexes, schema_version is raised; no
    record is rewritten (old evaluations are recorded afterwards by research_db migrate_evaluations). Returns the
    version found."""
    check_spec(spec_columns(SPEC_PATH))
    if not db_path.exists():
        raise SystemExit(f"database not found: {db_path}")
    with Database(db_path) as db:
        with db.read() as txn:
            meta = txn.get_nodes_by_label(LABELS["meta"])
            found = txn.get_property(meta[0], "schema_version")
        if found > SCHEMA_VERSION:
            raise SystemExit(f"{db_path} is schema_version {found}, newer than this plugin's {SCHEMA_VERSION}")
        for version in range(found + 1, SCHEMA_VERSION + 1):
            for table, prop in ADDED_INDEXES.get(version, []):
                try:
                    db.create_node_property_index(LABELS[table], prop)
                except LatticeAlreadyExistsError:
                    pass
        if found < SCHEMA_VERSION:
            with db.write() as txn:
                meta = txn.get_nodes_by_label(LABELS["meta"])
                txn.set_property(meta[0], "schema_version", SCHEMA_VERSION)
                txn.set_property(meta[0], "updated_at", datetime.now(timezone.utc).isoformat())
                txn.commit()
    return found


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("db_path", nargs="?", type=Path, default=DEFAULT_DB_PATH)
    parser.add_argument("--upgrade", action="store_true", help="upgrade an existing database to this schema version")
    args = parser.parse_args(argv)
    if args.upgrade:
        found = upgrade_db(args.db_path)
        print(f"upgraded {args.db_path} from schema_version {found} to {SCHEMA_VERSION}")
        return 0
    create_db(args.db_path)
    print(f"created {args.db_path} (schema_version={SCHEMA_VERSION})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
