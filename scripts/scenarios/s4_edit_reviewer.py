#!/usr/bin/env python3
"""F-S4-03a (run_s4.sh): the fictional user's edit of models.reviewer.model in research-tree.yaml.

    s4_edit_reviewer.py <research-tree.yaml> same-family|restore <host>

same-family: the reviewer becomes a model of the Leader's own family (Claude host: anthropic/claude-haiku-5-5; Codex
host: openai/gpt-6-luna); the original line is kept beside the file (.reviewer-orig). restore: puts it back.
"""
import re
import sys
from pathlib import Path

path, what, host = Path(sys.argv[1]), sys.argv[2], sys.argv[3]
orig = path.with_name(path.name + ".reviewer-orig")
text = path.read_text(encoding="utf-8")
m = re.search(r"(\n  reviewer:\n    model: )(\S+)", text)
if m is None:
    raise SystemExit("no models.reviewer.model in the configuration")
if what == "same-family":
    orig.write_text(m.group(2), encoding="utf-8")
    same = "anthropic/claude-haiku-5-5" if host == "claude" else "openai/gpt-6-luna"
    path.write_text(text[:m.start(2)] + same + text[m.end(2):], encoding="utf-8")
else:
    path.write_text(text[:m.start(2)] + orig.read_text(encoding="utf-8").strip() + text[m.end(2):], encoding="utf-8")
    orig.unlink()
