"""Bounded fast research: deterministic fixtures, never a scientific efficacy benchmark."""
from __future__ import annotations

import json
import unittest

from test_identity import IdentityFixture, ResearchDB, ResearchDBError
from test_research_db import BASE, PROTOCOL, SECONDARY, Database, create_db


class FastFixture(IdentityFixture):
    def setUp(self):
        super().setUp()
        self.anchor = "底线问题: x；必须解决的瓶颈: x；非目标: x；约束: x；成功条件: x"
        goal = self.doc(self.rld, "project/goal-fast.v1.md", "goal", body="## 问题锚点\n" + self.anchor)
        instruction = self.doc(self.rld, "instructions/fast.v1.md", "user_instruction")
        self.rld.update_project(goal_doc_id=goal, workflow_mode="fast_screening", screen_seeds=1,
                                code_review_required=True, user_instruction_doc_id=instruction)

    def body(self, ceiling=None):
        ceiling = ceiling or {"nodes": 2, "walltime_s": 3600, "n_seeds": 3}
        return ("## 问题锚点\n" + self.anchor + "\n\n## 可证伪预测\n配对指标改善\n"
                "## 干预\n改变更新规则\n## 匹配对照\n同一训练量的基线\n"
                "## 资源上限\n```json\n" + json.dumps(ceiling) + "\n```\n"
                "## 停止与继续条件\n正向补 seed；无效修复；负向暂停\n")

    def hypothesis(self, parent=None, **kw):
        self.n += 1
        doc = self.doc(self.rld, f"h/fast{self.n}.v1.md", "hypothesis", body=self.body())
        return self.rld.create_hypothesis("h", "s", doc, [], parent_id=parent, **kw)

    def exp(self, h, code, config, kind="method", walltime=60, body=None, **kw):
        self.n += 1
        design = self.doc(self.worker, f"exp/fast{self.n}.v1.md", "experiment_design", body=body or self.body())
        return self.worker.create_experiment(kind, "m", design, code, 1, walltime, hypothesis_id=h,
            n_seeds=kw.pop("n_seeds", 1), method_config=config, estimated_node_h=0.1,
            selection_rationale="bounded test", **kw)

    def finish_seed(self, exp, seed):
        run = f"{exp}/s{seed}"
        self.worker.create_run(exp, seed)
        self.worker.update_run(run, exec_status="submitted")
        self.worker.update_run(run, exec_status="succeeded", valid=True, metric_value=BASE["acc"],
            secondary={k: BASE[k] for k in SECONDARY}, nodes_used=1, walltime_used_s=10, output_path="outputs/run")

    def partial_doc(self, exp):
        preview = self.rld.preview_evaluation(exp)
        self.n += 1
        path = f"outputs/partial-{self.n}.json"
        (self.root / "outputs").mkdir(exist_ok=True)
        value = preview["metrics"]["acc"]["mean"]
        (self.root / path).write_text(json.dumps({"acc": value}))
        body = "```evidence\n" + json.dumps([{"id": "mean:acc", "value": str(value), "source": path}]) + "\n```\n"
        return self.doc(self.worker, f"results/partial-{self.n}.v1.md", "experiment_result", body=body)


