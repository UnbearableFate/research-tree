"""Validate, log and send one agent-to-agent message.

A research root (research/<project-id>/) holds research_tree.db, docs/,
messages/ and agents.json. This tool:

  1. builds the message (id, timestamp and project are filled in),
  2. validates it against schema/message.schema.json and the 1000-byte limit,
  3. checks the references: the project and every `about` id exist in the
     database, every `docs` path is registered, not superseded and present on
     disk, and `re` names a logged message,
  4. appends the exact line to messages/<sender-id>.jsonl,
  5. delivers it through the recipient's channel from agents.json and appends
     the outcome to messages/<sender-id>.delivery.jsonl.

Channels:
  native       print only; the sending agent passes the printed line to its
               Codex send_message_to_thread tool (thread id from agents.json)
  codex-queue  `codex queue --thread <thread> --message <line>`
  herdr        `herdr agent prompt <herdr_agent> <line>`

A delivery failure exits non-zero and leaves the message logged; after
checking the recipient, resend the same message with --resend <id> rather than
composing a new one.

agents.json maps "<role>/<agent-id>" to
  {"channel": "native" | "codex-queue" | "herdr",
   "thread": "<codex thread id>", "herdr_agent": "<name>", "remote": "<app-server addr>"}
"""

from __future__ import annotations

import argparse
import fcntl
import json
import os
import re
import subprocess
import sys
import time
from pathlib import Path

from jsonschema import Draft202012Validator
from research_db import ResearchDB, ResearchDBError, now_utc, table_of

SCHEMA_PATH = Path(__file__).resolve().parent.parent / "schema" / "message.schema.json"
MAX_BYTES = 1000

DEFAULT_NEED = {
    "instruction": "ack",
    "task": "ack",
    "delivery": "ack",
    "question": "answer",
    "reply": "none",
    "confirm_request": "decision",
    "ack": "none",
    "alert": "ack",
}


class MessageError(Exception):
    pass


def serialize(message: dict) -> str:
    return json.dumps(message, ensure_ascii=False, separators=(",", ":"))


def agent_id(address: str) -> str:
    return address.split("/", 1)[1]


def load_registry(root: Path) -> dict:
    path = root / "agents.json"
    if not path.exists():
        raise MessageError(f"agent registry not found: {path}")
    return json.loads(path.read_text(encoding="utf-8"))


def logged_message(root: Path, message_id: str) -> str | None:
    sender = message_id.rsplit("-", 1)[0]
    log = root / "messages" / f"{sender}.jsonl"
    if not log.exists():
        return None
    for line in log.read_text(encoding="utf-8").splitlines():
        if json.loads(line)["id"] == message_id:
            return line
    return None


def schema_errors(validator: Draft202012Validator, message: dict) -> str | None:
    errors = sorted(validator.iter_errors(message), key=lambda e: list(e.path))
    if not errors:
        return None
    return "; ".join(f"{'/'.join(map(str, e.path)) or '<message>'}: {e.message}" for e in errors)


def check_references(root: Path, message: dict) -> str:
    """Check about/docs/re against the database, docs/ and message logs. Returns the project id."""
    try:
        with ResearchDB(root / "research_tree.db", message["from"]).reader() as tx:
            projects = tx.ids("project")
            if len(projects) != 1:
                raise MessageError(f"expected exactly one Project in the database, found {projects}")
            for entity in message.get("about", []):
                if tx.get(entity) is None:
                    raise MessageError(f"about: {entity} is not a {table_of(entity)} in the database")
            for doc in message.get("docs", []):
                ids = tx.ids("document", "WHERE n.path = $path", path=doc)
                if len(ids) != 1:
                    raise MessageError(f"docs: {doc} is registered {len(ids)} times, expected once")
                if tx.get(ids[0])["status"] == "superseded":
                    raise MessageError(f"docs: {doc} is superseded; reference its current version")
                if not (root / "docs" / doc).is_file():
                    raise MessageError(f"docs: {doc} is registered but missing on disk")
    except ResearchDBError as exc:
        raise MessageError(str(exc)) from None

    if "re" in message and logged_message(root, message["re"]) is None:
        raise MessageError(f"re: message {message['re']} is not in the message logs")
    return projects[0]


def append_message(root: Path, message: dict, validator: Draft202012Validator) -> str:
    """Assign the next id under the sender's log lock, validate and append. Returns the line."""
    sender = agent_id(message["from"])
    log_dir = root / "messages"
    log_dir.mkdir(exist_ok=True)
    with open(log_dir / f"{sender}.jsonl", "a+", encoding="utf-8") as log:
        fcntl.flock(log, fcntl.LOCK_EX)
        log.seek(0)
        lines = log.read().splitlines()
        last_seq = int(json.loads(lines[-1])["id"].rsplit("-", 1)[1]) if lines else 0
        message = {"v": 1, "id": f"{sender}-{last_seq + 1:04d}", **message}

        errors = schema_errors(validator, message)
        if errors:
            raise MessageError(errors)
        line = serialize(message)
        size = len(line.encode("utf-8"))
        if size > MAX_BYTES:
            raise MessageError(f"message is {size} bytes, limit is {MAX_BYTES}; shorten text or move detail into a document")

        log.write(line + "\n")
        log.flush()
        os.fsync(log.fileno())
        return line


