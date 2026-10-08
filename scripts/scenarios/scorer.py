#!/usr/bin/env python3
"""Independent scorer of ToyOpt Lab runs: recomputes correct / n from the saved model and the evaluation split.

It does not import the project's training code: it reads model.json (weights), the split file the run's manifest
names (checked against data/splits.json and the manifest's sha256), evaluates the logistic model itself, and
compares with the run's predictions.jsonl and metrics.json. A changed report or metrics file never changes what it
computes.

    python3 scripts/scenarios/scorer.py OUTPUT_DIR --data-dir PROJECT/code/data
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import sys
from pathlib import Path

SANITY_EVAL = 100


def _sigmoid(z: float) -> float:
    return 1 / (1 + math.exp(-max(-30.0, min(30.0, z))))


def load_rows(data_dir: Path, split: str, want_sha: str | None) -> tuple[list[dict], str]:
    splits = json.loads((data_dir / "splits.json").read_text(encoding="utf-8"))["splits"]
    entry = splits[split]
    raw = (data_dir / entry["file"]).read_bytes()
    digest = hashlib.sha256(raw).hexdigest()
    if digest != entry["sha256"] or (want_sha and digest != want_sha):
        raise ValueError(f"split {split}: file sha256 {digest[:12]} differs from splits.json/manifest")
    return [json.loads(line) for line in raw.decode("utf-8").splitlines() if line.strip()], digest


def score_output(out_dir: Path, data_dir: Path) -> dict:
    out_dir, data_dir = Path(out_dir), Path(data_dir)
    manifest = json.loads((out_dir / "run_manifest.json").read_text(encoding="utf-8"))
    config = manifest.get("config") or {}
    split = manifest.get("eval_split") or config.get("eval_split")
    rows, digest = load_rows(data_dir, split, manifest.get("eval_split_sha256"))
    # how many rows are scored follows from the run kind alone (the whole split, or the sanity prefix), never from
    # the run's own manifest; a manifest stating another count is reported
    n = SANITY_EVAL if config.get("sanity") else len(rows)
    rows = rows[:n]
    stated = (manifest.get("counts") or {}).get("n_eval")
    model = json.loads((out_dir / "model.json").read_text(encoding="utf-8"))
    w, b = model["w"], model["b"]
    preds = {r["id"]: int(_sigmoid(sum(a * c for a, c in zip(w, r["x"])) + b) > 0.5) for r in rows}
    correct = sum(preds[r["id"]] == r["y"] for r in rows)
    reported = {}
    if (out_dir / "predictions.jsonl").is_file():
        for line in (out_dir / "predictions.jsonl").read_text(encoding="utf-8").splitlines():
            if line.strip():
                p = json.loads(line)
                reported[p["id"]] = p
    labels = {r["id"]: r["y"] for r in rows}
    mismatched_preds = sorted(i for i, p in reported.items() if preds.get(i) != p.get("pred"))
    mismatched_labels = sorted(i for i, p in reported.items() if labels.get(i) != p.get("label"))
    metrics = json.loads((out_dir / "metrics.json").read_text(encoding="utf-8")) if (out_dir / "metrics.json").is_file() else {}
    accuracy = correct / len(rows)
    return {"output": str(out_dir), "split": split, "split_sha256": digest, "n": len(rows), "correct": correct,
            "accuracy": accuracy, "reported_accuracy": metrics.get("accuracy"),
            "accuracy_matches": metrics.get("accuracy") is not None and abs(metrics["accuracy"] - accuracy) < 1e-12,
            "prediction_mismatches": mismatched_preds[:20], "label_mismatches": mismatched_labels[:20],
            "manifest_n_eval": stated, "manifest_n_matches": stated == len(rows),
            "predictions_cover_split": set(reported) == set(labels)}


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("output", type=Path)
    p.add_argument("--data-dir", type=Path, required=True)
    args = p.parse_args(argv)
    print(json.dumps(score_output(args.output, args.data_dir), indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main())
