"""Tests for tools/build_site.py. Run: .venv/bin/python -m unittest discover -s tests"""

from __future__ import annotations

import contextlib
import io
import json
import re
import shutil
import subprocess
import sys
import tempfile
import unittest
from contextlib import ExitStack
from unittest.mock import patch
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "tools"))
from test_research_db import REPO, Fixture  # noqa: E402  (unittest discover puts tests/ on sys.path)

import build_site  # noqa: E402


def page_data(page: Path) -> dict:
    text = page.read_text(encoding="utf-8")
    raw = re.search(r'<script id="data" type="application/json">(.*?)</script>', text, re.S).group(1)
    return json.loads(raw)


class BuildSiteTest(Fixture):
    def setUp(self):
        super().setUp()
        self.page = self.root / "site" / "index.html"
        self.h = self.hypothesis()
        self.start(self.h)
        self.exp = self.method(self.h)

    def test_page_matches_snapshot(self):
        self.evaluate(self.exp)
        self.rld.decide(self.h, {"experiment_status": "beats_sota"}, "gate", based_on=[self.exp])
        data = build_site.build(self.db, self.page)
        self.assertIn(f'<meta name="data-version" content="{data["meta"]["data_version"]}">', self.page.read_text())
        embedded = page_data(self.page)
        node = next(n for n in embedded["nodes"] if n["id"] == self.h)
        self.assertEqual((node["exp_status"], node["latest"], node["go"]), ("beats_sota", self.exp, False))
        times = node["times"]
        self.assertTrue(all(times[k] for k in ("created_at", "started_at", "first_experiment_at", "first_result_at",
                                               "beats_sota_at")))
        self.assertIsNone(times["concluded_at"])  # still verifying
        sota_cmp = embedded["experiments"][self.exp]["comparisons"][0]
        self.assertEqual((sota_cmp["role"], sota_cmp["passes_gate"], sota_cmp["n_paired"]), ("sota", True, 3))
        # 3 SOTA seeds at 1 node x 1800 s plus 3 method seeds at 1 node x 600 s
        self.assertEqual(embedded["node_hours"], 2.0)
        self.assertEqual(embedded["screen_seeds"], 3)

    def test_root_architect_binding_is_separate_from_hypothesis_workers(self):
        self.rld.bind_architect_session("architect-session")
        self.rld.bind_worker_session(self.h, "hypothesis-session")
        full = build_site.build(self.db, self.page)
        for data in (full, build_site.summary(full, self.db), build_site.summary_or_empty(self.db)):
            architect = data["project"]["architect"]
            node = next(n for n in data["nodes"] if n["id"] == self.h)
            self.assertEqual((architect["id"], architect["agent_id"]), ("root", "architect-session"))
            self.assertEqual((node["worker"]["id"], node["worker"]["agent_id"]), ("w1", "hypothesis-session"))
            self.assertTrue(architect["session_at"])
            self.assertTrue(architect["resume"])
            self.assertNotIn("worker", data["project"])
            self.assertNotIn("project_worker", data)
            self.assertNotIn("verdict", node)
            self.assertNotIn("lineage_mode", node)
        for experiment in full["experiments"].values():
            self.assertNotIn("verdict", experiment)
            self.assertIn("outcome", experiment)

    def test_document_content_cannot_inject_script(self):
        evil = self.doc(self.rld, f"h/{self.h}/notes/evil.v1.md", "decision", about=(self.h,))
        path = self.root / "docs" / self.rld.get(evil)["path"]
        path.write_text("# 标题\n\n<script>alert(1)</script> </script><img src=x onerror=alert(2)>\n", encoding="utf-8")
        build_site.build(self.db, self.page)
        text = self.page.read_text(encoding="utf-8")
        self.assertNotIn("<script>alert", text)
        self.assertNotIn("<img src=x", text)
        self.assertEqual(text.count("</script>"), 2)  # only the data and code blocks close
        html_ = page_data(self.page)["docs"][evil]["html"]
        self.assertIn("&lt;script&gt;alert(1)&lt;/script&gt;", html_)

    def test_attention_items(self):
        self.finish_runs(self.worker, self.exp)
        one = self.method(self.h, n_seeds=1)
        self.evaluate(one, sota=(0.01, 0.0, 0.0))
        doc = self.rld.get(self.h)["doc_id"]
        (self.root / "docs" / self.rld.get(doc)["path"]).write_text("changed after it became current", encoding="utf-8")
        run = f"{self.exp}/s42"
        self.assertIsNone(self.rld.get(run).get("curve_path"))
        kinds = {(a["kind"], a["id"]) for a in build_site.build(self.db, self.page)["attention"]}
        self.assertIn(("needs_rld", self.h), kinds)
        self.assertIn(("doc_integrity", doc), kinds)
        self.assertIn(("curve_missing", run), kinds)

    def test_ui_messages_wait_for_an_rld_receipt(self):
        def line(**m) -> str:
            return json.dumps({"v": 1, "ts": "2026-10-04T00:00:00Z", "project": "P-test", **m}, ensure_ascii=False)
        logs = self.root / "messages"
        logs.mkdir(exist_ok=True)
        ui = dict(to="rld/main", **{"from": "ui/ui"})
        (logs / "ui--ui.jsonl").write_text("\n".join([
            line(id="ui--ui-0001", type="instruction", text="确认立项", need="none", **ui),
            line(id="ui--ui-0002", type="question", text="为什么？", need="answer", about=[self.h], **ui),
            line(id="ui--ui-0003", type="instruction", text="停止", need="ack", **ui)]) + "\n", encoding="utf-8")
        (logs / "rld--main.jsonl").write_text(line(id="rld--main-0001", type="reply", text="已停止", need="none", re="ui--ui-0003",
                                              to="ui/ui", **{"from": "rld/main"}) + "\n", encoding="utf-8")
        (logs / "window.jsonl").write_text(json.dumps({"id": "w-0001", "role": "user", "text": "x"}) + "\n")
        with (logs / "rld--main.jsonl").open("a", encoding="utf-8") as log:
            log.write('{"v": 1, "id": "rld--main-0002", "re": "ui--ui')  # a reply still being appended
        waiting = [a for a in build_site.build(self.db, self.page)["attention"] if a["kind"] == "awaiting_reply"]
        self.assertEqual([(a["id"], a["label"]) for a in waiting], [(self.h, "待RLD回执")])
        self.assertIn("ui--ui-0002", waiting[0]["text"])
        # the lightweight status the Claude mod's status line counts (待RLD回执 N) shows the same items
        light = [a for a in build_site.summary_or_empty(self.db)["attention"] if a["kind"] == "awaiting_reply"]
        self.assertEqual(light, waiting)

    def test_due_cleanup_and_the_ledger_show(self):
        self.evaluate(self.exp, sota=(0.01, 0.0, 0.0))
        due = [a for a in build_site.build(self.db, self.page)["attention"] if a["kind"] == "cleanup_due"]
        self.assertEqual([(a["id"], a["label"]) for a in due], [(None, "待清理"), (self.h, "待清理")])  # SOTA, node
        self.clean_all()
        data = build_site.build(self.db, self.page)
        self.assertFalse([a for a in data["attention"] if a["kind"] == "cleanup_due"])
        self.assertEqual(data["experiments"][self.exp]["cleaned"]["by"], "worker/w1")

    def test_check_reports_stale_page(self):
        cmd = [sys.executable, str(REPO / "tools" / "build_site.py"), "--db", str(self.db)]
        self.assertEqual(subprocess.run(cmd + ["--check"], capture_output=True).returncode, 1)  # no page yet
        self.assertEqual(subprocess.run(cmd, capture_output=True).returncode, 0)
        self.assertEqual(subprocess.run(cmd + ["--check"], capture_output=True).returncode, 0)
        self.hypothesis()
        out = subprocess.run(cmd + ["--check"], capture_output=True, text=True)
        self.assertEqual((out.returncode, json.loads(out.stdout)["stale"]), (1, True))
        subprocess.run(cmd, capture_output=True, check=True)
        self.assertTrue((self.root / "site" / "previous.html").is_file())

    @unittest.skipUnless(shutil.which("node"), "node is not installed")
    def test_page_script_is_valid_javascript(self):
        build_site.build(self.db, self.page)
        script = re.findall(r"<script>(.*?)</script>", self.page.read_text(encoding="utf-8"), re.S)[0]
        js = self.root / "page.js"
        js.write_text(script, encoding="utf-8")
        result = subprocess.run(["node", "--check", str(js)], capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)


