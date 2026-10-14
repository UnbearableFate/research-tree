"""Continuous incremental discovery with independently admitted, identity-bound candidates.

The Leader may confirm minimal scope while exploration continues. Candidate readiness never grants user
permission, a global discovery PASS, experiment execution, or final research GO. Proposal sources provide advice;
selection and the scientific validity/budget/evidence gates remain separate.
"""

from __future__ import annotations

import fcntl
import json
import os
import re
import tempfile
import unicodedata
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path

DISCOVERY_VERSION = 2
STATE_PATH = Path("cache") / "discovery" / "state.json"
CANDIDATES_PATH = Path("docs") / "project" / "discovery" / "candidates.json"


class DiscoveryError(Exception):
    pass


def now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


# -- state ---------------------------------------------------------------------------------------------------------


@contextmanager
def _locked(root: Path):
    path = root / STATE_PATH
    path.parent.mkdir(parents=True, exist_ok=True)
    with (path.parent / ".lock").open("w") as handle:
        fcntl.flock(handle, fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(handle, fcntl.LOCK_UN)


def load(root: Path) -> dict | None:
    path = root / STATE_PATH
    if not path.is_file():
        return None
    state = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(state, dict) or state.get("version") != DISCOVERY_VERSION or any(
            key in state for key in ("mode", "stages", "gate")):
        raise DiscoveryError("UNSUPPORTED_DISCOVERY_VERSION: sequential or unversioned discovery is no longer "
                             "supported. Preserve the old project and start a new version-3 project.")
    return state


def _save(root: Path, state: dict) -> None:
    path = root / STATE_PATH
    state["updated"] = now()
    fd, tmp = tempfile.mkstemp(dir=str(path.parent), prefix=".state.", suffix=".tmp")
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        json.dump(state, f, ensure_ascii=False, indent=1)
    os.replace(tmp, path)


def start(root: Path, executor_model: str | None = None) -> dict:
    """Start continuous discovery; resuming never rewrites existing candidate or evidence history."""
    # Inspect before creating directories/locks so a rejected old state is unchanged.
    state = load(root)
    read_candidates(root)
    if state is not None:
        return state
    with _locked(root):
        state = load(root)
        if state is None:
            state = {"version": DISCOVERY_VERSION, "executor_model": executor_model, "created": now()}
            _save(root, state)
        return state


def _require(root: Path) -> dict:
    state = load(root)
    if state is None:
        raise DiscoveryError("no discovery run: start it first (discovery start)")
    return state


# -- candidates ----------------------------------------------------------------------------------------------------


# Han and kana are written without spaces: a run of them is one word whatever spaces or punctuation fall inside it,
# and a word of its own next to Latin letters or digits ('LoRA 秩自适应' and 'LoRA秩自适应' are one idea).
_SPACELESS = "\u3005-\u3007\u3040-\u30ff\u31f0-\u31ff\u3400-\u4dbf\u4e00-\u9fff\uf900-\ufaff\U00020000-\U0003ffff"
_WORD_RE = re.compile(rf"[{_SPACELESS}](?:\W*[{_SPACELESS}])*|[^\W{_SPACELESS}]+")


def dedup_key(text: str) -> str:
    """A mechanical key: lower case, accents and punctuation removed, words joined by '-'.

    Letters without an ASCII form (CJK, Greek, ...) stay in the key, so 'LoRA 秩自适应' and 'LoRA 低秩初始化' remain
    two ideas; a pure-ASCII title keeps the key it always had."""
    t = "".join(unicodedata.normalize("NFD", ch).encode("ascii", "ignore").decode() or ch
                for ch in unicodedata.normalize("NFKC", text))
    return "-".join(re.sub(r"\W", "", w) for w in _WORD_RE.findall(t.lower()))[:120]


def _ascii_key(text: str) -> str:
    """The key before non-ASCII words were kept (it dropped them: 'LoRA 秩自适应' was 'lora'). Stored keys computed
    this way are matched again under their title's current key, so such a candidate keeps its id and selection."""
    t = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode() or text
    return "-".join(re.findall(r"\w+", t.lower()))[:120]


# What a candidate says (its content revision is over these); bookkeeping (found_by, selected, literature, ranks,
# feasibility notes) is not content.
CONTENT_FIELDS = ("title", "summary", "mechanism", "method", "claim", "statement", "closest_work", "hypothesis",
                  "prediction", "estimated_run", "intervention", "comparator", "resource_ceiling", "stop_conditions")


# Set only by merge, `discovery feasibility` and the Leader's `discovery select`: a proposal source gives advice, so
# a proposal that asserts any of these (selected, feasible, an identity or revision) has it ignored.
SYSTEM_FIELDS = ("id", "candidate_id", "origin", "found_by", "selected", "feasible", "feasibility_reasons",
                 "revision", "content_sha", "revisions", "present")


def content_sha(candidate: dict) -> str:
    import hashlib
    content = {k: candidate[k] for k in CONTENT_FIELDS if candidate.get(k) not in (None, "")}
    return hashlib.sha256(json.dumps(content, sort_keys=True, ensure_ascii=False).encode("utf-8")).hexdigest()


def merge(proposals: list[dict], user_hypotheses: list[dict], existing: list[dict] | None = None) -> list[dict]:
    """Merge read-only advisor proposals ({source, candidates}) with user hypotheses.

    Stable IDs survive reordered proposals. Scientific content changes advance a revision and invalidate old
    receipts. Missing candidates remain historical and unselected; weak candidates are never erased by ranking.
    """
    existing = [dict(c) for c in existing or []]
    by_id = {c["id"]: c for c in existing if c.get("id")}
    by_key = {(c.get("origin"), c.get("dedup_key")): c for c in existing if c.get("id")}
    for c in existing:  # a key stored by the older rule is found again under its title's current key
        if c.get("id") and isinstance(c.get("title"), str) and c.get("dedup_key") == _ascii_key(c["title"]):
            by_key.setdefault((c.get("origin"), dedup_key(c["title"])), c)
    numbers = [int(m.group(1)) for i in by_id if (m := re.fullmatch(r"CAND-(\d+)", i))]
    pool: dict[str, dict] = {}
    for h in user_hypotheses:
        key = h.get("dedup_key") or dedup_key(h["title"])
        # Preserve user-origin ideas; readiness still checks their exact current content.
        pool[key] = {**h, "dedup_key": key, "origin": "user", "found_by": ["user"], "selected": True}
    for proposal in proposals:
        source = proposal.get("source")
        if not isinstance(source, str) or not source.strip() or set(proposal) - {"source", "candidates"}:
            raise DiscoveryError("a proposal needs {source, candidates}; legacy lens shards are unsupported")
        if not isinstance(proposal.get("candidates"), list):
            raise DiscoveryError("a proposal's candidates must be a list")
        for c in proposal["candidates"]:
            if not (c.get("title") or "").strip():
                raise DiscoveryError(f"a candidate from {source} has no title")
            c = {k: v for k, v in c.items() if k not in SYSTEM_FIELDS}
            key = c.get("dedup_key") or dedup_key(c["title"])
            if key in pool:
                pool[key]["found_by"] = sorted(set(pool[key]["found_by"]) | {source})
                pool[key]["literature"] = sorted(set(pool[key].get("literature") or []) | set(c.get("literature") or []))
                for field, value in c.items():
                    pool[key].setdefault(field, value)
            else:
                pool[key] = {**c, "dedup_key": key, "origin": "explorer", "found_by": [source]}
    out, used = [], set()
    for c in pool.values():
        explicit = c.get("candidate_id") or (c.get("id") if CANDIDATE_RE.fullmatch(str(c.get("id") or "")) else None)
        old = by_id.get(explicit) if explicit else by_key.get((c["origin"], c["dedup_key"]))
        if explicit and old is None:
            raise DiscoveryError(f"{explicit} is not an existing candidate; a new idea gets a new id")
        if old is not None and old["id"] in used:
            old = None
        sha = content_sha(c)
        c = {k: v for k, v in c.items() if k not in ("candidate_id",)}
        if old is not None:
            revisions = list(old.get("revisions") or [{"revision": old.get("revision") or 1,
                                                       "content_sha": old.get("content_sha") or content_sha(old)}])
            revision = revisions[-1]["revision"]
            if revisions[-1]["content_sha"] != sha:
                revision += 1
                revisions.append({"revision": revision, "content_sha": sha, "at": now()})
            c.update(id=old["id"], revision=revision, content_sha=sha, revisions=revisions)
            cited = sorted(set(old.get("literature") or []) | set(c.get("literature") or []))
            if cited:
                c["literature"] = cited
            for key in ("selected", "feasible", "feasibility_reasons"):  # later stages' marks, for
                if revision == old.get("revision") and key in old and key not in c:  # unchanged content only
                    c[key] = old[key]
        else:
            n = max(numbers, default=0) + 1
            numbers.append(n)
            c.update(id=f"CAND-{n:04d}", revision=1, content_sha=sha,
                     revisions=[{"revision": 1, "content_sha": sha, "at": now()}])
        c["present"] = True
        used.add(c["id"])
        out.append(c)
    for old in existing:  # earlier candidates no longer in the inputs: history, never renumbered or selected
        if old.get("id") and old["id"] not in used:
            out.append({**old, "present": False, "selected": False})
    return sorted(out, key=lambda c: (not c.get("present", True), c["origin"] != "user", c["dedup_key"]))


CANDIDATE_RE = re.compile(r"CAND-\d{4,}")


def feasibility(candidates: list[dict], max_nodes: int, max_walltime_s: int, screen_node_h: float) -> list[dict]:
    """R13: only budget facts eliminate — a screening run that cannot fit one run's cap, or one seed that costs
    more than the screening budget. Everything else is a note. A user hypothesis is annotated, never removed."""
    out = []
    for c in candidates:
        run = c.get("estimated_run") or {}
        nodes, walltime = run.get("nodes"), run.get("walltime_s")
        reasons = []
        if not isinstance(nodes, int) or not isinstance(walltime, int):
            reasons.append("no estimated_run {nodes, walltime_s}: feasibility unknown")
            feasible = None
        else:
            if nodes > max_nodes or walltime > max_walltime_s:
                reasons.append(f"a screening run needs {nodes} nodes x {walltime} s, over the per-run cap "
                               f"{max_nodes} x {max_walltime_s} s")
            if nodes * walltime / 3600 > screen_node_h:
                reasons.append(f"one seed costs {nodes * walltime / 3600:.2f} node-h, over the screening budget "
                               f"{screen_node_h}")
            feasible = not reasons
        c = {**c, "feasible": feasible, "feasibility_reasons": reasons}
        if c["origin"] == "user" and feasible is False:
            c["feasibility_reasons"] = reasons + ["user hypothesis: kept for the user to decide"]
        out.append(c)
    return out


def select_candidate(root: Path, candidate_id: str) -> dict:
    """Select one incremental candidate without changing another candidate's selection or requiring triage.

    Selection is research prioritization, not a PASS receipt: admission rechecks current content and scope.
    """
    with _locked(root):
        _require(root)
        candidates = read_candidates(root)
        candidate = next((c for c in candidates if c.get("id") == candidate_id), None)
        if candidate is None or candidate.get("present") is False:
            raise DiscoveryError(f"{candidate_id} is not a current discovery candidate")
        candidate["selected"] = True
        write_candidates(root, candidates)
        return candidate


def cite(root: Path, candidate_id: str, literature: list[str]) -> dict:
    """Attach traceable literature documents without imposing a batch literature quota."""
    candidates = read_candidates(root)
    found = next((c for c in candidates if c["id"] == candidate_id), None)
    if found is None:
        raise DiscoveryError(f"no candidate {candidate_id} in {CANDIDATES_PATH}")
    found["literature"] = sorted(set(found.get("literature") or []) | set(literature))
    write_candidates(root, candidates)
    return found


def write_candidates(root: Path, candidates: list[dict]) -> str:
    load(root)
    read_candidates(root)
    path = root / CANDIDATES_PATH
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=str(path.parent), prefix=".candidates.", suffix=".tmp")
    with os.fdopen(fd, "w", encoding="utf-8") as handle:
        json.dump({"version": DISCOVERY_VERSION, "updated": now(), "candidates": candidates}, handle, ensure_ascii=False, indent=1)
        handle.write("\n")
    os.replace(tmp, path)
    return str(CANDIDATES_PATH)


