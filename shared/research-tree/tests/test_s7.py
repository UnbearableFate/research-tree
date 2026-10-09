"""S7 (plans/research-tree-implementation-and-real-scenarios.md §11.6): bounded repetition advice and findings that
can be checked before they reset a stall. REG-S7-01, 02, 07 (the scorer and evaluator cases are in the repository's
tests/). The numbers are REG fixtures."""

from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))

from test_research_db import PROTOCOL, SPECS, Fixture, MetricErrorAlias, ResearchDBError, metrics_mod  # noqa: E402

ABS = {**SPECS["metrics"][0]}  # absolute, percentage points
POLICY = {"enabled": True, "se_multiple": 2.0, "batch": 2, "seed_pool": [45, 46, 47, 48]}


def pairs(diffs, units=None):
    return [{"diff": d, "unit": (units[i] if units else (f"u{i}",))} for i, d in enumerate(diffs)]


class AdviceTest(unittest.TestCase):
    def advise(self, diffs, units=None, gain=0.5, used=(42, 43, 44), cost=100, available=10_000, policy=POLICY, spec=ABS):
        return metrics_mod.repetition_advice(spec, pairs(diffs, units), gain, policy, list(used), cost, available)

    def test_reg_s7_01_same_mean_different_spread(self):
        tight = self.advise([1.0, 1.05, 0.95])  # mean 1.0, SE ~0.03: clear of 0.5
        loose = self.advise([0.2, 1.8, 1.0])  # mean 1.0, SE ~0.46: within 2 SE of 0.5
        self.assertEqual((tight["advice"], loose["advice"]), ("enough", "add_repeats"))
        self.assertAlmostEqual(tight["mean"], loose["mean"])
        self.assertEqual(loose["seeds"], [45, 46])  # from the declared search pool, one batch
        one = self.advise([1.0])
        self.assertEqual((one["advice"], "variance is not known" in one["reason"], "sd" in one), ("add_repeats", True, False))
        flat = self.advise([0.9, 0.9, 0.9])
        self.assertEqual((flat["advice"], flat["se"]), ("enough", 0.0))
        self.assertEqual(self.advise([0.5, 0.5])["advice"], "add_repeats")  # exactly at the gain, zero spread
        self.assertEqual(self.advise([0.2, 1.8, 1.0], available=150)["seeds"], [45])  # one seed fits
        poor = self.advise([0.2, 1.8, 1.0], available=50)
        self.assertEqual(poor["advice"], "hold_inconclusive")
        used_up = self.advise([0.2, 1.8, 1.0], used=(42, 43, 44, 45, 46, 47, 48))
        self.assertEqual((used_up["advice"], "used up" in used_up["reason"]), ("hold_inconclusive", True))
        # the pool never borrows confirmation seeds: such a protocol is refused before any experiment
        with self.assertRaisesRegex(MetricErrorAlias, "never confirmation seeds"):
            metrics_mod.check_protocol({**PROTOCOL, "profile": "stage1_confirmed", "confirmation_seeds": [1042, 1043, 1044],
                                        "repetition": {**POLICY, "seed_pool": [45, 1042]}})
        self.assertEqual(self.advise([0.2, 1.8, 1.0], policy={**POLICY, "enabled": False})["advice"], "disabled")

    def test_reg_s7_07_unsupported_and_unverified_inputs(self):
        relative = {**ABS, "effect_mode": "relative_to_reference_mean", "relative_min_denominator": 1.0}
        out = self.advise([0.2, 1.8, 1.0], spec=relative)
        self.assertEqual(out["advice"], "unsupported_effect_mode")
        self.assertNotIn("se", out)  # no SE in another unit, no proposal
        self.assertNotIn("seeds", out)
        shared = self.advise([0.2, 1.8, 1.0], units=[("a",), ("a",), ("b",)])
        missing = self.advise([0.2, 1.8, 1.0], units=[("a",), None, ("b",)])
        for res in (shared, missing):
            self.assertEqual(res["advice"], "independence_unverified")
            self.assertNotIn("seeds", res)


class DbAdviceTest(Fixture):
    protocol_content = {**PROTOCOL, "independence_fields": ["data_order"], "repetition": POLICY}

    def test_advice_reads_the_runs_and_runs_nothing(self):
        h = self.hypothesis()
        self.start(h)
        exp = self.method(h)
        self.finish_runs(self.worker, exp, effect=(self.sota, (0.6, 0.0, 0.0)))  # reported without manifests
        before = len(self.rld.find("run"))
        advice = self.rld.repetition_advice(exp)
        self.assertEqual(advice["advice"], "independence_unverified")  # no recorded independence unit
        self.assertEqual(len(advice["pairs"]), 3)
        self.assertAlmostEqual(advice["pairs"][0]["diff"], 0.6)
        self.assertEqual(len(self.rld.find("run")), before)


class FindingsTest(Fixture):
    def finding(self, claim: str, evidence: list[str], about=()) -> str:
        body = (f"---\nkind: finding\nclaim: \"{claim}\"\nevidence_ids: {json.dumps(evidence)}\n"
                "interpretation: \"one reading\"\nlimitations: \"one setting\"\nstatus: supported\n---\n")
        doc = self.doc(self.rld, f"findings/f-{self.n}.v1.md", "finding", current=False, body=body, about=about)
        self.rld.set_document_current(doc)
        return doc

    def test_reg_s7_02_named_checked_findings_reset_a_stall(self):
        h = self.hypothesis()
        ev = self.rld.get(self.sota)["evaluation_id"]
        batch = lambda: self.decision_doc()  # noqa: E731
        self.assertEqual(self.rld.note_findings(h, 0, batch())["streak"], 1)
        self.assertEqual(self.rld.note_findings(h, 0, batch())["stall_state"], "structural")
        with self.assertRaisesRegex(ResearchDBError, "STALL_EVIDENCE_REQUIRED: 2 new finding"):
            self.rld.note_findings(h, 2, batch())  # a bare count
        f1 = self.finding("the reference reaches 70", [ev], about=(h,))
        with self.assertRaisesRegex(ResearchDBError, "STALL_EVIDENCE_REQUIRED: new_findings 2 but 1"):
            self.rld.note_findings(h, 2, batch(), finding_ids=[f1])
        doc = batch()
        out = self.rld.note_findings(h, 1, doc, finding_ids=[f1], rationale="the first measured fact of this node")
        self.assertEqual((out["streak"], out["accepted"]), (0, [f1]))
        self.assertEqual(self.rld.note_findings(h, 1, doc, finding_ids=[f1])["streak"], 0)  # the same batch again
        # the same finding, or the same claim and evidence repackaged, is not new
        again = self.finding("the reference  reaches 70", [ev], about=(h,))
        out = self.rld.note_findings(h, None, batch(), finding_ids=[f1, again])
        self.assertEqual((out["accepted"], out["streak"]), ([], 1))
        self.assertEqual(len(out["not_counted"]), 2)
        # a finding whose evidence no longer holds is not counted
        stale = self.finding("a second fact", [ev], about=(h,))
        self.rld.update_project(harness_ref=self.commit({"harness/stats.py": "stats v2\n"}), harness_paths=["harness"])
        out = self.rld.note_findings(h, None, batch(), finding_ids=[stale])
        self.assertEqual((out["accepted"], out["streak"]), ([], 2))
        self.assertIn("stale", out["not_counted"][0])


if __name__ == "__main__":
    unittest.main()
