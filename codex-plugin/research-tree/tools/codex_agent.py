"""Durable supervisor for one UI/worker turn. The main Codex thread remains the RLD."""
from __future__ import annotations

import json
import os
import signal
import socket
import subprocess
import sys
from pathlib import Path

import research_tree as tree
from codex_runtime import ROOT, Runtime
from codex_state import read_json, write_json
from research_db import now_utc


def command(spec, directory):
    actor = spec["actor"]
    runtime = Runtime(Path(spec["project"]))
    choice = spec["model"]
    model = choice["model"]
    if model == "inherit":
        model = read_json(runtime.cache / "leader.json", {}).get("model")
        if not model:
            raise ValueError("inherit needs the main session's model: trust hooks or research_control attach with model")
    effort = choice.get("effort")
    if effort is not None and not isinstance(effort, str):
        raise ValueError("Codex effort must be a named level, not a Claude token budget")
    argv = ["codex", "exec", "--json", "--skip-git-repo-check", "--model", model,
            "--output-last-message", str(directory / "answer.txt"), "--cd", spec.get("workdir", spec["project"])]
    if spec.get("workdir", spec["project"]) != spec["project"]:
        argv += ["--add-dir", spec["project"]]
    # An explicit server supports execution from an unpacked package too. If the plugin
    # is installed, its server receives the same fixed actor through its env allowlist;
    # its trusted file guards remain active. No global configuration is edited.
    configs = {
        "mcp_servers.research_tree.command": sys.executable,
        "mcp_servers.research_tree.args": [str(ROOT / "tools/codex_mcp.py"), "--project", spec["project"], "--actor", actor],
        "mcp_servers.research_tree.tool_timeout_sec": 1800,  # run_cleanup may take a while
        "sandbox_mode": "read-only" if actor == "ui/ui" else "workspace-write",
        "approval_policy": "never",
    }
    if effort is not None:
        configs["model_reasoning_effort"] = effort
    for key, value in configs.items():
        argv += ["-c", f"{key}={json.dumps(value, ensure_ascii=False)}"]
    if actor == "ui/ui":
        argv += ["--output-schema", str(ROOT / "schema/ui-response.schema.json")]
    if spec.get("resume"):
        argv += ["resume", spec["resume"]]
    argv.append("-")
    return argv


def run(directory: Path, lock_fd: int) -> int:
    spec = read_json(directory / "spec.json")
    runtime = Runtime(Path(spec["project"]))
    state_file = directory / "state.json"
    state = read_json(state_file)
    child = None
    interrupted = False

    def interrupt(signum, frame):
        nonlocal interrupted
        interrupted = True
        if child and child.poll() is None:
            child.terminate()

    signal.signal(signal.SIGTERM, interrupt)
    signal.signal(signal.SIGINT, interrupt)
    try:
        argv = command(spec, directory)
        env = {**os.environ, "RESEARCH_TREE_PROJECT": spec["project"], "RESEARCH_TREE_ACTOR": spec["actor"]}
        with (directory / "stderr.log").open("w") as errors:
            child = subprocess.Popen(argv, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=errors,
                                     text=True, cwd=spec["project"], env=env, pass_fds=(lock_fd,))
            state.update(status="running", started_at=now_utc(), pid=child.pid, supervisor_pid=os.getpid(),
                         host=socket.gethostname(), requested_model=spec["model"])
            write_json(state_file, state)
            child.stdin.write(spec["prompt"])
            child.stdin.close()
            with (directory / "events.jsonl").open("w", encoding="utf-8") as log:
                for line in child.stdout:
                    log.write(line)
                    log.flush()
                    try:
                        event = json.loads(line)
                    except ValueError:
                        continue
                    if event.get("type") == "thread.started":
                        thread = event["thread_id"]
                        state["thread_id"] = thread
                        write_json(state_file, state)
                        if spec.get("node_id"):
                            runtime.db("rld/main").bind_worker_session(spec["node_id"], thread)
                        tree.log_agent_model(runtime.root, {"agent": thread, "actor": spec["actor"], "event": "requested",
                                                            "model": argv[argv.index("--model") + 1],
                                                            "effort": spec["model"].get("effort")})
                    elif event.get("type") == "turn.failed":
                        state["turn_error"] = event.get("error")
            code = child.wait()
        state.update(exit_code=code, finished_at=now_utc())
        if interrupted:
            state["status"] = "interrupted"
        elif code or state.get("turn_error"):
            state["status"] = "failed"
        elif not state.get("thread_id"):
            state.update(status="failed", error="Codex returned no thread.started event")
        else:
            state["status"] = "completed"
        if spec["actor"] == "ui/ui":
            if state["status"] == "completed":
                answer = json.loads((directory / "answer.txt").read_text(encoding="utf-8"))
                state["actions"] = runtime.apply_ui(directory, answer)
            else:
                runtime.say("note", f"UI本轮未成功（{state['status']}）；详见 {directory}，没有执行其动作。")
        else:
            state["notification"] = runtime.enqueue(
                f"{spec['actor']} 本轮结束：{state['status']}。运行记录 {directory}。读取任务交付及日志核验；"
                "会话结束不代表科学任务或科研作业完成。", f"run-{spec['run']}")
    except Exception as exc:
        if child and child.poll() is None:
            child.terminate()
            try:
                child.wait(timeout=10)
            except subprocess.TimeoutExpired:
                child.kill()
                child.wait()
        state.update(status="failed", error=f"{type(exc).__name__}: {exc}", finished_at=now_utc())
        runtime.say("note", f"{spec['actor']} 启动或处理失败：{exc}；记录 {directory}")
        if spec["actor"] != "ui/ui":
            state["notification"] = runtime.enqueue(f"{spec['actor']} 本轮失败：{exc}。记录 {directory}；核对后再决定恢复。",
                                                    f"run-{spec['run']}")
    finally:
        write_json(state_file, state)
        os.close(lock_fd)
    return 0 if state["status"] == "completed" else 1


if __name__ == "__main__":
    raise SystemExit(run(Path(sys.argv[1]), int(sys.argv[2])))
