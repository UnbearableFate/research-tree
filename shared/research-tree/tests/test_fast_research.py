"""Fast research mechanics. Deterministic fixtures, not scientific or live-host efficacy claims."""
from __future__ import annotations

import unittest

from test_identity import IdentityFixture, ResearchDBError


class IdentityReplicationsTest(IdentityFixture):
    def test_experiment_review_binds_exact_method_and_claim(self):
        h = self.node()
        self.rld.update_project(code_review_required=True)
        code = self.commit()
        a, b = self.exp(h, code, {"lr": 0.1}), self.exp(h, code, {"lr": 0.2})
        basis = self.reviewer.review_basis(a, "code_review", code_ref=code)
        self.assertEqual(basis["method_spec_doc_ids"], [self.rld.get(a)["method_spec_doc_id"]])
        review = self.register(a, "code_review", "clear", basis, code_ref=code)
        with self.rld.reader() as tx:
            self.assertTrue(self.rld._code_review_applies(tx, tx.get(review), tx.get(a)))
            self.assertFalse(self.rld._code_review_applies(tx, tx.get(review), tx.get(b)))
        self.submit(a)
        self.rld.update_hypothesis(h, statement="new scientific claim")
        with self.rld.reader() as tx:
            self.assertFalse(self.rld._code_review_applies(tx, tx.get(review), tx.get(a)))

    def test_unsupported_review_subject_is_rejected(self):
        with self.assertRaisesRegex(ResearchDBError, "REVIEW_SUBJECT_UNSUPPORTED"):
            self.reviewer.review_basis(self.sota, "code_review")
        h = self.node()
        exp = self.exp(h, self.commit(), {"lr": 0.1})
        with self.assertRaisesRegex(ResearchDBError, "REVIEW_SUBJECT_UNSUPPORTED"):
            self.reviewer.review_basis(exp, "candidate_recheck")
        with self.assertRaisesRegex(ResearchDBError, "REVIEW_SUBJECT_UNSUPPORTED"):
            self.reviewer.review_basis(exp, "code_review", code_ref=self.harness)

    def test_scientific_config_change_at_same_commit_is_valid(self):
        h = self.node()
        exp = self.exp(h, self.harness, {"lr": 0.2})
        self.finish_runs(self.worker, exp)
        result = self.owner_for(exp).evaluate_experiment(exp, self.result_doc(exp=exp))
        self.assertTrue(result["evaluation_id"])

    def test_only_operational_config_change_cannot_fake_intervention(self):
        h = self.node()
        config = {**self.rld.get(self.sota)["effective_config"], "out": "elsewhere", "seed": 999}
        exp = self.exp(h, self.harness, config)
        self.finish_runs(self.worker, exp)
        with self.assertRaisesRegex(ResearchDBError, "different scientific configuration"):
            self.owner_for(exp).evaluate_experiment(exp, self.result_doc(exp=exp))

    def test_positive_signal_can_authorize_bounded_followup_seeds(self):
        self.rld.update_project(screen_seeds=1)
        h = self.node()
        exp = self.exp(h, self.commit(), {"lr": 0.1})
        self.effects[exp] = (self.sota, (0.3, 0.0, 0.0))
        self.finish_runs(self.worker, exp)
        self.owner_for(exp).evaluate_experiment(exp, self.result_doc(exp=exp))
        ev = self.rld.get(self.rld.get(exp)["evaluation_id"])
        self.assertEqual(ev["outcome"], "positive_signal")
        self.owner_for(exp).extend_seeds(exp, 3)
        self.assertEqual(self.rld.get(exp)["seeds"], [42, 43, 44])
        with self.assertRaisesRegex(ResearchDBError, "at most 3"):
            self.owner_for(exp).extend_seeds(exp, 4)

    def test_inconclusive_and_stale_positive_do_not_authorize_replication(self):
        self.rld.update_project(screen_seeds=1)
        h = self.node()
        a = self.exp(h, self.commit(), {"lr": 0.1})
        self.finish_runs(self.worker, a)
        self.owner_for(a).evaluate_experiment(a, self.result_doc(exp=a))
        with self.assertRaisesRegex(ResearchDBError, "current positive_signal"):
            self.owner_for(a).extend_seeds(a, 2)
        b = self.exp(h, self.commit(), {"lr": 0.2})
        self.effects[b] = (self.sota, (0.3, 0.0, 0.0))
        self.finish_runs(self.worker, b)
        self.owner_for(b).evaluate_experiment(b, self.result_doc(exp=b))
        self.rld.update_project(sota_experiment_id=self.baseline(1, 1800))
        with self.assertRaisesRegex(ResearchDBError, "current positive_signal"):
            self.owner_for(b).extend_seeds(b, 2)


if __name__ == "__main__":
    unittest.main()
