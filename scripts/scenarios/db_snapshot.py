#!/usr/bin/env python3
"""db_snapshot.py <project> <plugin-tools> <out.json> — read-only: the research database's export snapshot."""
import json
import sys
from pathlib import Path

sys.path.insert(0, sys.argv[2])
from research_db import ResearchDB  # noqa: E402
from research_tree import read_marker  # noqa: E402

marker = read_marker(Path(sys.argv[1]).resolve())
db = ResearchDB(marker["db"], "ui/ui")
json.dump(db.export_snapshot(), open(sys.argv[3], "w"), ensure_ascii=False, default=str)
