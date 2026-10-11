"""Small, dependency-free persistence primitives for the Codex adapter (POSIX)."""
from __future__ import annotations

import fcntl
import json
import os
import re
import tempfile
from contextlib import contextmanager
from pathlib import Path


def read_json(path: Path, default=None):
    return json.loads(path.read_text(encoding="utf-8")) if path.is_file() else default


def write_json(path: Path, value) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temp = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            json.dump(value, stream, ensure_ascii=False, indent=2)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temp, path)
    finally:
        if os.path.exists(temp):
            os.unlink(temp)


@contextmanager
def locked(path: Path, blocking: bool = True):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a") as stream:
        fcntl.flock(stream, fcntl.LOCK_EX | (0 if blocking else fcntl.LOCK_NB))
        yield stream


def lock_busy(path: Path) -> bool:
    try:
        with locked(path, blocking=False):
            return False
    except BlockingIOError:
        return True


def actor_key(actor: str) -> str:
    if not re.fullmatch(r"(?:rld/main|ui/ui|worker/[A-Za-z0-9_.]+|architect/[A-Za-z0-9_.]+|explorer/main|analyst/main|assistant/lens_[A-Za-z0-9_.]+)", actor):
        raise ValueError(f"invalid adapter actor: {actor}")
    return actor.replace("architect/", "worker/", 1).replace("/", "-")  # one writer lock per node, across role migration


def project_dir(cwd: Path) -> Path:
    """An explicit project wins for workers in worktrees; otherwise use this directory."""
    return Path(os.environ.get("RESEARCH_TREE_PROJECT", str(cwd))).resolve()


def cache_dir(cwd: Path) -> Path:
    marker = read_json(cwd / ".research-tree.json")
    if not marker:
        raise ValueError(f"no research project in {cwd}; initialize it first")
    return Path(marker["root"]) / "cache" / "codex"
