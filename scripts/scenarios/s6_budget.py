#!/usr/bin/env python3
"""The fictional user's budget edits in the S6 scenario (run_s6.sh).

    s6_budget.py one-more <research-tree.yaml> <project> <plugin tools dir>   # room for exactly one more search run
    s6_budget.py lift <research-tree.yaml>                                     # no total limit again
    s6_budget.py arm <fault file> <window>                                     # arm one adapter fault for the next call
    s6_budget.py disarm <fault file>

one-more reads the committed node-seconds (budget_status) and the largest registered single-run request among the
Zebra and Yak search experiments, and sets budget.total_limit to committed + that request + half of it: one more such
reservation fits, two do not. It prints what it set.
"""
import glob
import json
import re
import sys
from pathlib import Path


def set_total(yaml_path: Path, value: str) -> None:
    text = yaml_path.read_text(encoding="utf-8")
    new, n = re.subn(r"(\n  total_limit: )\S+", rf"\g<1>{value}", text, count=1)
    if n != 1:
        raise SystemExit("no budget.total_limit line")
    yaml_path.write_text(new, encoding="utf-8")


if sys.argv[1] == "one-more":
    yaml_path, project, tools = Path(sys.argv[2]), Path(sys.argv[3]), sys.argv[4]
    sys.path.insert(0, tools)
    from research_db import ResearchDB
    db = ResearchDB(glob.glob(f"{project}/research/*/research_tree.db")[0], "ui/ui")
    committed = db.budget_status()["committed"]["total"]
    nodes = {h["id"] for h in db.find("hypothesis") if str(h.get("title", "")).startswith(("Zebra", "Yak"))}
    request = max(e["nodes"] * e["walltime_s"] for e in db.find("experiment")
                  if e.get("hypothesis_id") in nodes and e["kind"] == "method")
    limit = committed + request + request // 2
    set_total(yaml_path, str(limit))
    print(json.dumps({"committed": committed, "request": request, "total_limit": limit}))
elif sys.argv[1] == "lift":
    set_total(Path(sys.argv[2]), "null")
elif sys.argv[1] == "arm":
    Path(sys.argv[2]).write_text(json.dumps({"faults": [{"id": f"F-{sys.argv[3]}", "window": sys.argv[3],
                                                          "key_glob": "*", "times": 1}]}))
elif sys.argv[1] == "disarm":
    Path(sys.argv[2]).write_text(json.dumps({"faults": []}))
