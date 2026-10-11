"""R08 deterministic incremental discovery checks; no reviewer calls or research jobs."""
from __future__ import annotations

import argparse
import copy
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

TOOLS = Path(__file__).resolve().parents[1] / "tools"
sys.path.insert(0, str(TOOLS))

import discovery
import project_config
import research_tree
from test_research_db import ANCHOR, Fixture, ResearchDB, ResearchDBError


def screening_candidate(title="A"):
    return {"title": title, "summary": "Update policy variant", "prediction": "Accuracy increases at equal compute",
            "intervention": "Use per-block update rates", "comparator": "Unchanged baseline at matching seed/data",
            "resource_ceiling": {"nodes": 1, "walltime_s": 60},
            "stop_conditions": ["Stop on invalid metrics", "Replicate an applicable positive signal"]}


class IncrementalReadinessTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        discovery.start(self.root, "claude-opus-5-5")

    def candidates(self, *items):
        candidates = discovery.merge([], list(items), discovery.read_candidates(self.root))
        discovery.write_candidates(self.root, candidates)
        return candidates

    def check(self, candidate_id="CAND-0001", **kwargs):
        return discovery.evaluate_candidate(self.root, candidate_id, max_nodes=2, max_walltime_s=120, screen_node_h=0.05, **kwargs)

    def test_ready_candidate_does_not_wait_for_incomplete_neighbor_or_batch_stages(self):
        candidates = self.candidates(screening_candidate(), {"title": "B"})
        before = {p: p.read_bytes() for p in self.root.rglob("*") if p.is_file()}
        self.assertEqual(self.check()["verdict"], "PASS")
        self.assertEqual(self.check(candidates[1]["id"])["verdict"], "BLOCKED")
        self.assertEqual(before, {p: p.read_bytes() for p in self.root.rglob("*") if p.is_file()})
        self.assertNotIn("gate", discovery.load(self.root))

    def test_each_screening_description_is_required(self):
        for field in ("prediction", "intervention", "comparator", "stop_conditions"):
            for bad in (None, "", "   ", [], {}, False, 7):
                with self.subTest(field=field, bad=bad):
                    item = screening_candidate()
                    item[field] = bad
                    self.candidates(item)
                    self.assertIn(field, " ".join(self.check()["reasons"]))

    def test_ceiling_has_positive_integer_shape_and_respects_all_project_limits(self):
        for ceiling in (None, {}, {"nodes": True, "walltime_s": 60}, {"nodes": 1, "walltime_s": False},
                        {"nodes": 0, "walltime_s": 60}, {"nodes": 1, "walltime_s": -1},
                        {"nodes": "1", "walltime_s": 60}, {"nodes": 1, "walltime_s": 0.5},
                        {"nodes": 3, "walltime_s": 60}, {"nodes": 1, "walltime_s": 121},
                        {"nodes": 2, "walltime_s": 100}):
            with self.subTest(ceiling=ceiling):
                self.candidates({**screening_candidate(), "resource_ceiling": ceiling})
                self.assertEqual(self.check()["verdict"], "BLOCKED")
        self.candidates({**screening_candidate(), "resource_ceiling": {"nodes": 2, "walltime_s": 90}})
        self.assertEqual(self.check()["verdict"], "PASS")

    def test_missing_historical_unselected_or_unrecorded_content_is_not_ready(self):
        self.assertEqual(self.check()["verdict"], "BLOCKED")
        candidate = self.candidates(screening_candidate())[0]
        for changes in ({"present": False}, {"selected": False}, {"intervention": "Untracked change"},
                        {"content_sha": None}, {"revision": None}, {"revision": 0}, {"revision": True}):
            with self.subTest(changes=changes):
                discovery.write_candidates(self.root, [{**candidate, **changes}])
                self.assertEqual(self.check()["verdict"], "BLOCKED")

    def test_screening_content_changes_revision_and_invalidates_old_admission_identity(self):
        old = self.candidates(screening_candidate())[0]
        for field, value in (("intervention", "New update"), ("comparator", "Matched baseline B"),
                             ("resource_ceiling", {"nodes": 1, "walltime_s": 61}),
                             ("stop_conditions", "Stop at cap")):
            with self.subTest(field=field):
                changed = self.candidates({**screening_candidate(), field: value})[0]
                self.assertEqual(changed["id"], old["id"])
                self.assertGreater(changed["revision"], old["revision"])
                self.assertNotEqual((old["revision"], old["content_sha"]), (changed["revision"], changed["content_sha"]))
        restored = self.candidates(screening_candidate())[0]
        self.assertEqual(restored["content_sha"], old["content_sha"])
        self.assertGreater(restored["revision"], old["revision"])

    def test_readiness_rejects_all_old_workflow_arguments(self):
        self.candidates(screening_candidate())
        for kwargs in ({"workflow_mode": "strict"}, {"workflow_mode": "fast_screening"}, {"reviews": []},
                       {"literature": {}}, {"min_related_work": 3}):
            with self.subTest(kwargs=kwargs), self.assertRaises(TypeError):
                discovery.evaluate_candidate(self.root, "CAND-0001", **kwargs)

    def test_selection_is_incremental_and_is_not_admission(self):
        items = discovery.merge([{"source": "explorer/main", "candidates": [screening_candidate(), {"title": "B"}]}], [])
        discovery.write_candidates(self.root, items)
        self.assertEqual(self.check()["verdict"], "BLOCKED")
        discovery.select_candidate(self.root, items[0]["id"])
        self.assertEqual(self.check()["verdict"], "PASS")
        discovery.select_candidate(self.root, items[1]["id"])
        self.assertTrue(all(c["selected"] for c in discovery.read_candidates(self.root)))
        self.assertEqual(self.check(items[1]["id"])["verdict"], "BLOCKED")
        with self.assertRaisesRegex(discovery.DiscoveryError, "not a current"):
            discovery.select_candidate(self.root, "CAND-9999")

    def test_incremental_has_no_global_pass_or_mode_switch(self):
        self.assertFalse(hasattr(discovery, "evaluate"))
        with self.assertRaises(TypeError):
            discovery.start(self.root, "full", "claude-opus-5-5")
        self.assertNotIn("mode", discovery.load(self.root))