class SummaryTest(Fixture):
    def test_summary_for_the_mod(self):
        h = self.hypothesis()
        self.start(h)
        exp = self.method(h)
        self.evaluate(exp)
        out = subprocess.run([sys.executable, str(REPO / "tools" / "build_site.py"), "--db", str(self.db), "--summary"],
                             capture_output=True, text=True, check=True)
        data = json.loads(out.stdout)
        node = data["nodes"][0]
        self.assertEqual((node["id"], node["outcome"], node["seeds"]), (h, "positive_signal", 3))
        self.assertAlmostEqual(node["vs_sota"], 0.3, places=9)
        self.assertEqual(data["counts"]["status"], {"verifying": 1})
        self.assertIn(str((self.root / "docs" / self.rld.get(node_doc := self.rld.get(h)["doc_id"])["path"]).resolve()),
                      data["guards"]["frozen_docs"], node_doc)
        self.assertEqual(data["guards"]["harness"], [str(Path(self.tmp.name) / "wt" / h / "harness")])
        self.assertTrue(any(a["kind"] == "conclusion_outdated" for a in data["attention"]))

    def test_summary_is_db_only_and_never_claims_unchecked_go(self):
        h, exp = self.candidate()
        with ExitStack() as stack:
            for name in ("collect", "load_curve", "render_markdown", "sha256_file", "review_attention"):
                stack.enter_context(patch.object(build_site, name, side_effect=AssertionError(f"expensive {name}")))
            for name in ("export_snapshot", "get_eligibility", "verify_document", "cleanup_due"):
                stack.enter_context(patch.object(build_site.ResearchDB, name, side_effect=AssertionError(name)))
            stack.enter_context(patch.object(Path, "read_text", side_effect=AssertionError("read presentation file")))
            stack.enter_context(patch.object(Path, "read_bytes", side_effect=AssertionError("read evidence file")))
            data = build_site.summary_or_empty(self.db)
        node = next(n for n in data["nodes"] if n["id"] == h)
        self.assertIsNone(data["counts"]["go"])
        self.assertIsNone(node["go"])
        self.assertEqual(node["outcome"], "positive_signal")
        self.assertEqual(node["evidence_state"], "not_checked")
        self.assertFalse(node["eligibility_checked"])
        self.assertFalse(data["meta"]["eligibility_checked"])
        self.assertEqual(data["meta"]["diagnostics"], "database_status_only")
        self.assertFalse((self.root / "site").exists())

    def test_summary_and_explicit_full_build_include_latest_committed_data(self):
        page = self.root / "site/index.html"
        build_site.build(self.db, page)
        old_version = build_site.page_version(page)
        h = self.hypothesis()
        self.start(h)
        exp = self.method(h)
        self.evaluate(exp)
        data = build_site.summary_or_empty(self.db)
        self.assertGreater(data["meta"]["data_version"], old_version)
        self.assertEqual(build_site.page_version(page), old_version)  # cheap status does not rebuild
        full = build_site.build(self.db, page)
        self.assertEqual(full["meta"]["data_version"], data["meta"]["data_version"])
        self.assertEqual(page_data(page)["meta"]["view"], "full")
        node = next(n for n in page_data(page)["nodes"] if n["id"] == h)
        self.assertEqual(node["latest"], exp)
        self.assertTrue(node["eligibility_checked"])
        self.assertEqual(node["intellectual_parent_id"], "P-test")
        self.assertEqual(node["code_parent_id"], "P-test")
        self.assertEqual(node["comparator_experiment_id"], self.sota)
        self.assertEqual(node["branch"]["base_commit"], self.harness)
        self.assertIn("思想来源", page.read_text())
        self.assertIn("代码起点", page.read_text())
        self.assertIn("比较参照", page.read_text())

    def test_intellectual_ancestry_code_source_and_comparator_are_separate(self):
        anchor = "底线问题: x；必须解决的瓶颈: x；非目标: x；约束: x；成功条件: x"
        goal = self.doc(self.rld, "project/fast-goal.v1.md", "goal", body="## 问题锚点\n" + anchor)
        instruction = self.doc(self.rld, "instructions/fast.v1.md", "user_instruction")
        self.rld.update_project(goal_doc_id=goal, user_instruction_doc_id=instruction)
        body = ("## 问题锚点\n" + anchor + "\n## 可证伪预测\n改善指标\n## 干预\n改变配置\n"
                '## 匹配对照\n相同种子基线\n## 资源上限\n{"nodes":1,"walltime_s":60,"n_seeds":1}\n'
                "## 停止与继续条件\n正向复制，负向暂停\n")
        idea_doc = self.doc(self.rld, "h/idea.v1.md", "hypothesis", body=body)
        idea = self.create_hypothesis("idea", "s", idea_doc, [])
        doc = self.doc(self.rld, "h/variant/hypothesis.v1.md", "hypothesis", body=body)
        variant = self.create_hypothesis("parallel variant", "test another implementation", doc, self.literature,
                        parent_id=idea, code_parent_id="P-test", comparator_experiment_id=self.sota)
        full = build_site.build(self.db, self.root / "site/index.html")
        compact = build_site.summary_or_empty(self.db)
        for data in (full, compact):
            node = next(n for n in data["nodes"] if n["id"] == variant)
            self.assertEqual(node["intellectual_parent_id"], idea)
            self.assertEqual(node["code_parent_id"], "P-test")
            self.assertEqual(node["comparator_experiment_id"], self.sota)
        self.assertEqual(self.rld.get(idea)["status"], "pending")

    def test_go_follows_eligibility_and_stale_evidence_shows(self):  # E01, K07-like display
        h, exp = self.candidate()
        page = self.root / "site" / "index.html"
        data = build_site.build(self.db, page)
        self.assertTrue(next(n for n in data["nodes"] if n["id"] == h)["go"])
        self.assertEqual(data["experiments"][exp]["evaluation"]["level"], "记录级重算")
        self.rld.update_project(harness_ref=self.commit({"harness/stats.py": "stats v2\n"}))
        data = build_site.build(self.db, page)
        self.assertFalse(next(n for n in data["nodes"] if n["id"] == h)["go"])
        stale = [a for a in data["attention"] if a["kind"] == "evidence_stale"]
        self.assertEqual([(a["id"], a["label"]) for a in stale], [(h, "证据已失效")])
        self.assertIn("HARNESS_CHANGED", stale[0]["text"])

    def test_outcome_disposition_and_ledger_show(self):
        h, exp = self.candidate()
        self.rld.add_obligation(h, "code_review:RV-0001", "dead_metric", "the metric function is never called",
                                "CRITICAL")
        page = self.root / "site" / "index.html"
        data = build_site.build(self.db, page)
        node = next(n for n in data["nodes"] if n["id"] == h)
        self.assertEqual((node["outcome"], node["disposition"], node["go"]), ("positive_signal", "active", False))
        self.assertIn(("obligation_open", h), {(a["kind"], a["id"]) for a in data["attention"]})


