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
import inspect
import json
import math
import os
import re
import shutil
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

sys.path.insert(0, str(Path(__file__).resolve().parent))
import evidence as claims_check  # noqa: E402
import metrics  # noqa: E402
from metrics import MetricError  # noqa: E402

SPEC_PATH = Path(__file__).resolve().parent.parent / "schema" / "research_tree.sql"
# The project's own cleanup script (in the project directory, beside research-tree.yaml), copied from this template.
CLEANUP_SCRIPT = "research-tree-cleanup.py"
CLEANUP_TEMPLATE = Path(__file__).resolve().parent.parent / "schema" / "cleanup.template.py"
# The database layout this interface writes (schema/create_db.py SCHEMA_VERSION; a test keeps them equal).
SCHEMA_VERSION = 12
OPEN_ATTEMPTS = 40
OPEN_RETRY_DELAY_S = 0.25

ROLES = ("ui", "rld", "worker", "assistant", "web_builder", "reviewer")

ID_PREFIX = {
    "project": "P",
    "hypothesis": "H",
    "experiment": "E",
    "branch": "BR",
    "document": "D",
    "decision": "DEC",
    "task": "T",
    "evaluation": "EV",
    "obligation": "OB",
    "reservation": "RS",
}
TABLE_OF_PREFIX = {prefix: table for table, prefix in ID_PREFIX.items()}
ENTITY_ID_RE = re.compile(r"^(P|H|E|EV|OB|RS|BR|D|DEC|T)-[A-Za-z0-9_.-]+$")
# A project may also be named like its directory / uv project (`my-study`), as long as it does not look like
# another record's id.
PROJECT_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]*$")
RUN_ID_RE = re.compile(r"^(E-[A-Za-z0-9_.-]+)/s(-?[0-9]+)$")
DOC_PATH_RE = re.compile(r"^(?!/)(?!.*\.\.)[A-Za-z0-9_./-]+\.v([0-9]+)\.(md|json|yaml)$")

# Edge-backed columns: (table, column) -> tables the edge may point to.
# The edge type is read from the spec's "-- edge: TYPE" comment.
EDGE_COLUMNS = {
    ("project", "sota_experiment_id"): ("experiment",),
    ("hypothesis", "parent_id"): ("hypothesis", "project"),
    ("experiment", "hypothesis_id"): ("hypothesis",),
    ("branch", "hypothesis_id"): ("hypothesis",),
    ("run", "experiment_id"): ("experiment",),
    ("decision", "target_id"): ("hypothesis", "project", "branch"),
    ("task", "target_id"): ("hypothesis", "project", "experiment"),
    ("evaluation", "experiment_id"): ("experiment",),
}

ENTITY_TABLES = tuple(ID_PREFIX) + ("run",)
REL_ENDPOINTS = {
    "rel_compared_with": (("experiment",), ("experiment",)),
    "rel_depends_on": (("experiment",), ("experiment",)),
    "rel_references": (("hypothesis",), ("document",)),
    "rel_related": (("hypothesis",), ("hypothesis",)),
    "rel_describes": (("document",), ENTITY_TABLES),
    "rel_supersedes": (("document",), ("document",)),
    "rel_based_on": (("decision",), ("experiment", "document", "evaluation")),
}

# Document columns -> allowed doc_type of the referenced document.
DOC_REF_TYPES = {
    ("project", "goal_doc_id"): ("goal",),
    ("project", "min_setup_doc_id"): ("min_setup",),
    ("project", "config_doc_id"): ("config",),
    ("project", "protocol_doc_id"): ("protocol",),
    ("project", "metric_spec_doc_id"): ("metric_spec",),
    ("evaluation", "protocol_doc_id"): ("protocol",),
    ("evaluation", "metric_spec_doc_id"): ("metric_spec",),
    ("evaluation", "result_doc_id"): ("experiment_result",),
    ("hypothesis", "doc_id"): ("hypothesis",),
    ("experiment", "design_doc_id"): ("experiment_design",),
    ("experiment", "result_doc_id"): ("experiment_result",),
    ("experiment", "code_review_waiver_doc_id"): ("decision",),
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
    "config": ("rld",),
    "protocol": ("rld",),
    "metric_spec": ("rld",),
    "task_request": ("rld",),
    "user_instruction": ("ui", "rld"),
    "literature": ("worker", "assistant", "rld"),
    "experiment_design": ("worker", "assistant", "rld"),
    "experiment_result": ("worker", "assistant", "rld"),
    "task_delivery": ("worker", "assistant", "web_builder"),
    "other": ("ui", "rld", "worker", "assistant"),
    "review": ("reviewer",),  # only through review_call.py (plans/design 09 §4)
}
CANDIDATE_ID_RE = re.compile(r"CAND-\d{4,}")
POSITIVE_NOVELTY = ("PROCEED", "PROCEED_WITH_CAUTION")  # 09 §3: CAUTION is positive; only a named ABANDON is not
REVIEW_KINDS = ("triage", "novelty_precheck", "critical_review", "proposal_review", "ablation_plan", "code_review",
                "candidate_recheck")
# A GO candidate's rechecks (07 §2): the dimensions about numbers are bound to the evaluation they checked, the
# others to its code (they stay valid when seeds are added to the same code, 07 §3).
RECHECK_DIMENSIONS = {"numbers": "evaluation", "protocol": "evaluation", "method_code": "code",
                      "novelty": "code", "theory": "code"}

CONCLUSIONS = ("no_gain", "beats_parent", "beats_sota", "inconclusive")
# A decision resting on an inconclusive result lists what is missing and the next experiment (03 §9, 06 §7).
INCONCLUSIVE_SECTIONS = ("缺失证据", "下一实验")
# From idea to experiment design (plans/design 03 §2, §10): the goal's problem anchor (copied verbatim into every
# hypothesis document), the hypothesis document's sections and an experiment design's fields.
ANCHOR_SECTION = "问题锚点"
ANCHOR_FIELDS = ("底线问题", "必须解决的瓶颈", "非目标", "约束", "成功条件")
HYPOTHESIS_SECTIONS = ("问题锚点", "方法步骤", "技术缺口", "可证伪预测与竞争解释", "最接近工作与差异", "Claim map",
                       "实验块", "成本估计", "停止条件", "有意舍弃的复杂度")
EXPERIMENT_DESIGN_SECTIONS = ("检验的 claim", "存在理由", "数据与切分", "比较系统", "指标", "设定", "成功判据",
                              "失败解释", "表图目标", "优先级与成本")
BLOCK_FIELDS = ("成功判据", "失败解释")
# Evaluation types that bound the wording of a result (03 §5, 04 §6): no SOTA claim on a proxy.
PROXY_EVAL_TYPES = ("synthetic_proxy", "self_supervised_proxy", "simulation_only")
SOTA_CLAIM_RE = re.compile(r"优于\s*SOTA|超过\s*SOTA|超越\s*SOTA|beats?\s+(the\s+)?SOTA|state[- ]of[- ]the[- ]art|新的\s*SOTA",
                           re.I)
FAILURE_PATCHES, FAILURE_REWRITES = 2, 2  # 03 §8: per root cause
BLOCK_RE_EVIDENCE = re.compile(r"^```evidence[ \t]*\n.*?^```[ \t]*$", re.M | re.S)
# What a NOT GO report accounts for, node by node (06 §3.3).
NOT_GO_SECTIONS = ("未探索", "工程失败", "不确定", "重复方向", "明确反证", "投入价值判断")
DISPOSITIONS = ("active", "paused", "retired")
# The execution lifecycle as the old node status shows it (06 §3.1).
BUDGET_POOLS = ("search", "confirmation", "repair")
SUBMISSION_KEY_RE = re.compile(r"[A-Za-z0-9_.:@/-]{1,128}")
LIFECYCLE = {"pending": "pending", "verifying": "verifying", "expandable": "assessed", "prunable": "assessed"}
SEVERITIES = ("CRITICAL", "MAJOR", "MINOR")
FIX_TYPES = ("corrected_from_results", "re_evaluated", "re_run", "code_fixed", "claim_narrowed", "claim_withdrawn",
             "citation_replaced")
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
    "planned": ("submitted", "cancelled", "unknown"),  # unknown: a submit timed out under a claimed reservation
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
# What import_run_result writes besides the measurements; kept per attempt like them.
IMPORT_FIELDS = ("manifest_path", "manifest", "evidence_paths", "import_record")
# The '## ' sections a task's request and delivery documents must have: what a delegation and its result hand over.
TASK_SECTIONS = {
    "task_request": ("任务与节点", "问题与预测", "干预与对照", "范围与权限", "资源与预算", "验收与停止条件", "交付"),
    "task_delivery": ("实际改动与版本", "运行与产物", "验证结果", "资源观测", "未完成与未知项"),
}
RESEARCH_TASK_KINDS = ("harness", "literature", "experiment", "analysis")
FINAL_EXEC = ("succeeded", "failed", "cancelled")
# What one attempt of a run records; kept in run.attempts when the run is resubmitted.
REPORTED_FIELDS = ("job_id", "exec_status", "valid", "invalid_reason", "curve_path", "log_path", "output_path",
                   "started_at", "finished_at")
ATTEMPT_FIELDS = (REPORTED_FIELDS + RUN_MEASUREMENTS + IMPORT_FIELDS
                  + ("retracted_at", "retracted_reason", "submission_key"))
# Settings from the project configuration (research-tree.yaml) besides the caps and gates above.
LIMIT_FIELDS = ("max_parallel_workers", "alert_node_h", "config_doc_id", "total_limit", "search_limit",
                "confirmation_limit", "repair_limit", "overrun_factor", "stall_structural_at", "stall_human_at",
                "recheck_required", "review_usd_alert", "screen_seeds", "design_required", "max_primary_claims",
                "max_core_blocks", "code_review_required", "sanity_required", "require_precheck",
                "literature_verification")
# The documents evaluations are computed under (plans/design/04): protocol and metric specification.
EVIDENCE_DOC_FIELDS = ("protocol_doc_id", "metric_spec_doc_id")
# Caps the user authorizes (10 §1.5): an agent may lower them, raising one (or lifting it, None) needs the user.
CAP_FIELDS = ("total_limit", "search_limit", "confirmation_limit", "repair_limit", "max_nodes", "max_walltime_s",
              "alert_node_h", "review_usd_alert")

class ResearchDBError(Exception):
    pass


class PermissionDenied(ResearchDBError):
    pass


class CodedError(ResearchDBError):
    """A refusal with one of the stable error codes of plans/design/10 §1.6 (STAT_MISMATCH, EVIDENCE_STALE, ...)."""

    def __init__(self, code: str, message: str):
        super().__init__(f"{code}: {message}")
        self.code = code


