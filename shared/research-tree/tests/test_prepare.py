"""prepare: a uv project with the tools' dependencies, plus plan.md and research-tree.yaml to fill in. No Python."""
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
FAKE_UV = """#!/bin/sh
printf '%s\\n' "$*" >> "$FAKE_UV_LOG"
case $1 in
    --version) echo 'uv 0.0.0 (fake)' ;;
    init) [ "${FAKE_UV_FAIL:-}" = init ] && { echo 'no python' >&2; exit 2; }; echo '[project]' > pyproject.toml ;;
    add) [ "${FAKE_UV_FAIL:-}" = add ] && { echo 'offline' >&2; exit 2; }; mkdir -p .venv ;;
esac
"""


class PrepareTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.cwd = Path(self.tmp.name) / "用户 项目"
        self.cwd.mkdir()
        self.bin = Path(self.tmp.name) / "bin"
        self.bin.mkdir()
        # Only POSIX utilities and uv: no Python on PATH.
        for tool in ("dirname", "cat", "tail", "mkdir"):
            (self.bin / tool).symlink_to(shutil.which(tool))
        (self.bin / "uv").write_text(FAKE_UV)
        (self.bin / "uv").chmod(0o755)
        self.log = Path(self.tmp.name) / "uv.log"
        self.env = {"PATH": str(self.bin), "FAKE_UV_LOG": str(self.log), "HOME": self.tmp.name}

    def tearDown(self):
        self.tmp.cleanup()

    def prepare(self, *args, **env):
        return subprocess.run([shutil.which("sh"), str(ROOT / "tools/prepare.sh"), *args], cwd=self.cwd,
                              env={**self.env, **env}, capture_output=True, text=True)

    def calls(self):
        return self.log.read_text().splitlines() if self.log.exists() else []

    def test_prepare_makes_a_uv_project_and_copies_both_templates(self):
        done = self.prepare("--python=3.12")
        self.assertEqual(done.returncode, 0, done.stderr)
        self.assertEqual(self.calls(), ["--version", "init . --no-workspace --python=3.12",
                                        "add --project . latticedb==0.15.0 jsonschema>=4.26 pyyaml>=6.0 pypdf>=5.1"])
        self.assertEqual((self.cwd / "plan.md").read_bytes(), (ROOT / "schema/plan.template.md").read_bytes())
        self.assertEqual((self.cwd / "research-tree.yaml").read_bytes(), (ROOT / "schema/config.template.yaml").read_bytes())
        self.assertIn("下一步", done.stdout)

    def test_prepare_again_keeps_the_users_files_and_project(self):
        self.prepare()
        (self.cwd / "plan.md").write_text("# 我的计划\n")
        (self.cwd / "research-tree.yaml").unlink()
        (self.cwd / "research-tree.yaml").symlink_to(Path(self.tmp.name) / "missing.yaml")
        self.log.unlink()
        again = self.prepare("--python", "3.11")
        self.assertEqual(again.returncode, 0, again.stderr)
        self.assertNotIn("init . --no-workspace --python=3.11", self.calls())  # pyproject.toml is there
        self.assertEqual((self.cwd / "plan.md").read_text(), "# 我的计划\n")
        self.assertTrue((self.cwd / "research-tree.yaml").is_symlink())
        self.assertFalse((Path(self.tmp.name) / "missing.yaml").exists())
        self.assertIn("保留已有的研究计划", again.stdout)

    def test_prepare_stops_without_uv_or_when_uv_fails(self):
        (self.bin / "uv").unlink()
        missing = self.prepare()
        self.assertEqual(missing.returncode, 1)
        self.assertIn("需要 uv", missing.stderr)
        (self.bin / "uv").write_text(FAKE_UV)
        (self.bin / "uv").chmod(0o755)
        failed = self.prepare(FAKE_UV_FAIL="add")
        self.assertEqual(failed.returncode, 1)
        self.assertIn("offline", failed.stderr)
        self.assertFalse((self.cwd / "plan.md").exists())  # nothing to fill in before the environment works
        self.assertEqual(self.prepare("--venv").returncode, 2)


if __name__ == "__main__":
    unittest.main()