class CheapScreeningTest(FastFixture):
    def test_cheap_search_runs_without_review_but_does_not_confirm_go(self):
        h = self.node()
        exp = self.exp(h, self.harness, {"lr": 0.2})
        self.effects[exp] = (self.sota, (0.3, 0.0, 0.0))
        self.finish_runs(self.worker, exp)
        result = self.worker.evaluate_experiment(exp, self.result_doc(exp=exp))
        self.assertEqual(result["outcome"], "positive_signal")
        self.assertEqual(self.rld.reviews(kind="code_review"), [])
        import build_site
        shown = next(n for n in build_site.summary_or_empty(self.db)["nodes"] if n["id"] == h)
        self.assertEqual(shown["outcome"], "positive_signal")
        self.assertIsNone(shown["go"])
        full = build_site.collect(self.db)
        displayed = next(n for n in full["nodes"] if n["id"] == h)
        self.assertEqual(displayed["latest"], exp)
        self.assertEqual(displayed["outcome"], "positive_signal")
        self.assertFalse(displayed["go"])
        state = self.rld.get_eligibility(h)
        self.assertFalse(state["eligible"])
        self.assertIn("SEARCH_REPLICATION_REQUIRED", state["reasons"])
        with self.assertRaisesRegex(ResearchDBError, "not ready to freeze"):
            self.rld.freeze_candidate(h, result["evaluation_id"])
        self.worker.extend_seeds(exp, 3)
        self.assertEqual(len(self.rld.get(exp)["seeds"]), 3)

    def test_five_fields_and_declared_resource_ceiling_are_enforced(self):
        doc = self.doc(self.rld, "h/incomplete.v1.md", "hypothesis", body=self.body().replace("## 干预\n改变更新规则\n", ""))
        with self.assertRaisesRegex(ResearchDBError, "DESIGN_SECTION_MISSING"):
            self.rld.create_hypothesis("bad", "s", doc, [])
        doc = self.doc(self.rld, "h/small.v1.md", "hypothesis", body=self.body({"nodes": 1, "walltime_s": 30, "n_seeds": 1}))
        h = self.rld.create_hypothesis("small", "s", doc, [])
        self.start(h)
        with self.assertRaisesRegex(ResearchDBError, "BUDGET_EXCEEDED"):
            self.exp(h, self.commit(), {"lr": 0.2}, walltime=31)

    def test_sanity_and_known_validity_blockers_still_apply(self):
        h = self.node()
        self.rld.update_project(sanity_required=True)
        code = self.commit()
        exp = self.exp(h, code, {"lr": 0.2})
        with self.assertRaisesRegex(ResearchDBError, "SANITY_REQUIRED"):
            self.submit(exp)
        sanity = self.exp(h, code, {"lr": 0.2}, kind="sanity", sanity_overrides={"epochs": 1})
        self.finish_runs(self.worker, sanity)
        payload = {"method_implemented": True, "issues": [{"severity": "CRITICAL", "category": "leakage",
                   "file": "method.txt", "line": 1, "description": "verified leak", "verified": True}]}
        self.register(exp, "code_review", "blocking", self.reviewer.review_basis(exp, "code_review"), payload=payload)
        with self.assertRaisesRegex(ResearchDBError, "CODE_REVIEW_REQUIRED"):
            self.submit(exp)
        self.rld.update_hypothesis(h, statement="clarified claim, same method")
        with self.assertRaisesRegex(ResearchDBError, "CODE_REVIEW_REQUIRED"):
            self.submit(exp)  # Claim wording does not repair the known leakage.
        other_h = self.node()
        other = self.exp(other_h, code, {"lr": 0.2})
        other_sanity = self.exp(other_h, code, {"lr": 0.2}, kind="sanity", sanity_overrides={"epochs": 1})
        self.finish_runs(self.worker, other_sanity)
        with self.assertRaisesRegex(ResearchDBError, "CODE_REVIEW_REQUIRED"):
            self.submit(other)  # A new hypothesis ID does not repair the same bad method either.

    def test_actual_allocation_cannot_expand_the_declared_cheap_scope(self):
        h = self.node()
        first = self.exp(h, self.commit(), {"lr": 0.2})
        second = self.exp(h, self.commit(), {"lr": 0.3})
        for exp in (first, second):
            self.worker.create_run(exp, 42)
        with self.assertRaisesRegex(ResearchDBError, "BUDGET_EXCEEDED"):
            self.worker.reserve_submission("oversized", [f"{first}/s42@1"], {"nodes": 8, "walltime_s": 3600})
        self.assertEqual(self.rld.find("reservation"), [])
        refs = [f"{first}/s42@1", f"{second}/s42@1"]
        reservation = self.worker.reserve_submission("grouped", refs, {"nodes": 2, "walltime_s": 60})
        self.assertEqual(reservation["reserved_units"], 120)
        self.worker.claim_submission("grouped")

    def test_reduced_scope_is_rechecked_at_submission_and_claim(self):
        h = self.node()
        exp = self.exp(h, self.commit(), {"lr": 0.2})
        self.worker.create_run(exp, 42)
        self.worker.reserve_submission("planned", [f"{exp}/s42@1"], {"nodes": 1, "walltime_s": 60})
        doc = self.doc(self.rld, "h/reduced.v1.md", "hypothesis", body=self.body({"nodes": 1, "walltime_s": 30, "n_seeds": 3}))
        self.rld.update_hypothesis(h, doc_id=doc)
        with self.assertRaisesRegex(ResearchDBError, "BUDGET_EXCEEDED"):
            self.worker.claim_submission("planned")
        with self.assertRaisesRegex(ResearchDBError, "BUDGET_EXCEEDED"):
            self.submit(exp)

    def test_engineering_failure_is_invalid_and_duplicate_method_is_reused(self):
        h = self.node()
        code = self.commit()
        exp = self.exp(h, code, {"lr": 0.2})
        same = self.exp(h, code, {"lr": 0.2, "out": "another-output"})
        self.assertEqual(same, exp)
        self.worker.create_run(exp, 42)
        self.worker.update_run(f"{exp}/s42", exec_status="submitted")
        self.worker.update_run(f"{exp}/s42", exec_status="failed", valid=False, invalid_reason="broken runner")
        self.assertEqual(self.rld.get_eligibility(h)["outcome"], "invalid")
        with self.assertRaisesRegex(ResearchDBError, "valid run for every seed"):
            self.worker.evaluate_experiment(exp, self.result_doc(exp=exp))


