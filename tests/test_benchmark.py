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
    def episode(self, outcome="go", candidates=(), tested=(), system="C", host="claude", executor="claude-haiku-5-5"):
        return {"system": system, "host": host, "version": "v", "executor_model": executor, "outcome": outcome,
                "go_candidates": [{"decision_id": f"DC-{i}", "node": f"H-{i}", "knobs": k} for i, k in enumerate(candidates)],
                "tested": [{"node": f"H-{i}", "knobs": k, "retired": r} for i, (k, r) in enumerate(tested)],
                "valid_runs": 12, "node_seconds": 7200, "user_instructions": 3, "review_cost_usd": 0.4}

    def test_reg_s7_03_another_effective_set_is_not_a_false_go(self):
        truth = {"scenario": "combination", "best": ["clip", "ema"], "effective": [["clip", "ema"], ["wd"]]}
        other = score.score_episode(self.episode(candidates=[["wd"]]), truth)
        self.assertEqual((other["false_go"], other["found_effective"], other["found_best"]), (0, True, False))
        wrong = score.score_episode(self.episode(candidates=[["clip"]], tested=[(["clip", "ema"], True)]), truth)
        self.assertEqual((wrong["false_go"], wrong["found_effective"], wrong["best_retired"]), (1, False, True))
        self.assertEqual((wrong["efficiency"], wrong["user_burden"], wrong["coverage"]), (6.0, 2, 1))
        zero = score.score_episode(self.episode("not_go"), {"scenario": "zero", "best": []})
        self.assertEqual((zero["false_go"], zero["found_effective"]), (0, False))

    def test_reg_s7_04_every_candidate_and_outcome_is_kept(self):
        truth = {"scenario": "combination", "best": ["clip", "ema"]}
        two = score.score_episode(self.episode(candidates=[["clip", "ema"], ["clip"]]), truth)
        self.assertEqual(([c["supported"] for c in two["go_candidates"]], two["false_go"]), ([True, False], 1))
        scores = [score.score_episode(self.episode(o), truth) for o in ("blocked", "budget_stopped", "incomplete", "not_go")]
        grouped = score.group(scores)["C/claude"]
        self.assertEqual({k: v for k, v in grouped["outcomes"].items() if v},
                         {"blocked": 1, "budget_stopped": 1, "incomplete": 1, "not_go": 1})
        self.assertEqual((grouped["episodes"], grouped["false_go"]), (4, 0))  # stopping is not success, nor a false GO

    def test_reg_s7_05_one_label_one_executor_and_normalized_events(self):
        truth = {"scenario": "zero", "best": []}
        mixed = [score.score_episode(self.episode("not_go", executor=m), truth) for m in ("claude-haiku-5-5", "gpt-6-luna")]
        with self.assertRaisesRegex(ValueError, "mixes executors"):
            score.group(mixed)
        # events come from plain tables: an older layout without the newer fields still normalizes
        tables = {"project": [{"status": "go"}], "run": [], "hypothesis": [{"id": "H-1", "experiment_status": "beats_sota"}],
                  "experiment": [], "decision": [{"id": "DC-1", "field": "status", "to_value": "go", "decided_at": "t"}],
                  "reservation": [], "document": []}
        ep = score.events(tables, Path("/nonexistent"), "B", "codex", "616d646", "gpt-6-luna", "completed", None)
        self.assertEqual((ep["outcome"], [c["node"] for c in ep["go_candidates"]]), ("go", ["H-1"]))

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
            self.assertAlmostEqual(accuracy(truth["best"]) - plain, 0.03, delta=0.006)
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
        ep = score.normalize(marker.parent, ROOT / "shared" / "research-tree" / "tools", "C", "claude", "test")
        self.assertEqual(ep["outcome"], "active")
        self.assertGreaterEqual(ep["valid_runs"], 1)
        self.assertTrue(any(t["knobs"] in (["ema"], []) for t in ep["tested"]))
        self.assertEqual(ep["attempts"]["duplicate_jobs"], 0)

if __name__ == "__main__":
    unittest.main()
