"""S0 scenario base (plans/research-tree-implementation-and-real-scenarios.md §4.2): REG-S0-01..05 and the local
execution adapter the real scenarios submit through."""

import json
import os
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCEN = ROOT / "scripts" / "scenarios"
sys.path.insert(0, str(SCEN))
sys.path.insert(0, str(SCEN / "toyopt"))

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


class RecordTest(unittest.TestCase):
    def full(self, base: Path) -> dict:
        evidence = base / "session.log"
        evidence.write_text("raw")
        r = record.template("SC-S0-01", "S0", "claude", 1)
        r.update(status="PASS", project_root="/p", source_ref="abc", build_path="dist/claude",
                 loaded_plugin_path="/x/dist/claude/plugins/research-tree", observed_model="claude-haiku-5-5",
                 session_id="s-1", commands=["herdr agent prompt rt '/research-tree init'"],
                 raw_evidence_paths=[str(evidence)], observer_results={"runs": []}, resume_evidence={"new_session": "s-2"},
                 assertions=[{"id": "A1", "expected": "baseline evaluation from real runs", "actual": "EV-0001",
                              "evidence": str(evidence), "verdict": "PASS"}],
                 review_calls=[{"review_id": "D-0010", "backend": "pi", "outcome": "ok",
                                "observed_model": "gpt-6-luna"}])
        return r

    def test_reg_s0_03_missing_parts_cannot_pass(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            good = self.full(base)
            self.assertEqual(record.problems(good, base), [])
            for key, value in (("host", None), ("observed_model", None), ("commands", []),
                               ("raw_evidence_paths", []), ("raw_evidence_paths", ["missing.log"]),
                               ("resume_evidence", None), ("observer_results", None), ("session_id", None)):
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
                                                      "observed_model": "claude-haiku-5-5"}]},
                           {**good, "assertions": [{**good["assertions"][0], "actual": {"eval_type": "simulation_only"}}]}):
                self.assertTrue(record.problems(broken, base))
            reg = {**good, "evidence_class": "reg", "substitutes_used": ["mock_reviewer"]}
            self.assertEqual(record.problems(reg, base), [])

    def test_fault_plan_shape(self):
        self.assertEqual(record.check_faults({"faults": [{"id": "F1", "target": "report", "trigger": "before import",
                                                          "times": 1, "invariants": ["no evaluation"]}]}), [])
        self.assertTrue(record.check_faults({"faults": [{"id": "F1", "times": 0}]}))


if __name__ == "__main__":
    unittest.main()
