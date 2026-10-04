"""research-tree cleanup for this project: which run outputs are disposable, and deleting them.

research-tree copied this file from its template when the project was set up; it belongs to the project now.
Adapt CLASSES to what the experiment harness writes (the root node's worker does this together with the
harness) and change anything else the project needs.

research_db's run_cleanup calls it once an experiment's statistics are recorded, in two steps, each a JSON
object on stdin and one on stdout:

  plan    {"runs": [{"run": "E-0005/s1", "output_dir": "/abs/dir", "evidence": ["/abs/log", ...]}],
           "keep": ["final_weights", ...]}
       -> {"items": [{"run": "E-0005/s1", "path": "/abs/dir/ckpt-100", "class": "periodic_ckpt", "bytes": 123}]}
          Lists what to delete; deletes nothing. research_db checks every item (inside the run's output_dir, no
          evidence, no class the experiment keeps) before step two.
  delete  {"items": [the items research_db approved]}
       -> {"items": [{..., "action": "deleted" | "failed", "reason": "..."}]}
          Deletes exactly those items.

A file no pattern matches is kept: logs, metrics, configs and curves are the experiment's evidence.
"""

from __future__ import annotations

import fnmatch
import json
import shutil
import sys
from pathlib import Path

# class -> glob patterns, matched against a file or directory name and against its path relative to the run's
# output directory. A matching directory is deleted whole. Order matters: the first class that matches wins.
CLASSES = {
    "optimizer_state": ["optimizer*.pt", "optimizer*.bin", "optim_state*", "rng_state*", "scheduler*.pt"],
    "periodic_ckpt": ["checkpoint-*", "ckpt-*", "step_*", "global_step*"],
    "final_weights": ["*.safetensors", "*.pt", "*.pth", "*.bin", "*.ckpt"],
    "predictions": ["predictions*.jsonl", "predictions*.json", "preds*.npy"],
    "trace": ["*.trace.json", "*.pt.trace.json", "profiler", "activations*", "grad_stats*"],
    "scratch": ["tmp", "scratch", "*.tmp"],
}


def classify(rel: Path) -> str | None:
    for name, patterns in CLASSES.items():
        if any(fnmatch.fnmatch(rel.name, p) or fnmatch.fnmatch(rel.as_posix(), p) for p in patterns):
            return name
    return None


def size(path: Path) -> int:
    if path.is_file():
        return path.stat().st_size
    return sum(p.stat().st_size for p in path.rglob("*") if p.is_file() and not p.is_symlink())


def plan(request: dict) -> dict:
    keep = set(request.get("keep", []))
    items = []
    for run in request["runs"]:
        root = Path(run["output_dir"])
        if not root.is_dir():
            continue
        evidence = [Path(e) for e in run.get("evidence", [])]
        stack = sorted(root.iterdir())
        while stack:
            path = stack.pop(0)
            if path.is_symlink():
                continue  # never follow a link out of the run's directory
            rel = path.relative_to(root)
            kind = classify(rel)
            holds_evidence = any(e == path or path in e.parents for e in evidence)
            if kind and kind not in keep and not holds_evidence:
                items.append({"run": run["run"], "path": str(path), "class": kind, "bytes": size(path)})
            elif path.is_dir():
                stack.extend(sorted(path.iterdir()))
    return {"items": items}


def delete(request: dict) -> dict:
    done = []
    for item in request["items"]:
        path = Path(item["path"])
        try:
            if path.is_dir() and not path.is_symlink():
                shutil.rmtree(path)
            else:
                path.unlink()
            done.append({**item, "action": "deleted"})
        except OSError as exc:
            done.append({**item, "action": "failed", "reason": str(exc)})
    return {"items": done}


if __name__ == "__main__":
    step = sys.argv[1] if len(sys.argv) > 1 else ""
    if step not in ("plan", "delete"):
        sys.exit("usage: research-tree-cleanup.py plan|delete < request.json")
    print(json.dumps((plan if step == "plan" else delete)(json.load(sys.stdin)), ensure_ascii=False))
