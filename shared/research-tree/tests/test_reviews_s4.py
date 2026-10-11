"""S4 (plans/research-tree-implementation-and-real-scenarios.md §8.6): what a review receipt concludes is computed
from its checklist and the current applicability; its evidence is resolved to real files of the reviewed version;
model families come from model names; literature follow-up is bounded and repeatable; findings close only with
evidence for that item. REG-S4-01..08 (REG-S4-04's call-level cases are in test_review_call). The receipts are REG
fixtures, not reviewer output."""

from __future__ import annotations

import json
import re
import sys
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))

from test_research_db import PROTOCOL, Fixture, ResearchDB, ResearchDBError, rdb, recheck_payload  # noqa: E402

import review_rules  # noqa: E402

DIMENSIONS = list(review_rules.RECHECK_ITEMS)


def receipt(dimension: str, top: str, items: dict | None = None, paths=("docs/evidence.md",)) -> dict:
    """A receipt whose items all pass unless items says otherwise."""
    items = items or {}
    return {"dimension": dimension, "result": top, "evidence_paths": list(paths), "reason": "r",
            "checklist": [{"item": i, "result": items.get(i, "pass"), "note": f"{i} note"}
                          for i in review_rules.RECHECK_ITEMS[dimension]]}


class S4Fixture(Fixture):
    protocol_content = {**PROTOCOL, "review_applicability": {"novelty": {"exemptible": True}}}

    def setUp(self):
        super().setUp()
        self.reviewer = ResearchDB(self.db, "reviewer/pi")
        (self.reviewer.docs_root / "reviews").mkdir(exist_ok=True)
        (self.root / "docs" / "evidence.md").write_text("evidence\n", encoding="utf-8")
        self.k = 0

    def candidate_node(self) -> tuple[str, str, str]:
        h, exp = self.concluded()
        self.rld.decide(h, {"experiment_status": "beats_sota"}, "gate", based_on=[exp])
        self.recheck_pass(h, exp)
        self.rld.update_project()
        return h, exp, self.rld.get_eligibility(h)["basis_evaluation_id"]

    def register(self, h: str, dimension: str, payload: dict, ev: str, session: str | None = None,
                 basis: dict | None = None, **kw) -> str:
        self.k += 1
        session = session or f"RV-{self.k:04d}"
        version = 1 + sum(1 for d in self.rld.reviews() if d.get("review_session") == session)
        path = f"reviews/{session}.v{version}.md"
        (self.reviewer.docs_root / path).write_text(json.dumps(payload), encoding="utf-8")
        previous = [d for d in self.rld.reviews() if d.get("review_session") == session and d["status"] == "current"]
        return self.reviewer.register_review(
            path, f"recheck {dimension}", "candidate_recheck", [h], payload.get("result", "pass"), session, "pi",
            "openai/gpt-6-astra", 0.01, dimension=dimension, evaluation_id=ev,
            supersedes=previous[0]["id"] if previous else None,
            basis=basis or self.reviewer.review_basis(h, "candidate_recheck", dimension, ev), payload=payload, **kw)

    def all_pass(self, h: str, ev: str, skip: tuple = ()) -> None:
        for dimension in DIMENSIONS:
            if dimension not in skip:
                self.register(h, dimension, recheck_payload(self, dimension, "pass", ev), ev)

    def state(self, h: str) -> dict:
        return {r["dimension"]: r["state"] for r in self.rld.get_eligibility(h)["rechecks"]}

    def with_applicability(self, h: str, declared: dict | None) -> None:
        """A new hypothesis document whose '评审适用性' block declares the claim's own scope (a new claim)."""
        self.n += 1
        original = (self.root / "docs" / self.rld.get(self.rld.get(h)["doc_id"])["path"]).read_text()
        body = re.sub(r"^## (?:Claim map|评审适用性)\n.*?(?=^## |\Z)", "", original, flags=re.M | re.S)
        body += "\n## Claim map\n\n| claim | evidence |\n|---|---|\n| faster | runs |\n\n"
        if declared is not None:
            body += f"## 评审适用性\n\n```json\n{json.dumps(declared)}\n```\n"
        doc = self.doc(self.rld, f"h/{h}/hypothesis.v{self.n}.md", "hypothesis", body=body)
        self.rld.update_hypothesis(h, doc_id=doc)


