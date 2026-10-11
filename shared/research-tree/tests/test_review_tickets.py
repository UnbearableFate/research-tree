"""R05/R13 regressions: only fake backends, persistent review tickets and local validation."""
from __future__ import annotations

import json
import os
import threading
import unittest
from contextlib import ExitStack
from types import SimpleNamespace
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from unittest.mock import Mock, patch

import test_review_call as fixture
from test_review_call import NOVELTY, block

import review_call
import test_research_db as dbfixture


class ReviewTicketTest(unittest.TestCase):
    project = fixture.ReviewCallTest.project
    fake = fixture.ReviewCallTest.fake
    calls = fixture.ReviewCallTest.calls

    def setUp(self):
        fixture.ReviewCallTest.setUp(self)
        def reap():
            for process in list(review_call._JOB_CHILDREN.values()):
                process.wait(timeout=10)
            review_call._JOB_CHILDREN.clear()
        reap()
        self.addCleanup(reap)
        self.project()
        self.argv = ["--kind", "novelty_precheck", "--brief", self.brief, "--about", "P-r"]
        self.proc = Mock(pid=os.getpid())
        self.proc.poll.return_value = None

    def pending(self):
        with patch.object(review_call.subprocess, "Popen", return_value=self.proc):
            return review_call.start_job(self.cwd, self.root, self.argv)

    def test_start_is_local_and_identical_requests_share_one_ticket(self):
        with patch.object(review_call, "backend_for", side_effect=AssertionError("backend on start")), \
                patch.object(review_call.subprocess, "Popen", return_value=self.proc) as spawn:
            first = review_call.start_job(self.cwd, self.root, self.argv)
            second = review_call.start_job(self.cwd, self.root, [*self.argv, "--wait-s", "40"])
            self.assertEqual(first, second)
            self.assertEqual(spawn.call_count, 1)
            job = review_call.wait_job(self.root, first, 0)
        self.assertEqual((job["status"], job["phase"]), ("running", "queued"))
        self.assertEqual(job["request"]["basis"], {"subject": "P-r"})
        self.assertTrue(review_call._job_answer(job)[0]["pending"])

    def test_concurrent_starts_are_deduplicated_under_the_job_lock(self):
        with patch.object(review_call.subprocess, "Popen", return_value=self.proc) as spawn, \
                ThreadPoolExecutor(max_workers=5) as pool:
            tickets = list(pool.map(lambda _: review_call.start_job(self.cwd, self.root, self.argv), range(5)))
        self.assertEqual(len(set(tickets)), 1)
        self.assertEqual(spawn.call_count, 1)
        self.assertEqual(len(review_call.list_jobs(self.root)), 1)

    def test_spawn_failure_is_persisted_and_never_silently_repaid(self):
        with patch.object(review_call.subprocess, "Popen", side_effect=OSError("process limit")) as spawn:
            first = review_call.start_job(self.cwd, self.root, self.argv)
            second = review_call.start_job(self.cwd, self.root, self.argv)
        self.assertEqual(first, second)
        self.assertEqual(spawn.call_count, 1)
        one = review_call.wait_job(self.root, first, 0)
        self.assertEqual(one, review_call.wait_job(self.root, first, 0))
        self.assertEqual(one["phase"], "spawn_failed")
        self.assertIn("no model was called", one["answer"]["error"])

    def test_fingerprint_binds_brief_basis_configuration_and_model(self):
        with patch.object(review_call.subprocess, "Popen", return_value=self.proc):
            first = review_call.start_job(self.cwd, self.root, self.argv)
            (self.root / self.brief).write_text("# revised brief\n")
            changed_brief = review_call.start_job(self.cwd, self.root, self.argv)
            config = self.cwd / "research-tree.yaml"
            config.write_text(config.read_text().replace("thinking: high", "thinking: medium"))
            changed_config = review_call.start_job(self.cwd, self.root, self.argv)
            config.write_text(config.read_text().replace("model: openai/gpt-6-astra", "model: anthropic/claude-sonnet-5-5"))
            changed_model = review_call.start_job(self.cwd, self.root, self.argv)
            with patch.object(review_call.ResearchDB, "review_basis", return_value={"subject": "P-r", "revision": 2}):
                changed_basis = review_call.start_job(self.cwd, self.root, self.argv)
                again = review_call.start_job(self.cwd, self.root, self.argv)
        self.assertEqual(len({first, changed_brief, changed_config, changed_model, changed_basis}), 5)
        self.assertEqual(changed_basis, again)

    def test_changed_inputs_between_start_and_dispatch_fail_before_backend(self):
        ticket = self.pending()
        (self.root / self.brief).write_text("changed after enqueue\n")
        with patch.object(review_call, "backend_for", side_effect=AssertionError("must fail locally")):
            review_call._run_job(self.cwd, self.root, ticket)
        answer = review_call.wait_job(self.root, ticket, 0)["answer"]
        self.assertFalse(answer["ok"])
        self.assertIn("changed after the ticket", answer["error"])
        self.assertEqual(review_call.spent(self.root), 0)

    def test_unexpected_errors_and_interruptions_are_collectable(self):
        for failure in (RuntimeError("crashed"), KeyboardInterrupt("interrupted")):
            with self.subTest(failure=type(failure).__name__):
                (self.root / self.brief).write_text(type(failure).__name__)
                ticket = self.pending()
                with patch.object(review_call, "_call", side_effect=failure) as call:
                    review_call._run_job(self.cwd, self.root, ticket)
                    review_call._run_job(self.cwd, self.root, ticket)
                    self.assertEqual(call.call_count, 1)
                answer = review_call.wait_job(self.root, ticket, 0)["answer"]
                self.assertFalse(answer["ok"])
                self.assertIn(type(failure).__name__, answer["error"])

    def test_dead_worker_is_terminal_and_repeated_start_cannot_restart_it(self):
        ticket = self.pending()
        with patch.object(review_call, "_process_alive", return_value=False):
            job = review_call.wait_job(self.root, ticket, 0)
        self.assertEqual(job["phase"], "interrupted")
        self.assertTrue(job["answer"]["recovery_required"])
        with patch.object(review_call.subprocess, "Popen", side_effect=AssertionError("duplicate spawn")):
            self.assertEqual(review_call.start_job(self.cwd, self.root, self.argv), ticket)
        with patch.object(review_call, "_call", side_effect=AssertionError("duplicate paid call")):
            review_call._run_job(self.cwd, self.root, ticket)
        self.assertEqual(job, review_call.wait_job(self.root, ticket, 0))

    def test_orphan_session_is_recovered_by_ticket_ownership_before_pointer_publication(self):
        ticket = self.pending()
        # Reproduce SIGKILL after _allocate persists ownership, before _update_job publishes the pointer.
        with review_call._Lock(self.root):
            session, _, version, _, _ = review_call._allocate(self.root, None, "novelty_precheck", "P-r", "pi", ticket)
            other, _, _, _, _ = review_call._allocate(self.root, None, "novelty_precheck", "P-r", "pi", "RJ-ffffffffffff")
        review_call._update_job(self.root, ticket, worker_started_at=review_call.now())
        pending = review_call._read_job(self.root, ticket)
        self.assertNotIn("session", pending)
        self.assertTrue(review_call._sessions(self.root)[session]["busy"])
        with patch.object(review_call, "backend_for", side_effect=AssertionError("recovery cannot call a model")), \
                patch.object(review_call.subprocess, "Popen", side_effect=AssertionError("recovery cannot spawn")):
            recovered = review_call.wait_job(self.root, ticket, 0)
            self.assertEqual(review_call.start_job(self.cwd, self.root, self.argv), ticket)
            self.assertEqual(review_call.wait_job(self.root, ticket, 0), recovered)
        self.assertEqual((recovered["status"], recovered["phase"]), ("done", "interrupted"))
        self.assertEqual((recovered["session"], recovered["version"]), (session, version))
        states = review_call._sessions(self.root)
        self.assertFalse(states[session]["busy"])
        self.assertIsNone(states[session]["active_ticket"])
        self.assertTrue(states[other]["busy"])  # another job's reservation is untouched
        with review_call._Lock(self.root):
            _, _, next_version, _, _ = review_call._allocate(self.root, session, "novelty_precheck", "P-r", "pi")
        self.assertEqual(next_version, version + 1)

    def test_worker_lease_prevents_duplicate_dispatch_and_collection_is_nonblocking(self):
        ticket = self.pending()
        entered, release = threading.Event(), threading.Event()
        answer = {"ok": False, "error": "test-only completed call"}

        def call(*args, **kwargs):
            entered.set()
            if not release.wait(10):
                raise AssertionError("test worker was not released")
            return answer, 2

        with patch.object(review_call, "_call", side_effect=call) as mocked, ThreadPoolExecutor(max_workers=2) as pool:
            first = pool.submit(review_call._run_job, self.cwd, self.root, ticket)
            try:
                self.assertTrue(entered.wait(10))
                second = pool.submit(review_call._run_job, self.cwd, self.root, ticket)
                self.assertEqual(second.result(timeout=3), 0)
                self.assertEqual(review_call.wait_job(self.root, ticket, 0)["status"], "running")
                self.assertEqual(mocked.call_count, 1)
            finally:
                release.set()
            first.result(timeout=5)
        self.assertEqual(review_call.wait_job(self.root, ticket, 0)["answer"], answer)

    def test_registered_receipt_survives_interruption_before_terminal_ticket_write(self):
        self.fake("pi")
        with patch.dict(os.environ, {**self.env, "FAKE_ANSWERS": json.dumps([{"text": block(NOVELTY)}])}):
            ticket = review_call.start_job(self.cwd, self.root, self.argv)
            complete = review_call.wait_job(self.root, ticket, 30)
        self.assertTrue(complete["answer"]["ok"], complete)
        self.assertEqual(review_call.start_job(self.cwd, self.root, self.argv), ticket)
        # Reproduce the crash boundary: DB receipt committed, no final job answer or success log yet.
        interrupted = {k: v for k, v in complete.items() if k not in ("answer", "finished_at")}
        interrupted.update(status="running", phase="reviewing")
        review_call._atomic_json(review_call._job_file(self.root, ticket), interrupted)
        log = self.root / review_call.CALL_LOG
        lines = [json.loads(line) for line in log.read_text().splitlines()]
        log.write_text("".join(json.dumps(line) + "\n" for line in lines if line.get("outcome") != "ok"))
        snapshot = self.rld.export_snapshot()
        # Session index can also lag a committed receipt; recover its pointer without a second call.
        sessions = review_call._sessions(self.root)
        sessions[complete["session"]].update(version=0, doc_id=None, busy=False)
        review_call._save_sessions(self.root, sessions)
        recovered = review_call.wait_job(self.root, ticket, 0)
        self.assertEqual(recovered["phase"], "recovered")
        self.assertEqual(recovered["answer"], complete["answer"])
        self.assertEqual(recovered, review_call.wait_job(self.root, ticket, 0))
        self.assertEqual(snapshot, self.rld.export_snapshot())
        state = review_call._sessions(self.root)[complete["session"]]
        self.assertEqual((state["version"], state["doc_id"]), (complete["version"], complete["answer"]["result"]["review_id"]))
        self.assertAlmostEqual(review_call.spent(self.root), complete["answer"]["result"]["cost_usd"])
        self.assertEqual(len([c for c in self.calls() if "-p" in c]), 1)

    def test_atomic_write_failure_preserves_previous_complete_state(self):
        ticket = self.pending()
        path = review_call._job_file(self.root, ticket)
        before = path.read_bytes()
        with patch.object(Path, "replace", side_effect=OSError("interrupted write")), self.assertRaises(OSError):
            review_call._atomic_json(path, {"incomplete": "must never replace a valid ticket"})
        self.assertEqual(path.read_bytes(), before)
        self.assertFalse(list(path.parent.glob(f".{path.name}.*.tmp")))

    def test_invalid_subjects_and_dimensions_fail_before_backend_or_dispatch(self):
        for params in ({"about": "H-9999"}, {"kind": "code_review", "code_ref": "bad"},
                       {"dimension": "numbers"}):
            with self.subTest(params=params), patch.object(review_call, "backend_for") as backend, \
                    patch.object(review_call.subprocess, "Popen") as spawn:
                request = {"kind": "novelty_precheck", "brief": self.brief, "about": "P-r", **params}
                argv = [part for key, value in request.items() for part in ("--" + key.replace("_", "-"), value)]
                with self.assertRaises(review_call.ReviewError):
                    review_call.start_job(self.cwd, self.root, argv)
                backend.assert_not_called()
                spawn.assert_not_called()
        self.assertEqual(review_call.spent(self.root), 0)
        self.assertEqual(self.rld.reviews(), [])