@contextmanager
def _coded() -> Iterator[None]:
    """metrics.MetricError as a CodedError of this interface."""
    try:
        yield
    except MetricError as exc:
        raise CodedError(exc.code, str(exc).split(": ", 1)[1]) from None


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
    if col_type == "BOOLEAN":
        return value.upper() in ("TRUE", "1")
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
        # research/<project-id>/research_tree.db lives in the project directory.
        self.project_dir = self.db_path.resolve().parent.parent.parent
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
            meta = txn.get_nodes_by_label("Meta")
            version = txn.get_property(meta[0], "schema_version") if meta else None
            if version != SCHEMA_VERSION:
                raise ResearchDBError(
                    f"{self.db_path} has schema_version {version}, this plugin writes version {SCHEMA_VERSION}: "
                    + ("back up the research directory, run `python <plugin>/schema/create_db.py --upgrade "
                       f"{self.db_path}`, then migrate_evaluations (dry_run first)" if isinstance(version, int)
                       and version < SCHEMA_VERSION else "use the plugin version that wrote it")
                    + "; reading still works")
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
            raise ResearchDBError(f"this method does not take {', '.join(extra)}; it takes {', '.join(allowed)}")

    def _require_active(self, project: dict) -> None:
        if project["status"] != "active":
            raise ResearchDBError(
                f"project {project['id']} is {project['status']}: no new research work after GO, NOT GO or a stop; "
                "resuming needs a user instruction (decide project status active, based_on that instruction)")

    # -- project ---------------------------------------------------------------

    def create_project(self, id: str, title: str, min_setup_doc_id: str, primary_metric: str,
                       metric_direction: str, metric_is_percent: bool, secondary_metrics: list[str],
                       seeds: list[int], **optional) -> str:
        """The project record (the tree's root): comparison setup and caps; rld only, once per database."""
        self._require_role("rld")
        self._only_fields(optional, ("goal_doc_id", "go_margin", "gate_seeds", "screen_budget_node_h",
                                     "min_related_work", "max_nodes", "max_walltime_s", "repo_path")
                          + LIMIT_FIELDS + EVIDENCE_DOC_FIELDS)
        if table_of(id) != "project":
            raise ResearchDBError(f"project id {id!r} must be letters, digits, _ . - and must not look like another "
                                  "record's id (H-, E-, BR-, D-, DEC-, T-)")
        missing = [k for k in EVIDENCE_DOC_FIELDS if not optional.get(k)]
        if missing:
            raise CodedError("PROTOCOL_CHANGE_REQUIRED", f"a new project registers its metric specification and "
                                                         f"protocol documents first; missing {', '.join(missing)} "
                                                         "(see doc_library: metric_spec, protocol)")
        record = {
            "id": id, "title": title, "min_setup_doc_id": min_setup_doc_id, "primary_metric": primary_metric,
            "metric_direction": metric_direction, "metric_is_percent": metric_is_percent,
            "secondary_metrics": secondary_metrics, "seeds": seeds, "stage": "stage1", "status": "active",
            "owner": self.agent, **optional,
            "resume_doc_ids": [min_setup_doc_id] + ([optional["goal_doc_id"]] if optional.get("goal_doc_id") else []),
        }
        self._check_comparison_setup({"gate_seeds": SPEC["project"].columns["gate_seeds"].default, **record})
        with self._writer() as tx:
            if tx.ids("project"):
                raise ResearchDBError("this database already has a project")
            self._check_evidence_docs(tx, {"gate_seeds": SPEC["project"].columns["gate_seeds"].default,
                                           "go_margin": SPEC["project"].columns["go_margin"].default, **record})
            return self._insert(tx, "project", record)

    def _check_comparison_setup(self, project: dict) -> None:
        self._check_values("project", {k: project[k] for k in ("seeds", "secondary_metrics", "gate_seeds")})
        for name in ("max_parallel_workers", "alert_node_h"):
            if project.get(name) is not None and not (_type_ok(project[name], SPEC["project"].columns[name].type)
                                                      and project[name] > 0):
                raise ResearchDBError(f"{name} must be positive or null")
        if len(project["seeds"]) != project["gate_seeds"] or len(set(project["seeds"])) != project["gate_seeds"]:
            raise ResearchDBError(f"seeds must be {project['gate_seeds']} distinct values")
        names = project["secondary_metrics"]
        if len(set(names)) != len(names) or project["primary_metric"] in names:
            raise ResearchDBError("secondary_metrics must be distinct and must not repeat the primary metric")

    def update_project(self, user_instruction_doc_id: str | None = None, **changes) -> None:
        """Title, documents, stage, budgets and caps, the frozen harness, the SOTA baseline, the protocol and metric
        specification documents; comparison settings (GATE_FIELDS) only until the first experiment exists. A new
        harness clears the SOTA baseline, which must then be re-run and re-evaluated. Once experiments exist, a new
        protocol_doc_id or metric_spec_doc_id needs user_instruction_doc_id (a current user_instruction: the user
        decided the change, never an agent after seeing results); evaluations under the old ones stop supporting
        GO."""
        self._require_role("rld")
        self._only_fields(changes, ("title", "goal_doc_id", "min_setup_doc_id", "stage", "min_related_work",
                                    "screen_budget_node_h", "max_nodes", "max_walltime_s", "repo_path",
                                    "harness_ref", "harness_paths", "sota_experiment_id")
                          + GATE_FIELDS + LIMIT_FIELDS + EVIDENCE_DOC_FIELDS)
        with self._writer() as tx:
            project = self._project(tx)
            if set(changes) & set(GATE_FIELDS):
                if tx.ids("experiment"):
                    raise ResearchDBError(f"{GATE_FIELDS} are fixed once experiments exist")
                self._check_comparison_setup({**project, **changes})
            final = {**project, **changes}
            if final.get("metric_spec_doc_id") and set(changes) & (set(GATE_FIELDS) | set(EVIDENCE_DOC_FIELDS)):
                self._check_evidence_docs(tx, final)  # the gate is stated once: project and specification agree
            if any(k in changes and changes[k] != project.get(k) for k in EVIDENCE_DOC_FIELDS):
                if tx.ids("experiment"):
                    instruction = user_instruction_doc_id and tx.get(user_instruction_doc_id)
                    if not instruction or (instruction.get("doc_type"), instruction.get("status")) != (
                            "user_instruction", "current"):
                        raise CodedError("PROTOCOL_CHANGE_REQUIRED",
                                         "experiments exist: a new protocol or metric specification is the user's "
                                         "decision; pass user_instruction_doc_id, the current user_instruction "
                                         "document that records it")
                self._check_evidence_docs(tx, final)
            raised = [k for k in CAP_FIELDS if k in changes and changes[k] != project.get(k) and (
                changes[k] is None or (project.get(k) is not None and changes[k] > project[k]))]
            for gate in ("recheck_required", "design_required", "code_review_required", "sanity_required",
                         "require_precheck", "literature_verification"):
                if project.get(gate) and changes.get(gate) is False:
                    raised.append(gate)  # dropping a gate lowers the bar: the user's decision
            if raised:
                instruction = user_instruction_doc_id and tx.get(user_instruction_doc_id)
                if not instruction or (instruction.get("doc_type"), instruction.get("status")) != (
                        "user_instruction", "current"):
                    raise CodedError("BUDGET_EXCEEDED", f"raising {', '.join(raised)} is the user's decision: pass "
                                                        "user_instruction_doc_id, the current user_instruction "
                                                        "document that records it (research-tree.yaml, config apply)")
            if {"max_parallel_workers", "alert_node_h"} & set(changes):
                self._check_comparison_setup(final)
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
                frozen_set = sorted(final["harness_paths"]) != sorted(project.get("harness_paths") or [])
                if (resolved != project.get("harness_ref") or frozen_set) and project.get("sota_experiment_id"):
                    changes.setdefault("sota_experiment_id", None)  # a new frozen harness: the SOTA is run again
            sota = changes.get("sota_experiment_id")
            if sota is not None:
                exp = tx.require(sota, ("experiment",))
                if exp["kind"] != "baseline" or exp["seeds"] != final["seeds"]:
                    raise ResearchDBError(f"the SOTA baseline must be a baseline experiment on seeds {final['seeds']}")
                if not exp.get("evaluated_at"):
                    invalid = _invalid_runs(tx, exp)
                    raise ResearchDBError(
                        f"{sota} is not evaluated yet: its owner (or rld) calls evaluate_experiment(experiment_id, "
                        "result_doc_id) with no verdict, as baselines record metrics only, "
                        "once every seed has a valid run" + (f"; not yet valid: {invalid}. {VALID_RUN_HOW}" if invalid else ""))
                if exp.get("harness_ref") != final.get("harness_ref"):
                    raise ResearchDBError(
                        f"{sota} was evaluated with harness {str(exp.get('harness_ref'))[:10]}, but the frozen harness is "
                        f"{str(final.get('harness_ref'))[:10]}: run the baseline again with the frozen harness "
                        "(create_experiment kind=baseline, then its runs and evaluate_experiment) and set that experiment")
            self._update(tx, project["id"], changes)

    def check_project_changes(self, **changes) -> None:
        """Refuse, without writing, project changes the gate rules would refuse (config apply checks before it
        registers a new configuration version): comparison settings and their agreement with the metric
        specification and protocol."""
        with self.reader() as tx:
            project = self._project(tx)
            final = {**project, **changes}
            if set(changes) & set(GATE_FIELDS):
                self._check_comparison_setup(final)
            if final.get("metric_spec_doc_id") and set(changes) & (set(GATE_FIELDS) | set(EVIDENCE_DOC_FIELDS)):
                self._check_evidence_docs(tx, final)

    def _check_evidence_docs(self, tx: _Tx, project: dict) -> None:
        """The metric specification fits the project's metrics (same primary and direction, a spec for every
        secondary metric); the protocol is well formed. Both are current documents."""
        for key in EVIDENCE_DOC_FIELDS:
            if project.get(key) and tx.require(project[key], ("document",))["status"] != "current":
                raise ResearchDBError(f"{key}: {project[key]} is not current; set_document_current first")
        if project.get("metric_spec_doc_id"):
            specs = self._json_doc(tx, project["metric_spec_doc_id"], "metric_spec")
            with _coded():
                metrics.check_metric_specs(specs)
            names = {s["name"] for s in specs["metrics"]}
            primary = metrics.spec_by_name(specs)[specs["primary"]]
            wanted = {project["primary_metric"], *project["secondary_metrics"]}
            if specs["primary"] != project["primary_metric"] or primary["direction"] != project["metric_direction"] \
                    or names != wanted:
                raise CodedError("METRIC_UNIT_MISMATCH",
                                 f"{project['metric_spec_doc_id']} must specify exactly the project's metrics "
                                 f"{sorted(wanted)} with primary {project['primary_metric']} "
                                 f"({project['metric_direction']} is better); it has {sorted(names)}, primary "
                                 f"{specs['primary']} ({primary['direction']})")
            if not project.get("protocol_doc_id"):
                raise CodedError("PROTOCOL_CHANGE_REQUIRED", "a project with a metric specification also registers a "
                                                             "protocol (protocol_doc_id): its evaluation type labels "
                                                             "every evaluation")
            if primary["minimum_practical_gain"] != project.get("go_margin"):
                raise CodedError("METRIC_UNIT_MISMATCH",
                                 f"the primary metric's minimum_practical_gain {primary['minimum_practical_gain']} "
                                 f"must equal the project's go_margin {project.get('go_margin')} (stage1.go_margin "
                                 "in research-tree.yaml): one SOTA gate, stated once")
        if project.get("protocol_doc_id"):
            with _coded():
                protocol = metrics.check_protocol(self._json_doc(tx, project["protocol_doc_id"], "protocol"))
            if protocol.get("min_pairs") is not None and protocol["min_pairs"] < project["gate_seeds"]:
                raise CodedError("PROTOCOL_CHANGE_REQUIRED", f"min_pairs {protocol['min_pairs']} is below gate_seeds "
                                                             f"{project['gate_seeds']}")

    def _json_doc(self, tx: _Tx, doc_id: str, doc_type: str) -> dict:
        """A JSON document's content; a frozen document must still match its recorded hash."""
        doc = tx.require(doc_id, ("document",))
        if doc["doc_type"] != doc_type:
            raise ResearchDBError(f"{doc_id} is a {doc['doc_type']} document, expected {doc_type}")
        path = self.docs_root / doc["path"]
        if not path.is_file() or (doc.get("sha256") and sha256_file(path) != doc["sha256"]):
            raise ResearchDBError(f"{doc_id} ({doc['path']}) is missing or no longer matches its recorded hash")
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            raise ResearchDBError(f"{doc_id} ({doc['path']}) is not JSON: {exc}") from None

    def _specs(self, tx: _Tx, project: dict) -> dict:
        """The project's metric specification, or the compatibility one for a project without it."""
        if project.get("metric_spec_doc_id"):
            return self._json_doc(tx, project["metric_spec_doc_id"], "metric_spec")
        return metrics.legacy_specs(project)

    def _protocol(self, tx: _Tx, project: dict) -> dict | None:
        return self._json_doc(tx, project["protocol_doc_id"], "protocol") if project.get("protocol_doc_id") else None

    # -- hypotheses -------------------------------------------------------------

    def create_hypothesis(self, title: str, statement: str, doc_id: str, related_work: list[str],
                          parent_id: str | None = None, priority: int = 0, direction: str | None = None,
                          candidate_id: str | None = None, user_instruction_doc_id: str | None = None) -> str:
        """related_work: current literature documents consulted when creating the node (the cached
        related research); the hypothesis document records the creation rationale.

        The tree's root is the project: it holds the baselines (frozen harness, SOTA and other baseline
        experiments) and no hypothesis. Without parent_id a node is a child of the root, as every initial
        hypothesis is; a node is derived below another hypothesis only once that one is verified and
        expandable, so the level of a node never has to be guessed.

        With literature_verification only literature whose existence was verified (front matter `verification:
        verified`) counts toward min_related_work. With require_precheck an initial node names the discovery
        candidate it comes from (candidate_id) and needs that candidate's receipts: a current novelty_precheck
        that is PROCEED or PROCEED_WITH_CAUTION and a critical_review with stance proceed. A negative receipt does
        not drop a user's hypothesis: the user decides, and user_instruction_doc_id (their current instruction)
        then admits it."""
        self._require_role("rld")
        with self._writer() as tx:
            project = self._project(tx)
            self._require_active(project)
            if parent_id is not None and parent_id != project["id"]:
                parent = tx.require(parent_id, ("hypothesis",))
                if parent["status"] != "expandable":
                    raise ResearchDBError(
                        f"{parent_id} is {parent['status']}: new nodes go below the root (no parent_id) or below a "
                        "verified, expandable node"
                    )
            self._check_stall(tx, parent_id, direction)
            if project.get("design_required"):
                self._check_hypothesis_doc(tx, project, doc_id)
            related = sorted(set(related_work))
            if len(related) < project["min_related_work"]:
                raise ResearchDBError(
                    f"a new node must reference at least {project['min_related_work']} related-work documents, "
                    f"got {len(related)}"
                )
            for doc_id_ in related:
                self._check_literature(tx, doc_id_)
            if project.get("literature_verification"):
                verified = [d for d in related if self._literature_verified(tx, d)]
                if len(verified) < project["min_related_work"]:
                    raise ResearchDBError(
                        f"only {len(verified)} of the cited literature documents are verified to exist "
                        f"(front matter verification: verified); a node needs {project['min_related_work']} — "
                        "unverified literature is kept but does not count (literature.py verify)")
            if project.get("require_precheck") and parent_id in (None, project["id"]):
                self._check_receipts(tx, candidate_id, user_instruction_doc_id)
            elif candidate_id is not None and not CANDIDATE_ID_RE.fullmatch(candidate_id):
                raise ResearchDBError("candidate_id is a discovery candidate id (CAND-0001)")
            hyp_id = self._insert(tx, "hypothesis", {
                "id": tx.next_id("hypothesis"), "project_id": project["id"], "parent_id": parent_id or project["id"],
                "title": title, "statement": statement, "doc_id": doc_id, "status": "pending",
                "experiment_status": "todo", "novelty_recheck": "pending", "theory_recheck": "pending",
                "priority": priority, "owner": self.agent, "resume_doc_ids": [doc_id],
                "disposition": "active", "direction": direction, "new_findings_streak": 0, "stall_state": "none",
                "candidate_id": candidate_id,
            })
            for doc_id_ in related:
                tx.link("rel_references", hyp_id, doc_id_)
            return hyp_id

    def _doc_sections(self, tx: _Tx, doc_id: str) -> tuple[dict, str]:
        """A document's '## ' sections: {heading: body}, and the document's path."""
        doc = tx.require(doc_id, ("document",))
        path = self.docs_root / doc["path"]
        text = path.read_text(encoding="utf-8") if path.is_file() else ""
        return dict(re.findall(r"^##[ \t]+(.+?)[ \t]*\n(.*?)(?=^##[ \t]|\Z)", text, re.M | re.S)), doc["path"]

    @staticmethod
    def _section(sections: dict, name: str) -> str | None:
        return next((body for heading, body in sections.items() if heading.lower().startswith(name.lower())), None)

    def _anchor(self, tx: _Tx, doc_id: str) -> str | None:
        body = self._section(self._doc_sections(tx, doc_id)[0], ANCHOR_SECTION)
        return None if body is None else re.sub(r"\s+", " ", re.sub(r"<!--.*?-->", "", body, flags=re.S)).strip()

    def _check_hypothesis_doc(self, tx: _Tx, project: dict, doc_id: str) -> None:
        """03 §10: the hypothesis document has its sections, the goal's problem anchor verbatim, a claim map of at
        most max_primary_claims claims and at most max_core_blocks experiment blocks, each with its success
        criterion and failure interpretation written before the experiment."""
        goal = project.get("goal_doc_id")
        anchor = self._anchor(tx, goal) if goal else None
        if not anchor or not all(f in anchor for f in ANCHOR_FIELDS):
            raise ResearchDBError(f"the goal document {goal} needs a '## {ANCHOR_SECTION}' section with "
                                  f"{', '.join(ANCHOR_FIELDS)} (03 §2); register a goal version with it "
                                  "(update_project goal_doc_id)")
        sections, path = self._doc_sections(tx, doc_id)
        missing = [name for name in HYPOTHESIS_SECTIONS if self._section(sections, name) is None]
        if missing:
            raise ResearchDBError(f"{doc_id} ({path}) lacks the sections {', '.join(missing)}; a hypothesis document "
                                  f"has the '## ' sections {', '.join(HYPOTHESIS_SECTIONS)} (03 §10)")
        if self._anchor(tx, doc_id) != anchor:
            raise ResearchDBError(f"{doc_id}'s {ANCHOR_SECTION} differs from the goal's ({goal}): the anchor is copied "
                                  "verbatim; a change of the problem is drift — push back, or change the anchor in "
                                  "the goal with the user's instruction")
        rows = [line for line in self._section(sections, "Claim map").splitlines() if line.strip().startswith("|")]
        claims = [r for r in rows[2:] if r.strip("|").strip()]  # header and separator rows first
        if not 1 <= len(claims) <= project.get("max_primary_claims", 2):
            raise ResearchDBError(f"{doc_id}: the claim map has {len(claims)} claims; 1..{project.get('max_primary_claims', 2)} "
                                  "primary claims (design.max_primary_claims)")
        blocks = re.split(r"^###[ \t]+", self._section(sections, "实验块"), flags=re.M)[1:]
        if not 1 <= len(blocks) <= project.get("max_core_blocks", 5):
            raise ResearchDBError(f"{doc_id}: {len(blocks)} experiment blocks ('### ' under 实验块); "
                                  f"1..{project.get('max_core_blocks', 5)} (design.max_core_blocks)")
        for block in blocks:
            lacking = [f for f in BLOCK_FIELDS if f not in block]
            if lacking:
                raise ResearchDBError(f"{doc_id}: experiment block '{block.splitlines()[0].strip()}' lacks "
                                      f"{', '.join(lacking)}: written before the experiment, never after the result")

    def _check_design_doc(self, tx: _Tx, doc_id: str) -> None:
        sections, path = self._doc_sections(tx, doc_id)
        missing = [name for name in EXPERIMENT_DESIGN_SECTIONS if self._section(sections, name) is None]
        if missing:
            raise ResearchDBError(f"{doc_id} ({path}) lacks the sections {', '.join(missing)}; an experiment design "
                                  f"has the '## ' sections {', '.join(EXPERIMENT_DESIGN_SECTIONS)} (03 §4, §10)")

    def _literature_verified(self, tx: _Tx, doc_id: str) -> bool:
        return self._literature_verified_path(tx.get(doc_id)["path"])

    def _literature_verified_path(self, rel: str) -> bool:
        """A literature document whose front matter records `verification: verified` (literature.py)."""
        path = self.docs_root / rel
        text = path.read_text(encoding="utf-8") if path.is_file() else ""
        head = re.match(r"^---\n(.*?)\n---", text, re.S)
        return bool(head and re.search(r"^verification:\s*[\"']?verified[\"']?\s*$", head.group(1), re.M))

    def _check_receipts(self, tx: _Tx, candidate_id: str | None, user_instruction_doc_id: str | None) -> None:
        """02 §3 D8 / R09: an initial node needs its candidate's novelty and critical-review receipts."""
        if not candidate_id or not CANDIDATE_ID_RE.fullmatch(candidate_id):
            raise ResearchDBError("discovery.require_precheck: an initial node names its discovery candidate "
                                  "(candidate_id CAND-…) whose novelty_precheck and critical_review it rests on")
        docs = [tx.get(i) for i in tx.ids("document", "WHERE n.doc_type = $t", t="review")]
        mine = [d for d in docs if d["status"] == "current" and d.get("review_about") == candidate_id]

        def latest(kind):
            found = [d for d in mine if d.get("review_kind") == kind]
            return max(found, key=lambda d: int(d["id"].split("-")[1])) if found else None
        novelty, critique = latest("novelty_precheck"), latest("critical_review")
        missing = [k for k, d in (("novelty_precheck", novelty), ("critical_review", critique)) if d is None]
        if missing:
            raise CodedError("REVIEW_UNAVAILABLE", f"{candidate_id} has no {' and no '.join(missing)} receipt "
                                                   f"(research_review with about={candidate_id}); the node is "
                                                   "created after both")
        negative = [f"{novelty['id']} {novelty['review_result']}"] if novelty["review_result"] not in POSITIVE_NOVELTY else []
        if critique["review_result"] != "proceed":
            negative.append(f"{critique['id']} stance {critique['review_result']}")
        if negative:
            instruction = user_instruction_doc_id and tx.get(user_instruction_doc_id)
            if not instruction or (instruction.get("doc_type"), instruction.get("status")) != (
                    "user_instruction", "current"):
                raise ResearchDBError(f"{candidate_id}'s receipts advise against it ({'; '.join(negative)}): a user "
                                      "hypothesis stays for the user to decide (report it as '建议放弃，待用户决定'); "
                                      "to build it anyway pass user_instruction_doc_id, their current instruction")

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
               based_on: list[str] | tuple[str, ...] = (), reconsider_when: str | None = None) -> list[str]:
        """Change hypothesis state or project status; one decision record per field. A GO or NOT GO rests on a report
        (doc_id) that lists the numbers it relies on, with their source files, in an ```evidence block.

        Hypothesis fields: status, experiment_status, novelty_recheck, theory_recheck, priority. status prunable also
        retires the node (a 'disposition' decision on the same evidence) and needs reconsider_when; verifying needs
        the node's disposition active (decide_disposition first when it was paused or retired).
        Project field: status.
        """
        self._require_role("rld")
        if not reason:
            raise ResearchDBError("a decision needs a reason")
        with self._writer() as tx:
            target = tx.require(target_id, ("hypothesis", "project"))
            evidence = [tx.require(i, ("experiment", "document", "evaluation")) for i in based_on]
            for item in evidence:
                if item["_table"] == "document" and item["status"] != "current":
                    raise ResearchDBError(f"based_on: {item['id']} is {item['status']}, expected current")
            self._check_values(target["_table"], changes)
            if target["_table"] == "hypothesis":
                self._check_hypothesis_decision(tx, target, changes, doc_id, evidence)
                if changes.get("status") == "prunable" and not (reconsider_when or "").strip():
                    raise ResearchDBError("status prunable retires the node: reconsider_when says what fact would "
                                          "reopen it")
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
                    if changes["status"] == "prunable" and _disposition(target) != "retired":
                        decision_id = tx.next_id("decision")
                        self._insert(tx, "decision", {
                            "id": decision_id, "target_id": target_id, "field": "disposition",
                            "from_value": _disposition(target), "to_value": "retired", "reason": reason,
                            "doc_id": doc_id, "decided_by": self.agent, "decided_at": now})
                        for item in evidence:
                            tx.link("rel_based_on", decision_id, item["id"])
                        decision_ids.append(decision_id)
                        update.update(disposition="retired", disposition_reason=reason,
                                      reconsider_when=reconsider_when)
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
                latest = self._latest_evaluated(tx, hyp["id"])
                rebinding = (field_name in RECHECK_FIELDS and value == "pass" and latest is not None
                             and latest["id"] in {e["id"] for e in evidence}
                             and not self._recheck_bound(tx, hyp["id"], field_name, latest))
                if not rebinding:  # a pass of a recheck may be renewed for new code, nothing else repeats
                    raise ResearchDBError(f"{hyp['id']}.{field_name} is already {value!r}")

        old_status = hyp["status"]
        new_status = changes.get("status", old_status)
        # A node that cannot run within caps/permissions is reported to the user; if the user declines,
        # a current user_instruction document describing this node lets RLD prune it without an experiment.
        user_declined = any(self._describes(tx, e, hyp["id"], "user_instruction") for e in evidence)
        if new_status != old_status:
            if new_status not in NODE_TRANSITIONS[old_status] and not (new_status == "prunable" and user_declined):
                raise _not_allowed(f"{hyp['id']}: status", old_status, new_status, NODE_TRANSITIONS[old_status])
            if doc_id is None:
                raise ResearchDBError("a node status change needs a decision document (doc_id)")
            if new_status == "verifying" and self._branch_of(tx, hyp["id"]) is None:
                raise ResearchDBError(f"{hyp['id']} needs a code branch before verification starts")
            if new_status == "verifying" and _disposition(hyp) != "active":
                raise ResearchDBError(f"{hyp['id']} is {_disposition(hyp)}: decide_disposition active (with its "
                                      "reason and evidence) before verifying it again")

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
            if changes[field_name] == "pass":
                # A recheck is bound to the code it examined: it stays valid while the evaluation basis has the
                # same code (more seeds), not after the method changes (plans/design 07 §3).
                latest = self._latest_evaluated(tx, hyp["id"])
                if latest is None or latest["id"] not in {e["id"] for e in evidence}:
                    raise ResearchDBError(f"{field_name}=pass needs based_on the experiment it rechecks: "
                                          f"{hyp['id']}'s latest evaluated experiment "
                                          f"{latest and latest['id']}")

        if new_status == "pending" and (final["experiment_status"] != "todo"
                                        or any(final[f] != "pending" for f in RECHECK_FIELDS)):
            raise ResearchDBError("a pending node has experiment_status todo and no rechecks")
        if new_status == "verifying" and final["experiment_status"] == "todo":
            raise ResearchDBError("a verifying node has its code change and experiments under way (experiment_status running)")
        if new_status == "expandable" and final["experiment_status"] not in ("beats_parent", "beats_sota"):
            raise ResearchDBError("an expandable node must beat its parent or SOTA")
        if new_status == "prunable" and new_status != old_status and not user_declined:
            # Retiring a node is the Leader's decision on evidence (06 §3): any evidence, not only a negative result;
            # a node never tested is retired only by the user.
            if old_status == "pending":
                raise ResearchDBError("a node without experiments is given up only by the user: based_on a current "
                                      "user_instruction document about it")
            if not any(e["_table"] in ("experiment", "evaluation", "document") for e in evidence):
                raise ResearchDBError("retiring a node (status prunable) needs based_on its evidence: an experiment, "
                                      "evaluation or document")
        latest = self._latest_evaluated(tx, hyp["id"])
        latest_ev = tx.get(latest["evaluation_id"]) if latest and latest.get("evaluation_id") else None
        if latest_ev and latest_ev.get("outcome") == "inconclusive" and (
                new_status != old_status or "experiment_status" in changes):
            # partial support: say what is missing and what comes next, before deciding on it
            self._check_headings(tx, doc_id, INCONCLUSIVE_SECTIONS,
                                 f"{hyp['id']}'s latest result {latest['id']} is inconclusive")

    def _check_conclusion(self, tx: _Tx, hyp: dict, conclusion: str, doc_id: str | None,
                          evidence: list[dict]) -> None:
        latest = self._latest_evaluated(tx, hyp["id"])
        if latest is None:
            raise ResearchDBError(f"{hyp['id']} has no experiment evaluated with the current harness")
        if latest["id"] not in {e["id"] for e in evidence}:
            raise ResearchDBError(f"experiment_status={conclusion} needs based_on the latest evaluated experiment {latest['id']}")
        if latest.get("verdict") is None:  # new flow: the conclusion agrees with the recomputed comparisons
            ev = tx.get(latest["evaluation_id"]) if latest.get("evaluation_id") else {}
            if conclusion == "inconclusive":
                if ev.get("outcome") != "inconclusive":
                    raise ResearchDBError(f"{latest['id']}'s outcome is {ev.get('outcome')}, not inconclusive")
                return
            edges = tx.edges("rel_compared_with", source=latest["id"])
            self._check_verdict(self._project(tx), latest, conclusion, edges)
            return
        if latest["verdict"] == conclusion or (latest["verdict"] == "close" and conclusion == "inconclusive"):
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

    def _check_headings(self, tx: _Tx, doc_id: str | None, required: tuple[str, ...], why: str) -> None:
        doc = tx.get(doc_id) if doc_id else None
        path = self.docs_root / doc["path"] if doc else None
        headings = re.findall(r"^#{2,3}[ \t]+(.+?)[ \t]*$", path.read_text(encoding="utf-8"), re.M) \
            if path and path.is_file() else []
        missing = [r for r in required if not any(h.startswith(r) for h in headings)]
        if missing:
            raise ResearchDBError(f"{why}: the decision document (doc_id) has the '## ' sections "
                                  f"{', '.join(required)}; missing {', '.join(missing)}")

    def _describes(self, tx: _Tx, item: dict, entity_id: str, doc_type: str) -> bool:
        return (item["_table"] == "document" and item["doc_type"] == doc_type
                and bool(tx.edges("rel_describes", source=item["id"], target=entity_id)))

    def _check_project_decision(self, tx: _Tx, project: dict, changes: dict, doc_id: str | None,
                                evidence: list[dict]) -> None:
        if set(changes) != {"status"}:
            raise ResearchDBError("project decisions change only status")
        old, new = project["status"], changes["status"]
        if new not in PROJECT_TRANSITIONS[old]:
            raise _not_allowed("project status", old, new, PROJECT_TRANSITIONS[old])
        if doc_id is None:
            raise ResearchDBError("a project status change needs a report or decision document (doc_id)")
        hypotheses = [tx.get(i) for i in tx.ids("hypothesis")]
        if new == "go":
            project_open = [o["id"] for o in (tx.get(i) for i in tx.ids("obligation"))
                            if o["status"] == "OPEN" and o["about"] == project["id"]]
            if project_open:
                raise CodedError("OBLIGATION_OPEN", f"open obligations about the project: {project_open}")
            # Checked again inside this write: no earlier snapshot or cached label stands for current evidence.
            results = [self._eligibility(tx, project, h) for h in hypotheses]
            if not any(r["eligible"] for r in results):
                detail = "; ".join(f"{r['hypothesis_id']}: {', '.join(r['reasons'])}" for r in results
                                   if r["basis_evaluation_id"]) or "no node has an evaluation"
                message = ("GO needs a node whose current evaluation passes the SOTA gate and guardrails, with both "
                           f"rechecks bound to that evaluation's code ({detail})")
                based = [r for r in results if r["basis_evaluation_id"]]
                if any(r["evidence_state"] == "stale" for r in results):
                    raise CodedError("EVIDENCE_STALE", message)
                confirming = {"CONFIRMATION_REQUIRED", "CONFIRMATION_FAILED", "CONFIRMATION_REUSED",
                              "CONFIRMATION_STALE"}
                if any(r["reasons"] and set(r["reasons"]) <= confirming for r in based):
                    raise CodedError("CONFIRMATION_REQUIRED", message)
                if any("OBLIGATION_OPEN" in r["reasons"] for r in based):
                    raise CodedError("OBLIGATION_OPEN", message)
                if based and all("LEGACY_RESULT_UNVERIFIED" in r["reasons"] for r in based):
                    raise CodedError("LEGACY_RESULT_UNVERIFIED", message)
                raise ResearchDBError(message)
        if new == "not_go":
            # Not 'every hypothesis disproved' (06 §3.3): no node is still active, and the report accounts for what
            # was not explored, failed in engineering, stayed uncertain, repeated, was refuted, and the value of
            # going on. A pending cleanup does not block the decision; it stays an attention item until done.
            open_nodes = [h["id"] for h in hypotheses if _disposition(h) == "active"]
            if open_nodes:
                raise ResearchDBError(f"NOT GO needs every node paused or retired (decide_disposition, with reason "
                                      f"and reconsider condition); still active: {open_nodes}")
            self._check_headings(tx, doc_id, NOT_GO_SECTIONS, "a NOT GO report")
        if new in ("go", "not_go"):
            report = tx.require(doc_id, ("document",))
            self._require_unchanged(report)
            claims = claims_check.document_claims((self.docs_root / report["path"]).read_text(encoding="utf-8"))
            if report["doc_type"] != "report" or not claims:
                raise CodedError("STAT_MISMATCH", f"a {new.upper().replace('_', ' ')} decision rests on a report that "
                                                  f"cites its numbers in an ```evidence block; {doc_id} is a "
                                                  f"{report['doc_type']} document" + ("" if claims else " without one"))
            bad = [r for r in claims_check.check_batch(claims, self.db_path.parent, self.project_dir,
                                                       forbidden=self.docs_root)["results"] if r["status"] != "verified"]
            if bad:
                raise CodedError("STAT_MISMATCH", f"{doc_id}: numbers not found in their sources: " + "; ".join(
                    f"{r.get('id', '?')} {r.get('value')!r}: {r['status']}" for r in bad[:10]))
            protocol = self._protocol(tx, project)
            if new == "go" and protocol and protocol.get("profile") == "screening":
                # screening ends at candidate_ready (06 §2.4): a GO on it says so in its report
                self._check_headings(tx, doc_id, ("未经独立确认",), "a GO under the screening profile")
        if new in ("stopped", "active") and not any(
            e["_table"] == "document" and e["doc_type"] == "user_instruction" for e in evidence
        ):
            raise ResearchDBError(f"project status {new} needs based_on a current user_instruction document")

    # --投入处置、停滞计数（plans/design 06 §3、§5） --------------------------------------------

    def decide_disposition(self, hypothesis_id: str, disposition: str, reason: str, evidence_ids: list[str],
                           reconsider_when: str | None = None, doc_id: str | None = None) -> str:
        """Whether to keep investing in a node, separate from its lifecycle and its evidence (06 §3): active, paused
        or retired, with the reason, the evidence it rests on (experiments, evaluations, documents) and, for paused
        or retired, the condition that would reopen it. retired is not a scientific verdict and deletes nothing; a
        node never tested is retired only on a current user_instruction about it. rld only. Returns the decision id."""
        self._require_role("rld")
        if disposition not in DISPOSITIONS:
            raise ResearchDBError(f"disposition is one of {DISPOSITIONS}")
        if not reason.strip():
            raise ResearchDBError("a disposition needs a reason")
        if disposition in ("paused", "retired") and not (reconsider_when or "").strip():
            raise ResearchDBError(f"{disposition} needs reconsider_when: what fact would reopen the node")
        with self._writer() as tx:
            hyp = tx.require(hypothesis_id, ("hypothesis",))
            evidence = [tx.require(i, ("experiment", "evaluation", "document")) for i in evidence_ids]
            if not evidence:
                raise ResearchDBError("a disposition needs evidence_ids: experiments, evaluations or documents")
            for item in evidence:
                if item["_table"] == "document" and item["status"] != "current":
                    raise ResearchDBError(f"{item['id']} is {item['status']}, expected current")
            old = _disposition(hyp)
            if old == disposition:
                raise ResearchDBError(f"{hypothesis_id} is already {disposition}")
            if disposition == "retired" and hyp["status"] == "pending" and not any(
                    self._describes(tx, e, hypothesis_id, "user_instruction") for e in evidence):
                raise ResearchDBError("a node without experiments is given up only by the user: evidence_ids include a "
                                      "current user_instruction document about it")
            if doc_id is not None:
                self._check_refs(tx, "decision", {"doc_id": doc_id}, current_docs=True)
            now = now_utc()
            decision_id = tx.next_id("decision")
            self._insert(tx, "decision", {
                "id": decision_id, "target_id": hypothesis_id, "field": "disposition", "from_value": old,
                "to_value": disposition, "reason": reason, "doc_id": doc_id, "decided_by": self.agent,
                "decided_at": now})
            for item in evidence:
                tx.link("rel_based_on", decision_id, item["id"])
            self._update(tx, hypothesis_id, {"disposition": disposition, "disposition_reason": reason,
                                             "reconsider_when": reconsider_when})
            return decision_id

    def note_findings(self, node_id: str, new_findings: int, direction: str | None = None,
                      doc_id: str | None = None) -> dict:
        """At each decision batch, the number of new findings in the subtree under node_id (06 §5). Consecutive
        batches with none: at project.stall_structural_at the subtree must change direction (a child with a
        direction already recorded in it is refused, STALL_STRUCTURAL); at stall_human_at the RLD reports to the
        user (report_to_user). direction records the node's research direction when it has none yet. rld only."""
        self._require_role("rld")
        if not isinstance(new_findings, int) or isinstance(new_findings, bool) or new_findings < 0:
            raise ResearchDBError("new_findings is a count >= 0")
        with self._writer() as tx:
            project = self._project(tx)
            hyp = tx.require(node_id, ("hypothesis",))
            streak = 0 if new_findings else (hyp.get("new_findings_streak") or 0) + 1
            state = ("human" if streak >= project.get("stall_human_at", 4) else
                     "structural" if streak >= project.get("stall_structural_at", 2) else "none")
            changes = {"new_findings_streak": streak, "stall_state": state}
            if direction and not hyp.get("direction"):
                changes["direction"] = direction
            decision_id = tx.next_id("decision")
            self._insert(tx, "decision", {
                "id": decision_id, "target_id": node_id, "field": "findings",
                "from_value": str(hyp.get("new_findings_streak") or 0), "to_value": str(streak),
                "reason": f"{new_findings} new finding(s) this batch; stall {state}", "doc_id": doc_id,
                "decided_by": self.agent, "decided_at": now_utc()})
            self._update(tx, node_id, changes)
            return {"node_id": node_id, "streak": streak, "stall_state": state, "report_to_user": state == "human"}

    def _check_stall(self, tx: _Tx, parent_id: str | None, direction: str | None) -> None:
        """A new child below a stalled subtree takes a direction not yet recorded in that subtree."""
        node = tx.get(parent_id) if parent_id and table_of(parent_id) == "hypothesis" else None
        while node is not None:
            if node.get("stall_state") in ("structural", "human"):
                used = self._subtree_directions(tx, node["id"])
                if not direction or direction in used:
                    raise CodedError("STALL_STRUCTURAL", f"{node['id']}'s subtree had {node.get('new_findings_streak')} "
                                                         "batches without a new finding: a new child changes mechanism, "
                                                         f"control or question; name a direction not in {sorted(used)}")
            parent = node.get("parent_id")
            node = tx.get(parent) if parent and table_of(parent) == "hypothesis" else None

    def _subtree_directions(self, tx: _Tx, root_id: str) -> set[str]:
        out, todo = set(), [root_id]
        while todo:
            current = tx.get(todo.pop())
            if current.get("direction"):
                out.add(current["direction"])
            todo += [r["id"] for r in tx.query("MATCH (h:Hypothesis)-[:CHILD_OF]->(p {id: $id}) RETURN h.id AS id",
                                               id=current["id"])]
        return out

    # -- 未决问题账本（06 §6，借 ARIS forensics_gate） ------------------------------------------------

    def add_obligation(self, about: str, source: str, pattern: str, claim: str, severity: str,
                       evidence_excerpt: str = "") -> dict:
        """Record a finding that must be closed before the node becomes a GO candidate: a review finding, a
        protocol mismatch, a STAT_MISMATCH, a CRITICAL code-review issue. The fingerprint (source family, pattern,
        evidence excerpt) identifies it across reports: the same fingerprint again does not add a second one, raises
        its severity if higher (never lowers it) and reopens it if it was resolved. source is
        '<family>:<instance>', e.g. 'code_review:RV-0003' or 'STAT_MISMATCH:interface'; the family groups the reports
        that reconcile_obligations compares. rld or worker."""
        self._require_role("rld", "worker")
        return self._obligation(about, source, pattern, claim, severity, evidence_excerpt)

    def _obligation(self, about: str, source: str, pattern: str, claim: str, severity: str,
                    excerpt: str) -> dict:
        if severity not in SEVERITIES:
            raise ResearchDBError(f"severity is one of {SEVERITIES}")
        fingerprint = _fingerprint(source, pattern, excerpt)
        with self._writer() as tx:
            tx.require(about, ("hypothesis", "experiment", "evaluation", "project"))
            same = tx.ids("obligation", "WHERE n.fingerprint = $f", f=fingerprint)
            now = now_utc()
            if same:
                ob = tx.get(same[0])
                history = list((ob.get("history") or {}).get("events", []))
                changes = {}
                if SEVERITIES.index(severity) < SEVERITIES.index(ob["severity"]):  # CRITICAL first: a raise
                    changes["severity"] = severity
                    history.append({"at": now, "event": "escalated", "from": ob["severity"], "to": severity})
                if ob["status"] == "RESOLVED":
                    changes["status"] = "OPEN"
                    history.append({"at": now, "event": "reopened", "resolution": ob.get("resolution")})
                if ob.get("disappearance"):
                    history.append({"at": now, "event": "reappeared", **ob["disappearance"]})
                    changes["disappearance"] = None
                if changes:
                    changes["history"] = {"events": history}
                    self._update(tx, ob["id"], changes)
                return {"obligation_id": ob["id"], "created": False, "status": changes.get("status", ob["status"]),
                        "severity": changes.get("severity", ob["severity"])}
            ob_id = tx.next_id("obligation")
            self._insert(tx, "obligation", {
                "id": ob_id, "about": about, "source": source, "pattern": pattern, "fingerprint": fingerprint,
                "severity": severity, "status": "OPEN", "claim": claim, "evidence_excerpt": excerpt or None,
                "history": None})
            return {"obligation_id": ob_id, "created": True, "status": "OPEN", "severity": severity}

    def resolve_obligation(self, obligation_id: str, fix_type: str, evidence: str) -> None:
        """Close an OPEN obligation with its evidence: fix_type (FIX_TYPES) and evidence, a file inside the
        project (hashed now) or a record id (an evaluation or a current document). rld only: the verifier is the
        Leader, never the author of the finding's subject alone."""
        self._require_role("rld")
        if fix_type not in FIX_TYPES:
            raise ResearchDBError(f"fix_type is one of {FIX_TYPES}")
        with self._writer() as tx:
            ob = tx.require(obligation_id, ("obligation",))
            if ob["status"] != "OPEN":
                raise ResearchDBError(f"{obligation_id} is {ob['status']}, not OPEN")
            receipt = {"fix_type": fix_type, "verified_by": f"{self.role}/{self.agent}", "resolved_at": now_utc()}
            if ENTITY_ID_RE.match(evidence):
                item = tx.require(evidence, ("evaluation", "document"))
                if item["_table"] == "document" and item["status"] != "current":
                    raise ResearchDBError(f"{evidence} is {item['status']}, expected current")
                receipt["evidence_id"] = evidence
            else:
                path = self._inside_project(evidence, self.db_path.parent, "evidence")
                receipt.update(evidence_path=self._research_rel(path), evidence_sha256=sha256_file(path))
            self._update(tx, obligation_id, {"status": "RESOLVED", "resolution": receipt})

    def waive_obligation(self, obligation_id: str, user_instruction_doc_id: str) -> None:
        """Close an OPEN obligation by the user's decision (a current user_instruction document); a waiver is
        not a resolution and keeps the finding as it was. rld only."""
        self._require_role("rld")
        with self._writer() as tx:
            ob = tx.require(obligation_id, ("obligation",))
            if ob["status"] != "OPEN":
                raise ResearchDBError(f"{obligation_id} is {ob['status']}, not OPEN")
            doc = tx.require(user_instruction_doc_id, ("document",))
            if (doc["doc_type"], doc["status"]) != ("user_instruction", "current"):
                raise ResearchDBError("a waiver is the user's: a current user_instruction document")
            self._update(tx, obligation_id, {"status": "WAIVED", "waiver": {
                "user_instruction_doc_id": user_instruction_doc_id, "recorded_by": f"{self.role}/{self.agent}",
                "waived_at": now_utc()}})

    def reconcile_obligations(self, about: str, source: str, present: list[str]) -> list[str]:
        """A later report from the same source family about the same subject: OPEN obligations of that family whose
        fingerprint it no longer contains are marked UNRESOLVED_DISAPPEARANCE and stay OPEN (disappearance is not
        resolution). present: the fingerprints (or obligation ids) the new report still contains. Returns the ids
        marked. rld or worker."""
        self._require_role("rld", "worker")
        family = source.split(":", 1)[0]
        with self._writer() as tx:
            marked = []
            for ob in (tx.get(i) for i in tx.ids("obligation")):
                if ob["about"] != about or ob["status"] != "OPEN" or ob["source"].split(":", 1)[0] != family:
                    continue
                if ob["fingerprint"] in present or ob["id"] in present or ob.get("disappearance"):
                    continue
                self._update(tx, ob["id"], {"disappearance": {"code": "UNRESOLVED_DISAPPEARANCE", "noted_at": now_utc(),
                                                              "absent_from": source}})
                marked.append(ob["id"])
            return marked

    def obligations(self, about: str | None = None, status: str | None = None) -> list[dict]:
        """The ledger, optionally of one subject and/or status."""
        with self.reader() as tx:
            out = [tx.get(i) for i in tx.ids("obligation")]
        out = [o for o in out if (about is None or o["about"] == about) and (status is None or o["status"] == status)]
        for o in out:
            o.pop("_table", None)
        return out

    def _open_obligations(self, tx: _Tx, hyp_id: str) -> list[str]:
        """OPEN obligations about the node, its experiments or their evaluations."""
        subjects = {hyp_id}
        for row in tx.query("MATCH (e:Experiment)-[:TESTS]->(h:Hypothesis {id: $id}) RETURN e.id AS id", id=hyp_id):
            subjects.add(row["id"])
            subjects.update(v["id"] for v in self._evaluations_of(tx, row["id"]))
        return [o["id"] for o in (tx.get(i) for i in tx.ids("obligation"))
                if o["status"] == "OPEN" and o["about"] in subjects]

    # -- budget: reservations, submission identity, settlement (plans/design 05 §4) -----------------------
    # The plugin keeps the books; the site skill submits, queries and cancels (01 §4). Steps 1, 2, 4 and 6 of
    # the submission protocol are here: reserve, claim, attach, settle; submit (3) and query (5) are the skill's.

    def reserve_submission(self, submission_key: str, run_attempt_refs: list[str], resource_request: dict) -> dict:
        """Step 1: in one write, check authorization, admission and the budget, and record the submission intent
        with its reservation. submission_key is the project-unique identity the site skill passes to the scheduler
        (so a timed-out submission can be found again); the same key again returns the same reservation.
        run_attempt_refs: the runs this one scheduler allocation runs ('E-0002/s42@1'; one job may run several
        seeds: they share one reservation). resource_request: {"nodes", "walltime_s"} (the walltime cap the
        scheduler enforces), optional "budget_pool" (search, confirmation, repair; by default from the experiment's
        stage) and "platform_profile". Reserved units = nodes x walltime_s node-seconds, rounded up. With a total
        budget (project.total_limit) a run is submitted only under a reservation."""
        self._require_role("rld", "worker")
        if not isinstance(submission_key, str) or not SUBMISSION_KEY_RE.fullmatch(submission_key):
            raise ResearchDBError("submission_key is 1..128 characters of letters, digits and _ . : @ / -")
        if not isinstance(resource_request, dict) or set(resource_request) - {"nodes", "walltime_s", "budget_pool",
                                                                              "platform_profile"}:
            raise ResearchDBError('resource_request is {"nodes", "walltime_s", "budget_pool"?, "platform_profile"?}')
        nodes, walltime = resource_request.get("nodes"), resource_request.get("walltime_s")
        if not all(isinstance(v, int) and not isinstance(v, bool) and v > 0 for v in (nodes, walltime)):
            raise ResearchDBError("resource_request needs positive integer nodes and walltime_s")
        refs = sorted(set(run_attempt_refs or []))
        if not refs:
            raise ResearchDBError("run_attempt_refs names the runs this allocation runs")
        with self._writer() as tx:
            project = self._project(tx)
            same = tx.ids("reservation", "WHERE n.submission_key = $k", k=submission_key)
            if same:
                r = tx.get(same[0])
                if r["run_attempt_refs"] != refs or r["reserved_units"] != nodes * walltime:
                    raise CodedError("SUBMISSION_AMBIGUOUS", f"{submission_key} already reserves {r['run_attempt_refs']} "
                                                             f"({r['reserved_units']} node-s); one key, one submission")
                return self._reservation_view(r, created=False)
            self._require_active(project)
            if project.get("admission_paused"):
                raise CodedError("BUDGET_EXCEEDED", f"admission is paused: {project['admission_paused']}; the user "
                                                    "decides (resume_admission with their instruction)")
            if nodes > project["max_nodes"] or walltime > project["max_walltime_s"]:
                raise ResearchDBError(f"the request exceeds the per-run cap ({project['max_nodes']} nodes, "
                                      f"{project['max_walltime_s']} s); report the need to the user")
            pools = set()
            for ref in refs:
                run_id, _, attempt = ref.rpartition("@")
                run = tx.require(run_id, ("run",))
                exp = tx.get(run["experiment_id"])
                self._require_owner(exp)
                if str(run["attempt"]) != attempt:
                    raise ResearchDBError(f"{run_id} is at attempt {run['attempt']}, not {attempt}")
                if run["exec_status"] != "planned":
                    raise CodedError("SUBMISSION_AMBIGUOUS", f"{run_id}@{attempt} is {run['exec_status']}: it was "
                                                             "submitted already; reconcile, do not reserve again")
                if run.get("submission_key"):
                    raise CodedError("SUBMISSION_AMBIGUOUS", f"{run_id}@{attempt} is under {run['submission_key']}")
                pools.add(exp.get("budget_pool") or ("confirmation" if exp.get("stage") == "confirm" else "search"))
                self._check_ready(tx, project, exp)
            requested = [tx.get(tx.get(ref.rpartition("@")[0])["experiment_id"]) for ref in refs]
            need_nodes = max(e["nodes"] for e in requested)
            need_units = sum(e["nodes"] * e["walltime_s"] for e in requested)
            if nodes < need_nodes or nodes * walltime < need_units:
                raise CodedError("BUDGET_EXCEEDED", f"the request ({nodes} nodes x {walltime} s) is smaller than the "
                                                    f"runs' registered requests ({need_nodes} nodes, {need_units} "
                                                    "node-s in all): reserve what the scheduler will be asked for")
            pool = resource_request.get("budget_pool") or (pools.pop() if len(pools) == 1 else None)
            if pool is None or pool not in BUDGET_POOLS:
                raise ResearchDBError(f"budget_pool is one of {BUDGET_POOLS}; the runs' experiments name {sorted(pools)}")
            units = nodes * walltime
            self._check_budget(tx, project, pool, units)
            res_id = tx.next_id("reservation")
            self._insert(tx, "reservation", {
                "id": res_id, "project_id": project["id"], "submission_key": submission_key,
                "run_attempt_refs": refs, "budget_pool": pool, "resource_class": "node", "reserved_units": units,
                "accounting_status": "reserved", "submission_phase": "intent", "claim_generation": 0,
                "platform_profile": resource_request.get("platform_profile")})
            for ref in refs:
                tx.set(ref.rpartition("@")[0], {"submission_key": submission_key})
            return self._reservation_view(tx.get(res_id), created=True)

    def claim_submission(self, submission_key: str, reclaim: bool = False) -> dict:
        """Step 2: one executor takes the intent before submitting; it gets a claim generation that attach_job
        must present. A claimed intent is not claimed again: if its executor is gone, first check with the
        scheduler that nothing was submitted under the key, then reclaim=true (the old generation can no longer
        attach)."""
        with self._writer() as tx:
            r = self._reservation(tx, submission_key)
            self._require_run_owner(tx, r)
            if r["accounting_status"] in ("settled", "released"):
                raise ResearchDBError(f"{submission_key} is {r['accounting_status']}")
            if r["submission_phase"] == "attached":
                raise CodedError("SUBMISSION_AMBIGUOUS", f"{submission_key} is already job {r['job_id']}")
            if r["submission_phase"] == "claimed" and not reclaim:
                raise CodedError("SUBMISSION_AMBIGUOUS", f"{submission_key} is claimed (generation "
                                                         f"{r['claim_generation']}); query the scheduler by the key "
                                                         "before any new submission, then reclaim=true if nothing "
                                                         "was submitted")
            generation = r["claim_generation"] + 1
            self._update(tx, r["id"], {"submission_phase": "claimed", "claim_generation": generation})
            return {"submission_key": submission_key, "claim_generation": generation}

    def attach_job(self, submission_key: str, job_id: str, claim_generation: int) -> dict:
        """Step 4: the scheduler's job id for the claimed submission (also when it was found later by the key after
        a timeout). Writes the job id on the runs that have none. The same job again changes nothing; another job
        under the same key is refused."""
        if not isinstance(job_id, str) or not job_id.strip():
            raise ResearchDBError("job_id is the scheduler's id")
        with self._writer() as tx:
            r = self._reservation(tx, submission_key)
            self._require_run_owner(tx, r)
            if r["submission_phase"] == "attached":
                if r["job_id"] != job_id:
                    raise CodedError("SUBMISSION_AMBIGUOUS", f"{submission_key} is job {r['job_id']}, not {job_id}")
                return self._reservation_view(r, created=False)
            if r["submission_phase"] != "claimed" or claim_generation != r["claim_generation"]:
                raise CodedError("SUBMISSION_AMBIGUOUS", f"{submission_key} is {r['submission_phase']} with claim "
                                                         f"generation {r['claim_generation']}, not {claim_generation}")
            self._update(tx, r["id"], {"submission_phase": "attached", "job_id": job_id})
            for ref in r["run_attempt_refs"]:
                run_id = ref.rpartition("@")[0]
                if not tx.get(run_id).get("job_id"):
                    tx.set(run_id, {"job_id": job_id})
            return self._reservation_view(tx.get(r["id"]), created=False)

    def reconcile_submission(self, submission_key: str) -> dict:
        """Where a submission stands and what is safe next (read-only): never 'submit again' while the scheduler
        may have it."""
        with self.reader() as tx:
            r = self._reservation(tx, submission_key)
            runs = {ref: tx.get(ref.rpartition("@")[0])["exec_status"] for ref in r["run_attempt_refs"]}
        if r["accounting_status"] in ("settled", "released"):
            step = f"nothing: {r['accounting_status']}"
        elif r["submission_phase"] == "intent":
            step = "claim_submission, then submit with the key"
        elif r["submission_phase"] == "claimed":
            step = ("SUBMISSION_AMBIGUOUS: the scheduler may have it; query it by the submission key and attach_job "
                    "when found; release only once sure nothing was submitted (user instruction)")
        elif all(s in FINAL_EXEC for s in runs.values()):
            step = "settle_reservation with the scheduler's accounting for the job"
        else:
            step = f"query job {r['job_id']}; report the runs' exec_status"
        return {**self._reservation_view(r, created=False), "runs": runs, "next": step}

    def settle_reservation(self, reservation_id: str, accounting_ref: str) -> dict:
        """Step 6: the actual usage, from the scheduler's accounting file (JSON {"job_id", "node_seconds"} or
        {"job_id", "nodes_used", "walltime_used_s"}, inside the project), once every run of the allocation is final
        (failed runs cost too). Recorded as it is, also above the reservation or the budget: then the reservation is
        marked overrun and admission pauses until the user decides. Settling again with the same file changes
        nothing; another file is refused."""
        path = self._inside_project(accounting_ref, self.db_path.parent, "accounting_ref")
        record = _read_json(path, "accounting file")
        digest = sha256_file(path)
        with self._writer() as tx:
            r = tx.require(reservation_id, ("reservation",))
            self._require_run_owner(tx, r)
            if r["accounting_status"] == "settled":
                if r.get("accounting_sha256") != digest:
                    raise CodedError("EVIDENCE_CHANGED", f"{reservation_id} was settled from {r['accounting_ref']}")
                return self._reservation_view(r, created=False)
            if r["accounting_status"] == "released":
                raise ResearchDBError(f"{reservation_id} was released")
            billed = record.get("job_id") if isinstance(record, dict) else None
            if billed is None or billed != r.get("job_id"):
                raise CodedError("SUBMISSION_AMBIGUOUS", f"the accounting file is for job {billed}, the reservation's "
                                                         f"job is {r.get('job_id')}")
            units = record.get("node_seconds")
            if units is None and all(isinstance(record.get(k), int) for k in ("nodes_used", "walltime_used_s")):
                units = record["nodes_used"] * record["walltime_used_s"]
            if not isinstance(units, int) or isinstance(units, bool) or units < 0:
                raise ResearchDBError("the accounting file gives node_seconds, or nodes_used and walltime_used_s")
            open_runs = [ref for ref in r["run_attempt_refs"]
                         if tx.get(ref.rpartition("@")[0])["exec_status"] not in FINAL_EXEC
                         and tx.get(ref.rpartition("@")[0])["attempt"] == int(ref.rpartition("@")[2])]
            if open_runs:
                raise ResearchDBError(f"runs not final yet: {open_runs}; settle once the job has ended")
            project = self._project(tx)
            overrun = units > r["reserved_units"]
            changes = {"accounting_status": "settled", "actual_units": units, "settled_at": now_utc(),
                       "accounting_ref": self._research_rel(path), "accounting_sha256": digest, "overrun": overrun}
            self._update(tx, r["id"], changes)
            total = project.get("total_limit")
            used = self._committed(tx)["total"]
            if overrun or (total is not None and used > total):
                self._update(tx, project["id"], {"admission_paused": (
                    f"{r['id']} used {units} node-s against {r['reserved_units']} reserved"
                    + (f"; committed {used} of {total}" if total is not None else ""))})
            return self._reservation_view(tx.get(r["id"]), created=False)

    def release_reservation(self, submission_key: str, reason: str, user_instruction_doc_id: str | None = None) -> None:
        """Give a reservation back. An intent never claimed is released by its owner; once claimed or attached the
        scheduler may have run it, so only on the user's explicit decision (a current user_instruction document).
        Passing time is no evidence that a job does not exist."""
        if not reason.strip():
            raise ResearchDBError("releasing needs a reason")
        with self._writer() as tx:
            r = self._reservation(tx, submission_key)
            self._require_run_owner(tx, r)
            if r["accounting_status"] in ("settled", "released"):
                raise ResearchDBError(f"{submission_key} is {r['accounting_status']}")
            if r["submission_phase"] != "intent":
                doc = tx.get(user_instruction_doc_id) if user_instruction_doc_id else None
                if not doc or (doc.get("doc_type"), doc.get("status")) != ("user_instruction", "current"):
                    raise CodedError("SUBMISSION_AMBIGUOUS", f"{submission_key} is {r['submission_phase']}: the "
                                                             "scheduler may run it; releasing needs the user's "
                                                             "instruction")
            self._update(tx, r["id"], {"accounting_status": "released", "note": reason})
            for ref in r["run_attempt_refs"]:
                run = tx.get(ref.rpartition("@")[0])
                if run.get("submission_key") == submission_key and run["exec_status"] == "planned":
                    tx.set(run["id"], {"submission_key": None})

    def resume_admission(self, user_instruction_doc_id: str) -> None:
        """After an overrun the user decides how to go on (a current user_instruction document); rld records it."""
        self._require_role("rld")
        with self._writer() as tx:
            doc = tx.require(user_instruction_doc_id, ("document",))
            if (doc["doc_type"], doc["status"]) != ("user_instruction", "current"):
                raise ResearchDBError("resuming admission is the user's decision: a current user_instruction document")
            self._update(tx, self._project(tx)["id"], {"admission_paused": None})

    def budget_status(self) -> dict:
        """Authorized, committed (settled actual + outstanding reservations + recorded usage outside reservations)
        and available node-seconds, in total and per pool; open reservations; whether admission is paused."""
        with self.reader() as tx:
            project = self._project(tx)
            committed = self._committed(tx)
            open_res = [self._reservation_view(r, created=False) for r in (tx.get(i) for i in tx.ids("reservation"))
                        if r["accounting_status"] in ("reserved", "held_unknown")]
        limits = {"total": project.get("total_limit")} | {p: project.get(f"{p}_limit") for p in BUDGET_POOLS}
        return {"unit": "node_seconds", "limits": limits, "committed": committed,
                "available": {k: (v - committed[k] if v is not None else None) for k, v in limits.items()},
                "open_reservations": open_res, "admission_paused": project.get("admission_paused")}

    def _check_budget(self, tx: _Tx, project: dict, pool: str, units: int) -> None:
        committed = self._committed(tx)
        for scope, limit in (("total", project.get("total_limit")), (pool, project.get(f"{pool}_limit"))):
            if limit is not None and committed[scope] + units > limit:
                raise CodedError("BUDGET_EXCEEDED", f"{units} node-s do not fit the {scope} budget: {committed[scope]} "
                                                    f"of {limit} committed (settled, reserved or recorded); report to "
                                                    "the user, who decides")

    def _committed(self, tx: _Tx) -> dict:
        """node-seconds committed per pool and in total: settled actual usage, outstanding reservations, and
        recorded run usage not covered by any reservation (older runs, unreserved projects)."""
        out = {"total": 0} | {p: 0 for p in BUDGET_POOLS}
        covered = set()
        for r in (tx.get(i) for i in tx.ids("reservation")):
            if r["accounting_status"] != "released":  # a released reservation covers nothing actually run
                covered.update(r["run_attempt_refs"])
            amount = (r.get("actual_units") or 0) if r["accounting_status"] == "settled" else (
                r["reserved_units"] if r["accounting_status"] in ("reserved", "held_unknown") else 0)
            out[r["budget_pool"]] += amount
            out["total"] += amount
        for run in (tx.get(i) for i in tx.ids("run")):
            exp = tx.get(run["experiment_id"])
            pool = exp.get("budget_pool") or ("confirmation" if exp.get("stage") == "confirm" else "search")
            for n, a in [(run["attempt"], run), *((int(k), v) for k, v in (run.get("attempts") or {}).items())]:
                if f"{run['id']}@{n}" in covered or not (a.get("nodes_used") and a.get("walltime_used_s")):
                    continue
                out[pool] += a["nodes_used"] * a["walltime_used_s"]
                out["total"] += a["nodes_used"] * a["walltime_used_s"]
        return out

    def _reservation(self, tx: _Tx, submission_key: str) -> dict:
        ids = tx.ids("reservation", "WHERE n.submission_key = $k", k=submission_key)
        if not ids:
            raise ResearchDBError(f"no reservation {submission_key!r}")
        return tx.get(ids[0])

    def _require_run_owner(self, tx: _Tx, reservation: dict) -> None:
        for ref in reservation["run_attempt_refs"]:
            self._require_owner(tx.get(tx.get(ref.rpartition("@")[0])["experiment_id"]))

    @staticmethod
    def _reservation_view(r: dict, created: bool) -> dict:
        return {"reservation_id": r["id"], "created": created, **{k: r.get(k) for k in (
            "submission_key", "run_attempt_refs", "budget_pool", "reserved_units", "actual_units", "accounting_status",
            "submission_phase", "claim_generation", "job_id", "overrun")}}

    # -- experiments and runs -------------------------------------------------------

    def create_experiment(self, kind: str, method_name: str, design_doc_id: str, code_ref: str, nodes: int,
                          walltime_s: int, hypothesis_id: str | None = None, n_seeds: int | None = None,
                          **optional) -> str:
        """Seeds are the first n of project.seeds: baselines default to gate_seeds; node experiments default to
        (and may not exceed) the screening count from the SOTA cost.

        Once its statistics are recorded an experiment's outputs are cleaned (run_cleanup), all but its evidence.
        keep (output classes, e.g. ["final_weights"]) with keep_reason (which later experiment uses them) holds
        those classes back until its node is pruned (for a baseline: every node is) and every experiment that
        depends on it (link rel_depends_on) is evaluated. Declare it here: later the outputs are gone.

        stage (06 §2.2): screen (default) or replicate use project.seeds; confirm runs on the protocol's
        confirmation_seeds, never used in the search: a confirmation baseline (kind baseline), or the node's frozen
        candidate (the code of its latest experiment that passed the SOTA gate), compared with that baseline; at
        most max_confirmation_candidates nodes are confirmed. selection_rationale (why now, how the result changes
        the next step) is required once the node's last two results were inconclusive. estimated_node_h (required)
        is the cost estimate; milestone M0..M4 (03 §6); budget_pool (search, confirmation, repair; by default from
        the stage) is the budget part its reservations count against."""
        self._require_role("rld", "worker")
        self._only_fields(optional, ("config_path", "owner", "keep", "keep_reason", "stage", "selection_rationale",
                                     "estimated_node_h", "milestone", "budget_pool", "ablation_of",
                                     "source_review_id"))
        estimate = optional.get("estimated_node_h")
        if not (isinstance(estimate, (int, float)) and not isinstance(estimate, bool) and estimate > 0):
            raise ResearchDBError("estimated_node_h (the experiment's cost estimate over all its seeds, node-h > 0) "
                                  "is required: the overrun attention compares the actual usage with it")
        if optional.get("budget_pool") == "repair" and self.role != "rld":
            raise PermissionDenied("the repair budget is assigned by rld")
        stage = optional.pop("stage", None) or "screen"
        if stage not in ("screen", "replicate", "confirm"):
            raise ResearchDBError("stage is screen, replicate or confirm")
        if optional.get("owner") and self.role != "rld":
            raise PermissionDenied("only rld assigns an experiment to another owner")
        if optional.get("keep") and not (optional.get("keep_reason") or "").strip():
            raise ResearchDBError("keep needs keep_reason: which later experiment uses these outputs")
        with self._writer() as tx:
            project = self._project(tx)
            self._require_active(project)
            if not project.get("harness_ref"):
                raise ResearchDBError("freeze the harness (update_project harness_ref/harness_paths) before experiments")
            if kind != "sanity" and (kind == "baseline") != (hypothesis_id is None):
                raise ResearchDBError("baseline experiments have no hypothesis; method and ablation need one")
            if kind == "sanity" and stage != "screen":
                raise ResearchDBError("a sanity run is a minimal check, not a screen, replication or confirmation")
            if nodes > project["max_nodes"] or walltime_s > project["max_walltime_s"]:
                raise ResearchDBError(
                    f"a run exceeds the per-run cap ({project['max_nodes']} nodes, {project['max_walltime_s']} s); "
                    "report the budget need to the user"
                )
            self._check_usage_alert(tx, project)
            node = tx.require(hypothesis_id, ("hypothesis",)) if hypothesis_id is not None else project
            if hypothesis_id is not None and _disposition(node) != "active":
                raise ResearchDBError(f"{hypothesis_id} is {_disposition(node)} ({node.get('disposition_reason')}): no "
                                      "new experiments; decide_disposition active first if that changed")
            protocol = self._protocol(tx, project) or {}
            if kind == "sanity":  # 03 §8: one minimal attempt; it counts toward no seed and is never evaluated
                if n_seeds not in (None, 1):
                    raise ResearchDBError("a sanity experiment runs one seed")
                seeds = project["seeds"][:1]
            elif stage == "confirm":
                pool = protocol.get("confirmation_seeds") or []
                need = protocol.get("min_confirmation_pairs") or 3
                if len(pool) < need:
                    raise CodedError("PROTOCOL_CHANGE_REQUIRED", f"the protocol declares {len(pool)} confirmation_seeds; "
                                                                 f"a confirmation needs {need}")
                if set(pool) & set(project["seeds"]):
                    raise CodedError("PROTOCOL_CHANGE_REQUIRED", "confirmation_seeds overlap the search seeds "
                                                                 f"{project['seeds']}: they are not unseen")
                n = len(pool) if n_seeds is None else n_seeds
                if not need <= n <= len(pool):
                    raise ResearchDBError(f"a confirmation runs {need}..{len(pool)} confirmation seeds, got {n}")
                seeds = pool[:n]
            else:
                limit = project["gate_seeds"] if kind == "baseline" else self._screen_seeds(tx, project)
                n = limit if n_seeds is None else n_seeds
                if not 1 <= n <= limit:
                    raise ResearchDBError(f"this experiment may start with 1..{limit} seeds, got {n}")
                seeds = project["seeds"][:n]
            if hypothesis_id is not None and kind != "sanity" and stage != "confirm" and \
                    not (optional.get("selection_rationale") or "").strip():
                recent = [tx.get(v["id"]).get("outcome") for v in self._node_evaluations(tx, hypothesis_id)[-2:]]
                if recent == ["inconclusive", "inconclusive"]:
                    raise ResearchDBError(f"{hypothesis_id}'s last two results were inconclusive: another experiment "
                                          "needs selection_rationale (why now, how its result changes the next step; "
                                          "or narrow the claim, change direction, pause)")
            if self.role == "worker" and node.get("worker_id") and node["worker_id"] != self.agent:
                raise PermissionDenied(f"{node['id']} is worker/{node['worker_id']}'s node")
            branch = self._branch_of(tx, hypothesis_id) if hypothesis_id is not None else None
            if hypothesis_id is not None and branch is None:
                raise ResearchDBError(f"{hypothesis_id} needs a code branch before experiments")
            if branch is not None and branch["status"] in ("merged", "deleted"):
                raise ResearchDBError(f"{hypothesis_id}'s branch {branch['id']} is {branch['status']}: experiments run "
                                      "on a branch that still exists (a deleted or merged one is closed)")
            resolved = _git_commit(project["repo_path"], code_ref)
            if resolved is None:
                raise ResearchDBError(f"code_ref {code_ref} is not a commit in {project['repo_path']}")
            self._check_not_blocked(tx, node["id"])
            if project.get("design_required") and kind in ("method", "ablation"):
                self._check_design_doc(tx, design_doc_id)
            if kind == "ablation" and project.get("design_required"):
                self._check_ablation(tx, hypothesis_id, resolved, kind, stage, method_name, nodes, walltime_s,
                                     optional, project)
            elif optional.get("ablation_of") or optional.get("source_review_id"):
                raise ResearchDBError("ablation_of and source_review_id belong to an ablation")
            # The same configuration is never run twice (05 §5): same code, configuration and seeds -> that experiment.
            config_hash = self._config_hash(project, resolved, kind, stage, method_name, nodes, walltime_s,
                                            optional.get("config_path"))
            for other in (tx.get(i) for i in tx.ids("experiment", "WHERE n.config_hash = $h", h=config_hash)):
                if (other["code_ref"], other.get("hypothesis_id"), other["seeds"]) == (resolved, hypothesis_id, seeds):
                    return other["id"]
            # The references a node experiment is compared with are fixed now (plans/design 05 §3.2): later
            # experiments of the parent or a new SOTA do not move them.
            refs = {}
            if kind == "sanity":
                pass
            elif hypothesis_id is not None and stage == "confirm":
                refs["baseline_experiment_id"] = self._confirm_setup(tx, project, protocol, node, resolved)
            elif hypothesis_id is not None:
                refs["baseline_experiment_id"] = project.get("sota_experiment_id")
                parent = node.get("parent_id")
                if parent and table_of(parent) == "hypothesis":
                    latest = self._latest_evaluated(tx, parent)
                    if latest is None:
                        raise ResearchDBError(f"parent {parent} has no experiment evaluated with the current harness: "
                                              "the comparison reference is fixed when the experiment is created")
                    refs["parent_experiment_id"] = latest["id"]
            return self._insert(tx, "experiment", {
                "id": tx.next_id("experiment"), "project_id": project["id"], "hypothesis_id": hypothesis_id,
                "kind": kind, "method_name": method_name, "design_doc_id": design_doc_id, "code_ref": resolved,
                "seeds": seeds, "nodes": nodes, "walltime_s": walltime_s, "stage": stage, "config_hash": config_hash,
                "owner": optional.pop("owner", None) or self.agent, **refs, **optional,
            })

    def _config_hash(self, project: dict, code_ref: str, kind: str, stage: str, method_name: str, nodes: int,
                     walltime_s: int, config_path: str | None) -> str:
        """What an experiment runs besides its code: kind, stage, method, request and the configuration snapshot
        (config_path's content at code_ref in the repository, else the file under the project directory)."""
        content = None
        if config_path:
            shown = subprocess.run(["git", "-C", project["repo_path"], "show", f"{code_ref}:{config_path}"],
                                   capture_output=True, check=False)
            if shown.returncode == 0:
                content = hashlib.sha256(shown.stdout).hexdigest()
            elif not Path(config_path).is_absolute() and ".." not in Path(config_path).parts and \
                    (self.project_dir / config_path).is_file():
                content = sha256_file(self.project_dir / config_path)
        key = json.dumps([kind, stage, method_name, nodes, walltime_s, config_path, content], sort_keys=True)
        return hashlib.sha256(key.encode("utf-8")).hexdigest()[:32]

    def _check_ablation(self, tx: _Tx, hypothesis_id: str, code_ref: str, kind: str, stage: str, method_name: str,
                        nodes: int, walltime_s: int, optional: dict, project: dict) -> None:
        """03 §7: an ablation names the experiment it ablates and the ablation_plan review that proposed it; one
        with the same code and configuration as that experiment is a no-op and is refused."""
        target = tx.require(optional.get("ablation_of"), ("experiment",)) if optional.get("ablation_of") else None
        if target is None or target.get("hypothesis_id") != hypothesis_id:
            raise ResearchDBError(f"an ablation names ablation_of, an experiment of {hypothesis_id}")
        review = tx.require(optional.get("source_review_id"), ("document",)) if optional.get("source_review_id") else None
        if review is None or (review["doc_type"], review.get("review_kind"), review["status"]) != (
                "review", "ablation_plan", "current") or not tx.edges("rel_describes", source=review["id"],
                                                                      target=hypothesis_id):
            raise ResearchDBError(f"an ablation names source_review_id, the current ablation_plan review of "
                                  f"{hypothesis_id} that proposed it")
        mine = self._config_hash(project, code_ref, target["kind"], target.get("stage") or "screen",
                                 target["method_name"], nodes, walltime_s, optional.get("config_path"))
        if code_ref == target["code_ref"] and mine == target.get("config_hash"):
            raise ResearchDBError(f"this ablation runs {target['id']} unchanged (same code and configuration): a "
                                  "no-op ablation equivalent to what it ablates is not run")
        del kind, stage, method_name

    def _check_not_blocked(self, tx: _Tx, node_id: str) -> None:
        blocked = [t for t in (tx.get(i) for i in tx.ids("task")) if t.get("target_id") == node_id
                   and t.get("blocked_reason") and t["status"] not in ("accepted", "cancelled")]
        if blocked and self.role != "rld":
            raise CodedError("FAILURE_BUDGET", f"{blocked[0]['id']} is blocked ({blocked[0]['blocked_reason']}): the "
                                               "Leader decides (unblock_task) before anything else runs here")

    def _check_ready(self, tx: _Tx, project: dict, exp: dict) -> None:
        """03 §8, before a method or ablation experiment's run is submitted: a valid sanity run of the same code,
        and a cross-model code review of that code with no CRITICAL/MAJOR issue (or the Leader's recorded waiver)."""
        if exp["kind"] not in ("method", "ablation"):
            return
        if project.get("sanity_required"):
            sane = [e for e in (tx.get(i) for i in tx.ids("experiment")) if e["kind"] == "sanity"
                    and e.get("hypothesis_id") == exp.get("hypothesis_id") and e["code_ref"] == exp["code_ref"]]
            if not any((tx.get(f"{e['id']}/s{s}") or {}).get("valid") is True for e in sane for s in e["seeds"]):
                raise CodedError("SANITY_REQUIRED", f"{exp['id']}: run a sanity experiment (kind sanity) of code "
                                                    f"{exp['code_ref'][:10]} first and accept its run (valid=true: "
                                                    "counts, loss, metric file, reload) — the exit code is not enough")
        if project.get("code_review_required") and not exp.get("code_review_waiver_doc_id"):
            reviews = [d for d in (tx.get(i) for i in tx.ids("document", "WHERE n.doc_type = $t", t="review"))
                       if d["status"] == "current" and d.get("review_kind") == "code_review"
                       and d.get("basis_code_ref") == exp["code_ref"]]
            if not any(d["review_result"] == "clear" for d in reviews):
                why = "has blocking issues; fix them and review again (at most 2 rounds)" if reviews else "is missing"
                raise CodedError("CODE_REVIEW_REQUIRED", f"{exp['id']}: the code review of {exp['code_ref'][:10]} "
                                                         f"{why} (research_review kind=code_review with code_ref); "
                                                         "when the reviewer is unavailable the Leader may release it "
                                                         "with a decision document (waive_code_review)")

    def waive_code_review(self, experiment_id: str, doc_id: str) -> None:
        """rld: release an experiment without a clear code review (the reviewer was unavailable, 03 §8, X10); doc_id
        is the current decision document that records why."""
        self._require_role("rld")
        with self._writer() as tx:
            tx.require(experiment_id, ("experiment",))
            doc = tx.require(doc_id, ("document",))
            if (doc["doc_type"], doc["status"]) != ("decision", "current"):
                raise ResearchDBError("waiving the code review needs a current decision document")
            self._update(tx, experiment_id, {"code_review_waiver_doc_id": doc_id})
            tx.link("rel_describes", doc_id, experiment_id)

    def report_failure(self, task_id: str, root_cause: str, remedy: str) -> dict:
        """03 §8 failure budget, per task and root cause: at most 2 patches, then at most 2 rewrites from the
        hypothesis document; a 3rd patch is refused (rewrite or report); a failure after 2 rewrites blocks the task
        and reports it (an attention item) — the plan or the environment is to blame, no more retries."""
        if remedy not in ("patch", "rewrite"):
            raise ResearchDBError("remedy is patch or rewrite")
        cause = " ".join(root_cause.lower().split())
        if not cause:
            raise ResearchDBError("root_cause names the failure")
        with self._writer() as tx:
            task = tx.require(task_id, ("task",))
            if self.role != "rld" and (task.get("assignee_role"), task.get("assignee_id")) != (self.role, self.agent):
                raise PermissionDenied(f"{task_id} is not {self.role}/{self.agent}'s task")
            if task.get("blocked_reason"):
                raise CodedError("FAILURE_BUDGET", f"{task_id} is blocked: {task['blocked_reason']}")
            log = list((task.get("failure_log") or {}).get("entries", []))
            same = [f for f in log if f["root_cause"] == cause]
            patches = sum(f["remedy"] == "patch" for f in same)
            rewrites = sum(f["remedy"] == "rewrite" for f in same)
            if remedy == "patch" and (patches >= FAILURE_PATCHES or rewrites):
                raise CodedError("FAILURE_BUDGET", f"{cause!r} was patched {patches} time(s): rewrite from the "
                                                   "hypothesis document, or report to the Leader")
            entry = {"root_cause": cause, "remedy": remedy, "by": f"{self.role}/{self.agent}", "at": now_utc()}
            if remedy == "rewrite" and rewrites >= FAILURE_REWRITES:
                reason = f"{cause!r} failed the same way after {rewrites} rewrites: the plan or the environment"
                self._update(tx, task_id, {"failure_log": {"entries": log + [{**entry, "remedy": "blocked"}]},
                                           "blocked_reason": reason})
                return {"blocked": True, "reason": reason, "patches": patches, "rewrites": rewrites}
            self._update(tx, task_id, {"failure_log": {"entries": log + [entry]}})
            return {"blocked": False, "patches": patches + (remedy == "patch"),
                    "rewrites": rewrites + (remedy == "rewrite")}

    def unblock_task(self, task_id: str, doc_id: str) -> None:
        """rld: lift a failure-budget block with a decision document (new plan, changed environment, or stop)."""
        self._require_role("rld")
        with self._writer() as tx:
            task = tx.require(task_id, ("task",))
            doc = tx.require(doc_id, ("document",))
            if (doc["doc_type"], doc["status"]) != ("decision", "current"):
                raise ResearchDBError("unblocking needs a current decision document")
            if not task.get("blocked_reason"):
                raise ResearchDBError(f"{task_id} is not blocked")
            self._update(tx, task_id, {"blocked_reason": None, "failure_log": {"entries": []}})
            tx.link("rel_describes", doc_id, task_id)

    def _confirm_setup(self, tx: _Tx, project: dict, protocol: dict, hyp: dict, code_ref: str) -> str:
        """A node's confirmation: its frozen candidate and the confirmation baseline it is compared with."""
        latest = self._latest_evaluated(tx, hyp["id"])
        state = self._eligibility(tx, project, hyp)
        if latest is None or state["stage"] not in ("candidate_ready", "confirmed"):
            blocking = [r for r in state["reasons"] if not r.startswith(("RECHECK", "CONFIRMATION"))]
            raise CodedError("OBLIGATION_OPEN" if "OBLIGATION_OPEN" in blocking else "CONFIRMATION_REQUIRED",
                             f"{hyp['id']} is not candidate_ready ({', '.join(blocking) or 'no evaluation'}): "
                             "confirmation comes after a current search result that passes the gate and guardrails "
                             "with no open obligation")
        if code_ref != latest["code_ref"]:
            raise CodedError("CONFIRMATION_REQUIRED", f"a confirmation runs the frozen candidate {latest['id']} "
                                                      f"(code {latest['code_ref'][:10]}), not other code")
        limit = protocol.get("max_confirmation_candidates")
        confirmed = {e.get("hypothesis_id") for e in (tx.get(i) for i in tx.ids("experiment"))
                     if e.get("stage") == "confirm" and e.get("hypothesis_id")}
        if limit is not None and hyp["id"] not in confirmed and len(confirmed) >= limit:
            raise CodedError("BUDGET_EXCEEDED", f"max_confirmation_candidates is {limit}: {sorted(confirmed)} are "
                                                "being confirmed")
        baselines = [e for e in (tx.get(i) for i in tx.ids("experiment")) if e["kind"] == "baseline"
                     and e.get("stage") == "confirm" and e.get("evaluated_at") and e.get("harness_ref") == project["harness_ref"]]
        if not baselines:
            raise CodedError("CONFIRMATION_REQUIRED", "no confirmation baseline: run the SOTA method on the "
                                                      "confirmation seeds first (create_experiment kind=baseline, "
                                                      "stage=confirm) and evaluate it")
        return max(baselines, key=lambda e: int(e["id"].split("-")[1]))["id"]

    def _node_evaluations(self, tx: _Tx, hyp_id: str, stage: str | None = None) -> list[dict]:
        """The current evaluations of a node's method experiments (search stages unless stage is given), in order."""
        rows = tx.query("MATCH (e:Experiment)-[:TESTS]->(h:Hypothesis {id: $id}) RETURN e.id AS id", id=hyp_id)
        exps = sorted((tx.get(r["id"]) for r in rows), key=lambda e: int(e["id"].split("-")[1]))
        out = []
        for e in exps:
            if e["kind"] != "method" or not e.get("evaluation_id"):
                continue
            if (stage is None and (e.get("stage") or "screen") == "confirm") or (stage and e.get("stage") != stage):
                continue
            out.append(tx.get(e["evaluation_id"]))
        return out

    def _check_usage_alert(self, tx: _Tx, project: dict) -> None:
        """At alert_node_h of recorded usage, new experiments and seed extensions wait for the user's decision."""
        alert = project.get("alert_node_h")
        if alert is None:
            return
        used = node_hours([tx.get(i) for i in tx.ids("run")])
        if used >= alert:
            raise ResearchDBError(f"recorded usage {used:.2f} node-h has reached alert_node_h {alert}; report it to the "
                                  "user, who decides whether to continue (raise or clear alert_node_h in "
                                  "research-tree.yaml, then /research-tree config apply)")

    def screen_seed_count(self) -> int:
        """Seeds a node experiment starts with: from the SOTA baseline's first-seed cost and screen_budget_node_h."""
        with self.reader() as tx:
            return self._screen_seeds(tx, self._project(tx))

    def _screen_seeds(self, tx: _Tx, project: dict) -> int:
        """Largest n <= gate_seeds (and <= screen_seeds, the configured screening seeds) with n x (SOTA first-seed
        node-hours) < screen budget; at least 1."""
        sota = project.get("sota_experiment_id")
        if not sota:
            raise ResearchDBError("set the SOTA baseline before node experiments; its cost fixes the screening seeds")
        run = tx.require(f"{sota}/s{project['seeds'][0]}", ("run",))
        cost = run["nodes_used"] * run["walltime_used_s"] / 3600
        n = 1
        cap = min(project["gate_seeds"], project.get("screen_seeds") or project["gate_seeds"])
        while n < cap and (n + 1) * cost < project["screen_budget_node_h"]:
            n += 1
        return n

    def extend_seeds(self, experiment_id: str, n_seeds: int) -> None:
        """Add seeds (next in project.seeds). Beyond the screening count only when the verdict is close or
        beats_parent, or by rld. Clears the verdict and comparisons; the experiment is evaluated again."""
        with self._writer() as tx:
            project = self._project(tx)
            exp = tx.require(experiment_id, ("experiment",))
            self._require_owner(exp)
            self._require_active(project)
            if exp.get("stage") == "confirm":
                raise ResearchDBError("a confirmation keeps its declared confirmation seeds; it is not extended")
            if exp["kind"] == "sanity":
                raise ResearchDBError("a sanity experiment runs one seed and is not extended")
            if exp.get("hypothesis_id") and _disposition(tx.get(exp["hypothesis_id"])) != "active":
                raise ResearchDBError(f"{exp['hypothesis_id']} is not active: no seed extensions")
            if not len(exp["seeds"]) < n_seeds <= project["gate_seeds"]:
                raise ResearchDBError(f"{experiment_id} has {len(exp['seeds'])} seeds; extend to at most {project['gate_seeds']}")
            self._check_usage_alert(tx, project)
            if exp["kind"] != "baseline" and self.role != "rld" and n_seeds > self._screen_seeds(tx, project) \
                    and exp.get("verdict") not in ("close", "beats_parent"):
                raise ResearchDBError("seeds beyond the screening budget need verdict close or beats_parent, or rld")
            self._update(tx, experiment_id, {
                "seeds": project["seeds"][:n_seeds], "verdict": None, "metric_mean": None, "metric_sd": None,
                "result_doc_id": None, "harness_ref": None, "evaluated_at": None, "evaluation_id": None,
            })
            tx.unlink_all("rel_compared_with", experiment_id)

    def create_run(self, experiment_id: str, seed: int, job_id: str | None = None) -> str:
        """One seed's run of an experiment (id <experiment>/s<seed>); the experiment's owner. Then update_run reports
        exec_status (planned/submitted/running/succeeded/failed/...), valid and the measurements."""
        with self._writer() as tx:
            exp = tx.require(experiment_id, ("experiment",))
            self._require_owner(exp)
            self._require_active(self._project(tx))
            if seed not in exp["seeds"]:
                raise ResearchDBError(f"seed {seed} is not one of {experiment_id}'s seeds {exp['seeds']}")
            return self._insert(tx, "run", {
                "id": f"{experiment_id}/s{seed}", "experiment_id": experiment_id, "seed": seed,
                "job_id": job_id, "exec_status": "planned",
            })

    def update_run(self, run_id: str, **changes) -> None:
        """Report a run as the experiment's owner (or rld). Fields: job_id, attempt, exec_status, valid,
        invalid_reason, curve_path, log_path, output_path, started_at, finished_at, and the measurements
        metric_value, secondary ({secondary metric: number} for each of the project's secondary_metrics), nodes_used,
        walltime_used_s.

        exec_status moves planned -> submitted -> running -> succeeded, failed or cancelled (submitted may go straight
        to a final state; unknown when the scheduler cannot tell). metric_value and secondary are a succeeded run's
        results. valid=true accepts a succeeded run with all four measurements and its log_path or output_path, and
        freezes it; evaluate_experiment needs a valid run for every seed. valid=false needs invalid_reason.

        A run whose attempt failed or was cancelled, or succeeded but was marked invalid, is resubmitted by raising
        attempt by one together with exec_status planned/submitted. The finished attempt is kept in attempts (its
        usage still counts) and the run starts over."""
        self._only_fields(changes, REPORTED_FIELDS + ("attempt",) + RUN_MEASUREMENTS)
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
            if retry:
                if old not in ("succeeded", "failed", "cancelled"):
                    raise ResearchDBError(f"{run_id} attempt {run['attempt']} is {old}: resubmit only a finished attempt "
                                          "(succeeded, failed or cancelled); an unknown state is checked first, never "
                                          "resubmitted blindly")
                if old == "succeeded" and run.get("valid") is not False:
                    raise ResearchDBError(f"{run_id} succeeded: resubmitting it needs valid=false with invalid_reason "
                                          "first, so no seed is rerun to replace a result")
                past = dict(run.get("attempts") or {})
                past[str(run["attempt"])] = {k: run[k] for k in ATTEMPT_FIELDS if run.get(k) is not None}
                changes = {**{k: None for k in ATTEMPT_FIELDS}, "attempts": past, **changes}
            elif new != old and new not in EXEC_TRANSITIONS[old]:
                raise _not_allowed("exec_status", old, new, EXEC_TRANSITIONS[old])
            if new != "succeeded" and any(changes.get(k) is not None for k in ("metric_value", "secondary")):
                raise ResearchDBError(f"metric_value and secondary are a succeeded run's results; {run_id} is {new}: "
                                      "report exec_status succeeded first or in the same call")
            if run.get("retracted_at") and not retry:
                raise ResearchDBError(f"{run_id} attempt {run['attempt']} was retracted ({run.get('retracted_reason')}); "
                                      "resubmit it as a new attempt (attempt + 1 with exec_status planned or submitted)")
            if run.get("import_record") and not retry:
                for field in ("metric_value", "secondary"):
                    if field in changes and changes[field] != run.get(field):
                        raise CodedError("STAT_MISMATCH", f"{run_id}.{field} was imported from "
                                                          f"{run.get('manifest_path')} as {run.get(field)!r}; it is "
                                                          "not reported again")
            if new == "submitted" and new != old:
                self._check_submission(tx, project, {**run, **changes})
                self._check_ready(tx, project, tx.get(run["experiment_id"]))
            if new == "unknown" and old == "planned":  # the scheduler may have it only if it was being submitted
                if not run.get("submission_key"):
                    raise ResearchDBError(f"{run_id} was never submitted (no submission key): it stays planned")
                self._check_submission(tx, project, {**run, **changes})
            final = {**run, **changes}
            if final.get("valid") is False and not (final.get("invalid_reason") or "").strip():
                raise ResearchDBError("valid=false needs invalid_reason: what failed acceptance, citing the log")
            if final.get("valid") is True:
                missing = [k for k in RUN_MEASUREMENTS if final.get(k) is None]
                if new != "succeeded" or missing:
                    raise ResearchDBError(f"a valid run must have succeeded and record {', '.join(missing) or 'its measurements'}")
                if not (final.get("log_path") or final.get("output_path")):
                    raise ResearchDBError("a valid run needs its evidence: log_path or output_path")
                if set(final["secondary"]) != set(project["secondary_metrics"]) or not all(
                    _type_ok(v, "REAL") for v in final["secondary"].values()
                ):
                    raise ResearchDBError(f"secondary must give a number for each of {project['secondary_metrics']}")
                if final["nodes_used"] > project["max_nodes"] or final["walltime_used_s"] > project["max_walltime_s"]:
                    raise ResearchDBError("recorded usage exceeds the per-run cap")
                protocol = self._protocol(tx, project)
                if (protocol or {}).get("require_artifact_import") and not final.get("import_record"):
                    raise ResearchDBError(f"the protocol requires imported results: import_run_result({run_id}, "
                                          f"{final['attempt']}, <manifest>) before valid=true")
                with _coded():
                    metrics.run_values(self._specs(tx, project), {**final, "id": run_id},
                                       [n for n in [project["primary_metric"], *project["secondary_metrics"]]
                                        if n in metrics.spec_by_name(self._specs(tx, project))])
            self._update(tx, run_id, changes)
            if new == "unknown" and run.get("submission_key"):  # a lost answer keeps the reservation held (05 §4.5)
                held = self._reservation(tx, run["submission_key"])
                if held["accounting_status"] == "reserved":
                    self._update(tx, held["id"], {"accounting_status": "held_unknown"})
            exp = tx.get(run["experiment_id"])
            if new == "submitted" and exp.get("hypothesis_id"):
                self._stamp_once(tx, exp["hypothesis_id"], "first_experiment_at")

    def _check_submission(self, tx: _Tx, project: dict, run: dict) -> None:
        """With a total budget, a run is submitted only under its attempt's claimed or attached reservation."""
        if project.get("total_limit") is None and not run.get("submission_key"):
            return
        key = run.get("submission_key")
        r = self._reservation(tx, key) if key else None
        ref = f"{run['id']}@{run['attempt']}"
        if r is None or ref not in r["run_attempt_refs"] or r["accounting_status"] not in ("reserved", "held_unknown") \
                or r["submission_phase"] == "intent":
            raise CodedError("BUDGET_EXCEEDED", f"{ref} is submitted only under a reservation: reserve_submission, "
                                                "claim_submission, then submit with the submission key")

    def _stamp_once(self, tx: _Tx, hypothesis_id: str, field_name: str) -> None:
        """Record a node's first-time timestamp; later events never overwrite it."""
        if not tx.get(hypothesis_id).get(field_name):
            tx.set(hypothesis_id, {field_name: now_utc()})

    def _require_owner(self, record: dict) -> None:
        if self.role != "rld" and record["owner"] != self.agent:
            raise PermissionDenied(f"{record['id']} belongs to {record['owner']}")

    # -- run results ----------------------------------------------------------------

    def import_run_result(self, run_id: str, attempt: int, manifest_path: str) -> dict:
        """Import one attempt's results through its manifest (plans/design 05 §2.2): the frozen parser reads the
        metrics file the manifest names and checks identity (experiment, seed, attempt, code version), exit
        status, finite values in their valid range, counts, and the protocol's required settings. The values
        become the run's metric_value and secondary; the metrics file and declared evidence files are kept from
        cleanup. The experiment's owner (or rld), on a run reported succeeded; validity is still decided with
        update_run(valid=...). Importing the same attempt again with the same files changes nothing.

        Manifest (JSON; paths relative to the manifest's directory or absolute inside the project):
          {"experiment_id", "seed", "attempt", "code_ref", "exit_status": 0, "metrics_path",
           "counts": {"n_val": 400, ...}, "data_version", "config": {...} or path, "env": {...},
           optional "evidence_paths", "log_path", "curve_path", "output_path", "nodes_used", "walltime_used_s",
           and any key the protocol pairs on or requires}.
        The metrics file is a JSON object with the project's metrics by name, in their input units."""
        with self._ledgered(RUN_ID_RE.match(run_id).group(1) if RUN_ID_RE.match(run_id) else run_id,
                            "import_run_result"):
            return self._import_run_result(run_id, attempt, manifest_path)

    def _import_run_result(self, run_id: str, attempt: int, manifest_path: str) -> dict:
        with self.reader() as tx:
            project = self._project(tx)
            run = tx.require(run_id, ("run",))
            exp = tx.require(run["experiment_id"], ("experiment",))
            self._require_owner(exp)
            specs, protocol = self._specs(tx, project), self._protocol(tx, project)
        if attempt != run["attempt"]:
            raise CodedError("EVIDENCE_CHANGED", f"{run_id} is at attempt {run['attempt']}, not {attempt}")
        if run["exec_status"] != "succeeded":
            raise ResearchDBError(f"{run_id} is {run['exec_status']}: report exec_status succeeded (update_run) "
                                  "before importing its results")
        manifest_file = self._inside_project(manifest_path, self.db_path.parent, "manifest_path")
        manifest = _read_json(manifest_file, "manifest")
        if not isinstance(manifest, dict):
            raise ResearchDBError(f"{manifest_file} must hold a JSON object")
        base = manifest_file.parent
        problems = []
        for key, want in (("experiment_id", exp["id"]), ("seed", run["seed"]), ("attempt", attempt)):
            if manifest.get(key) != want:
                problems.append(f"{key} is {manifest.get(key)!r}, expected {want!r}")
        code = manifest.get("code_ref")
        if not isinstance(code, str) or _git_commit(project["repo_path"], code) != exp["code_ref"]:
            problems.append(f"code_ref {code!r} is not the experiment's code {exp['code_ref'][:10]}")
        if manifest.get("exit_status") not in (0, "succeeded"):
            problems.append(f"exit_status is {manifest.get('exit_status')!r}, not 0")
        counts = manifest.get("counts")
        if not isinstance(counts, dict) or not counts or not all(
                isinstance(v, int) and not isinstance(v, bool) and v > 0 for v in counts.values()):
            problems.append("counts must give the positive numbers of training/evaluation items actually used")
            counts = {}
        for name, want in ((protocol or {}).get("required_counts") or {}).items():
            if counts.get(name) != want:
                problems.append(f"counts.{name} is {counts.get(name)!r}, the protocol requires {want}")
        for key in ("data_version", "config", "env"):
            if manifest.get(key) in (None, "", {}):
                problems.append(f"{key} is missing")
        if problems:
            raise CodedError("PAIRING_MISMATCH" if any("protocol" in x for x in problems) else "STAT_MISMATCH",
                             f"{manifest_file.name} does not describe {run_id}@{attempt}: " + "; ".join(problems))
        for key, want in ((protocol or {}).get("match") or {}).items():
            if manifest.get(key) != want:
                raise CodedError("PAIRING_MISMATCH", f"{manifest_file.name}: {key} is {manifest.get(key)!r}, "
                                                     f"the protocol fixes {want!r}; this run cannot join the comparison")
        metrics_file = self._inside_project(manifest.get("metrics_path"), base, "metrics_path")
        values = _read_json(metrics_file, "metrics file")
        if not isinstance(values, dict):
            raise ResearchDBError(f"{metrics_file} must hold a JSON object of metric values")
        units = manifest.get("units")
        by_spec = metrics.spec_by_name(specs)
        declared = [n for n in [project["primary_metric"], *project["secondary_metrics"]] if n in by_spec
                    and not specs.get("legacy")]
        if declared and (not isinstance(units, dict) or any(units.get(n) != by_spec[n]["input_unit"] for n in declared)):
            raise CodedError("METRIC_UNIT_MISMATCH", f"{manifest_file.name} declares units {units!r}; the metric "
                                                     "specification reads "
                                                     f"{ {n: by_spec[n]['input_unit'] for n in declared} } "
                                                     "(the runner states each metric's unit in the manifest)")
        names = [project["primary_metric"], *project["secondary_metrics"]]
        by_name = by_spec
        with _coded():
            for name in names:
                if name not in values:
                    raise ResearchDBError(f"{metrics_file.name} has no {name}")
                if name in by_name:
                    metrics.canonical(by_name[name], values[name], f"{run_id}@{attempt}")
                elif not (metrics.is_number(values[name]) and math.isfinite(values[name])):
                    raise MetricError("NONFINITE_METRIC", f"{run_id}@{attempt}: {name} is {values[name]!r}")
            for key in (protocol or {}).get("pair_fields", []):
                if key != "seed" and not isinstance(manifest.get(key), (str, int, float, bool)):
                    raise MetricError("PAIRING_MISMATCH", f"{manifest_file.name} lacks {key} (a scalar), a pair "
                                                          "field of the protocol")
        evidence_files = [metrics_file] + [self._inside_project(e, base, "evidence_paths")
                                           for e in manifest.get("evidence_paths") or []]
        record = {"parser_version": metrics.PARSER_VERSION, "manifest_sha256": sha256_file(manifest_file),
                  "metrics_sha256": sha256_file(metrics_file), "imported_at": now_utc(),
                  "by": f"{self.role}/{self.agent}"}
        # every scalar field of the manifest is kept, so a later protocol can be checked against it without a re-run
        kept = {k: v for k, v in manifest.items() if isinstance(v, (str, int, float, bool)) and k != "counts"}
        changes = {
            "metric_value": values[project["primary_metric"]],
            "secondary": {k: values[k] for k in project["secondary_metrics"]},
            "manifest_path": self._research_rel(manifest_file), "manifest": {**kept, "counts": counts},
            "evidence_paths": [self._research_rel(f) for f in evidence_files], "import_record": record,
        }
        for key in ("log_path", "curve_path", "output_path"):
            if manifest.get(key):
                changes[key] = self._research_rel(self._inside_project(manifest[key], base, key, exists=False))
        for key in ("nodes_used", "walltime_used_s"):
            if isinstance(manifest.get(key), int) and not isinstance(manifest[key], bool):
                changes[key] = manifest[key]
        with self._writer() as tx:
            current = tx.require(run_id, ("run",))
            if current["attempt"] != attempt or current["exec_status"] != "succeeded":
                raise CodedError("EVIDENCE_CHANGED", f"{run_id} changed while its results were read; import again")
            previous = current.get("import_record")
            if previous:
                same = (previous["manifest_sha256"], previous["metrics_sha256"]) == (
                    record["manifest_sha256"], record["metrics_sha256"])
                if not same:
                    raise CodedError("EVIDENCE_CHANGED", f"{run_id}@{attempt} was imported from other files "
                                                         f"({current.get('manifest_path')}); an attempt is imported once")
                return {"run_id": run_id, "attempt": attempt, "imported": False, "import_record": previous}
            for key in ("metric_value", "secondary", "nodes_used", "walltime_used_s"):
                if current.get(key) is not None and key in changes and current[key] != changes[key]:
                    if current.get("valid") is True or key in ("metric_value", "secondary"):
                        raise CodedError("STAT_MISMATCH", f"{run_id} already records {key}={current[key]!r}; "
                                                          f"its metrics file says {changes[key]!r}")
            if current.get("valid") is True:  # a valid run is frozen: only the import fields are added
                changes = {k: v for k, v in changes.items() if k in IMPORT_FIELDS}
            self._update(tx, run_id, changes)
            return {"run_id": run_id, "attempt": attempt, "imported": True, "import_record": record,
                    "metrics": {k: values[k] for k in names}}

    def retract_run(self, run_id: str, reason: str, doc_id: str) -> None:
        """A valid run later shown to be invalid (a wrong evaluator, corrupted data, ...): rld only, with a current
        decision or report document. The run keeps its record and becomes invalid; every evaluation that used it
        stops supporting GO. The run may then be resubmitted as a new attempt."""
        self._require_role("rld")
        if not reason.strip():
            raise ResearchDBError("retracting a run needs a reason")
        with self._writer() as tx:
            run = tx.require(run_id, ("run",))
            if run.get("valid") is not True:
                raise ResearchDBError(f"{run_id} is not a valid run (valid {run.get('valid')})")
            self._check_refs(tx, "decision", {"doc_id": doc_id}, current_docs=True)
            now = now_utc()
            tx.set(run_id, {"valid": False, "invalid_reason": f"retracted: {reason} ({doc_id})",
                            "retracted_at": now, "retracted_reason": reason})
            exp = tx.get(run["experiment_id"])
            decision_id = tx.next_id("decision")
            self._insert(tx, "decision", {
                "id": decision_id, "target_id": exp.get("hypothesis_id") or self._project(tx)["id"],
                "field": "run_validity", "from_value": f"{run_id}@{run['attempt']} valid",
                "to_value": f"{run_id}@{run['attempt']} retracted", "reason": reason, "doc_id": doc_id,
                "decided_by": self.agent, "decided_at": now,
            })
            ref = f"{run_id}@{run['attempt']}"
            affected = [v for v in tx.ids("evaluation") if ref in (tx.get(v).get("run_attempt_refs") or [])]
            for target in [doc_id, *affected]:
                tx.link("rel_based_on", decision_id, target)

    def _inside_project(self, path: Any, base: Path, what: str, exists: bool = True) -> Path:
        if not isinstance(path, str) or not path:
            raise ResearchDBError(f"{what} is missing")
        resolved = Path(os.path.realpath(path if os.path.isabs(path) else base / path))
        if not resolved.is_relative_to(Path(os.path.realpath(self.project_dir))):
            raise ResearchDBError(f"{what} {path} is outside the project directory")
        if exists and not resolved.is_file():
            raise ResearchDBError(f"{what} {path} does not exist")
        return resolved

    def _research_rel(self, path: Path) -> str:
        """A path relative to the research root when it lies inside it (the form runs record), else absolute."""
        root = Path(os.path.realpath(self.db_path.parent))
        return str(path.relative_to(root)) if path.is_relative_to(root) else str(path)

    # -- evaluations ----------------------------------------------------------------

    def evaluate_experiment(self, experiment_id: str, result_doc_id: str, verdict: str | None = None,
                            protocol_id: str | None = None, baseline_experiment_id: str | None = None) -> dict:
        """Compute an experiment's statistics from its registered runs and record them as an evaluation
        (plans/design 05 §2–3): means and sample SDs per metric in canonical units, and for node experiments the
        paired effects against the references fixed at creation (SOTA baseline, and the parent's experiment below
        the top level), the SOTA gate (minimum practical gain of the primary metric over the required pairs) and
        the guardrails (allowed regressions). No number is taken from the caller. Every seed needs a valid run.

        verdict: node experiments still name one (no_gain, close, beats_parent, beats_sota, needs_rld); it must
        agree with the computed comparisons. Baselines record metrics only. protocol_id, when given, must be the
        project's current protocol. baseline_experiment_id rescores against the current SOTA when it changed since
        the experiment was created: a new evaluation, the earlier one stays. The same inputs again return the
        same evaluation. The result document cites its numbers in an ```evidence block (checked against files)."""
        with self._ledgered(experiment_id, "evaluate_experiment"):
            return self._evaluate(experiment_id, result_doc_id, verdict, protocol_id, baseline_experiment_id, None)

    def record_verdict(self, experiment_id: str, result_doc_id: str, metric_mean: float | None = None,
                       metric_sd: float | None = None, verdict: str | None = None,
                       comparisons: list[dict] | tuple[dict, ...] = ()) -> dict:
        """Compatibility entry of evaluate_experiment: the statistics are recomputed from the runs and the numbers
        given here are only cross-checked (STAT_MISMATCH when they differ beyond the decimals given). comparisons:
        [{"target_id", "role": "parent"|"sota", "n_paired", "delta_mean", "delta_sd", "deltas"}], effects oriented so
        that positive is better. Every seed needs a valid run first (update_run: exec_status succeeded, valid true,
        measurements)."""
        expected = {"metric_mean": metric_mean, "metric_sd": metric_sd, "comparisons": list(comparisons)}
        with self._ledgered(experiment_id, "record_verdict"):
            return self._evaluate(experiment_id, result_doc_id, verdict, None, None, expected)

    @contextmanager
    def _ledgered(self, experiment_id: str, call: str) -> Iterator[None]:
        """A STAT_MISMATCH or PAIRING_MISMATCH on a node's experiment is also an obligation (06 §6): it stays OPEN
        until the Leader resolves it with evidence (e.g. the corrected evaluation) and blocks GO meanwhile."""
        try:
            yield
        except CodedError as exc:
            if exc.code in ("STAT_MISMATCH", "PAIRING_MISMATCH"):
                exp = self.get(experiment_id) if table_of(experiment_id) == "experiment" else None
                if exp and exp.get("hypothesis_id"):
                    self._obligation(experiment_id, f"{exc.code}:interface", f"{call} on {experiment_id}", str(exc),
                                     "MAJOR", "")
            raise

    # Called between the computation (outside the write lock) and the write; tests use it to change the database.
    _after_compute = None

    def _evaluate(self, experiment_id: str, result_doc_id: str, verdict: str | None, protocol_id: str | None,
                  baseline_id: str | None, expected: dict | None) -> dict:
        with self.reader() as tx:
            project = self._project(tx)
            exp = tx.require(experiment_id, ("experiment",))
            self._require_owner(exp)
            if exp["kind"] == "sanity":
                raise ResearchDBError(f"{experiment_id} is a sanity check: accept its run (valid) — it is not evaluated "
                                      "and counts toward no seed")
            invalid = _invalid_runs(tx, exp)
            if invalid:
                raise ResearchDBError(f"{experiment_id} needs a valid run for every seed; not yet: {invalid}. "
                                      f"{VALID_RUN_HOW}")
            self._check_harness(project, exp)
            self._check_refs(tx, "experiment", {"result_doc_id": result_doc_id}, current_docs=True)
            self._check_values("experiment", {"verdict": verdict})
            if protocol_id is not None and protocol_id != project.get("protocol_doc_id"):
                raise CodedError("PROTOCOL_CHANGE_REQUIRED", f"{protocol_id} is not the project's current protocol "
                                                             f"({project.get('protocol_doc_id')})")
            if exp["kind"] == "baseline":
                if verdict is not None or (expected and expected["comparisons"]) or baseline_id:
                    raise ResearchDBError("a baseline records metrics only, no verdict or comparisons")
            else:
                branch = self._branch_of(tx, exp["hypothesis_id"])
                if _git_commit(project["repo_path"], branch["base_commit"]) == exp["code_ref"]:
                    raise ResearchDBError(f"{experiment_id} ran the branch base; a node needs a code change")
            refs = self._references(tx, project, exp, baseline_id)
            signature = self._signature(tx, project, exp, refs)
            with _coded():
                computed = self._compute(tx, project, exp, refs)
            if expected is not None:
                self._cross_check(computed, expected, exp)
            self._check_result_claims(tx, exp, result_doc_id, computed)
            edges = computed["edges"]
            if exp["kind"] != "baseline" and verdict is not None:  # the old labels, still checked when given
                self._check_verdict(project, exp, verdict, edges)
            fingerprint = hashlib.sha256(json.dumps({"inputs": signature["inputs_digest"], "verdict": verdict,
                                                     "result_doc_id": result_doc_id},
                                                    sort_keys=True).encode()).hexdigest()
            if exp.get("evaluated_at"):
                old = tx.get(exp["evaluation_id"]) if exp.get("evaluation_id") else None
                if old is None:
                    raise ResearchDBError(f"{experiment_id} is already evaluated; extend its seeds or start a new "
                                          "experiment (migrate_evaluations records an evaluation for it)")
                if old["fingerprint"] == fingerprint:  # the same inputs again: the same evaluation
                    return {"evaluation_id": old["id"], "created": False, **computed["public"]}
                if old["inputs_digest"] == signature["inputs_digest"] and not old.get("migrated"):
                    raise ResearchDBError(f"{experiment_id} is already evaluated with these runs ({old['id']}, verdict "
                                          f"{old.get('verdict')}); extend its seeds or start a new experiment")
        if self._after_compute is not None:
            self._after_compute()
        with self._writer() as tx:
            project = self._project(tx)
            exp = tx.require(experiment_id, ("experiment",))
            try:
                refs_now = self._references(tx, project, exp, baseline_id)
            except CodedError as exc:
                raise CodedError("EVIDENCE_CHANGED", f"the references of {experiment_id} changed while it was "
                                                     f"computed ({exc}); evaluate again") from None
            if self._signature(tx, project, exp, refs_now) != signature:
                raise CodedError("EVIDENCE_CHANGED", f"the runs, references, protocol or harness of {experiment_id} "
                                                     "changed while it was computed; evaluate again")
            current = tx.get(exp["evaluation_id"]) if exp.get("evaluation_id") else None
            if current is not None and current["fingerprint"] == fingerprint:  # written meanwhile by the same call
                return {"evaluation_id": current["id"], "created": False, **computed["public"]}
            if current is not None and current["inputs_digest"] == signature["inputs_digest"] \
                    and not current.get("migrated"):
                raise ResearchDBError(f"{experiment_id} was evaluated with these runs meanwhile ({current['id']}, "
                                      f"verdict {current.get('verdict')})")
            ev_id = self._record_evaluation(tx, project, exp, refs, signature, computed, verdict, result_doc_id,
                                            fingerprint)
            return {"evaluation_id": ev_id, "created": True, **computed["public"]}

    def _record_evaluation(self, tx: _Tx, project: dict, exp: dict, refs: dict, signature: dict, computed: dict,
                           verdict: str | None, result_doc_id: str | None, fingerprint: str,
                           migrated: bool = False) -> str:
        """Write one evaluation and make it the experiment's current one (migrated: the experiment's recorded
        result stays as it was)."""
        experiment_id = exp["id"]
        history = self._evaluations_of(tx, experiment_id)
        previous = history[-1]["id"] if history else None
        ev_id = tx.next_id("evaluation")
        revision = len(history) + 1
        self._insert(tx, "evaluation", {
            "id": ev_id, "experiment_id": experiment_id, "result_revision": revision,
            "run_attempt_refs": signature["run_attempt_refs"], "input_revisions": signature["inputs"],
            "pair_keys": computed["pair_keys"], "method_code_ref": exp["code_ref"],
            "harness_ref": project.get("harness_ref"), "harness_paths": sorted(project.get("harness_paths") or []),
            "protocol_doc_id": project.get("protocol_doc_id"),
            "metric_spec_doc_id": project.get("metric_spec_doc_id"),
            "baseline_experiment_id": refs.get("sota"), "baseline_evaluation_id": refs.get("sota_evaluation"),
            "parent_experiment_id": refs.get("parent"), "parent_evaluation_id": refs.get("parent_evaluation"),
            "result_doc_id": result_doc_id, "metrics": computed["metrics"], "comparisons": computed["comparisons"],
            "verdict": verdict, "outcome": computed.get("outcome"), "outcome_reason": computed.get("outcome_reason"),
            "stage": computed.get("stage"), "gate_passed": computed["gate_passed"],
            "guardrails_passed": computed["guardrails_passed"], "eval_type": computed["eval_type"],
            "limitations": computed["limitations"], "verification_level": computed["verification_level"],
            "artifact_refs": computed["artifact_refs"], "statistics_version": metrics.STATISTICS_VERSION,
            "parser_version": metrics.PARSER_VERSION if computed["verification_level"] == "artifact_imported" else None,
            "fingerprint": fingerprint, "inputs_digest": signature["inputs_digest"],
            "supersedes_evaluation_id": previous, "created_by": f"{self.role}/{self.agent}",
            "migrated": True if migrated else None,
        })
        if migrated:
            tx.set(experiment_id, {"evaluation_id": ev_id})
            return ev_id
        primary = computed["metrics"][computed["primary"]]
        self._update(tx, experiment_id, {
            "verdict": verdict, "metric_mean": primary["mean"], "metric_sd": primary["sd"],
            "result_doc_id": result_doc_id, "harness_ref": project["harness_ref"], "evaluated_at": now_utc(),
            "evaluation_id": ev_id,
        })
        if exp.get("hypothesis_id"):
            self._stamp_once(tx, exp["hypothesis_id"], "first_result_at")
        tx.unlink_all("rel_compared_with", experiment_id)
        for edge in computed["edges"]:
            tx.link("rel_compared_with", experiment_id, edge["target_id"],
                    {k: v for k, v in edge.items() if k != "target_id" and v is not None})
        return ev_id

    def migrate_states(self, dry_run: bool = True) -> dict:
        """Old node records to the separate lifecycle / outcome / disposition (plans/design 10 §2.3): disposition
        retired for prunable nodes, active otherwise, reason copied from the status; nothing else changes (no
        experiment is re-run, no verdict is upgraded: an old 'close' is an inconclusive result). rld only."""
        self._require_role("rld")
        with self.reader() as tx:
            plan = [(h["id"], h["status"], _disposition(h), h.get("status_reason"))
                    for h in (tx.get(i) for i in tx.ids("hypothesis")) if not h.get("disposition")]
            closes = [e["id"] for e in (tx.get(i) for i in tx.ids("experiment")) if e.get("verdict") == "close"]
            ran = {h for h, *_ in plan if self._node_evaluations(tx, h)}
        report = {"nodes": [{"hypothesis_id": h, "status": st, "disposition": d,
                             "lifecycle": "pending" if st == "prunable" and h not in ran else LIFECYCLE[st]}
                            for h, st, d, _ in plan], "close_as_inconclusive": closes}
        if not dry_run:
            with self._writer() as tx:
                for h, _, d, reason in plan:
                    if not tx.get(h).get("disposition"):
                        tx.set(h, {"disposition": d, "disposition_reason": reason or "migrated from status"})
        return report

    def migrate_evaluations(self, dry_run: bool = True) -> dict:
        """Shadow comparison for experiments evaluated before evaluations existed (plans/design 10 §2.2 B–C):
        recompute each from its registered runs and compare with its recorded mean, SD and comparisons. With
        dry_run=false the consistent ones get an evaluation bound to the harness they were evaluated with; the
        inconsistent ones are only listed. rld only. Nothing is re-run and no recorded result changes."""
        self._require_role("rld")
        report = {"consistent": [], "mismatched": [], "recorded": []}
        planned = []
        with self.reader() as tx:
            project = self._project(tx)
            # references (baselines) first, so that dependants bind to their evaluations
            order = sorted((tx.get(i) for i in tx.ids("experiment")),
                           key=lambda e: (e["kind"] != "baseline", int(e["id"].split("-")[1])))
            for exp in order:
                if not exp.get("evaluated_at") or exp.get("evaluation_id"):
                    continue
                edges = tx.edges("rel_compared_with", source=exp["id"])
                refs = {e["role"]: e["target_id"] for e in edges}
                for role in ("sota", "parent"):
                    if role in refs:
                        refs[f"{role}_evaluation"] = tx.get(refs[role]).get("evaluation_id")
                then = {**project, "harness_ref": exp.get("harness_ref")}
                try:
                    with _coded():
                        computed = self._compute(tx, then, exp, refs)
                    self._cross_check(computed, {
                        "metric_mean": exp.get("metric_mean"), "metric_sd": exp.get("metric_sd"),
                        "comparisons": [{k: e.get(k) for k in ("target_id", "role", "n_paired", "delta_mean",
                                                               "delta_sd", "deltas")} for e in edges]}, exp)
                except ResearchDBError as exc:
                    report["mismatched"].append({"experiment_id": exp["id"], "error": str(exc)})
                    continue
                signature = self._signature(tx, then, exp, refs)
                planned.append((exp["id"], refs, signature, computed))
                report["consistent"].append(exp["id"])
        if dry_run:
            return report
        with self._writer() as tx:
            project = self._project(tx)
            for exp_id, refs, signature, computed in planned:
                exp = tx.get(exp_id)
                then = {**project, "harness_ref": exp.get("harness_ref")}
                for role in ("sota", "parent"):  # bind to the references' evaluations, migrated just before
                    if role in refs:
                        refs[f"{role}_evaluation"] = tx.get(refs[role]).get("evaluation_id")
                if exp.get("evaluation_id"):
                    continue
                planned_inputs = signature["inputs"]
                signature = self._signature(tx, then, exp, refs)
                if signature["inputs"] != planned_inputs:  # its runs changed since the comparison: not now
                    report["mismatched"].append({"experiment_id": exp_id, "error": "EVIDENCE_CHANGED: runs changed"})
                    continue
                fingerprint = hashlib.sha256(json.dumps({"inputs": signature["inputs_digest"],
                                                         "verdict": exp.get("verdict"),
                                                         "result_doc_id": exp.get("result_doc_id")},
                                                        sort_keys=True).encode()).hexdigest()
                ev_id = self._record_evaluation(tx, then, exp, refs, signature, computed, exp.get("verdict"),
                                                exp.get("result_doc_id"), fingerprint, migrated=True)
                report["recorded"].append({"experiment_id": exp_id, "evaluation_id": ev_id,
                                           "verification_level": computed["verification_level"]})
        return report

    def _evaluations_of(self, tx: _Tx, experiment_id: str) -> list[dict]:
        rows = tx.query("MATCH (v:Evaluation)-[:EVALUATES]->(e:Experiment {id: $id}) RETURN v.id AS id", id=experiment_id)
        return sorted((tx.get(r["id"]) for r in rows), key=lambda v: v["result_revision"])

    def preview_evaluation(self, experiment_id: str, baseline_experiment_id: str | None = None) -> dict:
        """What evaluate_experiment would compute now, without recording anything: the means, SDs, paired effects,
        gate and guardrails, so that the result document can state them (mean:<metric>, delta:<role>:<metric>)
        before the evaluation. Read-only."""
        with self.reader() as tx:
            project = self._project(tx)
            exp = tx.require(experiment_id, ("experiment",))
            invalid = _invalid_runs(tx, exp)
            if invalid:
                raise ResearchDBError(f"{experiment_id} needs a valid run for every seed; not yet: {invalid}")
            refs = self._references(tx, project, exp, baseline_experiment_id)
            with _coded():
                computed = self._compute(tx, project, exp, refs)
        return {"experiment_id": experiment_id, "references": {k: v for k, v in refs.items() if v},
                "metrics": {n: {k: m[k] for k in ("n", "mean", "sd", "unit")} for n, m in computed["metrics"].items()},
                "comparisons": {r: {"target_id": c["target_id"], "n_paired": c["n_paired"],
                                    "effects": {n: e.get("delta_mean") for n, e in c["metrics"].items()},
                                    "passes_gate": c.get("passes_gate"), "guardrails": c["guardrails"]}
                                for r, c in computed["comparisons"].items()},
                "verification_level": computed["verification_level"], "limitations": computed["limitations"]}

    def _references(self, tx: _Tx, project: dict, exp: dict, baseline_id: str | None) -> dict:
        """The experiments a node experiment is compared with: fixed at creation (older experiments: the SOTA and
        the parent's latest evaluated experiment). baseline_id rescores against the current SOTA."""
        if exp["kind"] == "baseline":
            return {}
        refs = {}
        sota = exp.get("baseline_experiment_id") or project.get("sota_experiment_id")
        history = self._evaluations_of(tx, exp["id"])
        if history and history[-1].get("baseline_experiment_id"):  # a rescoring sticks to its new baseline
            sota = history[-1]["baseline_experiment_id"]
        if baseline_id is not None:
            if baseline_id != project.get("sota_experiment_id"):
                raise ResearchDBError(f"rescoring is against the current SOTA baseline "
                                      f"{project.get('sota_experiment_id')}, not {baseline_id}")
            sota = baseline_id
        if not sota:
            raise ResearchDBError("no SOTA baseline is set for the current harness")
        refs["sota"] = sota
        parent = tx.get(exp["hypothesis_id"])["parent_id"]
        if table_of(parent) == "hypothesis" and (exp.get("stage") or "screen") != "confirm":
            ref = (exp.get("parent_experiment_id") or (history[-1].get("parent_experiment_id") if history else None)
                   or (self._latest_evaluated(tx, parent) or {}).get("id"))
            if ref is None:
                raise ResearchDBError(f"parent {parent} has no experiment evaluated with the current harness")
            refs["parent"] = ref
        for role in ("sota", "parent"):
            if role in refs:
                target = tx.require(refs[role], ("experiment",))
                if not target.get("evaluated_at"):
                    raise ResearchDBError(f"the {role} reference {refs[role]} is not evaluated")
                refs[f"{role}_evaluation"] = target.get("evaluation_id")
                ref_ev = tx.get(target["evaluation_id"]) if target.get("evaluation_id") else None
                if ref_ev is not None and not ref_ev.get("migrated") and any(
                        ref_ev.get(k) != project.get(k) for k in ("protocol_doc_id", "metric_spec_doc_id")):
                    raise CodedError("EVIDENCE_STALE", f"the {role} reference {refs[role]} was evaluated under another "
                                                       "protocol or metric specification; evaluate it again (its runs "
                                                       "must meet the current protocol) before comparing with it")
        return refs

    def _signature(self, tx: _Tx, project: dict, exp: dict, refs: dict) -> dict:
        """What an evaluation rests on: each participating run's attempt and values, the references and their
        evaluations, the code, harness, protocol and metric specification. Compared again inside the write."""
        inputs, attempt_refs = {}, []
        for exp_id in [exp["id"]] + [refs[r] for r in ("sota", "parent") if r in refs]:
            seeds = exp["seeds"] if exp_id == exp["id"] else tx.require(exp_id, ("experiment",))["seeds"]
            for seed in seeds:
                run = tx.get(f"{exp_id}/s{seed}")
                if run is None:
                    continue
                inputs[run["id"]] = {k: run.get(k) for k in ("attempt", "valid", "metric_value", "secondary",
                                                             "retracted_at")}
                inputs[run["id"]]["import"] = (run.get("import_record") or {}).get("metrics_sha256")
                if exp_id == exp["id"] or run.get("valid") is True:
                    attempt_refs.append(f"{run['id']}@{run['attempt']}")
        context = {"code_ref": exp["code_ref"], "seeds": exp["seeds"], "harness_ref": project.get("harness_ref"),
                   "harness_paths": sorted(project.get("harness_paths") or []),
                   "protocol_doc_id": project.get("protocol_doc_id"),
                   "metric_spec_doc_id": project.get("metric_spec_doc_id"), "refs": refs,
                   "statistics_version": metrics.STATISTICS_VERSION}
        digest = hashlib.sha256(json.dumps({"inputs": inputs, **context}, sort_keys=True).encode()).hexdigest()
        return {"inputs": inputs, "run_attempt_refs": sorted(attempt_refs), "context": context,
                "inputs_digest": digest}

    def _compute(self, tx: _Tx, project: dict, exp: dict, refs: dict) -> dict:
        specs, protocol = self._specs(tx, project), self._protocol(tx, project)
        names = [project["primary_metric"], *project["secondary_metrics"]]
        legacy = bool(specs.get("legacy"))
        runs = [tx.get(f"{exp['id']}/s{s}") for s in exp["seeds"]]
        by_name = metrics.spec_by_name(specs)
        per_metric = {}
        for name in names:
            if name not in by_name:
                continue
            values = [metrics.run_values(specs, r, [name])[name] for r in runs]
            metrics.check_unit_mix(by_name[name], values, exp["id"])
            per_metric[name] = {**metrics.summary(values), "unit": by_name[name]["canonical_unit"],
                                "seeds": [r["seed"] for r in runs]}
        limitations = []
        if legacy:
            limitations.append("legacy metric specification: secondary metrics have no recorded direction and "
                               "their deltas are the caller's, not recomputed")
        if len(runs) == 1:
            limitations.append("n=1: no standard deviation")
        comparisons, edges, pair_keys = {}, [], {}
        gate_passed = guardrails_passed = None
        primary = specs["primary"]
        threshold = by_name[primary]["minimum_practical_gain"]
        comparison = (protocol or {}).get("gate_comparison", ">")
        stage = exp.get("stage") or "screen"
        min_pairs = (protocol or {}).get("min_pairs") or project["gate_seeds"]
        if stage == "confirm":  # the confirmation's own declared number of pairs (06 §2.2)
            min_pairs = (protocol or {}).get("min_confirmation_pairs") or 3
        for role in ("sota", "parent"):
            if role not in refs:
                continue
            target = tx.require(refs[role], ("experiment",))
            ref_runs = [r for r in (tx.get(f"{target['id']}/s{s}") for s in target["seeds"])
                        if r is not None and r.get("valid") is True]
            cmp = metrics.compare(specs, protocol, runs, ref_runs, names)
            if cmp["unpaired_same_seed"]:
                raise MetricError("PAIRING_MISMATCH", f"{exp['id']} and {target['id']} share seeds "
                                                      f"{cmp['unpaired_same_seed']} whose protocol fields differ")
            if cmp["n_paired"] == 0:
                raise MetricError("PAIRING_MISMATCH", f"{exp['id']} has no run paired with {target['id']}")
            effect = cmp["metrics"][primary]
            if effect.get("undefined"):
                raise MetricError(effect["undefined"], f"{primary} against {target['id']}: {effect['reason']}; "
                                                       "the protocol must say how to compare it")
            for name, e in cmp["metrics"].items():
                if e.get("undefined"):
                    limitations.append(f"{name} against {target['id']}: {e['undefined']} ({e['reason']})")
            guard = metrics.guardrails(specs, cmp)
            entry = {"target_id": target["id"], "n_paired": cmp["n_paired"], "n_independent": cmp["n_independent"],
                     "metrics": cmp["metrics"],
                     "delta_mean": effect["delta_mean"], "delta_sd": effect.get("delta_sd"),
                     "deltas": {n: cmp["metrics"][n]["delta_mean"] for n in project["secondary_metrics"]
                                if n in cmp["metrics"]},
                     "guardrails": guard}
            if role == "sota":
                entry["passes_gate"] = cmp["n_independent"] >= min_pairs and metrics.passes(
                    effect["delta_mean"], threshold, comparison)
                if cmp["n_independent"] < cmp["n_paired"]:
                    limitations.append(f"{cmp['n_paired']} pairs with {target['id']} are {cmp['n_independent']} "
                                       "independent repeats (shared independence fields)")
                gate_passed = entry["passes_gate"]
                guardrails_passed = all(g["passed"] for g in guard.values())
            comparisons[role] = entry
            pair_keys[role] = cmp["pair_keys"]
            edges.append({"target_id": target["id"], "role": role, "n_paired": cmp["n_paired"],
                          "delta_mean": effect["delta_mean"], "delta_sd": effect.get("delta_sd"),
                          "deltas": dict(entry["deltas"]), "passes_gate": entry.get("passes_gate")})
        outcome = reason = None
        if comparisons:  # against the parent's experiment below the top level, else the SOTA
            ref = comparisons.get("parent") or comparisons["sota"]
            outcome, reason = metrics.outcome(ref["delta_mean"], threshold, ref["n_independent"], min_pairs, comparison)
        participating = runs + [r for role in ("sota", "parent") if role in refs
                                for r in (tx.get(f"{refs[role]}/s{s}") for s in tx.get(refs[role])["seeds"])
                                if r is not None and r.get("valid") is True]
        self._check_protocol_runs(protocol, participating)
        imported = all(r.get("import_record") for r in participating)
        level = "legacy_unverified" if legacy else ("artifact_imported" if imported else "record_recomputed")
        if (protocol or {}).get("require_artifact_import") and level != "artifact_imported":
            missing = sorted(r["id"] for r in participating if not r.get("import_record"))
            raise MetricError("PROTOCOL_CHANGE_REQUIRED", f"the protocol requires imported results; not imported: "
                                                          f"{missing}")
        ceiling = metrics.EVAL_TYPE_LIMITS.get((protocol or {}).get("eval_type"))
        if ceiling:
            limitations.append(ceiling)
        public = {"verification_level": level, "metric_mean": per_metric.get(primary, {}).get("mean"),
                  "metric_sd": per_metric.get(primary, {}).get("sd"), "gate_passed": gate_passed,
                  "guardrails_passed": guardrails_passed,
                  "comparisons": {r: {k: c[k] for k in ("target_id", "n_paired", "delta_mean", "delta_sd", "deltas")}
                                  | ({"passes_gate": c["passes_gate"]} if "passes_gate" in c else {})
                                  for r, c in comparisons.items()}}
        public["outcome"] = outcome
        return {"outcome": outcome, "outcome_reason": reason, "stage": stage,
                "metrics": per_metric, "comparisons": comparisons, "edges": edges, "pair_keys": pair_keys,
                "gate_passed": gate_passed, "guardrails_passed": guardrails_passed, "primary": primary,
                "secondary": list(project["secondary_metrics"]),
                "eval_type": (protocol or {}).get("eval_type"), "limitations": limitations, "legacy": legacy,
                "verification_level": level,
                "artifact_refs": sorted({p for r in participating for p in (r.get("evidence_paths") or [])}),
                "public": public}

    def _check_protocol_runs(self, protocol: dict | None, runs: list[dict]) -> None:
        """Every run in a comparison meets the current protocol: its imported manifest has the settings the protocol
        fixes and the counts it requires. A protocol that fixes any is met only by imported runs."""
        match = (protocol or {}).get("match") or {}
        counts = (protocol or {}).get("required_counts") or {}
        if not (match or counts):
            return
        for run in runs:
            manifest = run.get("manifest")
            if not manifest:
                raise MetricError("PAIRING_MISMATCH", f"{run['id']} has no imported manifest, but the protocol fixes "
                                                      f"{sorted(match) + sorted(counts)}; import it (import_run_result)")
            wrong = [f"{k}={manifest.get(k)!r} (protocol {v!r})" for k, v in match.items() if manifest.get(k) != v]
            wrong += [f"counts.{k}={(manifest.get('counts') or {}).get(k)!r} (protocol {v})" for k, v in counts.items()
                      if (manifest.get("counts") or {}).get(k) != v]
            if wrong:
                raise MetricError("PAIRING_MISMATCH", f"{run['id']} does not meet the current protocol: "
                                                      f"{', '.join(wrong)}; it cannot join this comparison")

    def _check_result_claims(self, tx: _Tx, exp: dict, result_doc_id: str, computed: dict) -> None:
        """The result document of an evaluation speaks about this experiment: it cites every imported run's metrics
        file, and the summary numbers it states under the reserved claim ids (mean:<metric>, sd:<metric>,
        delta:<role>:<metric>) agree with the recomputed ones."""
        doc = tx.require(result_doc_id, ("document",))
        self._require_unchanged(doc)
        claims = claims_check.document_claims((self.docs_root / doc["path"]).read_text(encoding="utf-8")) or []
        cited = set()
        for c in claims:
            if isinstance(c, dict) and isinstance(c.get("source"), str):
                src = c["source"]
                cited.add(os.path.realpath(src if os.path.isabs(src) else self.db_path.parent / src))
        problems = []
        primary = f"mean:{computed['primary']}"
        if not any(isinstance(c, dict) and c.get("id") == primary for c in claims):
            problems.append(f"it states no {primary} (the primary metric's mean, checked against the recomputed one)")
        for seed in exp["seeds"]:
            run = tx.get(f"{exp['id']}/s{seed}")
            files = [self._research_path(p) for p in (run.get("evidence_paths") or [])[:1]]
            if files and files[0] not in cited:
                problems.append(f"{run['id']}'s metrics file {run['evidence_paths'][0]} is not cited")
        for c in claims:
            if not isinstance(c, dict) or not isinstance(c.get("id"), str):
                continue
            parts = c["id"].split(":")
            value = None
            if len(parts) == 2 and parts[0] in ("mean", "sd") and parts[1] in computed["metrics"]:
                value = computed["metrics"][parts[1]][parts[0]]
            elif len(parts) == 3 and parts[0] == "delta" and parts[1] in computed["comparisons"]:
                value = computed["comparisons"][parts[1]]["metrics"].get(parts[2], {}).get("delta_mean")
            else:
                continue
            if not metrics.matches_text(str(c.get("value")), value):
                problems.append(f"{c['id']} {c.get('value')!r} (recomputed {value})")
        if problems:
            raise CodedError("STAT_MISMATCH", f"result document {result_doc_id} ({doc['path']}) does not match "
                                              f"{exp['id']}: {'; '.join(problems)}")

    def _cross_check(self, computed: dict, expected: dict, exp: dict) -> None:
        """Numbers given by a caller of record_verdict against the recomputed ones (STAT_MISMATCH)."""
        problems = []
        primary = computed["metrics"].get(computed["primary"], {})
        for key, value in (("metric_mean", primary.get("mean")), ("metric_sd", primary.get("sd"))):
            if expected[key] is not None and not metrics.matches_given(expected[key], value):
                problems.append(f"{key} {expected[key]} (recomputed {value})")
        given = expected["comparisons"]
        if given:
            roles = {}
            for cmp in given:
                if not isinstance(cmp, dict) or set(cmp) - {"target_id", "role", "n_paired", "delta_mean",
                                                            "delta_sd", "deltas"}:
                    raise ResearchDBError(f"malformed comparison {cmp!r}")
                roles[cmp.get("role")] = cmp
            want = {r: c["target_id"] for r, c in computed["comparisons"].items()}
            if {r: c.get("target_id") for r, c in roles.items()} != want or len(roles) != len(given):
                raise ResearchDBError(f"comparisons must be exactly {want} (role -> target experiment)")
            for role, cmp in roles.items():
                mine = computed["comparisons"][role]
                if cmp.get("n_paired") != mine["n_paired"]:
                    problems.append(f"{role} pairs {mine['n_paired']} seeds, not {cmp.get('n_paired')}")
                for field in ("delta_mean", "delta_sd"):
                    if cmp.get(field) is not None and not metrics.matches_given(cmp[field], mine[field]):
                        problems.append(f"{role} {field} {cmp[field]} (recomputed {mine[field]})")
                deltas = cmp.get("deltas")
                if deltas is not None:
                    if not isinstance(deltas, dict):
                        raise ResearchDBError(f"{role} deltas must be an object")
                    for name, value in deltas.items():
                        if computed["legacy"] and name not in mine["deltas"]:
                            if not (_type_ok(value, "REAL") and math.isfinite(value)):
                                problems.append(f"{role} deltas.{name} is not a number")
                            continue
                        if name not in mine["deltas"] or not metrics.matches_given(value, mine["deltas"][name]):
                            problems.append(f"{role} deltas.{name} {value} (recomputed {mine['deltas'].get(name)})")
                    if computed["legacy"]:  # secondary deltas without a known direction: the caller's
                        if set(deltas) != set(computed["secondary"]):
                            raise ResearchDBError(f"deltas must give a number for each of {computed['secondary']}")
                        mine["deltas"] = {**deltas, **mine["deltas"]}
                        for edge in computed["edges"]:
                            if edge["role"] == role:
                                edge["deltas"] = dict(mine["deltas"])
        if problems:
            raise CodedError("STAT_MISMATCH", f"{exp['id']}: the numbers given differ from the ones recomputed from "
                                              f"its runs: {'; '.join(problems)}. The interface computes them; pass "
                                              "none, or call evaluate_experiment")

    def _check_harness(self, project: dict, exp: dict) -> None:
        repo, harness = project["repo_path"], project["harness_ref"]
        if not _git_ok(repo, "merge-base", "--is-ancestor", harness, exp["code_ref"]):
            raise ResearchDBError(f"{exp['id']}: code_ref does not contain the frozen harness {harness}")
        if not _git_ok(repo, "diff", "--quiet", harness, exp["code_ref"], "--", *project["harness_paths"]):
            raise ResearchDBError(f"{exp['id']}: the harness/statistics files differ from the frozen harness")

    def _check_verdict(self, project: dict, exp: dict, verdict: str, edges: list[dict]) -> None:
        by_role = {e["role"]: e for e in edges}
        parent = by_role.get("parent", by_role["sota"])  # top-level nodes compare with SOTA as their parent
        # an effect that could not be computed (None) does not count as better
        no_better = parent["delta_mean"] <= 0 and all(v is None or v <= 0 for v in parent["deltas"].values())
        if (verdict == "no_gain") != no_better:
            raise ResearchDBError("verdict no_gain applies exactly when no metric is better than the parent")
        if verdict == "beats_parent" and parent["delta_mean"] <= 0:
            raise ResearchDBError("beats_parent needs a positive primary-metric difference to the parent")
        gate = by_role["sota"]["passes_gate"]
        if verdict == "beats_sota" and not gate:
            raise ResearchDBError(
                f"beats_sota needs {project['gate_seeds']} paired seeds and a primary lead over the minimum practical "
                "gain (the metric specification's; go_margin without one)"
            )
        if gate and verdict not in ("beats_sota", "needs_rld"):
            raise ResearchDBError("the SOTA gate is passed; the verdict is beats_sota or needs_rld")

    def _latest_evaluated(self, tx: _Tx, hypothesis_id: str) -> dict | None:
        """The node's most recent method experiment evaluated with the current harness."""
        harness = self._project(tx)["harness_ref"]
        rows = tx.query("MATCH (e:Experiment)-[:TESTS]->(h:Hypothesis {id: $id}) RETURN e.id AS id", id=hypothesis_id)
        exps = [tx.get(r["id"]) for r in rows]
        exps = [e for e in exps if e["kind"] == "method" and e.get("evaluated_at") and e.get("harness_ref") == harness
                and (e.get("stage") or "screen") != "confirm"]
        return max(exps, key=lambda e: int(e["id"].split("-")[1]), default=None)

    def latest_result(self, hypothesis_id: str) -> dict | None:
        """The hypothesis's latest evaluated experiment under the current harness, or None."""
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
        """Register a written file under docs/ (path <name>.v<N>.md/.json/.yaml) as a draft; set_document_current
        then freezes it. Who may author which doc_type is fixed (doc_library.md)."""
        m = DOC_PATH_RE.match(path)
        if not m:
            raise ResearchDBError(f"document path must be relative, without '..', and end in .v<N>.md, .v<N>.json or .v<N>.yaml: {path}")
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
        """Change a draft document's title or summary; its author only."""
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
            self._check_content(doc)
            if doc["doc_type"] in ("experiment_result", "report"):
                self._check_wording(tx, doc)
            digest = sha256_file(self.docs_root / doc["path"])
            self._update(tx, doc_id, {"status": "current", "sha256": digest})
            return digest

    def _check_wording(self, tx: _Tx, doc: dict) -> None:
        """03 §5 / 04 §6: a proxy evaluation bounds the claim — no SOTA wording on synthetic or self-supervised
        proxies or simulations (only 'proxy agreement' / relative improvement)."""
        projects = tx.ids("project")
        if not projects:
            return
        eval_type = (self._protocol(tx, tx.get(projects[0])) or {}).get("eval_type")
        if eval_type not in PROXY_EVAL_TYPES:
            return
        text = (self.docs_root / doc["path"]).read_text(encoding="utf-8")
        text = BLOCK_RE_EVIDENCE.sub("", text)
        found = SOTA_CLAIM_RE.search(text)
        if found:
            raise CodedError("CLAIM_EXCEEDS_EVAL_TYPE", f"{doc['id']} ({doc['path']}) says {found.group(0)!r}, but the "
                                                        f"evaluation type is {eval_type}: a proxy result supports "
                                                        "'agreement on the proxy' or a relative improvement only; "
                                                        "write a new version within that limit")

    def _require_unchanged(self, doc: dict) -> None:
        path = self.docs_root / doc["path"]
        if doc["status"] != "draft" and (not path.is_file() or sha256_file(path) != doc.get("sha256")):
            raise ResearchDBError(f"{doc['id']} ({doc['path']}) no longer matches its recorded hash: a frozen document "
                                  "is not edited in place; write a new version")

    def _check_content(self, doc: dict) -> None:
        """What is checked before a document is frozen: a metric specification or protocol is well formed; the
        numbers an experiment result (or a report with an evidence block) cites appear in the files it cites."""
        path = self.docs_root / doc["path"]
        if doc["doc_type"] in ("metric_spec", "protocol"):
            if not doc["path"].endswith(".json"):
                raise ResearchDBError(f"a {doc['doc_type']} document is JSON (.v<N>.json)")
            content = _read_json(path, doc["doc_type"])
            with _coded():
                (metrics.check_metric_specs if doc["doc_type"] == "metric_spec" else metrics.check_protocol)(content)
        if doc["doc_type"] not in ("experiment_result", "report"):
            return
        claims = claims_check.document_claims(path.read_text(encoding="utf-8"))
        if claims is None:
            if doc["doc_type"] == "experiment_result":
                raise CodedError("STAT_MISMATCH", f"{doc['id']} ({doc['path']}) cites no numbers: an experiment "
                                                  "result lists each number it reports with its source file in an "
                                                  "```evidence block, e.g. [{\"id\": \"acc-s42\", \"value\": "
                                                  "\"0.9075\", \"source\": \"outputs/E-0002/s42/metrics.json\"}]")
            return
        if not claims:
            raise CodedError("STAT_MISMATCH", f"{doc['id']}: the evidence block lists no claim")
        checked = claims_check.check_batch(claims, self.db_path.parent, self.project_dir, forbidden=self.docs_root)
        bad = [r for r in checked["results"] if r["status"] != "verified"]
        if bad:
            raise CodedError("STAT_MISMATCH", f"{doc['id']} ({doc['path']}): numbers not found in their sources: " +
                             "; ".join(f"{r.get('id', '?')} {r.get('value')!r} in {r.get('source')!r}: {r['status']}"
                                       for r in bad[:10]))

    def supersede_document(self, old_id: str, new_id: str) -> None:
        """Mark a current document superseded by a newer current one of the same doc_type."""
        with self._writer() as tx:
            old = tx.require(old_id, ("document",))
            new = tx.require(new_id, ("document",))
            self._require_author(new)
            if "review" in (old["doc_type"], new["doc_type"]) and self.role != "reviewer":
                raise PermissionDenied("reviews are versioned only by review_call.py (a new review in the session)")
            if (old["status"], new["status"]) != ("current", "current"):
                raise ResearchDBError("both documents must be current; the old one becomes superseded")
            if old["doc_type"] != new["doc_type"]:
                raise ResearchDBError(f"cannot supersede a {old['doc_type']} with a {new['doc_type']}")
            self._update(tx, old_id, {"status": "superseded"})
            tx.link("rel_supersedes", new_id, old_id)

    def register_review(self, path: str, title: str, kind: str, about: list[str] | tuple[str, ...], result: str,
                        session: str, backend: str, reviewer_model: str, cost_usd: float,
                        dimension: str | None = None, evaluation_id: str | None = None,
                        supersedes: str | None = None, summary: str | None = None, code_ref: str | None = None) -> str:
        """reviewer only (review_call.py, plans/design 09 §2.1 step 7): register a written review as current, with
        its kind, result, backend and observed model. A candidate_recheck names its dimension and the evaluation it
        checked; it is bound to that evaluation and its code. A code_review names code_ref, the commit it read.
        supersedes: the earlier review of the same session
        (a follow-up round writes a new version). The cost is added to the project's review_cost_usd."""
        self._require_role("reviewer")
        m = DOC_PATH_RE.match(path)
        if not m or not path.startswith("reviews/"):
            raise ResearchDBError(f"a review is written under reviews/ as <name>.v<N>.md: {path}")
        if kind not in REVIEW_KINDS:
            raise ResearchDBError(f"kind is one of {REVIEW_KINDS}")
        if backend not in ("pi", "claude_code"):
            raise ResearchDBError("backend is pi or claude_code")
        if not isinstance(cost_usd, (int, float)) or isinstance(cost_usd, bool) or cost_usd < 0:
            raise ResearchDBError("cost_usd is a number >= 0")
        file = self.docs_root / path
        if not file.is_file():
            raise ResearchDBError(f"document file not found: {file}")
        with self._writer() as tx:
            project = self._project(tx)
            if tx.ids("document", "WHERE n.path = $path", path=path):
                raise ResearchDBError(f"{path} is already registered")
            candidates = [a for a in about if CANDIDATE_ID_RE.fullmatch(a)]
            if len(candidates) > 1 or (candidates and len(about) > 1):
                raise ResearchDBError("a review is about one discovery candidate, or about database entities")
            if candidates and kind == "candidate_recheck":
                raise ResearchDBError("a candidate_recheck is about a node, not a discovery candidate")
            targets = [tx.require(entity) for entity in about if entity not in candidates]
            fields = {}
            if kind == "candidate_recheck":
                if dimension not in RECHECK_DIMENSIONS:
                    raise ResearchDBError(f"a candidate_recheck names its dimension: one of {list(RECHECK_DIMENSIONS)}")
                if result not in ("pass", "fail", "uncertain", "not_applicable"):
                    raise ResearchDBError("a candidate_recheck result is pass, fail, uncertain or not_applicable")
                ev = tx.require(evaluation_id, ("evaluation",))
                exp = tx.get(ev["experiment_id"])
                if [t["id"] for t in targets] != [exp.get("hypothesis_id")]:
                    raise ResearchDBError(f"a candidate_recheck is about the node of {evaluation_id}: "
                                          f"{exp.get('hypothesis_id')}")
                fields = {"review_dimension": dimension, "basis_evaluation_id": ev["id"],
                          "basis_code_ref": exp["code_ref"]}
            elif dimension or evaluation_id:
                raise ResearchDBError("dimension and evaluation_id belong to a candidate_recheck")
            if kind == "code_review":  # bound to the code it read (03 §8): a submission checks the same commit
                resolved = _git_commit(project.get("repo_path") or "", code_ref or "") if code_ref else None
                if resolved is None:
                    raise ResearchDBError(f"a code_review names code_ref, a commit in {project.get('repo_path')}")
                fields["basis_code_ref"] = resolved
            elif code_ref:
                raise ResearchDBError("code_ref belongs to a code_review")
            previous = None
            if supersedes:
                previous = tx.require(supersedes, ("document",))
                if (previous["doc_type"], previous.get("review_session"), previous["status"]) != ("review", session, "current"):
                    raise ResearchDBError(f"{supersedes} is not the current review of session {session}")
            doc_id = self._insert(tx, "document", {
                "id": tx.next_id("document"), "path": path, "version": int(m.group(1)), "doc_type": "review",
                "title": title, "summary": summary, "status": "current", "author_role": self.role,
                "author_id": self.agent, "sha256": sha256_file(file), "review_kind": kind, "review_result": result,
                "review_backend": backend, "reviewer_model": reviewer_model, "review_session": session,
                "review_about": candidates[0] if candidates else None, **fields})
            for entity in about:
                if entity not in candidates:
                    tx.link("rel_describes", doc_id, entity)
            if previous:
                self._update(tx, previous["id"], {"status": "superseded"})
                tx.link("rel_supersedes", doc_id, previous["id"])
            self._update(tx, project["id"], {"review_cost_usd": round((project.get("review_cost_usd") or 0) + cost_usd, 6)})
            return doc_id

    def add_review_cost(self, cost_usd: float) -> None:
        """reviewer only (review_call.py): a failed or invalid call's cost, so the project's review cost is the one
        the review_usd_alert gate counts."""
        self._require_role("reviewer")
        if not isinstance(cost_usd, (int, float)) or isinstance(cost_usd, bool) or cost_usd < 0:
            raise ResearchDBError("cost_usd is a number >= 0")
        with self._writer() as tx:
            project = self._project(tx)
            self._update(tx, project["id"], {"review_cost_usd": round((project.get("review_cost_usd") or 0) + cost_usd, 6)})

    def reviews(self, about: str | None = None, kind: str | None = None) -> list[dict]:
        """Review documents (current and superseded), oldest first, optionally of one entity or kind."""
        with self.reader() as tx:
            docs = [tx.get(i) for i in tx.ids("document", "WHERE n.doc_type = $t", t="review")]
            if about:
                docs = [d for d in docs if d.get("review_about") == about
                        or tx.edges("rel_describes", source=d["id"], target=about)]
        out = [{k: v for k, v in d.items() if k != "_table"} for d in docs if not kind or d.get("review_kind") == kind]
        return sorted(out, key=lambda d: int(d["id"].split("-")[1]))

    def _candidate_rechecks(self, tx: _Tx, hyp: dict, evaluation_id: str, basis_exp: dict) -> tuple[list[dict], list[str]]:
        """The node's latest current candidate_recheck per dimension and why the GO bar is not met yet."""
        docs = [tx.get(i) for i in tx.ids("document", "WHERE n.doc_type = $t", t="review")]
        docs = [d for d in docs if d["status"] == "current" and d.get("review_kind") == "candidate_recheck"
                and tx.edges("rel_describes", source=d["id"], target=hyp["id"])]
        rows, reasons = [], []
        for dimension, binding in RECHECK_DIMENSIONS.items():
            mine = [d for d in docs if d.get("review_dimension") == dimension]
            if not mine:
                rows.append({"dimension": dimension, "state": "missing", "required": evaluation_id
                             if binding == "evaluation" else basis_exp["code_ref"]})
                reasons.append("RECHECK_PENDING")
                continue
            d = max(mine, key=lambda x: int(x["id"].split("-")[1]))
            bound = (d.get("basis_evaluation_id") == evaluation_id if binding == "evaluation"
                     else d.get("basis_code_ref") == basis_exp["code_ref"])
            state = ("stale" if not bound else {"pass": "pass", "not_applicable": "pass", "fail": "failed",
                                                "uncertain": "uncertain"}[d["review_result"]])
            rows.append({"dimension": dimension, "state": state, "required": evaluation_id if binding == "evaluation"
                         else basis_exp["code_ref"], "review_id": d["id"], "path": d["path"],
                         "result": d["review_result"], "backend": d.get("review_backend"),
                         "reviewer_model": d.get("reviewer_model"), "evaluation_id": d.get("basis_evaluation_id"),
                         "code_ref": d.get("basis_code_ref")})
            reasons += {"stale": ["RECHECK_STALE"], "failed": ["RECHECK_FAILED"],
                        "uncertain": ["RECHECK_UNCERTAIN"]}.get(state, [])
        return rows, reasons

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

    def create_branch(self, hypothesis_id: str, name: str, base_ref: str, base_commit: str, worktree_path: str,
                      owner: str | None = None) -> str:
        """The branch lives in the project's code repository (project.repo_path); its owner is the node's
        worker unless given."""
        self._require_role("rld")
        with self._writer() as tx:
            owner = owner or tx.require(hypothesis_id, ("hypothesis",)).get("worker_id")
            if not owner:
                raise ResearchDBError(f"assign {hypothesis_id} a worker (assign_worker) or pass owner")
            if self._branch_of(tx, hypothesis_id) is not None:
                raise ResearchDBError(f"{hypothesis_id} already has a branch")
            self._require_active(self._project(tx))
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
                raise _not_allowed("branch", branch["status"], to_status, allowed.get(branch["status"], ()))
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

    # -- node workers -----------------------------------------------------------------------
    # One node, one worker identity (worker/<worker_id>), responsible from start to completion. The current
    # agent session is recorded so the RLD can continue it (SendMessage); when it cannot be continued, a new
    # session with the same identity takes over from the node's resume documents.

    def assign_worker(self, node_id: str, worker_id: str | None = None) -> str:
        """Give a node (hypothesis, or the project as the root) its worker identity; set once."""
        self._require_role("rld")
        with self._writer() as tx:
            node = tx.require(node_id, ("hypothesis", "project"))
            wanted = worker_id or default_worker_id(node_id, node["_table"])
            if not re.fullmatch(r"[A-Za-z0-9_.]+", wanted):
                raise ResearchDBError(f"worker id must be letters, digits, _ or ., got {wanted!r}")
            if node.get("worker_id") and node["worker_id"] != wanted:
                raise ResearchDBError(f"{node_id} already belongs to worker/{node['worker_id']}")
            taken = [n["id"] for t in ("hypothesis", "project") for n in (tx.get(i) for i in tx.ids(t))
                     if n.get("worker_id") == wanted and n["id"] != node_id]
            if taken:
                raise ResearchDBError(f"worker/{wanted} already works on {taken[0]}")
            if not node.get("worker_id"):
                tx.set(node_id, {"worker_id": wanted})
            return wanted

    def bind_worker_session(self, node_id: str, agent_id: str) -> None:
        """Record the agent session now working as the node's worker (a new one replaces the old)."""
        self._require_role("rld")
        with self._writer() as tx:
            node = tx.require(node_id, ("hypothesis", "project"))
            if not node.get("worker_id"):
                raise ResearchDBError(f"assign {node_id} a worker before binding a session")
            self._check_values(node["_table"], {"worker_agent_id": agent_id})
            tx.set(node_id, {"worker_agent_id": agent_id, "worker_session_at": now_utc()})

    def add_resume_docs(self, node_id: str, doc_ids: list[str]) -> list[str]:
        """Add documents a new worker session needs to take over the node; rld or the node's worker."""
        with self._writer() as tx:
            node = tx.require(node_id, ("hypothesis", "project"))
            if self.role != "rld" and (self.role, self.agent) != ("worker", node.get("worker_id")):
                raise PermissionDenied(f"only rld or worker/{node.get('worker_id')} adds resume documents to {node_id}")
            for doc_id in doc_ids:
                tx.require(doc_id, ("document",))
            return self._append_resume(tx, node_id, doc_ids)

    def _append_resume(self, tx: _Tx, node_id: str, doc_ids: list[str]) -> list[str]:
        current = list(tx.get(node_id).get("resume_doc_ids") or [])
        merged = current + [d for d in doc_ids if d not in current]
        if merged != current:
            tx.set(node_id, {"resume_doc_ids": merged})
        return merged

    def resume_package(self, node_id: str) -> dict:
        """What a worker session needs to take over a node: identity, the session to continue, the resume
        documents at their current versions, the node's tasks, experiments, branch and comparison context."""
        with self.reader() as tx:
            node = tx.require(node_id, ("hypothesis", "project"))
            docs = []
            for doc_id in node.get("resume_doc_ids") or []:
                current = doc_id
                while newer := tx.edges("rel_supersedes", target=current):
                    current = newer[0]["source_id"]
                doc = tx.get(current)
                docs.append({"id": current, "path": doc["path"], "title": doc["title"], "doc_type": doc["doc_type"],
                             "status": doc["status"], "listed_as": doc_id})
            tasks = [{k: t.get(k) for k in ("id", "kind", "status", "assignee_id", "request_doc_id", "delivery_doc_id")}
                     for t in (tx.get(i) for i in tx.ids("task")) if t.get("target_id") == node_id]
            pending = sorted((t for t in tasks if t["status"] not in ("accepted", "cancelled")),
                             key=lambda t: int(t["id"].split("-")[1]))
            package = {
                "first_unaccepted_task": pending[0]["id"] if pending else None,
                "node": {k: v for k, v in node.items() if k != "_table"},
                "worker": f"worker/{node['worker_id']}" if node.get("worker_id") else None,
                "agent_id": node.get("worker_agent_id"), "session_at": node.get("worker_session_at"),
                "documents": docs, "tasks": tasks,
            }
            if node["_table"] == "hypothesis":
                exps = [tx.get(r["id"]) for r in tx.query(
                    "MATCH (e:Experiment)-[:TESTS]->(h:Hypothesis {id: $id}) RETURN e.id AS id", id=node_id)]
                package["experiments"] = [{k: e.get(k) for k in ("id", "kind", "seeds", "verdict", "code_ref",
                                                                  "result_doc_id")} for e in exps]
                branch = self._branch_of(tx, node_id)
                package["branch"] = branch and {k: branch.get(k) for k in ("id", "name", "status", "base_commit",
                                                                            "worktree_path", "head_commit")}
                latest = self._latest_evaluated(tx, node_id)
                package["latest_result"] = latest and latest["id"]
                parent = node.get("parent_id")
                if parent and table_of(parent) == "hypothesis":
                    ref = self._latest_evaluated(tx, parent)
                    package["parent_result"] = ref and {"id": ref["id"], "result_doc_id": ref.get("result_doc_id")}
            else:
                package["baselines"] = [{k: e.get(k) for k in ("id", "seeds", "code_ref", "result_doc_id", "evaluated_at")}
                                        for e in (tx.get(i) for i in tx.ids("experiment")) if e["kind"] == "baseline"]
            return package

    # -- cleanup --------------------------------------------------------------------------
    # The project's script (research-tree-cleanup.py) says which files of a run are disposable and deletes them;
    # this interface decides when an experiment is due, checks the script's plan and keeps the ledger.

    def cleanup_due(self, node_id: str | None = None) -> list[dict]:
        """Experiments whose outputs are due for cleanup (optionally of one node): evaluated since their last
        cleanup, of a concluded node without a verdict, or with kept outputs now released. Each lists its
        runs (earlier attempts too) with their output directories and evidence, and the classes still kept."""
        with self.reader() as tx:
            return [d for d in self._cleanup_due(tx) if node_id in (None, d["node"])]

    def _cleanup_due(self, tx: _Tx) -> list[dict]:
        project = self._project(tx)
        hyps = {h["id"]: h for h in (tx.get(i) for i in tx.ids("hypothesis"))}
        all_pruned = bool(hyps) and all(h["status"] == "prunable" for h in hyps.values())
        users = tx.edges("rel_depends_on")
        runs_of: dict[str, list[dict]] = {}
        for run in (tx.get(i) for i in tx.ids("run")):
            runs_of.setdefault(run["experiment_id"], []).append(run)
        due = []
        for exp in (tx.get(i) for i in tx.ids("experiment")):
            runs = runs_of.get(exp["id"], [])
            if not runs or any(r["exec_status"] not in FINAL_EXEC for r in runs):
                continue
            cited = self._cited_sources(tx, exp.get("result_doc_id"))
            hyp = hyps.get(exp.get("hypothesis_id"))
            passes = exp.get("cleanup") or {}
            last = passes[max(passes, key=int)] if passes else None
            covered = {name for p in passes.values() for name in p.get("covered", [])}
            released = (hyp["status"] == "prunable" if hyp else all_pruned) and all(
                tx.get(u["source_id"]).get("evaluated_at") for u in users if u["target_id"] == exp["id"])
            keep = [] if released else list(exp.get("keep") or [])
            # Every attempt of every run, named <run>@<attempt>; a pass covers the ones it cleaned.
            entries = []
            for run in sorted(runs, key=lambda r: r["seed"]):
                attempts = [(run["attempt"], run)] + [(int(n), a) for n, a in (run.get("attempts") or {}).items()]
                for n, a in sorted(attempts, key=lambda x: x[0]):
                    # evidence: the log and curve, the manifest and what an evaluation is recomputed from
                    kept = [a.get(k) for k in ("log_path", "curve_path", "manifest_path")] + list(a.get("evidence_paths") or [])
                    out_dir = self._research_path(a.get("output_path"))
                    entries.append({"run": f"{run['id']}@{n}", "output_dir": out_dir,
                                    "evidence": [p for p in (self._research_path(k) for k in kept) if p]
                                    + [c for c in cited if out_dir and Path(c).is_relative_to(out_dir)]})
            uncovered = any(e["run"] not in covered for e in entries)
            if exp.get("evaluated_at") and uncovered:
                reason = "statistics recorded"
            elif not exp.get("evaluated_at") and hyp and hyp.get("concluded_at") and uncovered:
                reason = "node concluded without a verdict for it"
            elif last is not None and last.get("kept") and not keep:
                reason = "kept outputs released"
            else:
                continue
            due.append({"experiment_id": exp["id"], "node": exp.get("hypothesis_id") or project["id"], "owner": exp["owner"],
                        "reason": reason, "keep": keep, "runs": entries})
        return due

    def _cited_sources(self, tx: _Tx, doc_id: str | None) -> list[str]:
        """The files a result document cites as sources: evidence, whatever their names."""
        doc = tx.get(doc_id) if doc_id else None
        path = self.docs_root / doc["path"] if doc else None
        if path is None or not path.is_file():
            return []
        claims = claims_check.document_claims(path.read_text(encoding="utf-8")) or []
        return [os.path.realpath(c["source"] if os.path.isabs(c["source"]) else self.db_path.parent / c["source"])
                for c in claims if isinstance(c, dict) and isinstance(c.get("source"), str)]

    def _research_path(self, path: str | None) -> str | None:
        """A recorded path as an absolute one: relative paths are relative to the research root (research/<id>/)."""
        if not path:
            return None
        return os.path.realpath(path if os.path.isabs(path) else self.db_path.parent / path)

    def run_cleanup(self, experiment_id: str, dry_run: bool = False) -> dict:
        """Clean a due experiment's outputs with the project's research-tree-cleanup.py: its owner (or rld), right
        after evaluate_experiment and before delivering. The script plans what to delete; every item must lie inside
        its run's output directory, hold no evidence (log, curve) and be of a class the experiment does not keep.
        Then the script deletes them and the result is recorded in the experiment's cleanup ledger. dry_run
        returns the checked plan only. A missing script is first copied from the plugin's template."""
        with self.reader() as tx:
            exp = tx.require(experiment_id, ("experiment",))
            self._require_owner(exp)
            entry = next((d for d in self._cleanup_due(tx) if d["experiment_id"] == experiment_id), None)
        if entry is None:
            raise ResearchDBError(f"{experiment_id} has no cleanup due: it is due once its statistics are recorded "
                                  "(evaluate_experiment) and all its runs are finished")
        script = self.project_dir / CLEANUP_SCRIPT
        if not script.is_file():
            shutil.copyfile(CLEANUP_TEMPLATE, script)
            raise ResearchDBError(f"copied the cleanup template to {script}: adapt its CLASSES to what this project's "
                                  "runs write, preview with dry_run=true, then run run_cleanup again")
        located = [r for r in entry["runs"] if r["output_dir"] and os.path.isdir(r["output_dir"])]
        unlocated = [r["run"] for r in entry["runs"] if r not in located]
        items = self._checked_plan(entry, located, _cleanup_script(script, "plan", {"runs": located, "keep": entry["keep"]}))
        result = {"experiment_id": experiment_id, "reason": entry["reason"], "kept": entry["keep"],
                  "unlocated": unlocated, "items": items}
        if dry_run:
            return {**result, "planned_bytes": sum(i["bytes"] for i in items)}
        done = _cleanup_script(script, "delete", {"items": items}).get("items")
        if not isinstance(done, list) or sorted(i.get("path", "") for i in done) != sorted(i["path"] for i in items):
            raise ResearchDBError(f"{CLEANUP_SCRIPT} delete must answer each approved item once; check the files and "
                                  "the script, then run run_cleanup again")
        freed = sum(i["bytes"] for i in done if i.get("action") == "deleted")
        with self._writer() as tx:
            passes = dict(tx.require(experiment_id, ("experiment",)).get("cleanup") or {})
            passes[str(len(passes) + 1)] = {
                "at": now_utc(), "by": f"{self.role}/{self.agent}", "reason": entry["reason"], "kept": entry["keep"],
                "freed_bytes": freed, "unlocated": unlocated, "items": done, "covered": [r["run"] for r in entry["runs"]],
                "failed": sum(i.get("action") != "deleted" for i in done)}
            self._update(tx, experiment_id, {"cleanup": passes})
        return {**result, "items": done, "freed_bytes": freed}

    def _checked_plan(self, entry: dict, located: list[dict], plan: dict) -> list[dict]:
        runs = {r["run"]: r for r in located}
        items, seen = [], set()
        for item in plan.get("items", []) if isinstance(plan, dict) else [None]:
            if not isinstance(item, dict) or set(item) != {"run", "path", "class", "bytes"} or not isinstance(item["bytes"], int):
                raise ResearchDBError(f"{CLEANUP_SCRIPT} plan items are {{run, path, class, bytes}}; got {item!r}")
            run = runs.get(item["run"])
            path = os.path.realpath(item["path"])
            problem = (
                "not one of the runs given" if run is None
                else "outside the run's output directory" if not Path(path).is_relative_to(run["output_dir"]) or path == run["output_dir"]
                else "holds evidence (log or curve)" if any(e == path or Path(e).is_relative_to(path) for e in run["evidence"])
                else f"of the kept class {item['class']}" if item["class"] in entry["keep"] or item["class"] == "evidence"
                else "listed twice" if path in seen else None)
            if problem:
                raise ResearchDBError(f"{CLEANUP_SCRIPT} planned {item['path']}, which is {problem}; fix the script, "
                                      "preview with dry_run=true, then run run_cleanup again")
            seen.add(path)
            items.append({**item, "path": path})
        return items

    # -- tasks ----------------------------------------------------------------------------

    def create_task(self, kind: str, assignee_role: str, request_doc_id: str, target_id: str | None = None,
                    assignee_id: str | None = None) -> str:
        """A delegated task (status open), optionally assigned to <assignee_role>/<assignee_id>; rld only.
        The request document has the '## ' sections 任务与节点, 问题与预测, 干预与对照, 范围与权限, 资源与预算,
        验收与停止条件, 交付. Research tasks (harness, literature, experiment, analysis) start only while the project
        is active."""
        self._require_role("rld")
        with self._writer() as tx:
            if kind in RESEARCH_TASK_KINDS:
                self._require_active(self._project(tx))
            self._check_sections(tx, request_doc_id)
            if assignee_role == "worker" and assignee_id:
                self._check_parallel_workers(tx, assignee_id)
            task_id = self._insert(tx, "task", {
                "id": tx.next_id("task"), "kind": kind, "target_id": target_id, "status": "open",
                "assignee_role": assignee_role, "assignee_id": assignee_id, "request_doc_id": request_doc_id,
            }, current_docs=True)
            if target_id and table_of(target_id) in ("hypothesis", "project"):
                self._append_resume(tx, target_id, [request_doc_id])
            return task_id

    def update_task(self, task_id: str, status: str | None = None, delivery_doc_id: str | None = None,
                    assignee_id: str | None = None, evidence_ids: list[str] | None = None) -> None:
        """Move a task along open -> in_progress -> delivered -> accepted/rejected (rejected -> in_progress again;
        rld may cancel). The assignee starts and delivers; delivered needs delivery_doc_id in the same call; rld
        accepts, rejects, cancels and (while open) assigns with assignee_id. The delivery document has the '## '
        sections 实际改动与版本, 运行与产物, 验证结果, 资源观测, 未完成与未知项, and the node's due cleanups
        are done first (run_cleanup)."""
        with self._writer() as tx:
            task = tx.require(task_id, ("task",))
            changes = {}
            if assignee_id is not None:
                self._require_role("rld")
                if task["status"] != "open":
                    raise ResearchDBError("a task is (re)assigned only while open")
                if task["assignee_role"] == "worker":
                    self._check_parallel_workers(tx, assignee_id, task_id)
                changes["assignee_id"] = assignee_id
            if status is not None:
                who = TASK_TRANSITIONS[task["status"]].get(status)
                if who is None:
                    raise _not_allowed("task", task["status"], status,
                                       [f"{to} ({who})" for to, who in TASK_TRANSITIONS[task["status"]].items()])
                if who == "rld":
                    self._require_role("rld")
                elif (self.role, self.agent) != (task["assignee_role"], task.get("assignee_id")):
                    raise PermissionDenied(f"only the assignee {task['assignee_role']}/{task.get('assignee_id')} may do this")
                changes["status"] = status
                if status == "accepted":
                    # done is not accepted: acceptance names what it checked (13 §2.1, ARIS run_state.accept)
                    items = [tx.require(i, ("evaluation", "decision", "document", "experiment"))
                             for i in evidence_ids or []]
                    if not items:
                        raise ResearchDBError("accepting a task needs evidence_ids: the evaluation, decision or "
                                              "document the acceptance checked")
                    if any(i["_table"] == "document" and i["status"] != "current" for i in items):
                        raise ResearchDBError("evidence documents must be current")
                    accepter = f"{self.role}/{self.agent}"
                    if accepter == f"{task['assignee_role']}/{task.get('assignee_id')}":
                        raise PermissionDenied("the assignee does not accept its own task")
                    changes.update(accepted_by=accepter, accepted_evidence=[i["id"] for i in items])
            elif evidence_ids:
                raise ResearchDBError("evidence_ids go with status accepted")
            if delivery_doc_id is not None:
                if status != "delivered":
                    raise ResearchDBError("delivery_doc_id is set together with status delivered")
                self._check_sections(tx, delivery_doc_id)
                waiting = [d["experiment_id"] for d in self._cleanup_due(tx) if d["node"] == task.get("target_id")]
                if waiting:
                    raise ResearchDBError(f"clean up first: {', '.join(waiting)} (run_cleanup), then deliver")
                changes["delivery_doc_id"] = delivery_doc_id
            elif status == "delivered":
                raise ResearchDBError("delivering a task needs delivery_doc_id")
            if not changes:
                raise ResearchDBError("nothing to change")
            self._update(tx, task_id, changes, current_docs=True)
            target = task.get("target_id")
            if delivery_doc_id is not None and target and table_of(target) in ("hypothesis", "project"):
                self._append_resume(tx, target, [delivery_doc_id])

    def _check_sections(self, tx: _Tx, doc_id: str) -> None:
        """A task request or delivery has its required '## ' sections (未知 or 不适用 where nothing applies)."""
        doc = tx.require(doc_id, ("document",))
        required = TASK_SECTIONS.get(doc["doc_type"], ())
        path = self.docs_root / doc["path"]
        headings = re.findall(r"^#{2,3}[ \t]+(.+?)[ \t]*$", path.read_text(encoding="utf-8"), re.M) if path.is_file() else []
        missing = [r for r in required if not any(h.startswith(r) for h in headings)]
        if missing:
            raise ResearchDBError(f"{doc_id} ({doc['path']}) lacks the sections {', '.join(missing)}; a {doc['doc_type']} "
                                  f"has the '## ' sections {', '.join(required)} (未知 or 不适用 where nothing applies): "
                                  "write a new version with them")

    def _check_parallel_workers(self, tx: _Tx, worker_id: str, task_id: str | None = None) -> None:
        """A worker with no task in hand may take one only while fewer than max_parallel_workers have one."""
        limit = self._project(tx).get("max_parallel_workers")
        if limit is None:
            return
        busy = busy_workers([tx.get(i) for i in tx.ids("task") if i != task_id])
        if worker_id not in busy and len(busy) >= limit:
            raise ResearchDBError(f"max_parallel_workers is {limit} and worker/{', worker/'.join(sorted(busy))} "
                                  "already have tasks in hand; wait for a delivery or raise the limit in research-tree.yaml")

    # -- reads ------------------------------------------------------------------------------

    def get(self, entity_id: str) -> dict | None:
        """One record by id (H-0001, E-0002, D-0003, T-0004, the project id, ...) with its properties, or None."""
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
        """Relations of type rel (e.g. rel_compared_with), optionally from source_id and/or to target_id."""
        if rel not in REL_ENDPOINTS:
            raise ResearchDBError(f"unknown relation {rel!r}")
        with self.reader() as tx:
            return tx.edges(rel, source_id, target_id)

    def children(self, parent_id: str) -> list[str]:
        """Ids of the hypotheses whose parent is parent_id (the project id for the top level)."""
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
        """Hypotheses eligible for GO now (get_eligibility): current evidence that passes the gate and guardrails,
        and both rechecks bound to that evidence's code."""
        with self.reader() as tx:
            project = self._project(tx)
            return [i for i in tx.ids("hypothesis") if self._eligibility(tx, project, tx.get(i))["eligible"]]

    def get_eligibility(self, hypothesis_id: str, protocol_id: str | None = None) -> dict:
        """Whether a hypothesis may support GO now, computed from its evaluations, never from cached labels
        (plans/design 05 §3.3): {eligible, basis_evaluation_id, experiment_id, evidence_state (none, current,
        stale), reasons, verification_level, gate_passed, guardrails_passed}. The basis is the node's latest
        evaluation; reasons name what is missing or no longer applies (HARNESS_CHANGED, BASELINE_CHANGED,
        PROTOCOL_CHANGED, METRIC_SPEC_CHANGED, STATISTICS_CHANGED, RUN_RETRACTED, INPUT_CHANGED,
        RESULT_REVISION_PENDING, LEGACY_RESULT_UNVERIFIED, EVAL_TYPE_MISSING, GATE_NOT_PASSED, GUARDRAIL_FAILED,
        OBLIGATION_OPEN, DISPOSITION_RETIRED, RECHECK_PENDING, RECHECK_FAILED, RECHECK_STALE, RECHECK_UNCERTAIN,
        CONFIRMATION_REQUIRED,
        CONFIRMATION_FAILED, CONFIRMATION_REUSED, CONFIRMATION_STALE). stage: candidate_ready once the search
        evidence passes the Type-A gates, confirmed after the confirmation; outcome: the basis's outcome, or invalid
        when the node's runs all ended without a valid one. rechecks (projects with recheck_required): per dimension
        the cross-model review that checked this basis (review id, result, backend, reviewer model, evaluation or
        code it is bound to, and the one it must be bound to) — what was checked and by whom; numbers and protocol
        are bound to recheck_evaluation_id (the confirmation's evaluation once there is one)."""
        with self.reader() as tx:
            return self._eligibility(tx, self._project(tx), tx.require(hypothesis_id, ("hypothesis",)), protocol_id)

    def evaluations(self, experiment_id: str | None = None, hypothesis_id: str | None = None) -> list[dict]:
        """Evaluation records (all, of one experiment, or of a hypothesis's experiments), oldest first."""
        with self.reader() as tx:
            if experiment_id:
                exp_ids = [tx.require(experiment_id, ("experiment",))["id"]]
            elif hypothesis_id:
                exp_ids = [r["id"] for r in tx.query("MATCH (e:Experiment)-[:TESTS]->(h:Hypothesis {id: $id}) "
                                                     "RETURN e.id AS id", id=hypothesis_id)]
            else:
                exp_ids = tx.ids("experiment")
            out = [ev for e in exp_ids for ev in self._evaluations_of(tx, e)]
        for ev in out:
            ev.pop("_table", None)
        return sorted(out, key=lambda v: int(v["id"].split("-")[1]))

    def _eligibility(self, tx: _Tx, project: dict, hyp: dict, protocol_id: str | None = None) -> dict:
        exps = [tx.get(r["id"]) for r in tx.query("MATCH (e:Experiment)-[:TESTS]->(h:Hypothesis {id: $id}) "
                                                   "RETURN e.id AS id", id=hyp["id"])]
        search = [e for e in exps if e["kind"] == "method" and (e.get("stage") or "screen") != "confirm"
                  and self._evaluations_of(tx, e["id"])]
        out = {"hypothesis_id": hyp["id"], "eligible": False, "basis_evaluation_id": None, "experiment_id": None,
               "evidence_state": "none", "reasons": ["NO_EVALUATION"], "verification_level": None,
               "gate_passed": None, "guardrails_passed": None, "stage": None, "outcome": None,
               "confirmation_evaluation_id": None, "open_obligations": [], "rechecks": None,
               "recheck_evaluation_id": None}
        if not search:
            # an engineering failure is no evidence: no evaluation; the node's outcome reads 'invalid' (06 §2.1)
            tried = [e for e in exps if e["kind"] == "method" and (e.get("stage") or "screen") != "confirm"]
            runs = [tx.get(f"{e['id']}/s{s}") for e in tried for s in e["seeds"]]
            if runs and all(r and r["exec_status"] in FINAL_EXEC and r.get("valid") is not True for r in runs):
                out["outcome"] = "invalid"
            return out
        latest = max(search, key=lambda e: int(e["id"].split("-")[1]))
        history = self._evaluations_of(tx, latest["id"])
        basis = next((v for v in history if v["id"] == latest.get("evaluation_id")), history[-1])
        reasons = self._stale_reasons(tx, project, basis)
        if protocol_id is not None and protocol_id != basis.get("protocol_doc_id"):
            reasons.append("PROTOCOL_CHANGED")
        state = "stale" if reasons else "current"
        if basis["verification_level"] == "legacy_unverified" or basis.get("migrated"):
            reasons.append("LEGACY_RESULT_UNVERIFIED")
        elif not basis.get("eval_type"):
            reasons.append("EVAL_TYPE_MISSING")
        if not basis.get("gate_passed"):
            reasons.append("GATE_NOT_PASSED")
        if basis.get("guardrails_passed") is False:
            reasons.append("GUARDRAIL_FAILED")
        opened = self._open_obligations(tx, hyp["id"])
        if opened:
            reasons.append("OBLIGATION_OPEN")
        if _disposition(hyp) == "retired":
            reasons.append("DISPOSITION_RETIRED")
        # candidate_ready: the search evidence passes the Type-A gates; confirmation and rechecks come next
        stage = "candidate_ready" if not reasons else None
        basis_exp = tx.get(basis["experiment_id"])
        for key in RECHECK_FIELDS:
            if hyp[key] == "fail":
                reasons.append("RECHECK_FAILED")
            elif hyp[key] != "pass":
                reasons.append("RECHECK_PENDING")
            elif not self._recheck_bound(tx, hyp["id"], key, basis_exp):
                reasons.append("RECHECK_STALE")
        confirmation = None
        protocol = self._protocol(tx, project)
        if protocol and protocol.get("profile", "stage1_confirmed") == "stage1_confirmed":
            confirmation, why = self._confirmation(tx, project, protocol, hyp, basis_exp)
            if why:
                reasons.append(why)
            elif stage == "candidate_ready":
                stage = "confirmed"
        rechecks, recheck_ev = None, None
        if project.get("recheck_required"):  # cross-model rechecks of the candidate (07, 09 candidate_recheck)
            # the numbers GO rests on: the confirmation's once there is one, else the search basis (07 §3, §6)
            recheck_ev = confirmation or basis["id"]
            rechecks, why = self._candidate_rechecks(tx, hyp, recheck_ev, basis_exp)
            reasons += why
        reasons = list(dict.fromkeys(reasons))
        return {**out, "eligible": not reasons, "basis_evaluation_id": basis["id"],
                "experiment_id": basis["experiment_id"], "evidence_state": state, "reasons": reasons,
                "verification_level": basis["verification_level"], "gate_passed": basis.get("gate_passed"),
                "guardrails_passed": basis.get("guardrails_passed"), "stage": stage, "outcome": basis.get("outcome"),
                "confirmation_evaluation_id": confirmation, "open_obligations": opened, "rechecks": rechecks,
                "recheck_evaluation_id": recheck_ev}

    def _confirmation(self, tx: _Tx, project: dict, protocol: dict, hyp: dict, basis_exp: dict) -> tuple:
        """The node's independent confirmation of its candidate code (06 §2.2, §2.5): a current confirm-stage
        evaluation of the same code that passes the gate and guardrails, on confirmation seeds that no earlier
        confirmation of other code of this node has used (feedback used to change the code is exploration)."""
        confirms = [e for e in (tx.get(r["id"]) for r in tx.query(
            "MATCH (e:Experiment)-[:TESTS]->(h:Hypothesis {id: $id}) RETURN e.id AS id", id=hyp["id"]))
            if e.get("stage") == "confirm" and e.get("evaluation_id")]
        mine = [e for e in confirms if e["code_ref"] == basis_exp["code_ref"]]
        if not mine:
            return None, "CONFIRMATION_REQUIRED"
        exp = max(mine, key=lambda e: int(e["id"].split("-")[1]))
        ev = tx.get(exp["evaluation_id"])
        earlier = [e for e in confirms if e["code_ref"] != exp["code_ref"] and int(e["id"].split("-")[1]) <
                   int(exp["id"].split("-")[1])]
        if any(set(e["seeds"]) & set(exp["seeds"]) for e in earlier):
            return ev["id"], "CONFIRMATION_REUSED"
        if self._stale_reasons(tx, project, ev):
            return ev["id"], "CONFIRMATION_STALE"
        if not ev.get("gate_passed") or ev.get("guardrails_passed") is False:
            return ev["id"], "CONFIRMATION_FAILED"
        return ev["id"], None

    def _stale_reasons(self, tx: _Tx, project: dict, ev: dict) -> list[str]:
        """Why an evaluation no longer applies to the current project (plans/design 05 §3.4)."""
        reasons = []
        if ev["harness_ref"] != project.get("harness_ref") or (
                ev.get("harness_paths") is not None and ev["harness_paths"] != sorted(project.get("harness_paths") or [])):
            reasons.append("HARNESS_CHANGED")
        if ev.get("protocol_doc_id") != project.get("protocol_doc_id"):
            reasons.append("PROTOCOL_CHANGED")
        if ev.get("metric_spec_doc_id") != project.get("metric_spec_doc_id"):
            reasons.append("METRIC_SPEC_CHANGED")
        if ev.get("baseline_experiment_id"):
            baseline = tx.get(ev["baseline_experiment_id"])
            base_ev = tx.get(baseline["evaluation_id"]) if baseline.get("evaluation_id") else None
            reference = project.get("sota_experiment_id")
            if ev.get("stage") == "confirm":  # a confirmation compares with the current confirmation baseline
                current = [e for e in (tx.get(i) for i in tx.ids("experiment")) if e["kind"] == "baseline"
                           and e.get("stage") == "confirm" and e.get("evaluated_at")
                           and e.get("harness_ref") == project.get("harness_ref")]
                reference = max(current, key=lambda e: int(e["id"].split("-")[1]))["id"] if current else None
            if ev["baseline_experiment_id"] != reference or (
                    baseline.get("evaluation_id") and baseline["evaluation_id"] != ev.get("baseline_evaluation_id")) or (
                    base_ev is not None and self._stale_reasons(tx, project, {**base_ev, "baseline_experiment_id": None})):
                reasons.append("BASELINE_CHANGED")
        if ev.get("statistics_version") != metrics.STATISTICS_VERSION or (
                ev.get("verification_level") == "artifact_imported" and ev.get("parser_version") != metrics.PARSER_VERSION):
            reasons.append("STATISTICS_CHANGED")
        exp = tx.get(ev["experiment_id"])
        if exp.get("evaluation_id") != ev["id"]:
            reasons.append("RESULT_REVISION_PENDING")
        for ref in ev.get("run_attempt_refs") or []:
            run_id, _, attempt = ref.rpartition("@")
            run = tx.get(run_id)
            if run is None or run.get("retracted_at") and run["attempt"] == int(attempt):
                reasons.append("RUN_RETRACTED")
            elif run["attempt"] != int(attempt):
                reasons.append("RUN_RETRACTED" if any(a.get("retracted_at") for a in (run.get("attempts") or {}).values())
                               else "INPUT_CHANGED")
            elif run.get("valid") is not True:
                reasons.append("RUN_RETRACTED")
        return list(dict.fromkeys(reasons))

    def _recheck_bound(self, tx: _Tx, hyp_id: str, field: str, basis_exp: dict) -> bool:
        """The latest decision setting a recheck to pass rests on an experiment with the basis's code."""
        rows = tx.query("MATCH (d:Decision)-[:DECIDES]->(h:Hypothesis {id: $id}) RETURN d.id AS id", id=hyp_id)
        decisions = sorted((tx.get(r["id"]) for r in rows if tx.get(r["id"])["field"] == field),
                           key=lambda d: int(d["id"].split("-")[1]))
        if not decisions or decisions[-1]["to_value"] != "pass":
            return False
        for edge in tx.edges("rel_based_on", source=decisions[-1]["id"]):
            target = tx.get(edge["target_id"])
            if target["_table"] == "evaluation":
                target = tx.get(target["experiment_id"])
            if target["_table"] == "experiment" and target["code_ref"] == basis_exp["code_ref"]:
                return True
        return False

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


