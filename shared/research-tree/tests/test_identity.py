"""S1 (plans/research-tree-implementation-and-real-scenarios.md §5.4): method identity, claim revisions, stable
discovery candidates and the system-captured review basis. REG-S1-01..06."""

from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path

TOOLS = Path(__file__).resolve().parents[1] / "tools"
sys.path.insert(0, str(TOOLS))

import discovery  # noqa: E402
from test_research_db import METHOD_CONFIG, Fixture, rdb, recheck_payload  # noqa: E402

ResearchDB, ResearchDBError = rdb.ResearchDB, rdb.ResearchDBError


class IdentityFixture(Fixture):
    def setUp(self):
        super().setUp()
        self.reviewer = ResearchDB(self.db, "reviewer/pi")
        (self.reviewer.docs_root / "reviews").mkdir(exist_ok=True)
        self.k = 0

    def node(self) -> str:
        h = self.hypothesis()
        self.start(h)
        return h

    def exp(self, h: str, code: str, config: dict, kind: str = "method", walltime: int = 60, **kw) -> str:
        self.n += 1
        design = self.doc(self.worker, f"exp/i{self.n}/design.v1.md", "experiment_design")
        return self.worker.create_experiment(kind, "m", design, code, 1, walltime, hypothesis_id=h, n_seeds=1,
                                             method_config=config, estimated_node_h=0.1,
                                             selection_rationale="identity test", **kw)

    def register(self, about: str, kind: str, result: str, basis: dict | None, **kw) -> str:
        self.k += 1
        path = f"reviews/RV-{9000 + self.k:04d}.v1.md"
        (self.reviewer.docs_root / path).write_text(result, encoding="utf-8")
        return self.reviewer.register_review(path, kind, kind, [about], result, f"RV-{9000 + self.k:04d}", "pi",
                                             "openai/gpt-6-luna", 0.0, basis=basis, **kw)

    def recheck(self, h: str, dimension: str, ev: str, result: str = "pass") -> str:
        return self.register(h, "candidate_recheck", result,
                             self.reviewer.review_basis(h, "candidate_recheck", dimension, ev),
                             dimension=dimension, evaluation_id=ev, payload=recheck_payload(self, dimension, result, ev))

    def submit(self, exp: str) -> None:
        run = f"{exp}/s{self.rld.get(exp)['seeds'][0]}"
        if self.rld.get(run) is None:
            self.worker.create_run(exp, self.rld.get(exp)["seeds"][0])
        self.worker.update_run(run, exec_status="submitted")


class MethodSpecTest(IdentityFixture):
    def test_reg_s1_01_identity_from_configuration_not_from_execution(self):
        # the SOTA baseline of the fixture already has one, without any search result
        sota = self.rld.get(self.sota)
        self.assertEqual(self.rld.get(sota["method_spec_doc_id"])["doc_type"], "method_spec")
        h = self.node()
        code = self.commit()
        a = self.exp(h, code, {"lr": 0.05, "out": "outputs/a"})
        b = self.exp(h, code, {"lr": 0.1, "out": "outputs/a"})
        c = self.exp(h, code, {"lr": 0.05, "out": "outputs/c", "walltime": 900, "eval_split": "c1"}, walltime=120)
        sa, sb, sc = (self.rld.get(x) for x in (a, b, c))
        self.assertNotEqual(sa["method_spec_doc_id"], sb["method_spec_doc_id"])  # same code, another learning rate
        self.assertEqual(sa["method_spec_doc_id"], sc["method_spec_doc_id"])  # only execution fields differ
        spec = json.loads((self.root / "docs" / self.rld.get(sa["method_spec_doc_id"])["path"]).read_text())
        self.assertEqual((spec["code_ref"], spec["config"]), (code, {"lr": 0.05}))
        self.assertEqual(sa["effective_config"], {"lr": 0.05, "out": "outputs/a"})  # the whole configuration kept
        # an unknown field is scientific by default
        d = self.exp(h, code, {"lr": 0.05, "warmup": 3})
        self.assertNotEqual(self.rld.get(d)["method_spec_doc_id"], sa["method_spec_doc_id"])
        with self.assertRaisesRegex(ResearchDBError, "METHOD_SPEC_INCOMPLETE"):
            self.worker.create_experiment("method", "m", self.doc(self.worker, "exp/x.v1.md", "experiment_design"),
                                          code, 1, 60, hypothesis_id=h, n_seeds=1, estimated_node_h=0.1,
                                          selection_rationale="x")

    def test_reg_s1_03_part_runs_import_only_with_their_identitys_configuration(self):
        h = self.node()
        exp = self.exp(h, self.commit(), {"lr": 0.05})
        run = f"{exp}/s{SEED}"
        self.worker.create_run(exp, SEED)
        self.worker.update_run(run, exec_status="submitted")
        self.worker.update_run(run, exec_status="succeeded")
        with self.assertRaisesRegex(ResearchDBError, "METHOD_SPEC_MISMATCH: .*lr: spec 0.05, run 0.1"):
            self.worker.import_run_result(run, 1, self.manifest(exp, SEED, config={"lr": 0.1}))
        self.assertIsNone(self.rld.get(run).get("import_record"))  # nothing half-written
        self.worker.import_run_result(run, 1, self.manifest(exp, SEED, config={"lr": 0.05, "eval_split": "explore"}))


