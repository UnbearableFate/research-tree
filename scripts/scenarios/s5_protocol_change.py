#!/usr/bin/env python3
"""F-S5-03 (run_s5.sh): the fictional user's protocol change in research-tree.yaml —
verification.max_confirmation_candidates 2 -> 1 (the protocol document changes; the harness and the runs do not).

    s5_protocol_change.py <research-tree.yaml>
"""
import sys
from pathlib import Path

path = Path(sys.argv[1])
text = path.read_text(encoding="utf-8")
i = text.index("\nverification:")
j = text.index("max_confirmation_candidates: 2", i)
path.write_text(text[:j] + "max_confirmation_candidates: 1" + text[j + len("max_confirmation_candidates: 2"):], encoding="utf-8")
