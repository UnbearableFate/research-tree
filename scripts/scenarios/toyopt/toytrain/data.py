"""ToyOpt Lab data: a fixed synthetic binary task and its splits (plans/research-tree-implementation-and-real-scenarios.md §3).

One task rule (teacher weights from TASK_SEED, a non-linear term and label noise) and independent sample instances
per split: train, explore (the exploration validation set), c1 and c2 (confirmation sets). Every split has its own
instance seed, so c1 and c2 share the task but none of explore's samples or labels. A split's identity is the
SHA-256 of its file content: a training seed never changes it, and a renamed file is still the same material.

The generator writes the splits as JSON lines ({"id", "x", "y"}) and a splits.json manifest; training only reads
those files.
"""
from __future__ import annotations

import hashlib
import json
import random
from pathlib import Path

GENERATOR_VERSION = "toyopt-data-1"
N_FEATURES = 16
TASK_SEED = 1234
# split -> (samples, instance seed); the instance seed draws the samples, the task seed the rule they follow.
# c1/c2 use instance seeds never drawn during the S0 development calibration (that touched 33 and 44 once).
SPLITS = {"train": (1200, 11), "explore": (400, 22), "c1": (400, 133), "c2": (400, 144)}
ROLES = {"train": "train", "explore": "exploration_validation", "c1": "confirmation", "c2": "confirmation"}
SANITY_TRAIN, SANITY_EVAL = 200, 100


def teacher(task_seed: int = TASK_SEED) -> list[float]:
    rng = random.Random(f"task:{task_seed}")
    return [round(rng.gauss(0, 1), 6) for _ in range(N_FEATURES)]


def make_split(name: str, n: int, instance_seed: int, task_seed: int = TASK_SEED) -> list[dict]:
    """n samples of the task drawn with the split's own instance seed (string seeds are deterministic)."""
    w = teacher(task_seed)
    rng = random.Random(f"split:{task_seed}:{name}:{instance_seed}")
    rows = []
    for i in range(n):
        x = [round(rng.gauss(0, 1), 6) for _ in range(N_FEATURES)]
        z = sum(a * b for a, b in zip(w, x)) + 0.8 * x[0] * x[1] + rng.gauss(0, 1.2)
        rows.append({"id": f"{name}-{i:05d}", "x": x, "y": 1 if z > 0 else 0})
    return rows


def split_text(rows: list[dict]) -> str:
    return "".join(json.dumps(r, separators=(",", ":")) + "\n" for r in rows)


def write_splits(data_dir: Path, splits: dict | None = None, task_seed: int = TASK_SEED) -> dict:
    """Write every split and splits.json; returns the manifest. The same inputs give byte-identical files."""
    data_dir.mkdir(parents=True, exist_ok=True)
    manifest = {"generator_version": GENERATOR_VERSION, "n_features": N_FEATURES, "task_seed": task_seed,
                "splits": {}}
    for name, (n, instance_seed) in (splits or SPLITS).items():
        text = split_text(make_split(name, n, instance_seed, task_seed))
        (data_dir / f"{name}.jsonl").write_text(text, encoding="utf-8")
        digest = hashlib.sha256(text.encode("utf-8")).hexdigest()
        manifest["splits"][name] = {"file": f"{name}.jsonl", "n": n, "role": ROLES.get(name, "other"),
                                    "sha256": digest, "split_id": f"{name}@{digest[:12]}"}
    (data_dir / "splits.json").write_text(json.dumps(manifest, indent=1, sort_keys=True) + "\n", encoding="utf-8")
    return manifest


def load_split(data_dir: Path, name: str) -> tuple[list[dict], dict]:
    """A split's rows and its manifest entry; refuses a file that no longer matches the manifest."""
    manifest = json.loads((data_dir / "splits.json").read_text(encoding="utf-8"))
    entry = manifest["splits"].get(name)
    if entry is None:
        raise FileNotFoundError(f"no split {name!r} in {data_dir / 'splits.json'}")
    text = (data_dir / entry["file"]).read_text(encoding="utf-8")
    if hashlib.sha256(text.encode("utf-8")).hexdigest() != entry["sha256"]:
        raise ValueError(f"{entry['file']} does not match splits.json")
    return [json.loads(line) for line in text.splitlines() if line.strip()], entry
