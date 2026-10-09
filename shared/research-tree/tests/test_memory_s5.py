"""S5 (plans/research-tree-implementation-and-real-scenarios.md §9.5): a lesson's fix is verified only by the records
of a real failure, a criterion frozen first, the verifying attempts and fixed checkers; every reader gets the same
memory_status; findings and lessons lose current support when their sources change. REG-S5-01..07. The runs are
REG fixtures, not measurements."""

from __future__ import annotations

import json
import sys
import time
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))

from test_research_db import Fixture, ResearchDB, ResearchDBError, rdb  # noqa: E402

CHECKS = [{"id": "C1", "type": "exit_status"}, {"id": "C2", "type": "import_valid"},
          {"id": "C3", "type": "launch_config", "field": "data_dir", "expected": "data/good"},
          {"id": "C4", "type": "read_count", "field": "n_val", "expected": 400},
          {"id": "C5", "type": "artifacts_match_manifest"}]


def lesson_text(verification: dict | None, status: str = "verified", root: str = "unknown", extra: dict | None = None,
                symptom: str = "FileNotFoundError: data/missing/train.jsonl when the run starts",
                fix: str = "launch with data_dir data/good") -> str:
    head = {"kind": "execution_lesson", "symptom": symptom, "root_cause": "the launch named a directory that is "
            "not in the checkout", "root_cause_status": root, "fix": fix, "status": status,
            "applicability": {"harness_ref": "HARNESS"}}
    if verification is not None:
        head["fix_verification"] = verification
    head.update(extra or {})
    return "---\n" + json.dumps(head, ensure_ascii=False) + "\n---\n\n# lesson\n"


class S5Fixture(Fixture):
    def setUp(self):
        super().setUp()
        h = self.hypothesis()
        self.start(h)
        self.h = h
        self.exp = self.method(h, n_seeds=1)
        self.run = f"{self.exp}/s42"

    def criterion(self, checks=CHECKS) -> str:
        body = "".join(f"## {name}\n\n未知\n\n" for name in rdb.TASK_SECTIONS["task_request"])
        body += "## 检查项\n\n```json\n" + json.dumps({"checks": checks}) + "\n```\n"
        return self.doc(self.rld, f"tasks/check-{self.n}.v1.md", "task_request", body=body)

    def fail_then_fix(self, data_dir: str = "data/good", checks=CHECKS) -> tuple[str, str]:
        """attempt 1 fails with a log; the criterion is frozen; attempt 2 runs with data_dir and is imported."""
        self.worker.create_run(self.exp, 42)
        self.worker.update_run(self.run, exec_status="submitted")
        log = self.root / "outputs" / self.exp / "s42" / "fail.log"
        log.parent.mkdir(parents=True, exist_ok=True)
        log.write_text("FileNotFoundError: data/missing/train.jsonl\n")
        self.worker.update_run(self.run, exec_status="failed", log_path=f"outputs/{self.exp}/s42/fail.log")
        criterion = self.criterion(checks)
        self.worker.update_run(self.run, attempt=2, exec_status="submitted", started_at=rdb.now_utc())
        self.worker.update_run(self.run, exec_status="succeeded")
        config = {**(self.rld.get(self.exp).get("effective_config") or {"lr": 0.05}), "data_dir": data_dir}
        self.worker.import_run_result(self.run, 2, self.manifest(self.exp, 42, attempt=2, config=config))
        self.worker.update_run(self.run, valid=True)
        return criterion, f"{self.run}@2"

    def verification(self, criterion: str, verified: str, **over) -> dict:
        v = {"failure_attempt_ref": f"{self.run}@1", "criterion_doc_id": criterion, "run_attempt_refs": [verified],
             "applied_fix_ref": {"kind": "execution_config", "field": "data_dir", "expected": "data/good"},
             "check_evidence_refs": [{"check": c["id"], "run": verified} for c in CHECKS]}
        v.update(over)
        return v

    def lesson(self, text: str) -> str:
        text = text.replace("HARNESS", self.rld.get("P-test")["harness_ref"])
        doc = self.doc(self.worker, f"lessons/lesson-{self.n}.v1.md", "lesson", current=False, body=text)
        self.worker.set_document_current(doc)
        return doc


