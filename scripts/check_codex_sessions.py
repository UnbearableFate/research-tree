#!/usr/bin/env python3
"""Exercise real Codex exec/resume against a local deterministic Responses fixture.

This checks CLI protocol/flags/session persistence, not model reasoning. It uses no
account credentials and makes no paid model calls. Run on a compute node on Miyabi.
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
    from codex_runtime import Runtime
    from codex_state import read_json, write_json, lock_busy

    server = ThreadingHTTPServer(("127.0.0.1", 0), ResponsesFixture)
    server.reply = "Fixture worker response; no research task has been delivered."
    server.requests = 0
    server.hold = False
    server.entered = threading.Event()
    server.release = threading.Event()
    threading.Thread(target=server.serve_forever, daemon=True).start()
    home, project = evidence / "codex-home", evidence / "project"
    home.mkdir()
    project.mkdir()
    os.environ["CODEX_HOME"] = str(home)
    for key in ("OPENAI_API_KEY", "CODEX_API_KEY", "RESEARCH_TREE_PROJECT", "RESEARCH_TREE_ACTOR", "CODEX_THREAD_ID"):
        os.environ.pop(key, None)
    (home / "config.toml").write_text(f'''model_provider = "fixture"
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
    research_tree.init(project, project / "plan.md", "P-cli")
    runtime = Runtime(project)
    db = runtime.db()

    def document(rel, kind):
        path = runtime.root / "docs" / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("# Fixture\n")
        ident = db.register_document(rel, kind, kind)
        db.set_document_current(ident)
        return ident

    setup = document("project/min-setup.v1.md", "min_setup")
    db.create_project("P-cli", "fixture", setup, "acc", "higher", True, [], [1, 2, 3])
    document("project/reports/init-plan.v1.md", "report")
    task = db.create_task("harness", "worker", document("tasks/T-0001/request.v1.md", "task_request"), target_id="P-cli")
    runtime.post({"type": "confirm_request", "text": "Fixture confirmation", "docs": ["project/reports/init-plan.v1.md"]})
    runtime.confirm("Fixture; no experiment authority.")
    db.assign_worker("P-cli")
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
        started = runtime.start_worker("P-cli", "Fixture: return final text only, do not execute any tools.")
        if not server.entered.wait(30):
            raise AssertionError("native worker did not reach the fixture provider")
        try:
            followup = runtime.start_worker("P-cli", "Fixture queued continuation; no tools.")
            write_json(evidence / "followup.json", followup)
            if followup.get("delivery") != "queued":
                raise AssertionError(f"native live-worker queue failed: {followup}")
        finally:
            server.hold = False
            server.release.set()
        first = wait(started)
        second = wait(runtime.start_worker("P-cli", "Fixture: acknowledge this continuation without executing tools."))
        if first["thread_id"] != second["thread_id"]:
            raise AssertionError("Codex resume changed the worker thread")
        server.reply = json.dumps({"reply": "Fixture UI response.", "actions": []})
        ui = wait(runtime.start_ui("Fixture UI question; no action requested."))
        result = {"ok": True, "worker_thread": first["thread_id"], "resumed_thread": second["thread_id"],
                  "ui_thread": ui["thread_id"], "local_responses": server.requests,
                  "live_followup": followup["delivery"],
                  "task_status": db.get(task)["status"]}
        if result["task_status"] != "open":
            raise AssertionError("ending a worker turn incorrectly delivered its task")
        write_json(evidence / "result.json", result)
        print(json.dumps(result, indent=2))
    finally:
        server.shutdown()
        server.server_close()


if __name__ == "__main__":
    main()
