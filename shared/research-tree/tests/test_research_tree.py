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
        # The project's own cleanup script, from the plugin's template.
        self.assertEqual((self.cwd / "research-tree-cleanup.py").read_text(encoding="utf-8"),
                         (REPO / "schema" / "cleanup.template.py").read_text(encoding="utf-8"))
        registry = json.loads((root / "agents.json").read_text())
        self.assertIn("ui/ui", registry)
        self.assertIn("architect/root", registry)
        self.assertNotIn("worker/root", registry)

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
        root = Path(out["result"]["root"]).resolve()
        plan_doc = root / "docs" / out["result"]["plan_instruction"]["path"]
        spec_doc = root / "docs" / out["result"]["metric_spec"]["path"]  # a version-3 configuration's specification
        self.assertEqual(sorted(data["guards"]["frozen_docs"]), sorted([str(plan_doc), str(spec_doc)]))

    def test_init_takes_the_prepared_config_a_named_one_or_the_default(self):
        self.run_tool("init", str(self.plan), "--project-id", "P-demo")
        template = (REPO / "schema" / "config.template.yaml").read_text(encoding="utf-8")
        self.assertEqual((self.cwd / "research-tree.yaml").read_text(encoding="utf-8"), template)

        def init(where: str, *args: str) -> dict:
            (self.cwd / where).mkdir(exist_ok=True)
            return json.loads(subprocess.run([sys.executable, str(TOOL), "init", str(self.plan), *args],
                                             cwd=self.cwd / where, capture_output=True, text=True).stdout)
        # The file prepare copied and the user edited is the one used; it is checked first.
        prepared = self.cwd / "prepared"
        prepared.mkdir()
        (prepared / "research-tree.yaml").write_text("version: 3\nbudget:\n  per_run:\n    nodes: 0\n  typo: 1\n", encoding="utf-8")
        error = init("prepared")["error"]
        self.assertIn("budget.per_run.nodes", error)
        self.assertIn("'typo' was unexpected", error)
        self.assertFalse((prepared / "research").exists())
        (prepared / "research-tree.yaml").write_text("version: 3\nbudget:\n  screen_node_h: 4\n", encoding="utf-8")
        self.assertTrue(init("prepared")["ok"])
        self.assertEqual((prepared / "research-tree.yaml").read_text(encoding="utf-8"), "version: 3\nbudget:\n  screen_node_h: 4\n")

        # Another file is named with --config; it does not replace a different one already there.
        good = self.cwd / "cluster.yaml"
        good.write_text("version: 3\nbudget:\n  screen_node_h: 4\n", encoding="utf-8")
        (self.cwd / "named").mkdir()
        (self.cwd / "named" / "research-tree.yaml").write_text("version: 3\nbudget:\n  screen_node_h: 5\n", encoding="utf-8")
        self.assertIn("already exists", init("named", "--config", str(good))["error"])
        self.assertTrue(init("copied", "--config", str(good))["ok"])
        self.assertEqual((self.cwd / "copied" / "research-tree.yaml").read_text(encoding="utf-8"), good.read_text(encoding="utf-8"))

    def test_a_plan_from_the_template_needs_its_goal_and_hypotheses(self):
        template = (REPO / "schema" / "plan.template.md").read_text(encoding="utf-8")
        (self.cwd / "plan.md").write_text(template, encoding="utf-8")
        code, out = self.run_tool("init")  # plan.md by default
        self.assertEqual(code, 2)
        self.assertIn("fill in 研究目标, 初始假说", out["error"])
        filled = template.replace("## 研究目标\n", "## 研究目标\n\n找到更好的LoRA优化器。\n").replace(
            "## 初始假说\n", "## 初始假说\n\n### 假说 1：子批次二阶矩\n预期准确率更高。\n")
        (self.cwd / "plan.md").write_text(filled, encoding="utf-8")
        code, out = self.run_tool("init", "--project-id", "P-plan")
        self.assertEqual(code, 0, out)
        self.assertTrue(out["result"]["plan"].endswith("plan.md"))

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

    def test_config_apply_registers_versions_and_writes_only_active_controls(self):
        code, out = self.run_tool("init", str(self.plan), "--project-id", "P-demo")
        self.assertEqual(code, 0, out)
        marker = out["result"]
        root, config = Path(marker["root"]), self.cwd / "research-tree.yaml"
        shown = self.run_tool("config")[1]["result"]
        self.assertEqual((shown["source"], shown["pending"]), ("file", False))
        code, out = self.run_tool("config", "apply", "--require-project")
        self.assertEqual(code, 2)
        self.assertIn("create_project", out["error"])
        code, out = self.run_tool("config", "apply")  # a change rests on the user's words, never made-up ones
        self.assertEqual(code, 2)
        self.assertIn("--words", out["error"])
        self.assertIsNone(json.loads((self.cwd / ".research-tree.json").read_text())["config"])
        first = self.run_tool("config", "apply", "--words", "按这个配置开始")[1]["result"]["config"]
        self.assertFalse(self.run_tool("config", "apply")[1]["result"]["new_version"])  # nothing changes: no words
        rld = ResearchDB(root / "research_tree.db", "rld/main")
        (root / "docs/project/min-setup.v1.md").write_text("setup\n")
        setup = rld.register_document("project/min-setup.v1.md", "min_setup", "setup")
        rld.set_document_current(setup)
        protocol = {"version": 1, "eval_type": "real_gt", "pair_fields": ["seed"],
                    **shown["protocol_requirements"]}
        (root / "docs/project/protocol.v1.json").write_text(json.dumps(protocol))
        proto = rld.register_document("project/protocol.v1.json", "protocol", "protocol")
        rld.set_document_current(proto)
        fields = dict(shown["db_fields"])
        seeds = fields.pop("seeds")
        rld.create_project("P-demo", "demo", setup, "accuracy", "higher", ["train_time_s"], seeds,
                           metric_spec_doc_id=marker["metric_spec"]["doc_id"], protocol_doc_id=proto, **fields)
        original = config.read_text()
        before = rld.export_snapshot()
        config.write_text(original.replace("replication_seeds: [43, 44]", "replication_seeds: [42]"))
        code, out = self.run_tool("config", "apply")
        self.assertEqual(code, 2)
        self.assertIn("distinct", out["error"])
        self.assertEqual(rld.export_snapshot(), before)
        config.write_text(original.replace("walltime: 1h", "walltime: 1h30m")
                         .replace("max_parallel_workers: null", "max_parallel_workers: 2")
                         .replace("replication_seeds: [43, 44]", "replication_seeds: [43]"))
        self.assertTrue(self.run_tool("config")[1]["result"]["pending"])
        code, out = self.run_tool("config", "apply", "--words", "/research-tree config apply")
        self.assertEqual(code, 0, out)
        result = out["result"]
        self.assertEqual(result["config"]["path"], "project/config.v2.yaml")
        self.assertEqual(result["updated_fields"], {"max_walltime_s": 5400, "max_parallel_workers": 2,
                                                   "gate_seeds": 2, "seeds": [42, 43]})
        self.assertEqual(rld.get(first["doc_id"])["status"], "superseded")
        self.assertEqual(rld.get(result["instruction"]["doc_id"])["doc_type"], "user_instruction")
        shown = self.run_tool("config")[1]["result"]
        self.assertEqual((shown["source"], shown["pending"]), (result["config"]["doc_id"], False))
        with Database(root / "research_tree.db") as db, db.write() as txn:
            txn.create_node(labels=["Experiment"], properties={"id": "E-0001"})
            txn.commit()
        config.write_text(config.read_text().replace("replication_seeds: [43]", "replication_seeds: [43, 44]"))
        code, out = self.run_tool("config", "apply")
        self.assertEqual(code, 2)
        self.assertIn("gate_seeds, seeds can no longer change", out["error"])
        self.assertFalse((root / "docs/project/config.v3.yaml").exists())
        config.write_text("budget: [")
        shown = self.run_tool("config")[1]["result"]
        self.assertIn("not valid YAML", shown["file_error"])
        self.assertEqual(shown["effective"]["verification"]["replication_seeds"], [43])

    def test_legacy_project_marker_is_rejected_before_any_metadata_write(self):
        marker = {"project_id": "old", "root": str(self.cwd / "research/old"), "phase": "planning"}
        path = self.cwd / ".research-tree.json"
        path.write_text(json.dumps(marker))
        before = path.read_bytes()
        for args in (("phase", "--set", "confirmed"), ("config", "apply"), ("status",)):
            code, out = self.run_tool(*args)
            self.assertEqual(code, 2)
            self.assertIn("UNSUPPORTED_PROJECT_VERSION", out["error"])
            self.assertEqual(path.read_bytes(), before)
        self.assertFalse((self.cwd / "research").exists())

    def test_old_configuration_fails_init_without_creating_a_research_directory(self):
        for version in (1, 2):
            (self.cwd / "research-tree.yaml").write_text(f"version: {version}\n")
            code, out = self.run_tool("init", str(self.plan))
            self.assertEqual(code, 2)
            self.assertIn("UNSUPPORTED_CONFIG_VERSION", out["error"])
            self.assertFalse((self.cwd / "research").exists())
            self.assertFalse((self.cwd / ".research-tree.json").exists())

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


