"""plans/design 11 R01–R08, R14, R18–R22: the cross-model review wrapper with stand-in pi and claude binaries."""

from __future__ import annotations

import json
import os
import shutil
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

TOOLS = Path(__file__).resolve().parents[1] / "tools"
sys.path.insert(0, str(TOOLS))
sys.path.insert(0, str(TOOLS.parent / "schema"))

import research_tree  # noqa: E402
import review_call  # noqa: E402
from research_db import PermissionDenied, ResearchDB  # noqa: E402

ABLATION = {"ablations": [{"name": "Remove update", "what_it_tests": "Contribution of the changed update",
                          "expected_if_component_matters": "Matched effect disappears", "priority": 1,
                          "config_only": True}], "coverage_assessment": "Matched control covers the mechanism",
            "unnecessary_ablations": [], "suggested_order": ["Remove update"], "estimated_compute": "60 node-seconds"}

FAKE_PI = r'''
import json, os, sys
args = sys.argv[1:]
with open(os.environ["FAKE_LOG"], "a") as log:
    log.write(json.dumps(["pi", *args]) + "\n")
if args[:2] == ["auth", "check"]:
    print(json.dumps({"status": "ready" if os.environ.get("FAKE_PI_AUTH", "ok") == "ok" else "missing"}))
    sys.exit(0 if os.environ.get("FAKE_PI_AUTH", "ok") == "ok" else 1)
if args == ["--list-models"]:
    print("provider  model  context")
    print("openai    gpt-6-astra  272K")
    print("anthropic claude-sonnet-5-5  1M")
    sys.exit(0)
answers = json.loads(os.environ["FAKE_ANSWERS"])
state = os.environ["FAKE_LOG"] + ".n"
n = int(open(state).read()) if os.path.exists(state) else 0
open(state, "w").write(str(n + 1))
answer = answers[min(n, len(answers) - 1)]
message = {"role": "assistant", "content": [{"type": "text", "text": answer.get("text", "")}],
           "provider": answer.get("provider", "openai"), "model": answer.get("model", "gpt-6-astra"),
           "usage": {"cost": {"total": answer.get("cost", 0.01)}}, "stopReason": answer.get("stop", "stop"),
           "errorMessage": answer.get("error")}
print(json.dumps({"type": "session"}))
tool_messages = []
for cost in answer.get("tool_costs", []):
    tool_message = {**message, "content": [], "stopReason": "toolUse", "usage": {"cost": {"total": cost}}}
    tool_messages.append(tool_message)
    print(json.dumps({"type": "message_end", "message": tool_message}))
    print(json.dumps({"type": "turn_end", "message": tool_message, "toolResults": []}))
print(json.dumps({"type": "message_end", "message": message}))
print(json.dumps({"type": "turn_end", "message": message, "toolResults": []}))
print(json.dumps({"type": "agent_end", "messages": [*tool_messages, message], "willRetry": False}))
'''

