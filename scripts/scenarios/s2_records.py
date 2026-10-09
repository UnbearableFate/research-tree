#!/usr/bin/env python3
"""Write the S2 scenario records of one host attempt from its controller directory (s2.sh via scenario.sh).

    python3 scripts/scenarios/s2_records.py claude 1 [--status PASS] [--note "..."] [--blocked "..."]

Every value comes from evidence: the read-only checkpoints (observer output and the material-usage record), the
database snapshot, the generated project's split identities (code/data/splits.json), the run manifests on disk, the
host's session files and the controller's command log. Raw evidence is archived beside the records with SHA-256 sums.
"""
from __future__ import annotations

import argparse
import json
import re
import shutil
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import record  # noqa: E402
import s0_records as s0  # noqa: E402

REPO = s0.REPO
S = Path("/home/yu/workspace/rt-scenarios/S2")
OUT = s0.OUT


def load(p: Path):
    return json.loads(p.read_text(encoding="utf-8")) if p.is_file() else None


def archive(ctl: Path, dest: Path) -> dict[str, str]:
    out = s0.archive(ctl, dest)
    for src in sorted(ctl.glob("checkpoint-*.json")) + sorted(ctl.glob("usage-*.json")) + sorted(ctl.glob("question-*.txt")):
        shutil.copy(src, dest / src.name)
        out[src.name] = str((dest / src.name).relative_to(REPO))
    sums = {rel: s0.hashlib.sha256((REPO / rel).read_bytes()).hexdigest() for rel in out.values()}
    (dest / "SHA256SUMS.json").write_text(json.dumps(sums, indent=1, sort_keys=True) + "\n", encoding="utf-8")
    return out


