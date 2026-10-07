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

NOVELTY = {"verdict": "PROCEED", "score": 7, "closest_prior_work": [
    {"title": "Prior A", "id": "arXiv:2401.00001", "overlap": "same family", "difference": "different schedule"}],
    "delta_sentence": "A schedule nobody has run at this scale.", "abandon_paper": None}

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
print(json.dumps({"type": "turn_end", "message": message, "toolResults": []}))
print(json.dumps({"type": "agent_end", "willRetry": False}))
'''

FAKE_CLAUDE = r'''
import json, os, sys
args = sys.argv[1:]
with open(os.environ["FAKE_LOG"], "a") as log:
    log.write(json.dumps(["claude", *args]) + "\n")
if args[:2] == ["auth", "status"]:
    print(json.dumps({"loggedIn": os.environ.get("FAKE_CLAUDE_AUTH", "ok") == "ok"}))
    sys.exit(0)
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
        self.rld.create_project("P-r", "r", setup, "accuracy", "higher", True, ["train_time_s"], [42, 43, 44],
                                metric_spec_doc_id=marker["metric_spec"]["doc_id"], protocol_doc_id=proto,
                                **{k: v for k, v in fields.items() if k != "seeds"})
        if leader:
            research_tree.log_agent_model(self.root, {"agent": "main", "actor": "rld/main", "event": "observed",
                                                      "model": leader})
        brief = self.root / "docs/reviews/briefs/novelty.v1.md"
        brief.parent.mkdir(parents=True)
        brief.write_text("# brief\nFiles: docs/project/min-setup.v1.md\n", encoding="utf-8")
        self.brief = "docs/reviews/briefs/novelty.v1.md"

    def fake(self, name: str) -> None:
        path = self.bin / name
        path.write_text(f"#!{sys.executable}\n" + (FAKE_PI if name == "pi" else FAKE_CLAUDE))
        path.chmod(0o755)

    def call(self, answers: list[dict], kind: str = "novelty_precheck", **kw) -> dict:
        self.env["FAKE_ANSWERS"] = json.dumps(answers)
        argv = ["--kind", kind, "--brief", kw.pop("brief", self.brief), "--about", kw.pop("about", "P-r")]
        for k, v in kw.items():
            argv += [f"--{k.replace('_', '-')}", v]
        out = []
        with patch.dict(os.environ, self.env), patch("builtins.print", lambda s: out.append(json.loads(s))), \
                patch.object(Path, "cwd", lambda: self.cwd):
            review_call.main(argv)
        return out[-1]

    def calls(self) -> list[list[str]]:
        return [json.loads(line) for line in self.log.read_text().splitlines()] if self.log.exists() else []

    def test_r01_r18_r19_backend_routing_without_fallback(self):
        self.project()
        out = self.call([{"text": block(NOVELTY)}])  # R01: pi not on PATH
        self.assertFalse(out["ok"])
        self.assertIn("REVIEW_UNAVAILABLE: pi is not on PATH", out["error"])
        self.assertEqual(self.rld.reviews(), [])
        self.fake("pi")
        self.env["FAKE_PI_AUTH"] = "missing"
        self.assertIn("not ready", self.call([{"text": block(NOVELTY)}])["error"])
        self.env["FAKE_PI_AUTH"] = "ok"
        out = self.call([{"text": block(NOVELTY)}])
        self.assertTrue(out["ok"], out)
        self.assertEqual(out["result"]["backend"], "pi")  # R18: a non-anthropic reviewer only calls pi
        self.assertEqual({c[0] for c in self.calls()}, {"pi"})
        doc = self.rld.reviews()[0]
        self.assertEqual((doc["review_backend"], doc["reviewer_model"], doc["review_result"], doc["author_role"]),
                         ("pi", "openai/gpt-6-astra", "PROCEED", "reviewer"))
        text = (self.root / "docs" / doc["path"]).read_text(encoding="utf-8")
        self.assertIn('backend: "pi"', text)
        self.assertTrue((self.root / "cache/reviews/RV-0001.v1.jsonl").is_file())

    def test_r19_anthropic_reviewer_never_falls_back_to_pi(self):
        self.project(reviewer="anthropic/claude-sonnet-5-5", leader="gpt-6-luna")
        self.fake("pi")  # pi's anthropic provider is ready, claude is missing
        out = self.call([{"text": block(NOVELTY)}])
        self.assertIn("REVIEW_UNAVAILABLE: claude is not on PATH", out["error"])
        self.assertEqual(self.calls(), [])
        self.fake("claude")
        self.env["FAKE_CLAUDE_AUTH"] = "no"
        self.assertIn("not logged in", self.call([{"text": block(NOVELTY)}])["error"])
        self.env["FAKE_CLAUDE_AUTH"] = "ok"
        out = self.call([{"structured": NOVELTY, "text": json.dumps(NOVELTY)}])
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
                          "text": "model not found", "structured": NOVELTY}])
        self.assertIn("REVIEW_UNAVAILABLE: claude_code: is_error=True", out["error"])
        self.assertEqual(self.rld.reviews(), [])

    def test_r03_one_follow_up_then_invalid(self):
        self.project()
        self.fake("pi")
        out = self.call([{"text": "no json here"}, {"text": block(NOVELTY)}])
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
        out = self.call([{"text": block(NOVELTY)}])
        self.assertIn("REVIEW_UNAVAILABLE: reviewer openai/gpt-6-astra is the Leader's family", out["error"])
        self.assertFalse([c for c in self.calls() if "-p" in c])  # the model was never called

    def test_unknown_leader_model_is_unavailable(self):
        self.project(leader=None)
        self.fake("pi")
        self.assertIn("cannot be placed in a model family", self.call([{"text": block(NOVELTY)}])["error"])

    def test_r05_r06_novelty_verdict_limits(self):
        self.project()
        self.fake("pi")
        unnamed = {**NOVELTY, "verdict": "ABANDON", "abandon_paper": None}
        out = self.call([{"text": block(unnamed)}, {"text": block(unnamed)}])  # R05: invalid, not negative
        self.assertIn("REVIEW_INVALID: ABANDON names the paper", out["error"])
        self.assertEqual(self.rld.reviews(), [])
        caution = {**NOVELTY, "verdict": "PROCEED_WITH_CAUTION"}
        out = self.call([{"text": block(caution)}])  # R06: counted as positive
        self.assertEqual(out["result"]["result"], "PROCEED_WITH_CAUTION")

    def test_r07_repeat_is_a_new_document_and_session_continues(self):
        self.project()
        self.fake("pi")
        first = self.call([{"text": block(NOVELTY)}])["result"]
        second = self.call([{"text": block(NOVELTY)}])["result"]
        self.assertNotEqual(first["review_id"], second["review_id"])
        self.assertEqual([d["status"] for d in self.rld.reviews()], ["current", "current"])
        third = self.call([{"text": block(NOVELTY)}], session=first["session"])["result"]
        self.assertEqual((third["session"], third["path"]), (first["session"], "reviews/RV-0001.v2.md"))
        self.assertEqual(self.rld.get(first["review_id"])["status"], "superseded")

    def test_r08_rld_cannot_author_a_review(self):
        self.project()
        (self.root / "docs/reviews").mkdir(exist_ok=True)
        (self.root / "docs/reviews/fake.v1.md").write_text("pass\n", encoding="utf-8")
        with self.assertRaises(PermissionDenied):
            self.rld.register_document("reviews/fake.v1.md", "review", "self review")
        with self.assertRaises(PermissionDenied):
            self.rld.register_review("reviews/fake.v1.md", "x", "novelty_precheck", ["P-r"], "PROCEED", "RV-9",
                                     "pi", "openai/gpt-6-astra", 0.0)

    def test_r14_review_budget(self):
        self.project(alert=0.015)
        self.fake("pi")
        self.assertTrue(self.call([{"text": block(NOVELTY), "cost": 0.02}])["ok"])
        out = self.call([{"text": block(NOVELTY)}])
        self.assertIn("REVIEW_BUDGET", out["error"])
        kinds = [a["kind"] for a in review_call_attention(self.root, self.rld)]
        self.assertIn("review_budget", kinds)
        self.assertEqual(self.rld.get("P-r")["review_cost_usd"], 0.02)

    def test_r21_other_or_several_observed_models_are_invalid(self):
        self.project(reviewer="anthropic/claude-sonnet-5-5", leader="gpt-6-luna")
        self.fake("claude")
        out = self.call([{"structured": NOVELTY, "models": ["claude-sonnet-5-5", "claude-haiku-4-5"]}])
        self.assertIn("REVIEW_INVALID", out["error"])
        out = self.call([{"structured": NOVELTY, "models": ["claude-opus-5-5"]}])
        self.assertIn("not the requested anthropic/claude-sonnet-5-5", out["error"])

    def test_r21_pi_answer_from_another_model_is_invalid(self):
        self.project()
        self.fake("pi")
        out = self.call([{"text": block(NOVELTY), "model": "gpt-6-luna"}])
        self.assertIn("REVIEW_INVALID: the review ran on openai/gpt-6-luna", out["error"])
        self.assertEqual(self.rld.reviews(), [])

    def test_r22_permission_denials_are_recorded(self):
        self.project(reviewer="anthropic/claude-sonnet-5-5", leader="gpt-6-luna")
        self.fake("claude")
        denial = {"tool_name": "Read", "tool_input": {"file_path": "/etc/hostname"}}
        out = self.call([{"structured": NOVELTY, "denials": [denial]}], add_dir="/data/code")
        self.assertTrue(out["ok"], out)
        command = [c for c in self.calls() if "-p" in c][0]
        self.assertEqual(command[command.index("--add-dir") + 1], "/data/code")
        text = (self.root / "docs" / out["result"]["path"]).read_text(encoding="utf-8")
        self.assertIn("/etc/hostname", text.split("---")[1])


