"""REG-S7-06 (plans/research-tree-implementation-and-real-scenarios.md §11.6): the private evaluator scores only legal
requests, once per run attempt and material, within a budget; private material that the public generator can
reproduce is refused; inside the sandbox a canary in the private directory cannot be reached by direct read, listing,
symbolic link, environment, other processes, inherited descriptors, the Docker socket or a search, while the
workspace stays usable. The canary holds a random token, nothing sensitive."""

from __future__ import annotations

import hashlib
import json
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts" / "private_eval"))

import evaluator  # noqa: E402
import private_material  # noqa: E402


class EvaluatorTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        base = Path(self.tmp.name)
        self.private, self.work = base / "private", base / "work"
        self.work.mkdir()
        private_material.generate(self.private, "p1", 60)
        self.ev = evaluator.Evaluator(self.private, self.work / "spool", self.work, budget=2)
        model = {"format": "toyopt-logreg-1", "n_features": 16, "w": [0.1] * 16, "b": 0.0}
        (self.work / "model.json").write_text(json.dumps(model))

    def tearDown(self):
        self.tmp.cleanup()

    def ask(self, rid, **over):
        req = {"request_id": rid, "run_ref": "E-0007/s42@1", "material": "p1", "model": "model.json", **over}
        path = self.work / "spool" / "requests" / f"{rid}.json"
        path.write_text(json.dumps(req) if not isinstance(over.get("_raw"), str) else over["_raw"])
        return self.ev.handle(path)

    def test_reg_s7_06_legal_requests_once_within_budget(self):
        first = self.ask("r1")
        self.assertTrue(first["ok"])
        self.assertEqual(set(first) - {"repeat"}, {"ok", "request_id", "run_ref", "material", "accuracy", "n"})
        self.assertEqual(self.ask("r1"), first)  # the same request again: the same answer
        again = self.ask("r2")  # another request for the same run attempt and material: one sample, not two
        self.assertEqual((again["accuracy"], again["repeat"]), (first["accuracy"], True))
        self.assertTrue(self.ask("r3", run_ref="E-0007/s43@1")["ok"])
        over = self.ask("r4", run_ref="E-0007/s44@1")
        self.assertIn("scored its 2 run attempts", over["refused"])  # no free oracle
        for rid, change, why in (("r5", {"material": "c1", "run_ref": "E-0010/s1@1"}, "unknown material"),
                                 ("r6", {"model": "/etc/passwd", "run_ref": "E-0011/s1@1"}, "inside the workspace"),
                                 ("r7", {"run_ref": "anything"}, "run attempt ref"),
                                 ("r8", {"extra": "x"}, "exactly")):
            with self.subTest(why):
                self.assertIn(why, self.ask(rid, **change)["refused"])
        (self.work / "bad.json").write_text("import os  # not data")
        self.assertIn("JSON data", self.ask("r9", run_ref="E-0008/s42@1", model="bad.json")["refused"])
        self.assertIn("other content", self.ask("r1", run_ref="E-0009/s42@1")["refused"])  # an id is not reused
        ledger = json.loads((self.private / "evaluator-ledger.json").read_text())
        self.assertEqual(len(ledger["scored"]), 2)

    def test_reg_s7_06_reconstructible_material_is_refused(self):
        self.assertTrue(private_material.check(self.private, None, tries=200)["ok"])
        bad = Path(self.tmp.name) / "bad"
        bad.mkdir()
        from toytrain import data
        rows = data.make_split("c1", 60, 133)  # the public c1 split: a public seed reproduces it
        (bad / "p1.jsonl").write_text(data.split_text(rows))
        (bad / "p1.generation.json").write_text(json.dumps({"name": "p1", "instance_seed": 133}))
        result = private_material.check(bad, None, tries=10)
        self.assertFalse(result["ok"])
        self.assertIn("reproduced by the public generator", result["problems"][0])


@unittest.skipUnless(shutil.which("bwrap"), "bwrap is not installed")
class CanaryTest(unittest.TestCase):
    def test_reg_s7_06_canary_is_unreachable_inside_and_reachable_outside(self):
        with tempfile.TemporaryDirectory(dir=Path.home()) as home_tmp, tempfile.TemporaryDirectory() as work:
            private = Path(home_tmp) / "private"
            canary = ROOT / "scripts" / "private_eval" / "canary.py"
            shutil.copy(canary, Path(work) / "canary.py")
            token = json.loads(subprocess.run([sys.executable, str(canary), "plant", "--private", str(private)],
                                              capture_output=True, text=True, check=True).stdout)["token_sha256"]
            probe = ["python3", str(Path(work) / "canary.py"), "probe", "--private", str(private), "--token-sha", token,
                     "--work", work]
            outside = json.loads(subprocess.run(probe, capture_output=True, text=True, timeout=120).stdout)
            self.assertTrue(outside["routes"]["direct_read"]["obtained"])  # the control: the canary is real
            inside = json.loads(subprocess.run([str(ROOT / "scripts" / "private_eval" / "sandbox.sh"), str(private),
                                                work, "--", *probe], capture_output=True, text=True, timeout=120).stdout)
            self.assertTrue(inside["blocked"], inside["routes"])
            self.assertTrue(inside["workspace_usable"])


if __name__ == "__main__":
    unittest.main()
