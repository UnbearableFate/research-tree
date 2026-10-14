"""Adapter tests run from the assembled plugin, including real supervisor subprocesses."""
from __future__ import annotations

import io
import json
import shlex
import shutil
import os
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch

# ruff: noqa: E402
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))

import codex_agent
import codex_hook
import codex_mcp
import research_tree
import project_config
from codex_runtime import Runtime
from metrics import minimal_documents
import build_site
from research_db import READ_METHODS, TASK_SECTIONS
from codex_state import actor_key, lock_busy, read_json, write_json


class AdapterTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.cwd = Path(self.temp.name) / "project with spaces"
        self.cwd.mkdir()
        (self.cwd / "plan.md").write_text("# 研究计划\n保留用户原话。\n", encoding="utf-8")
        # Host fixtures use the same sole supported config/protocol contract as production.
        specs, protocol = minimal_documents("accuracy", "higher", [])
        self.config = {"version": 3, "metric_specs": specs["metrics"],
                       "verification": {"screening_seeds": [1], "replication_seeds": [2, 3]}}
        (self.cwd / "research-tree.yaml").write_text(json.dumps(self.config))
        marker = research_tree.init(self.cwd, self.cwd / "plan.md", "P-test")
        self.runtime = Runtime(self.cwd)
        self.db = self.runtime.db()
        setup = self.doc("project/min-setup.v1.md", "min_setup")
        conf = research_tree.show_config(self.cwd)["effective"]
        protocol.update(project_config.protocol_requirements(conf))
        path = self.runtime.root / "docs/project/protocol.v1.json"
        path.write_text(json.dumps(protocol), encoding="utf-8")
        protocol_id = self.db.register_document("project/protocol.v1.json", "protocol", "protocol")
        self.db.set_document_current(protocol_id)
        self.db.create_project("P-test", "test", setup, "accuracy", "higher", [],
                               metric_spec_doc_id=marker["metric_spec"]["doc_id"], protocol_doc_id=protocol_id,
                               **project_config.db_fields(conf))
        self.plan = self.doc("project/reports/init-plan.v1.md", "report")
        request = self.doc("tasks/T-0001/request.v1.md", "task_request")
        self.task = self.db.create_task("harness", "architect", request, target_id="P-test")
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
    if os.environ.get('FAKE_LOCK'):  # whether an identity is free when its event reaches the Leader
        import fcntl
        with open(os.environ['FAKE_LOCK'], 'a') as lock:
            try:
                fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
                held = 'free'
            except BlockingIOError:
                held = 'held'
        with (base / 'queue-lock.log').open('a') as out:
            out.write(held + '\n')
    sys.exit(int(os.environ.get('FAKE_QUEUE_EXIT', '0')))
prompt = sys.stdin.read()
if os.environ.get('FAKE_CODEX_FAIL'):
    print('simulated failure', file=sys.stderr)
    sys.exit(3)