class VerificationTest(S5Fixture):
    def test_reg_s5_01_03_an_oom_or_path_symptom_with_a_verified_fix_and_unknown_cause(self):
        criterion, verified = self.fail_then_fix()
        doc = self.lesson(lesson_text(self.verification(criterion, verified)))
        status = self.rld.memory_status(doc)
        self.assertEqual((status["declared_status"], status["effective_status"], status["root_cause_status"]),
                         ("verified", "verified", "unknown"))  # the fix is verified; the cause stays unknown
        self.assertEqual(self.rld.get(doc)["memory_basis"]["verification"]["state"], "verified")
        self.assertTrue(all(c["passed"] for c in self.rld.get(doc)["memory_basis"]["verification"]["checks"]))
        oom = self.lesson(lesson_text(None, status="proposed", symptom="CUDA out of memory (OOM) at batch 64",
                                      fix="use batch 32 on this GPU"))
        self.assertEqual(self.rld.memory_status(oom)["effective_status"], "proposed")
        bad = self.doc(self.worker, "lessons/never.v1.md", "lesson", current=False,
                       body=lesson_text(None, status="proposed", fix="never use the pi backend"))
        with self.assertRaisesRegex(ResearchDBError, "permanent rule against a tool"):
            self.worker.set_document_current(bad)
        pack = self.rld.context_pack(self.h)
        row = next(x for x in pack["lessons"] if x["id"] == doc)
        self.assertEqual((row["status"], row["root_cause_status"]), ("verified", "unknown"))
        self.assertIn("根因未确定", pack["text"])

    def test_reg_s5_02_unfinished_or_withdrawn_attempts_do_not_verify(self):
        criterion, verified = self.fail_then_fix()
        other = self.method(self.h, n_seeds=1)
        planned = f"{other}/s42"
        self.worker.create_run(other, 42)  # planned, never run
        cases = {"planned": f"{planned}@1", "the failed attempt": f"{self.run}@1", "nonexistent": f"{self.run}@9"}
        for why, ref in cases.items():
            with self.subTest(why):
                v = self.verification(criterion, ref, check_evidence_refs=[{"check": c["id"], "run": ref} for c in CHECKS])
                doc = self.lesson(lesson_text(v))
                self.assertEqual(self.rld.memory_status(doc)["effective_status"], "unverified")
        for state in ("running", "unknown"):
            exp = self.method(self.h, n_seeds=1)
            self.worker.create_run(exp, 42)
            self.worker.update_run(f"{exp}/s42", exec_status="submitted")
            self.worker.update_run(f"{exp}/s42", exec_status=state)
            ref = f"{exp}/s42@1"
            doc = self.lesson(lesson_text(self.verification(criterion, ref, check_evidence_refs=[
                {"check": c["id"], "run": ref} for c in CHECKS])))
            self.assertEqual(self.rld.memory_status(doc)["effective_status"], "unverified", state)
        # the verifying attempt is retracted later: the lesson no longer counts as verified
        doc = self.lesson(lesson_text(self.verification(criterion, verified)))
        self.assertEqual(self.rld.memory_status(doc)["effective_status"], "verified")
        self.rld.retract_run(self.run, "the data directory was a stale copy", self.decision_doc())
        status = self.rld.memory_status(doc)
        self.assertEqual(status["effective_status"], "unverified")
        self.assertTrue(any("retracted" in r for r in status["recheck_reasons"]))

    def test_reg_s5_04_an_unrelated_run_a_mismatch_or_a_self_report_does_not_verify(self):
        criterion, verified = self.fail_then_fix(data_dir="data/other")  # the fix was not what ran
        mismatch = self.lesson(lesson_text(self.verification(criterion, verified)))
        reasons = self.rld.memory_status(mismatch)["recheck_reasons"]
        self.assertTrue(any("not the fix" in r for r in reasons), reasons)
        # an unrelated successful run (the SOTA's) with no failure of its own
        sota_run = f"{self.sota}/s42@1"
        unrelated = self.lesson(lesson_text(self.verification(criterion, sota_run, check_evidence_refs=[
            {"check": c["id"], "run": sota_run} for c in CHECKS])))
        self.assertEqual(self.rld.memory_status(unrelated)["effective_status"], "unverified")
        # self-reported booleans are ignored
        selfish = self.lesson(lesson_text(None, status="verified", root="verified",
                                          extra={"evidence_runs": [verified], "fix_applied": True, "checks_passed": True}))
        status = self.rld.memory_status(selfish)
        self.assertEqual(status["effective_status"], "unverified")
        self.assertEqual(self.rld.get(selfish)["memory_basis"]["verification"]["ignored_self_reports"],
                         ["checks_passed", "fix_applied"])
        # an unknown check type stays unverified; a criterion written after the run started is not frozen first
        time.sleep(1.1)  # timestamps have one-second resolution: this criterion is written after the run started
        weird = self.criterion([{"id": "C9", "type": "custom_python", "code": "print(1)"}])
        doc = self.lesson(lesson_text(self.verification(weird, verified, check_evidence_refs=[{"check": "C9", "run": verified}])))
        self.assertTrue(any("unknown check type" in r for r in self.rld.memory_status(doc)["recheck_reasons"]))
        self.assertTrue(any("written after" in r for r in self.rld.memory_status(doc)["recheck_reasons"]))

    def test_reg_s5_04_checkers_read_the_artifacts(self):
        criterion, verified = self.fail_then_fix()
        doc = self.lesson(lesson_text(self.verification(criterion, verified)))
        manifest = self.root / self.rld.get(self.run)["manifest_path"]
        metrics_file = manifest.parent / "metrics.json"
        metrics_file.write_text(metrics_file.read_text().replace("70.", "71."))  # the artifact changed after import
        reasons = self.rld.memory_status(doc)["recheck_reasons"]
        self.assertTrue(any("C5" in r and "differ" in r for r in reasons), reasons)