class ChecklistTest(S4Fixture):
    def test_reg_s4_01_a_failed_item_under_a_top_level_pass_fails(self):
        import review_call
        h, exp, ev = self.candidate_node()
        payload = receipt("numbers", "pass", {"C": "fail"})
        schema = json.loads((Path(review_call.REVIEWS_DIR) / "candidate_recheck.schema.json").read_text())
        self.assertEqual(review_call.problems("candidate_recheck", payload, schema, "numbers"), [])  # no rewrite asked
        doc = self.rld.get(self.register(h, "numbers", payload, ev))
        self.assertEqual((doc["reported_result"], doc["effective_result"], doc["review_result"]), ("pass", "fail", "fail"))
        self.assertEqual(doc["review_payload"], payload)  # the receipt as given
        self.assertTrue(any(w.startswith("SUMMARY_CHECKLIST_MISMATCH") for w in doc["normalization_warnings"]))
        (finding,) = self.rld.obligations(about=h, status="OPEN")
        self.assertEqual((finding["pattern"], finding["review_issue"]["item"]), ("numbers:C", "C"))
        self.all_pass(h, ev, skip=("numbers",))
        state = self.rld.get_eligibility(h)
        self.assertEqual(sorted(state["reasons"]), ["CONFIRMATION_REQUIRED", "OBLIGATION_OPEN", "RECHECK_FAILED"])
        with self.assertRaisesRegex(ResearchDBError, "OBLIGATION_OPEN|CONFIRMATION_REQUIRED|GO"):
            self.rld.decide("P-test", {"status": "go"}, "GO", doc_id=self.report_doc("go"))

    def test_reg_s4_02_the_one_rule(self):
        norm = review_rules.normalize_recheck
        self.assertEqual(norm("numbers", receipt("numbers", "pass", {"B": "uncertain"}))["effective_result"], "uncertain")
        self.assertEqual(norm("numbers", receipt("numbers", "uncertain"))["effective_result"], "uncertain")  # top more cautious
        self.assertEqual(norm("numbers", receipt("numbers", "fail"))["findings"][0]["item"], "summary")
        partial = receipt("numbers", "pass", {"B": "not_applicable", "F": "not_applicable"})
        self.assertEqual(norm("numbers", partial)["effective_result"], "pass")  # some N/A with reasons, the rest pass
        all_na = receipt("theory", "not_applicable", {"I": "not_applicable"})
        self.assertEqual(norm("theory", all_na)["effective_result"], "uncertain")  # not exempt: never a pass
        missing = receipt("protocol", "pass")
        missing["checklist"].pop()
        duplicated = receipt("novelty", "pass")
        duplicated["checklist"].append(dict(duplicated["checklist"][0]))
        foreign = receipt("theory", "pass")
        foreign["checklist"].append({"item": "A", "result": "pass", "note": "x"})
        for bad in ((missing, "protocol"), (duplicated, "novelty"), (foreign, "theory")):
            self.assertTrue(norm(bad[1], bad[0])["invalid"])
        h, exp, ev = self.candidate_node()
        with self.assertRaisesRegex(ResearchDBError, "REVIEW_INVALID: .*missing"):
            self.register(h, "protocol", missing, ev)
        with self.assertRaisesRegex(ResearchDBError, "REVIEW_INVALID: .*more than once"):
            self.register(h, "novelty", duplicated, ev)
        # a whole-dimension exemption: the frozen protocol allows it for novelty and the current claim declares it
        self.all_pass(h, ev, skip=("novelty",))
        na = receipt("novelty", "not_applicable", {"H": "not_applicable"})
        self.register(h, "novelty", na, ev)
        self.assertEqual(self.state(h)["novelty"], "uncertain")  # the claim declares nothing yet
        self.with_applicability(h, {"novelty": {"required": False, "scope_ref": "Claim map",
                                                "reason": "a reproduction: no method novelty is claimed"},
                                    "numbers": {"required": False, "reason": "ignored: never exempt"}})
        self.all_pass(h, ev, skip=("novelty",))  # the claim changed: claim-bound receipts again
        self.register(h, "novelty", na, ev)
        self.recheck_pass(h, exp)  # and the Leader's recheck decisions on the new claim
        rows = {r["dimension"]: r for r in self.rld.get_eligibility(h)["rechecks"]}
        self.assertEqual((rows["novelty"]["state"], rows["novelty"]["result"]), ("exempt", "not_applicable"))
        self.assertEqual(rows["numbers"]["applicability"]["required"], True)
        novelty_review = rows["novelty"]["review_id"]
        confirmation = self.complete_confirmation(h, exp, review=False)
        for dimension in ("numbers", "protocol"):
            self.register(h, dimension, recheck_payload(self, dimension, "pass", confirmation), confirmation)
        final = self.rld.get_eligibility(h)
        self.assertTrue(final["eligible"], final["reasons"])
        novelty = next(row for row in final["rechecks"] if row["dimension"] == "novelty")
        self.assertEqual((novelty["state"], novelty["result"], novelty["review_id"]),
                         ("exempt", "not_applicable", novelty_review))
        # a reviewer who finds an applicable problem in an exempted dimension is heard
        exempt = review_rules.applicability(self.protocol_content, {"novelty": {"required": False, "reason": "r"}})
        conflict = norm("novelty", receipt("novelty", "fail", {"H": "fail"}), exempt)
        self.assertEqual(conflict["effective_result"], "fail")
        self.assertTrue(any(w.startswith("APPLICABILITY_CONFLICT") for w in conflict["warnings"]))
        # the claim changes again (the declaration is withdrawn): the exemption no longer holds
        self.with_applicability(h, None)
        self.assertEqual(self.state(h)["novelty"], "stale")
        self.assertFalse(self.rld.get_eligibility(h)["eligible"])