VALID_RUN_HOW = ("A run becomes valid with update_run: exec_status planned -> submitted (-> running) -> succeeded, "
                 "then valid=true with metric_value, secondary, nodes_used and walltime_used_s.")


def _disposition(hyp: dict) -> str:
    """A node's investment disposition; old records without one: retired when prunable, else active."""
    return hyp.get("disposition") or ("retired" if hyp.get("status") == "prunable" else "active")


def _fingerprint(source: str, pattern: str, excerpt: str) -> str:
    """Identity of a finding across reports: the source family (before ':'), the pattern and the evidence excerpt
    with whitespace normalised (ARIS forensics_gate.fingerprint)."""
    basis = json.dumps({"source": source.split(":", 1)[0], "pattern": pattern,
                        "excerpt": re.sub(r"\s+", " ", excerpt or "").strip()}, sort_keys=True, ensure_ascii=False)
    return hashlib.sha256(basis.encode("utf-8")).hexdigest()[:24]


def _read_json(path: Path, what: str) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ResearchDBError(f"{what} {path} cannot be read as JSON: {exc}") from None


def _invalid_runs(tx: _Tx, exp: dict) -> str:
    """The seeds of an experiment without a valid run, each with its run's state."""
    states = []
    for seed in exp["seeds"]:
        run = tx.get(f"{exp['id']}/s{seed}")
        if run is None:
            states.append(f"{exp['id']}/s{seed} (no run)")
        elif run.get("valid") is not True:
            states.append(f"{run['id']} (exec_status {run['exec_status']}, valid {run.get('valid')})")
    return ", ".join(states)


