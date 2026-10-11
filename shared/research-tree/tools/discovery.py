"""Resumable discovery and deterministic candidate readiness. Nothing here calls a model.

Full/precheck retain the original whole-batch gate. Incremental discovery continues alongside the shared
framework after the user confirms the initial scope; each selected candidate is checked independently.
Candidate readiness never grants scope authorization or replaces experiment/evidence admission checks.

Stage state is ported from ARIS tools/run_state.py and the gate from tools/idea_discovery_gate.py
(Auto-claude-code-research-in-sleep @ 3b19a22), adapted: a stage is `done` when the Leader finished it and
`accepted` only on evidence it cannot write itself — a current review document by another model family
(review stages) or a deterministic check (literature verification, feasibility). Resume returns the first stage
that is not terminal, so a stage the Leader called done but no reviewer accepted is redone, never skipped
("a loop can DRIVE, it cannot ACQUIT").

State: research/<id>/cache/discovery/state.json. Candidates: docs/project/discovery/candidates.json (merged from
the lens shards in cache/discovery/shards/*.json). User hypotheses enter as candidates with origin "user": they
are annotated, never eliminated by the feasibility gate or the triage ranking (02 §3).
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

import review_rules

STAGES = ("brief", "literature", "candidates", "feasibility", "triage", "novelty", "critique", "refine", "gate")
SKIPPED_BY_MODE = {"full": (), "precheck": ("candidates", "feasibility", "triage"), "incremental": ()}
REVIEW_STAGES = {"triage": "triage", "novelty": "novelty_precheck", "critique": "critical_review"}
DETERMINISTIC_STAGES = ("literature", "feasibility")
TERMINAL = ("accepted", "skipped")
EXECUTOR_STATUSES = ("pending", "running", "done", "failed")
REPORT_SECTIONS = ("用户假说", "新发现候选", "淘汰想法")
STATE_PATH = Path("cache") / "discovery" / "state.json"
CANDIDATES_PATH = Path("docs") / "project" / "discovery" / "candidates.json"
# What a finished stage's --artifact usually is (the gate needs one for every stage but brief)
ARTIFACT_HINTS = {"literature": "docs/project/discovery/literature.md (the documents and their verification)",
                  "candidates": "docs/project/discovery/candidates.json",
                  "feasibility": "docs/project/discovery/candidates.json",
                  "triage": "docs/project/discovery/triage.md (the triage review id and the selection)",
                  "novelty": "docs/project/discovery/novelty-reviews.md (one line per candidate: review id, verdict)",
                  "critique": "docs/project/discovery/critical-reviews.md (one line per candidate: review id, stance)",
                  "refine": "docs/project/discovery/refined-hypotheses.md (the hypothesis documents written)"}


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
    return json.loads(path.read_text(encoding="utf-8")) if path.is_file() else None


def _save(root: Path, state: dict) -> None:
    path = root / STATE_PATH
    state["updated"] = now()
    fd, tmp = tempfile.mkstemp(dir=str(path.parent), prefix=".state.", suffix=".tmp")
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        json.dump(state, f, ensure_ascii=False, indent=1)
    os.replace(tmp, path)


def start(root: Path, mode: str, executor_model: str | None) -> dict:
    """Create discovery state; incremental stages track ongoing work without gating other candidates."""
    if mode not in SKIPPED_BY_MODE:
        raise DiscoveryError(f"discovery runs in mode full, precheck or incremental, not {mode!r} (off skips discovery)")
    with _locked(root):
        state = load(root)
        if state is not None:
            if state.get("mode") != mode:
                raise DiscoveryError(f"discovery already started in {state.get('mode')!r}, not {mode!r}; "
                                     "reconcile the existing run rather than silently changing its gates")
            return state
        state = {"mode": mode, "executor_model": executor_model, "created": now(), "gate": None,
                 "stages": [{"stage": s, "status": "skipped" if s in SKIPPED_BY_MODE[mode] else "pending",
                             "artifact": None, "evidence": None, "updated": now()} for s in STAGES]}
        _save(root, state)
        return state


def _stage(state: dict, name: str) -> dict:
    for s in state["stages"]:
        if s["stage"] == name:
            return s
    raise DiscoveryError(f"unknown stage {name!r}; stages: {', '.join(STAGES)}")


def set_status(root: Path, name: str, status: str, artifact: str | None = None) -> dict:
    """The Leader's own progress: pending, running, done or failed. Acceptance is accept()'s alone."""
    if status not in EXECUTOR_STATUSES:
        raise DiscoveryError(f"set writes {', '.join(EXECUTOR_STATUSES)}; acceptance needs evidence (accept)")
    with _locked(root):
        state = _require(root)
        stage = _stage(state, name)
        if stage["status"] == "skipped":
            raise DiscoveryError(f"{name} is skipped in mode {state['mode']}")
        if artifact and not (root / artifact.partition("#")[0]).is_file():
            raise DiscoveryError(f"--artifact {artifact} is not a file under the research root {root}")
        if status == "done" and name not in ("brief", "gate") and not (artifact or stage.get("artifact")):
            # the gate checks every stage's output (real-run-error #15): say so when the stage is finished
            raise DiscoveryError(f"{name} done needs --artifact, the stage's output file relative to the research root "
                                 f"(e.g. {ARTIFACT_HINTS.get(name, 'docs/project/discovery/<stage>.md')}); the "
                                 "discovery gate checks it")
        stage.update(status=status, updated=now(), **({"artifact": artifact} if artifact else {}))
        if name != "gate":
            state["gate"] = None  # anything redone invalidates an earlier gate result
        _save(root, state)
        return state


def _require(root: Path) -> dict:
    state = load(root)
    if state is None:
        raise DiscoveryError("no discovery run: start it first (discovery start)")
    return state


def accept(root: Path, name: str, evidence: list[str], reviews: list[dict] | None = None,
           verifier: str | None = None) -> dict:
    """Accept a done stage on evidence the Leader cannot write: review stages need current review documents of
    their kind by another model family (`reviews`: the records of `evidence`, from research_db.reviews), the
    deterministic stages a verifier's report (`verifier`: what checked it, `evidence`: its output files)."""
    with _locked(root):
        state = _require(root)
        stage = _stage(state, name)
        if stage["status"] not in ("done", "accepted"):
            raise DiscoveryError(f"{name} is {stage['status']}: only a finished stage is accepted")
        if not evidence:
            raise DiscoveryError(f"accepting {name} records its evidence (review ids or verifier output)")
        if name in REVIEW_STAGES:
            kind = REVIEW_STAGES[name]
            found = {r["id"]: r for r in reviews or []}
            for doc_id in evidence:
                r = found.get(doc_id)
                if r is None or r.get("review_kind") != kind or r.get("status") != "current":
                    raise DiscoveryError(f"{name} is accepted on current {kind} reviews; {doc_id} is not one")
                if family(r.get("reviewer_model")) in (None, family(state.get("executor_model"))):
                    raise DiscoveryError(f"{doc_id} is not by another model family than the Leader "
                                         f"({state.get('executor_model')})")
        elif name in DETERMINISTIC_STAGES:
            if not verifier:
                raise DiscoveryError(f"{name} is accepted on a deterministic check: name the verifier")
        else:
            raise DiscoveryError(f"{name} needs no acceptance: done is terminal for it")
        stage.update(status="accepted", evidence=list(evidence), verifier=verifier, updated=now())
        _save(root, state)
        return state


