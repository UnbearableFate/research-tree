"""Current-contract project generation and the real ToyOpt execution, scoring and evidence boundaries."""

import json
import os
import subprocess
import sys
import tempfile
import time
import unittest

import yaml
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCEN = ROOT / "scripts" / "scenarios"
sys.path.insert(0, str(SCEN))
sys.path.insert(0, str(SCEN / "toyopt"))
sys.path.insert(0, str(ROOT / "shared" / "research-tree" / "tools"))

import project_config  # noqa: E402
import observe  # noqa: E402
import record  # noqa: E402
import scorer  # noqa: E402
from toytrain import data as toydata  # noqa: E402


def make(dest: Path, *extra: str) -> dict:
    out = subprocess.run([sys.executable, str(ROOT / "scripts" / "make_rt_test_project.py"), str(dest), "--host",
                          "claude", "--stage", "S0", "--case", "SC-S0-01", *extra], capture_output=True, text=True)
    assert out.returncode == 0, out.stderr
    return json.loads(out.stdout)


def run(project: Path, seed: int, out: str, *extra: str, key: str | None = None) -> dict:
    """One real training run through the project's adapter and runner; waits for its end."""
    key = key or f"k-{seed}-{out.replace('/', '_')}"
    cmd = [sys.executable, str(project / "tools" / "local_exec.py"), "submit", "--key", key, "--cwd",
           str(project / "code"), "--out", str(project / out), "--", sys.executable, "-m", "toytrain.run",
           "--experiment", "E-0001", "--seed", str(seed), "--out", str(project / out),
           "--config", "configs/reference.json", *extra]
    subprocess.run(cmd, capture_output=True, text=True, check=True)
    waited = subprocess.run([sys.executable, str(project / "tools" / "local_exec.py"), "wait", "--key", key,
                             "--timeout", "120"], capture_output=True, text=True, check=True)
    return json.loads(waited.stdout)