CHANNEL_KEYS = {"native": (), "codex-queue": ("thread",), "herdr": ("herdr_agent",)}
MESSAGE_ID_RE = re.compile(r"^[A-Za-z0-9_.]+-[0-9]{4,}$")


def recipient_config(registry: dict, to: str, channel_override: str | None) -> dict:
    if to not in registry:
        raise MessageError(f"recipient {to} is not in agents.json")
    recipient = dict(registry[to])
    if channel_override:
        recipient["channel"] = channel_override
    channel = recipient.get("channel")
    if channel not in CHANNEL_KEYS:
        raise MessageError(f"agents.json: {to} has unknown channel {channel!r}")
    missing = [key for key in CHANNEL_KEYS[channel] if not recipient.get(key)]
    if missing:
        raise MessageError(f"agents.json: {to} needs {', '.join(missing)} for channel {channel}")
    return recipient


def deliver(line: str, recipient: dict) -> tuple[str, str]:
    """Send through the recipient's channel. Returns (status, detail)."""
    channel = recipient["channel"]
    if channel == "native":
        return "printed", f"send with Codex send_message_to_thread to thread {recipient.get('thread')}"
    if channel == "codex-queue":
        cmd = ["codex", "queue", "--thread", recipient["thread"], "--message", line]
        if recipient.get("remote"):
            cmd[2:2] = ["--remote", recipient["remote"]]
        accepted = "queued"
    else:
        cmd = ["herdr", "agent", "prompt", recipient["herdr_agent"], line]
        accepted = "submitted"
    # Argument list, no shell: the message text is never interpreted as a command.
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
    except (OSError, subprocess.TimeoutExpired) as exc:
        return "failed", f"{type(exc).__name__}: {exc}"
    if result.returncode != 0:
        return "failed", f"exit {result.returncode}: {(result.stderr or result.stdout).strip()[:300]}"
    return accepted, (result.stdout.strip() or "ok")[:300]


def record_delivery(root: Path, sender: str, message_id: str, to: str, channel: str, status: str, detail: str) -> None:
    record = {"id": message_id, "ts": now_utc(), "to": to, "channel": channel, "status": status, "detail": detail}
    with open(root / "messages" / f"{sender}.delivery.jsonl", "a", encoding="utf-8") as f:
        fcntl.flock(f, fcntl.LOCK_EX)
        f.write(serialize(record) + "\n")


def send(root: Path, line: str, registry: dict, channel_override: str | None) -> int:
    message = json.loads(line)
    recipient = recipient_config(registry, message["to"], channel_override)
    status, detail = deliver(line, recipient)
    record_delivery(root, agent_id(message["from"]), message["id"], message["to"], recipient["channel"], status, detail)
    print(line)
    print(f"{status}: {detail}", file=sys.stderr)
    return 1 if status == "failed" else 0


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="Validate, log and send one agent message.")
    p.add_argument("--root", type=Path, required=True, help="research/<project-id> directory")
    p.add_argument("--from", dest="sender", help="<role>/<agent-id> of the sender")
    p.add_argument("--to", help="<role>/<agent-id> of the recipient")
    p.add_argument("--type", choices=sorted(DEFAULT_NEED))
    p.add_argument("--text")
    p.add_argument("--docs", nargs="*", default=[], help="versioned paths relative to docs/")
    p.add_argument("--about", nargs="*", default=[], help="database entity ids")
    p.add_argument("--re", help="id of the message being answered")
    p.add_argument("--need", choices=["none", "ack", "answer", "decision"], help="default depends on --type")
    p.add_argument("--channel", choices=["native", "codex-queue", "herdr"], help="override agents.json")
    p.add_argument("--resend", metavar="ID", help="resend a logged message unchanged")
    args = p.parse_args(argv)

    root = args.root
    try:
        registry = load_registry(root)
        if args.resend:
            if not MESSAGE_ID_RE.match(args.resend):
                raise MessageError(f"--resend: {args.resend!r} is not a message id")
            line = logged_message(root, args.resend)
            if line is None:
                raise MessageError(f"message {args.resend} is not in the message logs")
            return send(root, line, registry, args.channel)

        missing = [name for name in ("sender", "to", "type", "text") if getattr(args, name) is None]
        if missing:
            p.error("required for a new message: " + ", ".join("--" + ("from" if m == "sender" else m) for m in missing))
        # Node workers are named after their node (worker/h0007) and only send; every other sender is registered.
        if args.sender not in registry and not args.sender.startswith("worker/"):
            raise MessageError(f"{args.sender} is not in agents.json")
        recipient_config(registry, args.to, args.channel)

        message = {
            "ts": now_utc(),
            "project": None,
            "from": args.sender,
            "to": args.to,
            "type": args.type,
            "text": args.text,
            "need": args.need or DEFAULT_NEED[args.type],
        }
        if args.re:
            message["re"] = args.re
        if args.about:
            message["about"] = args.about
        if args.docs:
            message["docs"] = args.docs

        validator = Draft202012Validator(json.loads(SCHEMA_PATH.read_text(encoding="utf-8")))
        # Schema check first so malformed ids never reach a query; id and project are filled in later.
        errors = schema_errors(validator, {"v": 1, "id": f"{agent_id(args.sender)}-0001", **message, "project": "P-placeholder"})
        if errors:
            raise MessageError(errors)
        message["project"] = check_references(root, message)

        line = append_message(root, message, validator)
        return send(root, line, registry, args.channel)
    except MessageError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