def _cleanup_script(script: Path, step: str, request: dict) -> dict:
    """One step (plan or delete) of the project's cleanup script: JSON in on stdin, JSON out on stdout."""
    out = subprocess.run([sys.executable, str(script), step], input=json.dumps(request, ensure_ascii=False),
                         capture_output=True, text=True, cwd=script.parent)
    if out.returncode != 0:
        raise ResearchDBError(f"{script.name} {step} failed (exit {out.returncode}): {out.stderr.strip()[-800:]}")
    try:
        return json.loads(out.stdout)
    except json.JSONDecodeError:
        raise ResearchDBError(f"{script.name} {step} must print one JSON object; got {out.stdout[:200]!r}") from None


def _not_allowed(what: str, old: str, new: str, allowed) -> ResearchDBError:
    """A refused state change, naming the changes that are possible from the current state."""
    return ResearchDBError(f"{what} {old} -> {new} is not allowed; from {old}: {', '.join(allowed) or 'none (final)'}")


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


def node_hours(runs: list[dict]) -> float:
    """Recorded usage: nodes_used x walltime_used_s over every attempt of the runs that reports both."""
    return sum(run_node_hours(r) or 0 for r in runs)


def run_node_hours(run: dict) -> float | None:
    """One run's recorded usage, its earlier attempts included; None when no attempt reports it."""
    used = [a["nodes_used"] * a["walltime_used_s"] / 3600 for a in [run, *(run.get("attempts") or {}).values()]
            if a.get("nodes_used") and a.get("walltime_used_s")]
    return sum(used) if used else None