class GeneratorTest(unittest.TestCase):
    def test_reg_s0_01_same_inputs_same_project_and_nothing_old(self):
        with tempfile.TemporaryDirectory() as tmp:
            a, b = Path(tmp) / "a", Path(tmp) / "b"
            make(a)
            make(b)
            self.assertEqual((a / "code/data/splits.json").read_text(), (b / "code/data/splits.json").read_text())
            for name in ("train", "explore", "c1", "c2"):
                self.assertEqual((a / f"code/data/{name}.jsonl").read_bytes(), (b / f"code/data/{name}.jsonl").read_bytes())
            self.assertEqual((a / "research-tree.yaml").read_text(), (b / "research-tree.yaml").read_text())
            self.assertEqual((a / "plan.md").read_text().replace(str(a), "X"), (b / "plan.md").read_text().replace(str(b), "X"))
            self.assertEqual((a / "code/configs/reference.json").read_text(), (b / "code/configs/reference.json").read_text())
            for project in (a, b):  # a fresh project: no database, reviews, results or job ledger
                self.assertFalse((project / "research").exists())
                self.assertFalse((project / ".research-tree.json").exists())
                self.assertFalse((project / ".local-exec").exists())
                self.assertFalse((project / "outputs").exists())
            ctl = json.loads((Path(tmp) / "a.ctl" / "scenario.json").read_text())
            self.assertEqual((ctl["host"], ctl["stage"], ctl["case"], ctl["attempt"], ctl["blind"]),
                             ("claude", "S0", "SC-S0-01", 1, False))
            # controller files stay outside the project
            self.assertFalse(any(p.name in ("scenario.json", "fault-plan.json") for p in a.rglob("*")))

    def test_generator_emits_only_the_current_contract(self):
        with tempfile.TemporaryDirectory() as tmp:
            configs = []
            for index, (host, label) in enumerate((("claude", "FAST"), ("codex", "FAST"), ("claude", "S7"))):
                project = Path(tmp) / str(index)
                made = make(project, "--host", host, "--stage", label)
                text = (project / "research-tree.yaml").read_text()
                config = yaml.safe_load(text)
                self.assertEqual(project_config.parse(text)["version"], 3)
                self.assertEqual(config["version"], 3)
                self.assertFalse(set(config) & {"workflow", "discovery", "literature", "review"})
                self.assertEqual(set(config["design"]), {"code_review", "sanity_first", "overrun_factor"})
                self.assertEqual(config["evidence_policy"], {"require_artifact_import": True})
                self.assertNotIn("compute_unit", config["budget"])
                self.assertEqual(set(config["models"]), {"ui", "worker", "architect", "explorer", "analyst", "reviewer"})
                self.assertEqual(config["verification"]["independence_fields"], ["train_seed"])
                self.assertNotIn("repetition", config["verification"])
                provenance = json.loads((Path(made["controller"]) / "scenario.json").read_text())
                self.assertEqual(provenance["generator_version"], "toyopt-lab-3")
                self.assertIn("architect/root", (project / "plan.md").read_text())
                configs.append(config)
            self.assertEqual(configs[0], configs[2])  # stage is metadata, never a contract selector

    def test_retired_generator_switches_are_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            project = Path(tmp) / "p"
            for flags in (("--legacy-toytrain",), ("--config-version", "2"), ("--profile", "screening"),
                          ("--discovery", "full"), ("--hypotheses", "0"), ("--with-reviewer",)):
                with self.subTest(flags=flags):
                    out = subprocess.run([sys.executable, str(ROOT / "scripts/make_rt_test_project.py"),
                                          str(project), "--host", "claude", *flags], capture_output=True, text=True)
                    self.assertNotEqual(out.returncode, 0)
                    self.assertIn("unrecognized arguments", out.stderr)
                    self.assertFalse(project.exists())

    def test_observer_rejects_unsupported_project_markers(self):
        with tempfile.TemporaryDirectory() as tmp:
            project = Path(tmp)
            for version in (None, 1, 2, True):
                (project / ".research-tree.json").write_text(json.dumps({"format_version": version}))
                with self.assertRaisesRegex(ValueError, "version-3"):
                    observe.observe(project)

    def test_refuses_a_used_directory(self):
        with tempfile.TemporaryDirectory() as tmp:
            dest = Path(tmp) / "p"
            make(dest)
            again = subprocess.run([sys.executable, str(ROOT / "scripts" / "make_rt_test_project.py"), str(dest),
                                    "--host", "claude"], capture_output=True, text=True)
            self.assertNotEqual(again.returncode, 0)
            self.assertIn("not empty", again.stderr)

    def test_reg_s0_05_material_identities(self):
        rows = {n: toydata.make_split(n, size, seed) for n, (size, seed) in toydata.SPLITS.items()}
        ids = {n: {tuple(r["x"]) for r in rs} for n, rs in rows.items()}
        for x, y in (("explore", "c1"), ("explore", "c2"), ("c1", "c2"), ("train", "c1")):
            self.assertFalse(ids[x] & ids[y], f"{x} and {y} share samples")
            self.assertNotEqual([r["y"] for r in rows[x]][:400], [r["y"] for r in rows[y]][:400])
        with tempfile.TemporaryDirectory() as tmp:
            project = Path(tmp) / "p"
            make(project)
            splits = json.loads((project / "code/data/splits.json").read_text())["splits"]
            self.assertEqual(len({s["split_id"] for s in splits.values()}), 4)
            # the training seed does not change the evaluation material's identity
            run(project, 42, "outputs/a")
            run(project, 43, "outputs/b")
            ma = json.loads((project / "outputs/a/run_manifest.json").read_text())
            mb = json.loads((project / "outputs/b/run_manifest.json").read_text())
            self.assertEqual(ma["eval_split_id"], mb["eval_split_id"])
            self.assertNotEqual(ma["train_seed"], mb["train_seed"])
            run(project, 1042, "outputs/c", "--eval-split", "c1")
            mc = json.loads((project / "outputs/c/run_manifest.json").read_text())
            self.assertNotEqual(mc["eval_split_id"], ma["eval_split_id"])
            # a renamed copy is the same material: its identity is its content
            data = project / "code/data"
            (data / "c1-renamed.jsonl").write_bytes((data / "c1.jsonl").read_bytes())
            self.assertEqual(toydata.hashlib.sha256((data / "c1-renamed.jsonl").read_bytes()).hexdigest(),
                             splits["c1"]["sha256"])


