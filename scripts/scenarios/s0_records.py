#!/usr/bin/env python3
"""Write the S0 scenario records of one host attempt from its controller directory (S0 final review S0-r3).

    python3 scripts/scenarios/s0_records.py claude 3 [--status PASS] [--note "..."]

Everything a record states is read from evidence, never typed in: the observed model and effort from the host's
own session files, the commands from commands.jsonl, the product's refusal from the session transcript, the
numbers from the read-only observer and the database snapshot, the resume check from the observer files taken
before and after the resumed session. The raw evidence is archived in the repository next to the records
(plans/design/test-logs/scenarios/S0/<host>/evidence-aNN/, transcripts gzip-compressed) with SHA-256 sums, so a
reviewer can check every PASS from the repository alone.
"""
from __future__ import annotations

import argparse
import gzip
import hashlib
import json
import re
import shutil
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(Path(__file__).resolve().parent))
import record  # noqa: E402

S = Path("/home/yu/workspace/rt-scenarios/S0")
OUT = REPO / "plans/design/test-logs/scenarios"


def load(p: Path):
    return json.loads(p.read_text(encoding="utf-8"))


def jsonl(p: Path) -> list[dict]:
    return [json.loads(line) for line in p.read_text(encoding="utf-8").splitlines() if line.strip()] if p.is_file() else []


def archive(ctl: Path, dest: Path) -> dict[str, str]:
    """Copy the raw evidence into the repository; returns {name: repo-relative path}."""
    dest.mkdir(parents=True, exist_ok=True)
    out = {}
    for name in ("commands.jsonl", "fault-plan.json", "scenario.json", "agent_models.jsonl", "review_calls.jsonl",
                 "observer-before-report.json", "observer-before-resume.json", "observer-after-resume.json",
                 "observer-final.json", "db-snapshot-final.json", "baseline-report.wrong.md",
                 "baseline-report.corrected.md", "source_ref.txt"):
        if (ctl / name).is_file():
            shutil.copy(ctl / name, dest / name)
            out[name] = str((dest / name).relative_to(REPO))
    for name in ("launches.jsonl", "events.jsonl"):
        src = ctl / "local-exec-state" / name
        if src.is_file():
            shutil.copy(src, dest / f"local-exec-{name}")
            out[f"local-exec-{name}"] = str((dest / f"local-exec-{name}").relative_to(REPO))
    for session in sorted((ctl / "sessions").glob("*.jsonl")):
        target = dest / "sessions" / (session.name + ".gz")
        target.parent.mkdir(exist_ok=True)
        with session.open("rb") as src, open(target, "wb") as raw, \
                gzip.GzipFile(fileobj=raw, mode="wb", compresslevel=9, mtime=0) as gz:
            shutil.copyfileobj(src, gz)
        out[f"session:{session.name}"] = str(target.relative_to(REPO))
    sums = {rel: hashlib.sha256((REPO / rel).read_bytes()).hexdigest() for rel in out.values()}
    (dest / "SHA256SUMS.json").write_text(json.dumps(sums, indent=1, sort_keys=True) + "\n", encoding="utf-8")
    return out


def transcript_text(ctl: Path) -> str:
    return "\n".join(p.read_text(encoding="utf-8", errors="replace") for p in sorted((ctl / "sessions").glob("*.jsonl")))


def observed(host: str, ctl: Path) -> tuple[str | list, str | None]:
    """The main session's model and effort, from the host's structured session records only (Claude: each
    assistant message's model and the line's effort; Codex: turn_context model and effort) — never from text."""
    models, efforts = set(), set()
    for session in sorted((ctl / "sessions").glob("*.jsonl")):
        for entry in jsonl(session):
            if host == "claude" and entry.get("type") == "assistant" and not entry.get("isSidechain"):
                models.add((entry.get("message") or {}).get("model"))
                efforts.add(entry.get("effort"))
            elif host == "codex" and entry.get("type") == "turn_context":
                payload = entry.get("payload") or {}
                models.add(payload.get("model"))
                efforts.add(payload.get("effort") or payload.get("reasoning_effort"))
    models.discard(None), efforts.discard(None)
    models.discard("<synthetic>")
    models, efforts = sorted(models), sorted(efforts)
    return (models[0] if len(models) == 1 else models), (efforts[0] if len(efforts) == 1 else None)


