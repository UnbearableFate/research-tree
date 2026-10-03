"""Read/write interface to the research-tree LatticeDB database.

Structure comes from schema/research_tree.sql (one TABLE per node label,
rel_* tables are edge types). LatticeDB enforces none of the spec's
constraints, so every write goes through this module, which checks:

  * column names, types, NOT NULL and CHECK (... IN ...) values from the spec;
  * references: edge-backed columns and *_doc_id columns point at existing
    records of the right kind;
  * who may write what (actor = "<role>/<agent-id>");
  * the experiment-first rules: every node is a code change evaluated with the
    frozen harness and statistics code; the seed budget; the verdict recorded
    for each experiment and its consistency with the paired comparisons; node
    status following the latest verdict; novelty/theory rechecks only after a
    node beats SOTA; GO/NOT GO; branch, task and document lifecycles;
  * every hypothesis/project/branch state change writes a decision record in
    the same transaction.

Each public write method is one short write transaction: open (retrying while
another process holds the lock), write, bump meta.data_version, commit, close.

CLI (one call per invocation, JSON in and out):
    python tools/research_db.py --db research/P-x/research_tree.db --actor rld/main \\
        create_hypothesis '{"title": "...", "statement": "...", "doc_id": "D-0003", "related_work": [...]}'
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sqlite3
import subprocess
import sys
import time
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator

from latticedb import Database, LatticeDatabaseLockedError

SPEC_PATH = Path(__file__).resolve().parent.parent / "schema" / "research_tree.sql"
OPEN_ATTEMPTS = 40
OPEN_RETRY_DELAY_S = 0.25

ROLES = ("ui", "rld", "worker", "assistant", "web_builder")

ID_PREFIX = {
    "project": "P",
    "hypothesis": "H",
    "experiment": "E",
    "branch": "BR",
    "document": "D",
    "decision": "DEC",
    "task": "T",
}
TABLE_OF_PREFIX = {prefix: table for table, prefix in ID_PREFIX.items()}
ENTITY_ID_RE = re.compile(r"^(P|H|E|BR|D|DEC|T)-[A-Za-z0-9_.-]+$")
# A project may also be named like its directory / uv project (`my-study`), as long as it does not look like
# another record's id.
PROJECT_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]*$")
RUN_ID_RE = re.compile(r"^(E-[A-Za-z0-9_.-]+)/s(-?[0-9]+)$")
DOC_PATH_RE = re.compile(r"^(?!/)(?!.*\.\.)[A-Za-z0-9_./-]+\.v([0-9]+)\.(md|json)$")

# Edge-backed columns: (table, column) -> tables the edge may point to.
# The edge type is read from the spec's "-- edge: TYPE" comment.
EDGE_COLUMNS = {
    ("project", "sota_experiment_id"): ("experiment",),
    ("hypothesis", "parent_id"): ("hypothesis", "project"),
    ("experiment", "hypothesis_id"): ("hypothesis",),
    ("branch", "hypothesis_id"): ("hypothesis",),
    ("run", "experiment_id"): ("experiment",),
    ("decision", "target_id"): ("hypothesis", "project", "branch"),
    ("task", "target_id"): ("hypothesis", "experiment"),
}

ENTITY_TABLES = tuple(ID_PREFIX) + ("run",)
REL_ENDPOINTS = {
    "rel_compared_with": (("experiment",), ("experiment",)),
    "rel_depends_on": (("experiment",), ("experiment",)),
    "rel_references": (("hypothesis",), ("document",)),
    "rel_related": (("hypothesis",), ("hypothesis",)),
    "rel_describes": (("document",), ENTITY_TABLES),
    "rel_supersedes": (("document",), ("document",)),
    "rel_based_on": (("decision",), ("experiment", "document")),
}

# Document columns -> allowed doc_type of the referenced document.
DOC_REF_TYPES = {
    ("project", "goal_doc_id"): ("goal",),
    ("project", "min_setup_doc_id"): ("min_setup",),
    ("hypothesis", "doc_id"): ("hypothesis",),
    ("experiment", "design_doc_id"): ("experiment_design",),
    ("experiment", "result_doc_id"): ("experiment_result",),
    ("decision", "doc_id"): ("decision", "report"),
    ("task", "request_doc_id"): ("task_request",),
    ("task", "delivery_doc_id"): ("task_delivery",),
}

# doc_type -> roles that may author it (doc_library.md section 4).
DOC_AUTHORS = {
    "goal": ("rld",),
    "min_setup": ("rld",),
    "hypothesis": ("rld",),
    "novelty": ("rld",),
    "theory": ("rld",),
    "decision": ("rld",),
    "workflow": ("rld",),
    "report": ("rld",),
    "task_request": ("rld",),
    "user_instruction": ("ui", "rld"),
    "literature": ("worker", "assistant", "rld"),
    "experiment_design": ("worker", "assistant", "rld"),
    "experiment_result": ("worker", "assistant", "rld"),
    "task_delivery": ("worker", "assistant", "web_builder"),
    "other": ("ui", "rld", "worker", "assistant"),
}

CONCLUSIONS = ("no_gain", "beats_parent", "beats_sota")
RECHECK_FIELDS = {"novelty_recheck": "novelty", "theory_recheck": "theory"}
EVAL_FIELDS = ("experiment_status",) + tuple(RECHECK_FIELDS)
NODE_TRANSITIONS = {
    "pending": ("verifying",),
    "verifying": ("expandable", "prunable"),
    "expandable": ("verifying", "prunable"),
    "prunable": ("verifying",),
}
PROJECT_TRANSITIONS = {
    "active": ("go", "not_go", "stopped"),
    "go": ("active",),
    "not_go": ("active",),
    "stopped": ("active",),
}
EXEC_TRANSITIONS = {
    "planned": ("submitted", "cancelled"),
    "submitted": ("running", "succeeded", "failed", "cancelled", "unknown"),
    "running": ("succeeded", "failed", "cancelled", "unknown"),
    "unknown": ("running", "succeeded", "failed", "cancelled"),
    "succeeded": (),
    "failed": (),
    "cancelled": (),
}
TASK_TRANSITIONS = {  # status -> {to_status: role allowed to make the change}
    "open": {"in_progress": "assignee", "cancelled": "rld"},
    "in_progress": {"delivered": "assignee", "cancelled": "rld"},
    "delivered": {"accepted": "rld", "rejected": "rld", "cancelled": "rld"},
    "rejected": {"in_progress": "assignee", "cancelled": "rld"},
    "accepted": {},
    "cancelled": {},
}
# Comparison rules and seeds that must not change once experiments exist.
GATE_FIELDS = ("primary_metric", "metric_direction", "metric_is_percent", "secondary_metrics", "go_margin",
               "gate_seeds", "seeds")
RUN_MEASUREMENTS = ("metric_value", "secondary", "nodes_used", "walltime_used_s")

class ResearchDBError(Exception):
    pass


class PermissionDenied(ResearchDBError):
    pass


# ---------------------------------------------------------------------------
# Spec
# ---------------------------------------------------------------------------


@dataclass
class Column:
    name: str
    type: str
    required: bool
    default: Any = None
    enum: tuple[str, ...] | None = None
    edge: str | None = None


@dataclass
class Table:
    name: str
    label: str
    columns: dict[str, Column] = field(default_factory=dict)
    edge: str | None = None  # rel_* tables only


def _label(table: str) -> str:
    return table.capitalize()


def _convert_default(value: str | None, col_type: str) -> Any:
    if value is None:
        return None
    value = value.strip("'")
    if col_type == "INTEGER":
        return int(value)
    if col_type == "REAL":
        return float(value)
    return value


def load_spec(path: Path = SPEC_PATH) -> dict[str, Table]:
    con = sqlite3.connect(":memory:")
    try:
        con.executescript(path.read_text(encoding="utf-8"))
        tables = {}
        for name, sql in con.execute("SELECT name, sql FROM sqlite_master WHERE type = 'table'"):
            table = Table(name, _label(name))
            first_line = sql.splitlines()[0]
            m = re.search(r"--\s*edge:\s*(\w+)", first_line)
            table.edge = m.group(1) if m else None
            no_comments = re.sub(r"--[^\n]*", "", sql)
            enums = {
                col: tuple(re.findall(r"'([^']*)'", values))
                for col, values in re.findall(r"CHECK\s*\(\s*(\w+)\s+IN\s*\(([^)]*)\)\s*\)", no_comments)
            }
            edges = {
                m.group(1): m.group(2)
                for m in re.finditer(r"^\s*(\w+)\s+[A-Z_]+[^\n]*--[^\n]*edge:\s*(\w+)", sql, re.M)
            }
            for _, col, col_type, notnull, default, pk in con.execute(f"PRAGMA table_info({name})"):
                table.columns[col] = Column(
                    col, col_type, bool(notnull or pk), _convert_default(default, col_type), enums.get(col), edges.get(col)
                )
            tables[name] = table
        return tables
    finally:
        con.close()


def _check_spec(spec: dict[str, Table]) -> None:
    spec_edges = {(t.name, c.name) for t in spec.values() for c in t.columns.values() if c.edge}
    if spec_edges != set(EDGE_COLUMNS):
        raise ResearchDBError(f"edge columns in spec {sorted(spec_edges)} differ from EDGE_COLUMNS")
    rels = {t for t in spec if t.startswith("rel_")}
    if rels != set(REL_ENDPOINTS) or any(spec[t].edge is None for t in rels):
        raise ResearchDBError("rel_* tables in spec differ from REL_ENDPOINTS or lack an edge type")
    doc_cols = {(t.name, c) for t in spec.values() for c in t.columns if c == "doc_id" or c.endswith("_doc_id")}
    if doc_cols != set(DOC_REF_TYPES):
        raise ResearchDBError(f"document columns in spec {sorted(doc_cols)} differ from DOC_REF_TYPES")
    doc_types = set(spec["document"].columns["doc_type"].enum)
    if doc_types != set(DOC_AUTHORS):
        raise ResearchDBError(f"doc types in spec {sorted(doc_types)} differ from DOC_AUTHORS")


SPEC = load_spec()
_check_spec(SPEC)


def _type_ok(value: Any, col_type: str) -> bool:
    if col_type == "TEXT":
        return isinstance(value, str)
    if col_type == "INTEGER":
        return isinstance(value, int) and not isinstance(value, bool)
    if col_type == "REAL":
        return isinstance(value, (int, float)) and not isinstance(value, bool)
    if col_type == "BOOLEAN":
        return isinstance(value, bool)
    if col_type == "INTEGER_LIST":
        return isinstance(value, list) and all(isinstance(v, int) and not isinstance(v, bool) for v in value)
    if col_type == "TEXT_LIST":
        return isinstance(value, list) and all(isinstance(v, str) for v in value)
    if col_type == "JSON":
        return isinstance(value, dict) and all(isinstance(k, str) for k in value)
    raise ResearchDBError(f"unknown column type {col_type}")


def now_utc() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def table_of(entity_id: str) -> str:
    if RUN_ID_RE.match(entity_id):
        return "run"
    if ENTITY_ID_RE.match(entity_id):
        return TABLE_OF_PREFIX[entity_id.split("-", 1)[0]]
    if PROJECT_ID_RE.match(entity_id):
        return "project"
    raise ResearchDBError(f"{entity_id!r} is not a valid entity id")


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


# ---------------------------------------------------------------------------
# Transaction helpers
# ---------------------------------------------------------------------------


class _Tx:
    def __init__(self, txn):
        self.txn = txn

    def query(self, cypher: str, **params) -> list[dict]:
        return list(self.txn.query(cypher, parameters=params or None))

    def node_id(self, entity_id: str) -> int | None:
        label = _label(table_of(entity_id))
        ids = self.txn.find_nodes_by_label_property(label, "id", entity_id, limit=2)
        if len(ids) > 1:
            raise ResearchDBError(f"duplicate records for {entity_id}")
        return ids[0] if ids else None

    def get(self, entity_id: str) -> dict | None:
        table = table_of(entity_id)
        label = _label(table)
        rows = self.query(f"MATCH (n:{label} {{id: $id}}) RETURN properties(n) AS p", id=entity_id)
        if not rows:
            return None
        record = {k: v for k, v in rows[0]["p"].items() if v is not None}
        for (t, col), _ in EDGE_COLUMNS.items():
            if t == table:
                edge = SPEC[t].columns[col].edge
                targets = self.query(f"MATCH (n:{label} {{id: $id}})-[:{edge}]->(m) RETURN m.id AS t", id=entity_id)
                if targets:
                    record[col] = targets[0]["t"]
        record["_table"] = table
        return record

    def require(self, entity_id: str, tables: tuple[str, ...] | None = None) -> dict:
        try:
            record = self.get(entity_id)
        except ResearchDBError:
            record = None
        if record is None:
            raise ResearchDBError(f"{entity_id} does not exist")
        if tables and record["_table"] not in tables:
            raise ResearchDBError(f"{entity_id} is a {record['_table']}, expected {' or '.join(tables)}")
        return record

    def ids(self, table: str, where: str = "", **params) -> list[str]:
        cypher = f"MATCH (n:{_label(table)}) {where} RETURN n.id AS id"
        return sorted(row["id"] for row in self.query(cypher, **params))

    def next_id(self, table: str) -> str:
        prefix = ID_PREFIX[table]
        numbers = [int(i.split("-", 1)[1]) for i in self.ids(table) if re.fullmatch(rf"{prefix}-[0-9]+", i)]
        return f"{prefix}-{max(numbers, default=0) + 1:04d}"

    def create(self, table: str, props: dict) -> str:
        spec = SPEC[table]
        node_props = {k: v for k, v in props.items() if v is not None and not spec.columns[k].edge}
        node = self.txn.create_node(labels=[spec.label], properties=node_props)
        for col, value in props.items():
            if value is not None and spec.columns[col].edge:
                target = self.node_id(value)
                self.txn.create_edge(node.id, target, spec.columns[col].edge)
        return props["id"]

    def set(self, entity_id: str, changes: dict) -> None:
        table = table_of(entity_id)
        nid = self.node_id(entity_id)
        for col, value in changes.items():
            column = SPEC[table].columns[col]
            if column.edge:
                old = self.get(entity_id).get(col)
                if old is not None:
                    self.txn.delete_edge(nid, self.node_id(old), column.edge)
                if value is not None:
                    self.txn.create_edge(nid, self.node_id(value), column.edge)
            else:
                self.txn.set_property(nid, col, value)

    def link(self, rel: str, source: str, target: str, props: dict | None = None) -> None:
        self.txn.create_edge(self.node_id(source), self.node_id(target), SPEC[rel].edge, properties=props or None)

    def unlink_all(self, rel: str, source: str) -> None:
        for edge in self.edges(rel, source=source):
            self.txn.delete_edge(self.node_id(source), self.node_id(edge["target_id"]), SPEC[rel].edge)

    def edges(self, rel: str, source: str | None = None, target: str | None = None) -> list[dict]:
        src_tables, _ = REL_ENDPOINTS[rel]
        conditions, params = [], {}
        if source is not None:
            conditions.append("a.id = $source")
            params["source"] = source
        if target is not None:
            conditions.append("b.id = $target")
            params["target"] = target
        where = f"WHERE {' AND '.join(conditions)}" if conditions else ""
        rows = []
        for src_table in src_tables:
            cypher = (
                f"MATCH (a:{_label(src_table)})-[e:{SPEC[rel].edge}]->(b) {where} "
                "RETURN a.id AS source_id, b.id AS target_id, properties(e) AS p"
            )
            for row in self.query(cypher, **params):
                rows.append({"source_id": row["source_id"], "target_id": row["target_id"], **(row["p"] or {})})
        return sorted(rows, key=lambda r: (r["source_id"], r["target_id"]))

    def bump_meta(self) -> int:
        meta_ids = self.txn.get_nodes_by_label("Meta")
        if len(meta_ids) != 1:
            raise ResearchDBError(f"expected one Meta node, found {len(meta_ids)}")
        version = self.txn.get_property(meta_ids[0], "data_version") + 1
        self.txn.set_property(meta_ids[0], "data_version", version)
        self.txn.set_property(meta_ids[0], "updated_at", now_utc())
        return version


# ---------------------------------------------------------------------------
# Public interface
# ---------------------------------------------------------------------------


class ResearchDB:
    def __init__(self, db_path: str | Path, actor: str):
        self.db_path = Path(db_path)
        self.docs_root = self.db_path.parent / "docs"
        role, _, agent = actor.partition("/")
        if role not in ROLES or not re.fullmatch(r"[A-Za-z0-9_.]+", agent):
            raise ResearchDBError(f"actor must be <role>/<agent-id> with role in {ROLES}, got {actor!r}")
        self.role, self.agent = role, agent

    # -- sessions -----------------------------------------------------------

    @contextmanager
    def _open(self, write: bool) -> Iterator[Database]:
        if not self.db_path.exists():
            raise ResearchDBError(f"database not found: {self.db_path}")
        for attempt in range(OPEN_ATTEMPTS):
            db = Database(self.db_path, read_only=not write)
            try:
                db.open()
                break
            except LatticeDatabaseLockedError:
                if attempt == OPEN_ATTEMPTS - 1:
                    raise ResearchDBError(f"database is locked after {OPEN_ATTEMPTS} attempts: {self.db_path}") from None
                time.sleep(OPEN_RETRY_DELAY_S)
        try:
            yield db
        finally:
            db.close()

    @contextmanager
    def reader(self) -> Iterator[_Tx]:
        """Read-only session for several reads against one consistent state."""
        with self._open(write=False) as db, db.read() as txn:
            yield _Tx(txn)

    @contextmanager
    def _writer(self) -> Iterator[_Tx]:
        with self._open(write=True) as db, db.write() as txn:
            tx = _Tx(txn)
            yield tx
            tx.bump_meta()
            txn.commit()

    # -- checks ---------------------------------------------------------------

    def _require_role(self, *roles: str) -> None:
        if self.role not in roles:
            raise PermissionDenied(f"{self.role}/{self.agent} may not do this; requires role {' or '.join(roles)}")

    def _check_values(self, table: str, values: dict) -> None:
        columns = SPEC[table].columns
        for col, value in values.items():
            if col not in columns:
                raise ResearchDBError(f"{table} has no column {col!r}")
            if value is None:
                continue
            column = columns[col]
            if not _type_ok(value, column.type):
                raise ResearchDBError(f"{table}.{col} must be {column.type}, got {value!r}")
            if column.enum and value not in column.enum:
                raise ResearchDBError(f"{table}.{col} must be one of {column.enum}, got {value!r}")

    def _check_required(self, table: str, record: dict) -> None:
        missing = [c.name for c in SPEC[table].columns.values() if c.required and record.get(c.name) is None]
        if missing:
            raise ResearchDBError(f"{table} requires {', '.join(missing)}")

    def _check_refs(self, tx: _Tx, table: str, values: dict, current_docs: bool = False) -> None:
        for col, value in values.items():
            if value is None:
                continue
            if (table, col) in EDGE_COLUMNS:
                tx.require(value, EDGE_COLUMNS[(table, col)])
            if (table, col) in DOC_REF_TYPES:
                doc = tx.require(value, ("document",))
                if doc["doc_type"] not in DOC_REF_TYPES[(table, col)]:
                    raise ResearchDBError(
                        f"{table}.{col}: {value} is a {doc['doc_type']} document, expected {DOC_REF_TYPES[(table, col)]}"
                    )
                if doc["status"] == "superseded" or (current_docs and doc["status"] != "current"):
                    raise ResearchDBError(f"{table}.{col}: {value} is {doc['status']}, expected a current document")

    def _insert(self, tx: _Tx, table: str, record: dict, current_docs: bool = False) -> str:
        record = {k: v for k, v in record.items() if v is not None}
        for col, column in SPEC[table].columns.items():
            if col not in record and column.default is not None:
                record[col] = column.default
        now = now_utc()
        for col in ("created_at", "updated_at"):
            if col in SPEC[table].columns:
                record[col] = now
        self._check_values(table, record)
        self._check_required(table, record)
        if tx.node_id(record["id"]) is not None:
            raise ResearchDBError(f"{record['id']} already exists")
        self._check_refs(tx, table, record, current_docs)
        return tx.create(table, record)

    def _update(self, tx: _Tx, entity_id: str, changes: dict, current_docs: bool = False) -> None:
        table = table_of(entity_id)
        self._check_values(table, changes)
        for col, value in changes.items():
            if value is None and SPEC[table].columns[col].required:
                raise ResearchDBError(f"{table}.{col} is required and cannot be cleared")
        self._check_refs(tx, table, changes, current_docs)
        if "updated_at" in SPEC[table].columns:
            changes = {**changes, "updated_at": now_utc()}
        tx.set(entity_id, changes)

    def _project(self, tx: _Tx) -> dict:
        ids = tx.ids("project")
        if len(ids) != 1:
            raise ResearchDBError(f"expected exactly one project, found {ids}")
        return tx.get(ids[0])

    def _only_fields(self, given: dict, allowed: tuple[str, ...]) -> None:
        extra = sorted(set(given) - set(allowed))
        if extra:
            raise PermissionDenied(f"{self.role} may not set {', '.join(extra)} here")

    # -- project ---------------------------------------------------------------

    def create_project(self, id: str, title: str, min_setup_doc_id: str, primary_metric: str,
                       metric_direction: str, metric_is_percent: bool, secondary_metrics: list[str],
                       seeds: list[int], **optional) -> str:
        self._require_role("rld")
        self._only_fields(optional, ("goal_doc_id", "go_margin", "gate_seeds", "screen_budget_node_h",
                                     "min_related_work", "max_nodes", "max_walltime_s", "repo_path"))
        if table_of(id) != "project":
            raise ResearchDBError(f"project id {id!r} must be letters, digits, _ . - and must not look like another "
                                  "record's id (H-, E-, BR-, D-, DEC-, T-)")
        record = {
            "id": id, "title": title, "min_setup_doc_id": min_setup_doc_id, "primary_metric": primary_metric,
            "metric_direction": metric_direction, "metric_is_percent": metric_is_percent,
            "secondary_metrics": secondary_metrics, "seeds": seeds, "stage": "stage1", "status": "active",
            "owner": self.agent, **optional,
        }
        self._check_comparison_setup({"gate_seeds": SPEC["project"].columns["gate_seeds"].default, **record})
        with self._writer() as tx:
            if tx.ids("project"):
                raise ResearchDBError("this database already has a project")
            return self._insert(tx, "project", record)

    def _check_comparison_setup(self, project: dict) -> None:
        self._check_values("project", {k: project[k] for k in ("seeds", "secondary_metrics", "gate_seeds")})
        if len(project["seeds"]) != project["gate_seeds"] or len(set(project["seeds"])) != project["gate_seeds"]:
            raise ResearchDBError(f"seeds must be {project['gate_seeds']} distinct values")
        names = project["secondary_metrics"]
        if len(set(names)) != len(names) or project["primary_metric"] in names:
            raise ResearchDBError("secondary_metrics must be distinct and must not repeat the primary metric")

    def update_project(self, **changes) -> None:
        """Title, documents, stage, budgets and caps, the frozen harness, the SOTA baseline; comparison
        settings (GATE_FIELDS) only until the first experiment exists. A new harness clears the SOTA baseline,
        which must then be re-run and re-evaluated."""
        self._require_role("rld")
        self._only_fields(changes, ("title", "goal_doc_id", "min_setup_doc_id", "stage", "min_related_work",
                                    "screen_budget_node_h", "max_nodes", "max_walltime_s", "repo_path",
                                    "harness_ref", "harness_paths", "sota_experiment_id") + GATE_FIELDS)
        with self._writer() as tx:
            project = self._project(tx)
            if set(changes) & set(GATE_FIELDS):
                if tx.ids("experiment"):
                    raise ResearchDBError(f"{GATE_FIELDS} are fixed once experiments exist")
                self._check_comparison_setup({**project, **changes})
            final = {**project, **changes}
            if {"repo_path", "harness_ref", "harness_paths"} & set(changes):
                if not (final.get("repo_path") and final.get("harness_ref") and final.get("harness_paths")):
                    raise ResearchDBError("freezing the harness needs repo_path, harness_ref and harness_paths")
                for path in final["harness_paths"]:
                    if path.startswith("/") or ".." in Path(path).parts:
                        raise ResearchDBError(f"harness path must be relative to the repository: {path}")
                resolved = _git_commit(final["repo_path"], final["harness_ref"])
                if resolved is None:
                    raise ResearchDBError(f"{final['harness_ref']} is not a commit in {final['repo_path']}")
                changes["harness_ref"] = final["harness_ref"] = resolved
                if resolved != project.get("harness_ref") and project.get("sota_experiment_id"):
                    changes.setdefault("sota_experiment_id", None)
            sota = changes.get("sota_experiment_id")
            if sota is not None:
                exp = tx.require(sota, ("experiment",))
                if exp["kind"] != "baseline" or exp["seeds"] != final["seeds"]:
                    raise ResearchDBError(f"the SOTA baseline must be a baseline experiment on seeds {final['seeds']}")
                if exp.get("harness_ref") != final.get("harness_ref") or not exp.get("evaluated_at"):
                    raise ResearchDBError(f"{sota} must be evaluated with the current frozen harness")
            self._update(tx, project["id"], changes)

    # -- hypotheses -------------------------------------------------------------

    def create_hypothesis(self, title: str, statement: str, doc_id: str, related_work: list[str],
                          parent_id: str | None = None, priority: int = 0) -> str:
        """related_work: current literature documents consulted when creating the node (the cached
        related research); the hypothesis document records the creation rationale."""
        self._require_role("rld")
        with self._writer() as tx:
            project = self._project(tx)
            related = sorted(set(related_work))
            if len(related) < project["min_related_work"]:
                raise ResearchDBError(
                    f"a new node must reference at least {project['min_related_work']} related-work documents, "
                    f"got {len(related)}"
                )
            for doc_id_ in related:
                self._check_literature(tx, doc_id_)
            hyp_id = self._insert(tx, "hypothesis", {
                "id": tx.next_id("hypothesis"), "project_id": project["id"], "parent_id": parent_id or project["id"],
                "title": title, "statement": statement, "doc_id": doc_id, "status": "pending",
                "experiment_status": "todo", "novelty_recheck": "pending", "theory_recheck": "pending",
                "priority": priority, "owner": self.agent,
            })
            for doc_id_ in related:
                tx.link("rel_references", hyp_id, doc_id_)
            return hyp_id

    def _check_literature(self, tx: _Tx, doc_id: str) -> None:
        doc = tx.require(doc_id, ("document",))
        if (doc["doc_type"], doc["status"]) != ("literature", "current"):
            raise ResearchDBError(f"{doc_id} must be a current literature document, it is {doc['status']} {doc['doc_type']}")

    def update_hypothesis(self, hypothesis_id: str, **changes) -> None:
        """Title, statement or hypothesis document (e.g. a new version). States change only through decide()."""
        self._require_role("rld")
        self._only_fields(changes, ("title", "statement", "doc_id", "owner"))
        with self._writer() as tx:
            tx.require(hypothesis_id, ("hypothesis",))
            self._update(tx, hypothesis_id, changes)

    # -- decisions --------------------------------------------------------------

    def decide(self, target_id: str, changes: dict, reason: str, doc_id: str | None = None,
               based_on: list[str] | tuple[str, ...] = ()) -> list[str]:
        """Change hypothesis state or project status; one decision record per field.

        Hypothesis fields: status, experiment_status, novelty_recheck, theory_recheck, priority.
        Project field: status.
        """
        self._require_role("rld")
        if not reason:
            raise ResearchDBError("a decision needs a reason")
        with self._writer() as tx:
            target = tx.require(target_id, ("hypothesis", "project"))
            evidence = [tx.require(i, ("experiment", "document")) for i in based_on]
            for item in evidence:
                if item["_table"] == "document" and item["status"] != "current":
                    raise ResearchDBError(f"based_on: {item['id']} is {item['status']}, expected current")
            self._check_values(target["_table"], changes)
            if target["_table"] == "hypothesis":
                self._check_hypothesis_decision(tx, target, changes, doc_id, evidence)
            else:
                self._check_project_decision(tx, target, changes, doc_id, evidence)
            if doc_id is not None:
                self._check_refs(tx, "decision", {"doc_id": doc_id}, current_docs=True)

            decision_ids = []
            now = now_utc()
            for field_name, value in changes.items():
                decision_id = tx.next_id("decision")
                self._insert(tx, "decision", {
                    "id": decision_id, "target_id": target_id,
                    "field": "project_status" if target["_table"] == "project" else field_name,
                    "from_value": None if target.get(field_name) is None else str(target[field_name]),
                    "to_value": str(value), "reason": reason, "doc_id": doc_id,
                    "decided_by": self.agent, "decided_at": now,
                })
                for item in evidence:
                    tx.link("rel_based_on", decision_id, item["id"])
                decision_ids.append(decision_id)
            update = dict(changes)
            if target["_table"] == "hypothesis":
                update.update(_node_timestamps(target, changes, now))
                if "status" in changes:
                    update["status_reason"] = reason
            self._update(tx, target_id, update)
            return decision_ids

    def _check_hypothesis_decision(self, tx: _Tx, hyp: dict, changes: dict, doc_id: str | None,
                                   evidence: list[dict]) -> None:
        allowed = ("status", "priority") + EVAL_FIELDS
        unknown = sorted(set(changes) - set(allowed))
        if unknown or not changes:
            raise ResearchDBError(f"hypothesis decisions change {allowed}; got {sorted(changes)}")
        for field_name, value in changes.items():
            if hyp.get(field_name) == value:
                raise ResearchDBError(f"{hyp['id']}.{field_name} is already {value!r}")

        old_status = hyp["status"]
        new_status = changes.get("status", old_status)
        # A node that cannot run within caps/permissions is reported to the user; if the user declines,
        # a current user_instruction document describing this node lets RLD prune it without an experiment.
        user_declined = any(self._describes(tx, e, hyp["id"], "user_instruction") for e in evidence)
        if new_status != old_status:
            if new_status not in NODE_TRANSITIONS[old_status] and not (new_status == "prunable" and user_declined):
                raise ResearchDBError(f"{hyp['id']}: status {old_status} -> {new_status} is not allowed")
            if doc_id is None:
                raise ResearchDBError("a node status change needs a decision document (doc_id)")
            if new_status == "verifying" and self._branch_of(tx, hyp["id"]) is None:
                raise ResearchDBError(f"{hyp['id']} needs a code branch before verification starts")

        eval_changes = {f: v for f, v in changes.items() if f in EVAL_FIELDS}
        if eval_changes and old_status != "verifying" and new_status != "verifying":
            raise ResearchDBError(f"{hyp['id']}: evaluation fields change only while verifying (status is {old_status})")

        final = {**hyp, **changes}
        conclusion = changes.get("experiment_status")
        if conclusion == "todo":
            raise ResearchDBError("experiment_status returns to running, not todo")
        if conclusion in CONCLUSIONS:
            self._check_conclusion(tx, hyp, conclusion, doc_id, evidence)
        for field_name, dimension in RECHECK_FIELDS.items():
            if field_name not in changes:
                continue
            if final["experiment_status"] != "beats_sota":
                raise ResearchDBError(f"{field_name} is rechecked only after the node beats SOTA")
            if changes[field_name] in ("pass", "fail") and not any(
                self._describes(tx, e, hyp["id"], dimension) for e in evidence
            ):
                raise ResearchDBError(f"{field_name}={changes[field_name]} needs based_on a current {dimension} "
                                      f"document about {hyp['id']}")

        if new_status == "pending" and (final["experiment_status"] != "todo"
                                        or any(final[f] != "pending" for f in RECHECK_FIELDS)):
            raise ResearchDBError("a pending node has experiment_status todo and no rechecks")
        if new_status == "verifying" and final["experiment_status"] == "todo":
            raise ResearchDBError("a verifying node has its code change and experiments under way (experiment_status running)")
        if new_status == "expandable" and final["experiment_status"] not in ("beats_parent", "beats_sota"):
            raise ResearchDBError("an expandable node must beat its parent or SOTA")
        if final["experiment_status"] == "no_gain" and new_status != "prunable":
            raise ResearchDBError("a node without gain is pruned (status prunable)")
        if new_status == "prunable" and new_status != old_status and not user_declined:
            if final["experiment_status"] != "no_gain" and "fail" not in (final[f] for f in RECHECK_FIELDS):
                raise ResearchDBError(
                    "a prunable node needs experiment_status no_gain, a failed recheck, or a user instruction declining it"
                )

    def _check_conclusion(self, tx: _Tx, hyp: dict, conclusion: str, doc_id: str | None,
                          evidence: list[dict]) -> None:
        latest = self._latest_evaluated(tx, hyp["id"])
        if latest is None:
            raise ResearchDBError(f"{hyp['id']} has no experiment evaluated with the current harness")
        if latest["id"] not in {e["id"] for e in evidence}:
            raise ResearchDBError(f"experiment_status={conclusion} needs based_on the latest evaluated experiment {latest['id']}")
        if latest["verdict"] == conclusion:
            return
        if latest["verdict"] != "needs_rld":
            raise ResearchDBError(f"{latest['id']} has verdict {latest['verdict']}; experiment_status must follow it"
                                  + (" (extend its seeds first)" if latest["verdict"] == "close" else ""))
        if doc_id is None:
            raise ResearchDBError("deciding a needs_rld verdict needs a decision document (doc_id)")
        if conclusion == "beats_sota" and not any(
            e.get("passes_gate") is True for e in tx.edges("rel_compared_with", source=latest["id"])
        ):
            raise ResearchDBError(f"beats_sota needs {latest['id']} to pass the SOTA gate")

    def _describes(self, tx: _Tx, item: dict, entity_id: str, doc_type: str) -> bool:
        return (item["_table"] == "document" and item["doc_type"] == doc_type
                and bool(tx.edges("rel_describes", source=item["id"], target=entity_id)))

    def _check_project_decision(self, tx: _Tx, project: dict, changes: dict, doc_id: str | None,
                                evidence: list[dict]) -> None:
        if set(changes) != {"status"}:
            raise ResearchDBError("project decisions change only status")
        old, new = project["status"], changes["status"]
        if new not in PROJECT_TRANSITIONS[old]:
            raise ResearchDBError(f"project status {old} -> {new} is not allowed")
        if doc_id is None:
            raise ResearchDBError("a project status change needs a report or decision document (doc_id)")
        hypotheses = [tx.get(i) for i in tx.ids("hypothesis")]
        if new == "go" and not any(_is_go_candidate(h) for h in hypotheses):
            raise ResearchDBError("GO needs a node that beats SOTA and passed both rechecks")
        if new == "not_go":
            open_nodes = [h["id"] for h in hypotheses if h["status"] != "prunable"]
            if open_nodes:
                raise ResearchDBError(f"NOT GO needs every hypothesis prunable; still open: {open_nodes}")
        if new in ("stopped", "active") and not any(
            e["_table"] == "document" and e["doc_type"] == "user_instruction" for e in evidence
        ):
            raise ResearchDBError(f"project status {new} needs based_on a current user_instruction document")

    # -- experiments and runs -------------------------------------------------------

    def create_experiment(self, kind: str, method_name: str, design_doc_id: str, code_ref: str, nodes: int,
                          walltime_s: int, hypothesis_id: str | None = None, n_seeds: int | None = None,
                          **optional) -> str:
        """Seeds are the first n of project.seeds: baselines default to gate_seeds; node experiments default to
        (and may not exceed) the screening count from the SOTA cost."""
        self._require_role("rld", "worker")
        self._only_fields(optional, ("config_path", "owner"))
        if optional.get("owner") and self.role != "rld":
            raise PermissionDenied("only rld assigns an experiment to another owner")
        with self._writer() as tx:
            project = self._project(tx)
            if not project.get("harness_ref"):
                raise ResearchDBError("freeze the harness (update_project harness_ref/harness_paths) before experiments")
            if (kind == "baseline") != (hypothesis_id is None):
                raise ResearchDBError("baseline experiments have no hypothesis; all other kinds need one")
            if nodes > project["max_nodes"] or walltime_s > project["max_walltime_s"]:
                raise ResearchDBError(
                    f"a run exceeds the per-run cap ({project['max_nodes']} nodes, {project['max_walltime_s']} s); "
                    "report the budget need to the user"
                )
            limit = project["gate_seeds"] if kind == "baseline" else self._screen_seeds(tx, project)
            n = limit if n_seeds is None else n_seeds
            if not 1 <= n <= limit:
                raise ResearchDBError(f"this experiment may start with 1..{limit} seeds, got {n}")
            if hypothesis_id is not None:
                tx.require(hypothesis_id, ("hypothesis",))
                if self._branch_of(tx, hypothesis_id) is None:
                    raise ResearchDBError(f"{hypothesis_id} needs a code branch before experiments")
            resolved = _git_commit(project["repo_path"], code_ref)
            if resolved is None:
                raise ResearchDBError(f"code_ref {code_ref} is not a commit in {project['repo_path']}")
            return self._insert(tx, "experiment", {
                "id": tx.next_id("experiment"), "project_id": project["id"], "hypothesis_id": hypothesis_id,
                "kind": kind, "method_name": method_name, "design_doc_id": design_doc_id, "code_ref": resolved,
                "seeds": project["seeds"][:n], "nodes": nodes, "walltime_s": walltime_s,
                "owner": optional.pop("owner", None) or self.agent, **optional,
            })

    def screen_seed_count(self) -> int:
        with self.reader() as tx:
            return self._screen_seeds(tx, self._project(tx))

    def _screen_seeds(self, tx: _Tx, project: dict) -> int:
        """Largest n <= gate_seeds with n x (SOTA first-seed node-hours) < screen budget; at least 1."""
        sota = project.get("sota_experiment_id")
        if not sota:
            raise ResearchDBError("set the SOTA baseline before node experiments; its cost fixes the screening seeds")
        run = tx.require(f"{sota}/s{project['seeds'][0]}", ("run",))
        cost = run["nodes_used"] * run["walltime_used_s"] / 3600
        n = 1
        while n < project["gate_seeds"] and (n + 1) * cost < project["screen_budget_node_h"]:
            n += 1
        return n

    def extend_seeds(self, experiment_id: str, n_seeds: int) -> None:
        """Add seeds (next in project.seeds). Beyond the screening count only when the verdict is close or
        beats_parent, or by rld. Clears the verdict and comparisons; the experiment is evaluated again."""
        with self._writer() as tx:
            project = self._project(tx)
            exp = tx.require(experiment_id, ("experiment",))
            self._require_owner(exp)
            if not len(exp["seeds"]) < n_seeds <= project["gate_seeds"]:
                raise ResearchDBError(f"{experiment_id} has {len(exp['seeds'])} seeds; extend to at most {project['gate_seeds']}")
            if exp["kind"] != "baseline" and self.role != "rld" and n_seeds > self._screen_seeds(tx, project) \
                    and exp.get("verdict") not in ("close", "beats_parent"):
                raise ResearchDBError("seeds beyond the screening budget need verdict close or beats_parent, or rld")
            self._update(tx, experiment_id, {
                "seeds": project["seeds"][:n_seeds], "verdict": None, "metric_mean": None, "metric_sd": None,
                "result_doc_id": None, "harness_ref": None, "evaluated_at": None,
            })
            tx.unlink_all("rel_compared_with", experiment_id)

    def create_run(self, experiment_id: str, seed: int, job_id: str | None = None) -> str:
        with self._writer() as tx:
            exp = tx.require(experiment_id, ("experiment",))
            self._require_owner(exp)
            if seed not in exp["seeds"]:
                raise ResearchDBError(f"seed {seed} is not one of {experiment_id}'s seeds {exp['seeds']}")
            return self._insert(tx, "run", {
                "id": f"{experiment_id}/s{seed}", "experiment_id": experiment_id, "seed": seed,
                "job_id": job_id, "exec_status": "planned",
            })

    def update_run(self, run_id: str, **changes) -> None:
        """A valid run is frozen. A finished, invalid run is resubmitted by raising attempt by one together with
        exec_status planned/submitted, which clears its measurements."""
        self._only_fields(changes, ("job_id", "attempt", "exec_status", "valid", "curve_path", "log_path",
                                    "output_path", "started_at", "finished_at") + RUN_MEASUREMENTS)
        with self._writer() as tx:
            project = self._project(tx)
            run = tx.require(run_id, ("run",))
            self._require_owner(tx.require(run["experiment_id"]))
            if run.get("valid") is True:
                raise ResearchDBError(f"{run_id} is valid and frozen")
            old, new = run["exec_status"], changes.get("exec_status", run["exec_status"])
            retry = changes.get("attempt") == run["attempt"] + 1 and new in ("planned", "submitted")
            if "attempt" in changes and not retry:
                raise ResearchDBError("attempt only increases by one, together with exec_status planned or submitted")
            if new != old and not retry and new not in EXEC_TRANSITIONS[old]:
                raise ResearchDBError(f"exec_status {old} -> {new} is not allowed")
            if retry:
                changes = {**{k: None for k in RUN_MEASUREMENTS}, "valid": None, **changes}
            final = {**run, **changes}
            if final.get("valid") is True:
                missing = [k for k in RUN_MEASUREMENTS if final.get(k) is None]
                if new != "succeeded" or missing:
                    raise ResearchDBError(f"a valid run must have succeeded and record {', '.join(missing) or 'its measurements'}")
                if set(final["secondary"]) != set(project["secondary_metrics"]) or not all(
                    _type_ok(v, "REAL") for v in final["secondary"].values()
                ):
                    raise ResearchDBError(f"secondary must give a number for each of {project['secondary_metrics']}")
                if final["nodes_used"] > project["max_nodes"] or final["walltime_used_s"] > project["max_walltime_s"]:
                    raise ResearchDBError("recorded usage exceeds the per-run cap")
            self._update(tx, run_id, changes)
            exp = tx.get(run["experiment_id"])
            if new == "submitted" and exp.get("hypothesis_id"):
                self._stamp_once(tx, exp["hypothesis_id"], "first_experiment_at")

    def _stamp_once(self, tx: _Tx, hypothesis_id: str, field_name: str) -> None:
        """Record a node's first-time timestamp; later events never overwrite it."""
        if not tx.get(hypothesis_id).get(field_name):
            tx.set(hypothesis_id, {field_name: now_utc()})

    def _require_owner(self, record: dict) -> None:
        if self.role != "rld" and record["owner"] != self.agent:
            raise PermissionDenied(f"{record['id']} belongs to {record['owner']}")

    # -- verdicts -------------------------------------------------------------------

    def record_verdict(self, experiment_id: str, result_doc_id: str, metric_mean: float,
                       metric_sd: float | None = None, verdict: str | None = None,
                       comparisons: list[dict] | tuple[dict, ...] = ()) -> None:
        """Record the frozen statistics code's output for all seeds of an experiment.

        comparisons: [{"target_id", "role": "parent"|"sota", "n_paired", "delta_mean", "delta_sd", "deltas"}],
        deltas oriented so that positive is better. Node experiments compare with SOTA and, below the top
        level, with the parent node's latest evaluated experiment. Baselines record no verdict.
        """
        with self._writer() as tx:
            project = self._project(tx)
            exp = tx.require(experiment_id, ("experiment",))
            self._require_owner(exp)
            if exp.get("evaluated_at"):
                raise ResearchDBError(f"{experiment_id} is already evaluated; extend its seeds or start a new experiment")
            for seed in exp["seeds"]:
                run = tx.get(f"{experiment_id}/s{seed}")
                if run is None or run.get("valid") is not True:
                    raise ResearchDBError(f"seed {seed} of {experiment_id} has no valid run")
            self._check_harness(project, exp)
            self._check_refs(tx, "experiment", {"result_doc_id": result_doc_id}, current_docs=True)
            self._check_values("experiment", {"verdict": verdict, "metric_mean": metric_mean, "metric_sd": metric_sd})

            edges = []
            if exp["kind"] == "baseline":
                if verdict is not None or comparisons:
                    raise ResearchDBError("a baseline records metrics only, no verdict or comparisons")
            else:
                branch = self._branch_of(tx, exp["hypothesis_id"])
                if _git_commit(project["repo_path"], branch["base_commit"]) == exp["code_ref"]:
                    raise ResearchDBError(f"{experiment_id} ran the branch base; a node needs a code change")
                if verdict is None:
                    raise ResearchDBError("a node experiment needs a verdict")
                edges = self._check_comparisons(tx, project, exp, comparisons)
                self._check_verdict(project, exp, verdict, edges)
            self._update(tx, experiment_id, {
                "verdict": verdict, "metric_mean": metric_mean, "metric_sd": metric_sd,
                "result_doc_id": result_doc_id, "harness_ref": project["harness_ref"], "evaluated_at": now_utc(),
            })
            if exp.get("hypothesis_id"):
                self._stamp_once(tx, exp["hypothesis_id"], "first_result_at")
            for edge in edges:
                tx.link("rel_compared_with", experiment_id, edge["target_id"],
                        {k: v for k, v in edge.items() if k != "target_id" and v is not None})

    def _check_harness(self, project: dict, exp: dict) -> None:
        repo, harness = project["repo_path"], project["harness_ref"]
        if not _git_ok(repo, "merge-base", "--is-ancestor", harness, exp["code_ref"]):
            raise ResearchDBError(f"{exp['id']}: code_ref does not contain the frozen harness {harness}")
        if not _git_ok(repo, "diff", "--quiet", harness, exp["code_ref"], "--", *project["harness_paths"]):
            raise ResearchDBError(f"{exp['id']}: the harness/statistics files differ from the frozen harness")

    def _check_comparisons(self, tx: _Tx, project: dict, exp: dict, comparisons) -> list[dict]:
        sota_id = project.get("sota_experiment_id")
        if not sota_id:
            raise ResearchDBError("no SOTA baseline is set for the current harness")
        expected = {"sota": sota_id}
        parent = tx.get(exp["hypothesis_id"])["parent_id"]
        if table_of(parent) == "hypothesis":
            reference = self._latest_evaluated(tx, parent)
            if reference is None:
                raise ResearchDBError(f"parent {parent} has no experiment evaluated with the current harness")
            expected["parent"] = reference["id"]
        given = {}
        for cmp in comparisons:
            if not isinstance(cmp, dict) or set(cmp) - {"target_id", "role", "n_paired", "delta_mean", "delta_sd", "deltas"}:
                raise ResearchDBError(f"malformed comparison {cmp!r}")
            given[cmp.get("role")] = cmp
        if {r: c.get("target_id") for r, c in given.items()} != expected or len(given) != len(comparisons):
            raise ResearchDBError(f"comparisons must be exactly {expected} (role -> target experiment)")
        edges = []
        for role, cmp in given.items():
            target = tx.require(cmp["target_id"], ("experiment",))
            edge = {k: cmp.get(k) for k in ("target_id", "role", "n_paired", "delta_mean", "delta_sd", "deltas")}
            edge["passes_gate"] = None
            self._check_values("rel_compared_with", {k: v for k, v in edge.items() if k != "target_id"})
            if any(edge[k] is None for k in ("n_paired", "delta_mean", "deltas")):
                raise ResearchDBError(f"{role} comparison needs n_paired, delta_mean and deltas")
            paired = len(set(exp["seeds"]) & set(target["seeds"]))
            if edge["n_paired"] != paired or paired == 0:
                raise ResearchDBError(f"{role} comparison pairs {paired} seeds, not {edge['n_paired']}")
            if set(edge["deltas"]) != set(project["secondary_metrics"]) or not all(
                _type_ok(v, "REAL") for v in edge["deltas"].values()
            ):
                raise ResearchDBError(f"deltas must give a number for each of {project['secondary_metrics']}")
            if role == "sota":
                edge["passes_gate"] = paired == project["gate_seeds"] and edge["delta_mean"] > project["go_margin"]
            edges.append(edge)
        return edges

    def _check_verdict(self, project: dict, exp: dict, verdict: str, edges: list[dict]) -> None:
        by_role = {e["role"]: e for e in edges}
        parent = by_role.get("parent", by_role["sota"])  # top-level nodes compare with SOTA as their parent
        no_better = parent["delta_mean"] <= 0 and all(v <= 0 for v in parent["deltas"].values())
        full = len(exp["seeds"]) == project["gate_seeds"]
        if (verdict == "no_gain") != no_better:
            raise ResearchDBError("verdict no_gain applies exactly when no metric is better than the parent")
        if verdict == "close" and full:
            raise ResearchDBError(f"with {project['gate_seeds']} seeds the verdict must be conclusive, not close")
        if verdict == "beats_parent" and parent["delta_mean"] <= 0:
            raise ResearchDBError("beats_parent needs a positive primary-metric difference to the parent")
        gate = by_role["sota"]["passes_gate"]
        if verdict == "beats_sota" and not gate:
            raise ResearchDBError(
                f"beats_sota needs {project['gate_seeds']} paired seeds and a primary lead over {project['go_margin']}"
            )
        if gate and verdict not in ("beats_sota", "needs_rld"):
            raise ResearchDBError("the SOTA gate is passed; the verdict is beats_sota or needs_rld")

    def _latest_evaluated(self, tx: _Tx, hypothesis_id: str) -> dict | None:
        """The node's most recent method experiment evaluated with the current harness."""
        harness = self._project(tx)["harness_ref"]
        rows = tx.query("MATCH (e:Experiment)-[:TESTS]->(h:Hypothesis {id: $id}) RETURN e.id AS id", id=hypothesis_id)
        exps = [tx.get(r["id"]) for r in rows]
        exps = [e for e in exps if e["kind"] == "method" and e.get("verdict") and e.get("harness_ref") == harness]
        return max(exps, key=lambda e: int(e["id"].split("-")[1]), default=None)

    def latest_result(self, hypothesis_id: str) -> dict | None:
        with self.reader() as tx:
            return self._latest_evaluated(tx, hypothesis_id)

    def link(self, rel: str, source_id: str, target_id: str, **props) -> None:
        """rel_depends_on (experiment owner), rel_related and rel_references (rld), rel_describes (document
        author or rld). rel_references adds related work consulted after creation."""
        if rel not in ("rel_depends_on", "rel_related", "rel_references", "rel_describes"):
            raise ResearchDBError(f"{rel} is written by its own method, not link()")
        with self._writer() as tx:
            src_tables, dst_tables = REL_ENDPOINTS[rel]
            source = tx.require(source_id, src_tables)
            tx.require(target_id, dst_tables)
            if rel in ("rel_related", "rel_references"):
                self._require_role("rld")
                if rel == "rel_references":
                    self._check_literature(tx, target_id)
            elif rel == "rel_depends_on":
                self._require_owner(source)
            elif self.role != "rld" and source["author_id"] != self.agent:
                raise PermissionDenied(f"{source_id} was written by {source['author_id']}")
            self._check_values(rel, props)
            if any(c.required and props.get(c.name) is None for c in SPEC[rel].columns.values()
                   if c.name not in ("source_id", "target_id")):
                raise ResearchDBError(f"{rel} requires its edge properties")
            existing = tx.edges(rel, source=source_id, target=target_id)
            if any(all(e.get(k) == v for k, v in props.items()) for e in existing):
                raise ResearchDBError(f"{rel} {source_id} -> {target_id} already exists")
            tx.link(rel, source_id, target_id, props)

    def _branch_of(self, tx: _Tx, hypothesis_id: str) -> dict | None:
        rows = tx.query("MATCH (b:Branch)-[:BRANCH_OF]->(h:Hypothesis {id: $id}) RETURN b.id AS id", id=hypothesis_id)
        return tx.get(rows[0]["id"]) if rows else None

    # -- documents ------------------------------------------------------------------

    def register_document(self, path: str, doc_type: str, title: str, summary: str | None = None,
                          about: list[str] | tuple[str, ...] = ()) -> str:
        m = DOC_PATH_RE.match(path)
        if not m:
            raise ResearchDBError(f"document path must be relative, without '..', and end in .v<N>.md or .v<N>.json: {path}")
        if doc_type not in DOC_AUTHORS:
            raise ResearchDBError(f"unknown doc_type {doc_type!r}")
        if self.role not in DOC_AUTHORS[doc_type]:
            raise PermissionDenied(f"{self.role} may not author {doc_type} documents")
        if summary is not None and len(summary) > 300:
            raise ResearchDBError("summary is limited to 300 characters")
        if not (self.docs_root / path).is_file():
            raise ResearchDBError(f"document file not found: {self.docs_root / path}")
        with self._writer() as tx:
            if tx.ids("document", "WHERE n.path = $path", path=path):
                raise ResearchDBError(f"{path} is already registered")
            for entity in about:
                tx.require(entity)
            doc_id = self._insert(tx, "document", {
                "id": tx.next_id("document"), "path": path, "version": int(m.group(1)), "doc_type": doc_type,
                "title": title, "summary": summary, "status": "draft", "author_role": self.role,
                "author_id": self.agent,
            })
            for entity in about:
                tx.link("rel_describes", doc_id, entity)
            return doc_id

    def update_document(self, doc_id: str, **changes) -> None:
        self._only_fields(changes, ("title", "summary"))
        with self._writer() as tx:
            doc = tx.require(doc_id, ("document",))
            self._require_author(doc)
            if doc["status"] != "draft":
                raise ResearchDBError(f"{doc_id} is {doc['status']}; write a new version instead")
            if changes.get("summary") is not None and len(changes["summary"]) > 300:
                raise ResearchDBError("summary is limited to 300 characters")
            self._update(tx, doc_id, changes)

    def set_document_current(self, doc_id: str) -> str:
        """draft -> current; records the file's sha256 and freezes the file. Returns the hash."""
        with self._writer() as tx:
            doc = tx.require(doc_id, ("document",))
            self._require_author(doc)
            if doc["status"] != "draft":
                raise ResearchDBError(f"{doc_id} is {doc['status']}, not draft")
            digest = sha256_file(self.docs_root / doc["path"])
            self._update(tx, doc_id, {"status": "current", "sha256": digest})
            return digest

    def supersede_document(self, old_id: str, new_id: str) -> None:
        with self._writer() as tx:
            old = tx.require(old_id, ("document",))
            new = tx.require(new_id, ("document",))
            self._require_author(new)
            if (old["status"], new["status"]) != ("current", "current"):
                raise ResearchDBError("both documents must be current; the old one becomes superseded")
            if old["doc_type"] != new["doc_type"]:
                raise ResearchDBError(f"cannot supersede a {old['doc_type']} with a {new['doc_type']}")
            self._update(tx, old_id, {"status": "superseded"})
            tx.link("rel_supersedes", new_id, old_id)

    def verify_document(self, doc_id: str) -> bool:
        """True when a current/superseded document's file still matches its recorded hash."""
        with self.reader() as tx:
            doc = tx.require(doc_id, ("document",))
        if doc["status"] == "draft":
            raise ResearchDBError(f"{doc_id} is a draft; drafts have no recorded hash")
        path = self.docs_root / doc["path"]
        return path.is_file() and sha256_file(path) == doc["sha256"]

    def _require_author(self, doc: dict) -> None:
        if self.role != "rld" and (doc["author_role"], doc["author_id"]) != (self.role, self.agent):
            raise PermissionDenied(f"{doc['id']} was written by {doc['author_role']}/{doc['author_id']}")

    # -- branches -----------------------------------------------------------------------

    def create_branch(self, hypothesis_id: str, name: str, base_ref: str, base_commit: str, owner: str,
                      worktree_path: str) -> str:
        """The branch lives in the project's code repository (project.repo_path)."""
        self._require_role("rld")
        with self._writer() as tx:
            if self._branch_of(tx, hypothesis_id) is not None:
                raise ResearchDBError(f"{hypothesis_id} already has a branch")
            repo = self._project(tx).get("repo_path")
            if not repo or _git_commit(repo, base_commit) is None:
                raise ResearchDBError(f"base_commit {base_commit} is not a commit in the project repository {repo}")
            return self._insert(tx, "branch", {
                "id": tx.next_id("branch"), "hypothesis_id": hypothesis_id, "repo_path": repo, "name": name,
                "base_ref": base_ref, "base_commit": base_commit, "worktree_path": worktree_path,
                "owner": owner, "status": "active",
            })

    def return_branch(self, branch_id: str, head_commit: str) -> None:
        """The owning worker hands the branch back to RLD once everything is committed."""
        with self._writer() as tx:
            branch = tx.require(branch_id, ("branch",))
            self._require_owner(branch)
            if branch["status"] != "active":
                raise ResearchDBError(f"{branch_id} is {branch['status']}, not active")
            self._update(tx, branch_id, {
                "status": "returned", "head_commit": head_commit, "owner": self._project(tx)["owner"],
                "returned_at": now_utc(),
            })

    def close_branch(self, branch_id: str, to_status: str, reason: str, doc_id: str,
                     merged_into: str | None = None, merge_commit: str | None = None) -> str:
        """returned/kept -> merged/kept/deleted. The worktree must already be removed. Returns the decision id."""
        self._require_role("rld")
        allowed = {"returned": ("merged", "kept", "deleted"), "kept": ("merged", "deleted")}
        with self._writer() as tx:
            branch = tx.require(branch_id, ("branch",))
            if to_status not in allowed.get(branch["status"], ()):
                raise ResearchDBError(f"branch {branch['status']} -> {to_status} is not allowed")
            if to_status == "merged" and not (merged_into and merge_commit):
                raise ResearchDBError("a merged branch needs merged_into and merge_commit")
            if branch.get("worktree_path") and Path(branch["worktree_path"]).exists():
                raise ResearchDBError(f"remove the worktree {branch['worktree_path']} before closing the branch")
            if to_status == "deleted":
                self._check_experiment_tags(tx, branch)
            self._check_refs(tx, "decision", {"doc_id": doc_id}, current_docs=True)
            decision_id = tx.next_id("decision")
            self._insert(tx, "decision", {
                "id": decision_id, "target_id": branch_id, "field": "branch_status", "from_value": branch["status"],
                "to_value": to_status, "reason": reason, "doc_id": doc_id, "decided_by": self.agent,
                "decided_at": now_utc(),
            })
            self._update(tx, branch_id, {
                "status": to_status, "worktree_path": None, "merged_into": merged_into,
                "merge_commit": merge_commit, "closed_at": now_utc(),
            })
            return decision_id

    def _check_experiment_tags(self, tx: _Tx, branch: dict) -> None:
        rows = tx.query(
            "MATCH (e:Experiment)-[:TESTS]->(h:Hypothesis {id: $id}) RETURN e.id AS id, e.code_ref AS ref",
            id=branch["hypothesis_id"],
        )
        for row in rows:
            if not row["ref"]:
                continue
            tagged = _git_commit(branch["repo_path"], f"refs/tags/exp/{row['id']}")
            if tagged is None or tagged != _git_commit(branch["repo_path"], row["ref"]):
                raise ResearchDBError(f"tag exp/{row['id']} must point at code_ref {row['ref']} before deleting the branch")

    # -- tasks ----------------------------------------------------------------------------

    def create_task(self, kind: str, assignee_role: str, request_doc_id: str, target_id: str | None = None,
                    assignee_id: str | None = None) -> str:
        self._require_role("rld")
        with self._writer() as tx:
            return self._insert(tx, "task", {
                "id": tx.next_id("task"), "kind": kind, "target_id": target_id, "status": "open",
                "assignee_role": assignee_role, "assignee_id": assignee_id, "request_doc_id": request_doc_id,
            }, current_docs=True)

    def update_task(self, task_id: str, status: str | None = None, delivery_doc_id: str | None = None,
                    assignee_id: str | None = None) -> None:
        with self._writer() as tx:
            task = tx.require(task_id, ("task",))
            changes = {}
            if assignee_id is not None:
                self._require_role("rld")
                if task["status"] != "open":
                    raise ResearchDBError("a task is (re)assigned only while open")
                changes["assignee_id"] = assignee_id
            if status is not None:
                who = TASK_TRANSITIONS[task["status"]].get(status)
                if who is None:
                    raise ResearchDBError(f"task {task['status']} -> {status} is not allowed")
                if who == "rld":
                    self._require_role("rld")
                elif (self.role, self.agent) != (task["assignee_role"], task.get("assignee_id")):
                    raise PermissionDenied(f"only the assignee {task['assignee_role']}/{task.get('assignee_id')} may do this")
                changes["status"] = status
            if delivery_doc_id is not None:
                if status != "delivered":
                    raise ResearchDBError("delivery_doc_id is set together with status delivered")
                changes["delivery_doc_id"] = delivery_doc_id
            elif status == "delivered":
                raise ResearchDBError("delivering a task needs delivery_doc_id")
            if not changes:
                raise ResearchDBError("nothing to change")
            self._update(tx, task_id, changes, current_docs=True)

    # -- reads ------------------------------------------------------------------------------

    def get(self, entity_id: str) -> dict | None:
        with self.reader() as tx:
            return tx.get(entity_id)

    def find(self, table: str, **equals) -> list[dict]:
        """Records of one table whose fields (properties or edge-backed columns) equal the given values."""
        if table not in ENTITY_TABLES:
            raise ResearchDBError(f"unknown table {table!r}")
        self._check_values(table, equals)
        props = {k: v for k, v in equals.items() if (table, k) not in EDGE_COLUMNS}
        where = " AND ".join(f"n.{k} = ${k}" for k in props)
        with self.reader() as tx:
            records = [tx.get(i) for i in tx.ids(table, f"WHERE {where}" if where else "", **props)]
        # Edge-backed columns are compared on the assembled records.
        return [r for r in records if all(r.get(k) == v for k, v in equals.items())]

    def edges(self, rel: str, source_id: str | None = None, target_id: str | None = None) -> list[dict]:
        if rel not in REL_ENDPOINTS:
            raise ResearchDBError(f"unknown relation {rel!r}")
        with self.reader() as tx:
            return tx.edges(rel, source_id, target_id)

    def children(self, parent_id: str) -> list[str]:
        with self.reader() as tx:
            return sorted(r["id"] for r in tx.query(
                "MATCH (h:Hypothesis)-[:CHILD_OF]->(p {id: $id}) RETURN h.id AS id", id=parent_id))

    def history(self, target_id: str) -> list[dict]:
        """Decision records for a hypothesis, project or branch, oldest first, with their evidence ids."""
        with self.reader() as tx:
            ids = [r["id"] for r in tx.query(
                "MATCH (d:Decision)-[:DECIDES]->(t {id: $id}) RETURN d.id AS id", id=target_id)]
            records = [tx.get(i) for i in ids]
            for record in records:
                record["based_on"] = [e["target_id"] for e in tx.edges("rel_based_on", source=record["id"])]
        return sorted(records, key=lambda d: (d["decided_at"], int(d["id"].split("-")[1])))

    def go_candidates(self) -> list[str]:
        with self.reader() as tx:
            return [i for i in tx.ids("hypothesis") if _is_go_candidate(tx.get(i))]

    def export_snapshot(self) -> dict:
        """Everything in the database as JSON-ready data, for HTML generation and the git snapshot."""
        with self.reader() as tx:
            meta_id = tx.txn.get_nodes_by_label("Meta")[0]
            meta = {k: tx.txn.get_property(meta_id, k) for k in SPEC["meta"].columns}
            tables = {t: [tx.get(i) for i in tx.ids(t)] for t in ENTITY_TABLES}
            for records in tables.values():
                for record in records:
                    record.pop("_table")
            edges = {rel: tx.edges(rel) for rel in REL_ENDPOINTS}
        return {"meta": meta, "tables": tables, "edges": edges}


