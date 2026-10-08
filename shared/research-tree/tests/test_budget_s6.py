"""S6 (plans/research-tree-implementation-and-real-scenarios.md §10.5): the budget pool follows from what was
approved, a submission key names one complete request, and a pool migration never frees money. REG-S6-01, 02, 03,
07 here; REG-S6-04 is BudgetTest.test_b01_last_quota_admits_one, REG-S6-05 BudgetTest.test_submission_protocol_
b03_b05_b06, REG-S6-06 tests/test_attempt_metrics.py. The numbers are REG fixtures."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))

import test_research_db as trdb  # noqa: E402  (not BudgetTest by name: it would run here again)
from test_research_db import METHOD_CONFIG, ResearchDBError, rdb  # noqa: E402

PermissionDenied = rdb.PermissionDenied


class S6Test(trdb.BudgetTest):
    # the inherited B-tests run in test_research_db; only the S6 cases run here
    test_b02_b10_one_key_one_reservation_per_allocation = None
    test_submission_protocol_b03_b05_b06 = None
    test_b01_last_quota_admits_one = None
    test_b04_b07_release_rules = None
    test_b08_b09_overrun_is_recorded_and_pauses_admission = None
    test_b12_settlement_waits_for_the_job_and_b14_pools = None
    test_caps_are_raised_only_by_the_user = None
    test_reservation_covers_the_registered_request = None
    test_submit_timeout_before_submitted_is_unknown = None
    test_released_reservation_does_not_hide_usage = None
    test_b11_session_restart_keeps_the_attempt = None

    def state(self) -> tuple:
        status = self.rld.budget_status()
        runs = [r for r in self.rld.find("run")]
        return (len(self.rld.find("reservation")), status["committed"], [r.get("submission_key") for r in runs])

    def test_reg_s6_01_a_full_search_pool_is_not_bypassed(self):
        e1, r1 = self.planned(1)
        self.worker.reserve_submission("k1", r1, {"nodes": 1, "walltime_s": 3600})  # 5400 + 3600 = the search limit
        _, r2 = self.planned(1)
        before = self.state()
        with self.assertRaisesRegex(ResearchDBError, "BUDGET_EXCEEDED: .*search budget"):
            self.worker.reserve_submission("k2", r2, {"nodes": 1, "walltime_s": 100})
        for pool in ("confirmation", "repair"):
            with self.assertRaisesRegex(ResearchDBError, f"BUDGET_POOL_MISMATCH: .*not {pool}"):
                self.worker.reserve_submission("k2", r2, {"nodes": 1, "walltime_s": 100, "budget_pool": pool})
        design = self.doc(self.worker, "exp/s6.v1.md", "experiment_design")
        code = self.rld.get(e1)["code_ref"]
        with self.assertRaisesRegex(ResearchDBError, "BUDGET_POOL_MISMATCH: a screen experiment draws on the search"):
            self.worker.create_experiment("method", "m", design, code, 1, 100, hypothesis_id=self.h,
                                          method_config=METHOD_CONFIG, estimated_node_h=0.1, budget_pool="confirmation",
                                          selection_rationale="s6")
        with self.assertRaises(PermissionDenied):
            self.worker.create_experiment("method", "m", design, code, 1, 100, hypothesis_id=self.h,
                                          method_config=METHOD_CONFIG, estimated_node_h=0.1, budget_pool="repair",
                                          selection_rationale="s6")
        self.assertEqual(self.state(), before)  # no reservation, no commitment, no run under a key

    def test_reg_s6_02_mixed_pools_are_split_and_repair_is_the_leaders(self):
        e1, r1 = self.planned(1)
        run = r1[0].rpartition("@")[0]
        design = self.doc(self.worker, "exp/rep.v1.md", "experiment_design")
        code = self.rld.get(e1)["code_ref"]
        with self.assertRaisesRegex(ResearchDBError, "BUDGET_POOL_MISMATCH: the repair pool is assigned on a recorded"):
            self.rld.create_experiment("method", "m", design, code, 1, 100, hypothesis_id=self.h, owner="w1",
                                       method_config=METHOD_CONFIG, estimated_node_h=0.1, budget_pool="repair",
                                       repair_basis=f"{run}@1", selection_rationale="s6")  # nothing failed yet
        self.worker.reserve_submission("k1", r1, {"nodes": 1, "walltime_s": 100})
        gen = self.worker.claim_submission("k1")["claim_generation"]
        self.worker.update_run(run, exec_status="submitted")
        self.worker.attach_job("k1", "job-1", gen)
        self.worker.update_run(run, exec_status="failed")
        repair = self.rld.create_experiment("method", "m", design, code, 1, 100, hypothesis_id=self.h, owner="w1",
                                            method_config={**METHOD_CONFIG, "fixed": True}, estimated_node_h=0.1,
                                            budget_pool="repair", repair_basis=f"{run}@1", selection_rationale="s6")
        self.worker.create_run(repair, self.rld.get(repair)["seeds"][0])
        rep_ref = f"{repair}/s{self.rld.get(repair)['seeds'][0]}@1"
        _, r2 = self.planned(1)
        with self.assertRaisesRegex(ResearchDBError, "BUDGET_POOL_MISMATCH: one allocation draws on one pool"):
            self.worker.reserve_submission("mix", [rep_ref, *r2], {"nodes": 1, "walltime_s": 200})
        self.assertEqual(self.worker.reserve_submission("rep", [rep_ref], {"nodes": 1, "walltime_s": 100})["budget_pool"],
                         "repair")  # the worker runs it under the Leader's assignment

    def test_reg_s6_03_one_key_one_complete_request(self):
        _, refs = self.planned(1)
        first = self.worker.reserve_submission("k1", refs, {"nodes": 1, "walltime_s": 120, "platform_profile": "cpu"})
        before = self.state()
        for request, field in (({"nodes": 2, "walltime_s": 60, "platform_profile": "cpu"}, "nodes"),  # same 120 node-s
                               ({"nodes": 1, "walltime_s": 120, "platform_profile": "gpu"}, "platform_profile"),
                               ({"nodes": 1, "walltime_s": 120, "platform_profile": "cpu", "budget_pool": "repair"}, "pool")):
            with self.subTest(field), self.assertRaisesRegex(ResearchDBError, f"SUBMISSION_AMBIGUOUS: .*{field}"):
                self.worker.reserve_submission("k1", refs, request)
        self.assertEqual(self.state(), before)
        again = self.worker.reserve_submission("k1", refs, {"nodes": 1, "walltime_s": 120, "platform_profile": "cpu"})
        self.assertEqual((again["reservation_id"], again["created"]), (first["reservation_id"], False))
        # a reservation from before request shapes were recorded is never matched by node-seconds alone
        self.raw(first["reservation_id"], request_nodes=None, request_walltime_s=None)
        with self.assertRaisesRegex(ResearchDBError, "SUBMISSION_AMBIGUOUS: .*not reconstructed"):
            self.worker.reserve_submission("k1", refs, {"nodes": 1, "walltime_s": 120, "platform_profile": "cpu"})

    def test_reg_s6_07_migration_moves_the_view_and_frees_nothing(self):
        _, r1 = self.planned(1)
        held = self.worker.reserve_submission("k1", r1, {"nodes": 1, "walltime_s": 3000})
        run = r1[0].rpartition("@")[0]
        self.worker.claim_submission("k1")
        self.worker.update_run(run, exec_status="submitted")
        self.worker.update_run(run, exec_status="unknown")  # in flight, state unknown
        self.raw(held["reservation_id"], budget_pool="confirmation")  # booked in the wrong pool by an older plugin
        before = self.rld.budget_status()["committed"]
        self.assertEqual(before["confirmation"], 3000)
        dry = self.rld.migrate_budget(dry_run=True)
        self.assertEqual(dry["corrected"], [held["reservation_id"]])
        report = self.rld.migrate_budget(dry_run=False)
        after = self.rld.budget_status()["committed"]
        self.assertEqual((after["total"], after["search"], after["confirmation"]), (before["total"], 8400, 0))
        res = self.rld.get(held["reservation_id"])
        self.assertEqual((res["budget_pool"], res["pool_correction"]["to"], res["accounting_status"]),
                         ("confirmation", "search", "held_unknown"))  # the original stays; nothing is released
        self.assertEqual(report["over_limit"], {})
        self.assertEqual(self.rld.migrate_budget(dry_run=False)["corrected"], [])  # idempotent
        self.assertEqual(self.rld.get(held["reservation_id"])["pool_correction"], res["pool_correction"])  # unchanged
        # a correction that overfills the search pool is reported, and new search admission is refused
        self.rld.update_project(search_limit=8000)
        self.assertEqual(self.rld.migrate_budget(dry_run=True)["over_limit"]["search"], {"committed": 8400, "limit": 8000})
        _, r2 = self.planned(1)
        with self.assertRaisesRegex(ResearchDBError, "BUDGET_EXCEEDED: .*search budget"):
            self.worker.reserve_submission("k2", r2, {"nodes": 1, "walltime_s": 100})


if __name__ == "__main__":
    unittest.main()