SEED = 42


class ClaimAndBasisTest(IdentityFixture):
    def candidate_with_rechecks(self):
        h, exp = self.concluded("beats_sota")
        self.rld.decide(h, {"experiment_status": "beats_sota"}, "gate", based_on=[exp])
        self.recheck_pass(h, exp)
        self.rld.update_project(recheck_required=True)
        ev = self.rld.get(exp)["evaluation_id"]
        for dimension in rdb.RECHECK_DIMENSIONS:
            self.recheck(h, dimension, ev)
        return h, exp, ev

    def states(self, h):
        e = self.rld.get_eligibility(h)
        return {r["dimension"]: r["state"] for r in e["rechecks"]}, e

    def test_reg_s1_02_a_broader_claim_invalidates_the_claim_bound_reviews_only(self):
        h, exp, ev = self.candidate_with_rechecks()
        states, before = self.states(h)
        self.assertEqual(set(states.values()), {"pass"})
        self.assertTrue(before["eligible"], before["reasons"])
        out = self.rld.update_hypothesis(h, statement="对所有分布都有收敛保证")
        self.assertEqual((out["claim_revision"], out["new_revision"]), (2, True))
        states, after = self.states(h)
        self.assertEqual(states, {"numbers": "pass", "protocol": "pass", "method_code": "stale",
                                  "novelty": "stale", "theory": "stale"})
        self.assertEqual(after["basis_evaluation_id"], ev)  # the numbers are not rewritten
        self.assertFalse(after["eligible"])
        self.assertIn("RECHECK_STALE", after["reasons"])
        self.assertFalse(after["rld_rechecks"]["novelty"]["bound"])  # REG-S1-06: the RLD's pass judged the old claim
        # a layout-only edit of the same claim is no new revision; a narrowed claim is the next one
        self.assertFalse(self.rld.update_hypothesis(h, statement="  对所有分布都有收敛保证 ")["new_revision"])
        narrowed = self.rld.update_hypothesis(h, statement="s")
        self.assertEqual(narrowed["claim_revision"], 3)
        self.assertEqual(len(self.rld.get(h)["claim_history"]["revisions"]), 3)

    def test_reg_s1_04_a_subject_changed_while_the_reviewer_answered_is_history_only(self):
        h, exp, ev = self.candidate_with_rechecks()
        basis = self.reviewer.review_basis(h, "candidate_recheck", "novelty", ev)
        self.rld.update_hypothesis(h, statement="更宽的主张")  # changes during the call
        self.rld.update_hypothesis(h, statement="s")  # and back to the same words: still another revision
        doc = self.register(h, "candidate_recheck", "pass", basis, dimension="novelty", evaluation_id=ev,
                            payload=recheck_payload(self, "novelty", "pass", ev))
        self.assertTrue(self.rld.get(doc)["review_basis_changed"])
        states, _ = self.states(h)
        self.assertEqual(states["novelty"], "stale")
        # a review registered without a basis (before S1) never binds the current state
        self.register(h, "candidate_recheck", "pass", None, dimension="numbers", evaluation_id=ev,
                      payload=recheck_payload(self, "numbers", "pass", ev))
        states, e = self.states(h)
        self.assertEqual(states["numbers"], "stale")
        self.assertTrue(next(r for r in e["rechecks"] if r["dimension"] == "numbers")["needs_recheck"])

    def test_reg_s1_06_same_code_new_configuration_or_claim_needs_new_clearance(self):
        h = self.node()
        self.rld.update_project(sanity_required=True, code_review_required=True)
        code = self.commit()
        exp = self.exp(h, code, {"lr": 0.05})
        # a sanity of the method, declared as a projection (short training), counts for it
        sanity = self.exp(h, code, {"lr": 0.05}, kind="sanity", sanity_overrides={"epochs": 2, "sanity": True})
        self.assertEqual(self.rld.get(sanity)["sanity_target_spec_doc_id"], self.rld.get(exp)["method_spec_doc_id"])
        with self.assertRaisesRegex(ResearchDBError, "may override only"):
            self.exp(h, code, {"lr": 0.05}, kind="sanity", sanity_overrides={"lr": 0.5})
        self.finish_runs(self.worker, sanity)
        self.register(h, "code_review", "clear", self.reviewer.review_basis(h, "code_review", code_ref=code),
                      code_ref=code)
        self.submit(exp)
        # the same commit with another learning rate: no sanity of it, no review of it
        other = self.exp(h, code, {"lr": 0.1})
        with self.assertRaisesRegex(ResearchDBError, "SANITY_REQUIRED"):
            self.submit(other)
        unrelated = self.exp(h, code, {"lr": 0.3}, kind="sanity")  # a sanity of other settings does not stand in
        self.finish_runs(self.worker, unrelated)
        with self.assertRaisesRegex(ResearchDBError, "SANITY_REQUIRED"):
            self.submit(other)
        sanity2 = self.exp(h, code, {"lr": 0.1}, kind="sanity", sanity_overrides={"epochs": 2})
        self.finish_runs(self.worker, sanity2)
        with self.assertRaisesRegex(ResearchDBError, "CODE_REVIEW_REQUIRED: .*is missing"):
            self.submit(other)
        # a waiver binds the claim revision it was given for
        log = self.root / "logs" / "review_calls.jsonl"
        log.parent.mkdir(exist_ok=True)
        log.write_text(json.dumps({"kind": "code_review", "about": h, "outcome": "REVIEW_UNAVAILABLE"}) + "\n")
        self.rld.waive_code_review(other, self.decision_doc())
        self.rld.update_hypothesis(h, statement="更宽的主张")
        with self.assertRaisesRegex(ResearchDBError, "CODE_REVIEW_REQUIRED"):
            self.submit(other)
        # and the clear review of the first configuration no longer applies after the claim changed either
        third = self.exp(h, code, {"lr": 0.05}, walltime=61)
        self.assertEqual(self.rld.get(third)["method_spec_doc_id"], self.rld.get(exp)["method_spec_doc_id"])
        with self.assertRaisesRegex(ResearchDBError, "CODE_REVIEW_REQUIRED"):
            self.submit(third)