class EvidenceTest(S4Fixture):
    def test_reg_s4_03_cited_code_must_be_the_reviewed_version(self):
        h, exp, ev = self.candidate_node()
        code = self.rld.get(exp)["code_ref"]
        files = [f for f in rdb.subprocess.run(["git", "-C", str(self.repo), "ls-tree", "-r", "--name-only", code],
                                               capture_output=True, text=True).stdout.split()]
        cases = {
            "no such file": ["docs/evidence.md", "code/nonexistent.py"],
            "wrong version": ["docs/evidence.md", str(self.repo / files[0])],
        }
        (self.repo / files[0]).write_text("edited after the commit\n", encoding="utf-8")  # a working-tree change
        for why, paths in cases.items():
            with self.subTest(why):
                doc = self.rld.get(self.register(h, "method_code", receipt("method_code", "pass", paths=paths), ev))
                self.assertEqual(doc["effective_result"], "uncertain")
                self.assertTrue(any(w.startswith("EVIDENCE_UNVERIFIED") for w in doc["normalization_warnings"]))
        statuses = {m["cited"]: m["status"] for m in self.rld.get(self.rld.reviews()[-1]["id"])["evidence_manifest"]["paths"]}
        self.assertEqual(statuses[str(self.repo / files[0])], "wrong_version")
        # the same relative path at the research root and in the commit: ambiguous
        (self.root / files[0]).parent.mkdir(parents=True, exist_ok=True)
        (self.root / files[0]).write_text("a research file\n", encoding="utf-8")
        doc = self.rld.get(self.register(h, "method_code", receipt("method_code", "pass", paths=[files[0]]), ev))
        self.assertEqual((doc["effective_result"], doc["evidence_manifest"]["paths"][0]["status"]), ("uncertain", "ambiguous"))
        # the commit's file through the review's snapshot directory verifies; a doc-only method_code pass does not
        snapshot = self.root / "cache" / "reviews" / "code" / code
        snapshot.mkdir(parents=True)
        rdb.subprocess.run(f"git -C {self.repo} archive {code} | tar -x -C {snapshot}", shell=True, check=True)
        doc = self.rld.get(self.register(h, "method_code", receipt("method_code", "pass",
                                                                   paths=[str(snapshot / files[0])]), ev))
        self.assertEqual(doc["effective_result"], "pass")
        doc = self.rld.get(self.register(h, "method_code", receipt("method_code", "pass"), ev))
        self.assertEqual(doc["effective_result"], "uncertain")
        # a negative finding about a missing file is kept as it is
        doc = self.rld.get(self.register(h, "method_code", receipt("method_code", "fail", {"G": "fail"},
                                                                   paths=["code/nonexistent.py"]), ev))
        self.assertEqual(doc["effective_result"], "fail")


