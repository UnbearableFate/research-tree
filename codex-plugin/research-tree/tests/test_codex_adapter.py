"""Adapter tests run from the assembled plugin, including real supervisor subprocesses."""
from __future__ import annotations

import json
import shutil
import os
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))

import codex_agent
import codex_hook
import codex_mcp
import research_tree
from codex_runtime import Runtime
from metrics import minimal_documents
import build_site
from research_db import READ_METHODS, TASK_SECTIONS
from codex_state import lock_busy, locked, read_json, write_json


class AdapterTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.cwd = Path(self.temp.name) / "project with spaces"
        self.cwd.mkdir()
        (self.cwd / "plan.md").write_text("# 研究计划\n保留用户原话。\n", encoding="utf-8")
        # the adapter's behaviour, not the configuration version: version 1 leaves the documents to the RLD
        shutil.copyfile(ROOT / "schema/config.v1.template.yaml", self.cwd / "research-tree.yaml")
        research_tree.init(self.cwd, self.cwd / "plan.md", "P-test")
        self.runtime = Runtime(self.cwd)
        self.db = self.runtime.db()
        setup = self.doc("project/min-setup.v1.md", "min_setup")
        docs = {}
        for kind, content in zip(("metric_spec", "protocol"), minimal_documents("accuracy", "higher", [])):
            path = self.runtime.root / "docs" / "project" / f"{kind}.v1.json"
            path.write_text(json.dumps(content), encoding="utf-8")
            docs[f"{kind}_doc_id"] = self.db.register_document(f"project/{kind}.v1.json", kind, kind)
            self.db.set_document_current(docs[f"{kind}_doc_id"])
        self.db.create_project("P-test", "test", setup, "accuracy", "higher", True, [], [1, 2, 3], **docs)
        self.plan = self.doc("project/reports/init-plan.v1.md", "report")
        request = self.doc("tasks/T-0001/request.v1.md", "task_request")
        self.task = self.db.create_task("harness", "worker", request, target_id="P-test")
        self.bin = Path(self.temp.name) / "bin"
        self.bin.mkdir()
        fake = self.bin / "codex"
        fake.write_text(f"#!{sys.executable}\n" + r'''
import json, os, sys, time, uuid
from pathlib import Path
args = sys.argv[1:]
base = Path(os.environ['FAKE_CODEX_DIR'])
with (base / 'calls.jsonl').open('a') as log:
    log.write(json.dumps(args) + '\n')
if args[0] == 'queue':
    sys.exit(int(os.environ.get('FAKE_QUEUE_EXIT', '0')))
prompt = sys.stdin.read()
if os.environ.get('FAKE_CODEX_FAIL'):
    print('simulated failure', file=sys.stderr)
    sys.exit(3)
thread = args[args.index('resume') + 1] if 'resume' in args else str(uuid.uuid4())
print(json.dumps({'type':'thread.started', 'thread_id':thread}), flush=True)
while (base / 'hold').exists():
    time.sleep(0.02)
answer = Path(args[args.index('--output-last-message') + 1])
answer.write_text(os.environ.get('FAKE_CODEX_REPLY', 'worker finished'), encoding='utf-8')
print(json.dumps({'type':'turn.completed'}), flush=True)
''')
        fake.chmod(0o755)
        self.environment = patch.dict(os.environ, {"PATH": str(self.bin) + os.pathsep + os.environ["PATH"],
                                                 "FAKE_CODEX_DIR": self.temp.name})
        self.environment.start()
        self.runtime.control("attach", {"session_id": "11111111-1111-4111-8111-111111111111", "model": "fixture-model"})

    def tearDown(self):
        hold = Path(self.temp.name) / "hold"
        hold.unlink(missing_ok=True)
        for _ in range(300):
            if not any(x["live"] for x in self.runtime.agents()):
                break
            time.sleep(0.02)
        self.environment.stop()
        self.temp.cleanup()

    def doc(self, path, kind):
        file = self.runtime.root / "docs" / path
        file.parent.mkdir(parents=True, exist_ok=True)
        file.write_text(f"# {kind}\n" + "".join(f"## {name}\n\n未知\n" for name in TASK_SECTIONS.get(kind, ())))
        doc = self.db.register_document(path, kind, kind)
        self.db.set_document_current(doc)
        return doc

    def confirm(self):
        self.runtime.post({"type": "confirm_request", "text": "请确认立项计划", "docs": ["project/reports/init-plan.v1.md"]})
        return self.runtime.confirm("同意上面的立项计划。")

    def assign(self):
        self.db.assign_worker("P-test")
        self.db.update_task(self.task, assignee_id="root")

    def wait_run(self, run):
        path = Path(run["directory"]) / "state.json"
        for _ in range(500):
            state = read_json(path)
            if state.get("status") in {"completed", "failed", "interrupted"} and not lock_busy(self.runtime.cache / "agents" / f"{run['actor'].replace('/', '-')}.lock"):
                return state
            time.sleep(0.02)
        self.fail(f"supervisor did not finish: {read_json(path)}")

    def test_confirmation_persists_verbatim_config_and_gates_workers(self):
        with self.assertRaisesRegex(ValueError, "confirmed"):
            self.runtime.start_worker("P-test", "task")
        with self.assertRaisesRegex(ValueError, "submitted"):
            self.runtime.confirm("同意")
        with self.assertRaises(Exception):
            self.runtime.post({"type": "confirm_request", "text": "plan", "docs": ["missing.v1.md"]})
        self.assertEqual(self.runtime.marker["phase"], "planning")
        result = self.confirm()
        self.assertEqual(self.runtime.marker["phase"], "confirmed")
        self.assertTrue(self.runtime.marker["config"]["doc_id"])
        self.assertIn("同意上面的立项计划。", (self.runtime.root / "docs" / result["document"]["path"]).read_text())
        self.assertEqual(result["delivery"]["delivery"], "queued")
        before = len(self.db.find("document"))
        self.runtime.confirm("again")
        self.assertEqual(len(self.db.find("document")), before)
        with self.assertRaisesRegex(ValueError, "assign_worker"):
            self.runtime.start_worker("P-test", "implement")

    def test_confirm_request_and_usage_alert_reach_the_webhook_log(self):
        self.runtime.post({"type": "confirm_request", "text": "请确认", "docs": ["project/reports/init-plan.v1.md"]})
        real = build_site.summary_or_empty
        build_site.summary_or_empty = lambda db: {**real(db), "project": {"alert_node_h": 1.0},
                                                  "attention": [{"kind": "usage_alert", "text": "用量达到 1 node·h"}]}
        try:
            self.runtime.summary()
            self.runtime.summary()  # one notification per threshold
        finally:
            build_site.summary_or_empty = real
        log = [json.loads(line) for line in (self.runtime.root / "logs/notify.jsonl").read_text().splitlines()]
        self.assertEqual([(r["kind"], r["outcome"]) for r in log],
                         [("confirm_request", "skipped: no notify.url"), ("alert", "skipped: no notify.url")])

    def test_bound_roles_cannot_impersonate_or_control_execution(self):
        ui = Runtime(self.cwd, "ui/ui")
        with self.assertRaisesRegex(ValueError, "only read"):
            ui.dispatch("research_db", {"method": "update_project", "kwargs": {"title": "oops"}})
        for action in ("worker", "confirm", "instruction", "attach", "acknowledge"):
            with self.assertRaisesRegex(ValueError, "only RLD"):
                ui.control(action, {})
        with self.assertRaisesRegex(ValueError, "unexpected"):
            codex_mcp.run_request(self.cwd, "worker/root", "research_db", {"actor": "rld/main", "method": "help"})
        self.confirm()
        self.assign()
        worker = Runtime(self.cwd, "worker/root")
        with self.assertRaisesRegex(Exception, "requires role rld"):
            worker.dispatch("research_db", {"method": "update_project", "kwargs": {"title": "oops"}})
        worker.dispatch("research_db", {"method": "update_task", "kwargs": {"task_id": self.task, "status": "in_progress"}})
        self.assertEqual(self.db.get(self.task)["status"], "in_progress")

    def test_direct_main_instruction_preserves_words_and_scope(self):
        words = "暂停新实验；已提交的作业先核对状态。"
        result = self.runtime.control("instruction", {"words": words, "understanding": "暂停新提交，核对原作业。",
                                                      "kind": "暂停", "about": ["P-test"]})
        self.assertIn(words, (self.runtime.root / "docs" / result["path"]).read_text())
        self.assertEqual(self.db.get(result["doc_id"])["doc_type"], "user_instruction")
        self.assertEqual(self.runtime.marker["phase"], "planning")
        with self.assertRaisesRegex(ValueError, "verbatim"):
            self.runtime.control("instruction", {"words": "", "understanding": "pause"})

    def test_worker_binding_followup_and_resume_use_same_identity(self):
        self.confirm()
        self.assign()
        hold = Path(self.temp.name) / "hold"
        hold.touch()
        first = self.runtime.start_worker("P-test", "实现根节点")
        for _ in range(300):
            if read_json(Path(first["directory"]) / "state.json").get("thread_id"):
                break
            time.sleep(0.02)
        queued = self.runtime.start_worker("P-test", "后续任务")
        self.assertEqual(queued["delivery"], "queued")
        with self.assertRaisesRegex(ValueError, "live"):
            self.runtime.start_worker("P-test", "replacement", restart=True)
        hold.unlink()
        state = self.wait_run(first)
        self.assertEqual(state["status"], "completed", state)
        self.assertEqual(self.db.get("P-test")["worker_agent_id"], state["thread_id"])
        second = self.runtime.start_worker("P-test", "继续核对")
        resumed = self.wait_run(second)
        self.assertEqual(resumed["thread_id"], state["thread_id"])
        self.assertEqual(resumed["status"], "completed", resumed)
        calls = [json.loads(x) for x in (Path(self.temp.name) / "calls.jsonl").read_text().splitlines()]
        execs = [c for c in calls if c[0] == "exec"]
        self.assertEqual(execs[0][execs[0].index("--model") + 1], "fixture-model")
        self.assertTrue(any("worker/root" in x for x in execs[0]))
        self.assertIn("resume", execs[1])
        self.assertFalse(any("bypass" in arg for call in calls for arg in call))
        # a background session cannot answer approval prompts: the plugin's own MCP server is pre-approved
        self.assertIn('mcp_servers.research_tree.default_tools_approval_mode="approve"', execs[0])

    def test_worker_failure_is_visible_and_does_not_look_delivered(self):
        self.confirm()
        self.assign()
        with patch.dict(os.environ, {"FAKE_CODEX_FAIL": "1"}):
            run = self.runtime.start_worker("P-test", "task")
            state = self.wait_run(run)
        self.assertEqual(state["status"], "failed")
        self.assertEqual(state["exit_code"], 3)
        self.assertEqual(self.db.get(self.task)["status"], "open")
        self.assertEqual(self.runtime.agents()[0]["live"], False)

    def test_ui_structured_confirmation_is_applied_once_and_records_original(self):
        self.runtime.post({"type": "confirm_request", "text": "确认？", "docs": ["project/reports/init-plan.v1.md"]})
        answer = {"reply": "已收到确认", "actions": [{"type": "confirm", "text": "", "docs": [], "about": [], "req": ""}]}
        with patch.dict(os.environ, {"FAKE_CODEX_REPLY": json.dumps(answer)}):
            run = self.runtime.start_ui("同意这个具体计划，按已说明的预算执行。")
            state = self.wait_run(run)
        self.assertEqual(state["status"], "completed", state)
        self.assertEqual(state["actions"][0]["status"], "completed", state)
        self.assertEqual(self.runtime.marker["phase"], "confirmed")
        docs = list((self.runtime.root / "docs/instructions").glob("*.md"))
        self.assertTrue(any("同意这个具体计划，按已说明的预算执行。" in p.read_text() for p in docs))
        with self.assertRaisesRegex(ValueError, "already attempted"):
            self.runtime.apply_ui(Path(run["directory"]), answer)

    def test_requirement_draft_submission_and_revision(self):
        source = self.runtime.say("user", "只研究优化器，先做小规模比较。")
        ui = Runtime(self.cwd, "ui/ui")
        draft = ui.dispatch("requirement_draft", {"title": "优化器范围", "fields": {"goal": "比较优化器", "scope": "小规模"},
                                                  "messages": [source["id"]], "about": ["P-test"]})
        directory = self.runtime.cache / "runs/ui-draft"
        write_json(directory / "spec.json", {"actor": "ui/ui", "user_message": source})
        response = {"reply": "提交范围", "actions": [{"type": "submit", "text": "", "docs": [], "about": [], "req": draft["id"]}]}
        result = self.runtime.apply_ui(directory, response)
        self.assertEqual(result[0]["status"], "completed", result)
        text = (self.runtime.root / "docs/requirements/REQ-0001.v1.md").read_text()
        self.assertIn(source["text"], text)
        ui.dispatch("requirement_draft", {"req": draft["id"], "fields": {"scope": "单机"}})
        self.assertEqual(research_tree.list_requirements(self.cwd)[0]["status"], "open")

    def test_queue_failure_is_durable_and_acknowledgement_is_separate(self):
        with patch.dict(os.environ, {"FAKE_QUEUE_EXIT": "1"}):
            first = self.runtime.enqueue("test", "fixed-id")
        self.assertEqual(first["delivery"], "failed")
        self.assertEqual(self.runtime.enqueue("test", "fixed-id")["delivery"], "failed")
        calls = (Path(self.temp.name) / "calls.jsonl").read_text().splitlines()
        self.assertEqual(len(calls), 1)
        retried = self.runtime.enqueue("test", "fixed-id", retry=True)
        self.assertEqual(retried["delivery"], "queued")
        self.assertEqual(retried["id"], "fixed-id")
        self.assertEqual(len(self.runtime.control("inbox", {})), 1)
        self.runtime.control("acknowledge", {"ids": ["fixed-id"]})
        self.assertEqual(self.runtime.control("inbox", {}), [])

    def test_ambiguous_queue_delivery_is_not_blindly_retried(self):
        with patch("codex_runtime.subprocess.run", side_effect=subprocess.TimeoutExpired("codex queue", 20)):
            result = self.runtime.enqueue("test", "timeout-id")
        self.assertEqual(result["delivery"], "unknown")
        with self.assertRaisesRegex(ValueError, "ambiguous"):
            self.runtime.enqueue("test", "timeout-id", retry=True)

    def test_startup_failure_notifies_rld_and_retains_evidence(self):
        self.confirm()
        self.assign()
        write_json(self.runtime.cache / "leader.json", {"session_id": "11111111-1111-4111-8111-111111111111"})
        run = self.runtime.start_worker("P-test", "task")
        state = self.wait_run(run)
        self.assertEqual(state["status"], "failed")
        self.assertIn("inherit", state["error"])
        self.assertEqual(state["notification"]["delivery"], "queued")

    def test_hook_guards_paths_and_preserves_worker_leader_boundary(self):
        summary = self.runtime.summary()
        path = self.runtime.root / "docs/project/min-setup.v1.md"
        event = {"hook_event_name": "PreToolUse", "cwd": str(self.cwd), "tool_name": "apply_patch",
                 "tool_input": {"command": f"*** Begin Patch\n*** Update File: {path}\n@@\n-old\n+new\n*** End Patch"}}
        self.assertEqual(codex_hook.handle(event)["hookSpecificOutput"]["permissionDecision"], "deny")
        event.update(tool_name="Bash", tool_input={"command": f"echo bad >> '{self.runtime.marker['db']}'"})
        self.assertEqual(codex_hook.handle(event)["hookSpecificOutput"]["permissionDecision"], "deny")
        event["tool_input"]["command"] = f"ls -l '{self.runtime.marker['db']}'"
        self.assertEqual(codex_hook.handle(event), {})
        event["tool_input"]["command"] = f"sed -n '1,20p' '{path}'"
        self.assertEqual(codex_hook.handle(event), {})
        config = self.cwd / "research-tree.yaml"
        for command in (f"echo x > '{config}'", "sed -i s/a/b/ research-tree.yaml"):
            event["tool_input"]["command"] = command
            self.assertEqual(codex_hook.handle(event)["hookSpecificOutput"]["permissionDecision"], "deny", command)
        event.update(tool_name="apply_patch", tool_input={"command": f"*** Begin Patch\n*** Update File: {config}\n*** End Patch"})
        self.assertIn("由用户修改", codex_hook.handle(event)["hookSpecificOutput"]["permissionDecisionReason"])
        # A worker acts only as itself and the UI only reads, also from a shell; the RLD drives the tools.
        db_call = f"python tools/research_db.py --db '{self.runtime.marker['db']}'"
        cases = [("worker/root", f"{db_call} --actor rld/main update_run '{{}}'", True),
                 ("worker/root", f"{db_call} --actor worker/root update_run '{{}}'", False),
                 ("ui/ui", f"{db_call} --actor ui/ui decide '{{}}'", True),
                 ("ui/ui", f"{db_call} --actor ui/ui get '{{}}'", False),
                 ("worker/root", "python tools/research_tree.py phase --set confirmed", True),
                 ("rld/main", f"{db_call} --actor rld/main decide '{{}}'", False),
                 # reviews only through research_review: no direct pi / claude -p, no reviewer identity (09 §4)
                 ("rld/main", "pi -p --mode json --model openai/gpt-6-astra 'review this'", True),
                 ("rld/main", "cd x && env A=1 pi -p 'x'", True),
                 ("rld/main", "claude -p --output-format json 'x'", True),
                 ("rld/main", "claude --print 'x'", True),
                 ("rld/main", "claude --version", False),
                 ("rld/main", "echo pi", False),
                 ("rld/main", f"{db_call} --actor reviewer/pi register_review '{{}}'", True),
                 ("worker/root", "python tools/review_call.py --kind code_review --brief b --about H-0001", True),
                 ("rld/main", "python tools/review_call.py --kind code_review --brief b --about H-0001", False)]
        for actor, command, denied in cases:
            event.update(tool_name="Bash", tool_input={"command": command})
            with patch.dict(os.environ, {"RESEARCH_TREE_ACTOR": actor}):
                self.assertEqual(bool(codex_hook.handle(event)), denied, (actor, command))
        self.assertEqual(codex_hook.READ_METHODS, set(READ_METHODS))
        prior = read_json(self.runtime.cache / "leader.json")
        with patch.dict(os.environ, {"RESEARCH_TREE_ACTOR": "worker/root", "RESEARCH_TREE_PROJECT": str(self.cwd)}):
            codex_hook.handle({"hook_event_name": "SessionStart", "cwd": str(self.cwd), "session_id": "worker-thread", "model": "child"})
        self.assertEqual(prior, read_json(self.runtime.cache / "leader.json"))
        observed = json.loads((self.runtime.root / "logs/agent_models.jsonl").read_text().splitlines()[-1])
        self.assertEqual((observed["actor"], observed["event"], observed["model"]), ("worker/root", "observed", "child"))
        codex_hook.handle({"hook_event_name": "SessionStart", "cwd": str(self.cwd), "session_id": "other-main", "model": "other"})
        self.assertEqual(prior, read_json(self.runtime.cache / "leader.json"))

    def test_mcp_protocol_and_error_recovery_without_project_environment(self):
        requests = [
            {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {"protocolVersion": "2024-11-05"}},
            {"jsonrpc": "2.0", "method": "notifications/initialized"},
            {"jsonrpc": "2.0", "id": 2, "method": "tools/list"},
            {"jsonrpc": "2.0", "id": 3, "method": "tools/call", "params": {"name": "research_control", "arguments": {"action": "status"}}},
            {"jsonrpc": "2.0", "id": 4, "method": "ping"},
        ]
        proc = subprocess.run([sys.executable, str(ROOT / "tools/codex_mcp.py"), "--project", str(self.cwd)],
                              input="\n".join(map(json.dumps, requests)) + "\n", capture_output=True, text=True)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        responses = [json.loads(x) for x in proc.stdout.splitlines()]
        self.assertEqual([r["id"] for r in responses], [1, 2, 3, 4])
        self.assertEqual(len(responses[1]["result"]["tools"]), 6)  # with research_review (09 §4)
        self.assertTrue(responses[2]["result"]["isError"])
        self.assertEqual(responses[3]["result"], {})


