"""Tests for tools/send_message.py. Run: .venv/bin/python -m unittest discover -s tests"""

from __future__ import annotations

import contextlib
import importlib.util
import io
import json
import os
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

FAKE_CLI = textwrap.dedent(
    """\
    #!{python}
    import json, os, sys
    with open(os.environ["FAKE_CLI_LOG"], "a") as f:
        f.write(json.dumps([os.path.basename(sys.argv[0])] + sys.argv[1:]) + "\\n")
    sys.exit(int(os.environ.get("FAKE_CLI_EXIT", "0")))
    """
)


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
        (self.root / "agents.json").write_text(
            json.dumps(
                {
                    "rld/main": {"channel": "native", "thread": "thread-rld"},
                    "worker/w1": {"channel": "codex-queue", "thread": "thread-w1"},
                    "ui/ui": {"channel": "herdr", "herdr_agent": "ui-agent"},
                }
            ),
            encoding="utf-8",
        )

        bin_dir = Path(self.tmp.name) / "bin"
        bin_dir.mkdir()
        for name in ("codex", "herdr"):
            exe = bin_dir / name
            exe.write_text(FAKE_CLI.format(python=sys.executable), encoding="utf-8")
            exe.chmod(0o755)
        self.cli_log = Path(self.tmp.name) / "cli.log"
        self.env = {"PATH": f"{bin_dir}:{os.environ['PATH']}", "FAKE_CLI_LOG": str(self.cli_log)}
        self.saved_env = {k: os.environ.get(k) for k in (*self.env, "FAKE_CLI_EXIT")}
        os.environ.update(self.env)

    def tearDown(self):
        for k, v in self.saved_env.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v
        self.tmp.cleanup()

    def run_tool(self, *args: str) -> tuple[int, str, str]:
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = send_message.main(["--root", str(self.root), *args])
        return code, out.getvalue(), err.getvalue()

    def log_lines(self, sender: str, suffix: str = "jsonl") -> list[dict]:
        path = self.root / "messages" / f"{sender}.{suffix}"
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

    def test_codex_queue_receives_line_verbatim(self):
        text = 'run $(rm -rf ~); echo "x" `id` \'q\''
        code, out, _ = self.task("--text", text)
        self.assertEqual(code, 0)
        argv = json.loads(self.cli_log.read_text().splitlines()[0])
        self.assertEqual(argv, ["codex", "queue", "--thread", "thread-w1", "--message", out.strip()])
        self.assertEqual(json.loads(argv[-1])["text"], text)
        self.assertEqual(self.log_lines("main", "delivery.jsonl")[0]["status"], "queued")

    def test_native_and_herdr_channels(self):
        code, _, err = self.run_tool(
            "--from", "worker/w1", "--to", "rld/main", "--type", "question", "--text", "问题"
        )
        self.assertEqual(code, 0)
        self.assertIn("thread-rld", err)
        self.assertEqual(self.log_lines("w1", "delivery.jsonl")[0]["status"], "printed")
        self.assertFalse(self.cli_log.exists())

        code, out, _ = self.run_tool("--from", "rld/main", "--to", "ui/ui", "--type", "reply", "--re", "w1-0001", "--text", "答复")
        self.assertEqual(code, 0)
        argv = json.loads(self.cli_log.read_text().splitlines()[0])
        self.assertEqual(argv, ["herdr", "agent", "prompt", "ui-agent", out.strip()])

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

    def test_bad_recipient_config_is_rejected_before_logging(self):
        registry = json.loads((self.root / "agents.json").read_text(encoding="utf-8"))
        registry["worker/w1"] = {"channel": "codex-queue"}  # thread missing
        (self.root / "agents.json").write_text(json.dumps(registry), encoding="utf-8")
        code, _, err = self.task()
        self.assertEqual(code, 2)
        self.assertIn("needs thread", err)
        self.assertEqual(self.log_lines("main"), [])

    def test_byte_limit_counts_utf8_of_full_line(self):
        docs = [f"{LONG_DIR}/result-part-{i}.v1.md" for i in range(5)]
        code, _, err = self.task("--text", "长" * 200, "--docs", *docs)
        self.assertEqual(code, 2)
        self.assertIn("bytes", err)
        self.assertEqual(self.log_lines("main"), [])

    def test_failed_delivery_stays_logged_and_resend_reuses_line(self):
        os.environ["FAKE_CLI_EXIT"] = "3"
        code, out, _ = self.task()
        self.assertEqual(code, 1)
        self.assertEqual(len(self.log_lines("main")), 1)
        os.environ["FAKE_CLI_EXIT"] = "0"
        code, out2, _ = self.run_tool("--resend", "main-0001")
        self.assertEqual(code, 0)
        self.assertEqual(out, out2)
        self.assertEqual(len(self.log_lines("main")), 1)
        self.assertEqual([d["status"] for d in self.log_lines("main", "delivery.jsonl")], ["failed", "queued"])

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