def make(host: str, attempt: int, status: str, notes: list[str], blocked: str | None, only: list[str]) -> None:
    ctl = S / f"rt-S2-{host}-a{attempt:02d}.ctl"
    proj = S / f"rt-S2-{host}-a{attempt:02d}"
    files = archive(ctl, OUT / "S2" / host / f"evidence-a{attempt:02d}")
    ck = {p.name[len("checkpoint-"):-5]: load(p) for p in ctl.glob("checkpoint-*.json")}
    usage = {p.name[len("usage-"):-5]: load(p) for p in ctl.glob("usage-*.json")}
    snap = load(ctl / "db-snapshot-final.json") or {"tables": {}}
    text = s0.transcript_text(ctl)
    model, effort = s0.observed(host, ctl)
    commands = []
    for line in (ctl / "commands.jsonl").read_text(encoding="utf-8").splitlines():
        try:
            commands.append(json.loads(line))
        except json.JSONDecodeError:
            commands.append({"event": line, "unparsed": True})
    prompts = [c.get("prompt") for c in commands if c.get("prompt")]
    cmd = "/research-tree" if host == "claude" else "$research-tree"
    ev = lambda name: files.get(name) or files.get("commands.jsonl")  # noqa: E731
    splits = (load(proj / "code" / "data" / "splits.json") or {})
    sha = {name: (entry or {}).get("sha256") for name, entry in (splits.get("splits") or splits).items()
           if isinstance(entry, dict)}
    root = Path((load(proj / ".research-tree.json") or {}).get("root") or "")
    fork = load(ctl / "forked_from.json")
    if fork and str(root).startswith(fork["project"]):  # a fork's records name the original path: read the copy
        root = proj / root.relative_to(fork["project"])
    exps = {e["id"]: e for e in snap["tables"].get("experiment", [])}
    runs = snap["tables"].get("run", [])
    project = (snap["tables"].get("project") or [{}])[0]
    sota = project.get("sota_experiment_id")

    def a(id_, expected, actual, evidence, ok):
        return {"id": id_, "expected": expected, "actual": actual, "evidence": evidence, "verdict": "PASS" if ok else "FAIL"}

    def manifest_split(run_or_attempt: dict) -> str | None:
        snapshot = run_or_attempt.get("manifest_snapshot")
        if snapshot:
            return snapshot.get("eval_split_sha256")
        path = root / (run_or_attempt.get("manifest_path") or "")
        return (load(path) or {}).get("eval_split_sha256") if run_or_attempt.get("manifest_path") else None

    def experiments_at(name):
        return {e["id"]: e for e in (ck.get(name) or {}).get("experiments", [])}

    # -- SC-S2-02: the weak control is never the reference ---------------------------------------------------
    weak = next((e for e in exps.values() if e.get("kind") == "baseline" and e.get("stage") != "confirm"
                 and (e.get("effective_config") or {}).get("lr") == 0.0005), None)
    confirm_base = [e for e in exps.values() if e.get("stage") == "confirm" and e.get("kind") == "baseline"]
    weak_refs = [e["id"] for e in confirm_base if weak and e.get("confirmation_of") == weak["id"]]
    starts_d = (ck.get("D-weak-control") or {}).get("jobs", {}).get("per_key", {})
    starts_e = (ck.get("E-weak-refused") or {}).get("jobs", {}).get("per_key", {})
    # the interface's own refusals (CodedError: CODE: message), never the rules text the agent read
    refusal_weak = re.search(r"CodedError: CONFIRMATION_BASELINE_MISMATCH: [^\n\"]{0,160}", text)
    cand_conf = [e for e in exps.values() if e.get("stage") == "confirm" and e.get("kind") == "method"]
    j_eval = {e["experiment_id"]: e for e in (ck.get("J-confirmed") or {}).get("evaluations", [])}
    k_exps, j_exps = experiments_at("K-late-control"), experiments_at("J-confirmed")
    first_conf = sorted(cand_conf, key=lambda e: e["id"])[0] if cand_conf else None
    s202 = [
        a("W1", "the weak control (sgd lr 0.0005) is a real, evaluated baseline-kind experiment",
          weak and {"id": weak["id"], "evaluation": weak.get("evaluation_id")}, ev("checkpoint-D-weak-control.json"),
          bool(weak and weak.get("evaluation_id"))),
        a("W2", "using it as the confirmation reference is refused; no confirmation job starts for that request",
          {"refusal": refusal_weak.group(0) if refusal_weak else None, "confirmation_of_weak": weak_refs,
           "new_starts": sorted(set(starts_e) - set(starts_d))}, ev("checkpoint-E-weak-refused.json"),
          bool(refusal_weak) and not weak_refs and not [k for k in set(starts_e) - set(starts_d) if "confirm" in k.lower()]),
        a("W3", "a control created later moves neither the batch's reference nor the confirmation's comparison",
          first_conf and {"J": (j_exps.get(first_conf["id"]) or {}).get("evaluation_id"),
                          "K": (k_exps.get(first_conf["id"]) or {}).get("evaluation_id"),
                          "baseline": first_conf.get("baseline_experiment_id")},
          ev("checkpoint-K-late-control.json"),
          bool(first_conf) and (j_exps.get(first_conf["id"]) or {}).get("evaluation_id")
          == (k_exps.get(first_conf["id"]) or {}).get("evaluation_id")
          and exps.get(first_conf.get("baseline_experiment_id") or "", {}).get("confirmation_of") == sota)]

    # -- SC-S2-01: the frozen candidate against the reference re-run on c1 ---------------------------------
    docs = {d["id"]: d for d in snap["tables"].get("document", [])}
    c1_base = next((e for e in confirm_base if e.get("confirmation_of") == sota), None)
    c1_runs = [r for r in runs if c1_base and r["experiment_id"] == c1_base["id"] and r.get("valid")]
    conf_runs = [r for r in runs if first_conf and r["experiment_id"] == first_conf["id"] and r.get("valid")]
    final_evals = {e["experiment_id"]: e for e in (ck.get("final") or {}).get("evaluations", [])}
    s201 = [
        a("F1", "the reference re-runs on the c1 material (its manifests carry c1's split identity)",
          {"experiment": c1_base and c1_base["id"], "splits": [manifest_split(r) for r in c1_runs], "c1": sha.get("c1")},
          files.get("db-snapshot-final.json"), bool(c1_runs) and all(manifest_split(r) == sha.get("c1") for r in c1_runs)),
        a("F2", "the candidate's confirmation runs on c1 and its evaluation equals the independent scorer",
          {"experiment": first_conf and first_conf["id"], "splits": [manifest_split(r) for r in conf_runs],
           "evaluation": final_evals.get(first_conf["id"]) if first_conf else None}, ev("checkpoint-final.json"),
          bool(conf_runs) and all(manifest_split(r) == sha.get("c1") for r in conf_runs)
          and bool((final_evals.get(first_conf["id"]) or {}).get("mean_matches"))),
        a("F3", "candidate, batch, baseline and material agree in the database",
          first_conf and {"candidate_spec": first_conf.get("candidate_spec_doc_id"),
                          "batch": first_conf.get("confirmation_batch_doc_id"),
                          "batch_type": (docs.get(first_conf.get("confirmation_batch_doc_id") or "") or {}).get("doc_type"),
                          "baseline": first_conf.get("baseline_experiment_id")},
          files.get("db-snapshot-final.json"),
          bool(first_conf) and (docs.get(first_conf.get("candidate_spec_doc_id") or "") or {}).get("doc_type") == "candidate_spec"
          and (docs.get(first_conf.get("confirmation_batch_doc_id") or "") or {}).get("doc_type") == "confirmation_batch"
          and bool(c1_base) and first_conf.get("baseline_experiment_id") == c1_base["id"])]

    # -- SC-S2-04: execution fault, restart, repeated import, no re-run of a valid result -------------------
    r1042 = next((r for r in runs if first_conf and r["experiment_id"] == first_conf["id"] and r["seed"] == 1042), None)
    attempts = ({**{k: v for k, v in (r1042.get("attempts") or {}).items()}, str(r1042["attempt"]): r1042}
                if r1042 else {})
    events_h = [e for e in ((usage.get("H-imported") or {}).get("material_usage") or {}).get("events", [])]
    events_i = [e for e in ((usage.get("I-after-restart") or {}).get("material_usage") or {}).get("events", [])]
    mine = lambda events: [e for e in events if first_conf and e.get("experiment") == first_conf["id"]]  # noqa: E731
    pairs = ((final_evals.get(first_conf["id"]) if first_conf else None) or {}).get("run_refs") or []
    s204 = [
        a("G1", "the input-path failure is kept as attempt 1; the retry is attempt 2 of the same run",
          {k: v.get("exec_status") for k, v in attempts.items()}, files.get("db-snapshot-final.json"),
          attempts.get("1", {}).get("exec_status") == "failed" and attempts.get("2", {}).get("exec_status") == "succeeded"),
        a("G2", "the material-usage record keeps both attempts", [e.get("run") for e in mine(events_h)],
          ev("usage-H-imported.json"), any(str(e.get("run", "")).endswith("@1") and "1042" in str(e.get("run")) for e in mine(events_h))
          and any(str(e.get("run", "")).endswith("@2") and "1042" in str(e.get("run")) for e in mine(events_h))),
        a("G3", "the restart leaves the material-usage record as it was", {"before": len(events_h), "after": len(events_i)},
          ev("usage-I-after-restart.json"), bool(events_h) and events_h == events_i[:len(events_h)] and len(events_i) == len(events_h)),
        a("G4", "a repeated import adds no pair: the evaluation rests on one attempt per seed", pairs,
          ev("checkpoint-final.json"), len(pairs) == len({p.split("@")[0] for p in pairs}) == 3),
        a("G5", "a valid imported result cannot be marked invalid to run it again",
          bool(re.search(r"CodedError: CONFIRMATION_MATERIAL_REUSED: [^\n\"]{0,60}imported confirmation result", text)),
          next((v for k, v in files.items() if k.startswith("session:")), files["commands.jsonl"]),
          bool(re.search(r"CodedError: CONFIRMATION_MATERIAL_REUSED: [^\n\"]{0,60}imported confirmation result", text)))]

    # -- SC-S2-03: a retuned rate after the feedback -----------------------------------------------------------
    retune_refusals = sorted(set(re.findall(r"CodedError: (CANDIDATE_IDENTITY_MISMATCH|CONFIRMATION_MATERIAL_REUSED|"
                                            r"CONFIRMATION_BASELINE_MISMATCH): ", text)))
    later = [e for e in cand_conf if first_conf and e["id"] != first_conf["id"]]
    later_runs = [r for r in runs if any(r["experiment_id"] == e["id"] for e in later)]
    s203 = [
        a("R1", "the old spec, the old batch, c1 and another node with the retuned rate are refused",
          retune_refusals, files["commands.jsonl"],
          "CANDIDATE_IDENTITY_MISMATCH" in retune_refusals or "CONFIRMATION_MATERIAL_REUSED" in retune_refusals),
        a("R2", "a new candidate's confirmation, if any, runs on c2 and never on c1",
          {"experiments": [e["id"] for e in later], "splits": sorted({str(manifest_split(r)) for r in later_runs}),
           "c2": sha.get("c2")}, files.get("db-snapshot-final.json"),
          all(manifest_split(r) in (sha.get("c2"), None) for r in later_runs)
          and not any(manifest_split(r) == sha.get("c1") for r in later_runs))]

    # -- SC-COMMON-01 ----------------------------------------------------------------------------------------
    obs = ck.get("final") or {}
    before, after = ck.get("M-c2") or {}, ck.get("N-after-restart") or {}
    base = next((e for e in obs.get("experiments", []) if e["kind"] == "baseline" and e["id"] == sota), None)
    base_runs = [r for r in obs.get("runs", []) if base and r.get("valid") and r["experiment_id"] == base["id"]]
    base_ev = next((e for e in obs.get("evaluations", []) if base and e["experiment_id"] == base["id"]), None)
    started = [c for c in (f"{cmd} prepare", f"{cmd} init", f"{cmd} confirm") if c in prompts]
    refs = lambda o: sorted(r["ref"] for r in o.get("runs", []))  # noqa: E731
    resume_same = bool(before) and refs(before) == refs(after) and \
        (before.get("jobs") or {}).get("per_key") == (after.get("jobs") or {}).get("per_key")
    common = [
        a("C1", "prepare, init and confirm entered through the host's own command", started, files["commands.jsonl"], len(started) == 3),
        a("C2", "every valid SOTA run rescored independently equals the DB value; artifacts present",
          [{"ref": r["ref"], "db": r["metric_value"], "scorer": (r.get("scorer") or {}).get("accuracy")} for r in base_runs],
          ev("checkpoint-final.json"), bool(base_runs) and all(r.get("db_matches_scorer") and r["artifacts"]["curve_matches_steps"]
                                                               and r["artifacts"]["usage_measured"] for r in base_runs)),
        a("C3", "the SOTA evaluation equals the independent mean", base_ev and {k: base_ev[k] for k in ("id", "recorded_mean", "independent_mean")},
          ev("checkpoint-final.json"), bool(base_ev and base_ev["mean_matches"])),
        a("C4", "page built and fresh; the observer never changed the DB", {"site": obs.get("site"), "db_unchanged": obs.get("db_sha256_unchanged")},
          ev("checkpoint-final.json"), (obs.get("site") or {}).get("exit") == 0 and bool(obs.get("db_sha256_unchanged"))),
        a("C5", "no duplicate process start", obs.get("jobs"), ev("checkpoint-final.json"), (obs.get("jobs") or {}).get("duplicate_jobs") == 0),
        a("C6", "the resumed session re-ran nothing", {"runs": refs(after), "starts": (after.get("jobs") or {}).get("per_key")},
          ev("checkpoint-N-after-restart.json"), resume_same)]
    src = (ctl / "source_ref.txt").read_text().split()
    sessions = [p for key, p in files.items() if key.startswith("session:")]
    for sc, assertions in (("SC-COMMON-01", common), ("SC-S2-01", s201), ("SC-S2-02", s202), ("SC-S2-03", s203),
                           ("SC-S2-04", s204)):
        if fork and sc == "SC-COMMON-01":
            continue  # the opening is another attempt's (forked_from): SC-COMMON-01 stays with the unbroken run
        r = record.template(sc, "S2", host, attempt)
        failed = [x["id"] for x in assertions if x["verdict"] != "PASS"]
        stopped = blocked and (not only or sc in only)
        r.update({"status": ("BLOCKED" if stopped else "FAIL") if failed else status,
                  **({"failures": [f"BLOCKED: {blocked}"]} if stopped and failed else {}),
                  "source_ref": src[0], "uncommitted_changes": src[1:], "project_root": str(proj),
                  "build_path": f"rt-scenarios/archive/build-S2-{host}-a{attempt:02d}.tar.gz",
                  "loaded_plugin_path": str(S / f"dist-{host}-S2a{attempt:02d}/plugins/research-tree"),
                  "observed_model": model, "observed_effort": effort,
                  "session_id": Path(sessions[0]).name.split(".")[0] if sessions else None,
                  "session_transcripts": sessions, "commands": [c.get("prompt") or c.get("event") for c in commands],
                  "fault_plan": files.get("fault-plan.json"), "observer_results": ev("checkpoint-final.json"),
                  "review_calls": obs.get("review_calls"), "assertions": assertions, "raw_evidence_paths": list(files.values()),
                  "resume_evidence": {"sessions": sessions, "question": [p for p in prompts if "恢复当前工作" in p],
                                      "observer_before": ev("checkpoint-M-c2.json"),
                                      "observer_after": ev("checkpoint-N-after-restart.json"), "unchanged": resume_same},
                  "remaining_gaps": notes,
                  "forked_from": fork and {"snapshot": fork.get("snapshot"), "attempt": fork["attempt"],
                                           "project": fork["project"]},
                  "resource_usage": {"cpu_seconds": (obs.get("jobs") or {}).get("cpu_seconds"),
                                     "job_wall_seconds": (obs.get("jobs") or {}).get("wall_seconds"),
                                     "plugin_node_seconds": None, "known_model_cost_usd": None,
                                     "unknown_cost_calls": ["the interactive host session's own cost has no raw bill"]}})
        d = record.record_dir(OUT, r)
        d.mkdir(parents=True, exist_ok=True)
        (d / "record.json").write_text(json.dumps(r, ensure_ascii=False, indent=1, default=str) + "\n", encoding="utf-8")
        print(d.relative_to(REPO), r["status"], failed)


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("host", choices=("claude", "codex"))
    p.add_argument("attempt", type=int)
    p.add_argument("--status", default="PASS")
    p.add_argument("--note", action="append", default=[])
    p.add_argument("--blocked")
    p.add_argument("--blocked-scenario", action="append", default=[])
    args = p.parse_args()
    make(args.host, args.attempt, args.status, args.note, args.blocked, args.blocked_scenario)
    return 0


if __name__ == "__main__":
    sys.exit(main())
