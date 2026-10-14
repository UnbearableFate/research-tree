#!/usr/bin/env python3
"""Score REG-only formula-fixture episodes from the current project/database contract.

    .venv/bin/python scripts/benchmark/score.py PROJECT_DIR --truth truth.json --system current \
        --tools DIST/.../tools [--host claude|codex] [--version <commit>] [--out episode.json]

Only version-3 project markers and schema-23 snapshots are accepted. GO candidates must be explicitly identified
by a project_status GO decision's based_on edges (rel_based_on) to experiments/evaluations and have marked REG knob
evidence: the imported metrics file of the experiment's valid runs. Node verdict labels, free-text reasons,
unrelated experiments and absent or changed artifacts never substitute for that evidence. Missing evidence
fails scoring rather than producing an empty successful GO. Formula-fixture scores are software regressions,
never scientific or model-efficacy evidence. Outcomes remain separate and executor models cannot be mixed.
The snapshot is exported by research_db.py under the repository's .venv interpreter when it exists (research_db
needs the project's dependencies, which the system python3 lacks).
"""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "scenarios"))
VENV_PYTHON = HERE.parents[1] / ".venv" / "bin" / "python"
PYTHON = str(VENV_PYTHON) if VENV_PYTHON.is_file() else sys.executable

OUTCOMES = ("go", "not_go", "blocked", "budget_stopped", "active", "incomplete")


def _knobs(root: Path, runs: list[dict], exp_id: str) -> list[str] | None:
    """The exact experiment's explicit fixture knobs, consistent across every valid run whose imported metrics file
    (import_run_result keeps it first in evidence_paths, relative to the research root) still has the bytes the
    import hashed."""
    observed = set()
    for run in runs:
        if run["experiment_id"] != exp_id or not run.get("valid"):
            continue
        evidence = run.get("evidence_paths") or []
        digest = (run.get("import_record") or {}).get("metrics_sha256")
        if not evidence or not digest:
            continue
        path = Path(evidence[0])
        path = path if path.is_absolute() else root / path
        if not path.is_file() or hashlib.sha256(path.read_bytes()).hexdigest() != digest:
            continue
        metrics = json.loads(path.read_text(encoding="utf-8"))
        if metrics.get("evidence_class") != "reg" or "knobs" not in metrics:
            continue
        knobs = metrics["knobs"]
        if not isinstance(knobs, list) or any(not isinstance(k, str) or not k for k in knobs):
            raise ValueError(f"{exp_id}: REG knobs must be an explicit list of nonempty strings")
        observed.add(tuple(sorted(set(knobs))))
    if len(observed) > 1:
        raise ValueError(f"{exp_id}: run artifacts disagree about the candidate's REG knobs")
    return list(next(iter(observed))) if observed else None


def snapshot(project_dir: Path, tools: Path, python: str = PYTHON) -> tuple[dict, dict, Path]:
    """Read current-contract tables and relations through the exact read-only ui/ui actor."""
    marker = json.loads((project_dir / ".research-tree.json").read_text(encoding="utf-8"))
    if type(marker.get("format_version")) is not int or marker["format_version"] != 3:
        raise ValueError("benchmark scoring requires a version-3 project marker")
    out = subprocess.run([python, str(tools / "research_db.py"), "--db", marker["db"], "--actor", "ui/ui",
                          "export_snapshot"], capture_output=True, text=True, check=True)
    result = json.loads(out.stdout)
    if result.get("ok") is not True:
        raise ValueError("current snapshot export failed")
    data = result["result"]
    if data["meta"]["schema_version"] != 23:
        raise ValueError("benchmark scoring requires database schema 23")
    return data["tables"], data["edges"], Path(marker["root"])


def normalize(project_dir: Path, tools: Path, system: str, host: str | None, version: str | None,
              executor_model: str | None = None, ended: str | None = None) -> dict:
    """Plain events of one episode. ended: how the controller saw it stop (completed, budget, blocked, timeout)."""
    import attempt_metrics
    tables, edges, root = snapshot(project_dir, tools)
    return events(tables, edges, root, system, host, version, executor_model, ended,
                  attempt_metrics.metrics(project_dir, tables, root))


