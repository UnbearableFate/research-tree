#!/usr/bin/env python3
"""usage_snapshot.py <project> <plugin-tools> <out.json> — read-only: the material-usage record and the candidate
specs / confirmation batches (a scenario checkpoint beside observe.py's)."""
import glob
import json
import sys

sys.path.insert(0, sys.argv[2])
from research_db import ResearchDB  # noqa: E402

db = ResearchDB(glob.glob(f"{sys.argv[1]}/research/*/research_tree.db")[0], "ui/ui")
json.dump({"material_usage": db.material_usage(), "documents": [d for d in db.export_snapshot()["tables"]["document"]
           if d.get("doc_type") in ("candidate_spec", "confirmation_batch")]},
          open(sys.argv[3], "w"), ensure_ascii=False, default=str)