thread = args[args.index('resume') + 1] if 'resume' in args else str(uuid.uuid4())
print(json.dumps({'type':'thread.started', 'thread_id':thread}), flush=True)
if os.environ.get('FAKE_CODEX_BACKGROUND'):  # a job the turn's shell leaves running (nohup ... &) inherits its fds
    import subprocess
    subprocess.Popen(['sleep', os.environ['FAKE_CODEX_BACKGROUND']], close_fds=False, start_new_session=True,
                     stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
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
        research_tree.log_agent_model(self.runtime.root, {"agent": "11111111-1111-4111-8111-111111111111",
                                                          "actor": "rld/main", "event": "observed",
                                                          "model": "fixture-model"})
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
        self.db.assign_architect()
        self.db.update_task(self.task, assignee_id="root")

    def start_architect(self, task, **kwargs):
        return self.runtime.control("architect", {"node_id": "P-test", "task": task, **kwargs})

    def wait_run(self, run):
        path = Path(run["directory"]) / "state.json"
        for _ in range(500):
            state = read_json(path)
            # a non-UI turn's end-of-turn event follows the lock's release
            if state.get("status") in {"completed", "failed", "interrupted"} and not lock_busy(self.runtime.cache / "agents" / f"{actor_key(run['actor'])}.lock") \
                    and (run["actor"] == "ui/ui" or "notification" in state):
                return state
            time.sleep(0.02)
        self.fail(f"supervisor did not finish: {read_json(path)}")

    def test_confirmation_persists_verbatim_config_and_gates_workers(self):
        with self.assertRaisesRegex(ValueError, "confirmed"):
            self.start_architect("task")
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
        with self.assertRaisesRegex(ValueError, "assign_architect"):
            self.start_architect("implement")

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

    def test_confirm_request_refuses_a_failed_scope_preflight(self):
        with patch.object(research_tree, "discovery_blocks_confirmation", return_value="initial scope preflight unavailable"):
            with self.assertRaisesRegex(ValueError, "scope preflight"):
                self.runtime.post({"type": "confirm_request", "text": "确认？", "docs": ["project/reports/init-plan.v1.md"]})
        self.assertEqual(self.runtime.marker["phase"], "planning")

    def test_post_text_boundary_preserves_rejected_messages(self):
        before = self.runtime.chat()
        for text in ("", "a" * 201, None, 123):
            with self.assertRaisesRegex(ValueError, "1..200"):
                self.runtime.post({"type": "notice", "text": text})
        self.assertEqual(self.runtime.chat(), before)
        for text in ("a", "😀" * 200):
            self.runtime.post({"type": "notice", "text": text})
        self.assertEqual([r["text"] for r in self.runtime.chat()[len(before):]], ["a", "😀" * 200])

    def test_research_review_handler_returns_ticket_without_waiting(self):
        import review_call
        args = {"kind": "code_review", "brief": "docs/project/min-setup.v1.md", "about": "P-test"}
        worker = Runtime(self.cwd, "architect/root")
        with self.assertRaisesRegex(ValueError, "only the Leader"):
            worker.dispatch("research_review", args)
        with patch.object(review_call, "start_job", return_value="RJ-0123456789ab") as start, \
                patch.object(review_call, "wait_job", side_effect=AssertionError("start must never wait")):
            result = self.runtime.dispatch("research_review", args)
        self.assertTrue(result["pending"])
        self.assertEqual(result["ticket"], "RJ-0123456789ab")
        self.assertEqual(start.call_args.args[:2], (self.cwd, self.runtime.root))
        self.assertIn("--kind", start.call_args.args[2])
        with patch.object(review_call, "start_job", side_effect=review_call.ReviewError("REVIEW_UNAVAILABLE", "fixture")):
            with self.assertRaisesRegex(ValueError, "REVIEW_UNAVAILABLE"):
                self.runtime.dispatch("research_review", args)

    def test_research_review_ticket_collects_a_background_review(self):
        """A review started as a background job (review_call.py --background) is collected with its ticket."""
        jobs = self.runtime.root / "cache/reviews/jobs"
        jobs.mkdir(parents=True)
        answer = {"ok": True, "result": {"review_id": "D-0099", "result": "PROCEED"}}
        (jobs / "RJ-0123456789ab.json").write_text(json.dumps({"ticket": "RJ-0123456789ab", "argv": [],
                                                               "status": "done", "started_at": "t", "answer": answer}))
        self.assertEqual(self.runtime.dispatch("research_review", {"ticket": "RJ-0123456789ab"}), answer["result"])
        with self.assertRaisesRegex(ValueError, "not a review job ticket"):
            self.runtime.dispatch("research_review", {"ticket": "nope"})
        with self.assertRaisesRegex(ValueError, "needs kind, brief, about"):
            self.runtime.dispatch("research_review", {})

    def test_a_new_main_session_learns_the_supported_takeover(self):
        """S0 final review: after the previous CLI ended, a new main session was refused as Leader and answered
        read-only; the hook now tells the model (not only the person) how to take over with attach."""
        first = codex_hook.handle({"hook_event_name": "SessionStart", "cwd": str(self.cwd),
                                   "session_id": "22222222-2222-4222-8222-222222222222", "model": "fixture-model"})
        context = first["hookSpecificOutput"]["additionalContext"]
        self.assertIn("research_control attach", context)
        self.assertIn("22222222-2222-4222-8222-222222222222", context)
        with self.assertRaisesRegex(ValueError, "runs fixture-model .*not gpt-6.1-sol"):  # the caller's word never sets it
            self.runtime.control("attach", {"session_id": "22222222-2222-4222-8222-222222222222", "model": "gpt-6.1-sol"})
        with self.assertRaisesRegex(ValueError, "no observed model"):
            self.runtime.control("attach", {"session_id": "33333333-3333-4333-8333-333333333333"})
        self.assertEqual(self.runtime.control("attach", {"session_id": "22222222-2222-4222-8222-222222222222"})["model"],
                         "fixture-model")
        again = codex_hook.handle({"hook_event_name": "SessionStart", "cwd": str(self.cwd),
                                   "session_id": "22222222-2222-4222-8222-222222222222", "model": "fixture-model"})
        self.assertNotIn("attach(", again["hookSpecificOutput"]["additionalContext"])

    def test_planning_prompt_gives_the_effective_project_fields(self):
        import codex_prompts
        conf = project_config.parse((ROOT / "schema/config.template.yaml").read_text())
        text = codex_prompts.planning({"plan_instruction": "D-1", "root": "/r", "project_id": "P-x"}, conf)
        for key, value in project_config.db_fields(conf).items():
            self.assertIn(json.dumps(key) + ": " + json.dumps(value), text)
        self.assertIn("不要从 yaml 原样抄写", text)
        self.assertNotIn("require_precheck", text)

    def test_config_apply_passes_the_users_metric_spec_replacement(self):
        with patch("research_tree.apply_config", return_value={"new_version": False, "updated_fields": {}}) as apply:
            self.runtime.control("config", {"apply": True, "words": "/config apply --replace-metric-spec",
                                            "replace_metric_spec": True})
        self.assertTrue(apply.call_args.kwargs["replace_metric_spec"])

    def test_review_deadlines_leave_time_to_return_the_runtime_failure(self):
        from review_call import MAX_CALL_S
        client_timeout = json.loads((ROOT / ".mcp.json").read_text())["mcpServers"]["research_tree"]["tool_timeout_sec"]
        spec = {"project": str(self.cwd), "actor": "architect/root", "model": {"model": "fixture-model"}}
        argv = codex_agent.command(spec, self.cwd)
        configs = dict(arg.split("=", 1) for arg in argv if arg.startswith("mcp_servers."))
        self.assertEqual(json.loads(configs["mcp_servers.research_tree.tool_timeout_sec"]), client_timeout)
        python = self.cwd / ".venv/bin/python"
        python.parent.mkdir(parents=True)
        python.symlink_to(sys.executable)
        failure = {"ok": False, "error": "REVIEW_UNAVAILABLE: the review call reached its overall deadline"}
        with patch("codex_mcp.subprocess.run", return_value=subprocess.CompletedProcess([], 1, json.dumps(failure), "")) as run:
            self.assertEqual(codex_mcp.run_request(self.cwd, "rld/main", "research_review",
                             {"kind": "code_review", "brief": "docs/request.md", "about": "P-test"}), failure)
        self.assertLess(run.call_args.kwargs["timeout"], MAX_CALL_S)  # detached model work is outside the RPC wait
        self.assertLess(run.call_args.kwargs["timeout"], client_timeout)

    def test_worker_honors_native_full_access_and_ui_remains_read_only(self):
        config_dir = self.cwd / "isolated-codex"
        config_dir.mkdir()
        config = config_dir / "config.toml"
        spec = {"project": str(self.cwd), "actor": "architect/root", "model": {"model": "fixture-model"}}
        with patch.dict(os.environ, {"CODEX_HOME": str(config_dir)}):
            self.assertIn('sandbox_mode="workspace-write"', codex_agent.command(spec, self.cwd))
            config.write_text('sandbox_mode = "danger-full-access"\n')
            argv = codex_agent.command(spec, self.cwd)
            self.assertIn('sandbox_mode="danger-full-access"', argv)
            forwarded = next(a.split("=", 1)[1] for a in argv if a.startswith("mcp_servers.research_tree.env_vars="))
            forwarded_names = set(json.loads(forwarded))
            self.assertTrue({"CODEX_HOME", "CLAUDE_CONFIG_DIR", "PI_CODING_AGENT_DIR"} <= forwarded_names)
            spec["actor"] = "ui/ui"
            self.assertIn('sandbox_mode="read-only"', codex_agent.command(spec, self.cwd))
            spec["actor"] = "explorer/main"
            self.assertIn('sandbox_mode="read-only"', codex_agent.command(spec, self.cwd))
            config.write_text('sandbox_mode = "workspace-write"\n')
            spec["actor"] = "architect/root"
            self.assertIn('sandbox_mode="workspace-write"', codex_agent.command(spec, self.cwd))
        manifest_names = set(json.loads((ROOT / ".mcp.json").read_text())["mcpServers"]["research_tree"]["env_vars"])
        self.assertEqual(forwarded_names, manifest_names)

    def test_bound_roles_cannot_impersonate_or_control_execution(self):
        ui = Runtime(self.cwd, "ui/ui")
        with self.assertRaisesRegex(ValueError, "only read"):
            ui.dispatch("research_db", {"method": "update_project", "kwargs": {"title": "oops"}})
        for action in ("worker", "confirm", "instruction", "attach", "acknowledge"):
            with self.assertRaisesRegex(ValueError, "only RLD"):
                ui.control(action, {})
        with self.assertRaisesRegex(ValueError, "unexpected"):
            codex_mcp.run_request(self.cwd, "architect/root", "research_db", {"actor": "rld/main", "method": "help"})
        self.confirm()
        self.assign()
        worker = Runtime(self.cwd, "architect/root")
        with self.assertRaisesRegex(Exception, "requires role rld"):
            worker.dispatch("research_db", {"method": "update_project", "kwargs": {"title": "oops"}})
        worker.dispatch("research_db", {"method": "update_task", "kwargs": {"task_id": self.task, "status": "in_progress"}})
        self.assertEqual(self.db.get(self.task)["status"], "in_progress")
        with self.assertRaisesRegex(ValueError, "failure/blocker: alert"):
            worker.dispatch("research_message", {"type": "blocker", "text": "test"})
        for arguments in ({}, {"type": "alert"}, {"text": "test"}):
            with self.assertRaisesRegex(ValueError, "needs type and text, or resend"):
                worker.dispatch("research_message", arguments)
        alert = worker.dispatch("research_message", {"type": "alert", "text": "test blocker", "about": [self.task]})
        self.assertEqual(alert["message"]["from"], "architect/root")

    def test_advisors_are_real_bound_read_only_sessions_with_distinct_messages(self):
        for role in ("explorer", "analyst"):
            with self.subTest(role=role):
                started = self.runtime.control(role, {"task": "Read the current evidence and propose the next experiment."})
                self.assertEqual(started["actor"], f"{role}/main")
                state = self.wait_run(started)
                self.assertEqual(state["status"], "completed", state)
                advisor = Runtime(self.cwd, started["actor"])
                self.assertEqual(advisor.dispatch("research_db", {"method": "get", "kwargs": {"entity_id": "P-test"}})["id"], "P-test")
                for method in ("create_experiment", "register_document", "update_task", "update_project", "decide"):
                    with self.assertRaisesRegex(ValueError, "only read"):
                        advisor.dispatch("research_db", {"method": method, "kwargs": {}})
                for action in ("worker", "architect", "explorer", "analyst", "confirm", "instruction", "attach", "acknowledge"):
                    with self.assertRaisesRegex(ValueError, "only RLD"):
                        advisor.control(action, {})
                with self.assertRaisesRegex(ValueError, "only the Leader"):
                    advisor.dispatch("research_review", {})
                with self.assertRaisesRegex(ValueError, "only a node"):
                    advisor.control("commit", {"paths": ["x"], "message": "forged"})
                with self.assertRaisesRegex(ValueError, "cannot switch"):
                    codex_mcp.run_request(self.cwd, started["actor"], "research_db", {"project": str(self.cwd.parent), "method": "get"})
                with patch.dict(os.environ, {"RESEARCH_TREE_ACTOR": started["actor"], "RESEARCH_TREE_PROJECT": str(self.cwd)}):
                    denial = codex_hook.handle({"hook_event_name": "PreToolUse", "cwd": str(self.cwd), "tool_name": "apply_patch",
                                               "tool_input": {"input": "*** Begin Patch\n*** Add File: proposed.py\n+x\n*** End Patch"}})
                    self.assertEqual(denial["hookSpecificOutput"]["permissionDecision"], "deny")
                    context = codex_hook.handle({"hook_event_name": "SessionStart", "cwd": str(self.cwd)})["hookSpecificOutput"]["additionalContext"]
                    self.assertIn(started["actor"], context)
                    self.assertNotIn("确认后先assign_worker", context)
                message = advisor.dispatch("research_message", {"type": "question", "text": "Check another matched seed?"})
                self.assertEqual(message["message"]["id"], f"{role}--main-0001")
                self.assertEqual(advisor.dispatch("research_message", {"resend": message["message"]["id"]})["message"], message["message"])
                spec = read_json(Path(started["directory"]) / "spec.json")
                self.assertIn('sandbox_mode="read-only"', codex_agent.command(spec, self.cwd))
                self.assertIn(role, spec["prompt"])
        self.assertFalse(self.db.get("P-test").get("architect_agent_id"))
        self.assertEqual(self.db.find("experiment"), [])
        self.assertEqual(self.runtime.marker["phase"], "planning")

    def test_architect_is_root_only_and_root_worker_alias_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "confirmed"):
            self.runtime.control("architect", {"node_id": "P-test", "task": "Build harness"})
        self.confirm()
        self.assign()
        with self.assertRaisesRegex(ValueError, "root"):
            self.runtime.control("architect", {"node_id": "H-0001", "task": "Take over hypothesis"})
        with self.assertRaisesRegex(ValueError, "invalid adapter actor"):
            actor_key("worker/root")
        with self.assertRaisesRegex(ValueError, "hypotheses only"):
            self.runtime.control("worker", {"node_id": "P-test", "task": "Duplicate root"})
        hold = Path(self.temp.name) / "hold"
        hold.touch()
        started = self.runtime.control("architect", {"node_id": "P-test", "task": "Build shared harness and baseline"})
        self.assertEqual(started["actor"], "architect/root")
        with self.assertRaisesRegex(ValueError, "live"):
            self.start_architect("Duplicate root", restart=True)
        hold.unlink()
        self.assertEqual(self.wait_run(started)["status"], "completed")
        architect = Runtime(self.cwd, "architect/root")
        architect.dispatch("research_db", {"method": "update_task", "kwargs": {"task_id": self.task, "status": "in_progress"}})
        self.assertEqual(self.db.get(self.task)["status"], "in_progress")
        self.assertIsNone(codex_hook.call_block([("research_db.py", "architect/root", "update_task")], "architect/root"))
        self.assertIsNotNone(codex_hook.call_block([("research_db.py", "rld/main", "update_task")], "architect/root"))

    def test_hypothesis_worker_uses_its_own_assignment_and_model(self):
        self.confirm()
        task = {"id": "T-0100", "target_id": "H-0001", "assignee_role": "worker", "assignee_id": "h0001", "status": "open"}
        package = {"actor": "worker/h0001", "node": {"id": "H-0001"}, "tasks": [task],
                   "branch": {"worktree_path": str(self.cwd)}, "agent_id": None}
        with patch.object(self.runtime, "db") as db, patch.object(self.runtime, "start_agent", return_value={"started": True}) as start:
            db.return_value.resume_package.return_value = package
            db.return_value.find.side_effect = lambda table: [task] if table == "task" else [{"max_parallel_workers": 2}]
            self.assertEqual(self.runtime.control("worker", {"node_id": "H-0001", "task": "Screen this hypothesis"}), {"started": True})
            self.assertEqual(start.call_args.args[0], "worker/h0001")
            self.assertEqual(start.call_args.args[2], research_tree.show_config(self.cwd)["effective"]["models"]["worker"])
            self.assertEqual(start.call_args.kwargs["node_id"], "H-0001")
            task["assignee_role"] = "architect"
            with self.assertRaisesRegex(ValueError, "actionable node task"):
                self.runtime.control("worker", {"node_id": "H-0001", "task": "Do not borrow an architect task"})
        with self.assertRaisesRegex(ValueError, "hypotheses only"):
            self.runtime.control("worker", {"node_id": "P-test", "task": "Do not use the removed root alias"})

    def test_committed_write_survives_display_failure_and_ui_is_on_demand(self):
        self.confirm()
        self.assign()
        worker = Runtime(self.cwd, "architect/root")
        with patch.object(build_site, "summary_or_empty", side_effect=RuntimeError("display unavailable")), \
                patch.object(build_site, "build", side_effect=AssertionError("write must not render")):
            worker.dispatch("research_db", {"method": "update_task", "kwargs": {"task_id": self.task, "status": "in_progress"}})
        self.assertEqual(self.db.get(self.task)["status"], "in_progress")
        self.assertTrue(read_json(self.runtime.cache / "summary-error.json")["stale"])
        self.assertEqual(self.runtime.agents(), [])  # neither confirmation nor writes start a persistent UI
        with patch.object(build_site, "build", return_value={"meta": {"data_version": 123}}) as render:
            page = self.runtime.control("build", {})
        self.assertEqual(page["data_version"], 123)
        render.assert_called_once()
        self.assertEqual(self.runtime.agents(), [])

    def test_pending_review_collection_is_nonblocking_and_does_not_restart(self):
        import review_call
        answer = {"ok": True, "pending": True, "ticket": "RJ-0123456789ab"}
        with patch.object(review_call, "start_job", side_effect=AssertionError("never restart")), \
                patch.object(review_call, "wait_job", return_value={}) as wait, \
                patch.object(review_call, "_job_answer", return_value=(answer, 0)):
            self.assertEqual(self.runtime.dispatch("research_review", {"ticket": answer["ticket"]}), answer)
        self.assertEqual(wait.call_args.args, (self.runtime.root, answer["ticket"], 0))
        with self.assertRaisesRegex(ValueError, "only its ticket"):
            self.runtime.dispatch("research_review", {"ticket": answer["ticket"], "kind": "code_review"})

    def test_removed_roles_and_control_actions_are_rejected(self):
        for actor in ("assistant/lens_test", "assistant/web_builder", "worker/root", "architect/other", "explorer/other"):
            with self.subTest(actor=actor), self.assertRaisesRegex(ValueError, "invalid adapter actor"):
                Runtime(self.cwd, actor)
        self.assertNotIn("lens", self.runtime.control("help", {}))
        with self.assertRaisesRegex(ValueError, "unknown control action"):
            self.runtime.control("lens", {"lens": "contradiction", "task": "generate"})
        review = next(tool for tool in codex_mcp.TOOLS if tool["name"] == "research_review")
        self.assertEqual(set(review["inputSchema"]["properties"]["kind"]["enum"]),
                         {"code_review", "ablation_plan", "candidate_recheck"})

    def test_old_project_marker_is_rejected_without_writing_it(self):
        marker_path = self.cwd / ".research-tree.json"
        original = marker_path.read_bytes()
        marker = json.loads(original)
        del marker["format_version"]
        marker_path.write_text(json.dumps(marker))
        before = marker_path.read_bytes()
        try:
            with self.assertRaisesRegex(Exception, "UNSUPPORTED_PROJECT_VERSION"):
                self.runtime.control("status", {})
            with self.assertRaisesRegex(Exception, "UNSUPPORTED_PROJECT_VERSION"):
                codex_hook.handle({"hook_event_name": "SessionStart", "cwd": str(self.cwd), "model": "fixture",
                                   "session_id": "33333333-3333-4333-8333-333333333333"})
            self.assertEqual(marker_path.read_bytes(), before)
        finally:
            marker_path.write_bytes(original)

    def test_direct_main_instruction_preserves_words_and_scope(self):
        words = "暂停新实验；已提交的作业先核对状态。"
        result = self.runtime.control("instruction", {"words": words, "understanding": "暂停新提交，核对原作业。",
                                                      "kind": "暂停", "about": ["P-test"]})
        self.assertIn(words, (self.runtime.root / "docs" / result["path"]).read_text())
        self.assertEqual(self.db.get(result["doc_id"])["doc_type"], "user_instruction")
        self.assertEqual(self.runtime.marker["phase"], "planning")
        with self.assertRaisesRegex(ValueError, "verbatim"):
            self.runtime.control("instruction", {"words": "", "understanding": "pause"})

    def test_display_model_names_reach_codex_exec_for_all_agent_roles(self):
        for role, display, expected in (
            ("ui", "GPT 6 Luna", "gpt-6-luna"),
            ("explorer", "GPT 6.1 Sol", "gpt-6.1-sol"),
            ("analyst", "GPT-6 Sol", "gpt-6-sol"),
            ("architect", "GPT-6 Sol", "gpt-6-sol"),
        ):
            with self.subTest(role=role):
                config = {**self.config, "models": {role: {"model": display, "effort": "high"}}}
                original = json.dumps(config)
                (self.cwd / "research-tree.yaml").write_text(original)
                with patch.dict(os.environ, {"FAKE_CODEX_REPLY": json.dumps({"reply": "收到", "actions": []})}):
                    if role == "ui":
                        run = self.runtime.start_ui("查看计划")
                    elif role in {"explorer", "analyst"}:
                        run = self.runtime.control(role, {"task": "Read current evidence and return advice."})
                    else:
                        self.confirm()
                        self.assign()
                        run = self.start_architect("实现根节点")
                    state = self.wait_run(run)
                self.assertEqual(state["status"], "completed", state)
                calls = [json.loads(line) for line in (Path(self.temp.name) / "calls.jsonl").read_text().splitlines()]
                argv = [call for call in calls if call[0] == "exec"][-1]
                self.assertEqual(argv[argv.index("--model") + 1], expected)
                self.assertIn('model_reasoning_effort="high"', argv)
                self.assertEqual((self.cwd / "research-tree.yaml").read_text(), original)
                records = [json.loads(line) for line in (self.runtime.root / "logs/agent_models.jsonl").read_text().splitlines()]
                requested = [record for record in records if record["event"] == "requested" and record["actor"] == run["actor"]][-1]
                self.assertEqual((requested["model"], requested["effort"]), (expected, "high"))

    def test_architect_binding_followup_and_resume_use_same_identity(self):
        self.confirm()
        self.assign()
        hold = Path(self.temp.name) / "hold"
        hold.touch()
        first = self.start_architect("实现根节点")
        for _ in range(300):
            if read_json(Path(first["directory"]) / "state.json").get("thread_id"):
                break
            time.sleep(0.02)
        queued = self.start_architect("后续任务")
        self.assertEqual(queued["delivery"], "queued")
        with self.assertRaisesRegex(ValueError, "live"):
            self.start_architect("replacement", restart=True)
        hold.unlink()
        state = self.wait_run(first)
        self.assertEqual(state["status"], "completed", state)
        self.assertEqual(self.db.get("P-test")["architect_agent_id"], state["thread_id"])
        second = self.start_architect("继续核对")
        resumed = self.wait_run(second)
        self.assertEqual(resumed["thread_id"], state["thread_id"])
        self.assertEqual(resumed["status"], "completed", resumed)
        calls = [json.loads(x) for x in (Path(self.temp.name) / "calls.jsonl").read_text().splitlines()]
        execs = [c for c in calls if c[0] == "exec"]
        self.assertEqual(execs[0][execs[0].index("--model") + 1], "fixture-model")
        self.assertTrue(any("architect/root" in x for x in execs[0]))
        self.assertIn("resume", execs[1])
        self.assertFalse(any("bypass" in arg for call in calls for arg in call))
        # a background session cannot answer approval prompts: the plugin's own MCP server is pre-approved
        self.assertIn('mcp_servers.research_tree.default_tools_approval_mode="approve"', execs[0])

    def test_architect_failure_is_visible_and_does_not_look_delivered(self):
        self.confirm()
        self.assign()
        with patch.dict(os.environ, {"FAKE_CODEX_FAIL": "1"}):
            run = self.start_architect("task")
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
        with self.assertRaisesRegex(ValueError, "questions belong in open"):
            ui.dispatch("requirement_draft", {"title": "优化器范围", "fields": {"authorization": "未授权"},
                                              "messages": [source["id"]]})
        self.assertEqual(research_tree.list_requirements(self.cwd), [])
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

    def test_invalid_ui_reference_preserves_draft_and_failed_action_without_replay(self):
        source = self.runtime.say("user", "先保存草稿，澄清后再提交。")
        ui = Runtime(self.cwd, "ui/ui")
        draft = ui.dispatch("requirement_draft", {"title": "图表", "fields": {"open": "待澄清"},
                                                  "messages": [source["id"]], "about": ["P-test"]})
        directory = self.runtime.cache / "runs/ui-invalid-reference"
        write_json(directory / "spec.json", {"actor": "ui/ui", "user_message": source})
        response = {"reply": "请澄清 seed。", "actions": [{"type": "question", "text": "seed?",
                    "docs": [], "about": [draft["id"]], "req": ""}]}
        before = self.runtime.marker["phase"]
        result = self.runtime.apply_ui(directory, response)
        self.assertEqual(result[0]["status"], "failed", result)
        self.assertIn(draft["id"], result[0]["error"])
        self.assertEqual(read_json(directory / "actions.json"), result)
        self.assertEqual(research_tree.list_requirements(self.cwd)[0], draft)
        self.assertEqual(self.runtime.marker["phase"], before)
        self.assertEqual(self.runtime.control("inbox", {}), [])
        with self.assertRaisesRegex(ValueError, "already attempted"):
            self.runtime.apply_ui(directory, response)
        self.assertFalse((self.runtime.root / "docs/requirements/REQ-0001.v1.md").exists())

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
        run = self.start_architect("task")
        state = self.wait_run(run)
        self.assertEqual(state["status"], "failed")
        self.assertIn("inherit", state["error"])
        self.assertEqual(state["notification"]["delivery"], "queued")

    def install_guard_python(self):
        # A fixture-local launcher uses this test environment without installing anything.
        python = self.cwd / ".venv/bin/python"
        python.parent.mkdir(parents=True, exist_ok=True)
        python.write_text(f"#!/bin/sh\nexec '{sys.executable}' \"$@\"\n")
        python.chmod(0o755)

    def test_codex_file_guard_uses_fresh_authority_without_the_display_cache(self):
        self.install_guard_python()
        self.runtime.summary()
        current = self.runtime.root / "docs/project/fresh.v1.md"
        self.doc("project/fresh.v1.md", "report")
        (self.runtime.cache / "summary.json").write_text("{broken presentation cache")
        event = {"hook_event_name": "PreToolUse", "cwd": str(self.cwd), "tool_name": "Write",
                 "tool_input": {"file_path": str(current)}}
        self.assertIn("新版本", codex_hook.handle(event)["hookSpecificOutput"]["permissionDecisionReason"])
        event["tool_input"]["file_path"] = str(self.cwd / "new.py")
        self.assertEqual(codex_hook.handle(event), {})
        for response in (subprocess.CompletedProcess([], 2, "", "database unavailable"),
                         subprocess.CompletedProcess([], 0, "{}", ""),
                         subprocess.CompletedProcess([], 0, json.dumps({"db_path": "other", "guards": {"frozen_docs": [], "harness": []}}), "")):
            with patch.object(codex_hook.subprocess, "run", return_value=response):
                self.assertIn("无法核验", codex_hook.handle(event)["hookSpecificOutput"]["permissionDecisionReason"])
        event.update(tool_name="Bash", tool_input={"command": "cat notes.txt"})
        with patch.object(codex_hook.subprocess, "run", side_effect=AssertionError("read-only tools need no file authorization")):
            self.assertEqual(codex_hook.handle(event), {})

    def test_hook_guards_paths_and_preserves_worker_leader_boundary(self):
        self.install_guard_python()
        self.runtime.summary()
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
        # the Leader edits the configuration when the user asks; a worker never does
        config = self.cwd / "research-tree.yaml"
        edit = {"command": f"*** Begin Patch\n*** Update File: {config}\n*** End Patch"}
        for actor, denied in (("rld/main", False), ("architect/root", True)):
            with patch.dict(os.environ, {"RESEARCH_TREE_ACTOR": actor}):
                for command in (f"echo x > '{config}'", "sed -i s/a/b/ research-tree.yaml"):
                    event.update(tool_name="Bash", tool_input={"command": command})
                    answer = codex_hook.handle(event).get("hookSpecificOutput", {}).get("permissionDecision")
                    self.assertEqual(answer == "deny", denied, (actor, command))
                event.update(tool_name="apply_patch", tool_input=edit)
                reason = codex_hook.handle(event).get("hookSpecificOutput", {}).get("permissionDecisionReason", "")
                self.assertEqual("按用户指示的 Leader" in reason, denied, actor)
        # A worker acts only as itself and the UI only reads, also from a shell; the RLD drives the tools.
        db_call = f"python tools/research_db.py --db '{self.runtime.marker['db']}'"
        cases = [("architect/root", f"{db_call} --actor rld/main update_run '{{}}'", True),
                 ("architect/root", f"{db_call} --actor architect/root update_run '{{}}'", False),
                 ("ui/ui", f"{db_call} --actor ui/ui decide '{{}}'", True),
                 ("ui/ui", f"{db_call} --actor ui/ui get '{{}}'", False),
                 ("ui/ui", f"{db_call} --actor rld/main get '{{}}'", True),
                 ("ui/ui", f"{db_call} --actor architect/root get '{{}}'", True),
                 ("explorer/main", f"{db_call} --actor rld/main get '{{}}'", True),
                 ("explorer/main", f"{db_call} --actor explorer/main get '{{}}'", False),
                 ("architect/root", "python tools/research_tree.py phase --set confirmed", True),
                 ("rld/main", f"{db_call} --actor rld/main decide '{{}}'", False),
                 # reviews only through research_review: no direct pi / claude -p, no reviewer identity (09 §4)
                 ("rld/main", "pi -p --mode json --model openai/gpt-6-astra 'review this'", True),
                 ("rld/main", "cd x && env A=1 pi -p 'x'", True),
                 ("rld/main", "claude -p --output-format json 'x'", True),
                 ("rld/main", "claude --print 'x'", True),
                 ("rld/main", "claude --version", False),
                 ("rld/main", "echo pi", False),
                 ("rld/main", f"{db_call} --actor reviewer/pi register_review '{{}}'", True),
                 ("architect/root", "python tools/review_call.py --kind code_review --brief b --about H-0001", True),
                 ("rld/main", "python tools/review_call.py --kind code_review --brief b --about H-0001", False)]
        for actor, command, denied in cases:
            event.update(tool_name="Bash", tool_input={"command": command})
            with patch.dict(os.environ, {"RESEARCH_TREE_ACTOR": actor}):
                self.assertEqual(bool(codex_hook.handle(event)), denied, (actor, command))
        self.assertEqual(codex_hook.READ_METHODS, set(READ_METHODS))
        prior = read_json(self.runtime.cache / "leader.json")
        with patch.dict(os.environ, {"RESEARCH_TREE_ACTOR": "architect/root", "RESEARCH_TREE_PROJECT": str(self.cwd)}):
            worker_context = codex_hook.handle({"hook_event_name": "SessionStart", "cwd": str(self.cwd), "session_id": "worker-thread", "model": "child"})["hookSpecificOutput"]["additionalContext"]
        self.assertIn("architect/root", worker_context)
        self.assertNotIn("用research_control inbox", worker_context)
        self.assertNotIn("需要用户决定时post_to_ui", worker_context)
        self.assertEqual(prior, read_json(self.runtime.cache / "leader.json"))
        observed = json.loads((self.runtime.root / "logs/agent_models.jsonl").read_text().splitlines()[-1])
        self.assertEqual((observed["actor"], observed["event"], observed["model"]), ("architect/root", "observed", "child"))
        for actor in ("ui/ui", "explorer/main", "explorer/main", "analyst/main"):
            with patch.dict(os.environ, {"RESEARCH_TREE_ACTOR": actor, "RESEARCH_TREE_PROJECT": str(self.cwd)}):
                context = codex_hook.handle({"hook_event_name": "SessionStart", "cwd": str(self.cwd)})["hookSpecificOutput"]["additionalContext"]
            self.assertIn(actor, context)
            self.assertIn("只读", context)
            self.assertNotIn("用research_control inbox", context)
            self.assertNotIn("确认后先assign_worker", context)
        with patch.dict(os.environ, {"RESEARCH_TREE_ACTOR": "rld/main"}):
            context = codex_hook.handle({"hook_event_name": "SessionStart", "cwd": str(self.cwd), "session_id": prior["session_id"]})["hookSpecificOutput"]["additionalContext"]
        self.assertIn("用research_control inbox", context)
        self.assertEqual(prior["session_id"], read_json(self.runtime.cache / "leader.json")["session_id"])
        codex_hook.handle({"hook_event_name": "SessionStart", "cwd": str(self.cwd), "session_id": "other-main", "model": "other"})
        self.assertEqual(prior["session_id"], read_json(self.runtime.cache / "leader.json")["session_id"])

    def test_copy_reads_protected_sources_but_guards_its_actual_destinations(self):
        self.install_guard_python()
        self.runtime.summary()
        config = self.cwd / "research-tree.yaml"
        current = self.runtime.root / "docs/project/min-setup.v1.md"
        fresh = self.runtime.root / "docs/project/config.v2.yaml"
        destination = self.cwd / "copies"
        destination.mkdir()
        # The real planning command writes new documents, then copies the user
        # configuration into a new version. Reading either source is allowed.
        allowed = (f"cp '{config}' '{fresh}'",
                   f"cat > '{fresh}' <<'EOF'\nnew draft\nEOF\ncp '{config}' '{fresh}'",
                   f"cp '{current}' '{destination}'",
                   f"cp '{config}' '{current}' '{destination}'",
                   f"cp -t '{destination}' '{config}' '{current}'",
                   f"cp --target-directory='{destination}' '{config}'")
        denied = (f"cp '{fresh}' '{config}'",
                  f"cp '{fresh}' '{current}'",
                  f"cp '{config}' '{self.cwd}'",
                  f"cp -t '{self.cwd}' '{config}'",
                  f"cp --target-directory='{current.parent}' '{current}'",
                  f"cp -T '{fresh}' '{config}'",
                  f"cp '{config}' '{fresh}'\nrm '{config}'")
        event = {"hook_event_name": "PreToolUse", "cwd": str(self.cwd), "tool_name": "exec_command"}
        # a node session, for which the configuration is protected too (the Leader may write it when the user asks)
        with patch.dict(os.environ, {"RESEARCH_TREE_ACTOR": "architect/root"}):
            for command, expected in [(c, False) for c in allowed] + [(c, True) for c in denied]:
                with self.subTest(command=command):
                    event["tool_input"] = {"cmd": command}
                    self.assertEqual(bool(codex_hook.handle(event)), expected)

    def test_shell_writes_reach_protected_files_as_the_shell_runs_them(self):
        """In-place option clusters, dd of=, wildcards, cd and exec_command's workdir, and apply_patch run from the
        shell reach the same protected files as a literal path does; reads and other writes stay allowed."""
        self.install_guard_python()
        self.runtime.summary()
        root = os.path.relpath(self.runtime.root, self.cwd)
        doc, db = f"{root}/docs/project/min-setup.v1.md", f"{root}/research_tree.db"
        patch_text = f"*** Begin Patch\n*** Update File: {doc}\n@@\n-old\n+it's new\n*** End Patch"
        code = self.cwd / "code"
        code.mkdir()
        cases = [(f"perl -pi -e 's/a/b/' {doc}", {}, True),
                 (f"sed -Ei 's/a/b/' {doc}", {}, True),
                 (f"sed -ni 's/a/b/p' {doc}", {}, True),
                 ("sed --in-place 's/a/b/' research-tree.yaml", {}, True),
                 (f"dd if=/dev/zero of={db} count=1", {}, True),
                 (f"rm -f {db}*", {}, True),
                 (f"sed -i 's/a/b/' {root}/docs/project/*.md", {}, True),
                 (f"cd {root} && echo x > research_tree.db", {}, True),
                 (f"cd {root}/docs/project && sed -i 's/a/b/' min-setup.v1.md", {}, True),
                 ("sed -i 's/a/b/' docs/project/min-setup.v1.md", {"workdir": str(self.runtime.root)}, True),
                 ('cd "$WORK" && rm -f notes.txt', {}, True),  # a directory only known when the shell runs
                 ("cd - && rm -f notes.txt", {}, True),
                 (f"apply_patch <<'EOF'\n{patch_text}\nEOF", {}, True),
                 (["apply_patch", patch_text], {}, True),
                 (f"sed -n 'p' {root}/docs/project/*.md", {}, False),
                 (f"dd if={db} of=code/copy.db", {}, False),
                 ("rm -f code/*.tmp", {}, False),
                 ("cd code && echo x > notes.txt", {}, False),
                 ('cd "$WORK" && ls notes.txt', {}, False),
                 ("sed -i 's/a/b/' min-setup.v1.md", {"workdir": str(code)}, False),
                 ("apply_patch <<'EOF'\n" + patch_text.replace(doc, "code/new.py") + "\nEOF", {}, False)]
        with patch.dict(os.environ, {"RESEARCH_TREE_ACTOR": "architect/root"}):
            for command, extra, denied in cases:
                with self.subTest(command=command, **extra):
                    tool, key = ("shell", "command") if isinstance(command, list) else ("exec_command", "cmd")
                    event = {"hook_event_name": "PreToolUse", "cwd": str(self.cwd), "tool_name": tool,
                             "tool_input": {key: command, **extra}}
                    self.assertEqual(bool(codex_hook.handle(event)), denied)

    def test_adapter_entry_points_and_in_process_records_stay_out_of_the_shell(self):
        """A session cannot act as the Leader through the adapter's own entry points, and no session forges the
        hook-observed model or the confirmed phase from a shell; the runtime never defaults to the Leader."""
        import codex_runtime
        runtime, cli, mcp, hook = (shlex.quote(str(ROOT / "tools" / name)) for name in
                                   ("codex_runtime.py", "codex_cli.py", "codex_mcp.py", "codex_hook.py"))
        cases = [("architect/root", f"python {runtime} --project ws --actor rld/main < request.json", True),
                 ("worker/h0001", f"python {cli} --project ws config apply", True),
                 ("explorer/main", f"python {mcp} --actor rld/main", True),
                 ("rld/main", f"python {cli} --project ws status", False),
                 ("rld/main", f"python3 {hook} < event.json", True),
                 ("rld/main", "python tools/research_tree.py agent-log --agent s --actor rld/main --event observed "
                              "--model m", True),
                 ("rld/main", "python tools/research_tree.py phase --set confirmed", True),
                 ("rld/main", "python tools/research_tree.py discovery status", False)]
        for actor, command, denied in cases:
            with self.subTest(actor=actor, command=command), patch.dict(os.environ, {"RESEARCH_TREE_ACTOR": actor}):
                event = {"hook_event_name": "PreToolUse", "cwd": str(self.cwd), "tool_name": "exec_command",
                         "tool_input": {"cmd": command}}
                self.assertEqual(bool(codex_hook.handle(event)), denied)
        request = json.dumps({"tool": "research_control", "arguments": {"action": "help"}})
        with patch.object(sys, "argv", ["codex_runtime.py", "--project", str(self.cwd)]), \
                patch("sys.stdin", io.StringIO(request)), patch("sys.stdout", io.StringIO()), \
                patch("sys.stderr", io.StringIO()), self.assertRaises(SystemExit):
            codex_runtime.main()

    def test_hook_finds_the_project_from_a_subdirectory(self):
        """A main session started in <ws>/code is still guarded and gets the project context."""
        code = self.cwd / "code"
        code.mkdir()
        db = os.path.relpath(self.runtime.marker["db"], code)
        with patch.dict(os.environ, {"RESEARCH_TREE_ACTOR": "rld/main"}):
            os.environ.pop("RESEARCH_TREE_PROJECT", None)
            denial = codex_hook.handle({"hook_event_name": "PreToolUse", "cwd": str(code), "tool_name": "exec_command",
                                        "tool_input": {"cmd": f"rm -f {shlex.quote(db)}"}})
            context = codex_hook.handle({"hook_event_name": "SessionStart", "cwd": str(code),
                                         "session_id": "11111111-1111-4111-8111-111111111111", "model": "fixture-model"})
        self.assertEqual(denial["hookSpecificOutput"]["permissionDecision"], "deny")
        self.assertIn("项目 P-test", context["hookSpecificOutput"]["additionalContext"])

    def test_confirmation_and_config_apply_carry_the_users_words(self):
        with patch("research_tree.apply_config", wraps=research_tree.apply_config) as apply:
            self.confirm()
        self.assertEqual(apply.call_args.kwargs["words"], "同意上面的立项计划。")
        for words in (None, "", "  ", ["应用配置"]):
            with self.subTest(words=words), self.assertRaisesRegex(ValueError, "user's request"):
                self.runtime.control("config", {"apply": True, "words": words})

    def test_identity_lock_stays_with_the_supervisor(self):
        """A job the turn leaves running does not keep its identity live, and the end-of-turn event reaches the
        Leader only once the identity is free for its next turn."""
        lock = self.runtime.cache / "agents" / f"{actor_key('explorer/main')}.lock"
        with patch.dict(os.environ, {"FAKE_CODEX_BACKGROUND": "3", "FAKE_LOCK": str(lock)}):
            run = self.runtime.control("explorer", {"task": "Read the current evidence and return advice."})
            path = Path(run["directory"]) / "state.json"
            for _ in range(500):
                if "notification" in read_json(path):
                    break
                time.sleep(0.02)
            self.assertEqual(read_json(path)["status"], "completed", read_json(path))
            self.assertFalse(lock_busy(lock))  # the background job is still running
        self.assertEqual((Path(self.temp.name) / "queue-lock.log").read_text().split(), ["free"])

    def test_advisor_keeps_its_thread_after_a_start_that_failed_before_thread_started(self):
        first = self.wait_run(self.runtime.control("explorer", {"task": "Survey the literature."}))
        with patch.dict(os.environ, {"FAKE_CODEX_FAIL": "1"}):
            failed = self.wait_run(self.runtime.control("explorer", {"task": "Continue the survey."}))
        self.assertEqual(failed["status"], "failed")
        self.assertNotIn("thread_id", failed)
        resumed = self.wait_run(self.runtime.control("explorer", {"task": "Continue the survey."}))
        self.assertEqual(resumed["thread_id"], first["thread_id"])
        calls = [json.loads(line) for line in (Path(self.temp.name) / "calls.jsonl").read_text().splitlines()]
        execs = [call for call in calls if call[0] == "exec"]
        self.assertEqual(execs[-1][execs[-1].index("resume") + 1], first["thread_id"])

    def test_init_in_live_session_observes_the_model_on_the_first_tool_event(self):
        fresh = self.cwd / "fresh"
        fresh.mkdir()
        (fresh / "plan.md").write_text("# A project initialized in an existing Codex session\n")
        shutil.copyfile(ROOT / "schema/config.template.yaml", fresh / "research-tree.yaml")
        event = {"hook_event_name": "SessionStart", "cwd": str(fresh),
                 "session_id": "fresh-main", "model": "gpt-6-luna"}
        with patch.dict(os.environ, {"RESEARCH_TREE_ACTOR": "rld/main", "RESEARCH_TREE_PROJECT": str(fresh)}):
            self.assertEqual(codex_hook.handle(event), {})  # no project at session startup
            marker = research_tree.init(fresh, fresh / "plan.md", "P-fresh")
            event["hook_event_name"] = "PostToolUse"
            codex_hook.handle(event)
            from review_call import leader_model
            self.assertEqual(leader_model(Path(marker["root"])), "gpt-6-luna")
            codex_hook.handle(event)
            log = Path(marker["root"]) / "logs/agent_models.jsonl"
            self.assertEqual(len(log.read_text().splitlines()), 1)
            event.pop("model")
            codex_hook.handle(event)
            self.assertEqual(leader_model(Path(marker["root"])), "gpt-6-luna")
            event["model"] = "gpt-6-astra"
            codex_hook.handle(event)
            self.assertEqual(leader_model(Path(marker["root"])), "gpt-6-astra")

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

    def test_mcp_server_survives_malformed_arguments_and_handler_failures(self):
        fresh = Path(self.temp.name) / "fresh"
        fresh.mkdir()
        requests = [
            {"jsonrpc": "2.0", "id": 1, "method": "tools/call", "params": {"name": "research_control", "arguments": {
                "project": str(fresh), "action": "init", "params": json.dumps({"plan": "plan.md"})}}},
            {"jsonrpc": "2.0", "id": 2, "method": "ping"},
        ]
        proc = subprocess.run([sys.executable, str(ROOT / "tools/codex_mcp.py"), "--project", str(self.cwd),
                               "--actor", "rld/main"], input="\n".join(map(json.dumps, requests)) + "\n",
                              capture_output=True, text=True)
        responses = [json.loads(x) for x in proc.stdout.splitlines()]
        self.assertEqual([r["id"] for r in responses], [1, 2], proc.stderr)
        self.assertTrue(responses[0]["result"]["isError"])
        self.assertIn("params", json.loads(responses[0]["result"]["content"][0]["text"])["error"])
        # any other failure while handling one request is that request's JSON-RPC error
        with patch.object(codex_mcp, "run_request", side_effect=AttributeError("fixture")), \
                patch("sys.stdin", io.StringIO("\n".join(map(json.dumps, requests)) + "\n")), \
                patch("sys.stdout", new_callable=io.StringIO) as out:
            codex_mcp.serve(self.cwd, "rld/main")
        answers = [json.loads(x) for x in out.getvalue().splitlines()]
        self.assertEqual([(a["id"], a.get("error", {}).get("code")) for a in answers], [(1, -32603), (2, None)])
        self.assertEqual(answers[1]["result"], {})


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


