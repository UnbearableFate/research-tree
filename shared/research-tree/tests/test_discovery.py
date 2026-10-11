"""plans/design 11 R09–R13, R15–R17: discovery stages, candidates and gates; receipts before initial nodes."""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

TOOLS = Path(__file__).resolve().parents[1] / "tools"
sys.path.insert(0, str(TOOLS))
sys.path.insert(0, str(TOOLS.parent / "schema"))

import discovery  # noqa: E402
from test_research_db import Fixture, rdb  # noqa: E402  (the same research_db module the fixture uses)

ResearchDB, ResearchDBError = rdb.ResearchDB, rdb.ResearchDBError


class StateTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)

    def review(self, doc_id: str, kind: str, model: str = "openai/gpt-6-luna", status: str = "current") -> dict:
        return {"id": doc_id, "review_kind": kind, "reviewer_model": model, "status": status}

    def test_r11_resume_returns_the_first_unaccepted_stage(self):
        discovery.start(self.root, "full", "claude-opus-5-5")
        self.assertEqual(discovery.resume_point(self.root)["stage"], "brief")
        discovery.set_status(self.root, "brief", "done")
        (self.root / "lit.md").write_text("x")
        discovery.set_status(self.root, "literature", "done", "lit.md")
        # done but not accepted: literature is redone on resume, never skipped
        self.assertEqual(discovery.resume_point(self.root)["stage"], "literature")
        with self.assertRaisesRegex(discovery.DiscoveryError, "deterministic check"):
            discovery.accept(self.root, "literature", ["verify.json"])
        discovery.accept(self.root, "literature", ["verify.json"], verifier="literature.py")
        self.assertEqual(discovery.resume_point(self.root)["stage"], "candidates")
        # a restart keeps what was recorded (start is idempotent)
        self.assertEqual(discovery.start(self.root, "full", "x")["stages"][1]["status"], "accepted")

    def test_review_stage_acceptance_needs_another_family(self):
        discovery.start(self.root, "precheck", "claude-opus-5-5")
        self.assertEqual({s["stage"] for s in discovery.load(self.root)["stages"] if s["status"] == "skipped"},
                         {"candidates", "feasibility", "triage"})
        # real-run-error #15: a finished stage names its output, and the file exists
        with self.assertRaisesRegex(discovery.DiscoveryError, "novelty done needs --artifact"):
            discovery.set_status(self.root, "novelty", "done")
        with self.assertRaisesRegex(discovery.DiscoveryError, "not a file"):
            discovery.set_status(self.root, "novelty", "done", "x")
        (self.root / "x").write_text("RV-0001 PROCEED\n")
        discovery.set_status(self.root, "novelty", "done", "x")
        with self.assertRaisesRegex(discovery.DiscoveryError, "another model family"):
            discovery.accept(self.root, "novelty", ["D-1"], [self.review("D-1", "novelty_precheck",
                                                                         "anthropic/claude-sonnet-5-5")])
        with self.assertRaisesRegex(discovery.DiscoveryError, "current novelty_precheck"):
            discovery.accept(self.root, "novelty", ["D-2"], [self.review("D-2", "critical_review")])
        discovery.accept(self.root, "novelty", ["D-3"], [self.review("D-3", "novelty_precheck")])
        with self.assertRaisesRegex(discovery.DiscoveryError, "set writes pending, running, done, failed"):
            discovery.set_status(self.root, "critique", "accepted")

    def test_r12_r17_dedup_only_by_key_and_user_origin_kept(self):
        user = [{"title": "Adam with linear warmup", "summary": "u"}]
        shards = [{"lens": "variant", "generator": "assistant", "candidates": [
                      {"title": "Adam, with linear Warmup!", "summary": "same idea"},
                      {"title": "Weak idea", "summary": "obviously weak"}]},
                  {"lens": "repair", "candidates": [{"title": "Weak idea", "summary": "again"}]}]
        merged = discovery.merge(shards, user)
        self.assertEqual(len(merged), 2)  # duplicates clustered, the weak one kept
        first = merged[0]
        self.assertEqual((first["origin"], first["id"]), ("user", "CAND-0001"))
        self.assertEqual(first["found_by"], ["user", "variant:assistant"])
        self.assertEqual(merged[1]["found_by"], ["repair:assistant", "variant:assistant"])

    def test_r13_feasibility_only_budget_facts(self):
        cands = [{"id": "CAND-0001", "title": "u", "origin": "user", "estimated_run": {"nodes": 64, "walltime_s": 60}},
                 {"id": "CAND-0002", "title": "big", "origin": "lens", "estimated_run": {"nodes": 16, "walltime_s": 60}},
                 {"id": "CAND-0003", "title": "ok", "origin": "lens", "estimated_run": {"nodes": 1, "walltime_s": 600}},
                 {"id": "CAND-0004", "title": "?", "origin": "lens"}]
        out = {c["id"]: c for c in discovery.feasibility(cands, 8, 3600, 10)}
        self.assertFalse(out["CAND-0002"]["feasible"])
        self.assertIn("per-run cap", out["CAND-0002"]["feasibility_reasons"][0])
        self.assertTrue(out["CAND-0003"]["feasible"])
        self.assertIsNone(out["CAND-0004"]["feasible"])
        self.assertIn("kept for the user", out["CAND-0001"]["feasibility_reasons"][-1])

    def test_r15_user_hypothesis_ranked_last_still_selected(self):
        cands = [{"id": "CAND-0001", "origin": "user", "title": "u", "feasible": False},
                 {"id": "CAND-0002", "origin": "lens", "title": "a", "feasible": True},
                 {"id": "CAND-0003", "origin": "lens", "title": "b", "feasible": True},
                 {"id": "CAND-0004", "origin": "lens", "title": "c", "feasible": False}]
        ranking = [{"candidate_id": "CAND-0003", "rank": 1}, {"candidate_id": "CAND-0002", "rank": 2},
                   {"candidate_id": "CAND-0001", "rank": 3}]
        chosen = {c["id"]: c["selected"] for c in discovery.select(cands, ranking, 1)}
        self.assertEqual(chosen, {"CAND-0001": True, "CAND-0002": False, "CAND-0003": True, "CAND-0004": False})

    def test_gate_reports_what_is_missing(self):
        discovery.start(self.root, "precheck", "claude-opus-5-5")
        merged = discovery.merge([], [{"title": "u", "summary": "s", "literature": ["D-1", "D-2"]}])
        discovery.write_candidates(self.root, merged)
        basis = {"candidate_id": "CAND-0001", "revision": 1, "content_sha": merged[0]["content_sha"]}
        result = discovery.evaluate(self.root, [], {"D-1": True, "D-2": False}, 2, "report.md")
        self.assertEqual(result["verdict"], "BLOCKED")
        text = "; ".join(result["reasons"])
        for expected in ("brief: pending", "report", "no novelty_precheck receipt", "1 verified literature"):
            self.assertIn(expected, text)
        # everything in place
        (self.root / "a.md").write_text("x")
        for stage in ("brief", "literature", "novelty", "critique", "refine"):
            discovery.set_status(self.root, stage, "done", "a.md")
        discovery.accept(self.root, "literature", ["a.md"], verifier="literature.py")
        reviews = [{"id": "D-7", "review_kind": "novelty_precheck", "reviewer_model": "openai/gpt-6-luna",
                    "status": "current", "review_about": "CAND-0001", "review_basis": basis},
                   {"id": "D-8", "review_kind": "critical_review", "reviewer_model": "openai/gpt-6-luna",
                    "status": "current", "review_about": "CAND-0001", "review_basis": basis}]
        discovery.accept(self.root, "novelty", ["D-7"], reviews)
        discovery.accept(self.root, "critique", ["D-8"], reviews)
        (self.root / "report.md").write_text("## 用户假说\n\nCAND-0001: PROCEED\n\n## 新发现候选\n\n无\n\n## 淘汰想法\n\n无\n")
        result = discovery.evaluate(self.root, reviews, {"D-1": True, "D-2": True}, 2, "report.md")
        self.assertEqual(result, {"verdict": "PASS", "reasons": []})


