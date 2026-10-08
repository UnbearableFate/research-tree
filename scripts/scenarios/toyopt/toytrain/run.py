"""The project's runner: one training run with the manifest research-tree imports (import_run_result).

    python -m toytrain.run --experiment E-0002 --seed 42 --attempt 1 --out outputs/E-0002/s42-a1 \\
        [--config configs/sgd.json] [--method sgd] [--lr 0.05] [--epochs 8] [--batch 32] [--accum 1] \\
        [--eval-split explore] [--data-dir data] [--sanity]

The method settings come from --config (a JSON object with method, lr, epochs, batch, accum, eval_split), then the
command-line flags given explicitly. The runner trains (toytrain.train), then writes OUT/run_manifest.json: the
experiment, seed and attempt, the code version (git HEAD of this repository and whether the tree had changes), the
exit status, the files it wrote, counts actually used, the data version and the identities of the splits, the
effective configuration, the environment, each metric's unit, and the measured wall time. A failed run still
writes a manifest with its exit status and error, and exits non-zero.
"""
from __future__ import annotations

import argparse
import json
import math
import os
import platform
import subprocess
import sys
import time
import traceback
from pathlib import Path

from toytrain import data, train

REPO = Path(__file__).resolve().parents[1]
UNITS = {"accuracy": "fraction", "eval_loss": "nats", "final_loss": "nats", "train_time_s": "seconds"}


def git(*args: str) -> str:
    out = subprocess.run(["git", "-C", str(REPO), *args], capture_output=True, text=True)
    return out.stdout.strip() if out.returncode == 0 else ""


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--experiment", required=True)
    p.add_argument("--seed", type=int, required=True)
    p.add_argument("--attempt", type=int, default=1)
    p.add_argument("--out", required=True)
    p.add_argument("--config")
    for key in ("method", "eval_split", "data_dir"):
        p.add_argument(f"--{key.replace('_', '-')}")
    for key, kind in (("lr", float), ("epochs", int), ("batch", int), ("accum", int)):
        p.add_argument(f"--{key}", type=kind)
    p.add_argument("--sanity", action="store_true")
    args = p.parse_args(argv)
    out = Path(args.out).resolve()
    out.mkdir(parents=True, exist_ok=True)
    settings = dict(train.DEFAULTS)
    if args.config:
        settings.update(json.loads(Path(args.config).read_text(encoding="utf-8")))
    for key in ("method", "lr", "epochs", "batch", "accum", "eval_split"):
        if getattr(args, key) is not None:
            settings[key] = getattr(args, key)
    argv_train = ["--seed", str(args.seed), "--out", str(out), "--method", str(settings["method"]),
                  "--lr", str(settings["lr"]), "--epochs", str(settings["epochs"]), "--batch", str(settings["batch"]),
                  "--accum", str(settings["accum"]), "--eval-split", str(settings["eval_split"])]
    if args.data_dir:
        argv_train += ["--data-dir", args.data_dir]
    if args.sanity:
        argv_train.append("--sanity")
    manifest = {
        "experiment_id": args.experiment, "seed": args.seed, "train_seed": args.seed, "attempt": args.attempt,
        "code_ref": git("rev-parse", "HEAD"), "code_dirty": bool(git("status", "--porcelain", "--untracked-files=no")),
        "command": [sys.executable, "-m", "toytrain.train", *argv_train],
        "env": {"python": platform.python_version(), "platform": platform.platform(), "host": platform.node(),
                "pid": os.getpid()},
        "units": {"accuracy": UNITS["accuracy"]}, "metric_units": UNITS, "data_version": data.GENERATOR_VERSION,
        "nodes_used": 1, "output_path": str(out), "log_path": "train.log",
    }
    start = time.time()
    try:
        result = train.train(train.parse(argv_train))
    except Exception as exc:  # the failure is recorded as it happened; nothing is made up for it
        wall = time.time() - start
        with open(out / "train.log", "a", encoding="utf-8") as log:
            log.write("ERROR " + "".join(traceback.format_exception_only(type(exc), exc)))
            log.write(traceback.format_exc())
        manifest.update(exit_status=1, error=f"{type(exc).__name__}: {exc}", walltime_used_s=max(1, math.ceil(wall)),
                        config={k: settings[k] for k in ("method", "lr", "epochs", "batch", "accum", "eval_split")})
        (out / "run_manifest.json").write_text(json.dumps(manifest, indent=1) + "\n", encoding="utf-8")
        print(json.dumps({"ok": False, "error": manifest["error"], "manifest": str(out / "run_manifest.json")}))
        return 1
    wall = time.time() - start
    m = result["metrics"]
    manifest.update({
        "exit_status": 0, "metrics_path": "metrics.json", "curve_path": "curve.json",
        "evidence_paths": ["predictions.jsonl", "model.json", "effective_config.json"],
        "counts": {"n_train": m["n_train"], "n_eval": m["n_eval"], "steps": m["steps"]},
        "config": result["config"], "eval_split": m["eval_split"], "eval_split_id": m["eval_split_id"],
        "eval_split_sha256": result["splits"]["eval"]["sha256"], "train_split_id": m["train_split_id"],
        "walltime_used_s": max(1, math.ceil(wall)), "wall_seconds": round(wall, 4),
    })
    (out / "run_manifest.json").write_text(json.dumps(manifest, indent=1) + "\n", encoding="utf-8")
    print(json.dumps({"ok": True, "accuracy": m["accuracy"], "manifest": str(out / "run_manifest.json")}))
    return 0


if __name__ == "__main__":
    sys.exit(main())
