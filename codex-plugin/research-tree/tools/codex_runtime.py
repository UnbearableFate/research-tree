"""Codex lifecycle adapter over the shared research API. Run with the project's .venv."""
from __future__ import annotations

import argparse
import fcntl
import json
import os
import socket
import subprocess
import sys
import threading
import uuid
from pathlib import Path

from jsonschema import Draft202012Validator

import build_site
import codex_prompts
import notify
import research_tree as tree
import review_call
import send_message as messaging
from codex_state import actor_key, cache_dir, lock_busy, locked, read_json, write_json
from research_db import CLI_METHODS, READ_METHODS, ResearchDB, busy_workers, describe, now_utc

ROOT = Path(__file__).resolve().parents[1]
READS = set(READ_METHODS)
HELP = {
    "init": {"plan": "plan.md (default)", "project_id": "optional", "config": "optional YAML other than research-tree.yaml"},
    "status": {}, "refresh": {}, "build": {}, "pane": {}, "check": {},
    "config": {"apply": False, "words": "user's request when applying"},
    "confirm": {"words": "verbatim user confirmation"},
    "instruction": {"words": "verbatim user instruction from the main conversation",
                    "understanding": "interpretation and scope", "kind": "指令", "about": ["project or node ID"]},
    "worker": {"node_id": "assigned project or H-id", "task": "this turn's task",
               "restart": "false; true starts a new session only when previous run is no longer active"},
    "agents": {}, "inbox": {}, "acknowledge": {"ids": ["event-id"]},
    "chat": {}, "ui_path": {}, "attach": {"session_id": "main Codex session UUID", "model": "current model"},
}


