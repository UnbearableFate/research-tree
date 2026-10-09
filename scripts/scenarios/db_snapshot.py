#!/usr/bin/env python3
"""db_snapshot.py <project> <plugin-tools> <out.json> — read-only: the research database's export snapshot."""
import glob
import json
import sys

sys.path.insert(0, sys.argv[2])
from research_db import ResearchDB  # noqa: E402

db = ResearchDB(glob.glob(f"{sys.argv[1]}/research/*/research_tree.db")[0], "ui/ui")
json.dump(db.export_snapshot(), open(sys.argv[3], "w"), ensure_ascii=False, default=str)