FAKE_CLAUDE = r'''
import json, os, sys
args = sys.argv[1:]
with open(os.environ["FAKE_LOG"], "a") as log:
    log.write(json.dumps(["claude", *args]) + "\n")
if args[:2] == ["auth", "status"]:
    print(json.dumps({"loggedIn": os.environ.get("FAKE_CLAUDE_AUTH", "ok") == "ok"}))
    sys.exit(0)
if "FAKE_EXPECT_PROMPT" in os.environ:
    import argparse
    parser = argparse.ArgumentParser()
    for flag in ("-p", "--safe-mode", "--restricted", "--strict-mcp-config"):
        parser.add_argument(flag, action="store_true")
    for flag in ("--tools", "--add-dir"):
        parser.add_argument(flag, nargs="+")
    for flag in ("--output-format", "--model", "--effort", "--permission-mode", "--permission-prompts",
                 "--session-id", "--resume", "--append-system-prompt-file", "--json-schema", "--max-budget-usd"):
        parser.add_argument(flag)
    parser.add_argument("prompt", nargs="?")
    parsed = parser.parse_args(args)
    prompt = parsed.prompt or sys.stdin.read()
    if prompt != os.environ["FAKE_EXPECT_PROMPT"]:
        print("Error: missing or changed print-mode prompt", file=sys.stderr)
        sys.exit(1)
if "--json-schema" in args:
    schema = json.loads(args[args.index("--json-schema") + 1])
    def unsupported(value):
        if isinstance(value, dict):
            return value.get("$schema") == "https://json-schema.org/draft/2020-12/schema" or any(
                unsupported(item) for item in value.values())
        return isinstance(value, list) and any(unsupported(item) for item in value)
    if unsupported(schema):
        print('Error: --json-schema is not a valid JSON Schema: no schema with key or ref "https://json-schema.org/draft/2020-12/schema"', file=sys.stderr)
        sys.exit(1)
answers = json.loads(os.environ["FAKE_ANSWERS"])
state = os.environ["FAKE_LOG"] + ".n"
n = int(open(state).read()) if os.path.exists(state) else 0
open(state, "w").write(str(n + 1))
a = answers[min(n, len(answers) - 1)]
print(json.dumps({"type": "result", "subtype": "success", "is_error": a.get("is_error", False),
                  "terminal_reason": a.get("terminal_reason", "completed"), "api_error_status": a.get("status"),
                  "result": a.get("text", ""), "structured_output": a.get("structured"),
                  "total_cost_usd": a.get("cost", 0.02), "session_id": "s",
                  "modelUsage": {m: {"costUSD": 0.01} for m in a.get("models", ["claude-sonnet-5-5"])},
                  "permission_denials": a.get("denials", [])}))
'''


def block(data: dict, prose: str = "Reviewed the cited files.") -> str:
    return f"{prose}\n\n```json\n{json.dumps(data)}\n```\n"


class ReviewCallTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        base = Path(self.tmp.name)
        self.cwd = base / "project"
        self.cwd.mkdir()
        self.bin = base / "bin"
        self.bin.mkdir()
        self.log = base / "calls.jsonl"
        (self.cwd / "plan.md").write_text("# 计划\n", encoding="utf-8")
        shutil.copyfile(TOOLS.parent / "schema" / "config.template.yaml", self.cwd / "research-tree.yaml")
        self.env = {"PATH": f"{self.bin}{os.pathsep}/usr/bin:/bin", "FAKE_LOG": str(self.log), "FAKE_ANSWERS": "[]"}

    def project(self, reviewer: str = "openai/gpt-6-astra", leader: str | None = "claude-opus-5-5",
                alert: float | None = None) -> None:
        config = self.cwd / "research-tree.yaml"
        text = config.read_text(encoding="utf-8").replace("model: openai/gpt-6-astra", f"model: {reviewer}")
        if alert is not None:
            text = text.replace("review_usd_alert: null", f"review_usd_alert: {alert}")
        config.write_text(text, encoding="utf-8")
        marker = research_tree.init(self.cwd, self.cwd / "plan.md", "P-r")
        self.root = Path(marker["root"])
        self.rld = ResearchDB(Path(marker["db"]), "rld/main")
        (self.root / "docs/project/min-setup.v1.md").write_text("setup\n", encoding="utf-8")
        setup = self.rld.register_document("project/min-setup.v1.md", "min_setup", "setup")
        self.rld.set_document_current(setup)
        protocol = {"version": 1, "eval_type": "real_gt", "pair_fields": ["seed"], "profile": "stage1_confirmed",
                    "confirmation_seeds": [1042, 1043, 1044], "min_confirmation_pairs": 3,
                    "max_confirmation_candidates": 2, "require_artifact_import": True}
        (self.root / "docs/project/protocol.v1.json").write_text(json.dumps(protocol), encoding="utf-8")
        proto = self.rld.register_document("project/protocol.v1.json", "protocol", "protocol")
        self.rld.set_document_current(proto)
        fields = research_tree.show_config(self.cwd)["db_fields"]
        self.rld.create_project("P-r", "r", setup, "accuracy", "higher", ["train_time_s"], [42, 43, 44],
                                metric_spec_doc_id=marker["metric_spec"]["doc_id"], protocol_doc_id=proto,
                                **{k: v for k, v in fields.items() if k != "seeds"})
        # Minimal, deliberately synthetic subject for transport/receipt unit tests only. Scientific
        # admission and full mock flows are exercised by the database suites, not these fake model outputs.
        from latticedb import Database
        with Database(marker["db"]) as db, db.write() as tx:
            tx.create_node(labels=["Hypothesis"], properties={"id": "H-0001", "claim_revision": 1,
                           "claim_sha": "transport-fixture-claim", "project_id": "P-r"})
            tx.commit()
        if leader:
            research_tree.log_agent_model(self.root, {"agent": "main", "actor": "rld/main", "event": "observed",
                                                      "model": leader})
        brief = self.root / "docs/reviews/briefs/controls.v1.md"
        brief.parent.mkdir(parents=True)
        brief.write_text("# brief\nFiles: docs/project/min-setup.v1.md\n", encoding="utf-8")
        self.brief = "docs/reviews/briefs/controls.v1.md"

    def fake(self, name: str) -> None:
        path = self.bin / name
        path.write_text(f"#!{sys.executable}\n" + (FAKE_PI if name == "pi" else FAKE_CLAUDE))
        path.chmod(0o755)

    def call(self, answers: list[dict], kind: str = "ablation_plan", **kw) -> dict:
        self.env["FAKE_ANSWERS"] = json.dumps(answers)
        argv = ["--kind", kind, "--brief", kw.pop("brief", self.brief), "--about", kw.pop("about", "H-0001")]
        for k, v in kw.items():
            argv += [f"--{k.replace('_', '-')}", v]
        out = []
        with patch.dict(os.environ, self.env), patch("builtins.print", lambda s: out.append(json.loads(s))), \
                patch.object(Path, "cwd", lambda: self.cwd):
            review_call.main(argv)
        return out[-1]

    def calls(self) -> list[list[str]]:
        return [json.loads(line) for line in self.log.read_text().splitlines()] if self.log.exists() else []

    def test_init_checks_the_selected_backend_without_review_or_blocking_planning(self):
        cases = (("anthropic/claude-sonnet-5-5", "ok", True, "claude_code"),
                 ("anthropic/claude-sonnet-5-5", "missing", False, "claude_code"),
                 ("openai/gpt-6-astra", "ok", True, "pi"))
        self.fake("pi")
        self.fake("claude")
        for index, (model, auth, ready, backend) in enumerate(cases):
            with self.subTest(model=model, auth=auth):
                cwd = self.cwd / str(index)
                cwd.mkdir()
                (cwd / "plan.md").write_text("# Fresh planning input\n")
                text = (self.cwd / "research-tree.yaml").read_text().replace(
                    "model: openai/gpt-6-astra", f"model: {model}")
                (cwd / "research-tree.yaml").write_text(text)
                self.log.unlink(missing_ok=True)
                with patch.dict(os.environ, {**self.env, "FAKE_CLAUDE_AUTH": auth, "FAKE_PI_AUTH": auth}):
                    marker = research_tree.init(cwd, cwd / "plan.md", f"P-init-{index}")
                check = marker["reviewer_backend"]
                self.assertEqual((check["ok"], check["backend"], check["model"]), (ready, backend, model))
                self.assertEqual(research_tree.read_marker(cwd)["reviewer_backend"], check)
                self.assertEqual(marker["phase"], "planning")
                self.assertEqual(ResearchDB(Path(marker["db"]), "rld/main").reviews(), [])
                self.assertTrue(self.calls())
                self.assertTrue(all(c[0] == ("claude" if backend == "claude_code" else "pi") for c in self.calls()))
                self.assertFalse(any("-p" in c for c in self.calls()))
                if not ready:
                    self.assertIn("REVIEW_UNAVAILABLE", check["error"])

    def test_background_review_outlives_the_host_process_limit(self):
        """real-run-error #10/#12: a review longer than the host lets one tool process live runs as a detached job;
        the first call returns a ticket, the Leader collects the result with it, and nothing runs twice."""
        self.project()
        self.fake("pi")
        self.env["FAKE_ANSWERS"] = json.dumps([{"text": block(ABLATION)}])
        out = []
        with patch.dict(os.environ, self.env), patch("builtins.print", lambda s: out.append(json.loads(s))), \
                patch.object(Path, "cwd", lambda: self.cwd):
            review_call.main(["--kind", "ablation_plan", "--brief", self.brief, "--about", "H-0001", "--background",
                              "--wait-s", "0"])
            pending = out[-1]
            self.assertTrue(pending["pending"], pending)
            review_call.main(["--ticket", pending["ticket"], "--wait-s", "60"])
            done = out[-1]
            review_call.main(["--ticket", pending["ticket"], "--wait-s", "0"])  # collecting again repeats the answer
            again = out[-1]
            review_call.main(["--ticket", "RJ-nope", "--wait-s", "0"])
            bad = out[-1]
        self.assertTrue(done["ok"], done)
        self.assertEqual(done, again)
        self.assertEqual(done["result"]["result"], "planned")
        self.assertEqual(len(self.rld.reviews()), 1)
        self.assertEqual(len([c for c in self.calls() if c[1:2] not in (["auth"], ["--list-models"])]), 1)  # one model call
        self.assertFalse(bad["ok"])
        outcomes = [json.loads(line)["outcome"] for line in (self.root / "logs/review_calls.jsonl").read_text().splitlines()]
        self.assertEqual(outcomes, ["background_started", "started", "ok"])
        self.assertEqual([(j["ticket"], j["status"]) for j in review_call.list_jobs(self.root)],
                         [(pending["ticket"], "done")])

    def test_r01_r18_r19_backend_routing_without_fallback(self):
        self.project()
        out = self.call([{"text": block(ABLATION)}])  # R01: pi not on PATH
        self.assertFalse(out["ok"])
        self.assertIn("REVIEW_UNAVAILABLE: pi is not on PATH", out["error"])
        self.assertEqual(self.rld.reviews(), [])
        self.fake("pi")
        self.env["FAKE_PI_AUTH"] = "missing"
        self.assertIn("not ready", self.call([{"text": block(ABLATION)}])["error"])
        self.env["FAKE_PI_AUTH"] = "ok"
        out = self.call([{"text": block(ABLATION)}])
        self.assertTrue(out["ok"], out)
        self.assertEqual(out["result"]["backend"], "pi")  # R18: a non-anthropic reviewer only calls pi
        self.assertEqual({c[0] for c in self.calls()}, {"pi"})
        doc = self.rld.reviews()[0]
        self.assertEqual((doc["review_backend"], doc["reviewer_model"], doc["review_result"], doc["author_role"]),
                         ("pi", "openai/gpt-6-astra", "planned", "reviewer"))
        text = (self.root / "docs" / doc["path"]).read_text(encoding="utf-8")
        self.assertIn('backend: "pi"', text)
        self.assertTrue((self.root / "cache/reviews/RV-0001.v1.jsonl").is_file())

    def test_r19_anthropic_reviewer_never_falls_back_to_pi(self):
        self.project(reviewer="anthropic/claude-sonnet-5-5", leader="gpt-6-luna")
        self.fake("pi")  # pi's anthropic provider is ready, claude is missing
        out = self.call([{"text": block(ABLATION)}])
        self.assertIn("REVIEW_UNAVAILABLE: claude is not on PATH", out["error"])
        self.assertEqual(self.calls(), [])
        self.fake("claude")
        self.env["FAKE_CLAUDE_AUTH"] = "no"
        self.assertIn("not logged in", self.call([{"text": block(ABLATION)}])["error"])
        self.env["FAKE_CLAUDE_AUTH"] = "ok"
        out = self.call([{"structured": ABLATION, "text": json.dumps(ABLATION)}])
        self.assertTrue(out["ok"], out)
        self.assertEqual(out["result"]["backend"], "claude_code")  # R18
        self.assertNotIn("pi", {c[0] for c in self.calls()})
        command = [c for c in self.calls() if "-p" in c][0]
        # R22: isolated and read-only
        for flag in ("--safe-mode", "--restricted", "--strict-mcp-config"):
            self.assertIn(flag, command)
        self.assertEqual(command[command.index("--tools") + 1], "Read,Grep,Glob")
        self.assertEqual(command[command.index("--model") + 1], "claude-sonnet-5-5")

    def test_r02_r20_model_errors_are_unavailable(self):
        self.project()
        self.fake("pi")
        out = self.call([{"stop": "error", "error": "model gpt-6-astra not found"}])  # R02
        self.assertIn("REVIEW_UNAVAILABLE: pi: model gpt-6-astra not found", out["error"])
        self.assertEqual(self.rld.reviews(), [])
        attention = [a for a in review_call_attention(self.root, self.rld) if a["kind"] == "review_unavailable"]
        self.assertIn("not found", attention[0]["text"])

    def test_r20_claude_is_error_with_success_subtype(self):
        self.project(reviewer="anthropic/claude-sonnet-5-5", leader="gpt-6-luna")
        self.fake("claude")
        out = self.call([{"is_error": True, "terminal_reason": "api_error", "status": 404,
                          "text": "model not found", "structured": ABLATION}])
        self.assertIn("REVIEW_UNAVAILABLE: claude_code: is_error=True", out["error"])
        self.assertEqual(self.rld.reviews(), [])

    def test_claude_schema_dialect_is_compatible_without_changing_the_review_contract(self):
        from jsonschema import Draft7Validator
        self.project(reviewer="anthropic/claude-sonnet-5-5", leader="gpt-6-luna")
        self.fake("claude")
        out = self.call([{"structured": ABLATION, "text": json.dumps(ABLATION)}])
        self.assertTrue(out["ok"], out)
        backend = review_call.ClaudeBackend("anthropic/claude-sonnet-5-5", "medium", self.root, 900)
        for kind in review_call.REVIEW_KINDS:
            with self.subTest(kind=kind):
                source = json.loads((review_call.REVIEWS_DIR / f"{kind}.schema.json").read_text())
                before = json.loads(json.dumps(source))
                command = backend.command("Read brief", "session", Path("prompt.md"), True, [], source, None)
                cli_schema = json.loads(command[command.index("--json-schema") + 1])
                Draft7Validator.check_schema(cli_schema)
                self.assertNotIn("https://json-schema.org/draft/2020-12/schema", json.dumps(cli_schema))
                self.assertEqual(source, before)
                validator = Draft7Validator(cli_schema)
                self.assertFalse(validator.is_valid({}))
                if kind == "ablation_plan":
                    self.assertTrue(validator.is_valid(ABLATION))
                    self.assertFalse(validator.is_valid({**ABLATION, "ablations": [{**ABLATION["ablations"][0], "priority": 11}]}))
                    self.assertFalse(validator.is_valid({**ABLATION, "ablations": [{"name": "missing contract"}]}))

    def test_r03_one_follow_up_then_invalid(self):
        self.project()
        self.fake("pi")
        out = self.call([{"text": "no json here"}, {"text": block(ABLATION)}])
        self.assertTrue(out["ok"], out)  # the follow-up in the same session gave the JSON
        sessions = {c[c.index("--session-id") + 1] for c in self.calls() if "--session-id" in c}
        self.assertEqual(len(sessions), 1)
        self.log.unlink()
        Path(str(self.log) + ".n").unlink()
        out = self.call([{"text": "no json"}, {"text": block({"verdict": "MAYBE"})}])
        self.assertIn("REVIEW_INVALID", out["error"])
        self.assertEqual(len(self.rld.reviews()), 1)

    def test_r04_same_family_is_refused(self):
        self.project(leader="gpt-6-luna")  # the Leader is OpenAI, so is the reviewer
        self.fake("pi")
        out = self.call([{"text": block(ABLATION)}])
        self.assertIn("REVIEW_UNAVAILABLE: reviewer openai/gpt-6-astra is the Leader's family", out["error"])
        self.assertFalse([c for c in self.calls() if "-p" in c])  # the model was never called

    def test_reg_s4_04_family_through_channels(self):
        # the Leader reached through an aggregator is still OpenAI: refused before any model call
        self.project(leader="openrouter/openai/gpt-6-luna")
        self.fake("pi")
        out = self.call([{"text": block(ABLATION)}])
        self.assertIn("is the Leader's family", out["error"])
        self.assertFalse([c for c in self.calls() if "-p" in c])

    def test_reg_s4_04_observed_identity_decides(self):
        self.project()
        self.fake("pi")
        # the requested model answering through another channel is the same model
        out = self.call([{"text": block(ABLATION), "provider": "openrouter", "model": "openai/gpt-6-astra"}])
        self.assertTrue(out["ok"], out)
        self.assertEqual(self.rld.get(out["result"]["review_id"])["reviewer_family"], "openai")
        # another model answered (here the Leader's own family): kept and paid, never an independent review
        before = self.rld.get("P-r").get("review_cost_usd") or 0
        out = self.call([{"text": block(ABLATION), "provider": "anthropic", "model": "claude-opus-5-5", "cost": 0.03}])
        self.assertIn("REVIEW_INVALID: the review ran on anthropic/claude-opus-5-5", out["error"])
        self.assertAlmostEqual(self.rld.get("P-r")["review_cost_usd"] - before, 0.03)
        self.assertEqual(len(self.rld.reviews()), 1)

    def test_inapplicable_code_ref_is_rejected_before_backend_and_cost(self):
        self.project(reviewer="anthropic/claude-sonnet-5-5", leader="gpt-6-luna")
        self.fake("claude")
        cases = (("ablation_plan", ABLATION, {}),
                 ("candidate_recheck", {"dimension": "numbers", "result": "pass",
                                         "evidence_paths": ["docs/project/min-setup.v1.md"], "reason": "fixture"},
                  {"dimension": "numbers", "evaluation": "EV-0001"}))
        for kind, answer, params in cases:
            with self.subTest(kind=kind):
                self.log.unlink(missing_ok=True)
                Path(str(self.log) + ".n").unlink(missing_ok=True)
                before = self.rld.export_snapshot()
                out = self.call([{"structured": answer}], kind=kind, code_ref="a" * 40, **params)
                self.assertIn("REVIEW_INVALID", out["error"])
                self.assertEqual(self.calls(), [])
                self.assertEqual(review_call.spent(self.root), 0)
                self.assertEqual(self.rld.export_snapshot(), before)

    def test_unknown_leader_model_is_unavailable(self):
        self.project(leader=None)
        self.fake("pi")
        self.assertIn("cannot be placed in a model family", self.call([{"text": block(ABLATION)}])["error"])

    def test_removed_review_kinds_fail_before_backend_or_model_cost(self):
        self.project()
        self.fake("pi")
        before = self.rld.export_snapshot()
        for kind in ("triage", "novelty_precheck", "critical_review", "proposal_review"):
            with self.subTest(kind=kind), self.assertRaisesRegex(review_call.ReviewError, "REVIEW_INVALID"):
                review_call.review(self.cwd, kind, self.brief, "H-0001")
        self.assertFalse([c for c in self.calls() if "-p" in c])
        self.assertEqual(self.rld.export_snapshot(), before)
        self.assertEqual(self.rld.reviews(), [])

    def test_r07_repeat_is_a_new_document_and_session_continues(self):
        self.project()
        self.fake("pi")
        first = self.call([{"text": block(ABLATION)}])["result"]
        second = self.call([{"text": block(ABLATION)}])["result"]
        self.assertNotEqual(first["review_id"], second["review_id"])
        self.assertEqual([d["status"] for d in self.rld.reviews()], ["current", "current"])
        third = self.call([{"text": block(ABLATION)}], session=first["session"])["result"]
        self.assertEqual((third["session"], third["path"]), (first["session"], "reviews/RV-0001.v2.md"))
        self.assertEqual(self.rld.get(first["review_id"])["status"], "superseded")

    def test_r08_rld_cannot_author_a_review(self):
        self.project()
        (self.root / "docs/reviews").mkdir(exist_ok=True)
        (self.root / "docs/reviews/fake.v1.md").write_text("pass\n", encoding="utf-8")
        with self.assertRaises(PermissionDenied):
            self.rld.register_document("reviews/fake.v1.md", "review", "self review")
        with self.assertRaises(PermissionDenied):
            self.rld.register_review("reviews/fake.v1.md", "x", "ablation_plan", ["P-r"], "planned", "RV-9",
                                     "pi", "openai/gpt-6-astra", 0.0)

    def test_r14_review_budget(self):
        self.project(alert=0.015)
        self.fake("pi")
        self.assertTrue(self.call([{"text": block(ABLATION), "cost": 0.02}])["ok"])
        out = self.call([{"text": block(ABLATION)}])
        self.assertIn("REVIEW_BUDGET", out["error"])
        kinds = [a["kind"] for a in review_call_attention(self.root, self.rld)]
        self.assertIn("review_budget", kinds)
        self.assertEqual(self.rld.get("P-r")["review_cost_usd"], 0.02)

    def test_r21_other_or_several_observed_models_are_invalid(self):
        self.project(reviewer="anthropic/claude-sonnet-5-5", leader="gpt-6-luna")
        self.fake("claude")
        out = self.call([{"structured": ABLATION, "models": ["claude-sonnet-5-5", "claude-haiku-4-5"]}])
        self.assertIn("REVIEW_INVALID", out["error"])
        out = self.call([{"structured": ABLATION, "models": ["claude-opus-5-5"]}])
        self.assertIn("not the requested anthropic/claude-sonnet-5-5", out["error"])

    def test_r21_pi_answer_from_another_model_is_invalid(self):
        self.project()
        self.fake("pi")
        out = self.call([{"text": block(ABLATION), "model": "gpt-6-luna"}])
        self.assertIn("REVIEW_INVALID: the review ran on openai/gpt-6-luna", out["error"])
        self.assertEqual(self.rld.reviews(), [])

    def test_code_review_names_its_commit(self):
        self.project()
        self.fake("pi")
        out = self.call([{"text": block({"issues": [], "method_implemented": True})}], kind="code_review")
        self.assertIn("REVIEW_INVALID: a code_review names --code-ref", out["error"])

    def test_claude_prompt_survives_variadic_read_directories_on_start_and_resume(self):
        self.project(reviewer="anthropic/claude-sonnet-5-5", leader="gpt-6-luna")
        self.fake("claude")
        self.env["FAKE_EXPECT_PROMPT"] = review_call.PROMPT.format(brief=(self.root / self.brief).resolve())
        first = self.call([{"structured": ABLATION}], add_dir=str(self.cwd))
        self.assertTrue(first["ok"], first)
        resumed = self.call([{"structured": ABLATION}], add_dir=str(self.cwd), session=first["result"]["session"])
        self.assertTrue(resumed["ok"], resumed)
        self.assertEqual(resumed["result"]["session"], first["result"]["session"])
        self.assertEqual(self.rld.get(first["result"]["review_id"])["status"], "superseded")

    def test_r22_permission_denials_are_recorded(self):
        self.project(reviewer="anthropic/claude-sonnet-5-5", leader="gpt-6-luna")
        self.fake("claude")
        denial = {"tool_name": "Read", "tool_input": {"file_path": "/etc/hostname"}}
        out = self.call([{"structured": ABLATION, "denials": [denial]}], add_dir="/data/code")
        self.assertTrue(out["ok"], out)
        command = [c for c in self.calls() if "-p" in c][0]
        self.assertEqual(command[command.index("--add-dir") + 1], "/data/code")
        text = (self.root / "docs" / out["result"]["path"]).read_text(encoding="utf-8")
        self.assertIn("/etc/hostname", text.split("---")[1])