def terminal(stage: dict) -> bool:
    if stage["status"] in TERMINAL:
        return True
    # stages that promise no review or check end when the Leader has done them
    return stage["status"] == "done" and stage["stage"] not in REVIEW_STAGES and stage["stage"] not in DETERMINISTIC_STAGES


def resume_point(root: Path) -> dict | None:
    """R11: the first stage that is not terminal (a done-but-unaccepted review stage is redone), else None."""
    state = _require(root)
    return next((s for s in state["stages"] if not terminal(s)), None)


def family(model: str | None) -> str | None:
    """The model family of a provider/model or a bare model id; None when it cannot be told. The one table both
    review_call (who may review) and accept (whose review counts) use (review_rules.parse_model, S4 §8.3)."""
    return review_rules.family(model)


# -- candidates ----------------------------------------------------------------------------------------------------


def dedup_key(text: str) -> str:
    """A mechanical key: lower case, accents and punctuation removed, words joined by '-'."""
    t = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode() or text
    words = re.findall(r"\w+", t.lower(), re.UNICODE)
    return "-".join(words)[:120]


# What a candidate says (its content revision is over these); bookkeeping (found_by, selected, literature, ranks,
# feasibility notes) is not content.
CONTENT_FIELDS = ("title", "summary", "mechanism", "method", "claim", "statement", "closest_work", "hypothesis",
                  "prediction", "estimated_run", "intervention", "comparator", "resource_ceiling", "stop_conditions")