class IndependentLineageTest(FastFixture):
    def test_different_code_origin_cannot_launder_an_identical_comparator_method(self):
        parent = self.node()
        code = self.commit()
        ref = self.exp(parent, code, {"lr": 0.2})
        self.finish_runs(self.worker, ref)
        self.worker.evaluate_experiment(ref, self.result_doc(exp=ref))
        child = self.hypothesis(parent, code_parent_id="P-test", comparator_experiment_id=ref)
        self.start(child)
        noop = self.exp(child, code, {"lr": 0.2})
        self.finish_runs(self.worker, noop)
        with self.assertRaisesRegex(ResearchDBError, "not a new intervention"):
            self.worker.evaluate_experiment(noop, self.result_doc(exp=noop))

    def test_unproven_idea_has_parallel_variants_with_explicit_code_and_control(self):
        h = self.hypothesis()
        for _ in range(3):
            child = self.hypothesis(h, code_parent_id="P-test", comparator_experiment_id=self.sota,
                                    relations=[{"kind": "variant_of", "target": h}])
            self.start(child)
            exp = self.exp(child, self.commit(), {"lr": 0.2})
            record = self.rld.get(child)
            self.assertEqual((record["parent_id"], record["code_parent_id"], record["comparator_experiment_id"]),
                             (h, "P-test", self.sota))
            self.assertIsNone(self.rld.get(exp).get("parent_experiment_id"))
            self.finish_runs(self.worker, exp)
            self.worker.evaluate_experiment(exp, self.result_doc(exp=exp))
        with self.assertRaisesRegex(ResearchDBError, "cycle"):
            self.rld.link("rel_related", h, child, kind="variant_of")
        with self.assertRaisesRegex(ResearchDBError, "itself"):
            self.rld.link("rel_related", h, h, kind="competes")
        self.assertEqual(self.rld.get(h)["status"], "pending")
        self.assertEqual(self.rld.get(h)["disposition"], "active")
        snapshot = self.rld.export_snapshot()
        self.assertTrue(any(e["kind"] == "variant_of" for e in snapshot["edges"]["rel_related"]))

    def test_missing_comparator_and_invalid_relationship_are_refused(self):
        with self.assertRaisesRegex(ResearchDBError, "does not exist"):
            self.hypothesis(comparator_experiment_id="E-missing")
        with self.assertRaisesRegex(ResearchDBError, "relation"):
            self.hypothesis(relations=[{"kind": "unknown", "target": "H-missing"}])
        h = self.hypothesis()
        with self.assertRaisesRegex(ResearchDBError, "no evaluation"):
            self.hypothesis(relations=[{"kind": "repairs", "target": h}])


