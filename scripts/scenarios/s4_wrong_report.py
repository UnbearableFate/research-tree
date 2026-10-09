#!/usr/bin/env python3
"""F-S4-01 (run_s4.sh): a summary of Zebra's current evaluation whose numbers contradict the metrics files — the mean
raised by 5 points and every per-seed accuracy changed — written as docs/reports/zebra-summary-draft.md. The metrics,
the manifests and the registered result document are not touched. Records what it wrote in <ctl>/fault-applied.json.

    s4_wrong_report.py <ctl> <project> <plugin tools dir>
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
zebra = next(h for h in db.find("hypothesis") if str(h.get("title", "")).startswith("Zebra"))
exp = next(e for e in db.find("experiment") if e.get("hypothesis_id") == zebra["id"] and e["kind"] == "method"
           and e.get("evaluation_id"))
ev = db.get(exp["evaluation_id"])
true_mean = ev["metrics"]["accuracy"]["mean"]
runs = [db.get(f"{exp['id']}/s{s}") for s in exp["seeds"]]
lines = [f"# Zebra 结果摘要（草稿）\n", f"实验 {exp['id']}，evaluation {ev['id']}。\n",
         f"- 平均 accuracy：{true_mean + 5.0:.2f}（百分点）", "- 各 seed："]
true = {}
for r in runs:
    true[r["seed"]] = r["metric_value"]
    lines.append(f"  - seed {r['seed']}：{r['metric_value'] + 0.05:.4f}")
lines.append("\n结论：Zebra 相对参考方法有大幅提升。\n")
(root / "docs" / "reports").mkdir(parents=True, exist_ok=True)
target = root / "docs" / "reports" / "zebra-summary-draft.md"
target.write_text("\n".join(lines), encoding="utf-8")
record = {"file": str(target), "evaluation": ev["id"], "true_mean": true_mean, "written_mean": true_mean + 5.0,
          "true_per_seed": true, "written_per_seed": {k: v + 0.05 for k, v in true.items()}}
(ctl / "fault-applied.json").write_text(json.dumps(record, indent=1))
print(json.dumps(record))
