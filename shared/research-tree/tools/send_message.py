"""Validate, log and print one agent-to-agent message.

A research root (research/<project-id>/) holds research_tree.db, docs/,
messages/ and agents.json. This tool:

  1. builds the message (id, timestamp and project are filled in),
  2. validates it against schema/message.schema.json and the 1000-byte limit,
  3. checks the references: the project and every `about` id exist in the
     database, every `docs` path is registered, not superseded and present on
     disk, and `re` names a logged message,
  4. appends the exact line to messages/<role>--<agent-id>.jsonl,
  5. prints the line; the sender passes it on with its host's own means (in
     Claude Code: SendMessage to a worker; the research-tree mod calls this
     tool itself for the research window's messages and post_to_ui).

To pass on a logged message again, print it with --resend <id> rather than
composing a new one.

agents.json lists the registered "<role>/<agent-id>" addresses. Hypothesis workers
(worker/h0007) may send without a registry entry only when their identity is bound to exactly one hypothesis.
Every recipient and every other sender must be registered; the Architect is architect/root.
"""

from __future__ import annotations

import argparse
import fcntl
import json
import os
import re
import sys
from pathlib import Path

from jsonschema import Draft202012Validator
from research_db import ResearchDB, ResearchDBError, now_utc, table_of

SCHEMA_PATH = Path(__file__).resolve().parent.parent / "schema" / "message.schema.json"
MAX_BYTES = 1000
ADDRESS_PATTERN = (r"^(?:rld/main|ui/ui|architect/root|worker/(?!root$)[A-Za-z0-9_.]+|"
                   r"(?:explorer|analyst|reviewer)/[A-Za-z0-9_.]+)$")
ADDRESS_RE = re.compile(ADDRESS_PATTERN)
MESSAGE_ID_RE = re.compile(r"^(?:rld|ui|worker|architect|explorer|analyst|reviewer)--[A-Za-z0-9_.]+-[0-9]{4,}$")

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
    """Every role owns a distinct message namespace, including fixed root roles."""
    if not isinstance(address, str) or not ADDRESS_RE.fullmatch(address):
        raise MessageError(f"invalid agent address {address!r}")
    role, ident = address.split("/", 1)
    return f"{role}--{ident}"


def registered_address(address: str, registry: set[str]) -> bool:
    return address in registry


def load_registry(root: Path) -> set[str]:
    path = root / "agents.json"
    if not path.exists():
        raise MessageError(f"agent registry not found: {path}")
    try:
        addresses = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise MessageError(f"invalid agent registry {path}: {exc}") from None
    if not isinstance(addresses, list):
        raise MessageError("agents.json must list registered agent addresses")
    for address in addresses:
        agent_id(address)
    if len(set(addresses)) != len(addresses):
        raise MessageError("agents.json repeats an agent address")
    return set(addresses)


def logged_message(root: Path, message_id: str) -> str | None:
    if not MESSAGE_ID_RE.fullmatch(message_id):
        raise MessageError(f"{message_id!r} is not a message id")
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
    """Check registered identities, node ownership, about/docs/re. Returns the project id."""
    registry = load_registry(root)
    for address in (message["from"], message["to"]):
        agent_id(address)
    if not registered_address(message["to"], registry):
        raise MessageError(f"recipient {message['to']} is not in agents.json")
    if not registered_address(message["from"], registry) and not message["from"].startswith("worker/"):
        raise MessageError(f"{message['from']} is not in agents.json")
    try:
        with ResearchDB(root / "research_tree.db", message["from"]).reader() as tx:
            projects = tx.ids("project")
            if len(projects) != 1:
                raise MessageError(f"expected exactly one Project in the database, found {projects}")
            project = tx.require(projects[0], ("project",))
            for address in {message["from"], message["to"]}:
                role, ident = address.split("/", 1)
                if role == "worker":
                    owners = tx.ids("hypothesis", "WHERE n.worker_id = $worker_id", worker_id=ident)
                    if len(owners) != 1:
                        raise MessageError(f"{address} must be bound to exactly one hypothesis; found {owners}")
                elif role == "architect" and project.get("architect_id") != ident:
                    raise MessageError(f"{address} must be assigned to the project root")
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
        message = {**message, "v": 1, "id": f"{sender}-{last_seq + 1:04d}"}

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


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="Validate, log and print one agent message.")
    p.add_argument("--root", type=Path, required=True, help="research/<project-id> directory")
    p.add_argument("--from", dest="sender", help="<role>/<agent-id> of the sender")
    p.add_argument("--to", help="<role>/<agent-id> of the recipient")
    p.add_argument("--type", choices=sorted(DEFAULT_NEED))
    p.add_argument("--text")
    p.add_argument("--docs", nargs="*", default=[], help="versioned paths relative to docs/")
    p.add_argument("--about", nargs="*", default=[], help="database entity ids")
    p.add_argument("--re", help="id of the message being answered")
    p.add_argument("--need", choices=["none", "ack", "answer", "decision"], help="default depends on --type")
    p.add_argument("--resend", metavar="ID", help="print a logged message again, unchanged")
    args = p.parse_args(argv)

    root = args.root
    try:
        load_registry(root)
        if args.resend:
            if not MESSAGE_ID_RE.fullmatch(args.resend):
                raise MessageError(f"--resend: {args.resend!r} is not a message id")
            line = logged_message(root, args.resend)
            if line is None:
                raise MessageError(f"message {args.resend} is not in the message logs")
            print(line)
            return 0

        missing = [name for name in ("sender", "to", "type", "text") if getattr(args, name) is None]
        if missing:
            p.error("required for a new message: " + ", ".join("--" + ("from" if m == "sender" else m) for m in missing))
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

        print(append_message(root, message, validator))
        return 0
    except MessageError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