class RecheckCallTest(ReviewCallTest):  # The base tests run again here.
    """K06 and concurrency through review_call itself."""

    def test_k06_structure_is_corrected_a_verdict_is_not(self):
        """S4 §8.1: only a missing, repeated or foreign checklist item is sent back; a method_code pass that cites no
        code is structurally fine here and is made uncertain when registered (test_reviews_s4, REG-S4-03)."""
        schema = json.loads((TOOLS.parent / "schema/reviews/candidate_recheck.schema.json").read_text())
        recheck = {"dimension": "method_code", "result": "pass", "evidence_paths": ["docs/hypotheses/H-0001/result.v1.md"],
                   "reason": "the report says the method is implemented"}
        self.assertTrue(any("checklist" in f for f in review_call.problems("candidate_recheck", recheck, schema, "method_code")))
        items = [{"item": i, "result": "pass", "note": "seen"} for i in ("D", "G", "M")]
        self.assertEqual(review_call.problems("candidate_recheck", {**recheck, "checklist": items}, schema, "method_code"), [])
        self.assertTrue(any("missing" in f for f in review_call.problems(
            "candidate_recheck", {**recheck, "checklist": items[:2]}, schema, "method_code")))
        self.assertTrue(any("do not belong" in f for f in review_call.problems(
            "candidate_recheck", {**recheck, "checklist": items + [{"item": "H", "result": "pass", "note": "x"}]},
            schema, "method_code")))
        failed = {**recheck, "result": "fail", "checklist": [{**items[0], "result": "fail"}, *items[1:]]}
        self.assertEqual(review_call.problems("candidate_recheck", failed, schema, "method_code"), [])  # a legal fail

    def test_concurrent_reviews_get_their_own_numbers(self):
        import threading
        self.project()
        self.fake("pi")
        self.env["FAKE_ANSWERS"] = json.dumps([{"text": block(ABLATION)}])
        results = []
        with patch.dict(os.environ, self.env):
            def go():
                try:
                    results.append(review_call.review(self.cwd, "ablation_plan", self.brief, "H-0001"))
                except Exception as exc:  # noqa: BLE001
                    results.append(exc)
            threads = [threading.Thread(target=go) for _ in range(3)]
            for t in threads:
                t.start()
            for t in threads:
                t.join()
        self.assertTrue(all(isinstance(r, dict) for r in results), results)
        self.assertEqual(len({r["path"] for r in results}), 3)
        for d in self.rld.reviews():  # every registered file still matches its hash
            self.assertTrue(self.rld.verify_document(d["id"]))

    def test_failed_call_cost_reaches_the_project(self):
        self.project()
        self.fake("pi")
        out = self.call([{"text": "no json", "cost": 0.03}, {"text": "still none", "cost": 0.02}])
        self.assertIn("REVIEW_INVALID", out["error"])
        self.assertAlmostEqual(self.rld.get("P-r")["review_cost_usd"], 0.05)

    def test_pi_tool_reading_turns_reach_the_review_budget_once(self):
        self.project(alert=0.05)
        self.fake("pi")
        out = self.call([{"text": block(ABLATION), "cost": 0.01, "tool_costs": [0.02, 0.03]}])
        self.assertTrue(out["ok"], out)
        self.assertAlmostEqual(self.rld.get("P-r")["review_cost_usd"], 0.06)
        self.assertAlmostEqual(review_call.spent(self.root), 0.06)
        before = self.calls()
        out = self.call([{"text": block(ABLATION)}])
        self.assertIn("REVIEW_BUDGET", out["error"])
        self.assertEqual(self.calls(), before)

    def test_failed_pi_terminal_turn_preserves_tool_reading_charges(self):
        self.project()
        self.fake("pi")
        out = self.call([{"text": "", "stop": "error", "error": "provider failure",
                         "cost": 0.01, "tool_costs": [0.02, 0.03]}])
        self.assertIn("REVIEW_UNAVAILABLE", out["error"])
        self.assertEqual(self.rld.reviews(), [])
        self.assertAlmostEqual(self.rld.get("P-r")["review_cost_usd"], 0.06)
        self.assertAlmostEqual(review_call.spent(self.root), 0.06)


def review_call_attention(root: Path, rld: ResearchDB) -> list[dict]:
    import build_site
    return build_site.review_attention(root, rld.get("P-r"))


if __name__ == "__main__":
    unittest.main()
