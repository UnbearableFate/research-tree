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

    def test_confirm_request_waits_for_the_discovery_gate(self):
        with patch.object(research_tree, "discovery_blocks_confirmation", return_value="discovery 门尚未通过：x"):
            with self.assertRaisesRegex(ValueError, "discovery 门尚未通过"):
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

    def test_research_review_handler(self):
        args = {"kind": "novelty_precheck", "brief": "docs/project/min-setup.v1.md", "about": "P-test"}
        worker = Runtime(self.cwd, "worker/root")
        with self.assertRaisesRegex(ValueError, "only the Leader"):
            worker.dispatch("research_review", args)
        # this fixture's configuration is version 1: no models.reviewer, so the call is unavailable and logged
        with self.assertRaisesRegex(ValueError, "REVIEW_UNAVAILABLE: research-tree.yaml has no models.reviewer"):
            self.runtime.dispatch("research_review", args)
        log = [json.loads(x) for x in (self.runtime.root / "logs/review_calls.jsonl").read_text().splitlines()]
        self.assertEqual((log[-1]["kind"], log[-1]["about"], log[-1]["outcome"]),
                         ("novelty_precheck", "P-test", "REVIEW_UNAVAILABLE"))

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

    def test_config_apply_passes_the_users_metric_spec_replacement(self):
        with patch("research_tree.apply_config", return_value={"new_version": False, "updated_fields": {}}) as apply:
            self.runtime.control("config", {"apply": True, "words": "/config apply --replace-metric-spec",
                                            "replace_metric_spec": True})
        self.assertTrue(apply.call_args.kwargs["replace_metric_spec"])

    def test_review_deadlines_leave_time_to_return_the_runtime_failure(self):
        from review_call import MAX_CALL_S
        client_timeout = json.loads((ROOT / ".mcp.json").read_text())["mcpServers"]["research_tree"]["tool_timeout_sec"]
        spec = {"project": str(self.cwd), "actor": "worker/root", "model": {"model": "fixture-model"}}
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
        self.assertLess(MAX_CALL_S, run.call_args.kwargs["timeout"])
        self.assertLess(run.call_args.kwargs["timeout"], client_timeout)

    def test_worker_honors_native_full_access_and_ui_remains_read_only(self):
        config_dir = self.cwd / "isolated-codex"
        config_dir.mkdir()
        config = config_dir / "config.toml"
        spec = {"project": str(self.cwd), "actor": "worker/root", "model": {"model": "fixture-model"}}
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
            spec["actor"] = "assistant/lens_test"
            self.assertIn('sandbox_mode="read-only"', codex_agent.command(spec, self.cwd))
            config.write_text('sandbox_mode = "workspace-write"\n')
            spec["actor"] = "worker/root"
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
            codex_mcp.run_request(self.cwd, "worker/root", "research_db", {"actor": "rld/main", "method": "help"})
        self.confirm()
        self.assign()
        worker = Runtime(self.cwd, "worker/root")
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
        self.assertEqual(alert["message"]["from"], "worker/root")

    def test_lens_has_a_fixed_read_only_identity_and_cannot_be_duplicated(self):
        (self.cwd / "research-tree.yaml").write_text(json.dumps({"version": 2,
            "discovery": {"mode": "full", "lenses": ["contradiction"]},
            "models": {"lens_assistant": {"model": "fixture-model", "effort": "medium"}}}))
        hold = Path(self.temp.name) / "hold"
        hold.touch()
        task = {"lens": "contradiction", "task": "Read the plan and propose candidates only."}
        started = self.runtime.control("lens", task)
        self.assertTrue(started["actor"].startswith("assistant/lens_"))
        with self.assertRaisesRegex(ValueError, "live"):
            self.runtime.control("lens", task)
        helper = Runtime(self.cwd, started["actor"])
        self.assertEqual(helper.dispatch("research_db", {"method": "get", "kwargs": {"entity_id": "P-test"}})["id"], "P-test")
        for method in ("create_experiment", "register_document", "update_project"):
            with self.assertRaisesRegex(ValueError, "only read"):
                helper.dispatch("research_db", {"method": method, "kwargs": {}})
        for action in ("worker", "lens", "confirm", "instruction", "attach"):
            with self.assertRaisesRegex(ValueError, "only RLD"):
                helper.control(action, {})
        with self.assertRaisesRegex(ValueError, "only the Leader"):
            helper.dispatch("research_review", {})
        with self.assertRaisesRegex(ValueError, "do not send"):
            helper.dispatch("research_message", {"type": "alert", "text": "x"})
        hold.unlink()
        state = self.wait_run(started)
        self.assertEqual(state["status"], "completed", state)
        self.assertEqual(self.runtime.marker["phase"], "planning")
        self.assertFalse(self.db.get("P-test").get("worker_agent_id"))
        self.assertEqual(self.db.find("experiment"), [])

    def test_lens_requires_full_discovery_planning_and_a_configured_lens(self):
        with self.assertRaisesRegex(ValueError, "mode full"):
            self.runtime.control("lens", {"lens": "contradiction", "task": "generate"})
        (self.cwd / "research-tree.yaml").write_text(json.dumps({"version": 2,
            "discovery": {"mode": "full", "lenses": ["contradiction"]}}))
        with self.assertRaisesRegex(ValueError, "configured"):
            self.runtime.control("lens", {"lens": "unknown", "task": "generate"})
        with self.assertRaisesRegex(ValueError, "concrete"):
            self.runtime.control("lens", {"lens": "contradiction", "task": ""})
        shutil.copyfile(ROOT / "schema/config.v1.template.yaml", self.cwd / "research-tree.yaml")
        self.confirm()
        with self.assertRaisesRegex(ValueError, "during planning"):
            self.runtime.control("lens", {"lens": "contradiction", "task": "generate"})

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
            ("lens_assistant", "GPT 6.1 Sol", "gpt-6.1-sol"),
            ("worker", "GPT-6 Sol", "gpt-6-sol"),
        ):
            with self.subTest(role=role):
                config = {"version": 2 if role == "lens_assistant" else 1,
                          "models": {role: {"model": display, "effort": "high"}}}
                if role == "lens_assistant":
                    config["discovery"] = {"mode": "full", "lenses": ["contradiction"]}
                original = json.dumps(config)
                (self.cwd / "research-tree.yaml").write_text(original)
                with patch.dict(os.environ, {"FAKE_CODEX_REPLY": json.dumps({"reply": "收到", "actions": []})}):
                    if role == "ui":
                        run = self.runtime.start_ui("查看计划")
                    elif role == "lens_assistant":
                        run = self.runtime.control("lens", {"lens": "contradiction", "task": "Generate candidates."})
                    else:
                        self.confirm()
                        self.assign()
                        run = self.runtime.start_worker("P-test", "实现根节点")
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
                 ("ui/ui", f"{db_call} --actor rld/main get '{{}}'", True),
                 ("ui/ui", f"{db_call} --actor worker/root get '{{}}'", True),
                 ("assistant/lens_test", f"{db_call} --actor rld/main get '{{}}'", True),
                 ("assistant/lens_test", f"{db_call} --actor assistant/lens_test get '{{}}'", False),
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
            worker_context = codex_hook.handle({"hook_event_name": "SessionStart", "cwd": str(self.cwd), "session_id": "worker-thread", "model": "child"})["hookSpecificOutput"]["additionalContext"]
        self.assertIn("worker/root", worker_context)
        self.assertNotIn("用research_control inbox", worker_context)
        self.assertNotIn("需要用户决定时post_to_ui", worker_context)
        self.assertEqual(prior, read_json(self.runtime.cache / "leader.json"))
        observed = json.loads((self.runtime.root / "logs/agent_models.jsonl").read_text().splitlines()[-1])
        self.assertEqual((observed["actor"], observed["event"], observed["model"]), ("worker/root", "observed", "child"))
        for actor in ("ui/ui", "assistant/lens_123456789abc"):
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
        for command, expected in [(c, False) for c in allowed] + [(c, True) for c in denied]:
            with self.subTest(command=command):
                event["tool_input"] = {"cmd": command}
                self.assertEqual(bool(codex_hook.handle(event)), expected)

    def test_init_in_live_session_observes_the_model_on_the_first_tool_event(self):
        fresh = self.cwd / "fresh"
        fresh.mkdir()
        (fresh / "plan.md").write_text("# A project initialized in an existing Codex session\n")
        shutil.copyfile(ROOT / "schema/config.v1.template.yaml", fresh / "research-tree.yaml")
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
