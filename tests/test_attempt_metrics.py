"""REG-S6-06 (plans/research-tree-implementation-and-real-scenarios.md §10.5): a legitimate retry after a failure
adds an authorized retry, not a duplicate job; a real extra process start adds exactly one duplicate job; transport
retries and repeated settlements are counted apart; a fault class is avoidable only after its fix was verified and
when it was not injected again. The ledgers are REG fixtures written the way the local execution adapter writes them."""

from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts" / "scenarios"))

import attempt_metrics  # noqa: E402


class AttemptMetricsTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.project = Path(self.tmp.name)
        self.root = self.project / "research" / "P"
        (self.project / ".local-exec").mkdir(parents=True)
        (self.root / "logs").mkdir(parents=True)
        self.launches, self.events, self.faults = [], [], []

    def tearDown(self):
        self.tmp.cleanup()

    def write(self):
        for name, rows in (("launches", self.launches), ("events", self.events), ("faults", self.faults)):
            (self.project / ".local-exec" / f"{name}.jsonl").write_text("".join(json.dumps(r) + "\n" for r in rows))

    def start(self, key, launch=1):
        self.launches.append({"key": key, "launch": launch, "pid": 1000 + len(self.launches)})
        self.events.append({"call": "submit", "key": key})

    def log(self, name, text):
        (self.root / "logs" / name).write_text(text)
        return f"logs/{name}"

    def tables(self, run, reservations, documents=()):
        return {"run": [run], "reservation": [{"submission_key": k} for k in reservations], "document": list(documents)}

    def test_retry_is_authorized_and_an_extra_start_is_one_duplicate(self):
        self.start("k-a1")
        self.start("k-a2")
        self.events.append({"call": "submit", "key": "k-a2"})  # the answer was lost; asked again, no new start
        self.events += [{"call": "accounting", "key": "k-a2"}, {"call": "accounting", "key": "k-a2"}]
        run = {"id": "E-1/s42", "attempt": 2, "exec_status": "succeeded", "valid": True, "submission_key": "k-a2",
               "attempts": {"1": {"exec_status": "failed", "submission_key": "k-a1",
                                  "log_path": self.log("a1.log", "FileNotFoundError: data/missing")}}}
        self.write()
        m = attempt_metrics.metrics(self.project, self.tables(run, ["k-a1", "k-a2"]), self.root)
        self.assertEqual((m["research_attempts"], m["authorized_retries"], m["duplicate_jobs"], m["transport_retries"],
                          m["duplicate_settlement_requests"]), (2, 1, 0, 1, 1))
        self.start("k-a2", launch=2)  # the adapter's declared extra_launch fault: a second real process
        self.faults.append({"fault": "F", "window": "extra_launch", "key": "k-a2"})
        self.write()
        m = attempt_metrics.metrics(self.project, self.tables(run, ["k-a1", "k-a2"]), self.root)
        self.assertEqual((m["duplicate_jobs"], m["authorized_retries"], m["injected_failures"]), (1, 1, 1))
        self.start("orphan")  # a start no run intent explains
        self.write()
        self.assertEqual(attempt_metrics.metrics(self.project, self.tables(run, ["k-a1", "k-a2"]), self.root)["duplicate_jobs"], 2)

    def test_avoidable_failures_need_an_earlier_verified_fix(self):
        verified = {"doc_type": "lesson", "status": "current", "updated_at": "2026-10-08T10:00:00Z",
                    "memory_basis": {"verification": {"state": "verified", "failure": "E-1/s42@1"}}}
        failed = lambda key, at: {"exec_status": "failed", "submission_key": key, "finished_at": at,  # noqa: E731
                                  "log_path": self.log(f"{key}.log", "FileNotFoundError: data/missing")}
        run = {"id": "E-1/s42", "attempt": 3, "exec_status": "failed", "submission_key": "k3",
               "finished_at": "2026-10-08T11:00:00Z", "log_path": self.log("k3.log", "FileNotFoundError: again"),
               "attempts": {"1": failed("k1", "2026-10-08T09:00:00Z"), "2": failed("k2", "2026-10-08T09:30:00Z")}}
        self.write()
        m = attempt_metrics.metrics(self.project, self.tables(run, ["k1", "k2", "k3"], [verified]), self.root)
        self.assertEqual(m["avoidable_repeated_failures"], 1)  # only the failure after the fix was verified
        self.faults.append({"fault": "F", "window": "lose_submit_response", "key": "k3"})  # injected again: not the agent's
        self.write()
        m = attempt_metrics.metrics(self.project, self.tables(run, ["k1", "k2", "k3"], [verified]), self.root)
        self.assertEqual(m["avoidable_repeated_failures"], 0)
        other = dict(run, log_path=self.log("k3.log", "MemoryError: out of memory"))
        self.faults.clear()
        self.write()
        m = attempt_metrics.metrics(self.project, self.tables(other, ["k1", "k2", "k3"], [verified]), self.root)
        self.assertEqual(m["avoidable_repeated_failures"], 0)  # another fault class


if __name__ == "__main__":
    unittest.main()