class CurrentProjectionTest(unittest.TestCase):
    def test_a_curve_not_aligned_with_its_step_series_is_reported_not_drawn(self):
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            files = {"scalar-step.json": {"step": 1000, "loss": [1.0, 0.5]},
                     "short-loss.json": {"step": [0, 10, 20], "loss": [1.0, 0.5]},
                     "aligned.json": {"step": [0, 10], "loss": [1.0, 0.5], "note": "not a series"}}
            for name, curve in files.items():
                (base / name).write_text(json.dumps(curve), encoding="utf-8")
            for name in ("scalar-step.json", "short-loss.json"):
                with self.subTest(name=name):
                    curve, problem = build_site.load_curve(name, base)
                    self.assertIsNone(curve)  # a valid run with a problem shows as curve_missing
                    self.assertIn(name, problem)
            self.assertEqual(build_site.load_curve("aligned.json", base), ({"step": [0, 10], "loss": [1.0, 0.5]}, None))

    def test_lineage_is_never_inferred_from_the_idea_parent(self):
        lineage = build_site._lineage({}, "H-0001")
        self.assertEqual(lineage, {"intellectual_parent_id": "H-0001", "code_parent_id": None,
                                   "comparator_experiment_id": None})

    def test_screening_waits_for_a_valid_matching_first_baseline_seed(self):
        project = {"sota_experiment_id": "E-0001", "seeds": [42, 43, 44], "gate_seeds": 3,
                   "screen_seeds": 3, "screen_budget_node_h": 10}
        def check(runs):
            return build_site._screen_seeds({"E-0001": {"runs": runs}}, project)
        self.assertIsNone(check([{"seed": 43, "valid": True, "node_h": 0.5}]))
        self.assertIsNone(check([{"seed": 42, "valid": False, "node_h": 0.5}]))
        self.assertIsNone(check([{"seed": 42, "valid": True, "node_h": None}]))
        self.assertEqual(check([{"seed": 42, "valid": True, "node_h": 0.5},
                                {"seed": 43, "valid": False, "node_h": 0.5}]), 1)
        self.assertEqual(check([{"seed": seed, "valid": True, "node_h": 0.5} for seed in [42, 43, 44]]), 3)