class RecheckCallTest(ReviewCallTest):  # noqa: the base tests run again here
    """K06 and concurrency through review_call itself."""

    def test_k06_method_code_pass_must_cite_code(self):
        self.project()
        self.fake("pi")
        recheck = {"dimension": "method_code", "result": "pass", "evidence_paths": ["docs/hypotheses/H-0001/result.v1.md"],
                   "reason": "the report says the method is implemented"}
        found = review_call.problems("candidate_recheck", recheck, json.loads(
            (TOOLS.parent / "schema/reviews/candidate_recheck.schema.json").read_text()), "method_code")
        self.assertTrue(any("K06" in f for f in found), found)
        ok = {**recheck, "evidence_paths": ["code/toytrain/methods.py"]}
        self.assertEqual(review_call.problems("candidate_recheck", ok, json.loads(
            (TOOLS.parent / "schema/reviews/candidate_recheck.schema.json").read_text()), "method_code"), [])
        empty = {**recheck, "dimension": "numbers", "evidence_paths": []}
        self.assertIn("evidence_paths", "; ".join(review_call.problems("candidate_recheck", empty, json.loads(
            (TOOLS.parent / "schema/reviews/candidate_recheck.schema.json").read_text()), "numbers")))

    def test_concurrent_reviews_get_their_own_numbers(self):
        import threading
        self.project()
        self.fake("pi")
        self.env["FAKE_ANSWERS"] = json.dumps([{"text": block(NOVELTY)}])
        results = []
        with patch.dict(os.environ, self.env):
            def go():
                try:
                    results.append(review_call.review(self.cwd, "novelty_precheck", self.brief, "P-r"))
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


def review_call_attention(root: Path, rld: ResearchDB) -> list[dict]:
    import build_site
    return build_site.review_attention(root, rld.get("P-r"))


if __name__ == "__main__":
    unittest.main()