class IncrementalBaselineTest(FastFixture):
    def new_baseline(self, count=3):
        self.n += 1
        design = self.doc(self.worker, f"exp/partial-base{self.n}.v1.md", "experiment_design")
        return self.worker.create_experiment("baseline", "incremental", design, self.harness, 1, 60,
            n_seeds=count, method_config={"lr": 0.05, "baseline": self.n}, estimated_node_h=0.1)

    def test_first_pair_does_not_wait_for_remaining_baseline_and_stays_current(self):
        baseline = self.new_baseline()
        self.finish_seed(baseline, 42)
        base_ev = self.worker.evaluate_experiment(baseline, self.partial_doc(baseline))
        self.rld.update_project(sota_experiment_id=baseline)
        self.assertEqual(self.rld.get(base_ev["evaluation_id"])["metrics"]["acc"]["n"], 1)
        h = self.node()
        exp = self.exp(h, self.harness, {"lr": 0.2})
        self.finish_runs(self.worker, exp)
        ev = self.worker.evaluate_experiment(exp, self.result_doc(exp=exp))
        self.assertEqual(ev["comparisons"]["sota"]["n_paired"], 1)
        self.assertFalse(self.rld.get_eligibility(h)["eligible"])
        for seed in (43, 44):
            self.finish_seed(baseline, seed)
        self.worker.evaluate_experiment(baseline, self.result_doc(exp=baseline))
        with self.rld.reader() as tx:
            self.assertEqual(self.rld._stale_reasons(tx, self.rld._project(tx), tx.get(ev["evaluation_id"])), [])
        self.rld.retract_run(f"{baseline}/s42", "bad source", self.decision_doc())
        self.assertEqual(self.rld.get_eligibility(h)["evidence_state"], "stale")

    def test_missing_baseline_seed_cannot_authorize_submission(self):
        baseline = self.new_baseline()
        with self.assertRaisesRegex(ResearchDBError, "no valid matching"):
            self.worker.evaluate_experiment(baseline, self.result_doc(exp=baseline))
        self.finish_seed(baseline, 42)
        self.worker.evaluate_experiment(baseline, self.partial_doc(baseline))
        self.rld.update_project(sota_experiment_id=baseline)
        h = self.node()
        exp = self.exp(h, self.commit(), {"lr": 0.2})
        self.rld.extend_seeds(exp, 2)
        self.worker.create_run(exp, 43)
        with self.assertRaisesRegex(ResearchDBError, "PAIRING_MISMATCH"):
            self.worker.reserve_submission("no-baseline-43", [f"{exp}/s43@1"], {"nodes": 1, "walltime_s": 60})
        self.assertEqual(self.rld.find("reservation"), [])
        with self.assertRaisesRegex(ResearchDBError, "PAIRING_MISMATCH"):
            self.worker.update_run(f"{exp}/s43", exec_status="submitted")
        self.finish_seed(baseline, 43)
        self.worker.reserve_submission("baseline-43", [f"{exp}/s43@1"], {"nodes": 1, "walltime_s": 60})
        self.rld.retract_run(f"{baseline}/s43", "bad source", self.decision_doc())
        with self.assertRaisesRegex(ResearchDBError, "PAIRING_MISMATCH"):
            self.worker.claim_submission("baseline-43")


class FastConfirmationTest(FastFixture):
    protocol_content = {**PROTOCOL, "profile": "stage1_confirmed", "confirmation_seeds": [1042, 1043, 1044],
                        "max_confirmation_candidates": 2,
                        "confirmation_materials": [{"name": "c1", "seeds": [1042, 1043, 1044]}]}

    def test_full_search_replication_still_needs_frozen_independent_confirmation(self):
        h = self.node()
        exp = self.exp(h, self.harness, {"lr": 0.2})
        self.effects[exp] = (self.sota, (0.3, 0.1, 0.1))
        self.finish_runs(self.worker, exp)
        self.worker.evaluate_experiment(exp, self.result_doc(exp=exp))
        self.worker.extend_seeds(exp, 3)
        self.finish_runs(self.worker, exp)
        result = self.worker.evaluate_experiment(exp, self.result_doc(exp=exp))
        self.rld.decide(h, {"experiment_status": "beats_sota"}, "search gate passed", based_on=[exp])
        self.recheck_pass(h, exp)
        state = self.rld.get_eligibility(h)
        self.assertEqual(state["stage"], "candidate_ready")
        self.assertFalse(state["eligible"])
        self.assertEqual(state["reasons"], ["CONFIRMATION_REQUIRED"])
        candidate = self.rld.freeze_candidate(h, result["evaluation_id"])
        self.rld.create_confirmation_batch([candidate], "c1")
        self.assertFalse((self.rld.get("P-test").get("material_usage") or {}).get("events"))
        self.assertFalse(self.rld.get_eligibility(h)["eligible"])


