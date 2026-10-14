"""Verify the artifact, including execution after extracting outside the source tree."""
from __future__ import annotations

import importlib.util
import json
import os
import subprocess
import sys
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("build_plugins", ROOT / "scripts/build_plugins.py")
builder = importlib.util.module_from_spec(spec)
spec.loader.exec_module(builder)
spec = importlib.util.spec_from_file_location("run_tests", ROOT / "scripts/run_tests.py")
runner = importlib.util.module_from_spec(spec)
spec.loader.exec_module(runner)


class HostParityTest(unittest.TestCase):
    """Both adapters expose the shared read-only API: the Claude mod's READ_ONLY and the Codex hook's READ_METHODS
    are research_db.READ_METHODS."""

    def test_read_only_methods(self):
        import re
        sys.path.insert(0, str(ROOT / "shared/research-tree/tools"))
        from research_db import READ_METHODS
        tsx = (ROOT / "claude-mod/research-tree/hooks/register.tsx").read_text(encoding="utf-8")
        claude = re.search(r"const READ_ONLY = /\^\(([^)]*)\)\$/", tsx).group(1).split("|")
        hook = (ROOT / "codex-plugin/research-tree/tools/codex_hook.py").read_text(encoding="utf-8")
        codex = re.findall(r'"([a-z_]+)"', re.search(r"READ_METHODS = \{([^}]*)\}", hook).group(1))
        self.assertEqual(sorted(claude), sorted(READ_METHODS))
        self.assertEqual(sorted(codex), sorted(READ_METHODS))


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
            # prepare with a stand-in uv (no network): the plan stays, the configuration is copied.
            fake = Path(tmp) / "bin"
            fake.mkdir()
            (fake / "uv").write_text("#!/bin/sh\n[ \"$1\" = init ] && echo '[project]' > pyproject.toml\nexit 0\n")
            (fake / "uv").chmod(0o755)
            env = {**os.environ, "PATH": f"{fake}{os.pathsep}{os.environ['PATH']}"}
            prepared = subprocess.run(["sh", str(plugin / "tools/prepare.sh")], cwd=project, env=env,
                                      capture_output=True, text=True)
            self.assertEqual(prepared.returncode, 0, prepared.stderr)
            self.assertEqual((project / "plan.md").read_text(), "# 独立安装包验证\n")
            cmd = [sys.executable, str(plugin / "tools/research_tree.py")]
            initialized = subprocess.run(cmd + ["init", "--project-id", "standalone"],
                                         cwd=project, capture_output=True, text=True)
            self.assertEqual(initialized.returncode, 0, initialized.stderr + initialized.stdout)
            marker = json.loads(initialized.stdout)["result"]
            self.assertTrue(Path(marker["db"]).is_file())
            shown = subprocess.run(cmd + ["config"], cwd=project, capture_output=True, text=True)
            self.assertEqual(shown.returncode, 0, shown.stderr)
            config = json.loads(shown.stdout)["result"]["effective"]
            self.assertEqual(config["version"], 3)
            self.assertEqual(config["verification"]["screening_seeds"], [42])
            self.assertNotIn("workflow", config)
            self.assertNotIn("discovery", config)
            self.assertNotIn("lens_assistant", config["models"])
            self.assertEqual(marker["format_version"], 3)

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

    def test_bundles_exclude_obsolete_configuration_and_review_contracts(self):
        with tempfile.TemporaryDirectory() as tmp:
            output = Path(tmp) / "dist"
            builder.build(["claude", "codex"], output)
            for host in ("claude", "codex"):
                plugin = output / host / "plugins/research-tree"
                self.assertFalse(list((plugin / "schema").glob("config.v1.*")))
                self.assertFalse((plugin / "schema/web_builder.md").exists())
                self.assertTrue((plugin / "schema/progress_page.md").is_file())
                manifest = json.loads((plugin / builder.MANIFESTS[host]).read_text())
                self.assertEqual(manifest["version"], "0.2.0")
                self.assertEqual({p.stem.removesuffix(".schema") for p in (plugin / "schema/reviews").glob("*.json")},
                                 {"ablation_plan", "code_review", "candidate_recheck"})
                if host == "claude":
                    manifest = json.loads((plugin / ".claude-plugin/plugin.json").read_text())
                    self.assertNotIn("actor", manifest.get("userConfig", {}))
                schema = json.loads((plugin / "schema/config.schema.json").read_text())
                self.assertEqual(schema["properties"]["version"]["const"], 3)
                self.assertNotIn("workflow", schema["properties"])
                self.assertNotIn("discovery", schema["properties"])
                self.assertNotIn("lens_assistant", schema["properties"]["models"]["properties"])
                self.assertRegex((plugin / "schema/create_db.py").read_text(), r"SCHEMA_VERSION\s*=\s*23\b")

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


class TestRunnerTest(unittest.TestCase):
    """scripts/run_tests.py runs the Codex adapter's tests from the current sources, never a stale dist/."""

    def test_codex_suite_is_built_from_the_current_sources_outside_the_repository(self):
        with tempfile.TemporaryDirectory() as tmp:
            tests = runner.build_codex(Path(tmp))
            self.assertTrue(tests.is_relative_to(Path(tmp)))
            for source in (ROOT / "codex-plugin/research-tree/tests").glob("test_codex*.py"):
                self.assertEqual((tests / source.name).read_bytes(), source.read_bytes())
            self.assertTrue(runner.jobs("codex", tests, []))

    def test_a_failed_build_or_a_missing_suite_fails_the_run(self):
        failed = subprocess.CompletedProcess([], 2, "", "build failed: codex adapter is incomplete")
        with tempfile.TemporaryDirectory() as tmp, mock.patch.object(runner.subprocess, "run", return_value=failed):
            with self.assertRaisesRegex(SystemExit, "build failed"):
                runner.build_codex(Path(tmp))
        with tempfile.TemporaryDirectory() as tmp:
            for base in (Path(tmp), Path(tmp) / "missing"):
                with self.assertRaisesRegex(SystemExit, "no test_codex"):
                    runner.jobs("codex", base, [])


if __name__ == "__main__":
    unittest.main()
