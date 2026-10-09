#!/usr/bin/env python3
"""Scenario records (plans/research-tree-implementation-and-real-scenarios.md §12.2) and fault plans (§3.3).

    record.py new SC-S0-01 --stage S0 --host claude --attempt 1 [--dir plans/design/test-logs/scenarios]
    record.py validate RECORD.json            # may this record be summed up as PASS?
    record.py faults FAULT-PLAN.json          # is the fault plan well formed?
    record.py summary [--dir ...]             # stage x host status from every record

A record is JSON. Its status may be PASS only when validate finds nothing: the host, the observed model (from the
host's own records, never the configured one), the commands actually run, raw evidence that exists, every assertion
with expected / actual / evidence / verdict PASS, the observer's result, and the resume evidence when the scenario
resumes. A real host scenario (evidence_class real_sc) must not rest on a canned model answer, a mock reviewer,
preset scores or a direct database write: those belong to REG or simulation records.

A retry may start from another attempt's saved opening (scripts/scenarios/lib.sh, FORK=...): its records name that
snapshot in forked_from. A forked attempt can show a stage's own scenarios, never SC-COMMON-01 (the opening is not
its own), and a stage x host cell is PASS only when some unbroken attempt of that stage and host passed SC-COMMON-01.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
DEFAULT_DIR = REPO / "plans" / "design" / "test-logs" / "scenarios"
STATUSES = ("NOT_STARTED", "IN_PROGRESS", "PASS", "FAIL", "BLOCKED")
VERDICTS = ("PASS", "FAIL", "BLOCKED")
EVIDENCE_CLASSES = ("real_sc", "reg", "simulation")
HOSTS = ("claude", "codex")
# §2.2: what each host's test session runs on and which reviewer backend its product review uses
# The effort follows the §2.2 model matrix as the user last revised it (medium for both test sessions); §0.1 and
# §4.1 still say "high" from an earlier revision — implementation-status.md records the resolution.
MATRIX = {"claude": {"main": "claude-haiku-5-5", "effort": "medium", "reviewer_backend": "pi",
                     "reviewer": "openai/gpt-6-luna"},
          "codex": {"main": "gpt-6-luna", "effort": "medium", "reviewer_backend": "claude_code",
                    "reviewer": "anthropic/claude-haiku-5-5"}}
REAL_BACKENDS = ("pi", "claude_code")
# what a real scenario may not rest on (§2.1)
SUBSTITUTES = ("canned_model_response", "mock_reviewer", "local_responses_stub", "direct_db_write",
               "preset_review_pass", "preset_go", "preset_scores", "formula_metric")
FAULT_FIELDS = ("id", "target", "trigger", "times", "invariants")


def template(scenario_id: str, stage: str, host: str, attempt: int) -> dict:
    return {
        "scenario_id": scenario_id, "stage": stage, "host": host, "attempt": attempt, "status": "NOT_STARTED",
        "evidence_class": "real_sc", "requires_resume": True, "project_root": None, "source_ref": None,
        "uncommitted_changes": [], "build_path": None, "loaded_plugin_path": None,
        "requested_model": MATRIX[host]["main"], "observed_model": None, "observed_effort": None, "session_id": None,
        "session_transcripts": [],
        "review_calls": [], "preconditions": [], "commands": [], "fault_plan": None, "substitutes_used": [],
        "assertions": [], "raw_evidence_paths": [], "observer_results": None, "state_before": None,
        "state_after": None, "resume_evidence": None, "forked_from": None,
        "resource_usage": {"cpu_seconds": None, "job_wall_seconds": None, "plugin_node_seconds": None,
                           "known_model_cost_usd": None, "unknown_cost_calls": []},
        "failures": [], "fixes_and_retests": [], "remaining_gaps": []}


def _exists(path: str, base: Path) -> bool:
    p = Path(path)
    return (p if p.is_absolute() else base / p).exists() or (REPO / p).exists()


def problems(record: dict, base: Path | None = None) -> list[str]:
    """Why the record cannot be summed up as PASS (empty when it can)."""
    base = base or REPO
    out = []
    if record.get("status") not in STATUSES:
        out.append(f"status must be one of {STATUSES}")
    if record.get("host") not in HOSTS:
        out.append("host is claude or codex")
    if record.get("evidence_class") not in EVIDENCE_CLASSES:
        out.append(f"evidence_class is one of {EVIDENCE_CLASSES}")
    for key in ("scenario_id", "stage", "source_ref", "build_path", "loaded_plugin_path", "project_root"):
        if not record.get(key):
            out.append(f"{key} is missing")
    if not record.get("observed_model"):
        out.append("observed_model is missing (from the host's own records, not the configuration)")
    if not record.get("session_id"):
        out.append("session_id is missing")
    if record.get("evidence_class") == "real_sc":
        if not record.get("observed_effort"):
            out.append("observed_effort is missing (from the host's own records)")
        elif record.get("host") in MATRIX and record["observed_effort"] != MATRIX[record["host"]]["effort"]:
            out.append(f"observed effort {record['observed_effort']} is not the matrix effort "
                       f"{MATRIX[record['host']]['effort']}")
        if record.get("requires_resume", True) and record.get("resume_evidence"):
            resume = record["resume_evidence"]
            pair = [resume.get("observer_before"), resume.get("observer_after")]
            if not all(pair) or not all(_exists(p, base) for p in pair):
                out.append("resume_evidence needs observer_before and observer_after (read-only snapshots around the "
                           "resumed session)")
        transcripts = record.get("session_transcripts") or []
        if not transcripts or not all(_exists(p, base) for p in transcripts):
            out.append("session_transcripts (the host's raw session files) are missing")
        for call in record.get("review_calls") or []:
            if call.get("outcome") == "ok" and not (call.get("raw_output") and _exists(call["raw_output"], base)):
                out.append(f"review call {call.get('review_id') or call} has no raw reviewer output on file")
    if not record.get("commands"):
        out.append("commands actually run are missing")
    raw = record.get("raw_evidence_paths") or []
    if not raw:
        out.append("raw_evidence_paths is empty")
    missing = [p for p in raw if not _exists(p, base)]
    if missing:
        out.append(f"raw evidence does not exist: {missing[:5]}")
    if not record.get("observer_results"):
        out.append("observer_results is missing")
    if record.get("requires_resume", True) and not record.get("resume_evidence"):
        out.append("resume_evidence is missing (the scenario ends the session and resumes in a new one)")
    assertions = record.get("assertions") or []
    if not assertions:
        out.append("no assertions")
    for i, a in enumerate(assertions):
        for key in ("id", "expected", "actual", "evidence", "verdict"):
            if a.get(key) in (None, "", []):
                out.append(f"assertion {a.get('id', i)} lacks {key}")
        if a.get("verdict") not in VERDICTS:
            out.append(f"assertion {a.get('id', i)} verdict is one of {VERDICTS}")
        elif a["verdict"] != "PASS":
            out.append(f"assertion {a.get('id', i)} is {a['verdict']}")
    fork = record.get("forked_from")
    if fork:
        if str(record.get("scenario_id", "")).startswith("SC-COMMON"):
            out.append("SC-COMMON-01 needs an unbroken attempt: this one was forked from a saved opening")
        if not (isinstance(fork, dict) and fork.get("snapshot") and fork.get("attempt")):
            out.append("forked_from names the prefix snapshot and the attempt that made it")
    if record.get("evidence_class") == "real_sc":
        used = list(record.get("substitutes_used") or [])  # any substitute, named in SUBSTITUTES or not
        if used:
            out.append(f"a real scenario rests on substitutes {used}: record it as reg or simulation")
        host = record.get("host")
        if host in MATRIX and record.get("observed_model") and record["observed_model"] != MATRIX[host]["main"]:
            out.append(f"observed model {record['observed_model']} is not the {host} matrix model {MATRIX[host]['main']}")
        for call in record.get("review_calls") or []:
            if call.get("backend") is None and not call.get("review_id") and not call.get("cost_usd") \
                    and str(call.get("outcome", "")).startswith("REVIEW_"):
                continue  # refused by the interface before any backend was chosen: a refusal, not a review
            if call.get("backend") not in REAL_BACKENDS:
                out.append(f"review call {call.get('review_id') or call} has backend {call.get('backend')!r}, "
                           f"not a real reviewer backend {REAL_BACKENDS}")
            if call.get("mock") or call.get("canned"):
                out.append(f"review call {call.get('review_id') or call} is a mock")
            if call.get("outcome") == "ok" and not call.get("observed_model"):
                out.append(f"review call {call.get('review_id') or call} has no observed model")
            want = MATRIX.get(host, {})
            if call.get("outcome") == "ok" and want and (
                    call.get("backend") != want["reviewer_backend"]
                    or str(call.get("observed_model") or "").split("/")[-1] != want["reviewer"].split("/")[-1]):
                out.append(f"review call {call.get('review_id') or call} ran {call.get('backend')}/"
                           f"{call.get('observed_model')}, not the {host} matrix reviewer "
                           f"{want['reviewer_backend']}/{want['reviewer']}")
        if any("simulation_only" in json.dumps(a.get("actual"), ensure_ascii=False) for a in assertions):
            out.append("an assertion rests on a simulation_only evaluation")
    return out


def check_faults(plan: dict) -> list[str]:
    out = []
    faults = plan.get("faults")
    if not isinstance(faults, list):
        return ["faults is a list"]
    seen = set()
    for f in faults:
        missing = [k for k in FAULT_FIELDS if f.get(k) in (None, "", [])]
        if missing:
            out.append(f"fault {f.get('id')} lacks {missing}")
        if f.get("id") in seen:
            out.append(f"fault id {f.get('id')} repeats")
        seen.add(f.get("id"))
        if not isinstance(f.get("times"), int) or f.get("times", 0) < 1:
            out.append(f"fault {f.get('id')} times is a positive integer")
    return out


def record_dir(base: Path, record: dict) -> Path:
    return base / record["stage"] / record["host"] / record["scenario_id"] / f"a{int(record['attempt']):02d}"


def summary(base: Path) -> dict:
    """Stage x host: PASS only when every record of that stage and host passed validation."""
    out: dict = {}
    for path in sorted(base.glob("*/*/*/*/record.json")):
        record = json.loads(path.read_text(encoding="utf-8"))
        cell = out.setdefault(record["stage"], {}).setdefault(record["host"], {})
        latest = cell.get(record["scenario_id"])
        if latest is None or record["attempt"] >= latest["attempt"]:
            bad = problems(record, path.parent)
            cell[record["scenario_id"]] = {"attempt": record["attempt"], "status": record["status"],
                                           "valid": not bad, "problems": bad[:5],
                                           **({"forked_from": record["forked_from"].get("attempt")}
                                              if isinstance(record.get("forked_from"), dict) else {})}
    return out


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest="cmd", required=True)
    n = sub.add_parser("new")
    n.add_argument("scenario_id")
    n.add_argument("--stage", required=True)
    n.add_argument("--host", required=True, choices=HOSTS)
    n.add_argument("--attempt", type=int, default=1)
    n.add_argument("--dir", type=Path, default=DEFAULT_DIR)
    v = sub.add_parser("validate")
    v.add_argument("record", type=Path)
    f = sub.add_parser("faults")
    f.add_argument("plan", type=Path)
    s = sub.add_parser("summary")
    s.add_argument("--dir", type=Path, default=DEFAULT_DIR)
    args = p.parse_args(argv)
    if args.cmd == "new":
        record = template(args.scenario_id, args.stage, args.host, args.attempt)
        target = record_dir(args.dir, record) / "record.json"
        if target.exists():
            print(f"{target} exists: a new attempt is a new record", file=sys.stderr)
            return 2
        target.parent.mkdir(parents=True)
        target.write_text(json.dumps(record, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
        print(target)
        return 0
    if args.cmd == "validate":
        record = json.loads(args.record.read_text(encoding="utf-8"))
        bad = problems(record, args.record.parent)
        if record.get("status") == "PASS" and bad:
            print(json.dumps({"ok": False, "problems": bad}, ensure_ascii=False, indent=1))
            return 1
        print(json.dumps({"ok": not bad, "status": record.get("status"), "problems": bad}, ensure_ascii=False, indent=1))
        return 0 if not bad else 1
    if args.cmd == "faults":
        bad = check_faults(json.loads(args.plan.read_text(encoding="utf-8")))
        print(json.dumps({"ok": not bad, "problems": bad}, ensure_ascii=False))
        return 0 if not bad else 1
    print(json.dumps(summary(args.dir), ensure_ascii=False, indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main())
