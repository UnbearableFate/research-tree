"""Attempts, retries and duplicates counted apart (plans/research-tree-implementation-and-real-scenarios.md §10.3).

The research database says which run attempts exist and how they ended; the execution adapter's own ledgers say
which processes really started (launches.jsonl) and which calls were made (events.jsonl); the controller's fault
file says which failures were injected. A duplicate job is a process start that no legitimate attempt accounts
for — computed from the launch ledger against the run intents, never as sum(attempt - 1). A failure is avoidable
only when a fix for the same fault class was already verified (the lesson's memory_basis) before it happened, and
it was not injected again by the controller; nothing is matched on root-cause wording.
"""
from __future__ import annotations

import json
import re
from collections import Counter
from pathlib import Path

FAULT_CLASS_RE = re.compile(r"\b([A-Z][A-Za-z]*(?:Error|Exception))\b|(out of memory|OOM)\b", re.I)


def _jsonl(path: Path) -> list[dict]:
    out = []
    if path.is_file():
        for line in path.read_text(encoding="utf-8").splitlines():
            try:
                out.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    return out


def fault_class(root: Path, attempt: dict) -> str | None:
    """A stable class for a failed attempt: the first exception or OOM named in its log."""
    log = attempt.get("log_path")
    path = (root / log) if log and not Path(log).is_absolute() else Path(log or "")
    if not log or not path.is_file():
        return None
    m = FAULT_CLASS_RE.search(path.read_text(encoding="utf-8", errors="replace"))
    return (m.group(1) or "OOM") if m else None


def attempts_of(runs: list[dict]) -> list[tuple[str, int, dict]]:
    out = []
    for run in runs:
        for n, a in [(run["attempt"], run), *((int(k), v) for k, v in (run.get("attempts") or {}).items())]:
            out.append((run["id"], n, a))
    return sorted(out, key=lambda x: (x[0], x[1]))


def metrics(project_dir: Path, tables: dict, root: Path, duplicate_import_requests: int | None = None) -> dict:
    exec_dir = project_dir / ".local-exec"
    launches = [e for e in _jsonl(exec_dir / "launches.jsonl") if e.get("pid") and not e.get("ended")]
    starts = Counter(e["key"] for e in launches)
    events = _jsonl(exec_dir / "events.jsonl")
    submits = Counter(e["key"] for e in events if e.get("call") == "submit" and e.get("key"))
    settles = Counter(e["key"] for e in events if e.get("call") == "accounting" and e.get("key"))
    injected = _jsonl(exec_dir / "faults.jsonl")
    reserved_keys = {r["submission_key"] for r in tables.get("reservation", [])}
    all_attempts = attempts_of(tables.get("run", []))
    by_ref = {(rid, n): a for rid, n, a in all_attempts}
    research = [(rid, n, a) for rid, n, a in all_attempts if a.get("exec_status") not in (None, "planned")]
    authorized = 0
    for rid, n, a in research:
        prev = by_ref.get((rid, n - 1))
        if n > 1 and prev is not None and (prev.get("exec_status") in ("failed", "cancelled")
                                           or prev.get("valid") is False or prev.get("retracted_at")):
            authorized += 1
    # every start beyond the first of a key, and every start of a key no reservation (no run intent) explains
    duplicates = sum(max(0, n - 1) if k in reserved_keys else n for k, n in starts.items())
    # avoidable repeated failures: a fault class whose fix was verified before this failure, not injected again
    verified = []
    for d in tables.get("document", []):
        basis = (d.get("memory_basis") or {}).get("verification") or {}
        if d.get("doc_type") == "lesson" and d.get("status") == "current" and basis.get("state") == "verified":
            rid, _, n = str(basis.get("failure") or "").rpartition("@")
            source = by_ref.get((rid, int(n))) if n.isdigit() else None
            cls = fault_class(root, source) if source else None
            if cls:
                verified.append((cls, d.get("updated_at") or d.get("created_at") or ""))
    injected_keys = {f.get("key") for f in injected}
    avoidable = 0
    for rid, n, a in research:
        if a.get("exec_status") != "failed" or a.get("submission_key") in injected_keys:
            continue
        cls = fault_class(root, a)
        when = a.get("finished_at") or a.get("started_at") or ""
        if cls and any(cls == c and at and when and at < when for c, at in verified):
            avoidable += 1
    return {"research_attempts": len(research), "authorized_retries": authorized,
            "transport_retries": sum(n - 1 for n in submits.values() if n > 1),
            "duplicate_jobs": duplicates, "duplicate_import_requests": duplicate_import_requests,
            "duplicate_settlement_requests": sum(n - 1 for n in settles.values() if n > 1),
            "injected_failures": len(injected), "avoidable_repeated_failures": avoidable,
            "starts_per_key": dict(starts)}