class CurrencyTest(S5Fixture):
    def test_reg_s5_05_sources_change_and_both_packs_say_so(self):
        criterion, verified = self.fail_then_fix()
        lesson = self.lesson(lesson_text(self.verification(criterion, verified)).replace(
            '"applicability": {"harness_ref": "HARNESS"}', '"applicability": {"data_layout": "toy-v1"}'))
        ev = self.rld.get(self.sota)["evaluation_id"]
        finding = self.doc(self.rld, "findings/f.v1.md", "finding", current=False, about=(self.h,), body=(
            f"---\nkind: finding\nclaim: \"the reference reaches 70\"\nevidence_ids: [{ev}]\n"
            "interpretation: \"the toy task is easy\"\nlimitations: \"one setting\"\nstatus: supported\n---\n"))
        self.rld.set_document_current(finding)
        self.assertEqual(self.rld.memory_status(finding)["effective_status"], "supported")
        self.rld.update_project(harness_ref=self.commit({"harness/stats.py": "stats v2\n"}), harness_paths=["harness"])
        for role, actor in (("rld", self.rld), ("worker", self.worker)):
            pack = actor.context_pack(self.h, role=role)
            row = next(f for f in pack["findings"] if f["id"] == finding)
            self.assertEqual((row["status"], row["declared_status"], row["source_refs"]), ("stale", "supported", [ev]))
            self.assertTrue(row["recheck_reasons"])
            self.assertIn("待复核", pack["text"])
            kept = next(x for x in pack["lessons"] if x["id"] == lesson)
            self.assertEqual(kept["status"], "verified")  # a harness change outside the lesson's scope: still verified
        self.assertIn("finding", json.dumps(self.rld.resume_package(self.h), ensure_ascii=False))

    def test_reg_s5_06_scope_and_budget(self):
        old = self.lesson(lesson_text(None, status="proposed").replace("HARNESS", "0" * 40))  # another harness
        scopeless = self.lesson(lesson_text(None, status="proposed").replace(
            ', "applicability": {"harness_ref": "HARNESS"}', ""))
        countered = self.lesson(lesson_text(None, status="proposed", extra={"counterexamples": ["E-0009 ran fine without it"]}))
        pack = self.rld.context_pack(self.h)
        rows = {x["id"]: x for x in pack["lessons"]}
        self.assertTrue(any("harness_ref" in r for r in rows[old]["recheck_reasons"]))
        self.assertTrue(any("scope not stated" in r for r in rows[scopeless]["recheck_reasons"]))
        self.assertEqual(rows[countered]["counterexamples"], ["E-0009 ran fine without it"])
        self.rld.update_project(memory_pack_limit=1200)
        small = self.rld.context_pack(self.h)
        size = len(small["text"]) + len(json.dumps({"lessons": small["lessons"], "findings": small["findings"]},
                                                   ensure_ascii=False))
        self.assertLessEqual(size, 1200)
        self.assertTrue(small["truncated"])


class MigrationTest(S5Fixture):
    def test_reg_s5_07_old_labels_are_not_trusted_and_migration_is_idempotent(self):
        criterion, verified = self.fail_then_fix()
        good = self.lesson(lesson_text(self.verification(criterion, verified)))
        label_only = self.lesson(lesson_text(None, status="verified", root="verified",
                                             extra={"evidence_runs": [verified]}))
        for doc in (good, label_only):
            self.raw(doc, memory_basis=None)  # as recorded before S5
        self.assertEqual(self.rld.memory_status(good)["evidence_state"], "legacy")
        self.assertEqual(self.rld.memory_status(label_only)["effective_status"], "unverified")
        report = self.rld.migrate_memory(dry_run=False)
        self.assertEqual((report["derived"], report["legacy"]), ([good], [label_only]))
        self.assertEqual(self.rld.memory_status(good)["effective_status"], "verified")
        self.assertEqual(self.rld.memory_status(label_only)["evidence_state"], "legacy")
        again = self.rld.migrate_memory(dry_run=False)
        self.assertEqual(again, {"derived": [], "legacy": []})
        # the same verifying attempt named twice is one verification
        twice = self.lesson(lesson_text(self.verification(criterion, verified, run_attempt_refs=[verified, verified])))
        self.assertEqual(self.rld.get(twice)["memory_basis"]["verification"]["runs"], [verified])


if __name__ == "__main__":
    unittest.main()