class Runtime:
    def __init__(self, cwd: Path, actor="rld/main"):
        self.cwd = cwd.resolve()
        actor_key(actor)
        self.actor = actor

    @property
    def marker(self):
        return tree.read_marker(self.cwd)

    @property
    def root(self):
        return Path(self.marker["root"])

    @property
    def cache(self):
        return cache_dir(self.cwd)

    def db(self, actor=None):
        return ResearchDB(Path(self.marker["db"]), actor or self.actor)

    def require_rld(self):
        if self.actor != "rld/main":
            raise ValueError("only RLD may control research execution")

    def summary(self):
        with locked(self.cache / "summary.lock"):
            return self._summary()

    def _summary(self):
        result = build_site.summary_or_empty(Path(self.marker["db"]))
        write_json(self.cache / "summary.json", result)
        threshold = result.get("project") and result["project"].get("alert_node_h")
        alert = next((a for a in result["attention"] if a["kind"] == "usage_alert"), None)
        previous = read_json(self.cache / "alert.json")
        if alert and previous != threshold:
            self.say("note", alert["text"])
            notify.send(self.root, tree.show_config(self.cwd)["effective"], "alert", alert["text"])
            write_json(self.cache / "alert.json", threshold)
        elif not alert and previous is not None:
            write_json(self.cache / "alert.json", None)
        return result

    def say(self, role, text):
        with locked(self.cache / "chat.lock"):
            log = self.root / "messages/window.jsonl"
            entry = {"id": f"w-{uuid.uuid4().hex}", "role": role, "text": text, "ts": now_utc()}
            with log.open("a", encoding="utf-8") as stream:
                stream.write(json.dumps(entry, ensure_ascii=False) + "\n")
                stream.flush()
                os.fsync(stream.fileno())
        return entry

    def chat(self):
        return list(tree.window_messages(self.root).values())

    def enqueue(self, text, event_id=None, retry=False):
        """Durably queue before notifying Codex. A timeout is ambiguous and is never retried automatically."""
        event_id = event_id or f"event-{uuid.uuid4().hex}"
        file = self.cache / "inbox.json"
        leader = read_json(self.cache / "leader.json", {})
        with locked(self.cache / "inbox.lock"):
            inbox = read_json(file, [])
            prior = next((x for x in inbox if x["id"] == event_id), None)
            if prior:
                if not retry or prior["acknowledged"] or prior["delivery"] == "queued":
                    return prior
                if prior["delivery"] not in {"pending", "failed"}:
                    raise ValueError("previous delivery is ambiguous; inspect the destination before any retry")
                entry = prior
                entry.pop("error", None)
            else:
                entry = {"id": event_id, "text": text, "created_at": now_utc(), "delivery": "pending", "acknowledged": False}
                inbox.append(entry)
            if leader.get("session_id"):
                entry.update(delivery="sending", session_id=leader["session_id"])
            write_json(file, inbox)
        if leader.get("session_id"):
            try:
                sent = subprocess.run(["codex", "queue", "--thread", leader["session_id"], "--message",
                                       f"[research-tree {event_id}] {text}\n读取相关文档后处理，并用 research_control acknowledge 确认收到该事件。"],
                                      capture_output=True, text=True, cwd=self.cwd, timeout=20)
                entry["delivery"] = "queued" if sent.returncode == 0 else "failed"
                if sent.returncode:
                    entry["error"] = sent.stderr[-1500:]
            except subprocess.TimeoutExpired:
                entry.update(delivery="unknown", error="queue timed out; inspect destination before resending")
            except OSError as exc:
                entry.update(delivery="failed", error=str(exc))
        with locked(self.cache / "inbox.lock"):
            inbox = read_json(file, [])
            for item in inbox:
                if item["id"] == event_id:
                    item.update({k: v for k, v in entry.items() if k != "acknowledged"})
            write_json(file, inbox)
        return entry

    def log_message(self, sender, recipient, kind, text, docs=None, about=None, re=None, need=None):
        message = {"ts": now_utc(), "project": None, "from": sender, "to": recipient,
                   "type": kind, "text": text, "need": need or messaging.DEFAULT_NEED[kind]}
        for key, value in (("docs", docs), ("about", about), ("re", re)):
            if value:
                message[key] = value
        validator = Draft202012Validator(read_json(ROOT / "schema/message.schema.json"))
        validator.validate({"v": 1, "id": f"{messaging.agent_id(sender)}-0001", **message, "project": "P-placeholder"})
        registry = messaging.load_registry(self.root)
        if recipient not in registry or (sender not in registry and not sender.startswith("worker/")):
            raise ValueError("unregistered message participant")
        message["project"] = messaging.check_references(self.root, message)
        return json.loads(messaging.append_message(self.root, message, validator))

    def relay(self, kind, text, docs=None, about=None, need=None):
        message = self.log_message("ui/ui", "rld/main", kind, text[:200], docs, about, need=need)
        return {"message": message, "delivery": self.enqueue(json.dumps(message, ensure_ascii=False), message["id"])}

    def post(self, args):
        self.require_rld()
        kind = args["type"]
        if kind not in {"notice", "reply", "confirm_request"}:
            raise ValueError("invalid UI message type")
        text = args["text"]
        if not isinstance(text, str) or not 1 <= len(text) <= 200:
            raise ValueError("text must contain 1..200 characters")
        if kind == "confirm_request" and self.marker["phase"] == "planning":
            blocked = tree.discovery_blocks_confirmation(self.cwd)  # 02 D8: the discovery gate first
            if blocked:
                raise ValueError(blocked)
        if kind != "notice":
            message = self.log_message(self.actor, "ui/ui", kind, text, args.get("docs"), re=args.get("re"))
        else:
            message = None
        if kind == "confirm_request" and self.marker["phase"] == "planning":
            tree.set_phase(self.cwd, "awaiting_confirmation")
        if kind == "confirm_request":  # optional webhook: the user may be away; no answer is no consent
            notify.send(self.root, tree.show_config(self.cwd)["effective"], "confirm_request", text, args.get("docs"))
        entry = self.say("rld", text + ("\n引用：" + ", ".join(args["docs"]) if args.get("docs") else ""))
        return {"message": message, "chat": entry, "phase": self.marker["phase"]}

    def confirm(self, words):
        self.require_rld()
        if not isinstance(words, str) or not words.strip():
            raise ValueError("confirmation needs the user's verbatim words")
        with locked(self.cache / "control.lock"):
            marker = self.marker
            if marker["phase"] == "confirmed":
                return {"already_confirmed": True}
            if marker["phase"] != "awaiting_confirmation":
                raise ValueError("RLD has not submitted a plan for confirmation")
            tree.apply_config(self.cwd, "rld/main", require_project=True)
            document = tree.register_instruction(self.root, words, "用户确认立项计划，允许worker实现根节点。",
                                                 "确认（立项计划）", [marker["project_id"]])
            tree.set_phase(self.cwd, "confirmed")
        self.say("note", f"立项确认已登记：{document['doc_id']}。")
        # The RLD answers a confirmation by starting the root's worker, not with a receipt.
        result = self.relay("instruction", "用户确认立项计划，请指派根节点worker并实现框架与baselines。",
                            [document["path"]], [marker["project_id"]], need="none")
        return {"document": document, **result}

    def start_agent(self, actor, prompt, model, *, node_id=None, resume=None, user_message=None, workdir=None):
        """Transfer an exclusive per-identity lock to the supervisor and Codex child."""
        key = actor_key(actor)
        agent_lock = self.cache / "agents" / f"{key}.lock"
        agent_lock.parent.mkdir(parents=True, exist_ok=True)
        handle = agent_lock.open("a")
        try:
            fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            handle.close()
            raise ValueError(f"{actor} already has a live turn; wait for its completion") from None
        try:
            run = uuid.uuid4().hex
            directory = self.cache / "runs" / run
            directory.mkdir(parents=True)
            spec = {"run": run, "actor": actor, "project": str(self.cwd), "node_id": node_id,
                    "prompt": prompt, "model": model, "resume": resume, "user_message": user_message,
                    "workdir": str(workdir or self.cwd)}
            write_json(directory / "spec.json", spec)
            write_json(directory / "state.json", {"run": run, "actor": actor, "status": "starting", "created_at": now_utc()})
            with (directory / "supervisor.log").open("a") as log:
                process = subprocess.Popen([sys.executable, str(ROOT / "tools/codex_agent.py"), str(directory), str(handle.fileno())],
                                           cwd=self.cwd, stdin=subprocess.DEVNULL, stdout=log, stderr=log,
                                           start_new_session=True, pass_fds=(handle.fileno(),))
            threading.Thread(target=process.wait, daemon=True).start()
            write_json(self.cache / "agents" / f"{key}.json", {"run": run, "actor": actor, "directory": str(directory),
                                                                "supervisor_pid": process.pid, "host": socket.gethostname()})
            return {"run": run, "actor": actor, "status": "starting", "directory": str(directory)}
        finally:
            handle.close()  # the child holds the same open file description and lock

    def start_worker(self, node_id, task, restart=False):
        self.require_rld()
        if self.marker["phase"] != "confirmed":
            raise ValueError("plan must be confirmed by the user before a worker starts")
        if not isinstance(task, str) or not task.strip():
            raise ValueError("worker needs a concrete task")
        with locked(self.cache / "control.lock"):
            package = self.db().resume_package(node_id)
            if not package["worker"]:
                raise ValueError("assign_worker before starting the node's session")
            agent = read_json(self.cache / "agents" / f"{actor_key(package['worker'])}.json", {})
            if lock_busy(self.cache / "agents" / f"{actor_key(package['worker'])}.lock"):
                if restart:
                    raise ValueError("cannot replace a live worker")
                state = read_json(Path(agent["directory"]) / "state.json", {}) if agent else {}
                if not state.get("thread_id"):
                    raise ValueError("worker is starting; its thread ID is not available yet")
                return self.queue_worker(state["thread_id"], package["worker"], task)
            worker_id = package["worker"].split("/", 1)[1]
            tasks = self.db().find("task")
            busy = busy_workers(tasks)
            project = self.db().find("project")[0]
            limit = project.get("max_parallel_workers")
            if limit is not None and worker_id not in busy and len(busy) >= limit:
                raise ValueError(f"max_parallel_workers={limit} reached")
            if not any(t.get("assignee_id") == worker_id and t["status"] in {"open", "in_progress", "rejected"}
                       for t in package["tasks"]):
                raise ValueError("assign an actionable node task to this worker before starting it")
            conf = tree.show_config(self.cwd)["effective"]
            workdir = (package.get("branch") or {}).get("worktree_path") or package["node"].get("repo_path") or self.cwd
            if not Path(workdir).is_dir():
                raise ValueError(f"assigned worker checkout does not exist: {workdir}")
            return self.start_agent(package["worker"], codex_prompts.worker(self.marker, package, conf, task),
                                    conf["models"]["worker"], node_id=node_id,
                                    resume=None if restart else package.get("agent_id"), workdir=workdir)

    def queue_worker(self, thread_id, actor, text):
        receipt = {"id": uuid.uuid4().hex, "actor": actor, "thread_id": thread_id, "text": text,
                   "at": now_utc(), "delivery": "pending"}
        path = self.cache / "followups" / f"{receipt['id']}.json"
        write_json(path, receipt)
        try:
            sent = subprocess.run(["codex", "queue", "--thread", thread_id, "--message", text],
                                  cwd=self.cwd, capture_output=True, text=True, timeout=20)
            receipt["delivery"] = "queued" if sent.returncode == 0 else "failed"
            if sent.returncode:
                receipt["error"] = sent.stderr[-1500:]
        except subprocess.TimeoutExpired:
            receipt.update(delivery="unknown", error="queue timed out; inspect the worker before resending")
        except OSError as exc:
            receipt.update(delivery="failed", error=str(exc))
        write_json(path, receipt)
        return receipt

    def start_ui(self, text):
        # This is called by the human-facing CLI, never exposed as an RLD MCP action.
        self.require_rld()
        if not text.strip():
            raise ValueError("empty user message")
        with locked(self.cache / "control.lock"):
            if lock_busy(self.cache / "agents/ui-ui.lock"):
                raise ValueError("UI is still processing the previous message")
            entry = self.say("user", text)
            conf = tree.show_config(self.cwd)["effective"]
            prompt = codex_prompts.ui(self.marker, conf, self.summary(), entry, self.chat()[-30:],
                                     tree.list_requirements(self.cwd))
            return self.start_agent("ui/ui", prompt, conf["models"]["ui"], user_message=entry)

    def apply_ui(self, directory, response):
        """One-shot actions. An interrupted applying action stays explicit; never blind-replayed."""
        self.require_rld()
        Draft202012Validator(read_json(ROOT / "schema/ui-response.schema.json")).validate(response)
        spec = read_json(directory / "spec.json")
        if spec["actor"] != "ui/ui":
            raise ValueError("not a UI run")
        journal = directory / "actions.json"
        if journal.exists():
            raise ValueError("UI actions already attempted; inspect the journal before recovery")
        actions = [{"action": action, "status": "pending"} for action in response["actions"]]
        write_json(journal, actions)
        self.say("ui", response["reply"])
        for item in actions:
            action = item["action"]
            item["status"] = "applying"
            write_json(journal, actions)
            try:
                kind = action["type"]
                if kind == "confirm":
                    result = self.confirm(spec["user_message"]["text"])
                elif kind == "instruction":
                    with locked(self.cache / "control.lock"):
                        document = tree.register_instruction(self.root, spec["user_message"]["text"], action["text"],
                                                             "指令", action["about"])
                    result = self.relay("instruction", action["text"], [document["path"]], action["about"])
                elif kind == "submit":
                    with locked(self.cache / "control.lock"):
                        document = tree.submit_requirement(self.cwd, action["req"])
                    result = self.relay("instruction", f"需求 {document['req']} v{document['version']}：{document['title']}",
                                        [document["path"]])
                else:
                    result = self.relay("question", action["text"], action["docs"], action["about"])
                item.update(status="completed", result=result)
            except Exception as exc:
                item.update(status="failed", error=str(exc))
                self.say("note", f"UI动作未完成：{kind}：{exc}")
            write_json(journal, actions)
        return actions

    def agents(self):
        result = []
        for path in sorted((self.cache / "agents").glob("*.json")):
            entry = read_json(path)
            state = read_json(Path(entry["directory"]) / "state.json", {})
            live = lock_busy(path.with_suffix(".lock"))
            result.append({**entry, **state, "live": live,
                           "observation": "lock-held" if live else "no live owner",
                           "status": state.get("status") if live or state.get("status") in {"completed", "failed", "interrupted"}
                           else "interrupted"})
        return result

    def control(self, action, params):
        if action == "help":
            return HELP
        if action == "init":
            self.require_rld()
            marker = tree.init(self.cwd, self.cwd / (params.get("plan") or "plan.md"), params.get("project_id"),
                               self.cwd / params["config"] if params.get("config") else None)
            self.summary()
            return {"project": marker, "next": codex_prompts.planning(marker, tree.show_config(self.cwd)["effective"])}
        if action in {"status", "refresh"}:
            return {"project": self.marker, "summary": self.summary(), "agents": self.agents()}
        if action == "chat":
            return self.chat()
        if action == "ui_path":
            return {"command": [str(self.cwd / ".venv/bin/python"), str(ROOT / "tools/codex_cli.py"),
                                "--project", str(self.cwd), "ui"]}
        if action == "config" and not params.get("apply"):
            return tree.show_config(self.cwd)
        if action == "check":
            summary = self.summary()
            page = self.root / "site/index.html"
            return {"page_version": build_site.page_version(page), "db_version": summary["meta"]["data_version"],
                    "stale": build_site.page_version(page) != summary["meta"]["data_version"]}
        self.require_rld()
        if action == "confirm":
            return self.confirm(params.get("words"))
        if action == "instruction":
            words, understanding = params.get("words"), params.get("understanding")
            if not isinstance(words, str) or not words.strip() or not isinstance(understanding, str) or not understanding.strip():
                raise ValueError("instruction needs the user's verbatim words and their interpretation")
            with locked(self.cache / "control.lock"):
                return tree.register_instruction(self.root, words, understanding, params.get("kind", "指令"),
                                                 params.get("about", []))
        if action == "config":
            if not params.get("words", "").strip():
                raise ValueError("config apply needs the user's request")
            with locked(self.cache / "control.lock"):
                result = tree.apply_config(self.cwd, self.actor, words=params["words"])
            if result["new_version"] or result["updated_fields"]:
                result["delivery"] = self.enqueue("用户已应用新配置。读取 research_control config；向活跃worker转告平台和预算变化。")
            return result
        if action in {"build", "pane"}:
            with locked(self.cache / "build.lock"):
                page = self.root / "site/index.html"
                data = build_site.build(Path(self.marker["db"]), page)
            return {"path": str(page), "data_version": data["meta"]["data_version"]}
        if action == "worker":
            return self.start_worker(**params)
        if action == "agents":
            return self.agents()
        if action == "attach":
            session = str(uuid.UUID(params["session_id"]))
            write_json(self.cache / "leader.json", {"session_id": session, "model": params.get("model"), "at": now_utc()})
            return {"session_id": session}
        if action in {"inbox", "acknowledge"}:
            with locked(self.cache / "inbox.lock"):
                inbox = read_json(self.cache / "inbox.json", [])
                if action == "acknowledge":
                    ids = params.get("ids", [])
                    if set(ids) - {x["id"] for x in inbox}:
                        raise ValueError("unknown inbox event")
                    for entry in inbox:
                        if entry["id"] in ids:
                            entry["acknowledged"] = True
                    write_json(self.cache / "inbox.json", inbox)
                return [x for x in inbox if not x["acknowledged"]]
        raise ValueError(f"unknown control action {action}; use help")

    def dispatch(self, name, args):
        if name == "research_db":
            method, kwargs = args["method"], args.get("kwargs", {})
            if method == "help":
                return describe(**kwargs)
            if method not in CLI_METHODS:
                raise ValueError("unknown research_db method; use help")
            if self.actor == "ui/ui" and method not in READS:
                raise ValueError("UI may only read scientific records")
            if self.actor.startswith("worker/") and self.marker["phase"] != "confirmed":
                raise ValueError("worker access requires a confirmed plan")
            result = getattr(self.db(), method)(**kwargs)
            if method not in READS:
                self.summary()
            return result
        if name == "research_control":
            return self.control(args["action"], args.get("params", {}))
        if name == "research_review":
            if self.actor != "rld/main":
                raise ValueError("only the Leader organizes reviews")
            entry = {"kind": args["kind"], "about": args["about"], "dimension": args.get("dimension"),
                     "session": args.get("session")}
            try:
                result = review_call.review(self.cwd, args["kind"], args["brief"], args["about"], args.get("dimension"),
                                            args.get("evaluation"), args.get("session"), args.get("add_dirs") or [],
                                            self.actor, args.get("code_ref"))
            except review_call.ReviewError as exc:
                review_call.record_failure(self.root, entry, exc)
                self.summary()
                raise ValueError(str(exc)) from None
            review_call.log_call(self.root, {**entry, "outcome": "ok", "review_id": result["review_id"],
                                             "session": result["session"], "backend": result["backend"],
                                             "model": result["model_observed"], "cost_usd": result["cost_usd"]})
            self.summary()
            return result
        if name == "post_to_ui":
            return self.post(args)
        if name == "requirement_draft":
            if self.actor != "ui/ui":
                raise ValueError("only UI drafts requirements")
            fields = args.get("fields", {})
            if set(fields) - set(tree.REQ_FIELDS):
                raise ValueError("unknown requirement field")
            with locked(self.cache / "control.lock"):
                return tree.draft_requirement(self.cwd, args.get("req"), args.get("title"), fields,
                                              args.get("messages", []), args.get("about", []))
        if name == "research_message":
            if self.actor == "ui/ui":
                raise ValueError("UI sends actions through its response, not directly")
            if args.get("resend"):
                mid = args["resend"]
                if not messaging.MESSAGE_ID_RE.fullmatch(mid):
                    raise ValueError("invalid message id")
                original = messaging.logged_message(self.root, mid)
                if not original:
                    raise ValueError("message not found")
                message = json.loads(original)
                if message["from"] != self.actor or message["to"] != "rld/main":
                    raise ValueError("can only resend this actor's messages to RLD")
            else:
                message = self.log_message(self.actor, "rld/main", args["type"], args["text"],
                                           args.get("docs"), args.get("about"), args.get("re"))
            return {"message": message, "delivery": self.enqueue(json.dumps(message, ensure_ascii=False), message["id"], retry=bool(args.get("resend")))}
        raise ValueError(f"unknown tool {name}")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project", required=True, type=Path)
    parser.add_argument("--actor", default="rld/main")
    args = parser.parse_args()
    try:
        request = json.load(sys.stdin)
        result = Runtime(args.project, args.actor).dispatch(request["tool"], request.get("arguments", {}))
        print(json.dumps({"ok": True, "result": result}, ensure_ascii=False))
    except Exception as exc:
        print(json.dumps({"ok": False, "error": f"{type(exc).__name__}: {exc}"}, ensure_ascii=False))
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
