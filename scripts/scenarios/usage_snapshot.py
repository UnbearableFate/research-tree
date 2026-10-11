#!/usr/bin/env python3
"""usage_snapshot.py <project> <plugin-tools> <out.json> — read-only: the material-usage record and the candidate
specs / confirmation batches (a scenario checkpoint beside observe.py's)."""
import json
import sys
from pathlib import Path

sys.path.insert(0, sys.argv[2])
from research_db import ResearchDB  # noqa: E402
from research_tree import read_marker  # noqa: E402

marker = read_marker(Path(sys.argv[1]).resolve())
db = ResearchDB(marker["db"], "ui/ui")
json.dump({"material_usage": db.material_usage(), "documents": [d for d in db.export_snapshot()["tables"]["document"]
           if d.get("doc_type") in ("candidate_spec", "confirmation_batch")]},
          open(sys.argv[3], "w"), ensure_ascii=False, default=str)
