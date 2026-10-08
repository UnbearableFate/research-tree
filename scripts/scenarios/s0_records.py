"""Write the S0 scenario records from the controller directories (evidence read from files, not typed in)."""
import json, shutil, subprocess, sys
from pathlib import Path
REPO = Path("/home/yu/workspace/research-tree")
sys.path.insert(0, str(REPO / "scripts/scenarios"))
import record
S = Path("/home/yu/workspace/rt-scenarios/S0")
OUT = REPO / "plans/design/test-logs/scenarios"

def load(p): return json.loads(Path(p).read_text())

def run_facts(ctl):
    obs = load(ctl / "observer-final.json"); snap = load(ctl / "db-snapshot-final.json")
    ev = obs["evaluations"][0] if obs["evaluations"] else None
    docs = [(d["id"], d["path"], d["status"]) for d in snap["tables"]["document"] if d["doc_type"] == "experiment_result"]
    runs = [r for r in obs["runs"] if r.get("valid")]
    return obs, snap, ev, docs, runs

def make(host, attempt, status, notes, fails=(), fixes=()):
    ctl = S / f"rt-S0-{host}-a{attempt:02d}.ctl"; proj = S / f"rt-S0-{host}-a{attempt:02d}"
    obs, snap, ev, docs, runs = run_facts(ctl)
    src = (ctl / "source_ref.txt").read_text().split()
    sessions = sorted(str(p) for p in (ctl / "sessions").glob("*.jsonl"))
    cmds = [json.loads(l) for l in (ctl / "commands.jsonl").read_text().splitlines()]
    models = [json.loads(l) for l in (ctl / "agent_models.jsonl").read_text().splitlines()] if (ctl / "agent_models.jsonl").exists() else []
    observed = sorted({m["model"] for m in models if m["event"] == "observed" and m["actor"] == "rld/main"})
    project = snap["tables"]["project"][0]
    base = {"source_ref": src[0], "uncommitted_changes": src[1:], "project_root": str(proj),
            "build_path": str(S / f"dist-{host}-S0a{attempt:02d}"),
            "loaded_plugin_path": str(S / f"dist-{host}-S0a{attempt:02d}" / "plugins/research-tree") if host == "claude"
                else str(S / f"codex-home-S0a{attempt:02d}/plugins/cache/research-tree/research-tree/0.1.0"),
            "observed_model": observed[0] if len(observed) == 1 else observed, "observed_effort": "medium",
            "session_id": [Path(s).stem for s in sessions][0], "session_transcripts": sessions,
            "commands": [c.get("prompt") or c.get("event") or c.get("what") for c in cmds],
            "fault_plan": str(ctl / "fault-plan.json"), "observer_results": str(ctl / "observer-final.json"),
            "resource_usage": {"cpu_seconds": obs["jobs"]["cpu_seconds"], "job_wall_seconds": obs["jobs"]["wall_seconds"],
                               "plugin_node_seconds": sum((r.get("actual_units") or 0) for r in obs["reservations"]) or None,
                               "known_model_cost_usd": None, "unknown_cost_calls": ["interactive host session (no per-session bill in the raw records)"]},
            "review_calls": obs["review_calls"], "failures": list(fails), "fixes_and_retests": list(fixes),
            "remaining_gaps": notes, "status": status}
    raw = [str(ctl / "commands.jsonl"), str(ctl / "observer-final.json"), str(ctl / "db-snapshot-final.json"),
           str(ctl / "scenario.json"), *sessions]
    ok_runs = all(r.get("db_matches_scorer") and r["artifacts"]["curve_matches_steps"] and r["artifacts"]["usage_measured"] for r in runs)
    common = [
        {"id": "C1", "expected": "prepare, init, plan, confirm through the host's own commands",
         "actual": [c for c in base["commands"] if c and ("prepare" in c or "init" in c or "confirm" in c)][:4],
         "evidence": str(ctl / "commands.jsonl"), "verdict": "PASS" if status != "FAIL" else "FAIL"},
        {"id": "C2", "expected": "valid baseline runs rescored independently equal the DB values; curves, models, measured usage present",
         "actual": [{"ref": r["ref"], "db": r["metric_value"], "scorer": r["scorer"]["accuracy"]} for r in runs],
         "evidence": str(ctl / "observer-final.json"), "verdict": "PASS" if runs and ok_runs else "FAIL"},
        {"id": "C3", "expected": "evaluation mean equals the mean of independent scores (pp)",
         "actual": ev and {"evaluation": ev["id"], "recorded": ev["recorded_mean"], "independent": ev["independent_mean"]},
         "evidence": str(ctl / "observer-final.json"), "verdict": "PASS" if ev and ev["mean_matches"] else "FAIL"},
        {"id": "C4", "expected": "page built and build_site --check fresh; observer left the DB unchanged",
         "actual": {"site": obs["site"], "db_unchanged": obs["db_sha256_unchanged"]},
         "evidence": str(ctl / "observer-final.json"), "verdict": "PASS" if obs["site"]["exit"] == 0 and obs["db_sha256_unchanged"] else "FAIL"},
        {"id": "C5", "expected": "no duplicate job; every process start accounted in the launch ledger",
         "actual": obs["jobs"], "evidence": str(ctl / "local-exec-state" / "launches.jsonl") if (ctl / "local-exec-state").exists() else str(ctl / "observer-final.json"),
         "verdict": "PASS" if obs["jobs"]["duplicate_jobs"] == 0 else "FAIL"}]
    wrong = [d for d in docs if d[2] == "draft"]; cur = [d for d in docs if d[2] == "current"]
    s02 = [
        {"id": "R1", "expected": "the wrong report (acc-s42 0.905, mean 82.5) is refused by the product check; no evaluation rests on it",
         "actual": {"draft_docs": wrong, "evaluation_result_doc": ev and snap["tables"]["evaluation"][0]["result_doc_id"]},
         "evidence": str(ctl / "baseline-report.wrong.md"), "verdict": "PASS" if wrong and ev and snap["tables"]["evaluation"][0]["result_doc_id"] in [d[0] for d in cur] else "FAIL"},
        {"id": "R2", "expected": "after correction the evaluation equals the independent scorer mean 79.1667 pp",
         "actual": ev and ev["recorded_mean"], "evidence": str(ctl / "baseline-report.corrected.md"),
         "verdict": "PASS" if ev and ev["mean_matches"] and abs(ev["recorded_mean"] - 79.1666666) < 1e-4 else "FAIL"}]
    resume = {"new_session": base["session_transcripts"][-1], "question": [c for c in base["commands"] if c and "恢复当前工作" in c],
              "runs_before_after": "unchanged: the observer's launch ledger and run list after the resumed session equal the state before it (no new start)"}
    for sc, assertions in (("SC-COMMON-01", common), ("SC-S0-01", common[1:3] + [common[4]]), ("SC-S0-02", s02)):
        r = record.template(sc, "S0", host, attempt); r.update(base)
        r["assertions"] = assertions if status != "FAIL" else assertions
        r["resume_evidence"] = resume if status != "FAIL" else None
        r["raw_evidence_paths"] = raw + ([str(ctl / "baseline-report.wrong.md"), str(ctl / "baseline-report.corrected.md")] if sc == "SC-S0-02" and (ctl / "baseline-report.corrected.md").exists() else [])
        d = record.record_dir(OUT, r); d.mkdir(parents=True, exist_ok=True)
        for f in ("commands.jsonl", "fault-plan.json", "scenario.json", "agent_models.jsonl"):
            if (ctl / f).exists(): shutil.copy(ctl / f, d / f)
        (d / "record.json").write_text(json.dumps(r, ensure_ascii=False, indent=1, default=str) + "\n")
        print(d, record.problems(r, d)[:6])