class IncrementalAdmissionTest(Fixture):
    def setUp(self):
        super().setUp()
        goal = self.doc(self.rld, "project/goal.v1.md", "goal", body=ANCHOR)
        instruction = self.doc(ResearchDB(self.db, "ui/ui"), "instructions/fast-scope.v1.md", "user_instruction",
                               body="Use fast screening and incremental discovery within the existing project budget.")
        self.rld.update_project(goal_doc_id=goal, user_instruction_doc_id=instruction)
        discovery.start(self.root, "claude-opus-5-5")
        candidates = discovery.merge([], [screening_candidate(), {"title": "B"}])
        discovery.write_candidates(self.root, candidates)
        self.ready, self.pending = [c["id"] for c in candidates]
        self.hyp_doc = self.doc(self.rld, "hypotheses/fast.v1.md", "hypothesis", body=ANCHOR +
                               "## 可证伪预测\nAccuracy increases at equal compute\n\n"
                               "## 干预\nUse per-block update rates\n\n"
                               "## 匹配对照\nUnchanged baseline at matching seed/data\n\n"
                               '## 资源上限\n```json\n{"nodes": 1, "walltime_s": 60}\n```\n\n'
                               "## 停止与继续条件\nStop on invalid metrics; replicate an applicable positive signal\n")

    def test_backend_admits_ready_a_while_b_and_all_batch_stages_remain_pending(self):
        node = self.rld.create_hypothesis("A", "Improve matched accuracy", self.hyp_doc, [], candidate_id=self.ready)
        self.assertEqual(self.rld.get(node)["candidate_id"], self.ready)
        self.assertEqual(self.rld.get(node)["comparator_experiment_id"], self.sota)
        before = self.rld.find("hypothesis")
        with self.assertRaisesRegex(ResearchDBError, "PRECHECK_REQUIRED"):
            self.rld.create_hypothesis("B", "Improve matched accuracy", self.hyp_doc, [], candidate_id=self.pending)
        self.assertEqual(self.rld.find("hypothesis"), before)
        self.assertNotIn("gate", discovery.load(self.root))
        self.assertNotIn("stages", discovery.load(self.root))
        self.assertEqual(self.rld.reviews(), [])

    def test_candidate_scope_and_hypothesis_scope_are_both_rechecked_at_admission(self):
        changed = discovery.merge([], [{**screening_candidate(), "resource_ceiling": {"nodes": 99, "walltime_s": 60}},
                                       {"title": "B"}], discovery.read_candidates(self.root))
        discovery.write_candidates(self.root, changed)
        with self.assertRaisesRegex(ResearchDBError, "PRECHECK_REQUIRED"):
            self.rld.create_hypothesis("A", "Improve accuracy", self.hyp_doc, [], candidate_id=self.ready)
        self.assertEqual(self.rld.find("hypothesis"), [])

        changed = discovery.merge([], [screening_candidate(), {"title": "B"}], changed)
        discovery.write_candidates(self.root, changed)
        bad_doc = self.doc(self.rld, "hypotheses/incomplete.v1.md", "hypothesis", body=ANCHOR +
                           "## 可证伪预测\nImprove accuracy\n")
        with self.assertRaisesRegex(ResearchDBError, "DESIGN_SECTION_MISSING"):
            self.rld.create_hypothesis("A", "Improve accuracy", bad_doc, [], candidate_id=self.ready)
        self.assertEqual(self.rld.find("hypothesis"), [])

    def test_candidate_scope_cannot_be_borrowed_or_removed_by_a_doc_update(self):
        node = self.rld.create_hypothesis("A", "s", self.hyp_doc, [], candidate_id=self.ready)
        original = self.rld.get(node)["screening_contract"]
        text = (self.root / "docs" / self.rld.get(self.hyp_doc)["path"]).read_text()
        changed = self.doc(self.rld, "hypotheses/widened.v1.md", "hypothesis",
                           body=text.replace("Use per-block update rates", "Change an unrelated mechanism")
                                    .replace('"walltime_s": 60', '"walltime_s": 3600'))
        with self.assertRaisesRegex(ResearchDBError, "PRECHECK_REQUIRED"):
            self.rld.update_hypothesis(node, doc_id=changed)
        self.assertEqual(self.rld.get(node)["screening_contract"], original)
        with self.assertRaisesRegex(ResearchDBError, "PRECHECK_REQUIRED"):
            self.rld.create_hypothesis("different idea", "s", changed, [], candidate_id=self.ready)


class IncrementalCommandTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.cwd = Path(self.tmp.name)
        self.plan = self.cwd / "plan.md"
        self.plan.write_text("# A small scoped research project\n")
        import review_call
        with mock.patch.object(review_call, "backend_for", return_value=argparse.Namespace(
                name="fixture-only", precheck=mock.Mock())):
            marker = research_tree.init(self.cwd, self.plan, "P-incremental")
        self.root = Path(marker["root"])

    def command(self, action, **kwargs):
        args = argparse.Namespace(action=action, candidate=None, triage=None, report=None)
        for k, v in kwargs.items():
            setattr(args, k, v)
        return research_tree.discovery_command(self.cwd, args)

    def test_minimal_scope_can_be_asked_with_pending_discovery_but_remains_unconfirmed(self):
        self.assertIsNone(research_tree.discovery_blocks_confirmation(self.cwd))
        self.assertEqual(research_tree.read_marker(self.cwd)["phase"], "planning")
        self.assertIsNone(research_tree.read_marker(self.cwd)["confirmed_at"])
        self.command("start")
        self.assertIsNone(self.command("check")["blocked"])
        self.assertEqual(research_tree.read_marker(self.cwd)["phase"], "planning")
        registry = json.loads((self.root / "agents.json").read_text())
        for actor in ("architect/root", "explorer/main", "analyst/main"):
            self.assertIn(actor, registry)

    def test_cli_candidate_checks_do_not_write_global_gate_or_confirm_scope(self):
        self.command("start")
        items = discovery.merge([{"source": "explorer/main", "candidates": [screening_candidate(), {"title": "B"}]}], [])
        discovery.write_candidates(self.root, items)
        self.command("select", candidate=items[0]["id"])
        marker = copy.deepcopy(research_tree.read_marker(self.cwd))
        self.assertEqual(self.command("gate", candidate=items[0]["id"])["verdict"], "PASS")
        self.assertEqual(self.command("gate", candidate=items[1]["id"])["verdict"], "BLOCKED")
        self.assertEqual(research_tree.read_marker(self.cwd), marker)
        self.assertNotIn("gate", discovery.load(self.root))
        with self.assertRaisesRegex(research_tree.TreeError, "requires --candidate"):
            self.command("gate")

    def test_old_configuration_never_falls_back_to_a_current_workflow(self):
        for mode in ("full", "precheck", "incremental"):
            (self.cwd / "research-tree.yaml").write_text(f"version: 2\ndiscovery: {{mode: {mode}}}\n")
            for action in ("check", "select", "gate"):
                with self.subTest(mode=mode, action=action), self.assertRaisesRegex(project_config.ConfigError,
                                                                                  "UNSUPPORTED_CONFIG_VERSION"):
                    self.command(action, candidate="CAND-0001")
        self.assertEqual(research_tree.read_marker(self.cwd)["phase"], "planning")


if __name__ == "__main__":
    unittest.main()