class WorkerCommitTest(unittest.TestCase):
    """S1 real scenario (Codex a02): the sandbox keeps .git read-only, so a worker commits through the server, only
    in its own node worktree and only the files it names."""

    def test_commit_in_own_worktree_only(self):
        with tempfile.TemporaryDirectory() as d:
            repo = Path(d) / "code"
            repo.mkdir()
            git = lambda *a: subprocess.run(["git", "-C", str(repo), "-c", "user.email=t@t", "-c", "user.name=t", *a],  # noqa: E731
                                             check=True, capture_output=True)
            git("init", "-q", "-b", "main")
            (repo / "a.txt").write_text("a")
            git("add", ".")
            git("commit", "-qm", "init")
            wt = Path(d) / "wt"
            git("worktree", "add", "-q", "-b", "node", str(wt))
            (wt / "zebra").mkdir()
            (wt / "zebra" / "m1.json").write_text("{}")

            class Fake:
                actor = "worker/h1"
                marker = {"phase": "confirmed"}

                def db(self):
                    class DB:
                        def find(self, table):
                            return [{"worktree_path": str(wt), "owner": "h1", "hypothesis_id": "H-0001"},
                                    {"worktree_path": str(Path(d) / "other"), "owner": "h2", "hypothesis_id": "H-0002"}]
                    return DB()
            env = {"GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@t", "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@t"}
            with patch.dict(os.environ, env):
                out = Runtime.commit(Fake(), {"paths": ["zebra/m1.json"], "message": "zebra config"})
                self.assertEqual(out["worktree"], str(wt.resolve()))
                for bad in (["../code/a.txt"], ["/etc/passwd"], [".git/config"]):
                    with self.subTest(bad=bad), self.assertRaisesRegex(ValueError, "not a file inside"):
                        Runtime.commit(Fake(), {"paths": bad, "message": "x"})
            log = subprocess.run(["git", "-C", str(wt), "log", "--oneline", "-1"], capture_output=True, text=True).stdout
            self.assertIn("zebra config", log)