class ConfigV3Test(unittest.TestCase):
    """Version 3 states the gate once (metric_specs and verification); init registers the specification;
    the Leader's protocol must agree with the configured profile and confirmation settings."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.cwd = Path(self.tmp.name)
        (self.cwd / "plan.md").write_text("# 计划\n", encoding="utf-8")

    def tearDown(self):
        self.tmp.cleanup()

    def run_tool(self, *args):
        out = subprocess.run([sys.executable, str(TOOL), *args], cwd=self.cwd, capture_output=True, text=True)
        return out.returncode, json.loads(out.stdout)

    def test_display_model_name_reaches_effective_config_without_rewriting_user_file(self):
        path = self.cwd / "research-tree.yaml"
        original = "version: 3\nmodels:\n  ui: {model: Haiku 5, effort: high}\n"
        path.write_text(original, encoding="utf-8")
        code, out = self.run_tool("init", "plan.md", "--project-id", "P-model-name")
        self.assertEqual(code, 0, out)
        code, out = self.run_tool("config")
        self.assertEqual(code, 0, out)
        self.assertEqual(out["result"]["effective"]["models"]["ui"],
                         {"model": "claude-haiku-5-5", "effort": "high"})
        self.assertEqual(path.read_text(encoding="utf-8"), original)

    def test_current_configuration(self):
        code, out = self.run_tool("init", "plan.md", "--project-id", "P-v3")
        self.assertEqual(code, 0, out)
        marker = out["result"]
        root = Path(marker["root"])
        spec = json.loads((root / "docs" / marker["metric_spec"]["path"]).read_text(encoding="utf-8"))
        self.assertEqual((spec["primary"], spec["metrics"][0]["minimum_practical_gain"]), ("accuracy", 0.2))
        rld = ResearchDB(root / "research_tree.db", "rld/main")
        (root / "docs" / "project" / "min-setup.v1.md").write_text("setup\n", encoding="utf-8")
        setup = rld.register_document("project/min-setup.v1.md", "min_setup", "setup")
        rld.set_document_current(setup)
        protocol = {"version": 1, "eval_type": "real_gt", "pair_fields": ["seed"], "profile": "stage1_confirmed",
                    "confirmation_seeds": [1042, 1043, 1044], "min_confirmation_pairs": 3,
                    "max_confirmation_candidates": 3, "require_artifact_import": True}
        (root / "docs" / "project" / "protocol.v1.json").write_text(json.dumps(protocol), encoding="utf-8")
        proto = rld.register_document("project/protocol.v1.json", "protocol", "protocol")
        rld.set_document_current(proto)
        fields = {k: v for k, v in self.run_tool("config")[1]["result"]["db_fields"].items()
                  if k in ("go_margin", "gate_seeds")}
        rld.create_project("P-v3", "v2", setup, "accuracy", "higher", ["train_time_s"], [42, 43, 44],
                           metric_spec_doc_id=marker["metric_spec"]["doc_id"], protocol_doc_id=proto, **fields)
        code, out = self.run_tool("config", "apply", "--require-project")
        self.assertEqual(code, 2)
        self.assertIn("max_confirmation_candidates is 3, the configuration says 2", out["error"])
        agreeing = {**protocol, "profile": "stage1_confirmed", "confirmation_seeds": [1042, 1043, 1044],
                    "min_confirmation_pairs": 3, "max_confirmation_candidates": 2, "require_artifact_import": True}
        (root / "docs" / "project" / "protocol.v2.json").write_text(json.dumps(agreeing), encoding="utf-8")
        proto2 = rld.register_document("project/protocol.v2.json", "protocol", "protocol")
        rld.set_document_current(proto2)
        rld.update_project(protocol_doc_id=proto2)
        code, out = self.run_tool("config", "apply", "--require-project", "--words", "同意立项计划")
        self.assertEqual(code, 0, out)
        # one gate: changing the primary's minimum practical gain changes go_margin with a new specification version
        config = self.cwd / "research-tree.yaml"
        config.write_text(config.read_text(encoding="utf-8").replace("minimum_practical_gain: 0.2",
                                                                     "minimum_practical_gain: 0.3"), encoding="utf-8")
        code, out = self.run_tool("config", "apply", "--words", "门槛改为 0.3 个百分点")
        self.assertEqual(code, 0, out)
        project = rld.get("P-v3")
        self.assertEqual((project["go_margin"], rld.get(project["metric_spec_doc_id"])["path"]),
                         (0.3, "project/metric-spec.v2.json"))
        # the budget cap is the user's: raising it in their file takes effect with their instruction recorded
        for limit in (50000, 90000):
            config.write_text(config.read_text(encoding="utf-8").replace(
                "total_limit: null" if limit == 50000 else "total_limit: 50000", f"total_limit: {limit}"),
                encoding="utf-8")
            code, out = self.run_tool("config", "apply", "--words", f"总预算调到 {limit}")
            self.assertEqual(code, 0, out)
        self.assertEqual(rld.get("P-v3")["total_limit"], 90000)
        self.assertEqual(rld.get(out["result"]["instruction"]["doc_id"])["doc_type"], "user_instruction")


class RealRunFixesTest(unittest.TestCase):
    """plans/real-run-error.md #2/#14 (run from a subdirectory), #9 (relative inputs), #16-#18 (the metric
    specification the RLD registered is not silently reverted by config apply)."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.cwd = Path(self.tmp.name)
        (self.cwd / "plan.md").write_text("# 计划\n", encoding="utf-8")
        (self.cwd / "research-tree.yaml").write_text(
            (REPO / "schema" / "config.template.yaml").read_text(encoding="utf-8"),
            encoding="utf-8")

    def tearDown(self):
        self.tmp.cleanup()

    def run_tool(self, *args, cwd=None):
        out = subprocess.run([sys.executable, str(TOOL), *args], cwd=cwd or self.cwd, capture_output=True, text=True)
        return out.returncode, json.loads(out.stdout)

    def project(self):
        code, out = self.run_tool("init", "plan.md", "--project-id", "P-fix")
        self.assertEqual(code, 0, out)
        marker = out["result"]
        self.root = Path(marker["root"])
        self.rld = ResearchDB(self.root / "research_tree.db", "rld/main")
        (self.root / "docs/project/min-setup.v1.md").write_text("setup\n", encoding="utf-8")
        setup = self.rld.register_document("project/min-setup.v1.md", "min_setup", "setup")
        self.rld.set_document_current(setup)
        protocol = {"version": 1, "eval_type": "real_gt", "pair_fields": ["seed"], "profile": "stage1_confirmed",
                    "confirmation_seeds": [1042, 1043, 1044], "min_confirmation_pairs": 3,
                    "max_confirmation_candidates": 2, "require_artifact_import": True}
        (self.root / "docs/project/protocol.v1.json").write_text(json.dumps(protocol), encoding="utf-8")
        proto = self.rld.register_document("project/protocol.v1.json", "protocol", "protocol")
        self.rld.set_document_current(proto)
        fields = {k: v for k, v in self.run_tool("config")[1]["result"]["db_fields"].items() if k in ("go_margin", "gate_seeds")}
        self.rld.create_project("P-fix", "fix", setup, "accuracy", "higher", ["train_time_s"], [42, 43, 44],
                                metric_spec_doc_id=marker["metric_spec"]["doc_id"], protocol_doc_id=proto, **fields)
        return marker

    def test_tools_find_the_project_from_a_subdirectory(self):
        self.project()
        code, out = self.run_tool("status", cwd=self.root)
        self.assertEqual(code, 0, out)
        self.assertEqual(out["result"]["project_id"], "P-fix")
        code, out = self.run_tool("query", "get", '{"entity_id": "P-fix"}', cwd=self.root / "docs")
        self.assertEqual((code, out["result"]["id"]), (0, "P-fix"))
        # discovery inputs resolve against the research root, like --artifact (#9), from any directory
        self.assertEqual(self.run_tool("discovery", "start")[0], 0)
        users = self.root / "docs/project/discovery/user-hypotheses.json"
        users.parent.mkdir(parents=True, exist_ok=True)
        users.write_text(json.dumps([{"title": "动量", "summary": "s"}]), encoding="utf-8")
        for where in (self.cwd, self.root):
            code, out = self.run_tool("discovery", "merge", "--user-hypotheses",
                                      "docs/project/discovery/user-hypotheses.json", cwd=where)
            self.assertEqual(code, 0, out)
        code, out = self.run_tool("discovery", "merge", "--user-hypotheses", "nope.json")
        self.assertEqual(code, 2)
        self.assertIn("not found under the research root", out["error"])

    def test_unknown_platform_skills_are_reported_with_close_names(self):
        """real-run-error #4: platform.skills named a skill the host did not have (plural vs singular)."""
        import research_tree as rt
        from unittest import mock
        home = self.cwd / "home"
        (home / ".claude/skills/miyabi-pbs-shell-template").mkdir(parents=True)
        (home / ".claude/skills/miyabi-pbs-shell-template/SKILL.md").write_text("x")
        with mock.patch.object(Path, "home", lambda: home):
            check = rt.check_skills(["miyabi-pbs-shell-templates", "miyabi-pbs-shell-template"], self.cwd)
        self.assertEqual(check["missing"], ["miyabi-pbs-shell-templates"])
        self.assertEqual(check["suggestions"]["miyabi-pbs-shell-templates"], ["miyabi-pbs-shell-template"])

    def test_advanced_verification_applies_without_keyerror_and_detects_real_mismatch(self):
        import project_config
        self.project()
        config = project_config.defaults()
        config["verification"]["independence_fields"] = ["training_seed"]
        config["verification"]["repetition"] = {"enabled": True, "batch": 1, "seed_pool": [43, 44]}
        protocol = {"version": 1, "eval_type": "real_gt", "pair_fields": ["seed"],
                    **project_config.protocol_requirements(config)}
        (self.root / "docs/project/protocol.v2.json").write_text(json.dumps(protocol))
        doc = self.rld.register_document("project/protocol.v2.json", "protocol", "advanced verification")
        self.rld.set_document_current(doc)
        self.rld.update_project(protocol_doc_id=doc)
        (self.cwd / "research-tree.yaml").write_text(json.dumps(config))
        for _ in range(2):
            code, out = self.run_tool("config", "apply", "--words", "启用独立性字段与重复建议")
            self.assertEqual(code, 0, out)
        config["verification"]["repetition"]["batch"] = 2
        (self.cwd / "research-tree.yaml").write_text(json.dumps(config))
        code, out = self.run_tool("config", "apply")
        self.assertEqual(code, 2)
        self.assertIn("repetition", out["error"])
        self.assertNotIn("KeyError", out["error"])

    def test_config_apply_does_not_revert_the_rlds_metric_specification(self):
        marker = self.project()
        spec = json.loads((self.root / "docs" / marker["metric_spec"]["path"]).read_text(encoding="utf-8"))
        for m in spec["metrics"]:
            if m["name"] == "train_time_s":
                m["allowed_regression"] = 0.5
        (self.root / "docs/project/metric-spec.v2.json").write_text(json.dumps(spec, ensure_ascii=False, indent=1) + "\n",
                                                                   encoding="utf-8")
        mine = self.rld.register_document("project/metric-spec.v2.json", "metric_spec", "spec v2 (user instruction)")
        self.rld.set_document_current(mine)
        self.rld.update_project(metric_spec_doc_id=mine)
        code, out = self.run_tool("config", "apply")  # the file still says 0.10: refused, nothing reverted
        self.assertEqual(code, 2, out)
        self.assertIn("train_time_s.allowed_regression 0.5 (in effect) vs 0.1 (file)", out["error"])
        self.assertEqual(self.rld.get("P-fix")["metric_spec_doc_id"], mine)
        self.assertEqual(self.rld.get(mine)["status"], "current")
        config = self.cwd / "research-tree.yaml"
        config.write_text(config.read_text(encoding="utf-8").replace("allowed_regression: 0.10", "allowed_regression: 0.5"),
                          encoding="utf-8")
        code, out = self.run_tool("config", "apply", "--words", "用 0.5")  # the file now agrees: taken over
        self.assertEqual(code, 0, out)
        self.assertEqual(self.rld.get("P-fix")["metric_spec_doc_id"], mine)
        self.assertEqual(json.loads((self.cwd / ".research-tree.json").read_text())["metric_spec"]["doc_id"], mine)
        self.assertFalse((self.root / "docs/project/metric-spec.v3.json").exists())
        # the user may decide the file's values replace it
        config.write_text(config.read_text(encoding="utf-8").replace("allowed_regression: 0.5", "allowed_regression: 0.2"),
                          encoding="utf-8")
        code, out = self.run_tool("config", "apply", "--replace-metric-spec", "--words", "改用 0.2")
        self.assertEqual(code, 0, out)
        new = self.rld.get("P-fix")["metric_spec_doc_id"]
        self.assertNotEqual(new, mine)
        self.assertEqual(self.rld.get(mine)["status"], "superseded")


    def test_a_refused_apply_registers_nothing(self):
        """A refusal found after the file was read (a gate locked by experiments) leaves the metric specification,
        the configuration and the marker as they were; no instruction is recorded."""
        marker = self.project()
        self.assertEqual(self.run_tool("config", "apply", "--require-project", "--words", "同意")[0], 0)
        with Database(self.root / "research_tree.db") as db, db.write() as txn:
            txn.create_node(labels=["Experiment"], properties={"id": "E-0001"})
            txn.commit()
        before = (self.cwd / ".research-tree.json").read_text()
        spec = self.rld.get("P-fix")["metric_spec_doc_id"]
        config = self.cwd / "research-tree.yaml"
        config.write_text(config.read_text(encoding="utf-8").replace("minimum_practical_gain: 0.2",
                                                                     "minimum_practical_gain: 0.3"), encoding="utf-8")
        instructions = len(self.rld.find("document", doc_type="user_instruction"))
        code, out = self.run_tool("config", "apply", "--words", "门槛改为 0.3")
        self.assertEqual(code, 2, out)
        self.assertIn("go_margin", out["error"])
        self.assertEqual((self.rld.get("P-fix")["metric_spec_doc_id"], self.rld.get(spec)["status"]), (spec, "current"))
        self.assertEqual((self.cwd / ".research-tree.json").read_text(), before)
        self.assertFalse((self.root / "docs/project/metric-spec.v2.json").exists())
        self.assertFalse((self.root / "docs/project/config.v2.yaml").exists())
        self.assertEqual(len(self.rld.find("document", doc_type="user_instruction")), instructions)
        self.assertEqual(marker["metric_spec"]["doc_id"], spec)

    def test_lowering_a_gate_applies_with_the_users_words(self):
        """Dropping a gate or the exploration share is the user's decision: their words carry it."""
        self.project()
        self.assertEqual(self.run_tool("config", "apply", "--require-project", "--words", "同意")[0], 0)
        config = self.cwd / "research-tree.yaml"
        text = config.read_text(encoding="utf-8")
        self.assertIn("code_review: true", text)
        config.write_text(text.replace("code_review: true", "code_review: false"), encoding="utf-8")
        code, out = self.run_tool("config", "apply", "--words", "这个项目不做代码审查")
        self.assertEqual(code, 0, out)
        self.assertFalse(self.rld.get("P-fix")["code_review_required"])


