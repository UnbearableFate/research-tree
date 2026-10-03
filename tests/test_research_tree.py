"""Tests for tools/research_tree.py. Run: .venv/bin/python -m unittest discover -s tests"""

from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
TOOL = REPO / "tools" / "research_tree.py"
sys.path.insert(0, str(REPO / "tools"))

from research_db import ResearchDB  # noqa: E402

PLAN = """# 低秩优化器研究计划

## 目标
在最小设定下找到优于SOTA的LoRA优化器。

## 初始假说
1. 子批次二阶矩预条件
```python
print("plan code block")
```
"""


class ResearchTreeTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.cwd = Path(self.tmp.name)
        self.plan = self.cwd / "plans" / "LoRA Opt plan.md"
        self.plan.parent.mkdir()
        self.plan.write_text(PLAN, encoding="utf-8")

    def tearDown(self):
        self.tmp.cleanup()

    def run_tool(self, *args: str) -> tuple[int, dict]:
        out = subprocess.run([sys.executable, str(TOOL), *args], cwd=self.cwd, capture_output=True, text=True)
        return out.returncode, json.loads(out.stdout)

    def test_init_lays_out_the_project(self):
        (self.cwd / "pyproject.toml").write_text('[project]\nname = "lora-study"\nversion = "0.1.0"\n', encoding="utf-8")
        code, out = self.run_tool("init", str(self.plan))
        self.assertEqual(code, 0, out)
        marker = out["result"]
        self.assertEqual((marker["project_id"], marker["phase"]), ("lora-study", "planning"))  # the uv project's name
        root = Path(marker["root"])
        self.assertEqual(root, self.cwd / "research" / "lora-study")
        for sub in ("docs/instructions", "docs/literature", "messages", "cache/literature", "site"):
            self.assertTrue((root / sub).is_dir(), sub)
        self.assertEqual(json.loads((self.cwd / ".research-tree.json").read_text())["db"], marker["db"])
        registry = json.loads((root / "agents.json").read_text())
        self.assertIn("ui/ui", registry)
        self.assertIn("worker/w1", registry)

        doc = ResearchDB(root / "research_tree.db", "rld/main").get(marker["plan_instruction"]["doc_id"])
        self.assertEqual((doc["doc_type"], doc["status"], doc["author_role"]), ("user_instruction", "current", "ui"))
        text = (root / "docs" / doc["path"]).read_text(encoding="utf-8")
        self.assertIn(PLAN.rstrip(), text)  # verbatim, code fence and all
        self.assertTrue(text.split("## 用户原话\n\n", 1)[1].startswith("~~~~"))

    def test_init_refuses_to_overwrite_and_checks_inputs(self):
        self.assertEqual(self.run_tool("init", str(self.plan))[0], 0)
        code, out = self.run_tool("init", str(self.plan), "--project-id", "P-other")
        self.assertEqual(code, 2)
        self.assertIn("already holds a research project", out["error"])
        other = Path(self.tmp.name) / "elsewhere"
        other.mkdir()
        for bad_id in ("bad id", "T-0001"):
            bad = subprocess.run([sys.executable, str(TOOL), "init", str(self.plan), "--project-id", bad_id],
                                 cwd=other, capture_output=True, text=True)
            self.assertIn("must not look like another record", json.loads(bad.stdout)["error"])
        missing = subprocess.run([sys.executable, str(TOOL), "init", "nope.md"], cwd=other, capture_output=True,
                                 text=True)
        self.assertIn("plan file not found", json.loads(missing.stdout)["error"])
        self.assertFalse((other / ".research-tree.json").exists())

    def test_project_id_defaults_to_the_directory_name(self):
        study = self.cwd / "my-study"
        study.mkdir()
        out = subprocess.run([sys.executable, str(TOOL), "init", str(self.plan)], cwd=study, capture_output=True,
                             text=True)
        marker = json.loads(out.stdout)["result"]
        self.assertEqual(marker["project_id"], "my-study")
        rld = ResearchDB(marker["db"], "rld/main")
        self.assertIsNone(rld.get("my-study"))  # an unprefixed project id is looked up as a project

    def test_instruction_and_phases(self):
        self.run_tool("init", str(self.plan), "--project-id", "P-demo")
        code, out = self.run_tool("instruction", "--text", "确认立项计划，开始实现根节点。", "--kind", "确认",
                                  "--understanding", "用户确认立项计划")
        self.assertEqual(code, 0, out)
        self.assertEqual(out["result"]["path"], "instructions/UI-0002.v1.md")

        self.assertEqual(self.run_tool("phase", "--set", "awaiting_confirmation")[1]["result"]["phase"],
                         "awaiting_confirmation")
        confirmed = self.run_tool("phase", "--set", "confirmed")[1]["result"]
        self.assertEqual(confirmed["phase"], "confirmed")
        self.assertIsNotNone(confirmed["confirmed_at"])
        code, out = self.run_tool("phase", "--set", "planning")
        self.assertEqual(code, 2)
        self.assertIn("does not go back", out["error"])

    def test_summary_right_after_init(self):
        _, out = self.run_tool("init", str(self.plan), "--project-id", "P-demo")
        summary = subprocess.run([sys.executable, str(REPO / "tools" / "build_site.py"), "--db", out["result"]["db"],
                                  "--summary"], cwd=self.cwd, capture_output=True, text=True, check=True)
        data = json.loads(summary.stdout)
        self.assertIsNone(data["project"])
        self.assertEqual(data["nodes"], [])
        plan_doc = Path(out["result"]["root"]).resolve() / "docs" / out["result"]["plan_instruction"]["path"]
        self.assertEqual(data["guards"]["frozen_docs"], [str(plan_doc)])

    def test_status_without_a_project(self):
        code, out = self.run_tool("status")
        self.assertEqual(code, 2)
        self.assertIn("/research-tree init", out["error"])


if __name__ == "__main__":
    unittest.main()