class MinimumControlTest(FastFixture):
    def target(self):
        h = self.node()
        code = self.commit()
        controls = {"controls": [{"id": "without-b", "code_ref": code, "method_config": {"a": True, "b": False},
                                  "nodes": 1, "walltime_s": 60, "n_seeds": 1}]}
        body = self.body() + "\n## 预声明最小对照\n```json\n" + json.dumps(controls) + "\n```\n"
        target = self.exp(h, code, {"a": True, "b": True}, body=body)
        return h, code, target

    def test_exact_predeclared_control_needs_no_ablation_review(self):
        self.rld.update_project(design_required=True)
        h, code, target = self.target()
        approval = self.rld.approve_minimum_controls(target, self.decision_doc())
        self.assertEqual(approval["controls"][0]["id"], "without-b")
        exp = self.exp(h, code, {"a": True, "b": False}, kind="ablation",
                       ablation_of=target, predeclared_control_id="without-b")
        self.submit(exp)
        self.assertIsNone(self.rld.get(exp).get("source_review_id"))
        with self.assertRaisesRegex(ResearchDBError, "CONTROL_NOT_APPROVED"):
            self.rld.extend_seeds(exp, 2)
        with self.assertRaisesRegex(ResearchDBError, "CONTROL_NOT_APPROVED"):
            self.exp(h, code, {"a": False, "b": False}, kind="ablation", ablation_of=target,
                     predeclared_control_id="without-b")
        with self.assertRaisesRegex(ResearchDBError, "CONTROL_NOT_APPROVED"):
            self.exp(h, code, {"a": True, "b": False}, kind="ablation", ablation_of=target,
                     predeclared_control_id="without-b", walltime=61)

    def test_late_unapproved_and_changed_claim_controls_are_blocked(self):
        self.rld.update_project(design_required=True)
        h, code, target = self.target()
        with self.assertRaisesRegex(ResearchDBError, "CONTROL_NOT_APPROVED"):
            self.exp(h, code, {"a": True, "b": False}, kind="ablation", ablation_of=target,
                     predeclared_control_id="without-b")
        self.rld.approve_minimum_controls(target, self.decision_doc())
        self.rld.update_hypothesis(h, statement="a changed claim")
        with self.assertRaisesRegex(ResearchDBError, "CONTROL_NOT_APPROVED"):
            self.exp(h, code, {"a": True, "b": False}, kind="ablation", ablation_of=target,
                     predeclared_control_id="without-b")
        _, _, other = self.target()
        self.submit(other)
        with self.assertRaisesRegex(ResearchDBError, "before.*first submission"):
            self.rld.approve_minimum_controls(other, self.decision_doc())