class ReceiptTest(Fixture):
    """R09, R10, R16: verified literature and discovery receipts before an initial node."""

    def lit_doc(self, verified: bool) -> str:
        """A literature document checked through verify_literature (the network layer stubbed)."""
        from unittest import mock
        import literature
        title = f"paper {self.n} {'real' if verified else 'ghost'}"
        # a hand-typed verification line in the file never counts: only the recorded check does
        doc = self.doc(self.worker, f"literature/LIT-v{self.n}.v1.md", "literature",
                       body=f"---\ntitle: \"{title}\"\nverification: verified\n---\n\n# x\n")
        verdict = {"verification": "verified" if verified else "unverified", "method": "arxiv", "detail": "stub"}
        with mock.patch.object(literature, "verify", return_value=verdict):
            self.worker.verify_literature(doc)
        return doc

    def review(self, about: str, kind: str, result: str) -> str:
        self.n += 1
        reviewer = ResearchDB(self.db, "reviewer/pi")
        (reviewer.docs_root / "reviews").mkdir(exist_ok=True)
        path = f"reviews/RV-{self.n:04d}.v1.md"
        (reviewer.docs_root / path).write_text(result, encoding="utf-8")
        return reviewer.register_review(path, "r", kind, [about], result, f"RV-{self.n:04d}", "pi",
                                        "openai/gpt-6-luna", 0.0, basis=reviewer.review_basis(about, kind))

    def test_r10_unverified_literature_does_not_count(self):
        self.rld.update_project(literature_verification=True)
        lit = [self.lit_doc(True), self.lit_doc(True), self.lit_doc(False)]
        doc = self.doc(self.rld, "h/x/hypothesis.v1.md", "hypothesis")
        with self.assertRaisesRegex(ResearchDBError, "LITERATURE_UNVERIFIED: only 2 of the cited"):
            self.rld.create_hypothesis("h", "s", doc, lit)
        self.rld.create_hypothesis("h", "s", doc, lit[:2] + [self.lit_doc(True)])

    def test_r09_r16_receipts(self):
        self.rld.update_project(require_precheck=True)
        doc = self.doc(self.rld, "h/y/hypothesis.v1.md", "hypothesis")
        with self.assertRaisesRegex(ResearchDBError, "PRECHECK_REQUIRED: .*names its discovery candidate"):
            self.rld.create_hypothesis("h", "s", doc, self.literature)
        with self.assertRaisesRegex(ResearchDBError, "PRECHECK_REQUIRED: .*after the discovery gate passed"):
            self.rld.create_hypothesis("h", "s", doc, self.literature, candidate_id="CAND-0001")
        state = self.root / "cache" / "discovery" / "state.json"
        state.parent.mkdir(parents=True)
        state.write_text(json.dumps({"gate": {"verdict": "PASS"}}))
        discovery.write_candidates(self.root, discovery.merge([], [{"title": "u1", "summary": "a"},
                                                                    {"title": "u2", "summary": "b"}]))
        with self.assertRaisesRegex(ResearchDBError, "CAND-0001 has no novelty_precheck and no critical_review"):
            self.rld.create_hypothesis("h", "s", doc, self.literature, candidate_id="CAND-0001")
        self.review("CAND-0001", "novelty_precheck", "ABANDON")
        with self.assertRaisesRegex(ResearchDBError, "no critical_review receipt"):  # R09 names what is missing
            self.rld.create_hypothesis("h", "s", doc, self.literature, candidate_id="CAND-0001")
        self.review("CAND-0001", "critical_review", "proceed")
        # R16: a named ABANDON of a user hypothesis is the user's to decide
        with self.assertRaisesRegex(ResearchDBError, "advise against it .*待用户决定"):
            self.rld.create_hypothesis("h", "s", doc, self.literature, candidate_id="CAND-0001")
        keep = self.doc(ResearchDB(self.db, "ui/ui"), "instructions/UI-0600.v1.md", "user_instruction")
        h = self.rld.create_hypothesis("h", "s", doc, self.literature, candidate_id="CAND-0001",
                                       user_instruction_doc_id=keep)
        self.assertEqual(self.rld.get(h)["candidate_id"], "CAND-0001")
        self.review("CAND-0002", "novelty_precheck", "PROCEED_WITH_CAUTION")  # R06: positive
        self.review("CAND-0002", "critical_review", "proceed")
        self.rld.create_hypothesis("h2", "s", doc, self.literature, candidate_id="CAND-0002")
        self.assertEqual([r["review_about"] for r in self.rld.reviews(about="CAND-0002")], ["CAND-0002"] * 2)


