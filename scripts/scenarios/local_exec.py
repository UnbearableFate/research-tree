#!/usr/bin/env python3
"""Local execution adapter of the ToyOpt Lab test projects: a stand-in "site skill" that really runs CPU jobs.

Copied into each test project as tools/local_exec.py. Its state lives in <project>/.local-exec/ (beside tools/):

  jobs/<key>.json      one record per submission key: job id, PID and process start time, state, exit code, usage
  launches.jsonl       append-only ledger of every process actually started (an observer counts duplicates here)
  events.jsonl         every call and its answer (the transport log)

    local_exec.py submit --key KEY --cwd DIR --out DIR -- COMMAND ...   start the job (same key again: no new process)
    local_exec.py status --key KEY                                    the job's state, found by its key
    local_exec.py wait --key KEY [--timeout 600]                      until the job has ended
    local_exec.py accounting --key KEY --write FILE                   actual usage of an ended job, as a JSON file
    local_exec.py cancel --key KEY                                    stop the job (only the process it started)
    local_exec.py list
    local_exec.py serve                                               the scheduler service (run by the controller)

When the scheduler service runs (`serve`, started by the test controller outside any agent sandbox), submit and
cancel only queue a request in .local-exec/queue/ and the service starts or stops the job: a host that runs each
command in a private, short-lived sandbox (Codex: its own PID namespace, killed when the command ends) can then
submit jobs that outlive the command, as with a real scheduler. Without the service, submit starts the job itself.

A job runs under its own supervisor process (a new session), so closing the agent session that submitted it does
not stop it. The supervisor writes usage.json into the job's output directory: measured CPU seconds of the child
process, wall seconds, nodes_used 1 and walltime_used_s (wall seconds rounded up, at least 1).

Test faults (plans/... §3.3, §10.2) are declared before a scenario in the JSON file named by RT_LOCAL_EXEC_FAULTS:
{"faults": [{"id": "F1", "window": "lose_submit_response" | "lose_settlement" | "extra_launch",
"key_glob": "*", "times": 1}]}. Consumed faults are recorded beside it (<file>.consumed.json). Without the
variable no fault ever happens.
"""
from __future__ import annotations

import argparse
import fcntl
import fnmatch
import json
import math
import os
import re
import signal
import subprocess
import sys
import time
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path

STATE = Path(os.environ.get("RT_LOCAL_EXEC_STATE") or Path(__file__).resolve().parents[1] / ".local-exec")
KEY_RE = re.compile(r"^[A-Za-z0-9_.:@/-]{1,128}$")
TRANSPORT_LOST = 75


def now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ")


def job_file(key: str) -> Path:
    return STATE / "jobs" / (key.replace("/", "__") + ".json")


@contextmanager
def locked():
    STATE.mkdir(parents=True, exist_ok=True)
    with open(STATE / ".lock", "w") as handle:
        fcntl.flock(handle, fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(handle, fcntl.LOCK_UN)


def read_job(key: str) -> dict | None:
    path = job_file(key)
    return json.loads(path.read_text(encoding="utf-8")) if path.is_file() else None


def write_job(job: dict) -> None:
    path = job_file(job["key"])
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(job, indent=1) + "\n", encoding="utf-8")
    tmp.replace(path)


def append(name: str, entry: dict) -> None:
    STATE.mkdir(parents=True, exist_ok=True)
    with open(STATE / name, "a", encoding="utf-8") as f:
        f.write(json.dumps({"ts": now(), **entry}) + "\n")


def proc_start(pid: int) -> int | None:
    """The process's start time in clock ticks since boot (/proc/<pid>/stat field 22): with the PID, its identity."""
    try:
        stat = Path(f"/proc/{pid}/stat").read_text()
    except OSError:
        return None
    return int(stat[stat.rindex(")") + 2:].split()[19])


def alive(job: dict) -> bool:
    pid = job.get("pid")
    return bool(pid) and proc_start(pid) == job.get("proc_start_ticks")


DAEMON_STALE_S = 15.0


def daemon() -> dict | None:
    """The scheduler service's heartbeat, when it is alive."""
    path = STATE / "daemon.json"
    try:
        beat = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return beat if time.time() - beat.get("at", 0) < DAEMON_STALE_S else None