class ScorerTest(unittest.TestCase):
    def test_reg_s0_02_scorer_recounts_and_ignores_reports(self):
        with tempfile.TemporaryDirectory() as tmp:
            project = Path(tmp) / "p"
            make(project)
            job = run(project, 42, "outputs/s42")
            self.assertEqual(job["exit_code"], 0)
            out = project / "outputs/s42"
            first = scorer.score_output(out, project / "code/data")
            self.assertTrue(first["accuracy_matches"])
            self.assertEqual(first["n"], 400)
            self.assertEqual(first["correct"], json.loads((out / "metrics.json").read_text())["correct"])
            self.assertEqual(first["prediction_mismatches"], [])
            # a wrong report (and a doctored metrics file) does not move the independent score
            metrics = json.loads((out / "metrics.json").read_text())
            (out / "metrics.json").write_text(json.dumps({**metrics, "accuracy": 0.99}))
            second = scorer.score_output(out, project / "code/data")
            self.assertEqual((second["accuracy"], second["correct"]), (first["accuracy"], first["correct"]))
            self.assertFalse(second["accuracy_matches"])
            # nor does a doctored count in the run's own manifest
            manifest = json.loads((out / "run_manifest.json").read_text())
            manifest["counts"]["n_eval"] = 100
            (out / "run_manifest.json").write_text(json.dumps(manifest))
            third = scorer.score_output(out, project / "code/data")
            self.assertEqual((third["n"], third["correct"]), (first["n"], first["correct"]))
            self.assertFalse(third["manifest_n_matches"])
            usage = json.loads((out / "usage.json").read_text())
            self.assertGreater(usage["cpu_seconds"], 0)
            self.assertEqual(usage["walltime_used_s"], 1)

    def test_a_failed_run_still_writes_its_manifest(self):
        with tempfile.TemporaryDirectory() as tmp:
            project = Path(tmp) / "p"
            make(project)
            job = run(project, 42, "outputs/bad", "--data-dir", str(project / "no-such-dir"))
            self.assertEqual(job["exit_code"], 1)
            manifest = json.loads((project / "outputs/bad/run_manifest.json").read_text())
            self.assertEqual(manifest["exit_status"], 1)
            self.assertIn("FileNotFoundError", manifest["error"])
            self.assertIn("FileNotFoundError", (project / "outputs/bad/train.log").read_text())