def read_candidates(root: Path) -> list[dict]:
    path = root / CANDIDATES_PATH
    if not path.is_file():
        return []
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict) or value.get("version") != DISCOVERY_VERSION:
        raise DiscoveryError("UNSUPPORTED_DISCOVERY_VERSION: old candidate pools are preserved, never imported "
                             "implicitly; start a new version-3 project")
    candidates = value.get("candidates")
    if not isinstance(candidates, list) or any(not isinstance(c, dict) for c in candidates):
        raise DiscoveryError("candidate pool needs a candidates list of objects")
    return candidates


def read_proposals(root: Path) -> list[dict]:
    return [json.loads(p.read_text(encoding="utf-8"))
            for p in sorted((root / "cache" / "discovery" / "proposals").glob("*.json"))]


# -- the gate ------------------------------------------------------------------------------------------------------


def _has_description(value) -> bool:
    """Accept prose or structured descriptions, never an empty placeholder/bool/number alone."""
    if isinstance(value, str):
        return bool(value.strip())
    if isinstance(value, dict):
        return any(_has_description(v) for v in value.values())
    if isinstance(value, list):
        return bool(value) and all(_has_description(v) for v in value)
    return False


def evaluate_candidate(root: Path, candidate_id: str, *, max_nodes: int | None = None,
                       max_walltime_s: int | None = None, screen_node_h: float | None = None) -> dict:
    """Read-only readiness for one current selected candidate under its declared resource ceiling.

    Admission requires prediction, intervention, matched comparator, resource ceiling and stop/continue
    conditions. Independent final reviews and actual experiment/evidence checks remain separate.
    """
    load(root)  # reject an older discovery state even if its candidate file was manually replaced
    candidate = next((c for c in read_candidates(root) if c.get("id") == candidate_id), None)
    result = {"verdict": "BLOCKED", "reasons": [], "candidate_id": candidate_id,
              "revision": candidate.get("revision") if candidate else None,
              "content_sha": candidate.get("content_sha") if candidate else None}
    reasons = result["reasons"]
    if candidate is None or candidate.get("present") is False:
        reasons.append(f"{candidate_id} is not a current discovery candidate")
        return result
    if not candidate.get("selected"):
        reasons.append(f"{candidate_id} is not selected (discovery select --candidate {candidate_id})")
    if type(candidate.get("revision")) is not int or candidate["revision"] <= 0:
        reasons.append(f"{candidate_id}: no valid content revision; merge again to record its identity")
    if not candidate.get("content_sha") or candidate["content_sha"] != content_sha(candidate):
        reasons.append(f"{candidate_id}: content changed outside discovery merge; merge again to record its revision")
    for field in ("prediction", "intervention", "comparator", "stop_conditions"):
        if not _has_description(candidate.get(field)):
            reasons.append(f"{candidate_id}: screening needs {field}")
    ceiling = candidate.get("resource_ceiling")
    nodes = ceiling.get("nodes") if isinstance(ceiling, dict) else None
    walltime = ceiling.get("walltime_s") if isinstance(ceiling, dict) else None
    if type(nodes) is not int or type(walltime) is not int or nodes <= 0 or walltime <= 0:
        reasons.append(f"{candidate_id}: resource_ceiling needs positive integer nodes and walltime_s")
    else:
        if max_nodes is not None and nodes > max_nodes:
            reasons.append(f"{candidate_id}: resource_ceiling nodes {nodes} exceeds per-run cap {max_nodes}")
        if max_walltime_s is not None and walltime > max_walltime_s:
            reasons.append(f"{candidate_id}: resource_ceiling walltime_s {walltime} exceeds per-run cap {max_walltime_s}")
        if screen_node_h is not None and nodes * walltime / 3600 > screen_node_h:
            reasons.append(f"{candidate_id}: resource_ceiling exceeds screening budget {screen_node_h} node-h")
    result["verdict"] = "BLOCKED" if reasons else "PASS"
    return result