def enqueue(kind: str, key: str) -> None:
    queue = STATE / "queue"
    queue.mkdir(parents=True, exist_ok=True)
    tmp = queue / f".{kind}-{key.replace('/', '__')}.tmp"
    tmp.write_text(json.dumps({"kind": kind, "key": key, "at": now()}), encoding="utf-8")
    tmp.replace(queue / f"{kind}-{key.replace('/', '__')}.json")


def fault(window: str, key: str) -> dict | None:
    """Consume one declared fault for this window and key, if any is left."""
    path = os.environ.get("RT_LOCAL_EXEC_FAULTS")
    if not path or not Path(path).is_file():
        return None
    plan = json.loads(Path(path).read_text(encoding="utf-8"))
    used_file = Path(path + ".consumed.json")
    with locked():
        used = json.loads(used_file.read_text(encoding="utf-8")) if used_file.is_file() else {}
        for f in plan.get("faults", []):
            if f.get("window") != window or not fnmatch.fnmatch(key, f.get("key_glob", "*")):
                continue
            if len(used.get(f["id"], [])) >= int(f.get("times", 1)):
                continue
            used.setdefault(f["id"], []).append({"key": key, "at": now()})
            used_file.write_text(json.dumps(used, indent=1) + "\n", encoding="utf-8")
            return f
    return None


def answer(call: str, key: str | None, payload: dict, code: int = 0) -> int:
    append("events.jsonl", {"call": call, "key": key, "exit": code, "answer": payload})
    print(json.dumps(payload, ensure_ascii=False))
    return code


def launch(key: str, launch_n: int) -> None:
    """Start the job's supervisor in its own session (it outlives the caller)."""
    subprocess.Popen([sys.executable, str(Path(__file__).resolve()), "_supervise", "--key", key,
                      "--launch", str(launch_n)], start_new_session=True, stdin=subprocess.DEVNULL,
                     stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                     env={**os.environ, "RT_LOCAL_EXEC_STATE": str(STATE)})


def start_job(key: str) -> None:
    launch(key, 1)
    if (extra := fault("extra_launch", key)) is not None:  # S6: one real extra start, for the observer
        append("faults.jsonl", {"fault": extra["id"], "window": "extra_launch", "key": key})
        launch(key, 2)


def submit(args) -> int:
    if not KEY_RE.match(args.key):
        return answer("submit", args.key, {"ok": False, "error": "key is 1..128 of letters, digits and _ . : @ / -"}, 2)
    command = args.command[1:] if args.command[:1] == ["--"] else args.command
    if not command:
        return answer("submit", args.key, {"ok": False, "error": "no command after --"}, 2)
    with locked():
        job = read_job(args.key)
        if job is None:
            job = {"key": args.key, "job_id": f"local-{args.key}", "state": "launching", "cwd": str(Path(args.cwd).resolve()),
                   "out": str(Path(args.out).resolve()), "command": command, "submitted_at": now(), "launches": 0}
            write_job(job)
            fresh = True
        else:
            fresh = False
    if fresh:
        if daemon() is not None:  # the scheduler service starts it, outside the caller's sandbox
            with locked():
                job = read_job(args.key)
                job["via"] = "daemon"
                write_job(job)
            enqueue("submit", args.key)
        else:
            start_job(args.key)
    deadline = time.time() + 15
    while time.time() < deadline:
        job = read_job(args.key)
        if job.get("pid") or job["state"] in ("exited", "failed_to_start"):
            break
        time.sleep(0.05)
    if fresh and (lost := fault("lose_submit_response", args.key)) is not None:
        append("faults.jsonl", {"fault": lost["id"], "window": "lose_submit_response", "key": args.key})
        print("transport error: the submit response was lost; query the job by its key", file=sys.stderr)
        append("events.jsonl", {"call": "submit", "key": args.key, "exit": TRANSPORT_LOST, "answer": None})
        return TRANSPORT_LOST
    return answer("submit", args.key, {"ok": True, "existing": not fresh, **view(job)})


def view(job: dict) -> dict:
    return {k: job.get(k) for k in ("job_id", "key", "state", "pid", "started_at", "finished_at", "exit_code",
                                    "out", "cpu_seconds", "wall_seconds")}


