#!/usr/bin/env python3
"""Test an unpacked Codex marketplace via the installed CLI/app-server, without model inference.

Creates an isolated CODEX_HOME and project, installs the plugin, discovers its skill,
connects its MCP server, and executes a real tool call. No credentials are copied.
"""
from __future__ import annotations

import argparse
import json
import os
import queue
import subprocess
import tempfile
import threading
import time
from pathlib import Path


class Client:
    def __init__(self, cwd, env, log):
        self.process = subprocess.Popen(["codex", "app-server", "--stdio"], cwd=cwd, env=env,
                                        stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=log, text=True)
        self.messages = queue.Queue()
        self.sequence = 0
        self.events = []

        def read():
            for line in self.process.stdout:
                self.messages.put(json.loads(line))
            self.messages.put(None)

        threading.Thread(target=read, daemon=True).start()

    def request(self, method, params, timeout=45):
        self.sequence += 1
        ident = self.sequence
        self.process.stdin.write(json.dumps({"id": ident, "method": method, "params": params}) + "\n")
        self.process.stdin.flush()
        deadline = time.monotonic() + timeout
        while True:
            message = self.messages.get(timeout=max(0.01, deadline - time.monotonic()))
            if message is None:
                raise RuntimeError("app-server exited before replying")
            if message.get("id") == ident and ("result" in message or "error" in message):
                if "error" in message:
                    raise RuntimeError(f"{method}: {message['error']}")
                return message["result"]
            self.events.append(message)
            if "id" in message and "method" in message:
                raise RuntimeError(f"unexpected interactive server request: {message['method']}")

    def close(self):
        self.process.stdin.close()
        try:
            self.process.wait(timeout=10)
        except subprocess.TimeoutExpired:
            self.process.terminate()
            self.process.wait(timeout=10)


def check(marketplace: Path, work: Path):
    home, project = work / "codex-home", work / "project"
    home.mkdir()
    project.mkdir()
    env = {**os.environ, "CODEX_HOME": str(home)}
    # Do not inherit the executing agent's provider credentials or role overrides.
    for name in ("OPENAI_API_KEY", "CODEX_API_KEY", "RESEARCH_TREE_PROJECT", "RESEARCH_TREE_ACTOR"):
        env.pop(name, None)
    for command in (["codex", "plugin", "marketplace", "add", str(marketplace)],
                    ["codex", "plugin", "add", "research-tree@research-tree", "--json"]):
        result = subprocess.run(command, env=env, cwd=project, capture_output=True, text=True, timeout=45)
        if result.returncode:
            raise RuntimeError(result.stderr + result.stdout)
    (project / "plan.md").write_text("# Standalone Codex install smoke\nNo experiments authorized.\n")
    with (work / "app-server.log").open("w") as log:
        client = Client(project, env, log)
        try:
            client.request("initialize", {"clientInfo": {"name": "research-tree-validation", "version": "0.1.0"},
                                          "capabilities": {"experimentalApi": True}})
            skills = client.request("skills/list", {"cwds": [str(project)], "forceReload": True})
            (work / "skills.json").write_text(json.dumps(skills, indent=2))
            if "research-tree" not in json.dumps(skills):
                raise AssertionError("installed research-tree skill not discovered")
            thread = client.request("thread/start", {"cwd": str(project), "approvalPolicy": "never",
                                                      "sandbox": "workspace-write"})
            thread_id = thread["thread"]["id"]
            servers = client.request("mcpServerStatus/list", {"threadId": thread_id})
            (work / "mcp.json").write_text(json.dumps(servers, indent=2))
            entries = [s for s in servers["data"] if "research_tree" in s["name"]]
            if len(entries) != 1:
                raise AssertionError(f"expected one installed server, got {servers}")
            server = entries[0]
            if len(server.get("tools", {})) != 5:
                raise AssertionError(f"MCP discovery failed: {server}")
            result = client.request("mcpServer/tool/call", {"threadId": thread_id, "server": server["name"],
                                                             "tool": "research_control", "arguments": {"action": "status", "project": str(project)}})
            (work / "tool-call.json").write_text(json.dumps(result, indent=2))
            # Before init, the real tool should give its own actionable environment error.
            if "missing" not in json.dumps(result) or ".venv" not in json.dumps(result):
                raise AssertionError(f"unexpected pre-init tool result: {result}")

            def call(tool, **arguments):
                result = client.request("mcpServer/tool/call", {"threadId": thread_id, "server": server["name"],
                                                                "tool": tool, "arguments": {"project": str(project), **arguments}}, timeout=180)
                body = json.loads(result["content"][0]["text"])
                if result.get("isError") or not body["ok"]:
                    raise AssertionError(f"{tool}: {body}")
                return body["result"]

            # prepare, as the skill runs it: the shared shell helper builds the uv environment (the plan stays).
            prepared = subprocess.run(["sh", str(marketplace / "plugins/research-tree/tools/prepare.sh"), str(project)],
                                      env=env, capture_output=True, text=True, timeout=900)
            (work / "prepare.log").write_text(prepared.stdout + prepared.stderr)
            if prepared.returncode:
                raise RuntimeError(prepared.stderr + prepared.stdout)
            initialized = call("research_control", action="init", params={"project_id": "P-native"})
            root = Path(initialized["project"]["root"])

            def doc(rel, kind):
                (root / "docs" / rel).write_text(f"# {kind}\nNative CLI fixture; no experiments.\n")
                ident = call("research_db", method="register_document", kwargs={"path": rel, "doc_type": kind, "title": kind})
                call("research_db", method="set_document_current", kwargs={"doc_id": ident})
                return ident

            setup = doc("project/min-setup.v1.md", "min_setup")
            call("research_db", method="create_project", kwargs={"id": "P-native", "title": "Native installation smoke",
                  "min_setup_doc_id": setup, "primary_metric": "accuracy", "metric_direction": "higher",
                  "metric_is_percent": True, "secondary_metrics": [], "seeds": [1, 2, 3]})
            doc("project/reports/init-plan.v1.md", "report")
            call("post_to_ui", type="confirm_request", text="Fixture plan; confirm only for validation.", docs=["project/reports/init-plan.v1.md"])
            confirmed = call("research_control", action="confirm", params={"words": "Fixture confirmation; no experiments authorized."})
            # No attach in this fixture: confirmation remains durable but no model is woken.
            if confirmed["delivery"]["delivery"] != "pending":
                raise AssertionError("native no-inference fixture unexpectedly addressed a model session")
            page = call("research_control", action="build")
            version = call("research_control", action="check")
            if version["stale"] or not Path(page["path"]).is_file():
                raise AssertionError("native progress page was not built from current data")
            (work / "workflow.json").write_text(json.dumps({"project": initialized["project"], "confirmation": confirmed,
                                                           "page": page, "version": version}, indent=2))
            print(json.dumps({"ok": True, "thread": thread_id, "server": server["name"], "tools": len(server["tools"]),
                              "workflow": "init -> documents -> project -> confirmation -> progress page",
                              "evidence": str(work)}, indent=2))
        finally:
            client.close()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("marketplace", type=Path)
    parser.add_argument("--evidence", type=Path)
    args = parser.parse_args()
    if args.evidence:
        args.evidence.mkdir(parents=True, exist_ok=False)
        check(args.marketplace.resolve(), args.evidence.resolve())
    else:
        with tempfile.TemporaryDirectory(prefix="research-codex-install-") as temp:
            check(args.marketplace.resolve(), Path(temp))


if __name__ == "__main__":
    main()
