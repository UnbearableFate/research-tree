#!/usr/bin/env python3
"""Score one finished benchmark run (plans/design 11 §2.4) from its research database and the task's truth.

    python3 scripts/benchmark/score.py PROJECT_DIR --truth truth.json [--system A|B|C]

Metrics: outcome (go / not_go / active), false_go (GO where the truth has no gain, or on the wrong knob set),
found (GO on the true best knob set), premature_elimination (the true best knob set tested and then retired),
efficiency (valid runs per committed node-hour, failures included), the attempt counts of §10.3 kept apart
(research_attempts, authorized_retries, transport_retries, duplicate_jobs from the execution ledger, duplicate
settlement requests, injected_failures) and avoidable_repeated_failures (a failure of a fault class whose fix was
already verified, not injected again; scripts/scenarios/attempt_metrics.py),
user_burden (registered user instructions after the first; steering typed straight into the Leader's session is
not registered and must be counted from the host log), review_cost_usd, coverage (distinct knob sets tested) and
wall_clock_h (project creation to its last decision). Recovery time and the agents' token cost need the host logs
(the hosts' session records), not this database. Single runs are noisy: compare systems over several tasks and
seeds, never one run each.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2] / "shared" / "research-tree"
sys.path.insert(0, str(ROOT / "tools"))
sys.path.insert(0, str(ROOT / "schema"))


def score(records: dict, truth: dict) -> dict:
    """records: {status, go_knobs (list or None), tested: [{knobs, node_retired}], valid_runs, node_seconds,
    extra_attempts, user_instructions, review_cost_usd}."""
    best = sorted(truth.get("best") or [])
    go = records["status"] == "go"
    go_knobs = sorted(records.get("go_knobs") or [])
    tested = records.get("tested") or []
    hours = records.get("node_seconds", 0) / 3600
    return {
        "outcome": records["status"],
        "false_go": go and (not best or go_knobs != best),
        "found": go and bool(best) and go_knobs == best,
        "premature_elimination": bool(best) and any(sorted(t["knobs"]) == best and t["node_retired"] for t in tested),
        "efficiency": round(records.get("valid_runs", 0) / hours, 3) if hours else None,
        **{k: records.get(k) for k in ("research_attempts", "authorized_retries", "transport_retries",
                                        "duplicate_jobs", "duplicate_settlement_requests", "injected_failures")},
        "user_burden": max(0, records.get("user_instructions", 0) - 1),
        "review_cost_usd": records.get("review_cost_usd", 0.0),
        "coverage": len({tuple(sorted(t["knobs"])) for t in tested}),
        "avoidable_repeated_failures": records.get("avoidable_repeated_failures", 0),
        "wall_clock_h": records.get("wall_clock_h"),
    }


def gather(project_dir: Path) -> dict:
    from research_db import ResearchDB
    marker = json.loads((project_dir / ".research-tree.json").read_text(encoding="utf-8"))
    db = ResearchDB(Path(marker["db"]), "web_builder/benchmark")
    root = Path(marker["root"])
    project = db.find("project")[0]
    runs = db.find("run")

    def knobs_of(exp_id: str) -> list[str]:
        for r in runs:
            if r["experiment_id"] == exp_id and r.get("valid"):
                path = Path(r.get("metrics_path") or Path(r.get("output_path") or "") / "metrics.json")
                path = path if path.is_absolute() else root / path
                if path.is_file():
                    return json.loads(path.read_text(encoding="utf-8")).get("knobs") or []
        return []

    tested, go_knobs = [], None
    for h in db.find("hypothesis"):
        retired = h["status"] == "prunable" or h.get("disposition") == "retired"
        for e in db.find("experiment"):
            if e.get("hypothesis_id") == h["id"] and e["kind"] == "method":
                tested.append({"knobs": knobs_of(e["id"]), "node_retired": retired})
        if project["status"] == "go" and db.get_eligibility(h["id"])["eligible"]:
            go_knobs = knobs_of(db.get_eligibility(h["id"])["experiment_id"])
    users = [d for d in db.find("document") if d["doc_type"] == "user_instruction"]
    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scenarios"))
    import attempt_metrics
    counts = attempt_metrics.metrics(project_dir, db.export_snapshot()["tables"], root)
    decisions = sorted(d["decided_at"] for d in db.find("decision"))
    from datetime import datetime
    def ts(x):
        return datetime.fromisoformat(x.replace("Z", "+00:00"))
    wall = round((ts(decisions[-1]) - ts(project["created_at"])).total_seconds() / 3600, 3) if decisions else None
    return {"status": project["status"], "go_knobs": go_knobs, "tested": tested,
            "valid_runs": sum(1 for r in runs if r.get("valid")),
            "node_seconds": db.budget_status()["committed"]["total"],
            **{k: v for k, v in counts.items() if k != "starts_per_key"},
            "user_instructions": len(users), "review_cost_usd": project.get("review_cost_usd") or 0.0,
            "wall_clock_h": wall}


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("project", type=Path)
    p.add_argument("--truth", type=Path, required=True)
    p.add_argument("--system", default="C", help="A: single-agent loop, B: frozen research-tree, C: this version")
    args = p.parse_args()
    truth = json.loads(args.truth.read_text(encoding="utf-8"))
    result = {"system": args.system, "scenario": truth["scenario"], **score(gather(args.project), truth)}
    print(json.dumps(result, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