def supervise(args) -> int:
    job = read_job(args.key)
    out = Path(job["out"]) if args.launch == 1 else Path(job["out"]) / f"duplicate-launch-{args.launch}"
    out.mkdir(parents=True, exist_ok=True)
    stdout = open(out / "job.stdout.log", "ab")
    started = time.time()
    command = list(job["command"])
    if args.launch != 1:  # an extra start writes into its own directory, never over the job's own artifacts
        for i, arg in enumerate(command):
            if arg == "--out" and i + 1 < len(command):
                command[i + 1] = str(out)
            elif arg.startswith("--out="):
                command[i] = f"--out={out}"
    try:
        child = subprocess.Popen(command, cwd=job["cwd"], stdout=stdout, stderr=subprocess.STDOUT,
                                 stdin=subprocess.DEVNULL)
    except OSError as exc:
        with locked():
            job = read_job(args.key)
            if args.launch == 1:
                job.update(state="failed_to_start", error=str(exc), finished_at=now())
                write_job(job)
        append("launches.jsonl", {"key": args.key, "launch": args.launch, "pid": None, "error": str(exc)})
        return 1
    ticks = proc_start(child.pid)
    append("launches.jsonl", {"key": args.key, "job_id": job["job_id"], "launch": args.launch, "pid": child.pid,
                              "proc_start_ticks": ticks, "out": str(out)})
    if args.launch == 1:
        with locked():
            job = read_job(args.key)
            job.update(state="running", pid=child.pid, proc_start_ticks=ticks, supervisor_pid=os.getpid(),
                       started_at=now(), launches=job.get("launches", 0) + 1)
            write_job(job)
    _, status, usage = os.wait4(child.pid, 0)
    wall = time.time() - started
    code = os.waitstatus_to_exitcode(status)
    cpu = round(usage.ru_utime + usage.ru_stime, 4)
    record = {"job_id": job["job_id"], "submission_key": args.key, "launch": args.launch, "pid": child.pid,
              "exit_code": code, "cpu_seconds": cpu, "wall_seconds": round(wall, 4), "nodes_used": 1,
              "walltime_used_s": max(1, math.ceil(wall)), "node_seconds": max(1, math.ceil(wall)),
              "max_rss_kib": usage.ru_maxrss, "finished_at": now()}
    (out / "usage.json").write_text(json.dumps(record, indent=1) + "\n", encoding="utf-8")
    append("launches.jsonl", {"key": args.key, "launch": args.launch, "pid": child.pid, "ended": True,
                              "exit_code": code, "cpu_seconds": cpu, "wall_seconds": round(wall, 4)})
    if args.launch == 1:
        with locked():
            job = read_job(args.key)
            if job["state"] != "cancelled":
                job["state"] = "exited"
            job.update(exit_code=code, finished_at=record["finished_at"], cpu_seconds=cpu,
                       wall_seconds=round(wall, 4), walltime_used_s=record["walltime_used_s"])
            write_job(job)
    return 0


def status(args) -> int:
    job = read_job(args.key)
    if job is None:
        return answer("status", args.key, {"ok": True, "found": False, "key": args.key})
    if job.get("via") == "daemon":  # its process lives outside the caller's view; the service keeps the record
        if job["state"] in ("launching", "running") and daemon() is None:
            job["state"] = "unknown (scheduler service not answering)"
    elif job["state"] == "running" and not alive(job):
        time.sleep(0.2)  # the supervisor may be writing the end right now
        job = read_job(args.key)
        if job["state"] == "running" and not alive(job):
            job["state"] = "lost"
    return answer("status", args.key, {"ok": True, "found": True, **view(job)})


def wait(args) -> int:
    deadline = time.time() + args.timeout
    while time.time() < deadline:
        job = read_job(args.key)
        if job is None:
            return answer("wait", args.key, {"ok": False, "error": f"no job {args.key}"}, 2)
        if job["state"] in ("exited", "cancelled", "failed_to_start"):
            return answer("wait", args.key, {"ok": True, **view(job)})
        time.sleep(0.2)
    return answer("wait", args.key, {"ok": False, "error": "timeout", **view(read_job(args.key))}, 3)


