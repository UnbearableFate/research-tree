#!/usr/bin/env python3
"""Run the end-of-stage review (plans/research-tree-implementation-and-real-scenarios.md §2.6) with Claude Code CLI
(Fable 5.1, effort high) and record it.

    python3 scripts/stage_review.py S0 --round 1 --design plans/research-tree-implementation-and-real-scenarios.md \\
        --base <commit> [--tests path ...] [--final --evidence plans/design/test-logs/S0-claude.md ...]

A new non-interactive session that reads the files itself; the brief holds only paths (no executor summary).
The review counts only when is_error is false, terminal_reason is "completed" and modelUsage names only the
requested model. The raw result and the parsed findings go to plans/design/reviews/<batch>-r<round>.md.
"""
from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
MODEL = "claude-fable-5-1"
PROMPT = "plans/design/reviews/prompts/stage-review.md"


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("batch")
    p.add_argument("--round", type=int, required=True)
    p.add_argument("--design", nargs="+", required=True)
    p.add_argument("--base", required=True, help="commit before the batch; changed files are taken from it")
    p.add_argument("--tests", nargs="*", default=[])
    p.add_argument("--final", action="store_true", help="the final review of the stage's complete diff and evidence")
    p.add_argument("--evidence", nargs="*", default=[], help="scenario records and test logs of both hosts")
    args = p.parse_args()
    changed = subprocess.run(["git", "-C", str(REPO), "diff", "--name-only", "-z", args.base], capture_output=True,
                             text=True, check=True).stdout.split("\0")
    untracked = subprocess.run(["git", "-C", str(REPO), "ls-files", "-z", "--others", "--exclude-standard"],
                               capture_output=True, text=True, check=True).stdout.split("\0")
    changed = sorted(set(changed + untracked) - {""})
    changed = [c for c in changed if not c.startswith("plans/design/reviews/")]
    brief = (f"Review batch {args.batch}{' (final review of the complete diff)' if args.final else ''}. "
             f"Design: {', '.join(args.design)}. Changed files (git diff --name-only {args.base} plus new files): "
             f"{', '.join(changed)}. Tests: {', '.join(args.tests) or 'see changed files'}. "
             + (f"Scenario evidence (records, raw logs, observer output): {', '.join(args.evidence)}. " if args.evidence else "")
             + "Read everything yourself; executor notes are not evidence.")
    cmd = ["claude", "-p", "--output-format", "json", "--model", MODEL, "--effort", "high",
           "--safe-mode", "--restricted", "--strict-mcp-config", "--tools", "Read,Grep,Glob",
           "--permission-mode", "dontAsk", "--permission-prompts", "none", "--no-session-persistence",
           "--append-system-prompt-file", PROMPT, brief]
    record = REPO / "plans/design/reviews" / f"{args.batch}-r{args.round}.md"
    if record.exists():
        print(f"{record} exists; a new review is a new round", file=sys.stderr)
        return 2
    try:
        out = subprocess.run(cmd, cwd=REPO, capture_output=True, text=True, timeout=3600)
    except subprocess.TimeoutExpired:
        print("review not completed: timed out after 3600 s", file=sys.stderr)
        return 2
    try:
        result = json.loads(out.stdout)
    except json.JSONDecodeError:
        print(f"review did not answer JSON (exit {out.returncode}): {out.stderr[-2000:]}", file=sys.stderr)
        return 2
    models = sorted((result.get("modelUsage") or {}).keys())
    ok = result.get("is_error") is False and result.get("terminal_reason") == "completed" and models == [MODEL]
    text = result.get("result") or ""
    findings = last_json_list(text)
    valid = ok and findings is not None
    if not valid:  # an invalid review does not use up the round number
        n = 1
        while (invalid := record.with_name(f"{record.stem}-invalid-{n}.md")).exists():
            n += 1
        record = invalid
    record.parent.mkdir(parents=True, exist_ok=True)
    counts = ({s: sum(1 for f in findings if f.get("severity") == s) for s in ("CRITICAL", "MAJOR", "MINOR")}
              if findings is not None else "未能解析（评审无效）")
    record.write_text(
        f"# {args.batch} 评审第 {args.round} 轮（{MODEL}）\n\n"
        f"- 有效：{valid}（is_error={result.get('is_error')}, terminal_reason={result.get('terminal_reason')}, "
        f"modelUsage={models}）\n- 费用：total_cost_usd={result.get('total_cost_usd')}；num_turns={result.get('num_turns')}\n"
        f"- 发现：{json.dumps(counts, ensure_ascii=False)}\n- brief：{brief}\n\n## 评审原文\n\n{text}\n\n## 修复对照\n\n（待填写）\n",
        encoding="utf-8")
    print(json.dumps({"ok": valid, "record": str(record.relative_to(REPO)), "counts": counts,
                      "cost_usd": result.get("total_cost_usd"), "findings": findings}, ensure_ascii=False, indent=1))
    return 0 if valid else 1


def last_json_list(text: str):
    """The last ```json block that parses as a list of objects; backticks inside strings do not end it."""
    decoder = json.JSONDecoder()
    found = None
    for m in re.finditer(r"```json\s*", text):
        try:
            value, _ = decoder.raw_decode(text, m.end())
        except json.JSONDecodeError:
            continue
        if isinstance(value, list) and all(_finding(v) for v in value):
            found = value
    return found


def _finding(v) -> bool:
    """One finding of the fixed schema of 14 §3."""
    return (isinstance(v, dict) and v.get("severity") in ("CRITICAL", "MAJOR", "MINOR")
            and all(isinstance(v.get(k), str) and v[k] for k in ("file", "claim", "evidence", "suggested_fix")))


if __name__ == "__main__":
    raise SystemExit(main())
