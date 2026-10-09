"""S2 (plans/research-tree-implementation-and-real-scenarios.md §6.4): independent confirmation of the frozen
candidate against the right baseline, and the project's confirmation-material usage. REG-S2-01..08. The numbers are
REG fixtures (the shared Fixture's runs), not measurements."""

from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))

from test_research_db import METHOD_CONFIG, PROTOCOL, ConfirmationTest, rdb  # noqa: E402

ResearchDB, ResearchDBError = rdb.ResearchDB, rdb.ResearchDBError


class S2Test(ConfirmationTest):
    protocol_content = {**PROTOCOL, "profile": "stage1_confirmed", "confirmation_seeds": [1042, 1043, 1044],
                        "max_confirmation_candidates": 2,
                        "confirmation_materials": [{"name": "c1", "seeds": [1042, 1043, 1044]},
                                                   {"name": "c2", "seeds": [2042, 2043, 2044]}]}
    test_u04_u05 = None  # the parent's scenario assumes another candidate limit
    test_rechecks_bind_to_the_confirmation_the_go_rests_on = None

    def setUp(self):
        super().setUp()
        self.h, self.exp = self.candidate_ready()
        self.batch_id = self.batch(self.h)

    def weak_control(self) -> str:
        """A baseline-kind control that is not the frozen reference (a much weaker method)."""
        design = self.doc(self.worker, f"exp/w{self.n}.v1.md", "experiment_design")
        weak = self.worker.create_experiment("baseline", "weak", design, self.harness, 1, 60,
                                             method_config={"lr": 0.0001, "weak": True}, estimated_node_h=0.1)
        self.finish_runs(self.worker, weak, metric_value=10.0)
        self.worker.evaluate_experiment(weak, self.result_doc(exp=weak))
        return weak

    def confirmed(self):
        base = self.confirm_baseline()
        conf = self.confirm(self.h, self.exp)
        self.evaluate(conf, None, sota=(0.3, 0.1, 0.1))
        return base, conf

    def test_reg_s2_01_an_unrelated_weak_control_is_never_the_reference(self):
        weak = self.weak_control()
        design = self.doc(self.worker, "exp/wb.v1.md", "experiment_design")
        with self.assertRaisesRegex(ResearchDBError, "CONFIRMATION_BASELINE_MISMATCH: the batch's reference"):
            self.worker.create_experiment("baseline", "weak", design, self.harness, 1, 60, stage="confirm",
                                          method_config={"lr": 0.0001, "weak": True}, confirmation_of=weak,
                                          confirmation_batch_id=self.batch_id, estimated_node_h=0.1)
        with self.assertRaisesRegex(ResearchDBError, "CONFIRMATION_BASELINE_MISMATCH: a confirmation baseline runs"):
            self.worker.create_experiment("baseline", "weak", design, self.harness, 1, 60, stage="confirm",
                                          method_config={"lr": 0.0001, "weak": True}, confirmation_of=self.sota,
                                          confirmation_batch_id=self.batch_id, estimated_node_h=0.1)
        base = self.confirm_baseline()
        with self.assertRaisesRegex(ResearchDBError, "CONFIRMATION_BASELINE_MISMATCH: a confirmation of batch"):
            self.confirm(self.h, self.exp, baseline_experiment_id=weak)
        conf = self.confirm(self.h, self.exp)
        self.evaluate(conf, None, sota=(0.3, 0.1, 0.1))
        before = self.rld.get_eligibility(self.h)
        self.assertEqual(self.rld.get(conf)["baseline_experiment_id"], base)
        delta = self.rld.edges("rel_compared_with", source_id=conf)[0]["delta_mean"]
        self.assertAlmostEqual(delta, 0.3)  # against the reference re-run (70.0 -> 70.3), never the 10.0 control
        # a control created later (another confirmation baseline of the batch) moves nothing
        self.confirm_baseline(walltime_s=1700)
        after = self.rld.get_eligibility(self.h)
        self.assertEqual((after["confirmation_evaluation_id"], after["stage"]),
                         (before["confirmation_evaluation_id"], "confirmed"))
        self.assertEqual(self.rld.get(conf)["baseline_experiment_id"], base)

    def test_reg_s2_02_a_retuned_method_on_the_same_material_is_refused(self):
        self.confirmed()
        with self.assertRaisesRegex(ResearchDBError, "CANDIDATE_IDENTITY_MISMATCH"):
            self.worker.create_experiment(
                "method", "m", self.doc(self.worker, "exp/rt.v1.md", "experiment_design"),
                self.rld.get(self.exp)["code_ref"], 1, 60, hypothesis_id=self.h, stage="confirm",
                method_config={"lr": 0.1}, candidate_spec_id=self._batch(self.batch_id)["candidates"][0],
                confirmation_batch_id=self.batch_id, estimated_node_h=1.0)
        # the list cannot grow once the material is in use: a batch with a new candidate on c1 is refused
        newer = self.method(self.h)
        self.evaluate(newer, "beats_sota", sota=(0.4, 0.1, 0.1))
        self.recheck_pass(self.h, newer)
        cand = self.rld.freeze_candidate(self.h, self.rld.get_eligibility(self.h)["basis_evaluation_id"])
        with self.assertRaisesRegex(ResearchDBError, "CONFIRMATION_MATERIAL_REUSED"):
            self.rld.create_confirmation_batch([cand], "c1")

    def test_reg_s2_03_s2_04_material_in_use_before_any_evaluation_and_across_nodes(self):
        base = self.confirm_baseline()
        conf = self.confirm(self.h, self.exp)
        run = f"{conf}/s1042"
        self.worker.create_run(conf, 1042)
        self.worker.update_run(run, exec_status="submitted")  # in use from here on; no evaluation exists yet
        events = self.rld.material_usage()["events"]
        self.assertEqual([(e["run"], e["event"]) for e in events if e["experiment"] == conf], [(f"{run}@1", "submitted")])
        self.assertTrue(any(e["experiment"] == base for e in events))
        # another node (a 'repair' with another name) does not clear the project's record
        h2, exp2 = self.candidate_ready()
        cand2 = self.rld.freeze_candidate(h2, self.rld.get_eligibility(h2)["basis_evaluation_id"])
        with self.assertRaisesRegex(ResearchDBError, "CONFIRMATION_MATERIAL_REUSED"):
            self.rld.create_confirmation_batch([cand2], "c1")
        # retracting or cancelling never removes the record
        self.worker.update_run(run, exec_status="cancelled")
        self.assertEqual(len([e for e in self.rld.material_usage()["events"] if e["experiment"] == conf]), 1)

    def test_reg_s2_05_one_frozen_batch_shares_its_material(self):
        # two nodes with the same method identity (same commit and configuration) count as one candidate
        code = self.rld.get(self.exp)["code_ref"]
        h2 = self.hypothesis()
        self.start(h2)
        twin = self.method(h2, code_ref=code)
        self.evaluate(twin, "beats_sota", sota=(0.3, 0.1, 0.1))
        self.rld.decide(h2, {"experiment_status": "beats_sota"}, "gate", based_on=[twin])
        self.recheck_pass(h2, twin)
        self.assertEqual(self.rld.get(twin)["method_spec_doc_id"], self.rld.get(self.exp)["method_spec_doc_id"])
        c1 = self._batch(self.batch_id)["candidates"][0]
        c2 = self.rld.freeze_candidate(h2, self.rld.get_eligibility(h2)["basis_evaluation_id"])
        shared = self.rld.create_confirmation_batch([c1, c2], "c2")
        self.batch_id = shared
        self.confirm_baseline()
        for h, exp in ((self.h, self.exp), (h2, twin)):
            conf = self.confirm(h, exp)
            self.evaluate(conf, None, sota=(0.3, 0.1, 0.1))
        self.assertEqual(self.rld.get_eligibility(h2)["stage"], "confirmed")
        # two more different methods would be three distinct candidates: over max_confirmation_candidates 2
        frozen = []
        for effect in (0.5, 0.6):
            other = self.method(self.h)
            self.evaluate(other, "beats_sota", sota=(effect, 0.1, 0.1))
            self.recheck_pass(self.h, other)
            frozen.append(self.rld.freeze_candidate(self.h, self.rld.get_eligibility(self.h)["basis_evaluation_id"]))
        with self.assertRaisesRegex(ResearchDBError, "BUDGET_EXCEEDED"):
            self.rld.create_confirmation_batch(frozen, "c2")

    def test_reg_s2_06_execution_retries_yes_result_shopping_no(self):
        self.confirm_baseline()
        conf = self.confirm(self.h, self.exp)
        run = f"{conf}/s1042"
        self.worker.create_run(conf, 1042)
        self.worker.update_run(run, exec_status="submitted")
        self.worker.update_run(run, exec_status="failed")  # a real execution failure: a new attempt is legitimate
        self.worker.update_run(run, attempt=2, exec_status="submitted")
        self.worker.update_run(run, exec_status="succeeded")
        self.worker.import_run_result(run, 2, self.manifest(conf, 1042, attempt=2))
        with self.assertRaisesRegex(ResearchDBError, "CONFIRMATION_MATERIAL_REUSED: .*imported confirmation result"):
            self.worker.update_run(run, valid=False, invalid_reason="the number looks bad")
        self.worker.update_run(run, valid=True)
        self.rld.retract_run(run, "evaluator bug", self.decision_doc())
        with self.assertRaisesRegex(ResearchDBError, "CONFIRMATION_MATERIAL_REUSED: .*not run again"):
            self.worker.update_run(run, attempt=3, exec_status="submitted")
        self.assertEqual([e["run"] for e in self.rld.material_usage()["events"] if e["experiment"] == conf],
                         [f"{run}@1", f"{run}@2", f"{run}@2"])  # both attempts and the import kept

    def test_reg_s2_07_unknown_restart_and_duplicate_import_keep_the_record(self):
        self.confirm_baseline()
        conf = self.confirm(self.h, self.exp)
        planned = f"{conf}/s1043"
        self.worker.create_run(conf, 1043)
        self.worker.update_run(planned, exec_status="cancelled")  # never submitted: not an exposure
        self.assertEqual([e for e in self.rld.material_usage()["events"] if e["experiment"] == conf], [])
        run = f"{conf}/s1042"
        self.worker.create_run(conf, 1042)
        self.worker.update_run(run, exec_status="submitted")
        self.worker.update_run(run, exec_status="succeeded")
        manifest = self.manifest(conf, 1042)
        self.worker.import_run_result(run, 1, manifest)
        again = ResearchDB(self.db, "worker/w1").import_run_result(run, 1, manifest)  # a restarted session repeats it
        self.assertFalse(again["imported"])
        self.assertEqual([e["event"] for e in self.rld.material_usage()["events"] if e["experiment"] == conf],
                         ["submitted", "imported"])

    def test_reg_s2_08_a_confirmation_without_bindings_cannot_support_go(self):
        base, conf = self.confirmed()
        self.assertEqual(self.rld.get_eligibility(self.h)["stage"], "confirmed")
        self.raw(conf, candidate_spec_doc_id=None)  # as a confirmation from before S2 was recorded
        result = self.rld.get_eligibility(self.h)
        self.assertIn("CONFIRMATION_IDENTITY_UNVERIFIED", result["reasons"])
        self.assertNotEqual(result["stage"], "confirmed")
        with self.assertRaisesRegex(ResearchDBError, "CONFIRMATION_REQUIRED|GO needs"):
            self.rld.decide("P-test", {"status": "go"}, "GO", doc_id=self.report_doc("go"))
        self.rld.migrate_identity(dry_run=False)
        self.rld.migrate_identity(dry_run=False)
        self.assertIn("CONFIRMATION_IDENTITY_UNVERIFIED", self.rld.get_eligibility(self.h)["reasons"])


if __name__ == "__main__":
    unittest.main()
