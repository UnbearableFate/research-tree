#!/usr/bin/env python3
"""Run the repository's unittest suites in parallel (one subprocess per test class).

    python3 scripts/run_tests.py                       # shared core + repository tests + Codex adapter (from dist/)
    python3 scripts/run_tests.py test_units test_s7    # only these shared test modules (fast development loop)
    python3 scripts/run_tests.py --suite repo          # only tests/ ; --suite codex: the built Codex adapter
    python3 scripts/run_tests.py -j 8                  # at most 8 classes at a time (default: CPU count, max 32)

Each test class runs in its own `python -m unittest <module.Class>` process, so classes share no module state and
the results equal a serial run's. A class that fails is shown with its output; the exit code is non-zero when any
test failed or errored. During development run the affected modules; run the whole set before a commit or merge.
"""
from __future__ import annotations

import argparse
import ast
import os
import re
import subprocess
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
PY = str(REPO / ".venv" / "bin" / "python")
SUITES = {"shared": REPO / "shared" / "research-tree" / "tests", "repo": REPO / "tests",
          "codex": REPO / "dist" / "codex" / "plugins" / "research-tree" / "tests"}
RAN_RE = re.compile(r"^Ran (\d+) tests? in", re.M)


def classes(path: Path) -> list[str]:
    """The TestCase classes a module defines (by name: any class with test_ methods or a Test/Fixture base)."""
    tree = ast.parse(path.read_text(encoding="utf-8"))
    out = []
    for node in tree.body:
        if isinstance(node, ast.ClassDef):
            has_tests = any(isinstance(n, ast.FunctionDef) and n.name.startswith("test") for n in node.body)
            inherits = any(isinstance(b, (ast.Name, ast.Attribute)) for b in node.bases)
            if has_tests or (inherits and node.name.endswith("Test")):
                out.append(node.name)
    return out


def jobs(suite: str, modules: list[str]) -> list[tuple[Path, str]]:
    base = SUITES[suite]
    if not base.is_dir():
        return []
    pattern = "test_codex*.py" if suite == "codex" else "test_*.py"
    found = []
    for path in sorted(base.glob(pattern)):
        if modules and path.stem not in modules:
            continue
        found += [(base, f"{path.stem}.{c}") for c in classes(path)]
    return found


def run(job: tuple[Path, str]) -> tuple[str, int, int, str, float]:
    base, test_id = job
    start = time.monotonic()
    out = subprocess.run([PY, "-m", "unittest", test_id], cwd=base, capture_output=True, text=True)
    text = out.stdout + out.stderr
    m = RAN_RE.search(text)
    return test_id, out.returncode, int(m.group(1)) if m else 0, text, time.monotonic() - start


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("modules", nargs="*", help="shared test module names (test_units, ...); default: all")
    p.add_argument("--suite", choices=[*SUITES, "all"], default=None)
    p.add_argument("-j", "--jobs", type=int, default=min(32, os.cpu_count() or 4))
    a = p.parse_args()
    suites = [a.suite] if a.suite and a.suite != "all" else (["shared"] if a.modules else list(SUITES))
    todo = [j for s in suites for j in jobs(s, a.modules)]
    if not todo:
        print("no tests selected")
        return 1
    start = time.monotonic()
    with ThreadPoolExecutor(max_workers=a.jobs) as pool:
        results = list(pool.map(run, todo))
    failed = [r for r in results if r[1] != 0]
    total = sum(r[2] for r in results)
    for test_id, _, _, text, secs in failed:
        print(f"===== FAILED {test_id} ({secs:.1f} s)\n{text.strip()[-4000:]}\n")
    slow = sorted(results, key=lambda r: -r[4])[:3]
    print(f"Ran {total} tests in {len(todo)} classes, {time.monotonic() - start:.1f} s wall "
          f"(slowest: {', '.join(f'{r[0]} {r[4]:.0f}s' for r in slow)})")
    print("FAILED" if failed else "OK")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
