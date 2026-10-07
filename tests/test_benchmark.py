"""The workflow benchmark's tooling (plans/design 11 §2): hidden-truth tasks and scoring."""

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts" / "benchmark"))

import score  # noqa: E402


class ScoreTest(unittest.TestCase):
    def test_false_go_found_and_premature_elimination(self):
        truth = {"scenario": "combination", "best": ["clip", "ema"]}
        base = {"valid_runs": 12, "node_seconds": 7200, "extra_attempts": 1, "user_instructions": 3,
                "review_cost_usd": 0.4}
        wrong = score.score({**base, "status": "go", "go_knobs": ["clip"],
                             "tested": [{"knobs": ["clip"], "node_retired": False},
                                        {"knobs": ["ema", "clip"], "node_retired": True}]}, truth)
        self.assertEqual((wrong["false_go"], wrong["found"], wrong["premature_elimination"]), (True, False, True))
        self.assertEqual((wrong["efficiency"], wrong["user_burden"], wrong["coverage"]), (6.0, 2, 2))
        right = score.score({**base, "status": "go", "go_knobs": ["ema", "clip"], "tested": []}, truth)
        self.assertEqual((right["false_go"], right["found"]), (False, True))
        zero = score.score({**base, "status": "not_go", "go_knobs": None, "tested": []}, {"scenario": "zero", "best": []})
        self.assertEqual((zero["false_go"], zero["found"]), (False, False))

    def test_task_truth_stays_outside_the_project(self):
        with tempfile.TemporaryDirectory() as tmp:
            dest = Path(tmp) / "t"
            out = subprocess.run([sys.executable, str(ROOT / "scripts" / "benchmark" / "make_task.py"), str(dest),
                                  "--scenario", "combination", "--seed", "3"], capture_output=True, text=True)
            self.assertEqual(out.returncode, 0, out.stderr)
            truth = json.loads((dest / "truth.json").read_text())
            project = dest / "project"
            self.assertNotIn(str(truth["salt"]), "".join(p.read_text(errors="ignore") for p in project.rglob("*")
                                                         if p.is_file() and ".git" not in p.parts))
            code = project / "code"

            def accuracy(knobs, with_truth=True):
                env = {"PATH": "/usr/bin:/bin"}
                if with_truth:
                    env["RT_BENCH_TRUTH"] = str(dest / "truth.json")
                run = subprocess.run([sys.executable, "-m", "toytrain.train", "--seed", "1", "--out", str(dest / "o"),
                                      "--knobs", ",".join(knobs)], cwd=code, env=env, capture_output=True, text=True)
                return json.loads(run.stdout)["accuracy"]
            plain = accuracy([], with_truth=False)
            self.assertAlmostEqual(accuracy(truth["best"]) - plain, 0.015, delta=0.006)
            self.assertAlmostEqual(accuracy(truth["best"][:1]) - plain, 0.0, delta=0.006)


def make(dest: Path, scenario: str) -> dict:
    out = subprocess.run([sys.executable, str(ROOT / "scripts" / "benchmark" / "make_task.py"), str(dest),
                          "--scenario", scenario, "--seed", "5"], capture_output=True, text=True)
    assert out.returncode == 0, out.stderr
    return json.loads((dest / "truth.json").read_text())


def run(dest: Path, knobs, seed=1, lr=0.05):
    env = {"PATH": "/usr/bin:/bin", "RT_BENCH_TRUTH": str(dest / "truth.json")}
    done = subprocess.run([sys.executable, "-m", "toytrain.train", "--seed", str(seed), "--out", str(dest / "o"),
                           "--knobs", ",".join(knobs), "--lr", str(lr)], cwd=dest / "project" / "code", env=env,
                          capture_output=True, text=True)
    return json.loads(done.stdout)["accuracy"] if done.returncode == 0 else None


class ScenarioTest(unittest.TestCase):
    def test_confound_gain_is_explained_by_the_learning_rate(self):
        with tempfile.TemporaryDirectory() as tmp:
            dest = Path(tmp) / "t"
            truth = make(dest, "confound")
            knob = truth["confound"]
            self.assertGreater(run(dest, [knob]) - run(dest, []), 0.01)  # the knob seems to help
            self.assertAlmostEqual(run(dest, [knob]), run(dest, [], lr=0.1), delta=0.012)  # matched lr: same

    def test_faults_fail_once_then_recover(self):
        with tempfile.TemporaryDirectory() as tmp:
            dest = Path(tmp) / "t"
            make(dest, "faults")
            self.assertIsNone(run(dest, [], seed=0))
            self.assertIsNotNone(run(dest, [], seed=0))


class GatherTest(unittest.TestCase):
    def test_gather_reads_a_project_database(self):
        sys.path.insert(0, str(ROOT / "shared" / "research-tree" / "tests"))
        from test_research_db import Fixture
        fixture = type("F", (Fixture,), {"runTest": lambda self: None})()
        fixture.setUp()
        self.addCleanup(fixture.tearDown)
        h = fixture.hypothesis()
        fixture.start(h)
        exp = fixture.method(h, n_seeds=1)
        fixture.finish_runs(fixture.worker, exp)
        run_id = f"{exp}/s{fixture.rld.get(exp)['seeds'][0]}"
        out = fixture.root / "outputs" / "g"
        out.mkdir(parents=True)
        (out / "metrics.json").write_text(json.dumps({"knobs": ["ema"]}))
        fixture.rld.update_run(run_id, output_path=str(out)) if not fixture.rld.get(run_id).get("valid") else None
        marker = fixture.root.parent.parent / ".research-tree.json"
        marker.write_text(json.dumps({"db": str(fixture.db), "root": str(fixture.root)}))
        records = score.gather(marker.parent)
        self.assertEqual(records["status"], "active")
        self.assertGreaterEqual(records["valid_runs"], 1)
        self.assertGreater(records["node_seconds"], 0)
        self.assertTrue(any(t["knobs"] in (["ema"], []) for t in records["tested"]))
        self.assertIsNotNone(records["wall_clock_h"])


if __name__ == "__main__":
    unittest.main()
