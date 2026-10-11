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
            txn.create_node(labels=["Project"], properties={"id": "P-test", "architect_id": "root"})
            txn.create_node(labels=["Hypothesis"], properties={"id": "H-0001", "worker_id": "w1"})
            txn.create_node(labels=["Hypothesis"], properties={"id": "H-0007", "worker_id": "h0007"})
            txn.create_node(labels=["Hypothesis"], properties={"id": "H-0002", "worker_id": "main"})
            txn.create_node(labels=["Task"], properties={"id": "T-0001"})
            for i, (path, status) in enumerate(DOCS.items()):
                txn.create_node(labels=["Document"], properties={"id": f"D-{i:04d}", "path": path, "status": status})
            txn.commit()
        for path in DOCS:
            if "missing" not in path:
                (self.root / "docs" / path).parent.mkdir(parents=True, exist_ok=True)
                (self.root / "docs" / path).write_text("x\n", encoding="utf-8")
        self.registry = ["rld/main", "worker/w1", "ui/ui", "architect/root",
                         "explorer/main", "analyst/main", "reviewer/main", "worker/main"]
        self.write_registry(self.registry)

    def write_registry(self, addresses):
        (self.root / "agents.json").write_text(json.dumps(addresses), encoding="utf-8")

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
        logged = (self.root / "messages" / "rld--main.jsonl").read_text(encoding="utf-8").splitlines()
        self.assertEqual(out.strip(), logged[0])
        self.assertEqual([json.loads(line)["id"] for line in logged], ["rld--main-0001", "rld--main-0002"])
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
            "re not logged": (("--re", "worker--w1-0007"), "not in the message logs"),
            "task without docs": (("--docs",), "'docs' is a required property"),
            "unknown project-shaped id": (("--about", "X-1"), "is not a project"),
            "malformed id": (("--about", "bad id"), "does not match"),
        }
        for name, (extra, reason) in cases.items():
            with self.subTest(name):
                code, _, err = self.task(*extra)
                self.assertEqual(code, 2, err)
                self.assertIn(reason, err)
                self.assertEqual(self.log_lines("rld--main"), [])
        code, _, _ = self.task("--docs", "hypotheses/H-0001/hypothesis.v2.md")
        self.assertEqual(code, 0)

    def test_byte_limit_counts_utf8_of_full_line(self):
        docs = [f"{LONG_DIR}/result-part-{i}.v1.md" for i in range(5)]
        code, _, err = self.task("--text", "长" * 200, "--docs", *docs)
        self.assertEqual(code, 2)
        self.assertIn("bytes", err)
        self.assertEqual(self.log_lines("rld--main"), [])

    def test_resend_prints_the_logged_line_unchanged(self):
        code, out, _ = self.task()
        self.assertEqual(code, 0)
        code, out2, _ = self.run_tool("--resend", "rld--main-0001")
        self.assertEqual((code, out2), (0, out))
        self.assertEqual(len(self.log_lines("rld--main")), 1)
        code, _, err = self.run_tool("--resend", "rld--main-0009")
        self.assertEqual(code, 2)
        self.assertIn("not in the message logs", err)

    def test_every_role_has_distinct_logs_and_replies(self):
        self.assertEqual(self.task()[0], 0)
        for role in ("explorer", "analyst", "reviewer", "worker"):
            code, out, err = self.run_tool("--from", f"{role}/main", "--to", "rld/main",
                                           "--type", "question", "--text", "Evidence-backed next experiment?")
            self.assertEqual(code, 0, err)
            message = json.loads(out)
            self.assertEqual(message["id"], f"{role}--main-0001")
            code, replay, err = self.run_tool("--resend", message["id"])
            self.assertEqual((code, replay), (0, out), err)
            code, reply, err = self.run_tool("--from", "rld/main", "--to", f"{role}/main", "--type", "reply",
                                             "--text", "Please check the matched raw runs.", "--re", message["id"])
            self.assertEqual(code, 0, err)
            self.assertEqual(json.loads(reply)["re"], message["id"])
            self.assertEqual(len(self.log_lines(f"{role}--main")), 1)
        self.assertEqual([m["id"] for m in self.log_lines("rld--main")],
                         [f"rld--main-{n:04d}" for n in range(1, 6)])
        for address, expected in (("architect/root", "architect--root-0001"), ("ui/ui", "ui--ui-0001")):
            code, out, err = self.run_tool("--from", address, "--to", "rld/main", "--type", "alert", "--text", "Ready")
            self.assertEqual(code, 0, err)
            self.assertEqual(json.loads(out)["id"], expected)

    def test_advisors_and_architect_must_be_registered(self):
        self.write_registry(["rld/main", "ui/ui", "worker/w1"])
        for role, ident in (("explorer", "main"), ("analyst", "main"), ("reviewer", "main"), ("architect", "root")):
            address = f"{role}/{ident}"
            with self.subTest(address=address):
                for sender, recipient in ((address, "rld/main"), ("rld/main", address)):
                    code, _, err = self.run_tool("--from", sender, "--to", recipient,
                                                 "--type", "question", "--text", "x")
                    self.assertEqual(code, 2, err)
                    self.assertIn("not in agents.json", err)
        self.assertFalse(send_message.registered_address("architect/root", {"worker/root"}))
        self.assertFalse(send_message.registered_address("explorer/main", {"rld/main"}))
        self.assertFalse(send_message.registered_address("analyst/main", {"rld/main"}))

    def test_worker_senders_require_unique_hypothesis_ownership(self):
        for sender in ("worker/unknown", "worker/unbound"):
            self.write_registry([*self.registry, "worker/unbound"])
            with self.subTest(sender=sender):
                code, _, err = self.run_tool("--from", sender, "--to", "rld/main", "--type", "question", "--text", "x")
                self.assertEqual(code, 2, err)
                self.assertIn("bound to exactly one hypothesis", err)
                self.assertEqual(self.log_lines(send_message.agent_id(sender)), [])
        with Database(self.root / "research_tree.db") as db, db.write() as txn:
            txn.create_node(labels=["Hypothesis"], properties={"id": "H-0003", "worker_id": "w1"})
            txn.commit()
        code, _, err = self.run_tool("--from", "worker/w1", "--to", "rld/main", "--type", "question", "--text", "x")
        self.assertEqual(code, 2, err)
        self.assertIn("bound to exactly one hypothesis", err)
        code, _, err = self.task()
        self.assertEqual(code, 2, err)
        self.assertIn("bound to exactly one hypothesis", err)

    def test_architect_requires_project_assignment(self):
        with Database(self.root / "research_tree.db") as db, db.write() as txn:
            project = txn.get_nodes_by_label("Project")[0]
            txn.set_property(project, "architect_id", None)
            txn.commit()
        code, _, err = self.run_tool("--from", "architect/root", "--to", "rld/main", "--type", "alert", "--text", "Ready")
        self.assertEqual(code, 2, err)
        self.assertIn("assigned to the project root", err)

    def test_legacy_roles_root_worker_and_alternate_fixed_addresses_are_rejected(self):
        for address in ("assistant/lens", "web_builder/web", "worker/root", "architect/w1", "rld/other", "ui/other"):
            with self.subTest(address=address):
                for sender, recipient in ((address, "rld/main"), ("rld/main", address)):
                    code, _, err = self.run_tool("--from", sender, "--to", recipient, "--type", "alert", "--text", "x")
                    self.assertEqual(code, 2, err)
                    self.assertTrue("invalid agent address" in err or "does not match" in err, err)
                self.write_registry([*self.registry, address])
                code, _, err = self.task()
                self.assertEqual(code, 2, err)
                self.assertIn("invalid agent address", err)
                self.write_registry(self.registry)
        self.assertEqual(self.log_lines("rld--main"), [])

    def test_legacy_message_ids_are_rejected_even_when_the_old_log_exists(self):
        (self.root / "messages").mkdir()
        (self.root / "messages" / "main.jsonl").write_text('{"id":"main-0001"}\n', encoding="utf-8")
        for legacy_id in ("main-0001", "root-0001", "w1-0001", "../main-0001", "assistant--lens-0001"):
            with self.subTest(legacy_id=legacy_id):
                self.assertIsNone(send_message.MESSAGE_ID_RE.fullmatch(legacy_id))
                code, _, err = self.run_tool("--resend", legacy_id)
                self.assertEqual(code, 2, err)
                self.assertIn("is not a message id", err)
                code, _, err = self.task("--re", legacy_id)
                self.assertEqual(code, 2, err)
                self.assertIn("does not match", err)
        self.assertEqual(self.log_lines("rld--main"), [])

    def test_schema_rejects_legacy_fields_and_matches_runtime_addresses(self):
        schema = json.loads(send_message.SCHEMA_PATH.read_text(encoding="utf-8"))
        self.assertEqual(schema["$defs"]["agent"]["pattern"], send_message.ADDRESS_PATTERN)
        self.assertEqual(schema["properties"]["id"]["pattern"], send_message.MESSAGE_ID_RE.pattern)
        self.assertEqual(schema["properties"]["re"]["pattern"], send_message.MESSAGE_ID_RE.pattern)
        code, out, err = self.task()
        self.assertEqual(code, 0, err)
        message = json.loads(out)
        validator = send_message.Draft202012Validator(schema)
        self.assertIn("Additional properties", send_message.schema_errors(validator, {**message, "legacy": True}))

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
            self.assertEqual(self.log_lines("rld--main"), [])
        finally:
            holder.kill()
            holder.wait()
            holder.stdout.close()


if __name__ == "__main__":
    unittest.main()
