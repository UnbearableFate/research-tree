#!/usr/bin/env python3
"""The trusted evaluator of a blind pilot (plans/research-tree-implementation-and-real-scenarios.md §11.4).

    python3 scripts/private_eval/evaluator.py serve --private ~/rt-private/<task> --spool <workspace>/eval-spool \
        [--budget 6]
    python3 scripts/private_eval/evaluator.py once ...        # handle the requests waiting now, then exit

It runs outside the agent's sandbox and is the only reader of the private material. The agent (or its training
job) writes a request into spool/requests/<request_id>.json:
    {"request_id": "...", "run_ref": "E-0007/s42@1", "material": "p1", "model": "<path inside the workspace>"}
The evaluator checks the request's fixed structure, reads the model as data (format toyopt-logreg-1: n_features
weights and a bias, nothing executable), scores it on the private split and writes spool/answers/<request_id>.json
with the accuracy only. It never runs anything the agent provides. A request is bound to its run attempt and
material: the same request again returns the same answer and counts once; another request for an already scored
run attempt and material returns that answer too; a material has a fixed budget of distinct run attempts
(no free enumeration oracle). Malformed requests, unknown materials, models outside the workspace and requests over
the budget are refused with a reason, and every handled request leaves the queue (renamed to .done).
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import re
import sys
import time
from pathlib import Path

REQUEST_FIELDS = {"request_id", "run_ref", "material", "model"}
ID_RE = re.compile(r"[A-Za-z0-9_.-]{1,64}")
RUN_RE = re.compile(r"E-\d{4,}/s-?\d+@\d+")
MAX_MODEL_BYTES = 1 << 20


class Refused(Exception):
    pass


def load_private(private: Path, name: str) -> list[dict]:
    path = private / f"{name}.jsonl"
    if not ID_RE.fullmatch(name) or not path.is_file():
        raise Refused(f"unknown material {name!r}")
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def read_model(workspace: Path, rel: str) -> tuple[list[float], float]:
    try:
        path = (workspace / rel).resolve() if not Path(rel).is_absolute() else Path(rel).resolve()
    except ValueError:  # e.g. an embedded NUL: no file has that name
        raise Refused("the model is a file inside the workspace") from None
    if not path.is_relative_to(workspace.resolve()) or not path.is_file():
        raise Refused("the model is a file inside the workspace")
    if path.stat().st_size > MAX_MODEL_BYTES:
        raise Refused("the model file is too large for a toyopt-logreg-1 model")
    try:
        model = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, UnicodeDecodeError, RecursionError):
        raise Refused("the model is JSON data (format toyopt-logreg-1)") from None
    w, b = model.get("w") if isinstance(model, dict) else None, model.get("b") if isinstance(model, dict) else None
    if (not isinstance(model, dict) or model.get("format") != "toyopt-logreg-1" or not isinstance(w, list)
            or len(w) != model.get("n_features") or not all(isinstance(v, (int, float)) and math.isfinite(v) for v in w)
            or not isinstance(b, (int, float)) or not math.isfinite(b)):
        raise Refused("the model is {format: toyopt-logreg-1, n_features, w: [finite numbers], b: finite number}")
    return [float(v) for v in w], float(b)


def accuracy(rows: list[dict], w: list[float], b: float) -> float:
    if len(w) != len(rows[0]["x"]):
        raise Refused(f"the model has {len(w)} features, the material {len(rows[0]['x'])}")
    correct = 0
    for r in rows:
        z = sum(a * c for a, c in zip(w, r["x"])) + b
        correct += int((z > 0) == bool(r["y"]))
    return correct / len(rows)


class Evaluator:
    def __init__(self, private: Path, spool: Path, workspace: Path, budget: int):
        self.private, self.spool, self.workspace, self.budget = private, spool, workspace, budget
        (spool / "requests").mkdir(parents=True, exist_ok=True)
        (spool / "answers").mkdir(parents=True, exist_ok=True)
        self.ledger_path = private / "evaluator-ledger.json"  # private: the agent cannot edit the books
        self.ledger = json.loads(self.ledger_path.read_text()) if self.ledger_path.is_file() else {"scored": {}, "requests": {}}

    def save(self) -> None:
        self.ledger_path.write_text(json.dumps(self.ledger, indent=1), encoding="utf-8")

    def handle(self, req_path: Path) -> dict:
        """Answer one request and move it out of the queue, whatever it holds: a malformed request is refused with
        its reason, never left behind to stop the service again at its next pass."""
        try:
            req = json.loads(req_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError, UnicodeDecodeError, RecursionError):  # unreadable or not JSON
            req = None
        rid = req.get("request_id") if isinstance(req, dict) else None
        try:
            if not isinstance(req, dict) or set(req) != REQUEST_FIELDS \
                    or not all(isinstance(v, str) for v in req.values()) \
                    or not ID_RE.fullmatch(rid) or not RUN_RE.fullmatch(req["run_ref"]):
                raise Refused(f"a request is exactly {sorted(REQUEST_FIELDS)}, each a string, with a run attempt ref "
                              "E-…/s…@n")
            digest = hashlib.sha256(json.dumps(req, sort_keys=True).encode()).hexdigest()
            seen = self.ledger["requests"].get(rid)
            if seen is not None:
                if seen["digest"] != digest:
                    raise Refused(f"request {rid} was already made with other content")
                return seen["answer"]
            key = f"{req['material']}|{req['run_ref']}"
            if key in self.ledger["scored"]:  # the same run attempt on the same material: one sample, one answer
                answer = {**self.ledger["scored"][key], "request_id": rid, "repeat": True}
            else:
                rows = load_private(self.private, req["material"])
                w, b = read_model(self.workspace, req["model"])
                used = sum(1 for k in self.ledger["scored"] if k.startswith(req["material"] + "|"))
                if used >= self.budget:
                    raise Refused(f"material {req['material']} has scored its {self.budget} run attempts")
                answer = {"ok": True, "request_id": rid, "run_ref": req["run_ref"], "material": req["material"],
                          "accuracy": accuracy(rows, w, b), "n": len(rows)}
                self.ledger["scored"][key] = {k: v for k, v in answer.items() if k != "request_id"}
            self.ledger["requests"][rid] = {"digest": digest, "answer": answer}
        except Refused as exc:
            answer = {"ok": False, "request_id": rid, "refused": str(exc)}
            if isinstance(rid, str) and ID_RE.fullmatch(rid):
                self.ledger["requests"].setdefault(rid, {"digest": None, "answer": answer})
        self.save()
        name = rid if isinstance(rid, str) and ID_RE.fullmatch(rid) else req_path.stem
        (self.spool / "answers" / f"{name}.json").write_text(json.dumps(answer) + "\n", encoding="utf-8")
        req_path.rename(req_path.with_suffix(".done"))
        return answer

    def once(self) -> list[dict]:
        return [self.handle(p) for p in sorted((self.spool / "requests").glob("*.json"))]


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("mode", choices=("serve", "once"))
    ap.add_argument("--private", type=Path, required=True)
    ap.add_argument("--spool", type=Path, required=True)
    ap.add_argument("--workspace", type=Path, help="where models may be read from (default: the spool's parent)")
    ap.add_argument("--budget", type=int, default=6)
    a = ap.parse_args()
    ev = Evaluator(a.private, a.spool, a.workspace or a.spool.parent, a.budget)
    if a.mode == "once":
        print(json.dumps(ev.once()))
        return 0
    while True:
        ev.once()
        time.sleep(0.5)


if __name__ == "__main__":
    sys.exit(main())
