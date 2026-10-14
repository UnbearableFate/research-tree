"""Numbers in documents against the files they cite (plans/design/05 §2.4).

Ported from ARIS tools/evidence_check.py (Auto-claude-code-research-in-sleep @ 3b19a22): a claim is
(claim_id, value, source_path); it is verified when the value appears, as an exact decimal, in the cited file.
Statuses: verified / value_not_found / path_missing / unparseable. `verified` means only that the cited evidence
exists, not that it supports the claim; a value that is part of a compound construct (date, version, fraction,
locale grouping, a Unicode minus) fails closed. Nothing here calls a model.

Result and report documents carry their claims in one fenced block:

    ```evidence
    [{"id": "acc-s42", "value": "0.9075", "source": "outputs/E-0002/s42/metrics.json"}]
    ```

Sources are relative to the research root (research/<id>/) or absolute inside the project directory; globs are
allowed, and every matching file is searched.
"""

from __future__ import annotations

import json
import re
from decimal import Decimal, InvalidOperation
from pathlib import Path

_NUM_CORE = r"[+-]?(?:\d{1,3}(?:,\d{3})+(?:\.\d+)?|\d+(?:\.\d*)?|\.\d+)(?:[eE][+-]?\d+)?"
_BEFORE_OK = r"\s=(\[{\x22:"  # ':' only after a JSON key's closing quote (checked below), not in 12:30
_AFTER_OK = r"\s)\]}\x22;,."
_NUM_TOKEN_RE = re.compile(
    r"(?<![^" + _BEFORE_OK + r"])"
    r"(" + _NUM_CORE + r")(%?)"
    r"(?=[" + _AFTER_OK + r"]|$)"
    r"(?![.,]\d)"
)
_WS_GROUP_TAIL = re.compile(r"\d\s+$")
_WS_GROUP_LEAD = re.compile(r"\s+\d{3}(?!\d)")
_GROUP_TAIL_TOK = re.compile(r"\d{3}(?:\.\d+)?")
_PURE_NUMBER_RE = re.compile(_NUM_CORE)
BLOCK_RE = re.compile(r"^```evidence[ \t]*\n(.*?)^```[ \t]*$", re.M | re.S)
BAD = ("path_missing", "value_not_found", "unparseable")
MAX_GLOB_FILES = 20  # a glob source covers a few runs' files, not a directory tree


def _dec(s: str) -> Decimal:
    return Decimal(s.replace(",", "").strip())


def _pure_number(s: str):
    v = s.strip()
    has_pct = v.endswith("%")
    core = v[:-1].strip() if has_pct else v
    if not _PURE_NUMBER_RE.fullmatch(core):
        return None
    try:
        return _dec(core), has_pct
    except InvalidOperation:
        return None


def value_in_text(value: str, text: str) -> bool:
    """True if `value` is present in `text`, never a false positive: a pure number by exact decimal equality
    against safely bounded number tokens (percent flag consistent), anything else as a whitespace-normalised
    substring. An empty value never matches."""
    if not value.strip():
        return False
    pn = _pure_number(value)
    if pn is not None:
        dval, want_pct = pn
        for m in _NUM_TOKEN_RE.finditer(text):
            tok = m.group(1)
            if _GROUP_TAIL_TOK.fullmatch(tok) and _WS_GROUP_TAIL.search(text[:m.start()]):
                continue
            if m.start() > 0 and text[m.start() - 1] == ":" and not text[:m.start() - 1].endswith('"'):
                continue  # 12:30, 1:2 — a ':' counts only in compact JSON ("acc":0.9)
            if _WS_GROUP_LEAD.match(text[m.end():]):
                continue
            try:
                tnum = _dec(tok)
            except InvalidOperation:
                continue
            if tnum == dval and bool(m.group(2)) == want_pct:
                return True
        return False
    norm = re.sub(r"\s+", " ", text)
    return value.strip() in norm


def _resolve(source: str, root: Path, allowed: Path, forbidden: Path | None = None) -> list[Path]:
    base = Path(source) if Path(source).is_absolute() else root / source
    if ".." in Path(source).parts:
        return []
    if base.is_file():
        files = [base]
    elif "**" in source:  # a source names files, not the whole tree
        files = []
    else:
        rel = source if not Path(source).is_absolute() else None
        files = sorted(p for p in root.glob(rel) if p.is_file())[:MAX_GLOB_FILES + 1] if rel else []
        if len(files) > MAX_GLOB_FILES:
            files = []
    files = [f for f in files if f.resolve().is_relative_to(allowed.resolve())]
    if forbidden is not None:  # a document is not the source of its own numbers
        files = [f for f in files if not f.resolve().is_relative_to(forbidden.resolve())]
    return files


def resolve_source(source: str, root: Path, allowed: Path | None = None, forbidden: Path | None = None) -> list[Path]:
    """The files a claim's source names, as check_claim reads them (a glob covers every matching file)."""
    return _resolve(source, Path(root), Path(allowed or root), forbidden)


def check_claim(value: str, source: str, root: Path, allowed: Path | None = None,
                forbidden: Path | None = None) -> dict:
    """status in verified / path_missing / value_not_found; `allowed` bounds where sources may lie and nothing under
    `forbidden` (the document library) counts as a source."""
    files = _resolve(source, Path(root), Path(allowed or root), forbidden)
    if not files:
        return {"status": "path_missing", "value": value, "source": source,
                "detail": f"no file matches {source!r} under {root}"}
    read_any = False
    for f in files:
        try:
            text = f.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        read_any = True
        if value_in_text(value, text):
            return {"status": "verified", "value": value, "source": str(f), "detail": f"{value!r} found in {f}"}
    if not read_any:
        return {"status": "path_missing", "value": value, "source": source,
                "detail": f"file(s) matching {source!r} exist but are unreadable"}
    return {"status": "value_not_found", "value": value, "source": source,
            "detail": f"{value!r} not found in {source!r} ({len(files)} file(s) checked)"}


def check_batch(claims: list, root: Path, allowed: Path | None = None, forbidden: Path | None = None) -> dict:
    """claims: [{"id", "value", "source"}]; per-claim results and a summary. A numeric 0 is checkable; an empty
    value or source is unparseable."""
    results = []
    for c in claims:
        if not isinstance(c, dict):
            results.append({"claim": c, "status": "unparseable", "detail": "a claim is an object"})
            continue
        value, source = c.get("value"), c.get("source")
        if value is None or source is None or str(value).strip() == "" or str(source).strip() == "":
            results.append({**c, "status": "unparseable", "detail": "claim has no usable (value, source)"})
        else:
            results.append({**c, **check_claim(str(value), str(source), root, allowed, forbidden)})
    counts: dict = {}
    for r in results:
        counts[r["status"]] = counts.get(r["status"], 0) + 1
    return {"results": results, "summary": counts}


def document_claims(text: str) -> list | None:
    """The claims of a document's ```evidence block; None when the document has none. A malformed block gives
    one unparseable pseudo-claim so that it is refused, not skipped."""
    blocks = BLOCK_RE.findall(text)
    if not blocks:
        return None
    claims = []
    for block in blocks:
        try:
            value = json.loads(block)
        except json.JSONDecodeError as exc:
            return [{"id": "evidence-block", "value": None, "source": None, "error": f"not JSON: {exc}"}]
        if not isinstance(value, list):
            return [{"id": "evidence-block", "value": None, "source": None, "error": "the block is a JSON list"}]
        claims += value
    return claims