class AdapterTest(unittest.TestCase):
    def test_same_key_starts_one_process_and_a_lost_answer_is_found_by_key(self):
        with tempfile.TemporaryDirectory() as tmp:
            project = Path(tmp) / "p"
            make(project)
            faults = Path(tmp) / "faults.json"
            faults.write_text(json.dumps({"faults": [
                {"id": "F1", "window": "lose_submit_response", "key_glob": "lost-*", "times": 1},
                {"id": "F2", "window": "extra_launch", "key_glob": "dup-*", "times": 1}]}))
            env = {**os.environ, "RT_LOCAL_EXEC_FAULTS": str(faults)}
            tool = [sys.executable, str(project / "tools/local_exec.py")]

            def submit(key):
                return subprocess.run(tool + ["submit", "--key", key, "--cwd", str(project / "code"), "--out",
                                              str(project / "outputs" / key), "--", sys.executable, "-m",
                                              "toytrain.run", "--experiment", "E-0001", "--seed", "42", "--out",
                                              str(project / "outputs" / key)], capture_output=True, text=True, env=env)
            lost = submit("lost-1")
            self.assertEqual(lost.returncode, 75)
            self.assertEqual(lost.stdout, "")
            found = json.loads(subprocess.run(tool + ["status", "--key", "lost-1"], capture_output=True, text=True,
                                              env=env).stdout)
            self.assertTrue(found["found"])
            again = submit("lost-1")  # the same key again: the existing job, no second process
            self.assertEqual(again.returncode, 0)
            self.assertTrue(json.loads(again.stdout)["existing"])
            submit("dup-1")
            for key in ("lost-1", "dup-1"):
                subprocess.run(tool + ["wait", "--key", key], capture_output=True, text=True, env=env, check=True)
            deadline = time.time() + 20
            while time.time() < deadline and len([e for e in observe.jsonl(project / ".local-exec/launches.jsonl")
                                                  if e.get("ended")]) < 3:
                time.sleep(0.2)
            jobs = observe.launches(project)
            self.assertEqual(jobs["per_key"], {"lost-1": 1, "dup-1": 2})
            self.assertEqual(jobs["duplicate_jobs"], 1)
            # the extra start wrote into its own directory: the job's artifacts are the first start's
            ledger = [e for e in observe.jsonl(project / ".local-exec/launches.jsonl") if e.get("key") == "dup-1"
                      and not e.get("ended")]
            first = next(e["pid"] for e in ledger if e["launch"] == 1)
            manifest = json.loads((project / "outputs/dup-1/run_manifest.json").read_text())
            self.assertEqual(manifest["env"]["pid"], first)
            self.assertTrue((project / "outputs/dup-1/duplicate-launch-2/run_manifest.json").is_file())
            consumed = json.loads(Path(str(faults) + ".consumed.json").read_text())
            self.assertEqual(sorted(consumed), ["F1", "F2"])