BOOKKEEPING = ("id", "revision", "content_sha", "revisions", "found_by", "selected", "literature", "triage_rank",
               "feasible", "feasibility_reasons", "present", "origin", "dedup_key", "legacy_ids")


def content_sha(candidate: dict) -> str:
    import hashlib
    content = {k: candidate[k] for k in CONTENT_FIELDS if candidate.get(k) not in (None, "")}
    return hashlib.sha256(json.dumps(content, sort_keys=True, ensure_ascii=False).encode("utf-8")).hexdigest()


def merge(shards: list[dict], user_hypotheses: list[dict], existing: list[dict] | None = None) -> list[dict]:
    """R12, R17: merge lens shards ({"lens", "generator", "candidates": [{"title", "summary", "mechanism",
    "dedup_key"?, "estimated_run"?, ...}]}) with the user's hypotheses ({"title", "summary", ...}). Duplicates are
    clustered by dedup_key only — never dropped for being weak; a user hypothesis keeps origin "user" and records
    which lenses also found it.

    S1 §5.2: a candidate's id is stable. It is the explicit candidate_id an input names, else the id an existing
    candidate of the same origin and dedup_key already has, else a new number never used before — never a position
    in a sorted list, so inserting or reordering candidates moves no id. A candidate whose content changed keeps its
    id with the next revision (content_sha changes): reviews are bound to the revision they read, so a changed
    candidate needs new receipts. A candidate absent from the new inputs stays in the pool as not present (history),
    unselected."""
    existing = [dict(c) for c in existing or []]
    by_id = {c["id"]: c for c in existing if c.get("id")}
    by_key = {(c.get("origin"), c.get("dedup_key")): c for c in existing if c.get("id")}
    numbers = [int(m.group(1)) for i in by_id if (m := re.fullmatch(r"CAND-(\d+)", i))]
    pool: dict[str, dict] = {}
    for h in user_hypotheses:
        key = h.get("dedup_key") or dedup_key(h["title"])
        # a user hypothesis always goes to the novelty check and critical review (02 §3), in every mode
        pool[key] = {**h, "dedup_key": key, "origin": "user", "found_by": ["user"], "selected": True}
    for shard in shards:
        lens = shard.get("lens") or "unknown"
        for c in shard.get("candidates") or []:
            if not (c.get("title") or "").strip():
                raise DiscoveryError(f"a candidate of lens {lens} has no title")
            key = c.get("dedup_key") or dedup_key(c["title"])
            source = f"{lens}:{shard.get('generator') or 'assistant'}"
            if key in pool:
                pool[key]["found_by"] = sorted(set(pool[key]["found_by"]) | {source})
                pool[key]["literature"] = sorted(set(pool[key].get("literature") or []) | set(c.get("literature") or []))
                for field, value in c.items():
                    pool[key].setdefault(field, value)
            else:
                pool[key] = {**c, "dedup_key": key, "origin": "lens", "found_by": [source]}
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
            for key in ("selected", "triage_rank", "feasible", "feasibility_reasons"):  # later stages' marks, for
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


def receipt_applies(review: dict, candidate: dict) -> bool:
    """A discovery receipt counts for the candidate's current revision only (S1 §5.2): its system-captured basis
    names that content, and the candidate did not change while the reviewer answered."""
    basis = review.get("review_basis") or {}
    return (not review.get("review_basis_changed") and basis.get("candidate_id") == candidate.get("id")
            and basis.get("revision") == candidate.get("revision") and candidate.get("revision") is not None
            and basis.get("content_sha") == candidate.get("content_sha") and candidate.get("content_sha") is not None)


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


