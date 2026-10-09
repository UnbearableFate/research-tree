#!/usr/bin/env python3
"""Score finished benchmark episodes (plans/research-tree-implementation-and-real-scenarios.md §11.3, §11.5).

    python3 scripts/benchmark/score.py PROJECT_DIR --truth truth.json --system B|C --tools DIST/.../tools \
        [--host claude|codex] [--version <commit>] [--out episode.json]

An episode is first normalized into plain events read through the tested version's own tools (its export_snapshot),
so an older system is never asked to adopt the newer database layout: the final outcome (go, not_go, blocked,
budget_stopped, active, incomplete — kept apart, never merged into a success rate), every GO candidate with the knob
set its claim rests on and when it was decided, the knob sets tested, the attempt counts of §10.3 from the execution
ledger, and the measured costs. Each GO candidate is then scored on its own: it is a false GO only when its knob set
is not one the private truth lists as effective (another genuinely effective set is a success; hitting the best one
is reported separately). A node retired while holding the best set is reported (best_retired), not called a
premature elimination: retiring is a decision, not an error by itself. Episodes are grouped by system, host and the
executor model actually observed; one label never hides two executors. The truth file is the evaluator's, never the
agent's (§11.4). Single episodes are noisy: a pilot reports each one, not a verdict.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "scenarios"))

OUTCOMES = ("go", "not_go", "blocked", "budget_stopped", "active", "incomplete")


def _knobs(root: Path, runs: list[dict], exp_id: str) -> list[str]:
    for r in runs:
        if r["experiment_id"] == exp_id and r.get("valid"):
            path = Path(r.get("metrics_path") or Path(r.get("output_path") or "") / "metrics.json")
            path = path if path.is_absolute() else root / path
            if path.is_file():
                return sorted(json.loads(path.read_text(encoding="utf-8")).get("knobs") or [])
    return []


def snapshot(project_dir: Path, tools: Path, python: str = sys.executable) -> tuple[dict, Path]:
    """The project's tables through the tested version's own CLI (a read-only role)."""
    marker = json.loads((project_dir / ".research-tree.json").read_text(encoding="utf-8"))
    out = subprocess.run([python, str(tools / "research_db.py"), "--db", marker["db"], "--actor", "ui/benchmark",
                          "export_snapshot"], capture_output=True, text=True, check=True)
    data = json.loads(out.stdout)
    data = data.get("result", data)
    return data["tables"], Path(marker["root"])


def normalize(project_dir: Path, tools: Path, system: str, host: str | None, version: str | None,
              executor_model: str | None = None, ended: str | None = None) -> dict:
    """Plain events of one episode. ended: how the controller saw it stop (completed, budget, blocked, timeout)."""
    import attempt_metrics
    tables, root = snapshot(project_dir, tools)
    return events(tables, root, system, host, version, executor_model, ended,
                  attempt_metrics.metrics(project_dir, tables, root))


def events(tables: dict, root: Path, system: str, host: str | None, version: str | None,
           executor_model: str | None, ended: str | None, attempts: dict | None) -> dict:
    project = tables["project"][0]
    runs = tables.get("run", [])
    hyps = {h["id"]: h for h in tables.get("hypothesis", [])}
    exps = tables.get("experiment", [])
    decisions = sorted(tables.get("decision", []), key=lambda d: (d.get("decided_at") or "", d["id"]))
    candidates = []
    for d in decisions:  # every GO decision, in order; a later revision is its own event
        if d.get("field") != "status" or d.get("to_value") != "go":
            continue
        named = sorted({e.get("hypothesis_id") for e in exps
                        if e["id"] in f"{d.get('reason') or ''} {' '.join(d.get('based_on') or [])}"} - {None})
        for node in named or sorted(h for h, x in hyps.items() if x.get("experiment_status") == "beats_sota"):
            method = [e for e in exps if e.get("hypothesis_id") == node and e["kind"] == "method"]
            candidates.append({"decision_id": d["id"], "decided_at": d.get("decided_at"), "node": node,
                               "knobs": _knobs(root, runs, method[-1]["id"]) if method else []})
    tested = [{"node": e.get("hypothesis_id"), "knobs": _knobs(root, runs, e["id"]),
               "retired": hyps.get(e.get("hypothesis_id"), {}).get("status") == "prunable"
               or hyps.get(e.get("hypothesis_id"), {}).get("disposition") == "retired"}
              for e in exps if e["kind"] == "method" and e.get("hypothesis_id")]
    status = project.get("status")
    outcome = ("go" if status == "go" else "not_go" if status in ("not_go", "closed_not_go") else
               "budget_stopped" if ended == "budget" or project.get("admission_paused") else
               "blocked" if ended == "blocked" else "incomplete" if ended in ("timeout", "incomplete") else "active")
    return {"system": system, "host": host, "version": version, "executor_model": executor_model,
            "outcome": outcome, "ended": ended, "go_candidates": candidates, "tested": tested,
            "valid_runs": sum(1 for r in runs if r.get("valid")),
            "node_seconds": sum((r.get("actual_units") or r.get("reserved_units") or 0)
                                for r in tables.get("reservation", []) if r.get("accounting_status") != "released"),
            "review_cost_usd": project.get("review_cost_usd") or 0.0,
            "user_instructions": sum(1 for d in tables.get("document", []) if d.get("doc_type") == "user_instruction"),
            "attempts": attempts}


def score_episode(ep: dict, truth: dict) -> dict:
    effective = [sorted(k) for k in (truth.get("effective") or ([truth["best"]] if truth.get("best") else []))]
    best = sorted(truth.get("best") or [])
    scored = [{**c, "supported": sorted(c["knobs"]) in effective, "best": bool(best) and sorted(c["knobs"]) == best}
              for c in ep.get("go_candidates", [])]
    hours = (ep.get("node_seconds") or 0) / 3600
    return {"system": ep["system"], "host": ep.get("host"), "version": ep.get("version"),
            "executor_model": ep.get("executor_model"), "outcome": ep["outcome"],
            "go_candidates": scored, "false_go": sum(not c["supported"] for c in scored),
            "found_effective": any(c["supported"] for c in scored), "found_best": any(c["best"] for c in scored),
            "best_retired": bool(best) and any(sorted(t["knobs"]) == best and t["retired"] for t in ep.get("tested", [])),
            "coverage": len({tuple(sorted(t["knobs"])) for t in ep.get("tested", [])}),
            "efficiency": round(ep.get("valid_runs", 0) / hours, 3) if hours else None,
            "user_burden": max(0, (ep.get("user_instructions") or 0) - 1),
            "review_cost_usd": ep.get("review_cost_usd", 0.0), "attempts": ep.get("attempts")}


def group(scores: list[dict]) -> dict:
    """Per (system, host): the episodes with every outcome kept apart. Two executors under one label are refused."""
    out: dict = {}
    for s in scores:
        key = f"{s['system']}/{s.get('host')}"
        g = out.setdefault(key, {"executor_model": s.get("executor_model"), "episodes": 0,
                                 "outcomes": {o: 0 for o in OUTCOMES}, "false_go": 0, "found_effective": 0})
        if g["executor_model"] != s.get("executor_model"):
            raise ValueError(f"{key} mixes executors {g['executor_model']!r} and {s.get('executor_model')!r}: report "
                             "them as different groups")
        g["episodes"] += 1
        g["outcomes"][s["outcome"]] += 1
        g["false_go"] += s["false_go"]
        g["found_effective"] += int(s["found_effective"])
    return out


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("project", type=Path)
    p.add_argument("--truth", type=Path, required=True)
    p.add_argument("--system", required=True, help="A: single-agent loop, B: frozen research-tree, C: this version")
    p.add_argument("--tools", type=Path, required=True, help="the tested version's plugin tools directory")
    p.add_argument("--host")
    p.add_argument("--version")
    p.add_argument("--executor-model")
    p.add_argument("--ended", choices=("completed", "budget", "blocked", "timeout", "incomplete"))
    p.add_argument("--out", type=Path)
    args = p.parse_args()
    truth = json.loads(args.truth.read_text(encoding="utf-8"))
    ep = normalize(args.project, args.tools, args.system, args.host, args.version, args.executor_model, args.ended)
    result = {"scenario": truth.get("scenario"), "episode": ep, "score": score_episode(ep, truth)}
    if args.out:
        args.out.write_text(json.dumps(result, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    print(json.dumps(result, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
