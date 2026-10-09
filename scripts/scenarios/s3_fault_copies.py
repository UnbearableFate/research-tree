#!/usr/bin/env python3
"""F-S3-02 (s3.sh via scenario.sh): copies of a real, succeeded but not yet imported run's manifest with a declared field taken
out, written to <research root>/fault-injection/. The original stays untouched; the copies point at the same
artifacts. Records what it made in <ctl>/fault-applied.json.

    s3_fault_copies.py <ctl> <project> <plugin tools dir>
"""
import glob
import json
import sys
from pathlib import Path

ctl, project, tools = Path(sys.argv[1]), Path(sys.argv[2]), sys.argv[3]
sys.path.insert(0, tools)
from research_db import ResearchDB  # noqa: E402

db = ResearchDB(glob.glob(f"{project}/research/*/research_tree.db")[0], "ui/ui")
root = db.db_path.parent
record = {"copies": []}
for run in db.find("run"):
    if run["exec_status"] != "succeeded" or run.get("import_record"):
        continue
    exp = db.get(run["experiment_id"])
    if (exp.get("effective_config") or {}).get("lr") != 0.01:
        continue
    for manifest in sorted(set(project.glob("**/run_manifest.json"))):
        try:
            data = json.loads(manifest.read_text())
        except json.JSONDecodeError:
            continue
        if data.get("experiment_id") != exp["id"] or data.get("seed") != run["seed"]:
            continue
        out = root / "fault-injection"
        out.mkdir(exist_ok=True)
        for name, drop in (("no-train-seed", "train_seed"), ("no-units", "units")):
            copy = {k: v for k, v in data.items() if k != drop}
            for key in ("metrics_path", "curve_path", "log_path", "output_path"):
                if copy.get(key) and not Path(copy[key]).is_absolute():
                    copy[key] = str((manifest.parent / copy[key]).resolve())
            copy["evidence_paths"] = [str((manifest.parent / p).resolve()) for p in data.get("evidence_paths", [])]
            target = out / f"{run['id'].replace('/', '-')}-{name}.json"
            target.write_text(json.dumps(copy, indent=1))
            record["copies"].append({"run": run["id"], "original": str(manifest), "copy": str(target), "dropped": drop})
        break
(ctl / "fault-applied.json").write_text(json.dumps(record, indent=1))
print(json.dumps(record))