class PromptContractTest(unittest.TestCase):
    def test_only_current_workflow_is_advertised(self):
        import codex_prompts
        conf = project_config.parse((ROOT / "schema/config.template.yaml").read_text())
        project = {"plan_instruction": {"path": "project/plan.v1.md"}, "root": "/r", "project_id": "P-x"}
        package = {"actor": "architect/root", "node": {"id": "P-x"}}
        plan = codex_prompts.planning(project, conf)
        worker = codex_prompts.worker(project, package, conf, "Build shared harness")
        self.assertIn("version 3", plan)
        self.assertIn("schema 23", plan)
        self.assertIn("停止与继续条件", plan)
        self.assertIn("gate --candidate", plan)
        self.assertIn("assign_architect", plan)
        self.assertIn("cache/discovery/proposals", plan)
        self.assertIn("architect/root", worker)
        self.assertIn("reserve_submission", worker)
        self.assertIn("import_run_result", worker)
        self.assertIn("不等待每次新的模型 code_review", worker)
        for text in (plan, worker, codex_hook.WORKFLOW):
            for removed in ("workflow.mode", "discovery.mode", "lens", "strict", "config.v1", "旧 verdict"):
                self.assertNotIn(removed, text)
        for role in ("explorer", "analyst"):
            advisor = codex_prompts.advisor(project, conf, role, "Read current evidence")
            self.assertIn(f"{role}/main", advisor)
            self.assertIn("不修改文件、数据库", advisor)
            self.assertIn("由 Leader 记录", advisor)
        with self.assertRaisesRegex(ValueError, "advisor role"):
            codex_prompts.advisor(project, conf, "rld", "Take over")