def _git_commit(repo: str, ref: str) -> str | None:
    result = subprocess.run(
        ["git", "-C", repo, "rev-parse", "--verify", "--quiet", f"{ref}^{{commit}}"],
        capture_output=True, text=True,
    )
    return result.stdout.strip() if result.returncode == 0 else None


def _git_ok(repo: str, *args: str) -> bool:
    return subprocess.run(["git", "-C", repo, *args], capture_output=True).returncode == 0


def _node_timestamps(hyp: dict, changes: dict, now: str) -> dict:
    """Key node timestamps implied by a decision: first start of verification, first beats_sota, and the
    latest conclusion (cleared when the node is verified again)."""
    stamps = {}
    status = changes.get("status")
    if status == "verifying":
        stamps["concluded_at"] = None
        if not hyp.get("started_at"):
            stamps["started_at"] = now
    if status in ("expandable", "prunable"):
        stamps["concluded_at"] = now
    if changes.get("experiment_status") == "beats_sota" and not hyp.get("beats_sota_at"):
        stamps["beats_sota_at"] = now
    return stamps


def _is_go_candidate(hyp: dict) -> bool:
    return hyp["experiment_status"] == "beats_sota" and all(hyp[f] == "pass" for f in RECHECK_FIELDS)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

CLI_METHODS = sorted(
    name for name in vars(ResearchDB) if not name.startswith("_") and callable(getattr(ResearchDB, name))
    and name != "reader"
)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Call one ResearchDB method; prints the result as JSON.")
    parser.add_argument("--db", required=True, type=Path)
    parser.add_argument("--actor", required=True, help="<role>/<agent-id>")
    parser.add_argument("method", choices=CLI_METHODS)
    parser.add_argument("kwargs", nargs="?", default="{}", help="JSON object of keyword arguments")
    args = parser.parse_args(argv)
    try:
        kwargs = json.loads(args.kwargs)
        if not isinstance(kwargs, dict):
            raise ResearchDBError("kwargs must be a JSON object")
        result = getattr(ResearchDB(args.db, args.actor), args.method)(**kwargs)
    except (ResearchDBError, json.JSONDecodeError, TypeError) as exc:
        print(json.dumps({"ok": False, "error": f"{type(exc).__name__}: {exc}"}, ensure_ascii=False))
        return 2
    print(json.dumps({"ok": True, "result": result}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
