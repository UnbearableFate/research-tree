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

from latticedb import Database  # noqa: E402
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
        self.assertIn("worker/root", registry)

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

    def test_init_starts_from_the_default_config_or_a_named_one(self):
        self.run_tool("init", str(self.plan), "--project-id", "P-demo")
        template = (REPO / "schema" / "config.template.yaml").read_text(encoding="utf-8")
        self.assertEqual((self.cwd / "research-tree.yaml").read_text(encoding="utf-8"), template)

        other = self.cwd / "other"
        other.mkdir()
        init = lambda *args: json.loads(subprocess.run([sys.executable, str(TOOL), "init", str(self.plan), *args],
                                                       cwd=other, capture_output=True, text=True).stdout)
        # A file already in the directory is used only when named.
        (other / "research-tree.yaml").write_text("budget:\n  screen_node_h: 4\n", encoding="utf-8")
        self.assertIn("--config research-tree.yaml", init()["error"])
        bad = self.cwd / "bad.yaml"
        bad.write_text("budget:\n  per_run:\n    nodes: 0\n  typo: 1\n", encoding="utf-8")
        self.assertIn("already exists", init("--config", str(bad))["error"])
        (other / "research-tree.yaml").unlink()
        error = init("--config", str(bad))["error"]
        self.assertIn("budget.per_run.nodes", error)
        self.assertIn("'typo' was unexpected", error)
        self.assertFalse((other / "research").exists())
        self.assertFalse((other / "research-tree.yaml").exists())

        good = self.cwd / "cluster.yaml"
        good.write_text("budget:\n  screen_node_h: 4\n", encoding="utf-8")
        self.assertTrue(init("--config", str(good))["ok"])
        self.assertEqual((other / "research-tree.yaml").read_text(encoding="utf-8"), good.read_text(encoding="utf-8"))

    def test_ui_outbox(self):
        _, out = self.run_tool("init", str(self.plan), "--project-id", "P-demo")
        self.assertEqual(self.run_tool("ui", "reply", "--run", "r1", "--text", "进度如下")[0], 0)
        self.assertEqual(self.run_tool("ui", "instruction", "--run", "r1", "--understanding", "停止H-0002",
                                       "--about", "P-demo")[0], 0)
        code, err = self.run_tool("ui", "question", "--run", "r1")
        self.assertIn("needs --text", err["error"])
        code, err = self.run_tool("ui", "confirm", "--run", "../x")
        self.assertIn("not a UI run id", err["error"])
        lines = (Path(out["result"]["root"]) / "cache" / "ui" / "r1.jsonl").read_text(encoding="utf-8").splitlines()
        self.assertEqual([json.loads(line) for line in lines], [
            {"type": "reply", "text": "进度如下"},
            {"type": "instruction", "understanding": "停止H-0002", "kind": "指令", "about": ["P-demo"]},
        ])

    def test_the_ui_queries_read_only(self):
        _, out = self.run_tool("init", str(self.plan), "--project-id", "P-demo")
        code, read = self.run_tool("query", "find", '{"table": "document"}')
        self.assertEqual((code, read["result"][0]["doc_type"]), (0, "user_instruction"))
        self.assertIn("parameters", self.run_tool("query", "help", '{"method": "get"}')[1]["result"])
        code, err = self.run_tool("query", "create_task", '{"kind": "other", "assignee_role": "worker", "request_doc_id": "D-0001"}')
        self.assertEqual(code, 2)
        self.assertIn("query reads only", err["error"])

    def test_agent_models_are_logged(self):
        _, out = self.run_tool("init", str(self.plan), "--project-id", "P-demo")
        self.run_tool("agent-log", "--agent", "a1", "--actor", "worker/h0001", "--event", "requested", "--model", "inherit")
        self.run_tool("agent-log", "--agent", "a1", "--actor", "worker/h0001", "--event", "observed", "--model", "m-1")
        log = Path(out["result"]["root"]) / "logs" / "agent_models.jsonl"
        records = [json.loads(line) for line in log.read_text(encoding="utf-8").splitlines()]
        self.assertEqual([(r["agent"], r["event"], r["model"]) for r in records],
                         [("a1", "requested", "inherit"), ("a1", "observed", "m-1")])

    def test_config_apply_registers_versions_and_writes_the_record(self):
        _, out = self.run_tool("init", str(self.plan), "--project-id", "P-demo")
        root, config = Path(out["result"]["root"]), self.cwd / "research-tree.yaml"
        shown = self.run_tool("config")[1]["result"]
        self.assertEqual((shown["source"], shown["pending"]), ("file", False))
        self.assertEqual(shown["db_fields"]["max_walltime_s"], 3600)

        # Before the project record exists: the file is registered, nothing else changes.
        code, out = self.run_tool("config", "apply", "--require-project")
        self.assertEqual(code, 2)
        self.assertIn("create_project", out["error"])
        applied = self.run_tool("config", "apply")[1]["result"]
        first = applied["config"]
        self.assertEqual((applied["new_version"], applied["updated_fields"], first["path"]),
                         (True, {}, "project/config.v1.yaml"))
        self.assertEqual(self.run_tool("config", "apply")[1]["result"]["new_version"], False)

        rld = ResearchDB(root / "research_tree.db", "rld/main")
        (root / "docs" / "project" / "min-setup.v1.md").write_text("setup\n", encoding="utf-8")
        setup = rld.register_document("project/min-setup.v1.md", "min_setup", "setup")
        rld.set_document_current(setup)
        rld.create_project("P-demo", "demo", setup, "acc", "higher", True, ["loss"], [7, 8, 9])

        config.write_text(config.read_text(encoding="utf-8")
                          .replace("walltime: 1h", "walltime: 1h30m")
                          .replace("max_parallel_workers: null", "max_parallel_workers: 2")
                          .replace("gate_seeds: 3", "gate_seeds: 2"), encoding="utf-8")
        self.assertTrue(self.run_tool("config")[1]["result"]["pending"])
        code, out = self.run_tool("config", "apply", "--words", "/research-tree config apply")
        self.assertEqual(code, 0, out)
        result = out["result"]
        self.assertEqual(result["config"]["path"], "project/config.v2.yaml")
        self.assertEqual(result["updated_fields"], {"max_walltime_s": 5400, "max_parallel_workers": 2,
                                                    "gate_seeds": 2, "seeds": [7, 8]})
        project = rld.get("P-demo")
        self.assertEqual((project["config_doc_id"], project["seeds"], project["max_walltime_s"]),
                         (result["config"]["doc_id"], [7, 8], 5400))
        self.assertEqual(rld.get(first["doc_id"])["status"], "superseded")
        instruction = rld.get(result["instruction"]["doc_id"])
        self.assertEqual(instruction["doc_type"], "user_instruction")
        shown = self.run_tool("config")[1]["result"]
        self.assertEqual((shown["source"], shown["pending"]), (result["config"]["doc_id"], False))

        # Once an experiment exists the gates are fixed; a refused change registers nothing.
        with Database(root / "research_tree.db") as db, db.write() as txn:
            txn.create_node(labels=["Experiment"], properties={"id": "E-0001"})
            txn.commit()
        config.write_text(config.read_text(encoding="utf-8").replace("gate_seeds: 2", "gate_seeds: 3"), encoding="utf-8")
        code, out = self.run_tool("config", "apply")
        self.assertEqual(code, 2)
        self.assertIn("gate_seeds, seeds can no longer change", out["error"])
        self.assertFalse((root / "docs" / "project" / "config.v3.yaml").exists())

        # A broken file is reported; the registered version stays in effect.
        config.write_text("budget: [", encoding="utf-8")
        shown = self.run_tool("config")[1]["result"]
        self.assertIn("not valid YAML", shown["file_error"])
        self.assertEqual(shown["effective"]["stage1"]["gate_seeds"], 2)

    def test_requirements_are_clarified_in_drafts_and_submitted_with_the_words(self):
        _, out = self.run_tool("init", str(self.plan), "--project-id", "P-demo")
        root = Path(out["result"]["root"])
        window = [{"id": "w-0001", "ts": "2026-10-04T07:00:00Z", "role": "user", "text": "把研究范围缩小一点"},
                  {"id": "w-0002", "ts": "2026-10-04T07:00:20Z", "role": "ui", "text": "缩小到哪一个假说？"},
                  {"id": "w-0003", "ts": "2026-10-04T07:01:00Z", "role": "user", "text": "只保留第二个，预算不变"}]
        (root / "messages" / "window.jsonl").write_text("".join(json.dumps(w, ensure_ascii=False) + "\n" for w in window),
                                                        encoding="utf-8")
        code, out = self.run_tool("requirement", "draft", "--title", "缩小范围", "--goal", "集中资源", "--messages", "w-0002")
        self.assertIn("w-0002 is not a message of the person", out["error"])
        draft = self.run_tool("requirement", "draft", "--title", "缩小范围", "--goal", "集中资源",
                              "--messages", "w-0001")[1]["result"]
        self.assertEqual((draft["id"], draft["status"], draft["version"]), ("REQ-0001", "open", 0))
        code, out = self.run_tool("requirement", "submit", "--req", "REQ-0001")
        self.assertIn("范围", out["error"])  # still unclear: the UI keeps asking

        self.run_tool("requirement", "draft", "--req", "REQ-0001", "--scope", "只保留H-0002", "--open", "预算不变（用户明示）",
                      "--messages", "w-0003", "w-0001")
        code, out = self.run_tool("requirement", "submit", "--req", "REQ-0001")
        self.assertEqual(code, 0, out)
        first = out["result"]
        self.assertEqual((first["version"], first["path"]), (1, "requirements/REQ-0001.v1.md"))
        text = (root / "docs" / first["path"]).read_text(encoding="utf-8")
        for expected in ("## 范围\n\n只保留H-0002", "## 约束\n\n未知", "w-0001", "把研究范围缩小一点", "只保留第二个，预算不变"):
            self.assertIn(expected, text)
        rld = ResearchDB(root / "research_tree.db", "rld/main")
        doc = rld.get(first["doc_id"])
        self.assertEqual((doc["doc_type"], doc["status"], doc["author_role"]), ("user_instruction", "current", "ui"))
        self.assertIn("no changes", self.run_tool("requirement", "submit", "--req", "REQ-0001")[1]["error"])

        # A later change is a new version of the same requirement.
        self.run_tool("requirement", "draft", "--req", "REQ-0001", "--changes", "加上验收标准", "--acceptance", "H-0002完成判定")
        second = self.run_tool("requirement", "submit", "--req", "REQ-0001")[1]["result"]
        self.assertEqual(second["version"], 2)
        self.assertEqual(rld.get(first["doc_id"])["status"], "superseded")
        listed = self.run_tool("requirement", "list")[1]["result"]
        self.assertEqual([(d["id"], d["status"], d["version"]) for d in listed], [("REQ-0001", "submitted", 2)])
        self.assertIn("--req REQ-<n>", self.run_tool("ui", "submit", "--run", "r1")[1]["error"])

    def test_status_without_a_project(self):
        code, out = self.run_tool("status")
        self.assertEqual(code, 2)
        self.assertIn("/research-tree init", out["error"])


if __name__ == "__main__":
    unittest.main()