def make(host: str, attempt: int, status: str, notes: list[str]) -> None:
    ctl = S / f"rt-S0-{host}-a{attempt:02d}.ctl"
    proj = S / f"rt-S0-{host}-a{attempt:02d}"
    files = archive(ctl, OUT / "S0" / host / f"evidence-a{attempt:02d}")
    obs, before, after = (load(ctl / n) for n in ("observer-final.json", "observer-before-resume.json",
                                                   "observer-after-resume.json"))
    snap = load(ctl / "db-snapshot-final.json")
    model, effort = observed(host, ctl)
    commands = jsonl(ctl / "commands.jsonl")
    prompts = [c.get("prompt") for c in commands if c.get("prompt")]
    cmd = "/research-tree" if host == "claude" else "$research-tree"
    text = transcript_text(ctl)
    # the interface's own refusal of the wrong report (its error text), not any mention of the code in the rules
    refusal = re.search(r"STAT_MISMATCH: D-\d+ \([^)]*\): numbers not found in their sources[^\n\"]{0,200}", text)
    base = next((e for e in obs["experiments"] if e["kind"] == "baseline"), None)
    runs = [r for r in obs["runs"] if r.get("valid") and base and r["experiment_id"] == base["id"]]
    ev = next((e for e in obs["evaluations"] if base and e["experiment_id"] == base["id"]), None)
    ev_rec = next((e for e in snap["tables"]["evaluation"] if ev and e["id"] == ev["id"]), {})
    results = [(d["id"], d["status"]) for d in snap["tables"]["document"] if d["doc_type"] == "experiment_result"]
    ok_runs = bool(runs) and all(r.get("db_matches_scorer") and r["artifacts"]["curve_matches_steps"]
                                 and r["artifacts"]["usage_measured"] for r in runs)
    started = [c for c in (f"{cmd} prepare", f"{cmd} init", f"{cmd} confirm") if c in prompts]
    refs = lambda o: sorted(r["ref"] for r in o["runs"])  # noqa: E731
    resume_same = (refs(before) == refs(after) and before["jobs"]["per_key"] == after["jobs"]["per_key"]
                   and before["counts"]["evaluation"] == after["counts"]["evaluation"])
    sessions = [p for k, p in files.items() if k.startswith("session:")]
    raw = [p for k, p in files.items()]

    def a(id_, expected, actual, evidence, ok):
        return {"id": id_, "expected": expected, "actual": actual, "evidence": evidence, "verdict": "PASS" if ok else "FAIL"}
    common = [
        a("C1", "prepare, init and confirm entered through the host's own command", started, files["commands.jsonl"],
          len(started) == 3),
        a("C2", "every valid baseline run rescored independently equals the DB value; curve, model, predictions and "
                "measured usage present", [{"ref": r["ref"], "db": r["metric_value"], "scorer": r["scorer"]["accuracy"]}
                                           for r in runs], files["observer-final.json"], ok_runs and len(runs) == 3),
        a("C3", "the baseline evaluation's mean equals the mean of the independent scores (pp)",
          ev and {"evaluation": ev["id"], "recorded": ev["recorded_mean"], "independent": ev["independent_mean"]},
          files["observer-final.json"], bool(ev and ev["mean_matches"])),
        a("C4", "page built and build_site --check fresh; the observer never changed the DB",
          {"site": obs["site"], "db_unchanged": obs["db_sha256_unchanged"]}, files["observer-final.json"],
          obs["site"]["exit"] == 0 and obs["db_sha256_unchanged"]),
        a("C5", "no duplicate process start for any submission key", obs["jobs"],
          files.get("local-exec-launches.jsonl", files["observer-final.json"]), obs["jobs"]["duplicate_jobs"] == 0),
        a("C6", "the resumed session re-ran nothing: run list, process starts and evaluations equal before and after it",
          {"runs": refs(after), "starts": after["jobs"]["per_key"], "evaluations": after["counts"]["evaluation"]},
          files["observer-after-resume.json"], resume_same)]
    s02 = [
        a("R1", "the wrong report (acc-s42 0.905, mean 82.5) is refused by the product's numeric check; no evaluation "
                "rests on it", {"refusal": refusal.group(0) if refusal else None, "result_documents": results,
                                "evaluation_result_doc": ev_rec.get("result_doc_id")},
          sessions[0] if sessions else files["commands.jsonl"],
          bool(refusal) and any(s == "draft" for _, s in results)
          and dict(results).get(ev_rec.get("result_doc_id")) == "current"),
        a("R2", "after correction the evaluation equals the independent scorer mean", ev and ev["recorded_mean"],
          files["observer-final.json"], bool(ev and ev["mean_matches"]))]
    src = (ctl / "source_ref.txt").read_text().split()
    resume = {"new_session": sessions[-1] if sessions else None,
              "question": [p for p in prompts if "恢复当前工作" in p],
              "observer_before": files["observer-before-resume.json"],
              "observer_after": files["observer-after-resume.json"], "unchanged": resume_same}
    if host == "codex":
        resume["attach"] = bool(re.search(r'research_control[^\n]{0,200}attach|"action":\s*"attach"', text))
    for sc, assertions in (("SC-COMMON-01", common), ("SC-S0-01", [common[1], common[2], common[4], common[5]]),
                           ("SC-S0-02", s02)):
        r = record.template(sc, "S0", host, attempt)
        failed = [x["id"] for x in assertions if x["verdict"] != "PASS"]
        r.update({"status": "FAIL" if failed else status, "source_ref": src[0], "uncommitted_changes": src[1:],
                  "project_root": str(proj), "build_path": str(S / f"dist-{host}-S0a{attempt:02d}"),
                  "loaded_plugin_path": (str(S / f"dist-claude-S0a{attempt:02d}/plugins/research-tree") if host == "claude"
                                         else str(S / f"codex-home-S0a{attempt:02d}/plugins/cache/research-tree/research-tree/0.1.0")),
                  "observed_model": model, "observed_effort": effort,
                  "session_id": Path(sessions[0]).name.split(".")[0] if sessions else None,
                  "session_transcripts": sessions, "commands": [c.get("prompt") or c.get("event") or c.get("what")
                                                                for c in commands],
                  "fault_plan": files.get("fault-plan.json"), "observer_results": files["observer-final.json"],
                  "review_calls": obs["review_calls"], "assertions": assertions, "raw_evidence_paths": raw,
                  "resume_evidence": resume, "remaining_gaps": notes,
                  "resource_usage": {"cpu_seconds": obs["jobs"]["cpu_seconds"], "job_wall_seconds": obs["jobs"]["wall_seconds"],
                                     "plugin_node_seconds": sum(x.get("actual_units") or 0 for x in obs["reservations"]) or None,
                                     "known_model_cost_usd": None,
                                     "unknown_cost_calls": ["the interactive host session's own cost has no raw bill"]}})
        d = record.record_dir(OUT, r)
        d.mkdir(parents=True, exist_ok=True)
        (d / "record.json").write_text(json.dumps(r, ensure_ascii=False, indent=1, default=str) + "\n", encoding="utf-8")
        print(d.relative_to(REPO), r["status"], failed, record.problems(r, REPO)[:6])


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("host", choices=("claude", "codex"))
    p.add_argument("attempt", type=int)
    p.add_argument("--status", default="PASS")
    p.add_argument("--note", action="append", default=[])
    args = p.parse_args()
    make(args.host, args.attempt, args.status, args.note)
    return 0


if __name__ == "__main__":
    sys.exit(main())
