#!/usr/bin/env python3
"""Private confirmation material for a blind pilot (plans/research-tree-implementation-and-real-scenarios.md §11.4).

    python3 scripts/private_eval/private_material.py generate --out ~/rt-private/<task> [--name p1] [--n 400]
    python3 scripts/private_eval/private_material.py check --private ~/rt-private/<task> --public-data <project>/code/data

The material follows the public task rule (ToyOpt's teacher, published with the project) but its instances come from
a 64-bit instance seed drawn from the operating system's random source at generation time and kept only in the
private directory (mode 700) with the generation record. Labels carry the task's label noise, so they are not a
function of the features alone. `check` is the reconstruction review of §11.4: it regenerates the splits a reader of
the public project could make (every public split name with the public seeds, and instance seeds 0..N of every name)
and confirms none reproduces a private instance; it also scans the public data and code for the private seed.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import secrets
import sys
from datetime import datetime, timezone
from pathlib import Path

TOYOPT = Path(__file__).resolve().parents[1] / "scenarios" / "toyopt"
sys.path.insert(0, str(TOYOPT))
from toytrain import data  # noqa: E402


def row_key(row: dict) -> str:
    return hashlib.sha256(json.dumps(row["x"]).encode()).hexdigest()


def generate(out: Path, name: str, n: int) -> dict:
    out.mkdir(parents=True, exist_ok=True)
    os.chmod(out, 0o700)
    seed = secrets.randbits(64)
    rows = data.make_split(name, n, seed)
    (out / f"{name}.jsonl").write_text(data.split_text(rows), encoding="utf-8")
    record = {"name": name, "n": n, "generator": data.GENERATOR_VERSION, "task_seed": data.TASK_SEED,
              "instance_seed": seed, "source": "secrets.randbits(64)",
              "sha256": hashlib.sha256((out / f"{name}.jsonl").read_bytes()).hexdigest(),
              "created_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")}
    (out / f"{name}.generation.json").write_text(json.dumps(record, indent=1) + "\n", encoding="utf-8")
    for p in out.iterdir():
        os.chmod(p, 0o600)
    return {k: v for k, v in record.items() if k != "instance_seed"}


def check(private: Path, public_data: Path | None, tries: int = 2000) -> dict:
    problems = []
    for gen in private.glob("*.generation.json"):
        record = json.loads(gen.read_text())
        mine = {row_key(json.loads(line)) for line in (private / f"{record['name']}.jsonl").read_text().splitlines()}
        names = sorted({record["name"], *data.SPLITS})
        for name in names:
            seeds = list(range(tries)) + [s for _, s in data.SPLITS.values()]
            for s in seeds:
                if {row_key(r) for r in data.make_split(name, 5, s)} & mine:
                    problems.append(f"{record['name']}: instances reproduced by the public generator ({name}, seed {s})")
                    break
        secret = str(record["instance_seed"])
        if public_data is not None:
            for p in public_data.rglob("*"):
                if p.is_file() and secret in p.read_text(errors="ignore"):
                    problems.append(f"the private instance seed appears in {p}")
            for p in public_data.rglob("*.jsonl"):
                public = {row_key(json.loads(line)) for line in p.read_text().splitlines() if line.strip()}
                if public & mine:
                    problems.append(f"{p.name} shares instances with {record['name']}")
    return {"ok": not problems, "problems": problems}


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    g = sub.add_parser("generate")
    g.add_argument("--out", type=Path, required=True)
    g.add_argument("--name", default="p1")
    g.add_argument("--n", type=int, default=400)
    c = sub.add_parser("check")
    c.add_argument("--private", type=Path, required=True)
    c.add_argument("--public-data", type=Path)
    c.add_argument("--tries", type=int, default=2000)
    a = ap.parse_args()
    out = generate(a.out, a.name, a.n) if a.cmd == "generate" else check(a.private, a.public_data, a.tries)
    print(json.dumps(out))
    return 0 if out.get("ok", True) else 1


if __name__ == "__main__":
    sys.exit(main())