class CandidateTest(unittest.TestCase):
    def receipt(self, c: dict) -> dict:
        return {"review_kind": "novelty_precheck", "status": "current", "review_about": c["id"],
                "review_basis": {"candidate_id": c["id"], "revision": c["revision"], "content_sha": c["content_sha"]}}

    def test_reg_s1_03_reordering_and_insertion_move_no_receipt(self):
        zebra = {"title": "Zebra 动量", "summary": "heavy ball"}
        first = discovery.merge([], [zebra])
        z = first[0]
        self.assertEqual(z["id"], "CAND-0001")
        receipt = self.receipt(z)
        alpha = {"title": "Alpha 学习率预热", "summary": "warmup"}
        second = discovery.merge([], [alpha, zebra], first)
        by_title = {c["title"]: c for c in second}
        self.assertEqual(by_title["Zebra 动量"]["id"], "CAND-0001")  # sorted first or not, Zebra keeps its id
        self.assertEqual(by_title["Alpha 学习率预热"]["id"], "CAND-0002")
        self.assertTrue(discovery.receipt_applies(receipt, by_title["Zebra 动量"]))
        self.assertFalse(discovery.receipt_applies({**receipt, "review_about": "CAND-0002"}, by_title["Alpha 学习率预热"]))
        # Alpha's mechanism changes: same id, next revision; a receipt of the old revision no longer counts
        old_alpha = self.receipt(by_title["Alpha 学习率预热"])
        third = discovery.merge([], [{"title": "Alpha 学习率预热", "summary": "cosine schedule"}, zebra], second)
        a3 = next(c for c in third if c["title"].startswith("Alpha"))
        self.assertEqual((a3["id"], a3["revision"]), ("CAND-0002", 2))
        self.assertFalse(discovery.receipt_applies(old_alpha, a3))
        # removing Alpha and adding Beta: Beta gets a new number, never Alpha's
        fourth = discovery.merge([], [zebra, {"title": "Beta 梯度裁剪", "summary": "clip"}], third)
        ids = {c["title"]: (c["id"], c["present"]) for c in fourth}
        self.assertEqual(ids["Beta 梯度裁剪"], ("CAND-0003", True))
        self.assertEqual(ids["Alpha 学习率预热"], ("CAND-0002", False))
        # merging the same inputs again changes nothing
        self.assertEqual(discovery.merge([], [zebra, {"title": "Beta 梯度裁剪", "summary": "clip"}], fourth), fourth)