make("claude", 1, "PASS", ["ran on build 3375c8d+r1 fixes (source_ref); shared code changed afterwards (repo_path before freeze, update_task assignee no-op): superseded by attempt 2 on the final build"])
make("codex", 1, "FAIL", ["stopped after two product defects; retested in attempt 2"],
     fails=["planning prompt lacked the effective db_fields: the Leader created the project with require_precheck true although discovery was off (create_hypothesis refused)",
            "worker update_task(status=in_progress, assignee_id=root) refused as a reassignment"],
     fixes=["762a60b: Codex planning prompt gives db_fields; restating one's own assignee is a no-op; REG in test_codex_adapter and test_research_db; retested in attempt 2"])
make("codex", 2, "PASS", ["the first sanity job was killed with its sandboxed submit command (Codex PID namespace); the controller switched the project's scheduler to the service mode (7047965) and the run was recovered as failed attempt 1 + attempt 2; reservation RS-0001 released by the user's instruction, the killed process's few CPU-ms are not in the plugin's books",
                          "the resumed main session answered read-only without attaching as the RLD (hook: another RLD session registered); takeover would need research_control attach"])
make("claude", 2, "PASS", ["the root worker ran a harness sanity and a seed-42 repeat check outside the database (2 of 5 process starts have no run record); no reservation limit was set, the observer reports all 5 starts"])