class ReviewDisputesTest(FastFixture):
    def blocked(self, verified=False):
        self.rld.update_project(code_review_required=True)
        h = self.node()
        code = self.commit()
        exp = self.exp(h, code, {"lr": 0.2})
        payload = {"method_implemented": True, "issues": [{"severity": "MAJOR", "file": "method.txt", "line": 1,
            "category": "leakage" if verified else "input_unreadable", "description": "bad split" if verified else "wrong-case path",
            "verified": verified}]}
        review = self.register(exp, "code_review", "blocking", self.reviewer.review_basis(exp, "code_review"), payload=payload)
        evidence = self.doc(self.worker, "exp/dispute-evidence.v1.md", "other", body="readable evidence")
        dispute = self.worker.dispute_code_review(exp, review, "input_unreadable", evidence, "path case is wrong")
        return h, code, exp, review, evidence, dispute

    def recheck_dispute(self, exp, review, evidence, dispute, resolution="overturned"):
        payload = {"method_implemented": True, "issues": [], "dispute_resolution": {
            "review_id": review, "dispute_id": dispute["id"], "evidence_doc_id": evidence,
            "resolution": resolution, "evidence_paths": ["docs/exp/dispute-evidence.v1.md"]}}
        return self.register(exp, "code_review", "clear", self.reviewer.review_basis(exp, "code_review"), payload=payload)

    def test_fresh_reviewer_cannot_erase_blocker_but_evidence_adjudication_can(self):
        _, _, exp, review, evidence, dispute = self.blocked()
        clear = self.register(exp, "code_review", "clear", self.reviewer.review_basis(exp, "code_review"))
        with self.assertRaisesRegex(ResearchDBError, "CODE_REVIEW_REQUIRED"):
            self.submit(exp)
        with self.assertRaisesRegex(ResearchDBError, "REVIEW_DISPUTE_MISMATCH"):
            self.rld.adjudicate_code_review(review, dispute["id"], clear, "overturned", self.decision_doc(), "clear now")
        recheck = self.recheck_dispute(exp, review, evidence, dispute)
        result = self.rld.adjudicate_code_review(review, dispute["id"], recheck, "overturned", self.decision_doc(), "verified exact path and search protocol")
        self.assertEqual(result["adjudication"]["resolution"], "overturned")
        self.submit(exp)
        original = self.rld.get(review)
        self.assertEqual(original["review_result"], "blocking")
        self.assertEqual(len(original["review_disputes"]["items"]), 1)

    def test_verified_defect_follows_config_and_unchanged_source_until_bound_fix(self):
        h, code, original, review, evidence, _ = self.blocked(verified=True)
        changed = self.exp(h, code, {"lr": 0.3})
        with self.assertRaisesRegex(ResearchDBError, "CODE_REVIEW_REQUIRED"):
            self.submit(changed)
        newer_code = self.commit({"unrelated.txt": "unrelated edit"})
        changed_code = self.exp(h, newer_code, {"lr": 0.4})
        with self.assertRaisesRegex(ResearchDBError, "CODE_REVIEW_REQUIRED"):
            self.submit(changed_code)
        source = (self.repo / "method.txt").read_text()
        comment_code = self.commit({"method.txt": source + "# unrelated comment\n"})
        same_node = self.exp(h, comment_code, {"lr": 0.5})
        renamed_node = self.node()
        renamed = self.exp(renamed_node, comment_code, {"lr": 0.6})
        for exp in (same_node, renamed):
            with self.assertRaisesRegex(ResearchDBError, "CODE_REVIEW_REQUIRED"):
                self.submit(exp)
        dispute = self.worker.dispute_code_review(changed, review, "validity_defect", evidence, "configuration repair evidence")
        generic = self.register(changed, "code_review", "clear", self.reviewer.review_basis(changed, "code_review"))
        with self.assertRaisesRegex(ResearchDBError, "REVIEW_DISPUTE_MISMATCH"):
            self.rld.adjudicate_code_review(review, dispute["id"], generic, "fixed", self.decision_doc(), "generic clear")
        recheck = self.recheck_dispute(changed, review, evidence, dispute, "fixed")
        self.rld.adjudicate_code_review(review, dispute["id"], recheck, "fixed", self.decision_doc(), "independently checked configuration repair")
        self.submit(changed)
        for exp in (original, changed_code, same_node, renamed):
            with self.assertRaisesRegex(ResearchDBError, "CODE_REVIEW_REQUIRED"):
                self.submit(exp)
        self.assertEqual(self.rld.get(review)["review_result"], "blocking")

    def test_same_identity_cannot_claim_a_verified_defect_was_fixed(self):
        _, _, exp, review, evidence, dispute = self.blocked(verified=True)
        recheck = self.recheck_dispute(exp, review, evidence, dispute, "fixed")
        with self.assertRaisesRegex(ResearchDBError, "genuinely new method identity"):
            self.rld.adjudicate_code_review(review, dispute["id"], recheck, "fixed", self.decision_doc(), "unchanged")

    def test_fixed_resolution_expires_with_claim_or_any_supporting_evidence(self):
        h, code, _, review, evidence, _ = self.blocked(verified=True)
        repaired = self.exp(h, code, {"lr": 0.3})
        dispute = self.worker.dispute_code_review(repaired, review, "validity_defect", evidence, "configuration repair evidence")
        recheck = self.recheck_dispute(repaired, review, evidence, dispute, "fixed")
        decision = self.decision_doc()
        self.rld.adjudicate_code_review(review, dispute["id"], recheck, "fixed", decision, "checked repair")

        def blockers():
            with self.rld.reader() as tx:
                return self.rld._blocking_code_reviews(tx, tx.get(repaired), screening=True)

        self.assertEqual(blockers(), [])
        for doc_id in (evidence, recheck, decision):
            path = self.root / "docs" / self.rld.get(doc_id)["path"]
            text = path.read_text()
            path.write_text(text + "\nchanged evidence\n")
            self.assertTrue(blockers(), doc_id)
            path.write_text(text)
            self.assertEqual(blockers(), [])
        self.rld.update_hypothesis(h, statement="new claim")
        self.assertTrue(blockers())

    def test_verified_leakage_is_fixed_not_overturned(self):
        _, _, exp, review, evidence, dispute = self.blocked(verified=True)
        recheck = self.recheck_dispute(exp, review, evidence, dispute)
        with self.assertRaisesRegex(ResearchDBError, "verified leakage or metric defects"):
            self.rld.adjudicate_code_review(review, dispute["id"], recheck, "overturned", self.decision_doc(), "ignore")
        with self.assertRaisesRegex(ResearchDBError, "CODE_REVIEW_REQUIRED"):
            self.submit(exp)

    def test_claim_revision_and_missing_evidence_prevent_stale_resolution(self):
        h, _, exp, review, evidence, dispute = self.blocked()
        recheck = self.recheck_dispute(exp, review, evidence, dispute)
        self.rld.update_hypothesis(h, statement="changed claim")
        self.rld.update_hypothesis(h, statement="s")
        with self.assertRaisesRegex(ResearchDBError, "REVIEW_DISPUTE_MISMATCH"):
            self.rld.adjudicate_code_review(review, dispute["id"], recheck, "overturned", self.decision_doc(), "old proof")
        self.assertIsNone(self.rld.get(review)["review_disputes"]["items"][0]["adjudication"])