class CommandTest(unittest.TestCase):
    """The discovery subcommand end to end on a project (no network, no reviewer): merge selects the user
    hypotheses, cite attaches literature, the gate reports, and the start-up plan stays blocked until PASS."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.cwd = Path(self.tmp.name)
        (self.cwd / "plan.md").write_text("# 计划\n", encoding="utf-8")

    def tool(self, *args):
        out = subprocess.run([sys.executable, str(TOOLS / "research_tree.py"), *args], cwd=self.cwd,
                             capture_output=True, text=True, env={**os.environ})
        return json.loads(out.stdout)

    def test_precheck_flow(self):
        import research_tree
        config = (TOOLS.parent / "schema" / "config.template.yaml").read_text(encoding="utf-8")
        (self.cwd / "research-tree.yaml").write_text(config.replace("  mode: incremental ", "  mode: precheck "),
                                                    encoding="utf-8")
        self.assertTrue(self.tool("init", "plan.md", "--project-id", "P-d")["ok"])
        blocked = self.tool("discovery", "check")["result"]["blocked"]
        self.assertIn("尚未运行", blocked)
        self.assertEqual(research_tree.discovery_blocks_confirmation(self.cwd), blocked)
        self.assertEqual(self.tool("discovery", "start")["result"]["mode"], "precheck")
        (self.cwd / "users.json").write_text(json.dumps([{"title": "Adam warmup", "summary": "u"}]))
        merged = self.tool("discovery", "merge", "--user-hypotheses", "users.json")["result"]["candidates"]
        self.assertEqual([(c["id"], c["origin"], c["selected"]) for c in merged], [("CAND-0001", "user", True)])
        self.assertIn("not a literature document", self.tool("discovery", "cite", "--candidate", "CAND-0001",
                                                             "--literature", "D-0001")["error"])
        gate = self.tool("discovery", "gate", "--report", "docs/project/reports/discovery.v1.md")["result"]
        self.assertEqual(gate["verdict"], "BLOCKED")
        self.assertIn("CAND-0001 (Adam warmup): no novelty_precheck receipt", gate["reasons"])
        self.assertIn("discovery 门尚未通过", self.tool("discovery", "check")["result"]["blocked"])


if __name__ == "__main__":
    unittest.main()
