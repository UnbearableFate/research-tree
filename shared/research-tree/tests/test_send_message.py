"""Tests for tools/send_message.py. Run: .venv/bin/python -m unittest discover -s tests"""

from __future__ import annotations

import contextlib
import importlib.util
import io
import json
import subprocess
import sys
import tempfile
import textwrap
import time
import unittest
from pathlib import Path

from latticedb import Database

REPO = Path(__file__).resolve().parent.parent


def load(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


sys.path.insert(0, str(REPO / "tools"))
create_db = load("create_db", REPO / "schema" / "create_db.py")
send_message = load("send_message", REPO / "tools" / "send_message.py")
import research_db  # noqa: E402  (after sys.path setup)

LONG_DIR = "hypotheses/H-0001/experiments/E-0001/a-rather-long-directory-name-for-results"
DOCS = {
    "tasks/T-0001/request.v1.md": "current",
    "hypotheses/H-0001/hypothesis.v1.md": "superseded",
    "hypotheses/H-0001/hypothesis.v2.md": "current",
    "hypotheses/H-0001/notes/missing.v1.md": "current",  # registered but not written to disk
    **{f"{LONG_DIR}/result-part-{i}.v1.md": "current" for i in range(5)},
}

class SendMessageTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name) / "research" / "P-test"
        (self.root / "docs").mkdir(parents=True)
        create_db.create_db(self.root / "research_tree.db")
        with Database(self.root / "research_tree.db") as db, db.write() as txn:
            txn.create_node(labels=["Project"], properties={"id": "P-test"})
            txn.create_node(labels=["Hypothesis"], properties={"id": "H-0001"})
            txn.create_node(labels=["Task"], properties={"id": "T-0001"})
            for i, (path, status) in enumerate(DOCS.items()):
                txn.create_node(labels=["Document"], properties={"id": f"D-{i:04d}", "path": path, "status": status})
            txn.commit()
        for path in DOCS:
            if "missing" not in path:
                (self.root / "docs" / path).parent.mkdir(parents=True, exist_ok=True)
                (self.root / "docs" / path).write_text("x\n", encoding="utf-8")
        (self.root / "agents.json").write_text(json.dumps(["rld/main", "worker/w1", "ui/ui"]), encoding="utf-8")

    def tearDown(self):
        self.tmp.cleanup()

    def run_tool(self, *args: str) -> tuple[int, str, str]:
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = send_message.main(["--root", str(self.root), *args])
        return code, out.getvalue(), err.getvalue()

    def log_lines(self, sender: str) -> list[dict]:
        path = self.root / "messages" / f"{sender}.jsonl"
        return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()] if path.exists() else []

    def task(self, *extra: str) -> tuple[int, str, str]:
        return self.run_tool(
            "--from", "rld/main", "--to", "worker/w1", "--type", "task",
            "--text", "请完成T-0001", "--docs", "tasks/T-0001/request.v1.md", "--about", "T-0001", *extra,
        )

    def test_logs_exact_line_and_numbers_per_sender(self):
        code, out, _ = self.task()
        self.assertEqual(code, 0)
        code, _, _ = self.task()
        self.assertEqual(code, 0)
        logged = (self.root / "messages" / "main.jsonl").read_text(encoding="utf-8").splitlines()
        self.assertEqual(out.strip(), logged[0])
        self.assertEqual([json.loads(line)["id"] for line in logged], ["main-0001", "main-0002"])
        first = json.loads(logged[0])
        self.assertEqual((first["project"], first["need"]), ("P-test", "ack"))
        self.assertIn("请完成", logged[0])  # UTF-8, not \\u escapes

    def test_text_is_logged_verbatim_and_unregistered_recipients_are_refused(self):
        text = 'run $(rm -rf ~); echo "x" `id` \'q\''
        code, out, _ = self.task("--text", text)
        self.assertEqual(code, 0)
        self.assertEqual(json.loads(out)["text"], text)
        code, _, err = self.run_tool("--from", "rld/main", "--to", "worker/h0007", "--type", "question", "--text", "问题")
        self.assertEqual(code, 2)
        self.assertIn("not in agents.json", err)
        code, _, _ = self.run_tool("--from", "worker/h0007", "--to", "rld/main", "--type", "question", "--text", "问题")
        self.assertEqual(code, 0)

    def test_rejected_messages_are_not_logged(self):
        cases = {
            "unregistered doc": (("--docs", "tasks/T-9999/request.v1.md"), "registered 0 times"),
            "superseded doc": (("--docs", "hypotheses/H-0001/hypothesis.v1.md"), "superseded"),
            "doc missing on disk": (("--docs", "hypotheses/H-0001/notes/missing.v1.md"), "missing on disk"),
            "unknown entity": (("--about", "H-0404"), "not a hypothesis"),
            "re not logged": (("--re", "w1-0007"), "not in the message logs"),
            "task without docs": (("--docs",), "'docs' is a required property"),
            "unknown project-shaped id": (("--about", "X-1"), "is not a project"),
            "malformed id": (("--about", "bad id"), "does not match"),
        }
        for name, (extra, reason) in cases.items():
            with self.subTest(name):
                code, _, err = self.task(*extra)
                self.assertEqual(code, 2, err)
                self.assertIn(reason, err)
                self.assertEqual(self.log_lines("main"), [])
        code, _, _ = self.task("--docs", "hypotheses/H-0001/hypothesis.v2.md")
        self.assertEqual(code, 0)

    def test_byte_limit_counts_utf8_of_full_line(self):
        docs = [f"{LONG_DIR}/result-part-{i}.v1.md" for i in range(5)]
        code, _, err = self.task("--text", "长" * 200, "--docs", *docs)
        self.assertEqual(code, 2)
        self.assertIn("bytes", err)
        self.assertEqual(self.log_lines("main"), [])

    def test_resend_prints_the_logged_line_unchanged(self):
        code, out, _ = self.task()
        self.assertEqual(code, 0)
        code, out2, _ = self.run_tool("--resend", "main-0001")
        self.assertEqual((code, out2), (0, out))
        self.assertEqual(len(self.log_lines("main")), 1)
        code, _, err = self.run_tool("--resend", "main-0009")
        self.assertEqual(code, 2)
        self.assertIn("not in the message logs", err)

    def test_advisors_keep_distinct_logs_and_replies_in_legacy_projects(self):
        # No registry migration is needed, and existing Leader ids remain unchanged.
        self.assertEqual(self.task()[0], 0)
        messages = {}
        for role in ("explorer", "analyst"):
            code, out, err = self.run_tool("--from", f"{role}/main", "--to", "rld/main",
                                           "--type", "question", "--text", "Evidence-backed next experiment?")
            self.assertEqual(code, 0, err)
            messages[role] = json.loads(out)
            self.assertEqual(messages[role]["id"], f"{role}--main-0001")
            code, replay, err = self.run_tool("--resend", messages[role]["id"])
            self.assertEqual((code, replay), (0, out), err)
            code, reply, err = self.run_tool("--from", "rld/main", "--to", f"{role}/main", "--type", "reply",
                                             "--text", "Please check the matched raw runs.", "--re", messages[role]["id"])
            self.assertEqual(code, 0, err)
            self.assertEqual(json.loads(reply)["re"], messages[role]["id"])
        self.assertEqual([m["id"] for m in self.log_lines("main")], ["main-0001", "main-0002", "main-0003"])
        self.assertEqual(len(self.log_lines("explorer--main")), 1)
        self.assertEqual(len(self.log_lines("analyst--main")), 1)
        for role in ("explorer", "analyst"):
            code, _, err = self.run_tool("--from", f"{role}/other", "--to", "rld/main", "--type", "question", "--text", "x")
            self.assertEqual(code, 2, err)

    def test_architect_reuses_its_root_worker_log_without_rewriting_legacy_ids(self):
        for actor, expected in (("worker/root", "root-0001"), ("architect/root", "root-0002")):
            code, out, err = self.run_tool("--from", actor, "--to", "rld/main", "--type", "alert", "--text", "Root harness ready")
            self.assertEqual(code, 0, err)
            self.assertEqual(json.loads(out)["id"], expected)
        self.assertEqual(len(self.log_lines("root")), 2)
        self.assertTrue(send_message.MESSAGE_ID_RE.fullmatch("explorer--main-0001"))
        self.assertFalse(send_message.MESSAGE_ID_RE.fullmatch("../main-0001"))

    def test_gives_up_when_a_writer_holds_the_database(self):
        holder = subprocess.Popen(
            [sys.executable, "-c", textwrap.dedent(
                f"""
                import sys, time
                from latticedb import Database
                with Database({str(self.root / 'research_tree.db')!r}) as db:
                    print("held", flush=True)
                    time.sleep(5)
                """
            )],
            stdout=subprocess.PIPE, text=True,
        )
        try:
            self.assertEqual(holder.stdout.readline().strip(), "held")
            saved = research_db.OPEN_ATTEMPTS
            research_db.OPEN_ATTEMPTS = 2
            try:
                start = time.monotonic()
                code, _, err = self.task()
            finally:
                research_db.OPEN_ATTEMPTS = saved
            self.assertEqual(code, 2)
            self.assertIn("locked", err)
            self.assertLess(time.monotonic() - start, 3)
            self.assertEqual(self.log_lines("main"), [])
        finally:
            holder.kill()
            holder.wait()
            holder.stdout.close()


if __name__ == "__main__":
    unittest.main()