class DemoSmokeTest(unittest.TestCase):
    def test_fictional_demo_uses_only_current_workflow_and_preserves_confirmation_gate(self):
        import make_demo
        import project_config
        with tempfile.TemporaryDirectory() as directory:
            dest = Path(directory) / "demo"
            with contextlib.redirect_stdout(io.StringIO()):
                make_demo.Demo(dest).build()
            data = page_data(dest / "research" / make_demo.PROJECT_ID / "site/index.html")
            self.assertEqual(data["meta"]["schema_version"], 23)
            self.assertEqual(project_config.parse((dest / project_config.CONFIG_NAME).read_text())["version"], 3)
            self.assertEqual(project_config.parse((dest / "research" / make_demo.PROJECT_ID /
                "docs/project/config.v1.yaml").read_text())["version"], 3)
            self.assertEqual(data["project"]["architect"]["id"], "root")
            self.assertEqual(len(data["nodes"]), 4)
            self.assertEqual({n["outcome"] for n in data["nodes"]},
                             {"positive_signal", "negative_signal", "inconclusive", None})
            confirmed = [n for n in data["nodes"] if n["stage"] == "confirmed"]
            self.assertEqual(len(confirmed), 1)
            self.assertFalse(confirmed[0]["go"])  # final scientific reviews intentionally remain open
            self.assertTrue(confirmed[0]["eligibility"]["confirmation_evaluation_id"])
            for node in data["nodes"]:
                self.assertTrue(node["comparator_experiment_id"])
                self.assertTrue(node["code_parent_id"])
                self.assertNotIn("verdict", node)
            for experiment in data["experiments"].values():
                self.assertNotIn("verdict", experiment)
            logs = sorted(p.name for p in (dest / "research" / make_demo.PROJECT_ID / "messages").glob("*.jsonl"))
            self.assertEqual(logs, ["architect--root.jsonl", "rld--main.jsonl", "ui--ui.jsonl"])


class MarkdownTest(unittest.TestCase):
    def test_subset(self):
        out = build_site.render_markdown("---\nid: D-1\n---\n# 标题\n\n- 甲 **重点**\n- 乙\n\n| a | b |\n|---|---|\n| 1 | `x<y` |\n\n```\nraw <b>\n```\n")
        self.assertNotIn("id: D-1", out)
        self.assertIn("<h3>标题</h3>", out)
        self.assertIn("<ul><li>甲 <strong>重点</strong></li><li>乙</li></ul>", out)
        self.assertIn("<td><code>x&lt;y</code></td>", out)
        self.assertIn("<pre>raw &lt;b&gt;</pre>", out)


if __name__ == "__main__":
    unittest.main()