class RoleBoundaryTest(IdentityFixture):
    def test_leader_records_read_only_advisor_deliveries_with_exact_task_provenance(self):
        request = self.doc(self.rld, "tasks/advice.v1.md", "task_request")
        for role in ("explorer", "analyst"):
            task = self.rld.create_task("analysis", role, request, target_id="P-test", assignee_id="main")
            actor = ResearchDB(self.db, f"{role}/main")
            with self.assertRaisesRegex(ResearchDBError, "advisory"):
                actor.update_task(task, status="in_progress")
            self.rld.update_task(task, status="in_progress")
            unbound = self.doc(self.rld, f"tasks/{role}-unbound.v1.md", "task_delivery")
            with self.assertRaisesRegex(ResearchDBError, "exact task"):
                self.rld.update_task(task, status="delivered", delivery_doc_id=unbound)
            delivery = self.doc(self.rld, f"tasks/{role}-delivery.v1.md", "task_delivery", about=(task,))
            self.rld.update_task(task, status="delivered", delivery_doc_id=delivery)
            self.rld.update_task(task, status="accepted", evidence_ids=[delivery])
            recorded = self.rld.get(task)
            self.assertEqual((recorded["assignee_role"], recorded["assignee_id"], recorded["accepted_by"]),
                             (role, "main", "rld/main"))
            self.assertEqual(self.rld.get(delivery)["author_role"], "rld")
        worker_task = self.rld.create_task("harness", "worker", request, target_id="P-test", assignee_id="w1")
        with self.assertRaisesRegex(ResearchDBError, "only the assignee"):
            self.rld.update_task(worker_task, status="in_progress")

    def test_advisors_are_read_only_even_with_leader_or_worker_id(self):
        for role in ("explorer", "analyst"):
            actor = ResearchDB(self.db, f"{role}/main")
            self.assertEqual(actor.get("P-test")["id"], "P-test")
            with self.assertRaisesRegex(ResearchDBError, "requires role|advisory"):
                actor.update_project(title="changed")
            with self.assertRaisesRegex(ResearchDBError, "advisory|requires role"):
                actor.migrate_states(dry_run=False)

    def test_architect_root_alias_and_node_scope(self):
        self.rld.assign_worker("P-test", "w1")
        architect = ResearchDB(self.db, "architect/w1")
        request = self.doc(self.rld, "tasks/root-fast.v1.md", "task_request")
        task = self.rld.create_task("harness", "worker", request, target_id="P-test", assignee_id="w1")
        architect.update_task(task, status="in_progress")
        self.assertEqual(self.rld.get(task)["status"], "in_progress")
        self.assertIn(request, architect.add_resume_docs("P-test", [request]))
        h = self.node()
        with self.assertRaisesRegex(ResearchDBError, "only rld"):
            architect.add_resume_docs(h, [request])
        exp = self.exp(h, self.commit(), {"lr": 0.2})
        with self.assertRaisesRegex(ResearchDBError, "architect"):
            architect.create_run(exp, 42)
        with self.assertRaisesRegex(ResearchDBError, "requires role"):
            architect.decide_disposition(h, "retired", "no", [])
        with self.assertRaisesRegex(ResearchDBError, "architect tasks"):
            self.rld.create_task("experiment", "architect", request, target_id=h, assignee_id="w1")


