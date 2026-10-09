#!/usr/bin/env python3
"""Write the S1 scenario records of one host attempt from its controller directory (run_s1.sh).

    python3 scripts/scenarios/s1_records.py claude 2 [--status PASS] [--note "..."]

Every value comes from evidence: the read-only checkpoints the controller took after each step (observer output,
discovery candidate pool and gate state), the database snapshot, the host's own session files and the controller's
command log. The raw evidence is archived next to the records with SHA-256 sums (s0_records.archive).
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
S = Path("/home/yu/workspace/rt-scenarios/S1")
OUT = s0.OUT
# checkpoint names of the controller since attempt 2; attempt 1 used the first ordering (reviews after the change)
LAYOUT = {"v2": {"zebra": "A-discovery", "alpha_reviewed": "B-alpha-reviewed", "changed": "C-alpha-changed",
                 "restarted": "D-gate-after-restart", "rereviewed": "E-alpha-rereviewed"},
          "v1": {"zebra": "A-discovery", "alpha_reviewed": "B-alpha-added", "changed": "C-alpha-changed",
                 "restarted": "E-gate-after-restart", "rereviewed": "D-alpha-reviewed"}}
CLAIM_BOUND = ("method_code", "novelty", "theory")
EVAL_BOUND = ("numbers", "protocol")


def load(p: Path):
    return json.loads(p.read_text(encoding="utf-8")) if p.is_file() else None


def archive(ctl: Path, dest: Path) -> dict[str, str]:
    out = s0.archive(ctl, dest)
    for src in sorted(ctl.glob("checkpoint-*.json")) + sorted(ctl.glob("candidates-*.json")) + \
            sorted(ctl.glob("discovery-state-*.json")) + sorted(ctl.glob("fault-*.json")):
        shutil.copy(src, dest / src.name)
        out[src.name] = str((dest / src.name).relative_to(REPO))
    sums = {rel: s0.hashlib.sha256((REPO / rel).read_bytes()).hexdigest() for rel in out.values()}
    (dest / "SHA256SUMS.json").write_text(json.dumps(sums, indent=1, sort_keys=True) + "\n", encoding="utf-8")
    return out


def make(host: str, attempt: int, status: str, notes: list[str], layout: str, blocked: str | None = None,
         only: list[str] | None = None) -> None:
    ctl = S / f"rt-S1-{host}-a{attempt:02d}.ctl"
    proj = S / f"rt-S1-{host}-a{attempt:02d}"
    names = LAYOUT[layout]
    files = archive(ctl, OUT / "S1" / host / f"evidence-a{attempt:02d}")
    ck = {p.name[len("checkpoint-"):-5]: load(p) for p in ctl.glob("checkpoint-*.json")}
    cands = {p.name[len("candidates-"):-5]: load(p) for p in ctl.glob("candidates-*.json")}
    gates = {p.name[len("discovery-state-"):-5]: (load(p) or {}).get("gate") or {} for p in ctl.glob("discovery-state-*.json")}
    snap = load(ctl / "db-snapshot-final.json") or {"tables": {}}
    text = s0.transcript_text(ctl)
    model, effort = s0.observed(host, ctl)
    commands = []
    for line in (ctl / "commands.jsonl").read_text(encoding="utf-8").splitlines():
        try:
            commands.append(json.loads(line))
        except json.JSONDecodeError:  # kept as written (attempt 1's controller logged one event with broken quoting)
            commands.append({"event": line, "unparsed": True})
    prompts = [c.get("prompt") for c in commands if c.get("prompt")]
    cmd = "/research-tree" if host == "claude" else "$research-tree"
    ev_file = lambda name: files.get(name) or files.get("commands.jsonl")  # noqa: E731

    def a(id_, expected, actual, evidence, ok):
        return {"id": id_, "expected": expected, "actual": actual, "evidence": evidence,
                "verdict": "PASS" if ok else "FAIL"}

    def pool(name):
        return {c["id"]: c for c in ((cands.get(name) or {}).get("candidates") or [])}

    # the reviewer's raw output: pi writes .jsonl, the Claude CLI .json (older checkpoints named only .jsonl)
    research_root = Path((load(proj / ".research-tree.json") or {}).get("root") or "")
    for chk in ck.values():
        for call in (chk or {}).get("review_calls") or []:
            if call.get("session") and call.get("outcome") == "ok" and not Path(str(call.get("raw_output"))).is_file():
                found = sorted((research_root / "cache" / "reviews").glob(f"{call['session']}.v*.json*"))
                call["raw_output"] = str(found[0]) if found else call.get("raw_output")

    # -- SC-S1-01 ------------------------------------------------------------------------------------------
    first = pool(names["zebra"])
    zebra = next((i for i, c in first.items() if str(c.get("title", "")).startswith("Zebra")), None)
    later = [names[k] for k in ("alpha_reviewed", "changed", "restarted", "rereviewed")]
    zebra_seen = {n: (pool(n).get(zebra) or {}).get("revision") for n in [names["zebra"], *later]}
    alpha = next((i for i, c in pool(names["alpha_reviewed"]).items() if str(c.get("title", "")).startswith("Alpha")), None)
    alpha_rev = {n: (pool(n).get(alpha) or {}).get("revision") for n in later}
    calls = lambda name: (ck.get(name) or {}).get("review_calls") or []  # noqa: E731
    alpha_calls = lambda name: [c for c in calls(name) if c.get("about") == alpha and c.get("outcome") == "ok"]  # noqa: E731
    before_change = {c["kind"] for c in alpha_calls(names["alpha_reviewed"])}
    gate_c, gate_d, gate_e = (gates.get(names[k]) or {} for k in ("changed", "restarted", "rereviewed"))
    mentions = lambda gate, cid: [r for r in gate.get("reasons") or [] if cid and cid in r]  # noqa: E731
    new_alpha = [c for c in alpha_calls(names["rereviewed"]) if c not in alpha_calls(names["restarted"])]
    s101 = [
        a("Z1", "Zebra keeps one candidate id and its content revision through Alpha's insert, change and the restart",
          {"id": zebra, "revisions": zebra_seen}, ev_file(f"candidates-{names['rereviewed']}.json"),
          bool(zebra) and len(set(zebra_seen.values())) == 1 and None not in zebra_seen.values()),
        a("Z2", "Alpha gets its own new id; changing its mechanism raises its revision",
          {"id": alpha, "revisions": alpha_rev}, ev_file(f"candidates-{names['changed']}.json"),
          bool(alpha) and alpha != zebra and (alpha_rev[names["changed"]] or 0) > (alpha_rev[names["alpha_reviewed"]] or 0)),
        a("Z3", "after the change the gate is BLOCKED on Alpha's receipts; a re-merge, a restart and a new gate run "
                "do not change that; Zebra's receipts still apply",
          {"changed": gate_c, "after_restart": gate_d}, ev_file(f"discovery-state-{names['restarted']}.json"),
          gate_c.get("verdict") == "BLOCKED" and gate_d.get("verdict") == "BLOCKED"
          and bool(mentions(gate_c, alpha)) and bool(mentions(gate_d, alpha))
          and not mentions(gate_c, zebra) and not mentions(gate_d, zebra)),
        a("Z4", "Alpha's real novelty and critical reviews of its current revision; the gate then follows their "
                "verdicts (no missing-receipt reason for Alpha; a verdict such as NEEDS_EVIDENCE may still block)",
          {"new_calls": [{k: c.get(k) for k in ("kind", "review_id", "backend", "observed_model")} for c in new_alpha],
           "gate": gate_e}, ev_file(f"checkpoint-{names['rereviewed']}.json"),
          {"novelty_precheck", "critical_review"} <= {c["kind"] for c in new_alpha}
          and not [r for r in mentions(gate_e, alpha) if re.search(r"\bno \w+ receipt", r)])]  # a verdict may still block
    if layout == "v2":
        s101.insert(2, a("Z2b", "before its change Alpha had real novelty and critical receipts",
                         sorted(before_change), ev_file(f"checkpoint-{names['alpha_reviewed']}.json"),
                         {"novelty_precheck", "critical_review"} <= before_change))

    # -- SC-S1-03 ------------------------------------------------------------------------------------------
    exps = {e["id"]: e for e in snap["tables"].get("experiment", [])}
    zebra_node = next((n for n in (ck.get("final") or {}).get("nodes", []) if n.get("title")), None)
    hyp = zebra_node["id"] if zebra_node else None
    methods = [e for e in exps.values() if e.get("kind") == "method" and e.get("hypothesis_id") == hyp]

    # the three experiments the controller asked for share one commit: the one that has the output-dir variant
    commit = next((e["code_ref"] for e in methods if "output_dir" in (e.get("effective_config") or {})), None)
    methods = [e for e in methods if e["code_ref"] == commit] if commit else methods

    def pick(pred):
        return next((e for e in methods if pred(e.get("effective_config") or {})), None)
    m1 = pick(lambda c: c.get("lr") == 0.005 and "output_dir" not in c)
    m2 = pick(lambda c: c.get("lr") == 0.005 and "output_dir" in c)
    m3 = pick(lambda c: c.get("lr") == 0.01)
    spec = lambda e: e and e.get("method_spec_doc_id")  # noqa: E731
    fault = load(ctl / "fault-applied.json") or {}
    runs_m1 = [r for r in snap["tables"].get("run", []) if m1 and r["experiment_id"] == m1["id"]]
    imported_configs = []
    root = Path((load(proj / ".research-tree.json") or {}).get("root") or "")
    for r in runs_m1:
        for att in [r] + list((r.get("attempts") or {}).values()):
            if att.get("import_record") and att.get("manifest_path"):
                man = load(root / att["manifest_path"]) or {}
                imported_configs.append((man.get("config") or {}).get("lr"))
    evaluated = {e["experiment_id"] for e in (ck.get("I-zebra-evaluated") or {}).get("evaluations", [])}
    m3_runs = [r for r in (ck.get("I-zebra-evaluated") or {}).get("runs", []) if m3 and r["experiment_id"] == m3["id"]
               and r.get("exec_status") not in (None, "planned", "cancelled")]
    refusal_m3 = re.search(rf"(SANITY_REQUIRED|CODE_REVIEW_REQUIRED|REVIEW_BLOCKING)[^\n\"]{{0,40}}{m3['id'] if m3 else 'E-x'}", text)
    s103 = [
        a("I1", "a learning-rate change is a new method identity; a pure output-path change keeps it",
          {k: (e["id"], spec(e)) if e else None for k, e in (("m1", m1), ("m2", m2), ("m3", m3))},
          files.get("db-snapshot-final.json"), bool(m1 and m2 and m3) and spec(m1) == spec(m2) and spec(m1) != spec(m3)),
        a("I2", "the controller's configuration drift was applied to the file the runner reads", fault,
          files.get("fault-applied.json"), bool(fault.get("changed"))),
        a("I3", "the run reporting the drifted configuration is refused (METHOD_SPEC_MISMATCH) and nothing imports "
                "under the old identity with it", {"imported_lr": imported_configs,
                                                   "refusal": bool(re.search(r"METHOD_SPEC_MISMATCH", text))},
          files.get("db-snapshot-final.json"), "METHOD_SPEC_MISMATCH" in text and 0.02 not in imported_configs),
        a("I4", "after the file is restored the method experiment imports and is evaluated", sorted(evaluated),
          ev_file("checkpoint-I-zebra-evaluated.json"), bool(m1) and m1["id"] in evaluated),
        a("I5", "the lr 0.01 experiment is not submitted on the lr 0.005 method's sanity and code review",
          {"runs": m3_runs, "refusal": refusal_m3.group(0) if refusal_m3 else None},
          ev_file("checkpoint-I-zebra-evaluated.json"), bool(m3) and not m3_runs and bool(refusal_m3))]

    # -- SC-S1-02 ------------------------------------------------------------------------------------------
    def node(name):
        return next((n for n in (ck.get(name) or {}).get("nodes", []) if n.get("id") == hyp), {}) if hyp else {}

    def rows(name):
        return {r["dimension"]: r for r in (node(name).get("eligibility") or {}).get("rechecks") or []}

    def evals(name):
        return sorted((e["id"], e["recorded_mean"]) for e in (ck.get(name) or {}).get("evaluations", []))
    j, k, l_, m = (rows(n) for n in ("J-rechecked", "K-claim-broadened", "L-claim-narrowed", "M-after-restart"))
    rev = {n: node(n).get("claim_revision") for n in ("J-rechecked", "K-claim-broadened", "L-claim-narrowed", "M-after-restart")}
    state = lambda rs: {d: (r.get("state"), r.get("review_id")) for d, r in rs.items()}  # noqa: E731
    s102 = [
        a("K0", "the node's five rechecks exist for its current evaluation", state(j),
          ev_file("checkpoint-J-rechecked.json"), len(j) == 5 and all(r.get("review_id") for r in j.values())),
        a("K1", "broadening the claim is a new claim revision; the numbers do not change",
          {"revisions": rev, "evaluations_J": evals("J-rechecked"), "evaluations_K": evals("K-claim-broadened")},
          ev_file("checkpoint-K-claim-broadened.json"),
          (rev["K-claim-broadened"] or 0) > (rev["J-rechecked"] or 0) and evals("J-rechecked") == evals("K-claim-broadened")),
        a("K2", "the claim-bound rechecks (method_code, novelty, theory) stop applying; the evaluation-bound ones stay",
          state(k), ev_file("checkpoint-K-claim-broadened.json"),
          all((k.get(d) or {}).get("state") == "stale" for d in CLAIM_BOUND)
          and all(state(k).get(d) == state(j).get(d) for d in EVAL_BOUND)),
        a("K3", "narrowing again is another revision; only the affected dimensions are reviewed anew and apply",
          {"revisions": rev, "L": state(l_)}, ev_file("checkpoint-L-claim-narrowed.json"),
          (rev["L-claim-narrowed"] or 0) > (rev["K-claim-broadened"] or 0)
          and all((l_.get(d) or {}).get("state") != "stale" and (l_.get(d) or {}).get("review_id") != (j.get(d) or {}).get("review_id")
                  for d in CLAIM_BOUND)
          and all(state(l_).get(d) == state(j).get(d) for d in EVAL_BOUND)),
        a("K4", "after a restart the claim revision and every recheck state are what they were", {"M": state(m), "rev": rev},
          ev_file("checkpoint-M-after-restart.json"),
          rev["M-after-restart"] == rev["L-claim-narrowed"] and state(m) == state(l_) and bool(m))]

    # -- SC-COMMON-01 --------------------------------------------------------------------------------------
    obs = ck.get("final") or {}
    before, after = ck.get("L-claim-narrowed") or {}, ck.get("M-after-restart") or {}
    base = next((e for e in obs.get("experiments", []) if e["kind"] == "baseline" and e.get("evaluation_id")), None)
    runs = [r for r in obs.get("runs", []) if base and r.get("valid") and r["experiment_id"] == base["id"]]
    ev = next((e for e in obs.get("evaluations", []) if base and e["experiment_id"] == base["id"]), None)
    started = [c for c in (f"{cmd} prepare", f"{cmd} init", f"{cmd} confirm") if c in prompts]
    refs = lambda o: sorted(r["ref"] for r in o.get("runs", []))  # noqa: E731
    resume_same = bool(before) and refs(before) == refs(after) and \
        (before.get("jobs") or {}).get("per_key") == (after.get("jobs") or {}).get("per_key")
    common = [
        a("C1", "prepare, init and confirm entered through the host's own command", started, files["commands.jsonl"],
          len(started) == 3),
        a("C2", "every valid baseline run rescored independently equals the DB value; artifacts present",
          [{"ref": r["ref"], "db": r["metric_value"], "scorer": (r.get("scorer") or {}).get("accuracy")} for r in runs],
          ev_file("checkpoint-final.json"), bool(runs) and all(r.get("db_matches_scorer") and r["artifacts"]["curve_matches_steps"]
                                                               and r["artifacts"]["usage_measured"] for r in runs)),
        a("C3", "the baseline evaluation equals the independent mean", ev and {k: ev[k] for k in ("id", "recorded_mean", "independent_mean")},
          ev_file("checkpoint-final.json"), bool(ev and ev["mean_matches"])),
        a("C4", "page built and fresh; the observer never changed the DB", {"site": obs.get("site"), "db_unchanged": obs.get("db_sha256_unchanged")},
          ev_file("checkpoint-final.json"), (obs.get("site") or {}).get("exit") == 0 and bool(obs.get("db_sha256_unchanged"))),
        a("C5", "no duplicate process start for any submission key", obs.get("jobs"), ev_file("checkpoint-final.json"),
          (obs.get("jobs") or {}).get("duplicate_jobs") == 0),
        a("C6", "the resumed session re-ran nothing", {"runs": refs(after), "starts": (after.get("jobs") or {}).get("per_key")},
          ev_file("checkpoint-M-after-restart.json"), resume_same)]
    src = (ctl / "source_ref.txt").read_text().split()
    sessions = [p for key, p in files.items() if key.startswith("session:")]
    for sc, assertions in (("SC-COMMON-01", common), ("SC-S1-01", s101), ("SC-S1-02", s102), ("SC-S1-03", s103)):
        r = record.template(sc, "S1", host, attempt)
        failed = [x["id"] for x in assertions if x["verdict"] != "PASS"]
        stopped = blocked and (not only or sc in only)
        state = ("BLOCKED" if stopped else "FAIL") if failed else status
        r.update({"status": state, **({"failures": [f"BLOCKED: {blocked}"]} if stopped and failed else {}), "source_ref": src[0], "uncommitted_changes": src[1:],
                  "project_root": str(proj), "build_path": str(S / f"dist-{host}-S1a{attempt:02d}"),
                  "loaded_plugin_path": str(S / f"dist-{host}-S1a{attempt:02d}/plugins/research-tree"),
                  "observed_model": model, "observed_effort": effort,
                  "session_id": Path(sessions[0]).name.split(".")[0] if sessions else None,
                  "session_transcripts": sessions, "commands": [c.get("prompt") or c.get("event") for c in commands],
                  "fault_plan": files.get("fault-plan.json"), "observer_results": ev_file("checkpoint-final.json"),
                  "review_calls": obs.get("review_calls"), "assertions": assertions,
                  "raw_evidence_paths": list(files.values()),
                  "resume_evidence": {"sessions": sessions, "question": [p for p in prompts if "恢复当前工作" in p],
                                      "observer_before": ev_file("checkpoint-L-claim-narrowed.json"),
                                      "observer_after": ev_file("checkpoint-M-after-restart.json"), "unchanged": resume_same},
                  "remaining_gaps": notes,
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
    p.add_argument("--layout", choices=sorted(LAYOUT), default="v2")
    p.add_argument("--note", action="append", default=[])
    p.add_argument("--blocked", help="the environment stopped the attempt (e.g. the host's usage limit): a scenario "
                                     "whose assertions could not all run is BLOCKED, not FAIL")
    p.add_argument("--blocked-scenario", action="append", default=[],
                   help="limit --blocked to these scenarios (the others failed before the block)")
    args = p.parse_args()
    make(args.host, args.attempt, args.status, args.note, args.layout, args.blocked, args.blocked_scenario)
    return 0


if __name__ == "__main__":
    sys.exit(main())
