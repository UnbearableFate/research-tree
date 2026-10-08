#!/usr/bin/env python3
"""Human-facing control/UI console. Use the project's .venv Python.

Examples: codex_cli.py prepare; codex_cli.py init; codex_cli.py ui; codex_cli.py status
"""
from __future__ import annotations

import argparse
import json
import os
import selectors
import subprocess
import sys
from pathlib import Path

from codex_mcp import run_request


def prepare(project, python, update_uv):
    """A uv project with the tools' packages, plus plan.md and research-tree.yaml to fill in (tools/prepare.sh)."""
    command = ["sh", str(Path(__file__).resolve().parent / "prepare.sh"), f"--python={python}", str(project)]
    return subprocess.run(command[:3] + (["--update-uv"] if update_uv else []) + command[3:], check=False).returncode


def console(runtime):
    print("研究对话：输入问题/要求；/confirm 明确确认立项，/status 看摘要，/pane 生成页面，/quit 退出窗口。", flush=True)
    seen = set()
    selector = selectors.DefaultSelector()
    selector.register(sys.stdin, selectors.EVENT_READ)
    try:
        while True:
            for entry in runtime.chat():
                if entry["id"] not in seen:
                    if entry["role"] != "user":
                        print(f"[{entry['role']}] {entry['text']}", flush=True)
                    seen.add(entry["id"])
            if not selector.select(timeout=0.5):
                continue
            text = sys.stdin.readline()
            if not text or text.rstrip() == "/quit":
                break
            text = text.rstrip("\n")
            try:
                if text == "/confirm":
                    print(json.dumps(runtime.confirm(text), ensure_ascii=False), flush=True)
                elif text == "/config show":
                    print(json.dumps(runtime.control("config", {}), ensure_ascii=False, indent=2), flush=True)
                elif text in {"/status", "/pane"}:
                    print(json.dumps(runtime.control(text[1:], {}), ensure_ascii=False, indent=2), flush=True)
                elif text in {"/config apply", "/config apply --replace-metric-spec"}:
                    print(json.dumps(runtime.control("config", {"apply": True, "words": text,
                                                                "replace_metric_spec": text.endswith("spec")}),
                                     ensure_ascii=False), flush=True)
                else:
                    runtime.start_ui(text)
            except Exception as exc:
                print(f"未完成：{exc}", flush=True)
    finally:
        selector.close()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project", type=Path, default=Path.cwd())
    parser.add_argument("action", choices=["prepare", "init", "ui", "status", "refresh", "build", "pane", "check", "confirm", "config", "agents", "inbox"])
    parser.add_argument("value", nargs="?")
    parser.add_argument("--id", dest="project_id")
    parser.add_argument("--config", dest="config_file")
    parser.add_argument("--replace-metric-spec", action="store_true",
                        help="config apply: the file's metric_specs replace a specification the RLD registered")
    parser.add_argument("--python", default="3.13")
    parser.add_argument("--update-uv", action="store_true")
    args = parser.parse_args()
    try:
        if args.action == "prepare":
            return prepare(args.project, args.python, args.update_uv)
        if args.action == "init":
            params = {"plan": args.value or "plan.md", "project_id": args.project_id, "config": args.config_file}
            result = run_request(args.project.resolve(), "rld/main", "research_control", {"action": "init", "params": params})
            print(json.dumps(result, ensure_ascii=False, indent=2))
            return 0 if result["ok"] else 2
        python = args.project.resolve() / ".venv/bin/python"
        if not python.is_file():
            raise ValueError(f"missing {python}; initialize this project first")
        if Path(sys.prefix).resolve() != python.parent.parent.resolve():
            os.execv(str(python), [str(python), str(Path(__file__).resolve()), *sys.argv[1:]])
        from codex_runtime import Runtime
        runtime = Runtime(args.project)
        if args.action == "ui":
            console(runtime)
            return 0
        params = {}
        if args.action == "confirm":
            params = {"words": args.value or "/confirm"}
        elif args.action == "config":
            if args.value not in {"show", "apply"}:
                raise ValueError("config accepts show or apply")
            params = {"apply": args.value == "apply", "words": "research-tree config apply",
                      "replace_metric_spec": bool(getattr(args, "replace_metric_spec", False))}
        result = runtime.control(args.action, params)
        print(json.dumps({"ok": True, "result": result}, ensure_ascii=False, indent=2))
        return 1 if args.action == "check" and result["stale"] else 0
    except Exception as exc:
        print(json.dumps({"ok": False, "error": str(exc)}, ensure_ascii=False))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
