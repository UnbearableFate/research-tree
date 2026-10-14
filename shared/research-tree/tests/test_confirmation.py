"""S2 (plans/research-tree-implementation-and-real-scenarios.md §6.4): independent confirmation of the frozen
candidate against the right baseline, and the project's confirmation-material usage. REG-S2-01..08. The numbers are
REG fixtures (the shared Fixture's runs), not measurements."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))

from test_research_db import PROTOCOL, ConfirmationTest, rdb  # noqa: E402

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
        weak = self.architect.create_experiment("baseline", "weak", design, self.harness, 1, 60,
                                             method_config={"lr": 0.0001, "weak": True}, estimated_node_h=0.1)
        self.finish_runs(self.worker, weak, metric_value=10.0)
        self.owner_for(weak).evaluate_experiment(weak, self.result_doc(exp=weak))
        return weak

    def confirmed(self):
        base = self.confirm_baseline()
        conf = self.confirm(self.h, self.exp)
        self.evaluate(conf, sota=(0.3, 0.1, 0.1))
        return base, conf

    def test_reg_s2_01_an_unrelated_weak_control_is_never_the_reference(self):
        weak = self.weak_control()
        design = self.doc(self.worker, "exp/wb.v1.md", "experiment_design")
        with self.assertRaisesRegex(ResearchDBError, "CONFIRMATION_BASELINE_MISMATCH: the batch's reference"):
            self.architect.create_experiment("baseline", "weak", design, self.harness, 1, 60, stage="confirm",
                                          method_config={"lr": 0.0001, "weak": True}, confirmation_of=weak,
                                          confirmation_batch_id=self.batch_id, estimated_node_h=0.1)
        with self.assertRaisesRegex(ResearchDBError, "CONFIRMATION_BASELINE_MISMATCH: a confirmation baseline runs"):
            self.architect.create_experiment("baseline", "weak", design, self.harness, 1, 60, stage="confirm",
                                          method_config={"lr": 0.0001, "weak": True}, confirmation_of=self.sota,
                                          confirmation_batch_id=self.batch_id, estimated_node_h=0.1)
        base = self.confirm_baseline()
        with self.assertRaisesRegex(ResearchDBError, "CONFIRMATION_BASELINE_MISMATCH: a confirmation of batch"):
            self.confirm(self.h, self.exp, baseline_experiment_id=weak)
        conf = self.confirm(self.h, self.exp)
        self.evaluate(conf, sota=(0.3, 0.1, 0.1))
        before = self.rld.get_eligibility(self.h)
        self.assertEqual(self.rld.get(conf)["baseline_experiment_id"], base)
        delta = self.rld.edges("rel_compared_with", source_id=conf)[0]["delta_mean"]
        self.assertAlmostEqual(delta, 0.3)  # against the reference re-run (70.0 -> 70.3), never the 10.0 control
        # Resizing/relabeling a completed confirmation baseline reuses its immutable evidence.
        original = self.rld.get(base)
        same = self.architect.create_experiment("baseline", "renamed baseline", original["design_doc_id"],
            original["code_ref"], 1, 1700, stage="confirm", method_config=original["effective_config"],
            confirmation_of=self.sota, confirmation_batch_id=self.batch_id, estimated_node_h=1.0)
        self.assertEqual(same, base)
        self.assertEqual(self.rld.get(base), original)
        after = self.rld.get_eligibility(self.h)
        self.assertEqual((after["confirmation_evaluation_id"], after["stage"]),
                         (before["confirmation_evaluation_id"], "confirmed"))
        self.assertEqual(self.rld.get(conf)["baseline_experiment_id"], base)

    def test_a_confirmation_preview_names_its_own_baseline(self):  # S2 real scenario (Claude a01)
        base = self.confirm_baseline()
        conf = self.confirm(self.h, self.exp)
        self.finish_runs(self.worker, conf, effect=(base, (0.3, 0.1, 0.1)))
        same = self.rld.preview_evaluation(conf, baseline_experiment_id=base)  # naming its own baseline is fine
        self.assertEqual(same["references"]["sota"], base)
        with self.assertRaisesRegex(ResearchDBError, "is a confirmation: it is compared with its batch's fixed baseline"):
            self.rld.preview_evaluation(conf, baseline_experiment_id=self.sota)

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
        self.evaluate(newer, sota=(0.4, 0.1, 0.1))
        self.recheck_pass(self.h, newer)
        cand = self.rld.freeze_candidate(self.h, self.rld.get_eligibility(self.h)["basis_evaluation_id"])
        with self.assertRaisesRegex(ResearchDBError, "CONFIRMATION_MATERIAL_REUSED"):
            self.rld.create_confirmation_batch([cand], "c1")

    def test_reg_s2_03_s2_04_material_in_use_before_any_evaluation_and_across_nodes(self):
        base = self.confirm_baseline()
        conf = self.confirm(self.h, self.exp)
        run = f"{conf}/s1042"
        self.owner_for(conf).create_run(conf, 1042)
        self.owner_for_run(run).update_run(run, exec_status="submitted")  # in use from here on; no evaluation exists yet
        events = self.rld.material_usage()["events"]
        self.assertEqual([(e["run"], e["event"]) for e in events if e["experiment"] == conf], [(f"{run}@1", "submitted")])
        self.assertTrue(any(e["experiment"] == base for e in events))
        # another node (a 'repair' with another name) does not clear the project's record
        h2, exp2 = self.candidate_ready()
        cand2 = self.rld.freeze_candidate(h2, self.rld.get_eligibility(h2)["basis_evaluation_id"])
        with self.assertRaisesRegex(ResearchDBError, "CONFIRMATION_MATERIAL_REUSED"):
            self.rld.create_confirmation_batch([cand2], "c1")
        # retracting or cancelling never removes the record
        self.owner_for_run(run).update_run(run, exec_status="cancelled")
        self.assertEqual(len([e for e in self.rld.material_usage()["events"] if e["experiment"] == conf]), 1)

    def test_material_is_in_use_once_a_submission_is_claimed(self):
        """A claimed submission may reach the scheduler even when the run is later reported cancelled from planned."""
        self.confirm_baseline()
        conf = self.confirm(self.h, self.exp)
        run = f"{conf}/s1042"
        owner = self.owner_for(conf)
        owner.create_run(conf, 1042)
        owner.reserve_submission("k-confirm", [f"{run}@1"], {"nodes": 1, "walltime_s": 60})
        owner.claim_submission("k-confirm")
        events = [(e["run"], e["event"]) for e in self.rld.material_usage()["events"] if e["experiment"] == conf]
        self.assertEqual(events, [(f"{run}@1", "claimed")])
        self.owner_for_run(run).update_run(run, exec_status="cancelled")
        h2, _ = self.candidate_ready()
        cand2 = self.rld.freeze_candidate(h2, self.rld.get_eligibility(h2)["basis_evaluation_id"])
        with self.assertRaisesRegex(ResearchDBError, "CONFIRMATION_MATERIAL_REUSED"):
            self.rld.create_confirmation_batch([cand2], "c1")

    def test_a_failed_confirmation_is_not_tried_again_on_new_material(self):
        """INV-03: a method is confirmed once; a negative confirmation stands."""
        self.confirm_baseline()
        first = self.confirm(self.h, self.exp)
        self.assertEqual(self.evaluate(first, sota=(-0.3, 0.0, 0.0))["outcome"], "negative_signal")
        candidate = self._batch(self.batch_id)["candidates"][0]
        with self.assertRaisesRegex(ResearchDBError, "CONFIRMATION_REUSED"):
            self.rld.create_confirmation_batch([candidate], "c2")
        self.assertIn("CONFIRMATION_FAILED", self.rld.get_eligibility(self.h)["reasons"])

    def test_reg_s2_05_distinct_methods_share_a_frozen_batch_and_baseline(self):
        # Distinct methods share one predeclared batch and matching baseline, not duplicate trials
        code = self.commit()
        h2 = self.hypothesis()
        self.start(h2)
        twin = self.method(h2, code_ref=code)
        self.evaluate(twin, sota=(0.3, 0.1, 0.1))
        self.rld.decide(h2, {"experiment_status": "beats_sota"}, "gate", based_on=[twin])
        self.recheck_pass(h2, twin)
        self.assertNotEqual(self.rld.get(twin)["method_spec_doc_id"], self.rld.get(self.exp)["method_spec_doc_id"])
        c1 = self._batch(self.batch_id)["candidates"][0]
        c2 = self.rld.freeze_candidate(h2, self.rld.get_eligibility(h2)["basis_evaluation_id"])
        shared = self.rld.create_confirmation_batch([c1, c2], "c2")
        self.batch_id = shared
        baseline = self.confirm_baseline()
        for h, exp in ((self.h, self.exp), (h2, twin)):
            conf = self.confirm(h, exp)
            self.assertEqual(self.rld.get(conf)["baseline_experiment_id"], baseline)
            self.evaluate(conf, sota=(0.3, 0.1, 0.1))
        self.assertEqual(self.rld.get_eligibility(h2)["stage"], "confirmed")
        # two more different methods would be four distinct candidates: over max_confirmation_candidates 2
        frozen = []
        for effect in (0.5, 0.6):
            other = self.method(self.h)
            self.evaluate(other, sota=(effect, 0.1, 0.1))
            self.recheck_pass(self.h, other)
            frozen.append(self.rld.freeze_candidate(self.h, self.rld.get_eligibility(self.h)["basis_evaluation_id"]))
        with self.assertRaisesRegex(ResearchDBError, "BUDGET_EXCEEDED"):
            self.rld.create_confirmation_batch(frozen, "c2")

    def test_reg_s2_06_execution_retries_yes_result_shopping_no(self):
        self.confirm_baseline()
        conf = self.confirm(self.h, self.exp)
        run = f"{conf}/s1042"
        self.owner_for(conf).create_run(conf, 1042)
        self.owner_for_run(run).update_run(run, exec_status="submitted")
        self.owner_for_run(run).update_run(run, exec_status="failed")  # a real execution failure: a new attempt is legitimate
        self.owner_for_run(run).update_run(run, attempt=2, exec_status="submitted")
        self.owner_for_run(run).update_run(run, exec_status="succeeded")
        self.owner_for_run(run).import_run_result(run, 2, self.manifest(conf, 1042, attempt=2))
        with self.assertRaisesRegex(ResearchDBError, "CONFIRMATION_MATERIAL_REUSED: .*imported confirmation result"):
            self.owner_for_run(run).update_run(run, valid=False, invalid_reason="the number looks bad")
        self.owner_for_run(run).update_run(run, valid=True)
        self.rld.retract_run(run, "evaluator bug", self.decision_doc())
        with self.assertRaisesRegex(ResearchDBError, "CONFIRMATION_MATERIAL_REUSED: .*not run again"):
            self.owner_for_run(run).update_run(run, attempt=3, exec_status="submitted")
        self.assertEqual([e["run"] for e in self.rld.material_usage()["events"] if e["experiment"] == conf],
                         [f"{run}@1", f"{run}@2", f"{run}@2"])  # both attempts and the import kept

    def test_reg_s2_07_unknown_restart_and_duplicate_import_keep_the_record(self):
        self.confirm_baseline()
        conf = self.confirm(self.h, self.exp)
        planned = f"{conf}/s1043"
        self.owner_for(conf).create_run(conf, 1043)
        self.owner_for_run(planned).update_run(planned, exec_status="cancelled")  # never submitted: not an exposure
        self.assertEqual([e for e in self.rld.material_usage()["events"] if e["experiment"] == conf], [])
        run = f"{conf}/s1042"
        self.owner_for(conf).create_run(conf, 1042)
        self.owner_for_run(run).update_run(run, exec_status="submitted")
        self.owner_for_run(run).update_run(run, exec_status="succeeded")
        manifest = self.manifest(conf, 1042)
        self.owner_for_run(run).import_run_result(run, 1, manifest)
        again = ResearchDB(self.db, "worker/w1").import_run_result(run, 1, manifest)  # a restarted session repeats it
        self.assertFalse(again["imported"])
        self.assertEqual([e["event"] for e in self.rld.material_usage()["events"] if e["experiment"] == conf],
                         ["submitted", "imported"])

    def test_reg_s2_08_a_confirmation_without_bindings_cannot_support_go(self):
        base, conf = self.confirmed()
        self.assertEqual(self.rld.get_eligibility(self.h)["stage"], "confirmed")
        self.raw(conf, candidate_spec_doc_id=None)  # corrupt binding must fail closed
        result = self.rld.get_eligibility(self.h)
        self.assertIn("CONFIRMATION_IDENTITY_UNVERIFIED", result["reasons"])
        self.assertNotEqual(result["stage"], "confirmed")
        with self.assertRaisesRegex(ResearchDBError, "CONFIRMATION_REQUIRED|GO needs"):
            self.rld.decide("P-test", {"status": "go"}, "GO", doc_id=self.report_doc("go"))
        self.assertFalse(hasattr(self.rld, "migrate_identity"))
        self.assertIn("CONFIRMATION_IDENTITY_UNVERIFIED", self.rld.get_eligibility(self.h)["reasons"])


class ConfirmationIdentityTest(ConfirmationTest):
    test_u04_u05 = None
    test_rechecks_bind_to_the_confirmation_the_go_rests_on = None
    protocol_content = {**ConfirmationTest.protocol_content, "confirmation_materials": [
        {"name": "c1", "seeds": [1042, 1043, 1044], "split_sha256": "a" * 64},
        {"name": "c2", "seeds": [1042, 1043, 1044], "split_sha256": "b" * 64}]}

    def test_negative_confirmation_cannot_be_retried_by_renaming_or_resizing(self):
        h, exp = self.candidate_ready()
        self.batch_id = self.batch(h)
        self.confirm_baseline()
        first = self.confirm(h, exp)
        result = self.evaluate(first, sota=(-0.3, 0.0, 0.0))
        self.assertEqual(result["outcome"], "negative_signal")
        row = self.rld.get(first)
        before = (len(self.rld.find("experiment")), len(self.rld.find("run")))
        kwargs = {"kind": "method", "method_name": "retry-new-label", "design_doc_id": row["design_doc_id"],
                  "code_ref": row["code_ref"], "nodes": row["nodes"], "walltime_s": row["walltime_s"],
                  "hypothesis_id": h, "stage": "confirm", "method_config": row["effective_config"],
                  "candidate_spec_id": row["candidate_spec_doc_id"],
                  "confirmation_batch_id": row["confirmation_batch_doc_id"], "estimated_node_h": 1.0}
        for extra in ({}, {"nodes": 2}, {"walltime_s": 30},
                      {"method_config": {**row["effective_config"], "out": "retry-outputs"}}):
            with self.subTest(extra=extra):
                duplicate = self.worker.create_experiment(**{**kwargs, **extra})
                self.assertEqual(duplicate, first)
                with self.assertRaisesRegex(ResearchDBError, "already exists"):
                    self.worker.create_run(duplicate, 1042)
        # Validation must precede dedup: an invalid frozen reference does not receive the existing ID.
        with self.assertRaisesRegex(ResearchDBError, "CONFIRMATION_BASELINE_MISMATCH"):
            self.worker.create_experiment(**kwargs, baseline_experiment_id=self.sota)
        self.assertEqual(self.rld.get(first), row)
        self.assertEqual(before, (len(self.rld.find("experiment")), len(self.rld.find("run"))))
        self.assertIn("CONFIRMATION_FAILED", self.rld.get_eligibility(h)["reasons"])

    def test_distinct_holdout_materials_can_use_the_same_training_seeds(self):
        h, exp = self.candidate_ready()
        first_batch, second_batch = self.batch(h, material="c1"), self.batch(h, material="c2")
        first_base, second_base = self.confirm_baseline(first_batch), self.confirm_baseline(second_batch)
        first = self.confirm(h, exp, batch=first_batch)
        second = self.confirm(h, exp, batch=second_batch)
        a, b = self.rld.get(first), self.rld.get(second)
        self.assertNotEqual(first, second)
        self.assertNotEqual(first_base, second_base)
        self.assertEqual(a["method_spec_doc_id"], b["method_spec_doc_id"])
        self.assertEqual(a["seeds"], b["seeds"])
        self.assertNotEqual(a["material_key"], b["material_key"])
        for candidate in (first, second):
            run = self.worker.create_run(candidate, 1042)
            self.worker.update_run(run, exec_status="submitted")
            self.assertEqual(self.rld.get(run)["exec_status"], "submitted")

    def test_duplicate_claim_cites_existing_confirmation_instead_of_resampling(self):
        h, exp = self.candidate_ready()
        h2 = self.hypothesis()
        self.start(h2)
        method = self.rld.get(exp)
        twin = self.worker.create_experiment("method", "same method, new claim", method["design_doc_id"],
            method["code_ref"], 1, 60, hypothesis_id=h2, method_config=method["effective_config"], estimated_node_h=0.1)
        self.evaluate(twin)
        self.rld.decide(h2, {"experiment_status": "beats_sota"}, "gate", based_on=[twin])
        self.recheck_pass(h2, twin)
        self.batch_id = self.batch(h, h2)
        self.assertEqual(len(self._batch(self.batch_id)["method_specs"]), 1)
        self.confirm_baseline()
        first = self.confirm(h, exp)
        self.evaluate(first, sota=(-0.3, 0.0, 0.0))
        before = len(self.rld.find("experiment"))
        with self.assertRaisesRegex(ResearchDBError, f"CONFIRMATION_MATERIAL_REUSED: {first} already confirms"):
            self.confirm(h2, twin)
        self.assertEqual(len(self.rld.find("experiment")), before)


if __name__ == "__main__":
    unittest.main()