def busy_workers(tasks: list[dict]) -> set[str]:
    """Workers with a task in hand: assigned and not yet delivered, or sent back for rework."""
    return {t["assignee_id"] for t in tasks if t["assignee_role"] == "worker" and t.get("assignee_id")
            and t["status"] in ("open", "in_progress", "rejected")}


def default_worker_id(node_id: str, table: str) -> str:
    """The worker identity a node gets by default: `root` for the project, `h0007` for H-0007."""
    return "root" if table == "project" else re.sub(r"[^A-Za-z0-9_.]", "", node_id).lower()


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

# The methods that only read: the UI's and any reader's whole interface.
READ_METHODS = ("help", "get", "find", "edges", "children", "history", "go_candidates", "latest_result",
                "screen_seed_count", "export_snapshot", "verify_document", "resume_package", "cleanup_due",
                "get_eligibility", "evaluations", "preview_evaluation", "obligations", "budget_status",
                "reconcile_submission", "reviews")

CLI_METHODS = sorted(
    name for name in vars(ResearchDB) if not name.startswith("_") and callable(getattr(ResearchDB, name))
    and name != "reader"
)


def describe(method: str | None = None) -> dict | list:
    """The CLI's own `help`: every method with its parameters and the first line of its description, or one
    method's whole description."""
    if method is not None:
        if method not in CLI_METHODS:
            raise ResearchDBError(f"no method {method!r}; call help without a method for the list")
        fn = getattr(ResearchDB, method)
        return {"method": method, "parameters": _parameters(fn), "description": inspect.getdoc(fn) or ""}
    return [{"method": name, "parameters": _parameters(getattr(ResearchDB, name)),
             "summary": (inspect.getdoc(getattr(ResearchDB, name)) or "").split("\n")[0]}
            for name in CLI_METHODS]