class ReviewSubjectTest(dbfixture.Fixture):
    def setUp(self):
        super().setUp()
        self.hyp = self.hypothesis()
        self.start(self.hyp)
        self.exp = self.method(self.hyp)
        self.code = self.rld.get(self.exp)["code_ref"]
        self.brief = "docs/reviews/briefs/local.v1.md"
        (self.root / self.brief).parent.mkdir(parents=True, exist_ok=True)
        (self.root / self.brief).write_text("Read the exact method and its hypothesis.\n")
        reviewer = {"model": "openai/gpt-6-astra", "thinking": "high", "timeout_s": 60,
                    "require_cross_family": False}
        self.backend = SimpleNamespace(name="pi", precheck=Mock(), call=Mock())
        stack = self.enterContext(ExitStack())
        stack.enter_context(patch.object(review_call.tree, "read_marker", return_value={"root": str(self.root), "db": str(self.db)}))
        stack.enter_context(patch.object(review_call.tree, "show_config", return_value={"effective": {"models": {"reviewer": reviewer}}}))
        self.factory = stack.enter_context(patch.object(review_call, "backend_for", return_value=self.backend))

    def response(self, implemented=True):
        data = {"issues": [], "method_implemented": implemented}
        self.backend.call.return_value = ({"ok": True, "structured": data, "text": block(data), "cost_usd": 0.01,
                "provider": "openai", "model_observed": "openai/gpt-6-astra", "terminal_reason": "stop",
                "permission_denials": [], "usage": {}}, "fake raw output")

    def review(self, **kwargs):
        return review_call.review(self.root, "code_review", self.brief, self.exp, code_ref=self.code, **kwargs)

    def test_experiment_review_binds_exact_method_and_claim_and_is_applicable(self):
        self.response()
        result = self.review()
        receipt, experiment, hypothesis = self.rld.get(result["review_id"]), self.rld.get(self.exp), self.rld.get(self.hyp)
        basis = receipt["review_basis"]
        self.assertEqual(basis["experiment_id"], self.exp)
        self.assertEqual(basis["hypothesis_id"], self.hyp)
        self.assertEqual(basis["method_spec_doc_ids"], [experiment["method_spec_doc_id"]])
        self.assertEqual((basis["claim_sha"], basis["claim_revision"]), (hypothesis["claim_sha"], hypothesis["claim_revision"]))
        design = self.doc(self.worker, "exp/other/design.v1.md", "experiment_design")
        other = self.worker.create_experiment("method", "other config", design, self.code, 1, 1800,
                    hypothesis_id=self.hyp, method_config={"lr": 0.2}, estimated_node_h=1.0)
        with self.rld.reader() as tx:
            self.assertTrue(self.rld._code_review_applies(tx, receipt, experiment))
            self.assertFalse(self.rld._code_review_applies(tx, receipt, tx.get(other)))
        self.assertEqual(result["result"], "clear")
        self.assertEqual(self.backend.call.call_count, 1)

    def test_unsupported_experiment_or_wrong_commit_fails_before_backend(self):
        cases = (("novelty_precheck", self.exp, None), ("code_review", self.sota, self.harness),
                 ("code_review", self.exp, self.harness), ("code_review", self.hyp, "not-a-commit"))
        for kind, about, ref in cases:
            with self.subTest(kind=kind, about=about, code=ref), self.assertRaises(review_call.ReviewError):
                review_call.review(self.root, kind, self.brief, about, code_ref=ref)
        self.factory.assert_not_called()
        self.backend.precheck.assert_not_called()
        self.backend.call.assert_not_called()
        self.assertEqual(review_call.spent(self.root), 0)

    def test_session_followup_keeps_original_blocking_receipt_current(self):
        self.response(False)
        original = self.review()
        path = self.root / "docs" / original["path"]
        saved = path.read_bytes()
        self.response(True)
        followup = self.review(session=original["session"])
        self.assertEqual(original["result"], "blocking")
        self.assertEqual(followup["result"], "clear")
        self.assertEqual(self.rld.get(original["review_id"])["status"], "current")
        self.assertEqual(path.read_bytes(), saved)
        self.assertTrue(self.rld.verify_document(original["review_id"]))

    def test_failed_session_round_never_overwrites_its_raw_output(self):
        self.response()
        original = self.review()
        self.backend.call.return_value = ({"ok": True, "structured": None, "text": "malformed response",
                "cost_usd": 0.01, "provider": "openai", "model_observed": "openai/gpt-6-astra",
                "terminal_reason": "stop", "permission_denials": [], "usage": {}}, "original malformed output")
        with self.assertRaises(review_call.ReviewError):
            self.review(session=original["session"])
        raw = self.root / "cache/reviews/RV-0001.v2.jsonl"
        failed_output = raw.read_bytes()
        self.response()
        retry = self.review(session=original["session"])
        self.assertEqual(retry["path"], "reviews/RV-0001.v3.md")
        self.assertEqual(raw.read_bytes(), failed_output)

    def test_ticket_publication_error_releases_reserved_session_before_any_model_call(self):
        with patch.object(review_call, "_update_job", side_effect=OSError("fixture ticket write failed")), \
                self.assertRaisesRegex(OSError, "ticket write failed"):
            self.review(job_ticket="RJ-0123456789ab")
        self.backend.call.assert_not_called()
        state = review_call._sessions(self.root)["RV-0001"]
        self.assertFalse(state["busy"])
        self.assertIsNone(state["active_ticket"])
        self.assertIsNone(state["allocation_token"])
        self.assertEqual(review_call.spent(self.root), 0)
        # An explicit subsequent session request is possible; no model was silently restarted on failure.
        self.response()
        continued = self.review(session="RV-0001")
        self.assertEqual(continued["path"], "reviews/RV-0001.v2.md")
        self.assertEqual(self.backend.call.call_count, 1)

    def test_local_snapshot_error_releases_the_reserved_session_without_model_cost(self):
        with patch.object(review_call, "code_snapshot", side_effect=OSError("fixture extraction failed")), \
                self.assertRaises(OSError):
            self.review()
        self.backend.call.assert_not_called()
        self.assertFalse(review_call._sessions(self.root)["RV-0001"]["busy"])


if __name__ == "__main__":
    unittest.main()
