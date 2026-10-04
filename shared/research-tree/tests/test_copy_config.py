"""The pre-init config command must work without Python/uv on PATH and preserve user files."""
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]


class CopyConfigTest(unittest.TestCase):
    def test_copy_without_runtime_and_preserve_existing_file_or_symlink(self):
        with tempfile.TemporaryDirectory() as temp:
            cwd = Path(temp) / "用户 项目"
            cwd.mkdir()
            bin_dir = Path(temp) / "bin"
            bin_dir.mkdir()
            # Only the helper's POSIX utilities are available, no Python or uv.
            for tool in ("dirname", "cat"):
                (bin_dir / tool).symlink_to(shutil.which(tool))
            env = {**os.environ, "PATH": str(bin_dir)}
            command = [shutil.which("sh"), str(ROOT / "tools/copy_config.sh")]
            copied = subprocess.run(command, cwd=cwd, env=env, capture_output=True, text=True)
            self.assertEqual(copied.returncode, 0, copied.stderr)
            config = cwd / "research-tree.yaml"
            self.assertEqual(config.read_bytes(), (ROOT / "schema/config.template.yaml").read_bytes())
            self.assertEqual(list(cwd.iterdir()), [config])
            config.write_text("# 用户配置\n")
            again = subprocess.run(command, cwd=cwd, env=env, capture_output=True, text=True)
            self.assertNotEqual(again.returncode, 0)
            self.assertEqual(config.read_text(), "# 用户配置\n")
            config.unlink()
            outside = Path(temp) / "missing.yaml"
            config.symlink_to(outside)
            refused = subprocess.run(command + [str(cwd)], env=env, capture_output=True, text=True)
            self.assertNotEqual(refused.returncode, 0)
            self.assertTrue(config.is_symlink())
            self.assertFalse(outside.exists())


if __name__ == "__main__":
    unittest.main()
