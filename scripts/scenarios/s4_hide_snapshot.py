#!/usr/bin/env python3
"""F-S4-04 (s4.sh via scenario.sh): the code snapshot a method_code review reads (cache/reviews/code/<commit>/) holds another
version of the method's code: the snapshot is prepared from Zebra's commit and toytrain/methods.py in it is altered,
so a reviewer that reads and cites it cites a file that is not the reviewed commit's. `restore` removes the prepared
snapshot, so the next review extracts the real one. Records in <ctl>/snapshot-fault.json.

    s4_hide_snapshot.py hide|restore <ctl> <project> <plugin tools dir>
"""
import json
import shutil
import subprocess
import sys
from pathlib import Path

what, ctl, project = sys.argv[1], Path(sys.argv[2]), Path(sys.argv[3])
marker = json.loads((project / ".research-tree.json").read_text())
root = Path(marker["root"])
record_path = ctl / "snapshot-fault.json"
if what == "restore":
    record = json.loads(record_path.read_text())
    target = Path(record["snapshot"])
    for p in target.rglob("*"):
        p.chmod(0o755 if p.is_dir() else 0o644)
    shutil.rmtree(target)
    record["restored"] = True
    record_path.write_text(json.dumps(record, indent=1))
    raise SystemExit(0)
sys.path.insert(0, sys.argv[4])
from research_db import ResearchDB  # noqa: E402

db = ResearchDB(marker["db"], "ui/ui")
zebra = next(h for h in db.find("hypothesis") if str(h.get("title", "")).startswith("Zebra"))
exp = next(e for e in db.find("experiment") if e.get("hypothesis_id") == zebra["id"] and e["kind"] == "method")
repo, commit = db.find("project")[0]["repo_path"], exp["code_ref"]
target = root / "cache" / "reviews" / "code" / commit
if target.exists():
    for p in target.rglob("*"):
        p.chmod(0o755 if p.is_dir() else 0o644)
    shutil.rmtree(target)
target.mkdir(parents=True)
archive = subprocess.run(["git", "-C", repo, "archive", commit], capture_output=True, check=True).stdout
subprocess.run(["tar", "-x", "-C", str(target)], input=archive, check=True)
methods = target / "toytrain" / "methods.py"
methods.write_text(methods.read_text() + "\n\n# altered by the S4 controller: this file is not the reviewed commit's\n"
                   "def _unreviewed_change():\n    return None\n")
(target / ".complete").write_text(commit + "\n")
record = {"snapshot": str(target), "commit": commit, "altered": "toytrain/methods.py"}
record_path.write_text(json.dumps(record, indent=1))
print(json.dumps(record))
