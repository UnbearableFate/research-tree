"""Verify the artifact, including execution after extracting outside the source tree."""
from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
import tempfile
import unittest
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("build_plugins", ROOT / "scripts/build_plugins.py")
builder = importlib.util.module_from_spec(spec)
spec.loader.exec_module(builder)


class PackagingTest(unittest.TestCase):
    def test_standalone_claude_bundle_and_reproducible_archive(self):
        with tempfile.TemporaryDirectory() as tmp:
            output = Path(tmp) / "dist"
            result = builder.build(["claude"], output)[0]
            bundle = Path(result["archive"])
            first = bundle.read_bytes()
            builder.build(["claude"], output)
            self.assertEqual(first, bundle.read_bytes())
            with zipfile.ZipFile(bundle) as z:
                self.assertFalse(any("__pycache__" in p or ".pyc" in p or ".claude-plugin/types/" in p
                                     for p in z.namelist()))
                z.extractall(Path(tmp) / "unpacked")
            market = Path(tmp) / "unpacked/research-tree-claude"
            catalog = json.loads((market / ".claude-plugin/marketplace.json").read_text())
            plugin = market / catalog["plugins"][0]["source"]
            self.assertTrue((plugin / "hooks/register.tsx").is_file())
            self.assertEqual((plugin / "tools/research_db.py").read_bytes(),
                             (ROOT / "shared/research-tree/tools/research_db.py").read_bytes())
            # Exercise the copied backend in a new project, without source-relative imports.
            project = Path(tmp) / "user project"
            project.mkdir()
            (project / "plan.md").write_text("# 独立安装包验证\n")
            copied = subprocess.run(["sh", str(plugin / "tools/copy_config.sh")],
                                    cwd=project, capture_output=True, text=True)
            self.assertEqual(copied.returncode, 0, copied.stderr)
            cmd = [sys.executable, str(plugin / "tools/research_tree.py")]
            initialized = subprocess.run(cmd + ["init", "plan.md", "--project-id", "standalone",
                                                 "--config", "research-tree.yaml"],
                                         cwd=project, capture_output=True, text=True)
            self.assertEqual(initialized.returncode, 0, initialized.stderr + initialized.stdout)
            marker = json.loads(initialized.stdout)["result"]
            self.assertTrue(Path(marker["db"]).is_file())
            shown = subprocess.run(cmd + ["config"], cwd=project, capture_output=True, text=True)
            self.assertEqual(shown.returncode, 0, shown.stderr)
            self.assertEqual(json.loads(shown.stdout)["result"]["effective"]["stage1"]["gate_seeds"], 3)

    def test_collisions_and_missing_adapter_do_not_replace_working_build(self):
        import shutil
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp) / "repo"
            for name in ("shared", "claude-mod", ".claude-plugin"):
                shutil.copytree(ROOT / name, repo / name, ignore=shutil.ignore_patterns("__pycache__"))
            for name in ("pyproject.toml", "uv.lock"):
                shutil.copyfile(ROOT / name, repo / name)
            output = Path(tmp) / "dist"
            builder.build(["claude"], output, repo)
            before = (output / "claude/BUILD.json").read_bytes()
            with self.assertRaisesRegex(ValueError, "incomplete"):
                builder.build(["claude", "codex"], output, repo)
            self.assertEqual(before, (output / "claude/BUILD.json").read_bytes())
            duplicate = repo / "claude-mod/research-tree/tools/research_db.py"
            duplicate.parent.mkdir(exist_ok=True)
            duplicate.write_text("duplicate")
            with self.assertRaisesRegex(ValueError, "collision"):
                builder.build(["claude"], output, repo)
            self.assertEqual(before, (output / "claude/BUILD.json").read_bytes())

    def test_refuses_to_overwrite_sources_or_unowned_directory(self):
        with self.assertRaisesRegex(ValueError, "overlaps"):
            builder.build(["claude"], ROOT / "shared")
        with tempfile.TemporaryDirectory() as tmp:
            output = Path(tmp)
            (output / "claude").mkdir()
            (output / "claude/keep.txt").write_text("user data")
            with self.assertRaisesRegex(ValueError, "non-build"):
                builder.build(["claude"], output)
            self.assertEqual((output / "claude/keep.txt").read_text(), "user data")

    def test_two_host_assembly_has_identical_common_code(self):
        with tempfile.TemporaryDirectory() as tmp:
            output = Path(tmp) / "dist"
            builder.build(["claude", "codex"], output)
            catalog = json.loads((output / "codex/.agents/plugins/marketplace.json").read_text())
            self.assertEqual(catalog["plugins"][0]["source"],
                             {"source": "local", "path": "./plugins/research-tree"})
            for rel, source in builder.source_files(ROOT / "shared/research-tree"):
                for host in ("claude", "codex"):
                    self.assertEqual(source.read_bytes(),
                                     (output / host / "plugins/research-tree" / rel).read_bytes())


if __name__ == "__main__":
    unittest.main()
