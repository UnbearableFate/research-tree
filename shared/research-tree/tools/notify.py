"""Optional outside notification (plans/design 00 §2.4 item 6, 13 §2.2): a confirmation request or a usage alert is
also POSTed as JSON to research-tree.yaml's notify.url, for a user who is away from the host. Only these two kinds;
an unanswered notification is recorded, never taken as consent. Every attempt is logged to logs/notify.jsonl.
Nothing here raises: a failed notification does not stop the research workflow."""

from __future__ import annotations

import json
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

KINDS = ("confirm_request", "alert")


def send(root: Path, config: dict, kind: str, text: str, docs: list[str] | None = None) -> dict:
    """POST {project, kind, text, docs, ts} to notify.url when one is configured; returns the logged record."""
    notify = config.get("notify") or {}
    record = {"ts": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"), "kind": kind, "text": text[:500],
              "docs": docs or []}
    if kind not in KINDS:
        record["outcome"] = f"skipped: kind is one of {KINDS}"
    elif not notify.get("url"):
        record["outcome"] = "skipped: no notify.url"
    else:
        body = json.dumps({"project": root.name, **{k: record[k] for k in ("kind", "text", "docs", "ts")}},
                          ensure_ascii=False).encode("utf-8")
        request = urllib.request.Request(notify["url"], data=body, method="POST",
                                         headers={"Content-Type": "application/json"})
        try:
            with urllib.request.urlopen(request, timeout=notify.get("timeout_s", 10)) as response:
                record["outcome"] = f"sent: HTTP {response.status}"
        except Exception as exc:  # noqa: BLE001 — a notification never breaks the workflow
            record["outcome"] = f"failed: {type(exc).__name__}: {exc}"[:300]
    log = root / "logs" / "notify.jsonl"
    log.parent.mkdir(parents=True, exist_ok=True)
    with log.open("a", encoding="utf-8") as f:
        f.write(json.dumps(record, ensure_ascii=False) + "\n")
    return record
