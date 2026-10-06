#!/usr/bin/env python3
"""Codex workflow/context and file guards. This guardrail is not an OS security boundary."""
from __future__ import annotations

import json
import os
import re
import shlex
import sys
import time
from pathlib import Path

from codex_state import cache_dir, locked, project_dir, read_json, write_json

ROOT = Path(__file__).resolve().parents[1]
CONFIG = "research-tree.yaml"
# research_db.READ_METHODS; the hook runs without the project's packages, so the list is repeated (a test keeps
# the two equal).
READ_METHODS = {"help", "get", "find", "edges", "children", "history", "go_candidates", "latest_result",
                "screen_seed_count", "export_snapshot", "verify_document", "resume_package", "cleanup_due",
                "get_eligibility", "evaluations", "preview_evaluation"}
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
    if target == db.parent.parent.parent / CONFIG:
        return f"{CONFIG} 由用户修改：请用户自己编辑它，再用 research_control config apply 生效；需要变更时向用户说明理由。"
    guards = summary.get("guards", {})
    if any(target == Path(p).resolve() for p in guards.get("frozen_docs", [])):
        return "这是已生效文档；写 vN+1 并登记为新版本。"
    for prefix in guards.get("harness", []):
        base = Path(prefix).resolve()
        if target == base or base in target.parents:
            return "节点不能修改冻结的实验框架或统计代码。"
    return None


def research_calls(tokens):
    """The research_db.py / research_tree.py calls among shell tokens: (script, actor named, method or subcommand)."""
    calls = []
    for i, token in enumerate(tokens):
        script = Path(token).name
        if script not in {"research_db.py", "research_tree.py"}:
            continue
        actor = method = None
        j = i + 1
        while j < len(tokens) and tokens[j] not in {";", "&&", "||", "|", "&"}:
            flag, _, inline = tokens[j].partition("=")
            if flag in {"--actor", "--db", "--root"}:
                value = inline or (tokens[j + 1] if j + 1 < len(tokens) else None)
                j += 0 if inline else 1
                actor = value if flag == "--actor" else actor
            elif not tokens[j].startswith("-") and method is None:
                method = tokens[j]
            j += 1
        calls.append((script, actor, method))
    return calls


def call_block(calls, actor):
    """Only the RLD drives the tools from a shell; a worker acts as itself, any other session only reads."""
    if actor == "rld/main":
        return None
    for script, named, method in calls:
        if script == "research_tree.py" and method != "query":
            return f"{actor} 不运行 research_tree.py {method or ''}：它是插件与UI控制器的入口。"
        if script != "research_db.py":
            continue
        if actor.startswith("worker/") and named != actor:
            return f"{actor} 只能以自己的身份调用 research_db（--actor {actor}）；MCP research_db 自动固定身份。"
        if not actor.startswith("worker/") and method not in READ_METHODS:
            return f"{actor} 只读研究数据库（{method or '未知方法'} 会写入）。"
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
        blocked = call_block(research_calls(tokens), os.environ.get("RESEARCH_TREE_ACTOR", "rld/main"))
        if blocked:
            return blocked
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
    if kind == "SessionStart" and actor != "rld/main" and event.get("model"):
        # The model the session actually runs on: the observed side of rule 2's model records.
        log = Path(marker["root"]) / "logs" / "agent_models.jsonl"
        log.parent.mkdir(parents=True, exist_ok=True)
        with log.open("a", encoding="utf-8") as stream:
            stream.write(json.dumps({"ts": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), "agent": event.get("session_id"),
                                     "actor": actor, "event": "observed", "model": event["model"]}, ensure_ascii=False) + "\n")
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