def select(candidates: list[dict], ranking: list[dict], top_n: int) -> list[dict]:
    """R15: the ideas that go to the novelty check: every user hypothesis, whatever its rank, plus the top_n
    feasible new candidates by the triage ranking ([{candidate_id, rank}] from the triage review)."""
    rank = {r["candidate_id"]: r["rank"] for r in ranking}
    present = [c for c in candidates if c.get("present", True)]
    new = [c for c in present if c["origin"] != "user" and c.get("feasible") is not False]
    new.sort(key=lambda c: rank.get(c["id"], 10 ** 6))
    chosen = {c["id"] for c in new[:top_n]} | {c["id"] for c in present if c["origin"] == "user"}
    return [{**c, "selected": c["id"] in chosen, "triage_rank": rank.get(c["id"])} for c in candidates]


def select_candidate(root: Path, candidate_id: str) -> dict:
    """Select one incremental candidate without changing another candidate's selection or requiring triage.

    Selection is research prioritization, not a PASS receipt: admission rechecks current content and scope.
    """
    with _locked(root):
        state = _require(root)
        if state["mode"] != "incremental":
            raise DiscoveryError("select --candidate is for incremental discovery; full/precheck keep triage selection")
        candidates = read_candidates(root)
        candidate = next((c for c in candidates if c.get("id") == candidate_id), None)
        if candidate is None or candidate.get("present") is False:
            raise DiscoveryError(f"{candidate_id} is not a current discovery candidate")
        candidate["selected"] = True
        write_candidates(root, candidates)
        return candidate


def cite(root: Path, candidate_id: str, literature: list[str]) -> dict:
    """Attach literature documents (D-…) to a candidate: the gate counts the verified ones."""
    candidates = read_candidates(root)
    found = next((c for c in candidates if c["id"] == candidate_id), None)
    if found is None:
        raise DiscoveryError(f"no candidate {candidate_id} in {CANDIDATES_PATH}")
    found["literature"] = sorted(set(found.get("literature") or []) | set(literature))
    write_candidates(root, candidates)
    return found


def write_candidates(root: Path, candidates: list[dict]) -> str:
    path = root / CANDIDATES_PATH
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=str(path.parent), prefix=".candidates.", suffix=".tmp")
    with os.fdopen(fd, "w", encoding="utf-8") as handle:
        json.dump({"updated": now(), "candidates": candidates}, handle, ensure_ascii=False, indent=1)
        handle.write("\n")
    os.replace(tmp, path)
    return str(CANDIDATES_PATH)


def read_candidates(root: Path) -> list[dict]:
    path = root / CANDIDATES_PATH
    return json.loads(path.read_text(encoding="utf-8"))["candidates"] if path.is_file() else []


def read_shards(root: Path) -> list[dict]:
    return [json.loads(p.read_text(encoding="utf-8"))
            for p in sorted((root / "cache" / "discovery" / "shards").glob("*.json"))]


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


def evaluate_candidate(root: Path, candidate_id: str, *, workflow_mode: str = "strict",
                       reviews: list[dict] | None = None, literature: dict[str, bool] | None = None,
                       min_related_work: int = 0, max_nodes: int | None = None,
                       max_walltime_s: int | None = None, screen_node_h: float | None = None) -> dict:
    """Read-only readiness of exactly one candidate; no batch progress, report, or model call is required.

    Fast screening requires a falsifiable prediction, intervention, matched comparator, positive per-run
    resource ceiling within the supplied project limits, and stop/continue conditions. Strict readiness
    retains current revision-bound novelty/critique receipts and verified related work. The database still
    enforces negative-review adjudication, initial authorization, method identity and actual run limits.
    """
    if workflow_mode not in ("strict", "fast_screening"):
        raise DiscoveryError(f"unknown workflow mode {workflow_mode!r}")
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
    if workflow_mode == "fast_screening":
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
    else:
        mine = [r for r in reviews or [] if r.get("status") == "current" and r.get("review_about") == candidate_id]
        applicable = [r for r in mine if receipt_applies(r, candidate)]
        for kind in ("novelty_precheck", "critical_review"):
            if not any(r.get("review_kind") == kind for r in applicable):
                reasons.append(f"{candidate_id}: no {kind} receipt for its current revision {candidate.get('revision')}")
        novelty = [r for r in applicable if r.get("review_kind") == "novelty_precheck"]
        if novelty and max(novelty, key=lambda r: int(r["id"].split("-")[1])).get("review_result") == "NEEDS_EVIDENCE":
            reasons.append(f"{candidate_id}: novelty receipt needs evidence (NEEDS_EVIDENCE); run literature_followup")
        verified = {d for d in candidate.get("literature") or [] if (literature or {}).get(d)}
        if len(verified) < min_related_work:
            reasons.append(f"{candidate_id}: {len(verified)} verified literature documents, needs {min_related_work}")
    result["verdict"] = "BLOCKED" if reasons else "PASS"
    return result


