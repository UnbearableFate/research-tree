"""Tests for tools/build_site.py. Run: .venv/bin/python -m unittest discover -s tests"""

from __future__ import annotations

import json
import re
import shutil
import subprocess
import sys
import unittest
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
        self.evaluate(self.exp, "beats_sota")
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
        self.evaluate(one, "close", sota=(0.01, 0.0, 0.0))
        doc = self.rld.get(self.h)["doc_id"]
        (self.root / "docs" / self.rld.get(doc)["path"]).write_text("changed after it became current", encoding="utf-8")
        run = f"{self.exp}/s42"
        self.assertIsNone(self.rld.get(run).get("curve_path"))
        kinds = {(a["kind"], a["id"]) for a in build_site.build(self.db, self.page)["attention"]}
        self.assertIn(("extend_seeds", self.h), kinds)
        self.assertIn(("doc_integrity", doc), kinds)
        self.assertIn(("curve_missing", run), kinds)

    def test_ui_messages_wait_for_an_rld_receipt(self):
        def line(**m) -> str:
            return json.dumps({"v": 1, "ts": "2026-10-04T00:00:00Z", "project": "P-test", **m}, ensure_ascii=False)
        logs = self.root / "messages"
        logs.mkdir(exist_ok=True)
        ui = dict(to="rld/main", **{"from": "ui/ui"})
        (logs / "ui.jsonl").write_text("\n".join([
            line(id="ui-0001", type="instruction", text="确认立项", need="none", **ui),
            line(id="ui-0002", type="question", text="为什么？", need="answer", about=[self.h], **ui),
            line(id="ui-0003", type="instruction", text="停止", need="ack", **ui)]) + "\n", encoding="utf-8")
        (logs / "main.jsonl").write_text(line(id="main-0001", type="reply", text="已停止", need="none", re="ui-0003",
                                              to="ui/ui", **{"from": "rld/main"}) + "\n", encoding="utf-8")
        (logs / "window.jsonl").write_text(json.dumps({"id": "w-0001", "role": "user", "text": "x"}) + "\n")
        waiting = [a for a in build_site.build(self.db, self.page)["attention"] if a["kind"] == "awaiting_reply"]
        self.assertEqual([(a["id"], a["label"]) for a in waiting], [(self.h, "待RLD回执")])
        self.assertIn("ui-0002", waiting[0]["text"])

    def test_due_cleanup_and_the_ledger_show(self):
        self.evaluate(self.exp, "beats_parent", sota=(0.01, 0.0, 0.0))
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
        self.evaluate(exp, "beats_sota")
        out = subprocess.run([sys.executable, str(REPO / "tools" / "build_site.py"), "--db", str(self.db), "--summary"],
                             capture_output=True, text=True, check=True)
        data = json.loads(out.stdout)
        node = data["nodes"][0]
        self.assertEqual((node["id"], node["verdict"], node["seeds"]), (h, "beats_sota", 3))
        self.assertAlmostEqual(node["vs_sota"], 0.3, places=9)
        self.assertEqual(data["counts"]["status"], {"verifying": 1})
        self.assertIn(str((self.root / "docs" / self.rld.get(node_doc := self.rld.get(h)["doc_id"])["path"]).resolve()),
                      data["guards"]["frozen_docs"], node_doc)
        self.assertEqual(data["guards"]["harness"], [str(Path(self.tmp.name) / "wt" / h / "harness")])
        self.assertTrue(any(a["kind"] == "conclusion_outdated" for a in data["attention"]))

    def test_go_follows_eligibility_and_stale_evidence_shows(self):  # E01, K07-like display
        h, exp = self.concluded("beats_sota")
        self.rld.decide(h, {"experiment_status": "beats_sota"}, "gate", based_on=[exp])
        self.recheck_pass(h, exp)
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
