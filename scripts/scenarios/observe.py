#!/usr/bin/env python3
"""Read-only observer of a ToyOpt Lab test project: what the database, the run files and the job ledger say.

    python3 scripts/scenarios/observe.py PROJECT_DIR [--tools DIST/plugins/research-tree/tools] [--out FILE]

It never writes the research database (the file's SHA-256 is compared before and after) and takes no number from
the product's outputs as the expected value: every imported run is rescored from its model and evaluation split
(scorer.py), every evaluation's primary mean is recomputed from those scores, and process starts are counted in
the local execution adapter's launch ledger. The page check runs build_site.py --check.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import statistics
import subprocess
import sys
from collections import Counter
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import scorer  # noqa: E402
import attempt_metrics  # noqa: E402

REPO_TOOLS = HERE.parents[1] / "shared" / "research-tree" / "tools"


def sha(path: Path) -> str | None:
    return hashlib.sha256(path.read_bytes()).hexdigest() if path.is_file() else None


def jsonl(path: Path) -> list[dict]:
    if not path.is_file():
        return []
    out = []
    for line in path.read_text(encoding="utf-8").splitlines():
        try:
            out.append(json.loads(line))
        except json.JSONDecodeError:
            out.append({"unparsed": line[:200]})
    return out


def launches(project: Path) -> dict:
    """Process starts per submission key from the adapter's launch ledger: a key started more than once is a
    duplicate job, whatever the plugin's books say."""
    ledger = [e for e in jsonl(project / ".local-exec" / "launches.jsonl") if not e.get("ended")]
    per_key = Counter(e["key"] for e in ledger if e.get("pid"))
    ended = [e for e in jsonl(project / ".local-exec" / "launches.jsonl") if e.get("ended")]
    return {"starts": sum(per_key.values()), "keys": len(per_key),
            "duplicate_jobs": sum(n - 1 for n in per_key.values() if n > 1),
            "per_key": dict(per_key), "cpu_seconds": round(sum(e.get("cpu_seconds") or 0 for e in ended), 4),
            "wall_seconds": round(sum(e.get("wall_seconds") or 0 for e in ended), 4),
            "failed_exits": [e["key"] for e in ended if e.get("exit_code")]}


def artifact_checks(out_dir: Path) -> dict:
    """§3.2: the run's files exist and agree with each other — one loss per update step, a reloadable model,
    predictions, and usage measured by the adapter (not a request cap)."""
    manifest = json.loads((out_dir / "run_manifest.json").read_text(encoding="utf-8"))
    curve = json.loads((out_dir / "curve.json").read_text(encoding="utf-8")) if (out_dir / "curve.json").is_file() else {}
    usage = json.loads((out_dir / "usage.json").read_text(encoding="utf-8")) if (out_dir / "usage.json").is_file() else {}
    steps = (manifest.get("counts") or {}).get("steps")
    losses = curve.get("loss") or []
    return {"files": {n: (out_dir / n).is_file() for n in ("model.json", "predictions.jsonl", "metrics.json",
                                                           "train.log", "curve.json", "usage.json")},
            "curve_steps": len(losses), "manifest_steps": steps,
            "curve_matches_steps": bool(losses) and len(losses) == steps == len(curve.get("step") or []),
            "loss_finite": all(isinstance(v, (int, float)) and v == v for v in losses),
            "usage_measured": bool(usage.get("cpu_seconds")) and usage.get("source") is None
                              and usage.get("pid") == (manifest.get("env") or {}).get("pid"),
            "usage": {k: usage.get(k) for k in ("cpu_seconds", "wall_seconds", "walltime_used_s", "exit_code")}}


