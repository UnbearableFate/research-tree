#!/usr/bin/env python3
"""Codex workflow/context and file guards. This guardrail is not an OS security boundary."""
from __future__ import annotations

import json
import os
import re
import shlex
import sys
from pathlib import Path

from codex_state import cache_dir, locked, project_dir, read_json, write_json

ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = f"""research-tree 项目已启用。主会话是唯一 Research Leader。
读取 {ROOT / 'skills/research-tree/SKILL.md'} 与 {ROOT / 'rules/research-tree-rules.md'}。
只通过 research_db 修改研究数据库；已生效文档写新版本；节点不能修改冻结框架。
用户确认立项前不启动worker；确认后先assign_worker和分配任务，再research_control worker。
worker使用独立Codex会话，主会话不以原生spawn_agent绕开插件的身份/确认/并发门槛。
需要用户决定时post_to_ui；研究UI由用户在第二个终端打开（research_control ui_path）。
用research_control inbox处理未确认事件；已收到后acknowledge，收到回执不再回回执。
"""


def deny(reason):
    return {"hookSpecificOutput": {"hookEventName": "PreToolUse", "permissionDecision": "deny",
                                    "permissionDecisionReason": f"research-tree: {reason}"}}


def protected(path, cwd, summary, db):
    target = (cwd / path).resolve()
    if target == db or str(target).startswith(str(db) + "-"):
        return "不要直接改数据库文件；调用 research_db。"
    guards = summary.get("guards", {})
    if any(target == Path(p).resolve() for p in guards.get("frozen_docs", [])):
        return "这是已生效文档；写 vN+1 并登记为新版本。"
    for prefix in guards.get("harness", []):
        base = Path(prefix).resolve()
        if target == base or base in target.parents:
            return "节点不能修改冻结的实验框架或统计代码。"
    return None


def guard(event, cwd, summary, marker):
    name = event.get("tool_name", "")
    args = event.get("tool_input", {})
    if not isinstance(args, dict):
        return None
    if name in {"spawn_agent", "Agent"}:
        return "项目代理通过 research_control worker 启动；UI由用户的独立入口启动。"
    db = Path(marker["db"]).resolve()
    if name in {"apply_patch", "Edit", "Write", "NotebookEdit"}:
        patch = args.get("command", args.get("input", ""))
        paths = re.findall(r"^\*\*\* (?:Add File|Update File|Delete File|Move to): (.+)$", patch, re.M)
        paths += [args[k] for k in ("file_path", "notebook_path") if args.get(k)]
        for path in paths:
            reason = protected(path, cwd, summary, db)
            if reason:
                return reason
    if name in {"Bash", "exec_command", "shell", "shell_command"}:
        command = args.get("command", args.get("cmd", ""))
        if isinstance(command, list):
            command = shlex.join(command)
        # Shell parsing is deliberately bounded: direct writes, redirection, wrappers,
        # and literal protected paths. Arbitrary Python/shell indirection is not sandboxed.
        try:
            tokens = list(shlex.shlex(command, posix=True, punctuation_chars=";&|<>"))
        except ValueError:
            return None  # let the shell report its own syntax error
        writer = False
        for i, token in enumerate(tokens):
            if token in {";", "&&", "||", "|"}:
                writer = False
                continue
            if Path(token).name in {"rm", "mv", "cp", "dd", "truncate", "sqlite3", "shred", "tee"}:
                writer = True
            if Path(token).name in {"sed", "perl"} and any(t.startswith("-i") for t in tokens[i + 1:]):
                writer = True
            redirect = i > 0 and tokens[i - 1] in {">", ">>", ">|", "&>"}
            if writer or redirect:
                reason = protected(token, cwd, summary, db)
                if reason:
                    return reason
    return None


def handle(event):
    cwd = Path(event.get("cwd", ".")).resolve()
    project = project_dir(cwd)
    marker = read_json(project / ".research-tree.json")
    if not marker:
        return {}
    cache = cache_dir(project)
    kind = event.get("hook_event_name")
    actor = os.environ.get("RESEARCH_TREE_ACTOR", "rld/main")
    # Only the main CLI records its address. Child sessions never become the Leader.
    if actor == "rld/main" and kind in {"SessionStart", "PostToolUse"} and event.get("session_id"):
        with locked(cache / "leader.lock"):
            previous = read_json(cache / "leader.json", {})
            if not previous.get("session_id") or previous["session_id"] == event["session_id"]:
                write_json(cache / "leader.json", {"session_id": event["session_id"], "model": event.get("model") or previous.get("model")})
            else:
                return {"systemMessage": "research-tree已有另一RLD会话；若需要接管，先核对原会话与作业，再用research_control attach登记交接。"}
    summary = read_json(cache / "summary.json", {})
    if kind == "PreToolUse":
        reason = guard(event, cwd, summary, marker)
        return deny(reason) if reason else {}
    if kind == "SessionStart":
        return {"hookSpecificOutput": {"hookEventName": kind, "additionalContext": WORKFLOW +
                                        f"\n项目 {marker['project_id']}：{marker['phase']}。当前数据摘要可能是旧快照，用status刷新。"}}
    if kind == "Stop" and actor == "rld/main":
        inbox = read_json(cache / "inbox.json", [])
        pending = [x for x in inbox if not x["acknowledged"]]
        if pending and not event.get("stop_hook_active"):
            return {"decision": "block", "reason": "research-tree有未处理事件，请读取research_control inbox并处理/acknowledge。"}
    return {}


def main():
    try:
        event = json.load(sys.stdin)
        response = handle(event)
    except Exception as exc:
        # Explicit denials for pre-tool failures; hook errors otherwise fail open in Codex.
        response = deny(f"无法核对项目保护状态：{exc}") if locals().get("event", {}).get("hook_event_name") == "PreToolUse" else {"systemMessage": f"research-tree hook: {exc}"}
    print(json.dumps(response, ensure_ascii=False))


if __name__ == "__main__":
    main()