class FamilyTest(unittest.TestCase):
    def test_reg_s4_04_families_from_model_names(self):
        same = ["anthropic/claude-haiku-5-5", "openrouter/anthropic/claude-haiku-5-5", "claude-haiku-5-5",
                "bedrock/us.anthropic.claude-haiku-5-5-v1:0", "github-copilot/claude-haiku-5-5"]
        self.assertEqual({review_rules.family(m) for m in same}, {"anthropic"})
        self.assertTrue(all(review_rules.same_model(same[0], m) for m in same))
        aggregated = {"openrouter/openai/gpt-6-luna": "openai", "openrouter/google/gemini-3-pro": "google",
                      "openrouter/anthropic/claude-sonnet-5-5": "anthropic", "openrouter/deepseek/deepseek-v4": "deepseek"}
        self.assertEqual({m: review_rules.family(m) for m in aggregated}, aggregated)
        for unknown in ("openrouter/acme/foo-1", "azure/my-deployment", "", None):
            self.assertIsNone(review_rules.family(unknown))
        import review_call
        self.assertEqual(review_call.family("openrouter/anthropic/claude-haiku-5-5"), "anthropic")  # one table


class NoveltyTest(S4Fixture):
    def novelty(self, about: str, payload: dict, basis: dict, evaluation: str, session=None, **kw) -> str:
        return self.register(about, "novelty", payload, evaluation, session=session, basis=basis, **kw)

    def subject(self):
        h, exp = self.concluded()
        ev = self.rld.get(exp)["evaluation_id"]
        return h, ev, self.reviewer.review_basis(h, "candidate_recheck", "novelty", ev)

    def ask(self, queries):
        return {**receipt("novelty", "uncertain", {"H": "uncertain"}), "requested_queries": queries}

    def test_novelty_evidence_and_claim_identity_are_required_for_a_pass(self):
        h, ev, basis = self.subject()
        missing = self.rld.get(self.novelty(h, receipt("novelty", "pass", paths=["docs/missing-paper.md"]), basis, ev))
        self.assertEqual((missing["reported_result"], missing["review_result"]), ("pass", "uncertain"))
        self.assertTrue(any(w.startswith("EVIDENCE_UNVERIFIED") for w in missing["normalization_warnings"]))
        bound = self.rld.get(self.novelty(h, receipt("novelty", "pass"), basis, ev))
        self.assertEqual(bound["review_result"], "pass")
        self.rld.update_hypothesis(h, statement="a different claim")
        with self.rld.reader() as tx:
            self.assertFalse(self.rld._review_bound(tx, bound, h, "novelty", ev))
        with self.assertRaisesRegex(ResearchDBError, "REVIEW_INVALID"):
            self.novelty(h, {"verdict": "ABANDON", "score": 2}, basis, ev)

    def test_follow_up_once_repeats_neither_search_nor_model_cost(self):
        h, ev, basis = self.subject()
        ask = self.ask(["heavy ball momentum fixed budget", "polyak momentum toy"])
        first = self.novelty(h, ask, basis, ev, session="RV-0100")
        cost = self.rld.get("P-test")["review_cost_usd"]
        path = self.rld.get(first)["path"]
        again = self.reviewer.register_review(path, "novelty", "candidate_recheck", [h], "uncertain", "RV-0100",
            "pi", "openai/gpt-6-astra", 0.01, dimension="novelty", evaluation_id=ev, basis=basis, payload=ask)
        self.assertEqual((again, self.rld.get("P-test")["review_cost_usd"]), (first, cost))
        calls = []
        def search(query, sources=None, limit=10):
            calls.append(query)
            return [{"title": f"found for {query}", "source": "arxiv"}]
        with mock.patch("literature.search", search):
            one = self.rld.literature_followup(first)
            two = self.rld.literature_followup(first)
        self.assertEqual(calls, ask["requested_queries"])
        self.assertEqual(one["sha256"], two["sha256"])
        self.assertTrue(all(e["reused"] for e in two["entries"]))
        manifest = json.loads((self.root / one["manifest"]).read_text())
        self.assertEqual([q["status"] for q in manifest["queries"]], ["done", "done"])
        follow = self.novelty(h, self.ask(["one more"]), basis, ev, session="RV-0100", parent_review_id=first,
                              evidence_set={"path": one["manifest"], "sha256": one["sha256"]})
        self.assertEqual(self.rld.get(follow)["parent_review_id"], first)
        with self.assertRaisesRegex(ResearchDBError, "FOLLOWUP_LIMIT"):
            self.rld.literature_followup(follow)

    def test_subject_remains_fixed_during_follow_up(self):
        import review_call
        h, ev, basis = self.subject()
        first = self.novelty(h, self.ask(["heavy ball momentum fixed budget"]), basis, ev)
        with mock.patch("literature.search", lambda q, s=None, limit=10: []):
            done = self.rld.literature_followup(first)
        self.doc(self.worker, "literature/LIT-unrelated.v1.md", "literature")
        self.assertEqual(self.reviewer.review_basis(h, "candidate_recheck", "novelty", ev), basis)
        evidence = review_call.followup_evidence(self.root, self.db, done["manifest"], "candidate_recheck", h, basis)
        self.assertEqual(evidence["parent_review_id"], first)
        with self.assertRaisesRegex(review_call.ReviewError, "not a candidate_recheck review of"):
            review_call.followup_evidence(self.root, self.db, done["manifest"], "candidate_recheck", "H-9999", basis)

        self.rld.update_hypothesis(h, statement="changed during the follow-up")
        current = self.reviewer.review_basis(h, "candidate_recheck", "novelty", ev)
        with self.assertRaisesRegex(review_call.ReviewError, "the subject changed"):
            review_call.followup_evidence(self.root, self.db, done["manifest"], "candidate_recheck", h, current)
        late = self.novelty(h, receipt("novelty", "pass"), basis, ev, parent_review_id=first)
        self.assertTrue(self.rld.get(late)["review_basis_changed"])