class NotifyTest(unittest.TestCase):
    """00 §2.4 item 6: confirmation requests and usage alerts may also go to notify.url; every attempt is logged,
    a failure never raises, and an unanswered message to the RLD stays visible in `inbox`."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.cwd = Path(self.tmp.name)
        (self.cwd / "plan.md").write_text("# 计划\n", encoding="utf-8")

    def tearDown(self):
        self.tmp.cleanup()

    def run_tool(self, *args):
        out = subprocess.run([sys.executable, str(TOOL), *args], cwd=self.cwd, capture_output=True, text=True)
        return out.returncode, json.loads(out.stdout)

    def test_webhook_log_and_inbox(self):
        import http.server
        import threading
        received = []

        class Handler(http.server.BaseHTTPRequestHandler):
            def do_POST(self):
                received.append(json.loads(self.rfile.read(int(self.headers["Content-Length"]))))
                self.send_response(204)
                self.end_headers()

            def log_message(self, *args):
                pass

        server = http.server.HTTPServer(("127.0.0.1", 0), Handler)
        threading.Thread(target=server.serve_forever, daemon=True).start()
        self.addCleanup(server.shutdown)
        code, out = self.run_tool("init", "plan.md", "--project-id", "P-n")
        self.assertEqual(code, 0, out)
        root = Path(out["result"]["root"])
        code, out = self.run_tool("notify", "--kind", "alert", "--text", "用量到 1 node·h")
        self.assertEqual((code, out["result"]["outcome"]), (0, "skipped: no notify.url"))
        config = self.cwd / "research-tree.yaml"
        config.write_text(config.read_text(encoding="utf-8").replace(
            "  url: null", f"  url: http://127.0.0.1:{server.server_port}/hook"), encoding="utf-8")
        code, out = self.run_tool("notify", "--kind", "confirm_request", "--text", "请确认立项",
                                  "--docs", "project/reports/init-plan.v1.md")
        self.assertEqual((code, out["result"]["outcome"]), (0, "sent: HTTP 204"))
        self.assertEqual((received[0]["kind"], received[0]["docs"]),
                         ("confirm_request", ["project/reports/init-plan.v1.md"]))
        server.shutdown()
        server.server_close()
        code, out = self.run_tool("notify", "--kind", "alert", "--text", "x")
        self.assertEqual(code, 0)  # the receiver is gone: recorded as failed, the workflow goes on
        self.assertTrue(out["result"]["outcome"].startswith("failed"), out)
        log = [json.loads(line) for line in (root / "logs/notify.jsonl").read_text(encoding="utf-8").splitlines()]
        self.assertEqual([r["outcome"].split(":")[0] for r in log], ["skipped", "sent", "failed"])
        # receipts: a UI message that needs the RLD's answer is listed until a message about it arrives
        (root / "messages").mkdir(exist_ok=True)
        (root / "messages" / "ui.jsonl").write_text(json.dumps(
            {"id": "M-1", "from": "ui/ui", "to": "rld/main", "type": "requirement", "need": "answer",
             "text": "请加一个基线", "about": ["REQ-1"]}, ensure_ascii=False) + "\n", encoding="utf-8")
        code, out = self.run_tool("inbox")
        self.assertEqual((code, [i["id"] for i in out["result"]]), (0, ["REQ-1"]))


class DiscoveryConfigTest(unittest.TestCase):
    def test_discovery_switches_including_unquoted_off_are_unsupported(self):
        import project_config
        for value in ("off", "full", "precheck", "incremental"):
            with self.subTest(value=value), self.assertRaisesRegex(project_config.ConfigError, "unsupported"):
                project_config.parse(f"version: 3\ndiscovery: {{mode: {value}}}\n")