class RootCommitTest(unittest.TestCase):
    def test_architect_commits_only_the_confirmed_root_checkout(self):
        with tempfile.TemporaryDirectory() as temp:
            repo = Path(temp) / "root"
            repo.mkdir()
            git = lambda *args: subprocess.run(["git", "-C", str(repo), *args], check=True, capture_output=True)  # noqa: E731
            git("init", "-q", "-b", "main")
            (repo / "harness.py").write_text("print('initial')\n")
            git("add", ".")
            git("-c", "user.name=fixture", "-c", "user.email=test@example.invalid", "commit", "-qm", "init")
            (repo / "harness.py").write_text("print('updated')\n")

            class Fake:
                actor = "architect/root"
                marker = {"phase": "confirmed"}

                def db(self):
                    class DB:
                        def find(self, table):
                            if table == "project":
                                return [{"id": "P-test", "repo_path": str(repo), "architect_id": "root"}]
                            # A coincidentally matching worker id on another branch does not grant access.
                            return [{"hypothesis_id": "H-0001", "owner": "root", "worktree_path": str(Path(temp) / "other")}]
                    return DB()

            fake = Fake()
            with self.assertRaisesRegex(ValueError, "assigned project root"):
                Runtime.commit(fake, {"node_id": "H-0001", "paths": ["harness.py"], "message": "wrong node"})
            fake.marker = {"phase": "planning"}
            with self.assertRaisesRegex(ValueError, "confirmed"):
                Runtime.commit(fake, {"paths": ["harness.py"], "message": "premature"})
            fake.marker = {"phase": "confirmed"}
            result = Runtime.commit(fake, {"paths": ["harness.py"], "message": "maintain harness"})
            self.assertEqual(result["worktree"], str(repo))
            self.assertEqual(git("show", "HEAD:harness.py").stdout.decode(), "print('updated')\n")
            fake.actor = "architect/other"
            with self.assertRaisesRegex(ValueError, "assigned project root"):
                Runtime.commit(fake, {"paths": ["harness.py"], "message": "wrong assignee"})