class SchedulerServiceTest(unittest.TestCase):
    def test_jobs_submitted_through_the_service_outlive_the_caller(self):
        """Found in the S0 Codex run: a sandboxed command's own children die with it, so the controller runs the
        scheduler service and a submission only queues the job; status comes from the service's record."""
        with tempfile.TemporaryDirectory() as tmp:
            project = Path(tmp) / "p"
            make(project)
            tool = [sys.executable, str(project / "tools/local_exec.py")]
            service = subprocess.Popen(tool + ["serve"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            try:
                deadline = time.time() + 10
                while not (project / ".local-exec/daemon.json").is_file() and time.time() < deadline:
                    time.sleep(0.1)
                out = subprocess.run(tool + ["submit", "--key", "svc-1", "--cwd", str(project / "code"), "--out",
                                             str(project / "outputs/svc-1"), "--", sys.executable, "-m",
                                             "toytrain.run", "--experiment", "E-0001", "--seed", "42", "--out",
                                             str(project / "outputs/svc-1")], capture_output=True, text=True)
                self.assertEqual(out.returncode, 0, out.stderr)
                waited = json.loads(subprocess.run(tool + ["wait", "--key", "svc-1", "--timeout", "60"],
                                                   capture_output=True, text=True).stdout)
                self.assertEqual((waited["state"], waited["exit_code"]), ("exited", 0))
                job = json.loads((project / ".local-exec/jobs/svc-1.json").read_text())
                self.assertEqual(job["via"], "daemon")
                self.assertEqual(observe.launches(project)["per_key"], {"svc-1": 1})
            finally:
                service.terminate()
                service.wait()


class RecordTest(unittest.TestCase):
    def full(self, base: Path) -> dict:
        evidence = base / "session.log"
        evidence.write_text("raw")
        r = record.template("SC-S0-01", "S0", "claude", 1)
        r.update(status="PASS", project_root="/p", source_ref="abc", build_path="dist/claude",
                 loaded_plugin_path="/x/dist/claude/plugins/research-tree", observed_model="claude-haiku-5-5",
                 session_id="s-1", observed_effort="medium", session_transcripts=[str(evidence)],
                 commands=["herdr agent prompt rt '/research-tree init'"],
                 raw_evidence_paths=[str(evidence)], observer_results={"runs": []},
                 resume_evidence={"new_session": "s-2", "observer_before": str(evidence), "observer_after": str(evidence)},
                 assertions=[{"id": "A1", "expected": "baseline evaluation from real runs", "actual": "EV-0001",
                              "evidence": str(evidence), "verdict": "PASS"}],
                 review_calls=[{"review_id": "D-0010", "backend": "pi", "outcome": "ok",
                                "observed_model": "gpt-6-luna", "raw_output": str(evidence)}])
        return r

    def test_reg_s0_03_missing_parts_cannot_pass(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            good = self.full(base)
            self.assertEqual(record.problems(good, base), [])
            for key, value in (("host", None), ("observed_model", None), ("commands", []),
                               ("raw_evidence_paths", []), ("raw_evidence_paths", ["missing.log"]),
                               ("resume_evidence", None), ("observer_results", None), ("session_id", None),
                               ("observed_effort", None), ("observed_effort", "high"), ("session_transcripts", []),
                               ("resume_evidence", {"new_session": "s-2"})):
                broken = {**good, key: value}
                self.assertTrue(record.problems(broken, base), f"{key}={value!r} passed")
            failing = {**good, "assertions": [{**good["assertions"][0], "verdict": "FAIL"}]}
            self.assertTrue(record.problems(failing, base))
            path = base / "record.json"
            path.write_text(json.dumps({**good, "resume_evidence": None}))
            out = subprocess.run([sys.executable, str(SCEN / "record.py"), "validate", str(path)], capture_output=True,
                                 text=True)
            self.assertEqual(out.returncode, 1)

    def test_reg_s0_04_substitutes_are_not_real_scenarios(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            good = self.full(base)
            for broken in ({**good, "substitutes_used": ["mock_reviewer"]},
                           {**good, "substitutes_used": ["preset_scores"]},
                           {**good, "review_calls": [{"review_id": "D-1", "backend": "mock", "outcome": "ok",
                                                      "observed_model": "x"}]},
                           {**good, "review_calls": [{"review_id": "D-1", "backend": "pi", "outcome": "ok"}]},
                           {**good, "observed_model": "claude-sonnet-5-5"},
                           {**good, "review_calls": [{"review_id": "D-1", "backend": "pi", "outcome": "ok",
                                                      "observed_model": "claude-haiku-5-5", "raw_output": str(base / "session.log")}]},
                           {**good, "review_calls": [{"review_id": "D-1", "backend": "pi", "outcome": "ok",
                                                      "observed_model": "gpt-6-luna"}]},
                           {**good, "assertions": [{**good["assertions"][0], "actual": {"eval_type": "simulation_only"}}]}):
                self.assertTrue(record.problems(broken, base))
            reg = {**good, "evidence_class": "reg", "substitutes_used": ["mock_reviewer"]}
            self.assertEqual(record.problems(reg, base), [])

    def test_a_forked_attempt_cannot_show_the_common_opening(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            fork = {"snapshot": "rt-scenarios/S2/prefix-claude-a03.tar.gz", "attempt": "a03"}
            stage = {**self.full(base), "forked_from": fork}
            self.assertEqual(record.problems(stage, base), [])
            common = {**stage, "scenario_id": "SC-COMMON-01"}
            self.assertTrue(record.problems(common, base))
            self.assertTrue(record.problems({**stage, "forked_from": {"attempt": "a03"}}, base))
            self.assertEqual(record.problems({**common, "forked_from": None}, base), [])

    def test_evidence_is_a_nonempty_file_in_the_scenario_locations(self):
        with tempfile.TemporaryDirectory() as tmp, tempfile.TemporaryDirectory() as elsewhere:
            base = Path(tmp)
            good = self.full(base)
            (base / "empty.log").write_text("")
            (base / "dir").mkdir()
            outside = Path(elsewhere) / "session.log"
            outside.write_text("raw")
            (base / "link.log").symlink_to(outside)
            for bad in ("", ".", "/", "dir", str(base / "dir"), "empty.log", "README.md", str(ROOT / "README.md"),
                        str(outside), "link.log", None):
                with self.subTest(path=bad):
                    for broken in ({**good, "session_transcripts": [bad]}, {**good, "raw_evidence_paths": [bad]},
                                   {**good, "resume_evidence": {**good["resume_evidence"], "observer_after": bad}},
                                   {**good, "review_calls": [{**good["review_calls"][0], "raw_output": bad}]}):
                        self.assertTrue(record.problems(broken, base))
            # the scenario's own project and controller directories hold evidence too
            project = Path(elsewhere) / "rt-S0-claude-a01"
            transcript = Path(elsewhere) / "rt-S0-claude-a01.ctl" / "sessions" / "s.jsonl"
            transcript.parent.mkdir(parents=True)
            transcript.write_text("raw")
            self.assertEqual(record.problems({**good, "project_root": str(project),
                                              "session_transcripts": [str(transcript)]}, base), [])
            # never a directory holding the repository or one inside it
            for root, inside in (("/", outside), (ROOT, ROOT / "README.md"),
                                 (ROOT / "plans", ROOT / "plans/research-tree-implementation-and-real-scenarios.md")):
                with self.subTest(project_root=root):
                    self.assertTrue(inside.is_file())
                    self.assertTrue(record.problems({**good, "project_root": str(root),
                                                     "raw_evidence_paths": [str(inside)]}, base))

    def test_a_record_reads_its_own_stage_and_host_evidence(self):
        with tempfile.TemporaryDirectory() as tmp:
            tree = Path(tmp)
            base = tree / "S0" / "claude" / "SC-S0-01" / "a01"
            base.mkdir(parents=True)
            evidence = tree / "S0" / "claude" / "evidence-a01"
            evidence.mkdir()
            good = self.full(evidence)
            self.assertEqual(record.problems(good, base), [])
            other = tree / "S1" / "claude" / "evidence-a01"  # another stage's files are not this record's evidence
            other.mkdir(parents=True)
            (other / "observer.json").write_text("{}")
            self.assertTrue(record.problems({**good, "raw_evidence_paths": [str(other / "observer.json")]}, base))

    def test_a_scenario_that_resumes_needs_its_resume_whatever_the_flag_says(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            good = self.full(base)
            for scenario in ("SC-COMMON-01", "SC-S0-01", "SC-S6-02"):
                with self.subTest(scenario=scenario):
                    waived = {**good, "scenario_id": scenario, "requires_resume": False}
                    self.assertEqual(record.problems(waived, base), [])
                    self.assertTrue(record.problems({**waived, "resume_evidence": None}, base))
                    self.assertTrue(record.problems({**waived, "resume_evidence": {"new_session": "s-2"}}, base))
            # a scenario without a resume step may say it has none
            self.assertEqual(record.problems({**good, "scenario_id": "SC-S0-02", "requires_resume": False,
                                              "resume_evidence": None}, base), [])

    def test_summary_never_counts_reg_as_a_real_pass(self):
        with tempfile.TemporaryDirectory() as tmp:
            tree = Path(tmp)

            def put(scenario, attempt, **changes):
                base = tree / "S0" / "claude" / scenario / f"a{attempt:02d}"
                base.mkdir(parents=True)
                kept = {**self.full(base), "scenario_id": scenario, "attempt": attempt, **changes}
                (base / "record.json").write_text(json.dumps(kept))
            put("SC-S0-01", 1)
            put("SC-S0-01", 2, evidence_class="reg", substitutes_used=["preset_scores"])
            put("SC-S0-02", 1, evidence_class="reg", substitutes_used=["mock_reviewer"])
            cell = record.summary(tree)["S0"]["claude"]
            real, reg = cell["SC-S0-01"], cell["SC-S0-02"]
            self.assertEqual((real["attempt"], real["evidence_class"], real["valid"]), (1, "real_sc", True))
            self.assertEqual((reg["evidence_class"], reg["valid"]), ("reg", False))
            self.assertIn("never a real PASS", reg["problems"][0])

    def test_fault_plan_shape(self):
        self.assertEqual(record.check_faults({"faults": [{"id": "F1", "target": "report", "trigger": "before import",
                                                          "times": 1, "invariants": ["no evaluation"]}]}), [])
        self.assertTrue(record.check_faults({"faults": [{"id": "F1", "times": 0}]}))


if __name__ == "__main__":
    unittest.main()
