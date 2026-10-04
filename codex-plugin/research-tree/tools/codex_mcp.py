#!/usr/bin/env python3
"""Dependency-free stdio MCP entrypoint; research calls use the project's Python.

The transport can start before init creates .venv. No SDK, network service or API key
is needed for the server. Authentication for agent sessions belongs to Codex CLI.
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path

from codex_state import actor_key, project_dir

ROOT = Path(__file__).resolve().parents[1]


def schema(properties, required=()):
    return {"type": "object", "properties": {"project": {"type": "string", "description": "Absolute research project directory (the user's workspace, not the plugin directory). Always supply from the main session."}, **properties},
            "required": list(required), "additionalProperties": False}


STRING = {"type": "string"}
OBJECT = {"type": "object"}
TOOLS = [
    {"name": "research_db", "description": "Call the research database as this session's fixed role. Use help to discover methods and parameters. All shared scientific and ownership gates apply.",
     "inputSchema": schema({"method": STRING, "kwargs": OBJECT}, ["method"])},
    {"name": "research_control", "description": "Project control: init, status, refresh, build, check, config, confirm, instruction, worker, agents, inbox, acknowledge, chat, ui_path, attach. Parameters depend on action; use help. Only RLD can control execution. User confirmations require their verbatim words.",
     "inputSchema": schema({"action": STRING, "params": OBJECT}, ["action"])},
    {"name": "post_to_ui", "description": "RLD posts a notice, reply (requires re), or confirm_request (requires registered docs) to the independent research UI. A request is not approval.",
     "inputSchema": schema({"type": {"enum": ["notice", "reply", "confirm_request"]}, "text": STRING,
                            "docs": {"type": "array", "items": STRING}, "re": STRING}, ["type", "text"])},
    {"name": "research_message", "description": "Send a validated short message to RLD, or resend an existing id unchanged. Delivery state is returned separately from durable recording.",
     "inputSchema": schema({"type": STRING, "text": STRING, "docs": {"type": "array", "items": STRING},
                            "about": {"type": "array", "items": STRING}, "re": STRING, "resend": STRING})},
    {"name": "requirement_draft", "description": "UI only: save a requirement draft with source user-message IDs; this does not submit it to RLD. Use a submit action in the UI's final response to submit.",
     "inputSchema": schema({"req": STRING, "title": STRING, "fields": OBJECT,
                            "messages": {"type": "array", "items": STRING},
                            "about": {"type": "array", "items": STRING}})},
]


def run_request(cwd: Path, actor: str, name: str, arguments: dict) -> dict:
    if name not in {tool["name"] for tool in TOOLS}:
        raise ValueError(f"unknown tool: {name}")
    if not isinstance(arguments, dict):
        raise ValueError("arguments must be an object")
    # Avoid accepting an actor selected by the model, including at the CLI boundary.
    allowed = next(t for t in TOOLS if t["name"] == name)["inputSchema"]
    if set(arguments) - set(allowed["properties"]):
        raise ValueError("unexpected tool argument")
    if set(allowed["required"]) - set(arguments):
        raise ValueError("missing required tool argument")
    arguments = dict(arguments)
    selected = arguments.pop("project", None)
    if selected is not None:
        if not isinstance(selected, str) or not Path(selected).is_absolute():
            raise ValueError("project must be an absolute directory")
        if actor != "rld/main" and Path(selected).resolve() != cwd.resolve():
            raise ValueError("child sessions cannot switch research projects")
        cwd = Path(selected).resolve()
    if cwd == ROOT:
        raise ValueError("supply project: the absolute user workspace, not the installed plugin directory")
    if name == "research_control" and arguments.get("action") == "init":
        if actor != "rld/main":
            raise ValueError("only RLD initializes a project")
        bootstrap(cwd, arguments.get("params", {}))
    python = cwd / ".venv/bin/python"
    if not python.is_file():
        raise ValueError(f"missing {python}; run research_control init first")
    result = subprocess.run([str(python), str(ROOT / "tools/codex_runtime.py"), "--project", str(cwd),
                             "--actor", actor], input=json.dumps({"tool": name, "arguments": arguments}),
                            text=True, capture_output=True, cwd=cwd,
                            # a cleanup deletes run outputs and may take a while on shared storage
                            timeout=1800 if arguments.get("method") == "run_cleanup" else 90)
    try:
        response = json.loads(result.stdout)
    except ValueError:
        raise RuntimeError(f"research runtime exited {result.returncode}: {result.stderr[-2000:]}") from None
    return response


def bootstrap(cwd: Path, params: dict) -> None:
    if (cwd / ".research-tree.json").exists():
        raise ValueError("this directory already contains a research project")
    plan = cwd / (params.get("plan") or "")
    if not plan.is_file():
        raise ValueError("init requires an existing plan file")
    commands = [["uv", "--version"]]
    if params.get("update_uv"):
        commands.append(["uv", "self", "update"])
    if not (cwd / "pyproject.toml").exists():
        commands.append(["uv", "init", ".", "--no-workspace", "--python", params.get("python", "3.13")])
    commands.append(["uv", "add", "--project", ".", "latticedb==0.15.0", "jsonschema>=4.26", "pyyaml>=6.0"])
    for command in commands:
        result = subprocess.run(command, cwd=cwd, capture_output=True, text=True, timeout=600)
        if result.returncode:
            raise RuntimeError(f"{command[0:2]} failed: {result.stderr[-2000:]}")


def serve(cwd: Path, actor: str) -> None:
    for line in sys.stdin:
        request = None
        try:
            request = json.loads(line)
            if not isinstance(request, dict) or request.get("jsonrpc") != "2.0":
                raise ValueError("expected a JSON-RPC 2.0 object")
            if "id" not in request:  # notifications must never receive a response
                continue
            method, params = request.get("method"), request.get("params", {})
            if not isinstance(params, dict):
                raise ValueError("params must be an object")
            if method == "initialize":
                result = {"protocolVersion": params.get("protocolVersion", "2024-11-05"),
                          "capabilities": {"tools": {}}, "serverInfo": {"name": "research-tree", "version": "0.1.0"},
                          "instructions": f"Research-tree actor: {actor}. Main session: supply the absolute project directory on every tool call. Use research_db help before guessing parameters. "
                          "Planning requires user confirmation before workers start. Research state lives in the database. "
                          "Use the research-tree skill for the complete workflow; inspect inbox for unacknowledged events."}
            elif method == "ping":
                result = {}
            elif method == "tools/list":
                result = {"tools": TOOLS}
            elif method == "tools/call":
                try:
                    result = run_request(cwd, actor, params["name"], params.get("arguments", {}))
                except (ValueError, OSError, RuntimeError, subprocess.TimeoutExpired) as exc:
                    result = {"ok": False, "error": str(exc)}
                result = {"content": [{"type": "text", "text": json.dumps(result, ensure_ascii=False)}],
                          "isError": not result.get("ok", False)}
            else:
                print(json.dumps({"jsonrpc": "2.0", "id": request["id"],
                                  "error": {"code": -32601, "message": f"unknown method: {method}"}}), flush=True)
                continue
            response = {"jsonrpc": "2.0", "id": request["id"], "result": result}
        except (ValueError, KeyError, TypeError) as exc:
            response = {"jsonrpc": "2.0", "id": request.get("id") if isinstance(request, dict) else None,
                        "error": {"code": -32700 if isinstance(exc, json.JSONDecodeError) else -32600,
                                  "message": str(exc)}}
        print(json.dumps(response, ensure_ascii=False), flush=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project", type=Path)
    parser.add_argument("--actor", default=os.environ.get("RESEARCH_TREE_ACTOR", "rld/main"))
    args = parser.parse_args()
    actor_key(args.actor)
    serve((args.project or project_dir(Path.cwd())).resolve(), args.actor)


if __name__ == "__main__":
    main()
