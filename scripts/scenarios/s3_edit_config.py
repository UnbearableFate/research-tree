#!/usr/bin/env python3
"""The fictional user's edits of research-tree.yaml in the S3 scenario (s3.sh via scenario.sh), one named edit at a time.

    s3_edit_config.py <research-tree.yaml> input-mib | canonical-mib | primary-fraction

input-mib: model_bytes input_unit bytes -> mib. canonical-mib: model_bytes input_unit back to bytes, canonical_unit
bytes -> mib, allowed_regression 1024 (bytes) -> 0.0009765625 (MiB, the same bound). primary-fraction: accuracy
canonical_unit percentage_point -> fraction. Only the named block's own lines change.
"""
import sys
from pathlib import Path


def block(text: str, name: str) -> tuple[int, int]:
    start = text.index(f"- name: {name}")
    nxt = text.find("\n          - name:", start + 1)
    end = text.find("\n\n", start)
    stops = [x for x in (nxt, end) if x != -1]
    return start, min(stops) if stops else len(text)


def edit(path: Path, what: str) -> None:
    text = path.read_text(encoding="utf-8")
    name = "accuracy" if what == "primary-fraction" else "model_bytes"
    a, b = block(text, name)
    seg = text[a:b]
    changes = {"input-mib": [("input_unit: bytes", "input_unit: mib")],
               "canonical-mib": [("input_unit: mib", "input_unit: bytes"), ("canonical_unit: bytes", "canonical_unit: mib"),
                                 ("allowed_regression: 1024", "allowed_regression: 0.0009765625")],
               "primary-fraction": [("canonical_unit: percentage_point", "canonical_unit: fraction")]}[what]
    for old, new in changes:
        if old not in seg:
            raise SystemExit(f"{old!r} not in the {name} block")
        seg = seg.replace(old, new, 1)
    path.write_text(text[:a] + seg + text[b:], encoding="utf-8")


if __name__ == "__main__":
    edit(Path(sys.argv[1]), sys.argv[2])
