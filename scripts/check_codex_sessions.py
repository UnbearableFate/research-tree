#!/usr/bin/env python3
"""Exercise real Codex exec/resume against a local deterministic Responses fixture.

This checks CLI protocol/flags/session persistence, not model reasoning. It uses no
account credentials and makes no paid model calls. Use an isolated local fixture directory.
The fixture has no live Leader session: it covers the Architect queue, not notifications to the Leader.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import threading
import time
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path


class ResponsesFixture(BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass

    def do_POST(self):
        self.rfile.read(int(self.headers.get("Content-Length", 0)))
        if self.server.hold:
            self.server.entered.set()
            if not self.server.release.wait(45):
                self.send_error(504)
                return
        response_id, item_id = "resp_" + uuid.uuid4().hex, "msg_" + uuid.uuid4().hex
        text = self.server.reply
        item = {"id": item_id, "type": "message", "role": "assistant", "status": "completed",
                "content": [{"type": "output_text", "text": text, "annotations": []}]}
        response = {"id": response_id, "object": "response", "status": "completed", "output": [item],
                    "usage": {"input_tokens": 10, "output_tokens": 10, "total_tokens": 20}}
        events = [
            {"type": "response.created", "response": {**response, "status": "in_progress", "output": []}},
            {"type": "response.output_item.added", "output_index": 0, "item": {**item, "content": [], "status": "in_progress"}},
            {"type": "response.content_part.added", "item_id": item_id, "output_index": 0, "content_index": 0,
             "part": {"type": "output_text", "text": "", "annotations": []}},
            {"type": "response.output_text.delta", "item_id": item_id, "output_index": 0, "content_index": 0, "delta": text},
            {"type": "response.output_item.done", "output_index": 0, "item": item},
            {"type": "response.completed", "response": response},
        ]
        payload = "".join(f"event: {e['type']}\ndata: {json.dumps(e)}\n\n" for e in events).encode()
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)
        self.server.requests += 1


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("plugin", type=Path)
    parser.add_argument("--evidence", required=True, type=Path)
    args = parser.parse_args()
    plugin, evidence = args.plugin.resolve(), args.evidence.resolve()
    evidence.mkdir(parents=True, exist_ok=False)
    sys.path.insert(0, str(plugin / "tools"))
    import research_tree
    import project_config
    from codex_runtime import Runtime
    from metrics import minimal_documents
    from research_db import TASK_SECTIONS
    from codex_state import read_json, write_json, lock_busy

    server = ThreadingHTTPServer(("127.0.0.1", 0), ResponsesFixture)
    server.reply = "Fixture Architect response; no research task has been delivered."
    server.requests = 0
    server.hold = False
    server.entered = threading.Event()
    server.release = threading.Event()
    threading.Thread(target=server.serve_forever, daemon=True).start()
    test_home, project = evidence / "codex-home", evidence / "project"
    test_home.mkdir()
    project.mkdir()
    os.environ["CODEX_HOME"] = str(test_home)
    for key in ("OPENAI_API_KEY", "CODEX_API_KEY", "RESEARCH_TREE_PROJECT", "RESEARCH_TREE_ACTOR", "CODEX_THREAD_ID"):
        os.environ.pop(key, None)
    (test_home / "config.toml").write_text(f'''model_provider = "fixture"
model = "fixture-model"
[model_providers.fixture]
name = "Local deterministic fixture"
base_url = "http://127.0.0.1:{server.server_port}/v1"
wire_api = "responses"
requires_openai_auth = false
supports_websockets = false
''')
    (project / ".venv").symlink_to(Path(sys.prefix), target_is_directory=True)
    (project / "plan.md").write_text("# Fixture only\nNo experiments authorized.\n")
    # The local provider only replies with fixed text; it authorizes no research execution.
    fixture_documents = minimal_documents("acc", "higher", [])
    (project / "research-tree.yaml").write_text(json.dumps({
        "version": 3, "metric_specs": fixture_documents[0]["metrics"],
        "verification": {"screening_seeds": [1], "replication_seeds": [2, 3]}}))
    marker = research_tree.init(project, project / "plan.md", "P-cli")
    runtime = Runtime(project)
    db = runtime.db()

    def document(rel, kind):
        path = runtime.root / "docs" / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("# Fixture\n" + "".join(f"## {name}\n\n不适用\n" for name in TASK_SECTIONS.get(kind, ())))
        ident = db.register_document(rel, kind, kind)
        db.set_document_current(ident)
        return ident

    setup = document("project/min-setup.v1.md", "min_setup")
    conf = project_config.parse((project / "research-tree.yaml").read_text())
    protocol = fixture_documents[1]
    protocol.update(project_config.protocol_requirements(conf))
    (runtime.root / "docs/project/protocol.v1.json").write_text(json.dumps(protocol))
    protocol_id = db.register_document("project/protocol.v1.json", "protocol", "protocol")
    db.set_document_current(protocol_id)
    db.create_project("P-cli", "fixture", setup, "acc", "higher", [],
                      metric_spec_doc_id=marker["metric_spec"]["doc_id"], protocol_doc_id=protocol_id,
                      **project_config.db_fields(conf))
    document("project/reports/init-plan.v1.md", "report")
    task = db.create_task("harness", "architect", document("tasks/T-0001/request.v1.md", "task_request"), target_id="P-cli")
    runtime.post({"type": "confirm_request", "text": "Fixture confirmation", "docs": ["project/reports/init-plan.v1.md"]})
    runtime.confirm("Fixture; no experiment authority.")
    db.assign_architect()
    db.update_task(task, assignee_id="root")
    write_json(runtime.cache / "leader.json", {"model": "fixture-model"})

    def wait(run):
        deadline = time.monotonic() + 90
        while time.monotonic() < deadline:
            state = read_json(Path(run["directory"]) / "state.json")
            if state.get("status") in {"completed", "failed", "interrupted"} and not lock_busy(runtime.cache / "agents" / f"{run['actor'].replace('/', '-')}.lock"):
                if state["status"] != "completed":
                    raise AssertionError(f"native session failed: {state}; inspect {run['directory']}")
                return state
            time.sleep(0.1)
        raise TimeoutError(f"native session still running: {run}")

    try:
        server.hold = True
        started = runtime.control("architect", {"node_id": "P-cli", "task": "Fixture: return final text only, do not execute any tools."})
        if not server.entered.wait(30):
            raise AssertionError("native Architect did not reach the fixture provider")
        try:
            # The provider request and the supervisor's thread.started handling run concurrently.
            # Wait for the durable binding while the provider is held, before requesting a live follow-up.
            deadline = time.monotonic() + 10
            while not read_json(Path(started["directory"]) / "state.json").get("thread_id"):
                if time.monotonic() >= deadline:
                    raise AssertionError("native Architect did not persist its thread identity")
                time.sleep(0.05)
            followup = runtime.control("architect", {"node_id": "P-cli", "task": "Fixture queued continuation; no tools."})
            write_json(evidence / "followup.json", followup)
            if followup.get("delivery") != "queued":
                raise AssertionError(f"native live-Architect queue failed: {followup}")
        finally:
            server.hold = False
            server.release.set()
        first = wait(started)
        second = wait(runtime.control("architect", {"node_id": "P-cli", "task": "Fixture: acknowledge this continuation without executing tools."}))
        if first["thread_id"] != second["thread_id"]:
            raise AssertionError("Codex resume changed the Architect thread")
        server.reply = json.dumps({"reply": "Fixture UI response.", "actions": []})
        ui = wait(runtime.start_ui("Fixture UI question; no action requested."))
        result = {"ok": True, "architect_thread": first["thread_id"], "resumed_thread": second["thread_id"],
                  "ui_thread": ui["thread_id"], "local_responses": server.requests,
                  "live_followup": followup["delivery"],
                  "task_status": db.get(task)["status"]}
        if result["task_status"] != "open":
            raise AssertionError("ending a Architect turn incorrectly delivered its task")
        write_json(evidence / "result.json", result)
        print(json.dumps(result, indent=2))
    finally:
        server.shutdown()
        server.server_close()


if __name__ == "__main__":
    main()
