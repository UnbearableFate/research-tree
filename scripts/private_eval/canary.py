#!/usr/bin/env python3
"""Canary probe for the blind-pilot boundary (§11.4). Run inside the sandbox; it tries the ways a process could reach
the private material and reports each attempt. A canary file holds a random token and nothing sensitive.

    canary.py plant --private DIR                      # outside: write DIR/canary.txt, print its token
    sandbox.sh DIR WORK -- python3 canary.py probe --private DIR --token-sha <sha256 of the token> --work WORK

`probe` reports, per route, whether the canary content was obtained (it compares SHA-256, so the probe never needs
the token itself): direct read, directory listing, a symbolic link from the workspace, environment variables, every
visible process's environment and command line, inherited file descriptors, the Docker socket and a search of the
file system for the file name. It also checks that ordinary work still functions (write and read in the workspace).
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import secrets
import socket
import sys
from pathlib import Path


def h(text: str) -> str:
    return hashlib.sha256(text.encode()).hexdigest()


def plant(private: Path) -> dict:
    private.mkdir(parents=True, exist_ok=True)
    os.chmod(private, 0o700)
    token = f"CANARY-{secrets.token_hex(16)}"
    (private / "canary.txt").write_text(token)
    os.chmod(private / "canary.txt", 0o600)
    return {"token_sha256": h(token), "path": str(private / "canary.txt")}


def probe(private: Path, token_sha: str, work: Path) -> dict:
    found = {}

    def hit(text: str) -> bool:
        return any(h(part) == token_sha for part in text.replace("\x00", " ").split())

    def attempt(name, fn):
        import time
        start = time.monotonic()
        try:
            found[name] = {"obtained": bool(fn())}
        except Exception as exc:  # a refusal is the expected outcome
            found[name] = {"obtained": False, "error": f"{type(exc).__name__}: {str(exc)[:120]}"}
        found[name]["seconds"] = round(time.monotonic() - start, 2)
        print(f"{name}: {found[name]}", file=sys.stderr, flush=True)
    attempt("direct_read", lambda: hit((private / "canary.txt").read_text()))
    attempt("listing", lambda: "canary.txt" in os.listdir(private))
    link = work / ".canary-link"
    def via_link():
        if link.is_symlink() or link.exists():
            link.unlink()
        link.symlink_to(private / "canary.txt")
        try:
            return hit(link.read_text())
        finally:
            link.unlink()
    attempt("symlink", via_link)
    attempt("environment", lambda: any(hit(v) or str(private) in v for v in os.environ.values()))
    def procs():
        for p in Path("/proc").iterdir():
            if p.name.isdigit():
                for f in ("environ", "cmdline"):
                    try:
                        text = (p / f).read_bytes().decode(errors="ignore")
                    except OSError:
                        continue
                    if hit(text):
                        return True
                    if str(private) in text:  # the location is not secret (bwrap's own arguments name it)
                        path_seen.add(p.name)
        return False
    path_seen: set = set()
    attempt("processes", procs)
    def fds():
        for fd in os.listdir("/proc/self/fd"):
            try:
                target = os.readlink(f"/proc/self/fd/{fd}")
            except OSError:
                continue
            if target.startswith(str(private)):
                return True
        return False
    attempt("inherited_fds", fds)
    def docker():
        s = socket.socket(socket.AF_UNIX)
        s.settimeout(2)
        s.connect("/var/run/docker.sock")
        s.sendall(b"GET /version HTTP/1.0\r\n\r\n")
        return b"ApiVersion" in s.recv(4096)
    attempt("docker_socket", docker)
    def search():  # where a copy would most likely be: beside the private directory and in temporary directories
        for top, depth in ((private.parent, 1), (Path("/tmp"), 3), (Path("/var/tmp"), 3)):
            for path in [top, *[q for d in range(1, depth + 1) for q in top.glob("/".join(["*"] * d))]]:
                if path.name == "canary.txt" and path.is_file() and hit(path.read_text(errors="ignore")):
                    return True
        return False
    attempt("filesystem_search", search)
    ok_work = work / ".canary-work"
    ok_work.write_text("work")
    works = ok_work.read_text() == "work"
    ok_work.unlink()
    return {"routes": found, "blocked": not any(r["obtained"] for r in found.values()), "workspace_usable": works,
            "private_path_named_by_pids": sorted(path_seen)}


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("mode", choices=("plant", "probe"))
    ap.add_argument("--private", type=Path, required=True)
    ap.add_argument("--token-sha")
    ap.add_argument("--work", type=Path, default=Path.cwd())
    a = ap.parse_args()
    out = plant(a.private) if a.mode == "plant" else probe(a.private, a.token_sha, a.work)
    print(json.dumps(out))
    return 0


if __name__ == "__main__":
    sys.exit(main())