def _parameters(fn) -> str:
    return str(inspect.signature(fn)).replace("'", "").replace("(self, ", "(").replace("(self)", "()")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Call one ResearchDB method; prints the result as JSON.")
    parser.add_argument("--db", required=True, type=Path)
    parser.add_argument("--actor", required=True, help="<role>/<agent-id>")
    parser.add_argument("method", choices=CLI_METHODS + ["help"])
    parser.add_argument("kwargs", nargs="?", default="{}", help="JSON object of keyword arguments")
    args = parser.parse_args(argv)
    try:
        kwargs = json.loads(args.kwargs)
        if not isinstance(kwargs, dict):
            raise ResearchDBError("kwargs must be a JSON object")
        result = (describe(**kwargs) if args.method == "help"
                  else getattr(ResearchDB(args.db, args.actor), args.method)(**kwargs))
    except (ResearchDBError, json.JSONDecodeError, TypeError) as exc:
        error = f"{type(exc).__name__}: {exc}"
        if isinstance(exc, TypeError) and args.method in CLI_METHODS:
            error += (f"; {args.method}{_parameters(getattr(ResearchDB, args.method))}"
                      f' (help {{"method": "{args.method}"}} describes it)')
        out = {"ok": False, "error": error}
        if getattr(exc, "code", None):
            out["code"] = exc.code
        print(json.dumps(out, ensure_ascii=False))
        return 2
    print(json.dumps({"ok": True, "result": result}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