class ClosureTest(S4Fixture):
    def test_reg_s4_08_fail_resubmit_fix_resolve(self):
        h, exp, ev = self.candidate_node()
        self.all_pass(h, ev, skip=("numbers",))
        failing = receipt("numbers", "fail", {"C": "fail"})
        first = self.register(h, "numbers", failing, ev, session="RV-0200")
        (ob,) = self.rld.obligations(about=h, status="OPEN")
        # the same receipt again: as the same file, and as a new version of its session — nothing new
        again = self.reviewer.register_review(self.rld.get(first)["path"], "recheck numbers", "candidate_recheck", [h],
                                              "fail", "RV-0200", "pi", "openai/gpt-6-astra", 0.01, dimension="numbers",
                                              evaluation_id=ev, payload=failing,
                                              basis=self.reviewer.review_basis(h, "candidate_recheck", "numbers", ev))
        self.assertEqual(again, first)
        self.register(h, "numbers", failing, ev, session="RV-0200")
        self.assertEqual(len(self.rld.get(ob["id"])["findings"]["items"]), 1)
        self.assertEqual(len(self.rld.obligations(about=h)), 1)
        # an independent receipt with the same finding is appended to the same issue
        independent = self.register(h, "numbers", failing, ev, session="RV-0201")
        self.assertEqual([i["review_id"] for i in self.rld.get(ob["id"])["findings"]["items"]], [first, independent])
        # another open issue elsewhere
        self.register(h, "protocol", receipt("protocol", "fail", {"P3": "fail"}), ev)
        other = next(o for o in self.rld.obligations(about=h, status="OPEN") if o["pattern"] == "protocol:P3")
        # unrelated evidence does not close it: a file, a run's evaluation, another dimension's pass, its own receipt
        unrelated_pass = self.register(h, "theory", recheck_payload(self, "theory", "pass", ev), ev)
        for evidence in ("docs/evidence.md", ev, unrelated_pass, first):
            with self.assertRaisesRegex(ResearchDBError, "OBLIGATION_EVIDENCE_MISMATCH"):
                self.rld.resolve_obligation(ob["id"], "corrected_from_results", evidence)
        # a new review that still fails C keeps it open; a real pass of C closes it explicitly
        still = self.register(h, "numbers", receipt("numbers", "fail", {"C": "fail"}), ev, session="RV-0202")
        with self.assertRaisesRegex(ResearchDBError, "OBLIGATION_EVIDENCE_MISMATCH"):  # it repeats the finding
            self.rld.resolve_obligation(ob["id"], "corrected_from_results", still)
        fixed = self.register(h, "numbers", recheck_payload(self, "numbers", "pass", ev), ev)
        self.assertIn("OBLIGATION_OPEN", self.rld.get_eligibility(h)["reasons"])  # a pass alone closes nothing
        self.rld.resolve_obligation(ob["id"], "corrected_from_results", fixed)
        self.assertEqual(self.rld.get(ob["id"])["status"], "RESOLVED")
        state = self.rld.get_eligibility(h)
        self.assertIn("OBLIGATION_OPEN", state["reasons"])  # the protocol issue is still open
        self.assertEqual(state["open_obligations"], [other["id"]])
        # the old fail delivered again does not reopen the resolved issue
        self.reviewer.register_review(self.rld.get(first)["path"], "recheck numbers", "candidate_recheck", [h], "fail",
                                      "RV-0200", "pi", "openai/gpt-6-astra", 0.01, dimension="numbers",
                                      evaluation_id=ev, payload=failing,
                                      basis=self.reviewer.review_basis(h, "candidate_recheck", "numbers", ev))
        self.register(h, "numbers", failing, ev, session="RV-0200")
        self.assertEqual(self.rld.get(ob["id"])["status"], "RESOLVED")
        # claim_narrowed needs a newer claim revision
        self.register(h, "protocol", recheck_payload(self, "protocol", "pass", ev), ev)
        passing_protocol = self.rld.reviews()[-1]["id"]
        with self.assertRaisesRegex(ResearchDBError, "claim_narrowed needs a newer claim revision"):
            self.rld.resolve_obligation(other["id"], "claim_narrowed", passing_protocol)
        self.rld.resolve_obligation(other["id"], "re_evaluated", passing_protocol)
        self.register(h, "numbers", recheck_payload(self, "numbers", "pass", ev), ev)
        code_bound = {r["dimension"]: r["review_id"] for r in self.rld.get_eligibility(h)["rechecks"]
                      if r["dimension"] not in ("numbers", "protocol")}
        confirmation = self.complete_confirmation(h, exp, review=False)
        for dimension in ("numbers", "protocol"):
            self.register(h, dimension, recheck_payload(self, dimension, "pass", confirmation), confirmation)
        final = self.rld.get_eligibility(h)
        self.assertTrue(final["eligible"], final)
        self.assertEqual({r["dimension"]: r["review_id"] for r in final["rechecks"]
                          if r["dimension"] in code_bound}, code_bound)
        self.assertEqual(self.rld.get(ob["id"])["resolution"]["evidence_id"], fixed)
        self.assertEqual(self.rld.get(other["id"])["resolution"]["evidence_id"], passing_protocol)


class UnsupportedHistoryTest(S4Fixture):
    def test_unbound_receipts_fail_closed_and_no_migration_api_exists(self):
        h, exp, ev = self.candidate_node()
        self.complete_confirmation(h, exp)
        self.assertTrue(self.rld.get_eligibility(h)["eligible"])
        docs = {d["review_dimension"]: d["id"] for d in self.rld.reviews(kind="candidate_recheck")}
        for doc in docs.values():
            self.raw(doc, effective_result=None)
        self.raw(docs["numbers"], review_result="fail")
        before = self.rld.export_snapshot()
        self.assertFalse(hasattr(self.rld, "migrate_reviews"))
        rows = {r["dimension"]: r for r in self.rld.get_eligibility(h)["rechecks"]}
        self.assertTrue(all(r["needs_recheck"] and r["state"] == "stale" for r in rows.values()))
        self.assertFalse(self.rld.get_eligibility(h)["eligible"])
        self.assertEqual(self.rld.export_snapshot(), before)


if __name__ == "__main__":
    unittest.main()