class MigrationTest(IdentityFixture):
    def test_reg_s1_05_legacy_records_need_rechecks_and_migration_is_idempotent(self):
        h, exp = self.concluded("beats_sota")
        self.rld.update_project(recheck_required=True)
        ev = self.rld.get(exp)["evaluation_id"]
        old_review = self.register(h, "candidate_recheck", "pass", None, dimension="numbers", evaluation_id=ev,
                                   payload=recheck_payload(self, "numbers", "pass", ev))
        # records as an older plugin left them
        self.raw(h, claim_sha=None, claim_revision=None, claim_history=None)
        self.raw(exp, method_spec_doc_id=None, method_spec_sha=None)
        dry = self.rld.migrate_identity()
        self.assertIn(h, dry["claims"])
        self.assertIn(exp, dry["legacy_unbound_experiments"])
        self.assertIn(old_review, dry["needs_recheck_reviews"])
        self.assertIsNone(self.rld.get(h).get("claim_sha"))  # a dry run writes nothing
        done = self.rld.migrate_identity(dry_run=False)
        hyp = self.rld.get(h)
        self.assertEqual(hyp["claim_revision"], 1)
        self.assertTrue(hyp["claim_history"]["revisions"][0]["legacy"])
        again = self.rld.migrate_identity(dry_run=False)
        self.assertEqual(again["claims"], [])
        self.assertEqual(self.rld.get(h)["claim_history"], hyp["claim_history"])
        self.assertEqual(done["legacy_unbound_experiments"], again["legacy_unbound_experiments"])
        e = self.rld.get_eligibility(h)
        self.assertIn("METHOD_IDENTITY_UNBOUND", e["reasons"])  # history stays readable, it cannot carry GO
        self.assertFalse(e["eligible"])


if __name__ == "__main__":
    unittest.main()