def evaluate(root: Path, reviews: list[dict], literature: dict[str, bool], min_related_work: int,
             report_path: str | None) -> dict:
    """D8: every stage terminal with its artifact; the report has its sections (用户假说, 新发现候选, 淘汰想法) and
    they are not empty; every selected candidate has a novelty_precheck and a critical_review, and at least
    min_related_work verified literature documents (`literature`: doc id -> verified). Returns {verdict PASS or
    BLOCKED, reasons} and records it in the state."""
    state = _require(root)
    if state["mode"] == "incremental":
        raise DiscoveryError("incremental discovery has no whole-batch gate; use gate --candidate CAND-…")
    reasons = []
    for s in state["stages"]:
        if s["stage"] == "gate":
            continue
        if not terminal(s):
            reasons.append(f"{s['stage']}: {s['status']}" + (" (needs acceptance on evidence)"
                                                             if s["status"] == "done" else ""))
        elif s["status"] != "skipped" and s["stage"] != "brief" and not s.get("artifact"):
            reasons.append(f"{s['stage']}: no artifact recorded")
        elif s.get("artifact") and not (root / s["artifact"].partition("#")[0]).is_file():
            reasons.append(f"{s['stage']}: artifact {s['artifact']} is missing")
    if not report_path or not (root / report_path).is_file():
        reasons.append("the discovery report (docs/project/reports/discovery.vN.md) is missing")
    else:
        text = (root / report_path).read_text(encoding="utf-8")
        sections = dict(re.findall(r"^##[ \t]+(.+?)[ \t]*\n(.*?)(?=^##[ \t]|\Z)", text, re.M | re.S))
        for name in REPORT_SECTIONS:
            body = next((b for h, b in sections.items() if h.startswith(name)), None)
            if body is None:
                reasons.append(f"the report lacks the section ## {name}")
            elif not re.sub(r"<!--.*?-->", "", body, flags=re.S).strip():
                reasons.append(f"the report's section ## {name} is empty (write 无 when there is nothing)")
    current = [r for r in reviews if r.get("status") == "current"]
    candidates = read_candidates(root)
    if not any(c.get("selected") for c in candidates):
        reasons.append("no selected candidate: run discovery merge (user hypotheses are always selected)")
    for c in candidates:
        if not c.get("selected") or c.get("present") is False:
            continue
        mine = [r for r in current if r.get("review_about") == c["id"]]
        kinds = {r["review_kind"] for r in mine if receipt_applies(r, c)}
        for kind in ("novelty_precheck", "critical_review"):
            if kind not in kinds:
                stale = any(r["review_kind"] == kind for r in mine)
                reasons.append(f"{c['id']} ({c['title'][:40]}): no {kind} receipt"
                               + (f" for its current revision {c.get('revision')}" if stale else ""))
        novelty = [r for r in mine if r["review_kind"] == "novelty_precheck" and receipt_applies(r, c)]
        if novelty and max(novelty, key=lambda r: int(r["id"].split("-")[1])).get("review_result") == "NEEDS_EVIDENCE":
            reasons.append(f"{c['id']}: its novelty receipt needs evidence (NEEDS_EVIDENCE): run the requested "
                           "searches (literature_followup) and review again with them")
        cited = c.get("literature") or []
        verified = [d for d in cited if literature.get(d)]
        if len(verified) < min_related_work:
            reasons.append(f"{c['id']}: {len(verified)} verified literature documents, needs {min_related_work}")
    verdict = "BLOCKED" if reasons else "PASS"
    with _locked(root):
        state = _require(root)
        state["gate"] = {"verdict": verdict, "reasons": reasons, "at": now(), "report": report_path}
        gate = _stage(state, "gate")
        gate.update(status="done" if verdict == "PASS" else "failed", artifact=report_path, updated=now())
        _save(root, state)
    return {"verdict": verdict, "reasons": reasons}
