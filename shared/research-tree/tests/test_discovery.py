"""Continuous discovery identity/provenance and explicit rejection of the removed batch pipeline."""
from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

TOOLS = Path(__file__).resolve().parents[1] / "tools"
sys.path.insert(0, str(TOOLS))
import discovery


def candidate(title="Candidate"):
    return {"title": title, "prediction": "Increase accuracy", "intervention": "Change update rate",
            "comparator": "Matched baseline", "resource_ceiling": {"nodes": 1, "walltime_s": 60},
            "stop_conditions": "Stop on invalid data; replicate a positive signal"}


class StateTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)

    def test_start_is_resumable_without_sequential_gates(self):
        first = discovery.start(self.root, "claude-opus-5-5")
        before = (self.root / discovery.STATE_PATH).read_bytes()
        self.assertEqual(discovery.start(self.root, "different-model"), first)
        self.assertEqual((self.root / discovery.STATE_PATH).read_bytes(), before)
        self.assertEqual(first["version"], discovery.DISCOVERY_VERSION)
        for obsolete in ("mode", "stages", "gate"):
            self.assertNotIn(obsolete, first)
        for obsolete in ("set_status", "accept", "resume_point", "evaluate", "select"):
            self.assertFalse(hasattr(discovery, obsolete))

    def test_older_discovery_is_rejected_without_writing(self):
        path = self.root / discovery.STATE_PATH
        path.parent.mkdir(parents=True)
        for value in ({"mode": "full", "stages": []}, {"mode": "precheck"}, {"mode": "incremental"},
                      {"version": 1}, {"version": 2, "gate": {"verdict": "PASS"}}):
            with self.subTest(value=value):
                path.write_text(json.dumps(value))
                before = {p: p.read_bytes() for p in self.root.rglob("*") if p.is_file()}
                with self.assertRaisesRegex(discovery.DiscoveryError, "UNSUPPORTED_DISCOVERY_VERSION"):
                    discovery.start(self.root, "model")
                self.assertEqual(before, {p: p.read_bytes() for p in self.root.rglob("*") if p.is_file()})

    def test_older_candidate_pool_is_not_silently_rewritten(self):
        path = self.root / discovery.CANDIDATES_PATH
        path.parent.mkdir(parents=True)
        path.write_text(json.dumps({"candidates": [candidate()]}))
        before = path.read_bytes()
        with self.assertRaisesRegex(discovery.DiscoveryError, "UNSUPPORTED_DISCOVERY_VERSION"):
            discovery.write_candidates(self.root, [])
        with self.assertRaisesRegex(discovery.DiscoveryError, "UNSUPPORTED_DISCOVERY_VERSION"):
            discovery.start(self.root)
        self.assertEqual(path.read_bytes(), before)
        self.assertFalse((self.root / discovery.STATE_PATH).exists())

    def test_dedup_retains_user_origin_and_exact_advisor_sources(self):
        user = [{"title": "Adam with linear warmup", "summary": "u"}]
        proposals = [{"source": "explorer/variants", "candidates": [
            {"title": "Adam, with linear Warmup!", "summary": "same idea"},
            {"title": "Weak idea", "summary": "unpromising but retained"}]},
            {"source": "explorer/repairs", "candidates": [{"title": "Weak idea", "summary": "again"}]}]
        merged = discovery.merge(proposals, user)
        self.assertEqual(len(merged), 2)
        self.assertEqual((merged[0]["origin"], merged[0]["id"]), ("user", "CAND-0001"))
        self.assertEqual(merged[0]["found_by"], ["explorer/variants", "user"])
        self.assertEqual(merged[1]["found_by"], ["explorer/repairs", "explorer/variants"])
        self.assertEqual(merged[1]["origin"], "explorer")

    def test_titles_sharing_only_their_ascii_words_are_different_ideas(self):
        proposals = [{"source": "explorer/main", "candidates": [
            {"title": "LoRA 秩自适应", "intervention": "adapt the rank"},
            {"title": "LoRA 低秩初始化", "intervention": "initialise low rank"}]},
            {"source": "explorer/variants", "candidates": [{"title": "ＬｏＲＡ秩自适应！", "summary": "same idea"}]}]
        users = [{"title": "SGD 动量预热"}, {"title": "SGD 学习率重启"}]
        merged = discovery.merge(proposals, users)
        self.assertEqual(sorted(c["title"] for c in merged),
                         ["LoRA 低秩初始化", "LoRA 秩自适应", "SGD 动量预热", "SGD 学习率重启"])
        by_title = {c["title"]: c for c in merged}
        self.assertEqual(by_title["LoRA 秩自适应"]["intervention"], "adapt the rank")
        self.assertEqual(by_title["LoRA 秩自适应"]["found_by"], ["explorer/main", "explorer/variants"])
        self.assertEqual(by_title["LoRA 低秩初始化"]["intervention"], "initialise low rank")
        self.assertEqual(len({c["id"] for c in merged}), 4)
        # pure-ASCII titles keep the key they always had
        self.assertEqual(discovery.dedup_key("Adam, with linear Warmup!"), "adam-with-linear-warmup")
        self.assertEqual(discovery.dedup_key("Café: résumé_v2"), "cafe-resume_v2")
        # a later idea sharing only the ASCII word is a new candidate, not a revision of the first
        first = discovery.merge([], [{"title": "SGD 动量预热", "intervention": "warm up momentum"}])
        both = discovery.merge([], [{"title": "SGD 动量预热", "intervention": "warm up momentum"},
                                    {"title": "SGD 学习率重启", "intervention": "restart the rate"}], first)
        self.assertEqual([(c["id"], c["revision"]) for c in both if c["title"] == "SGD 动量预热"],
                         [(first[0]["id"], 1)])
        self.assertEqual([c["id"] for c in both if c["title"] == "SGD 学习率重启"], ["CAND-0002"])

    def test_candidates_keyed_by_the_older_rule_keep_their_identity(self):
        # pools written before non-ASCII words were kept store 'zebra' and 'lora' as keys
        old = discovery.merge([{"source": "explorer/main", "candidates": [{"title": "LoRA 秩自适应", "summary": "a"}]}],
                              [{"title": "Zebra：重球动量在固定更新预算下收敛更快"}])
        for c, stored in zip(old, ("zebra", "lora")):
            c["dedup_key"] = stored
            c["selected"] = True
        merged = discovery.merge([{"source": "explorer/main", "candidates": [
            {"title": "LoRA 秩自适应", "summary": "a"}, {"title": "LoRA 低秩初始化", "summary": "b"}]}],
            [{"title": "Zebra：重球动量在固定更新预算下收敛更快"}], old)
        by_title = {c["title"]: c for c in merged}
        for c in old:
            current = by_title[c["title"]]
            self.assertEqual((current["id"], current["revision"], current["selected"], current["present"]),
                             (c["id"], c["revision"], True, True))
            self.assertEqual(current["dedup_key"], discovery.dedup_key(c["title"]))
        self.assertEqual(by_title["LoRA 低秩初始化"]["id"], "CAND-0003")
        self.assertNotIn("selected", by_title["LoRA 低秩初始化"])

    def test_a_proposal_cannot_set_selection_feasibility_or_identity(self):
        claimed = {"selected": True, "feasible": True, "feasibility_reasons": [], "id": "CAND-0042",
                   "candidate_id": "CAND-0042", "origin": "user", "found_by": ["user"], "revision": 9,
                   "content_sha": "0" * 64, "revisions": [], "present": True}
        asserted = {**candidate("Self-selected"), **claimed}
        merged = discovery.merge([{"source": "explorer/main", "candidates": [asserted]},
                                  {"source": "explorer/other", "candidates": [asserted]}], [])
        self.assertEqual(len(merged), 1)
        c = merged[0]
        self.assertEqual((c["id"], c["origin"], c["revision"]), ("CAND-0001", "explorer", 1))
        self.assertEqual(c["found_by"], ["explorer/main", "explorer/other"])
        self.assertEqual(c["content_sha"], discovery.content_sha(candidate("Self-selected")))
        for field in ("selected", "feasible", "feasibility_reasons", "candidate_id"):
            self.assertNotIn(field, c)
        # nor can a proposal unselect what the Leader selected
        c["selected"] = True
        again = discovery.merge([{"source": "explorer/main", "candidates": [{**candidate("Self-selected"),
                                                                             "selected": False}]}], [], merged)
        self.assertTrue(again[0]["selected"])

    def test_legacy_lens_shards_and_malformed_proposals_are_rejected(self):
        for proposal in ({"lens": "variant", "candidates": [candidate()]}, {"candidates": []},
                         {"source": "", "candidates": []}, {"source": "explorer/main", "candidates": {}},
                         {"source": "explorer/main", "candidates": [{}]}):
            with self.subTest(proposal=proposal), self.assertRaises(discovery.DiscoveryError):
                discovery.merge([proposal], [])

    def test_candidate_id_revision_and_history_do_not_depend_on_order(self):
        a, b = candidate("A"), candidate("B")
        initial = discovery.merge([], [a, b])
        reversed_pool = discovery.merge([], [b, a], initial)
        self.assertEqual([(c["id"], c["revision"]) for c in initial],
                         [(c["id"], c["revision"]) for c in reversed_pool])
        changed = discovery.merge([], [{**a, "intervention": "Different update"}], initial)
        self.assertEqual(changed[0]["id"], initial[0]["id"])
        self.assertEqual(changed[0]["revision"], 2)
        self.assertNotEqual(changed[0]["content_sha"], initial[0]["content_sha"])
        self.assertFalse(changed[1]["present"])
        self.assertFalse(changed[1]["selected"])
        self.assertEqual(changed[0]["revisions"][0]["content_sha"], initial[0]["content_sha"])
        self.assertEqual(len(changed[0]["revisions"]), 2)

    def test_feasibility_records_budget_facts_without_deleting_user_ideas(self):
        candidates = [{"id": "CAND-0001", "title": "u", "origin": "user", "estimated_run": {"nodes": 64, "walltime_s": 60}},
                      {"id": "CAND-0002", "title": "big", "origin": "explorer", "estimated_run": {"nodes": 16, "walltime_s": 60}},
                      {"id": "CAND-0003", "title": "ok", "origin": "explorer", "estimated_run": {"nodes": 1, "walltime_s": 600}},
                      {"id": "CAND-0004", "title": "?", "origin": "explorer"}]
        out = {c["id"]: c for c in discovery.feasibility(candidates, 8, 3600, 10)}
        self.assertFalse(out["CAND-0002"]["feasible"])
        self.assertIn("per-run cap", out["CAND-0002"]["feasibility_reasons"][0])
        self.assertTrue(out["CAND-0003"]["feasible"])
        self.assertIsNone(out["CAND-0004"]["feasible"])
        self.assertIn("kept for the user", out["CAND-0001"]["feasibility_reasons"][-1])

    def test_selection_does_not_make_an_incomplete_candidate_ready(self):
        discovery.start(self.root)
        pool = discovery.merge([{"source": "explorer/main", "candidates": [{"title": "Incomplete"}]}], [])
        discovery.write_candidates(self.root, pool)
        discovery.select_candidate(self.root, pool[0]["id"])
        self.assertEqual(discovery.evaluate_candidate(self.root, pool[0]["id"])["verdict"], "BLOCKED")
        with self.assertRaisesRegex(discovery.DiscoveryError, "not a current"):
            discovery.select_candidate(self.root, "CAND-9999")

    def test_proposals_are_read_from_only_the_current_location(self):
        old = self.root / "cache/discovery/shards"
        old.mkdir(parents=True)
        (old / "old.json").write_text(json.dumps({"lens": "old", "candidates": [candidate("Old")]}))
        current = self.root / "cache/discovery/proposals"
        current.mkdir()
        proposal = {"source": "explorer/main", "candidates": [candidate()]}
        (current / "current.json").write_text(json.dumps(proposal))
        self.assertEqual(discovery.read_proposals(self.root), [proposal])


class CommandRejectionTest(unittest.TestCase):
    def test_removed_batch_actions_are_not_cli_options(self):
        with tempfile.TemporaryDirectory() as tmp:
            for action in ("set", "accept", "resume"):
                out = subprocess.run([sys.executable, str(TOOLS / "research_tree.py"), "discovery", action],
                                     cwd=tmp, capture_output=True, text=True)
                self.assertNotEqual(out.returncode, 0)
                self.assertIn("invalid choice", out.stderr)
            for flag in ("--triage", "--report", "--stage", "--verifier"):
                out = subprocess.run([sys.executable, str(TOOLS / "research_tree.py"), "discovery", "gate", flag, "x"],
                                     cwd=tmp, capture_output=True, text=True)
                self.assertNotEqual(out.returncode, 0)
                self.assertIn("unrecognized arguments", out.stderr)


if __name__ == "__main__":
    unittest.main()