def accounting(args) -> int:
    job = read_job(args.key)
    if job is None or job["state"] not in ("exited", "cancelled"):
        return answer("accounting", args.key, {"ok": False, "error": f"job {args.key} has not ended",
                                               **(view(job) if job else {})}, 2)
    record = {"job_id": job["job_id"], "submission_key": args.key, "nodes_used": 1,
              "walltime_used_s": job.get("walltime_used_s") or 1, "node_seconds": job.get("walltime_used_s") or 1,
              "cpu_seconds": job.get("cpu_seconds"), "wall_seconds": job.get("wall_seconds"),
              "exit_code": job.get("exit_code"), "source": "tools/local_exec.py (measured by the job's supervisor)"}
    target = Path(args.write)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(record, indent=1) + "\n", encoding="utf-8")
    if (lost := fault("lose_settlement", args.key)) is not None:
        append("faults.jsonl", {"fault": lost["id"], "window": "lose_settlement", "key": args.key})
        print("transport error: the accounting answer was lost; ask again", file=sys.stderr)
        append("events.jsonl", {"call": "accounting", "key": args.key, "exit": TRANSPORT_LOST, "answer": None})
        return TRANSPORT_LOST
    return answer("accounting", args.key, {"ok": True, "file": str(target), **record})


def cancel(args) -> int:
    with locked():
        job = read_job(args.key)
        if job is None:
            return answer("cancel", args.key, {"ok": False, "error": f"no job {args.key}"}, 2)
        if job.get("via") == "daemon" and job["state"] == "running":
            enqueue("cancel", args.key)
            return answer("cancel", args.key, {"ok": True, "cancelled": "requested", **view(job)})
        if job["state"] != "running" or not alive(job):
            return answer("cancel", args.key, {"ok": True, "cancelled": False, **view(job)})
        os.kill(job["pid"], signal.SIGTERM)  # only the process this adapter started, identified by PID + start time
        job["state"] = "cancelled"
        write_job(job)
    return answer("cancel", args.key, {"ok": True, "cancelled": True, **view(job)})


def serve(args) -> int:
    """The scheduler service: heartbeat, then start queued submissions and carry out queued cancellations."""
    STATE.mkdir(parents=True, exist_ok=True)
    queue = STATE / "queue"
    queue.mkdir(exist_ok=True)
    append("events.jsonl", {"call": "serve", "key": None, "exit": 0, "answer": {"pid": os.getpid()}})
    while True:
        (STATE / "daemon.json").write_text(json.dumps({"pid": os.getpid(), "at": time.time()}), encoding="utf-8")
        for req_file in sorted(queue.glob("*.json")):
            req = json.loads(req_file.read_text(encoding="utf-8"))
            req_file.unlink()
            job = read_job(req["key"])
            if job is None:
                continue
            if req["kind"] == "submit" and job["state"] == "launching":
                start_job(req["key"])
            elif req["kind"] == "cancel" and job["state"] == "running" and alive(job):
                os.kill(job["pid"], signal.SIGTERM)
                with locked():
                    job = read_job(req["key"])
                    job["state"] = "cancelled"
                    write_job(job)
        if args.once:
            return 0
        time.sleep(0.2)


def list_jobs(_args) -> int:
    jobs = [json.loads(p.read_text()) for p in sorted((STATE / "jobs").glob("*.json"))] if (STATE / "jobs").is_dir() else []
    print(json.dumps([view(j) for j in jobs], ensure_ascii=False))
    return 0


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("submit")
    s.add_argument("--key", required=True)
    s.add_argument("--cwd", required=True)
    s.add_argument("--out", required=True)
    s.add_argument("command", nargs=argparse.REMAINDER)
    for name in ("status", "cancel"):
        sub.add_parser(name).add_argument("--key", required=True)
    w = sub.add_parser("wait")
    w.add_argument("--key", required=True)
    w.add_argument("--timeout", type=float, default=600)
    a = sub.add_parser("accounting")
    a.add_argument("--key", required=True)
    a.add_argument("--write", required=True)
    sub.add_parser("list")
    sd = sub.add_parser("serve")
    sd.add_argument("--once", action="store_true", help=argparse.SUPPRESS)
    sv = sub.add_parser("_supervise")
    sv.add_argument("--key", required=True)
    sv.add_argument("--launch", type=int, default=1)
    args = p.parse_args(argv)
    return {"submit": submit, "status": status, "wait": wait, "accounting": accounting, "cancel": cancel,
            "list": list_jobs, "serve": serve, "_supervise": supervise}[args.cmd](args)


if __name__ == "__main__":
    sys.exit(main())