class FastSchemaCompatibilityTest(IdentityFixture):
    def test_schema21_upgrade_preserves_evidence_and_does_not_opt_into_fast_mode(self):
        before = self.rld.get(self.sota)
        self.raw("P-test", workflow_mode=None, discovery_mode=None)
        with Database(self.db) as db, db.write() as txn:
            txn.set_property(txn.get_nodes_by_label("Meta")[0], "schema_version", 21)
            txn.commit()
        self.assertEqual(self.rld.get(self.sota), before)
        with self.assertRaisesRegex(ResearchDBError, "schema_version 21"):
            self.rld.update_project(title="new title")
        self.assertEqual(create_db.upgrade_db(self.db), 21)
        self.assertEqual(create_db.upgrade_db(self.db), 22)
        self.assertEqual(self.rld.get(self.sota), before)
        self.assertNotIn("workflow_mode", self.rld.get("P-test"))
        self.assertNotIn("discovery_mode", self.rld.get("P-test"))
        self.rld.update_project(code_review_required=True)
        h = self.node()
        exp = self.exp(h, self.commit(), {"lr": 0.2})
        with self.assertRaisesRegex(ResearchDBError, "CODE_REVIEW_REQUIRED"):
            self.submit(exp)  # No silent fast-mode bypass on an upgraded project.
        doc = self.doc(self.rld, "h/legacy-child.v1.md", "hypothesis")
        with self.assertRaisesRegex(ResearchDBError, "expandable"):
            self.rld.create_hypothesis("child", "s", doc, self.literature, parent_id=h, code_parent_id="P-test")


class StrictIncrementalIntegrationTest(IdentityFixture):
    def test_verified_literature_map_and_candidate_receipts_admit_independently(self):
        import discovery
        instruction = self.doc(self.rld, "instructions/incremental.v1.md", "user_instruction")
        self.rld.update_project(discovery_mode="incremental", require_precheck=True, literature_verification=True,
                                user_instruction_doc_id=instruction)
        discovery.start(self.root, "incremental", "fixture-only")
        candidate = discovery.merge([], [{"title": "A", "literature": self.literature}])[0]
        discovery.write_candidates(self.root, [candidate, {"id": "CAND-0002", "title": "pending"}])
        with self.rld._writer() as tx:  # Deterministic verification fixture; no external literature call.
            for doc in self.literature:
                tx.set(doc, {"literature_check": "verified"})
        for kind, result in (("novelty_precheck", "PROCEED"), ("critical_review", "proceed")):
            self.register(candidate["id"], kind, result, self.reviewer.review_basis(candidate["id"], kind))
        doc = self.doc(self.rld, "h/incremental-strict.v1.md", "hypothesis")
        h = self.rld.create_hypothesis("A", "s", doc, self.literature, candidate_id=candidate["id"])
        self.assertEqual(self.rld.get(h)["candidate_id"], candidate["id"])


if __name__ == "__main__":
    unittest.main()