class PrepareEntryTest(unittest.TestCase):
    def test_cli_prepare_needs_neither_project_python_nor_dependencies(self):
        with tempfile.TemporaryDirectory() as temp:
            bin_dir = Path(temp) / "bin"
            bin_dir.mkdir()
            (bin_dir / "uv").write_text('#!/bin/sh\nprintf "%s\\n" "$*" >> uv.log\n'
                                        '[ "$1" = init ] && echo "[project]" > pyproject.toml\nexit 0\n')
            (bin_dir / "uv").chmod(0o755)
            project = Path(temp) / "project"
            project.mkdir()
            command = [sys.executable, "-S", str(ROOT / "tools/codex_cli.py"), "--project", str(project),
                       "prepare", "--python", "3.12"]
            env = {**os.environ, "PATH": f"{bin_dir}{os.pathsep}{os.environ['PATH']}"}
            result = subprocess.run(command, cwd=project, env=env, capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            self.assertIn("init . --no-workspace --python=3.12", (project / "uv.log").read_text())
            self.assertEqual((project / "research-tree.yaml").read_bytes(), (ROOT / "schema/config.template.yaml").read_bytes())
            self.assertEqual((project / "plan.md").read_bytes(), (ROOT / "schema/plan.template.md").read_bytes())


if __name__ == "__main__":
    unittest.main()