def observe(project: Path, tools: Path = REPO_TOOLS) -> dict:
    project = Path(project).resolve()
    marker = json.loads((project / ".research-tree.json").read_text(encoding="utf-8"))
    if type(marker.get("format_version")) is not int or marker["format_version"] != 3:
        raise ValueError("the observer requires a version-3 project marker")
    db = Path(marker["db"])
    root = Path(marker["root"])
    before = sha(db)
    sys.path.insert(0, str(tools))
    from research_db import ResearchDB  # noqa: E402
    snap = ResearchDB(db, "ui/ui").export_snapshot()
    tables = snap["tables"]
    data_dir = project / "code" / "data"
    runs, rescored = [], {}
    for run in tables["run"]:
        attempts = [(run["attempt"], run)] + [(int(k), a) for k, a in (run.get("attempts") or {}).items()]
        for n, a in sorted(attempts, key=lambda x: x[0]):
            entry = {"ref": f"{run['id']}@{n}", "exec_status": a.get("exec_status"), "valid": a.get("valid"),
                     "metric_value": a.get("metric_value"), "imported": bool(a.get("import_record")),
                     "submission_key": a.get("submission_key"), "job_id": a.get("job_id"),
                     "experiment_id": run["experiment_id"], "manifest_path": a.get("manifest_path")}
            if a.get("manifest_path"):
                out_dir = (root / a["manifest_path"]).parent
                try:
                    s = scorer.score_output(out_dir, data_dir)
                    entry["scorer"] = {k: s[k] for k in ("accuracy", "correct", "n", "split", "accuracy_matches",
                                                         "prediction_mismatches")}
                    entry["db_matches_scorer"] = (a.get("metric_value") is not None
                                                  and abs(a["metric_value"] - s["accuracy"]) < 1e-12)
                    rescored[entry["ref"]] = s["accuracy"]
                    entry["artifacts"] = artifact_checks(out_dir)
                except Exception as exc:  # reported, never hidden
                    entry["scorer_error"] = f"{type(exc).__name__}: {exc}"
            runs.append(entry)
    evaluations = []
    for ev in tables["evaluation"]:
        refs = [r for r in ev.get("run_attempt_refs") or [] if r.startswith(ev["experiment_id"] + "/")]
        values = [rescored.get(r) for r in refs]
        mean = statistics.fmean(values) if values and None not in values else None
        primary = next(iter(ev.get("metrics") or {}), None)
        recorded = (ev.get("metrics") or {}).get(primary, {}).get("mean")
        unit = (ev.get("metrics") or {}).get(primary, {}).get("unit")
        scale = 100.0 if unit in ("percentage_point", "percent") else 1.0
        evaluations.append({
            "id": ev["id"], "experiment_id": ev["experiment_id"], "outcome": ev.get("outcome"),
            "gate_passed": ev.get("gate_passed"), "verification_level": ev.get("verification_level"),
            "recorded_mean": recorded, "unit": unit, "independent_mean": None if mean is None else mean * scale,
            "mean_matches": None if mean is None or recorded is None else abs(recorded - mean * scale) < 1e-9,
            "run_refs": refs})
    reader = ResearchDB(db, "ui/ui")
    nodes = []  # S1: each node's claim revision and what its GO eligibility rests on now
    for h in tables["hypothesis"]:
        try:
            elig = reader.get_eligibility(h["id"])
        except Exception as exc:  # reported, never hidden
            elig = {"error": f"{type(exc).__name__}: {exc}"}
        nodes.append({"id": h["id"], "title": h.get("title"), "status": h.get("status"),
                      "claim_revision": h.get("claim_revision"), "claim_sha": h.get("claim_sha"),
                      "eligibility": elig})
    site = subprocess.run([sys.executable, str(tools / "build_site.py"), "--db", str(db), "--check"],
                          capture_output=True, text=True)
    after = sha(db)
    return {
        "project": str(project), "db": str(db), "db_sha256_unchanged": before == after, "phase": marker.get("phase"),
        "data_version": snap["meta"]["data_version"],
        "counts": {t: len(v) for t, v in tables.items()},
        "experiments": [{k: e.get(k) for k in ("id", "kind", "stage", "hypothesis_id", "code_ref", "seeds",
                                                 "evaluation_id", "owner", "method_spec_doc_id", "identity_status")}
                        for e in tables["experiment"]],
        "nodes": nodes,
        "runs": runs, "evaluations": evaluations,
        "obligations": [{k: o.get(k) for k in ("id", "about", "status", "severity", "pattern")}
                        for o in tables["obligation"]],
        "reservations": [{k: r.get(k) for k in ("id", "submission_key", "budget_pool", "accounting_status",
                                                  "reserved_units", "actual_units", "job_id")}
                         for r in tables["reservation"]],
        "jobs": launches(project),
        "attempts": attempt_metrics.metrics(project, tables, root),
        "site": {"exit": site.returncode, "answer": site.stdout.strip() or site.stderr.strip()[-300:]},
        "agent_models": jsonl(root / "logs" / "agent_models.jsonl"),
        "review_calls": [{**{k: c.get(k) for k in ("kind", "about", "dimension", "outcome", "backend", "cost_usd",
                                                    "review_id", "session", "error")},
                          "observed_model": c.get("model"),
                          "raw_output": next((str(f) for f in sorted((root / "cache" / "reviews").glob(f"{c['session']}.v*.json*"))),
                                             None) if c.get("outcome") == "ok" and c.get("session") else None}
                         for c in jsonl(root / "logs" / "review_calls.jsonl")
                         if c.get("outcome") not in ("started", "background_started")],
    }


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("project", type=Path)
    p.add_argument("--tools", type=Path, default=REPO_TOOLS)
    p.add_argument("--out", type=Path)
    args = p.parse_args(argv)
    result = observe(args.project, args.tools)
    text = json.dumps(result, ensure_ascii=False, indent=1)
    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(text + "\n", encoding="utf-8")
    print(text)
    return 0


if __name__ == "__main__":
    sys.exit(main())