def events(tables: dict, edges: dict, root: Path, system: str, host: str | None, version: str | None,
           executor_model: str | None, ended: str | None, attempts: dict | None) -> dict:
    project = tables["project"][0]
    runs = tables["run"]
    hyps = {h["id"]: h for h in tables["hypothesis"]}
    exps = {e["id"]: e for e in tables["experiment"]}
    evaluations = {e["id"]: e for e in tables["evaluation"]}
    decisions = sorted(tables["decision"], key=lambda d: (d.get("decided_at") or "", d["id"]))
    based_on: dict[str, list[str]] = {}  # a decision's evidence is an edge, never a column of the decision
    for edge in edges["rel_based_on"]:
        based_on.setdefault(edge["source_id"], []).append(edge["target_id"])
    candidates = []
    for decision in decisions:
        if (decision["target_id"] != project["id"] or decision["field"] != "project_status"
                or decision["to_value"] != "go"):
            continue
        explicit = set()
        for evidence in based_on.get(decision["id"], []):
            exp_id = evaluations[evidence]["experiment_id"] if evidence in evaluations else evidence
            exp = exps.get(exp_id)
            if exp and exp["kind"] == "method" and exp.get("hypothesis_id") in hyps:
                explicit.add(exp_id)
        if not explicit:
            raise ValueError(f"GO decision {decision['id']} needs explicit based_on method experiment/evaluation evidence")
        for exp_id in sorted(explicit):
            knobs = _knobs(root, runs, exp_id)
            if knobs is None:
                raise ValueError(f"GO decision {decision['id']}: {exp_id} lacks explicit REG knob artifacts")
            candidates.append({"decision_id": decision["id"], "decided_at": decision.get("decided_at"),
                               "node": exps[exp_id]["hypothesis_id"], "experiment_id": exp_id, "knobs": knobs})
    tested = [{"node": e["hypothesis_id"], "experiment_id": e["id"], "knobs": _knobs(root, runs, e["id"]),
               "retired": hyps[e["hypothesis_id"]]["disposition"] == "retired"}
              for e in exps.values() if e["kind"] == "method" and e.get("hypothesis_id") in hyps]
    status = project["status"]
    if status not in ("active", "go", "not_go", "stopped"):
        raise ValueError(f"unsupported project status {status!r}")
    if status == "go" and not candidates:
        raise ValueError("GO project has no explicit GO decision evidence")
    outcome = ("go" if status == "go" else "not_go" if status == "not_go" else
               "budget_stopped" if ended == "budget" or project.get("admission_paused") else
               "blocked" if ended == "blocked" else
               "incomplete" if status == "stopped" or ended in ("timeout", "incomplete") else "active")
    return {"evidence_class": "reg", "system": system, "host": host, "version": version,
            "executor_model": executor_model, "outcome": outcome, "ended": ended,
            "go_candidates": candidates, "tested": tested,
            "valid_runs": sum(1 for r in runs if r.get("valid")),
            "node_seconds": sum(r["actual_units"] if r.get("actual_units") is not None else r["reserved_units"]
                                for r in tables["reservation"] if r["accounting_status"] != "released"),
            "review_cost_usd": project.get("review_cost_usd") or 0.0,
            "user_instructions": sum(1 for d in tables["document"] if d["doc_type"] == "user_instruction"),
            "attempts": attempts}


def score_episode(ep: dict, truth: dict) -> dict:
    if ep.get("evidence_class") != "reg" or truth.get("evidence_class") != "reg":
        raise ValueError("formula-fixture scoring requires REG episode and truth labels")
    if ep["outcome"] == "go" and not ep.get("go_candidates"):
        raise ValueError("GO episode needs explicit candidate evidence")
    effective = [sorted(k) for k in (truth.get("effective") or ([truth["best"]] if truth.get("best") else []))]
    best = sorted(truth.get("best") or [])
    scored = [{**c, "supported": sorted(c["knobs"]) in effective, "best": bool(best) and sorted(c["knobs"]) == best}
              for c in ep.get("go_candidates", [])]
    hours = (ep.get("node_seconds") or 0) / 3600
    return {"evidence_class": "reg", "system": ep["system"], "host": ep.get("host"), "version": ep.get("version"),
            "executor_model": ep.get("executor_model"), "outcome": ep["outcome"],
            "go_candidates": scored, "false_go": sum(not c["supported"] for c in scored),
            "found_effective": any(c["supported"] for c in scored), "found_best": any(c["best"] for c in scored),
            "best_retired": bool(best) and any(t["knobs"] is not None and sorted(t["knobs"]) == best
                                              and t["retired"] for t in ep.get("tested", [])),
            "coverage": len({tuple(sorted(t["knobs"])) for t in ep.get("tested", []) if t["knobs"] is not None}),
            "efficiency": round(ep.get("valid_runs", 0) / hours, 3) if hours else None,
            "unscored_experiments": [t["experiment_id"] for t in ep.get("tested", []) if t["knobs"] is None],
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
    p.add_argument("--system", required=True, help="label for a current-contract REG fixture system")
    p.add_argument("--tools", type=Path, required=True, help="the current-contract plugin tools directory")
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
