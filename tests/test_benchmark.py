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


if __name__ == "__main__":
    unittest.main()
