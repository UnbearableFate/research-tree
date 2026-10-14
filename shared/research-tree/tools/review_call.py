"""Cross-model, non-interactive review (plans/design 09): one deterministic wrapper for every Type-B review.

    review_call.py --kind <ablation_plan|code_review|candidate_recheck>
                   --brief <file under the research root, e.g. docs/reviews/briefs/H-0001-numbers.v1.md>
                   --about <candidate or node id> [--dimension D --evaluation EV-xxxx] [--session RV-xxxx]
                   [--add-dir DIR ...] [--background] [--wait-s 0]
    review_call.py --ticket RJ-xxxxxxxxxxxx [--wait-s 0]      # collect a background review

Run in the project directory (where .research-tree.json is). The reviewer backend follows models.reviewer.model's
provider only: anthropic/* -> Claude Code CLI (`claude -p`), anything else -> pi (`pi -p --mode json`); neither
falls back to the other. The reviewer gets a new session that reads the brief itself (paths and structured
metadata only, never the Leader's summary); its answer must end in a ```json block matching the kind's schema
(schema/reviews/<kind>.schema.json, plus the checks schema cannot state). The review is written to
docs/reviews/RV-<n>.v<k>.md and registered by the reviewer role (register_review); the raw output stays in
cache/reviews/. Every call, also a failed one, is logged to logs/review_calls.jsonl.

Errors (never a Leader self-review in their place): REVIEW_UNAVAILABLE (backend missing or not logged in, model
error, same model family as the Leader, timeout), REVIEW_INVALID (no valid JSON after one follow-up in the same
session, a conditional check fails, or the observed model is not the requested one), REVIEW_BUDGET (the review
cost reached budget.review_usd_alert). Nothing here calls a model except the backend CLI.
"""

from __future__ import annotations

import argparse
import hashlib
import fcntl
import json
import os
import time
import re
import shutil
import subprocess
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "schema"))

from jsonschema import Draft202012Validator  # noqa: E402

import review_rules  # noqa: E402
import research_tree as tree  # noqa: E402
from research_db import (CANDIDATE_ID_RE, RECHECK_DIMENSIONS, REVIEW_KINDS, ResearchDB,  # noqa: E402
                         ResearchDBError)

REVIEWS_DIR = Path(__file__).resolve().parent.parent / "schema" / "reviews"
PROMPT = ("Read the brief at {brief} and follow it. Executor notes are not evidence beyond the files they cite. "
          "End with exactly one ```json block containing a valid JSON data object that matches the schema "
          "in your instructions. Put the required review fields and their values at the top level. "
          "Do not output the JSON Schema or wrap your review in $schema, type, required or properties metadata.")
FOLLOW_UP = ("Your answer did not contain one valid JSON block for the schema ({problem}). Output only that ```json "
             "block now, nothing else. Return a valid JSON data object with the required review fields at the "
             "top level, not the JSON Schema or a properties wrapper. Close the JSON object before the code fence.")
THINKING_TO_EFFORT = {"off": "low", "minimal": "low", "low": "low", "medium": "medium", "high": "high",
                      "xhigh": "xhigh", "max": "max"}
JSON_BLOCK_RE = re.compile(r"```json[ \t]*\n(.*?)```", re.S)
CALL_LOG = Path("logs") / "review_calls.jsonl"
# One call's whole wall time is capped (both rounds and the prechecks); the hosts wait a little longer than this.
MAX_CALL_S = 3600
CODE_SUFFIXES = (".py", ".pyx", ".c", ".cc", ".cpp", ".cu", ".h", ".hpp", ".rs", ".go", ".jl", ".java", ".js",
                 ".ts", ".sh", ".lua", ".r", ".m", ".scala")


class ReviewError(Exception):
    """code is REVIEW_UNAVAILABLE, REVIEW_INVALID or REVIEW_BUDGET. partial: what a backend printed before it was
    stopped at its timeout (the billed part of its cost is read from it)."""

    def __init__(self, code: str, message: str, cost: float = 0.0, partial: str = ""):
        super().__init__(f"{code}: {message}")
        self.code, self.cost, self.partial = code, cost, partial


def now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


family = review_rules.family  # one model-family table for every review decision


def leader_model(root: Path) -> str | None:
    """The Leader's observed model: the last observed record of rld/main in logs/agent_models.jsonl."""
    log = root / tree.AGENT_LOG
    found = None
    if log.is_file():
        for line in log.read_text(encoding="utf-8").splitlines():
            try:
                rec = json.loads(line)
            except json.JSONDecodeError:
                continue
            if rec.get("actor") == "rld/main" and rec.get("event") == "observed" and rec.get("model"):
                found = rec["model"]
    return found


def spent(root: Path) -> float:
    """Review cost so far: every logged call, failed ones too (their tokens were billed)."""
    log = root / CALL_LOG
    total = 0.0
    if log.is_file():
        for line in log.read_text(encoding="utf-8").splitlines():
            try:
                total += float(json.loads(line).get("cost_usd") or 0)
            except (json.JSONDecodeError, TypeError, ValueError):
                continue
    return total


# -- backends -----------------------------------------------------------------------------------------------------


def _run(cmd: list[str], cwd: Path, timeout: int, deadline: float | None = None,
         input_text: str | None = None) -> subprocess.CompletedProcess:
    if deadline is not None:
        timeout = int(min(timeout, deadline - time.monotonic()))
        if timeout <= 0:
            raise ReviewError("REVIEW_UNAVAILABLE", f"the review call reached its overall deadline before {cmd[0]} ran")
    try:
        input_args = {"stdin": subprocess.DEVNULL} if input_text is None else {"input": input_text}
        return subprocess.run(cmd, cwd=cwd, capture_output=True, text=True, timeout=timeout, check=False,
                              **input_args)
    except subprocess.TimeoutExpired as exc:
        # run() keeps what the killed process printed so far (bytes, also with text=True)
        partial = exc.stdout.decode("utf-8", "replace") if isinstance(exc.stdout, bytes) else exc.stdout or ""
        raise ReviewError("REVIEW_UNAVAILABLE", f"{cmd[0]} did not answer within {timeout} s",
                          partial=partial) from None
    except OSError as exc:
        raise ReviewError("REVIEW_UNAVAILABLE", f"{cmd[0]}: {exc}") from None


class PiBackend:
    name = "pi"
    deadline: float | None = None

    def __init__(self, model: str, thinking: str, root: Path, timeout: int):
        self.model, self.thinking, self.root, self.timeout = model, thinking, root, timeout
        self.provider = model.split("/", 1)[0]

    def precheck(self) -> None:
        if not shutil.which("pi"):
            raise ReviewError("REVIEW_UNAVAILABLE", "pi is not on PATH (the reviewer model is not anthropic/*, so "
                                                    "the pi backend is required; no fallback)")
        auth = _run(["pi", "auth", "check", "--provider", self.provider, "--json"], self.root, 60)
        if auth.returncode != 0:
            raise ReviewError("REVIEW_UNAVAILABLE", f"pi provider {self.provider} not ready: "
                                                    f"{(auth.stdout + auth.stderr).strip()[:300]}")
        listed = _run(["pi", "--list-models"], self.root, 60)
        name = self.model.split("/", 1)[1]
        if not any(line.split()[:2] == [self.provider, name] for line in listed.stdout.splitlines()):
            raise ReviewError("REVIEW_UNAVAILABLE", f"pi does not list {self.model}")

    def call(self, prompt: str, session: str, system_file: Path, first: bool, add_dirs: list[str],
             schema: dict, budget: float | None) -> tuple[dict, str]:
        cmd = ["pi", "-p", "--mode", "json", "--model", self.model, "--thinking", self.thinking,
               "--no-extensions", "--no-skills", "--no-context-files", "--no-mcp",
               "--tools", "read,grep,find,ls", "--session-id", session,
               "--session-dir", str(self.root / "cache" / "review-sessions"),
               "--append-system-prompt", str(system_file)]
        # the same --session-id continues the session (pi 1.0.4 creates it on the first call; checked 2026-10-07:
        # a second call with the id answered from the first one's context, so -c is not needed)
        try:
            out = _run(cmd + [prompt], self.root, self.timeout, self.deadline)
        except ReviewError as exc:  # the turns a run finished before its timeout were billed
            exc.cost += self.parse(exc.partial, "")["cost_usd"]
            raise
        return self.parse(out.stdout, out.stderr), out.stdout

    def parse(self, stdout: str, stderr: str) -> dict:
        end = None
        cost = 0.0
        for line in stdout.splitlines():
            try:
                event = json.loads(line)
            except json.JSONDecodeError:
                continue
            if event.get("type") == "turn_end":
                end = event
                # Each tool-reading turn is billed separately. message_end and agent_end repeat
                # these messages, so count only turn_end, including failed terminal turns.
                cost += float((((event.get("message") or {}).get("usage") or {}).get("cost") or {}).get("total") or 0)
        rec = {"backend": "pi", "provider": self.provider, "model_requested": self.model, "ok": False,
               "error": None, "text": "", "structured": None, "cost_usd": 0.0, "usage": None,
               "model_observed": None, "terminal_reason": None, "permission_denials": []}
        if end is None:
            rec["error"] = f"no turn_end event; stderr: {stderr.strip()[:300]}"
            return rec
        msg = end.get("message") or {}
        usage = msg.get("usage") or {}
        rec.update(text="".join(c.get("text", "") for c in msg.get("content") or [] if c.get("type") == "text"),
                   cost_usd=cost, usage=usage,
                   model_observed=f"{msg.get('provider')}/{msg.get('model')}",
                   terminal_reason=msg.get("stopReason"))
        rec["ok"] = msg.get("stopReason") == "stop"
        if not rec["ok"]:
            rec["error"] = msg.get("errorMessage") or f"stopReason {msg.get('stopReason')}"
        return rec


def _claude_schema(value):
    """The CLI's draft-7 validator cannot resolve our draft-2020-12 annotations.

    These review schemas use draft-7-compatible constraints. Remove only dialect
    annotations for transport; the original schema still validates the result.
    """
    if isinstance(value, dict):
        return {key: _claude_schema(item) for key, item in value.items() if key != "$schema"}
    return [_claude_schema(item) for item in value] if isinstance(value, list) else value


class ClaudeBackend:
    name = "claude_code"
    deadline: float | None = None

    def __init__(self, model: str, thinking: str, root: Path, timeout: int):
        self.model, self.root, self.timeout = model, root, timeout
        self.cli_model = model.split("/", 1)[1]
        self.effort = THINKING_TO_EFFORT[thinking]
        self.provider = "anthropic"

    def precheck(self) -> None:
        if not shutil.which("claude"):
            raise ReviewError("REVIEW_UNAVAILABLE", "claude is not on PATH (the reviewer model is anthropic/*, so "
                                                    "the Claude Code backend is required; no fallback to pi)")
        status = _run(["claude", "auth", "status"], self.root, 60)
        try:
            logged_in = json.loads(status.stdout).get("loggedIn") is True
        except json.JSONDecodeError:
            logged_in = False
        if not logged_in:
            raise ReviewError("REVIEW_UNAVAILABLE", "claude is not logged in (claude auth status)")

    def command(self, prompt: str, session: str, system_file: Path, first: bool, add_dirs: list[str],
                schema: dict, budget: float | None) -> list[str]:
        cmd = ["claude", "-p", "--output-format", "json", "--model", self.cli_model, "--effort", self.effort,
               "--safe-mode", "--restricted", "--strict-mcp-config",
               "--tools", "Read,Grep,Glob", "--permission-mode", "dontAsk", "--permission-prompts", "none",
               "--session-id" if first else "--resume", session,
               "--append-system-prompt-file", str(system_file), "--json-schema", json.dumps(_claude_schema(schema))]
        for d in add_dirs:
            cmd += ["--add-dir", d]
        if budget is not None:
            cmd += ["--max-budget-usd", f"{max(budget, 0.01):.2f}"]
        return cmd

    def call(self, prompt: str, session: str, system_file: Path, first: bool, add_dirs: list[str],
             schema: dict, budget: float | None) -> tuple[dict, str]:
        out = _run(self.command(prompt, session, system_file, first, add_dirs, schema, budget), self.root,
                   self.timeout, self.deadline, input_text=prompt)
        return self.parse(out.stdout, out.stderr), out.stdout

    def parse(self, stdout: str, stderr: str) -> dict:
        rec = {"backend": "claude_code", "provider": "anthropic", "model_requested": self.model, "ok": False,
               "error": None, "text": "", "structured": None, "cost_usd": 0.0, "usage": None,
               "model_observed": None, "terminal_reason": None, "permission_denials": []}
        try:
            result = json.loads(stdout)
        except json.JSONDecodeError:
            rec["error"] = f"no JSON result; stderr: {stderr.strip()[:300]}"
            return rec
        models = list((result.get("modelUsage") or {}).keys())
        rec.update(text=result.get("result") or "", structured=result.get("structured_output"),
                   cost_usd=float(result.get("total_cost_usd") or 0), usage=result.get("usage"),
                   terminal_reason=result.get("terminal_reason"),
                   permission_denials=result.get("permission_denials") or [], observed_models=models,
                   model_observed=f"anthropic/{models[0]}" if len(models) == 1 else None)
        # success is is_error false and a completed turn; subtype stays "success" on a 404 (09 §1.2)
        rec["ok"] = result.get("is_error") is False and result.get("terminal_reason") == "completed"
        if not rec["ok"]:
            rec["error"] = (f"is_error={result.get('is_error')} terminal_reason={result.get('terminal_reason')} "
                            f"api_error_status={result.get('api_error_status')}: {str(result.get('result'))[:300]}")
        return rec


def backend_for(reviewer: dict, root: Path):
    model = reviewer["model"]
    cls = ClaudeBackend if model.split("/", 1)[0] == "anthropic" else PiBackend
    return cls(model, reviewer["thinking"], root, int(reviewer["timeout_s"]))


# -- checks -------------------------------------------------------------------------------------------------------


def extract(rec: dict) -> dict | None:
    if isinstance(rec.get("structured"), dict):
        return rec["structured"]
    blocks = JSON_BLOCK_RE.findall(rec.get("text") or "")
    if not blocks:
        return None
    try:
        value = json.loads(blocks[-1])
    except json.JSONDecodeError:
        return None
    return value if isinstance(value, dict) else None


def problems(kind: str, data: dict | None, schema: dict, dimension: str | None) -> list[str]:
    """What makes an answer invalid: schema errors and the conditions JSON Schema cannot state (09 §3)."""
    if data is None:
        return ["no ```json block with an object"]
    found = [f"{'/'.join(map(str, e.absolute_path)) or '<root>'}: {e.message}"
             for e in Draft202012Validator(schema).iter_errors(data)]
    if found:
        return found[:5]
    if kind == "candidate_recheck":
        if data["dimension"] != dimension:
            found.append(f"dimension is {data['dimension']!r}, the brief asked for {dimension!r}")
        # S4 §8.1: only structure is corrected here (missing, duplicated or foreign checklist items); a legal fail
        # or uncertain is the review's answer and is never sent back to be rewritten. A pass whose cited files
        # cannot be resolved is made uncertain when it is registered (research_db.register_review).
        found += review_rules.structure_problems(dimension, data)
    return found


def result_of(kind: str, data: dict) -> str:
    """The review's conclusion as the reviewer states it; the positive/negative reading follows 09 §3. A
    candidate_recheck records its effective result instead (research_db.recheck_outcome)."""
    if kind == "candidate_recheck":
        return data["result"]
    if kind == "code_review":
        blocking = [i for i in data["issues"] if i["severity"] in ("CRITICAL", "MAJOR")]
        return "blocking" if blocking or not data["method_implemented"] else "clear"
    if kind == "ablation_plan":
        return "planned"
    raise ReviewError("REVIEW_INVALID", f"unsupported review kind {kind!r}")


# -- the call -----------------------------------------------------------------------------------------------------


class _Lock:
    """An exclusive lock on cache/reviews/.lock: RV numbers and review files are allocated one call at a time."""

    def __init__(self, root: Path):
        self.path = root / "cache" / "reviews" / ".lock"

    def __enter__(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.handle = self.path.open("w")
        fcntl.flock(self.handle, fcntl.LOCK_EX)
        return self

    def __exit__(self, *exc):
        fcntl.flock(self.handle, fcntl.LOCK_UN)
        self.handle.close()


def _sessions(root: Path) -> dict:
    path = root / "cache" / "reviews" / "sessions.json"
    return json.loads(path.read_text(encoding="utf-8")) if path.is_file() else {}


def _save_sessions(root: Path, sessions: dict) -> None:
    path = root / "cache" / "reviews" / "sessions.json"
    _atomic_json(path, sessions)


def _next_rv(root: Path, sessions: dict) -> str:
    numbers = [int(m.group(1)) for p in (root / "docs" / "reviews").glob("RV-*.v*.md")
               if (m := re.match(r"RV-(\d+)\.v\d+\.md$", p.name))]
    numbers += [int(k.split("-")[1]) for k in sessions]
    return f"RV-{max(numbers, default=0) + 1:04d}"


def _front_matter(fields: dict) -> str:
    return "---\n" + "".join(f"{k}: {json.dumps(v, ensure_ascii=False)}\n" for k, v in fields.items()) + "---\n"


def _prepare_review(cwd: Path, kind: str, brief: str, about: str, dimension: str | None = None,
                    evaluation: str | None = None, session: str | None = None, add_dirs: list[str] | None = None,
                    actor: str = "rld/main", code_ref: str | None = None,
                    evidence_set: str | None = None) -> dict:
    """Local validation and immutable request identity. Never construct or precheck a model backend here."""
    if not actor.startswith("rld/"):
        raise ReviewError("REVIEW_UNAVAILABLE", "the Leader (rld) organizes reviews; other roles ask the Leader")
    if kind not in REVIEW_KINDS:
        raise ReviewError("REVIEW_INVALID", f"kind is one of {REVIEW_KINDS}")
    if kind == "candidate_recheck" and (dimension not in RECHECK_DIMENSIONS or not evaluation):
        raise ReviewError("REVIEW_INVALID", f"a candidate_recheck names --dimension ({', '.join(RECHECK_DIMENSIONS)}) "
                                            "and --evaluation (the evaluation it rechecks)")
    if kind != "candidate_recheck" and (dimension or evaluation):
        raise ReviewError("REVIEW_INVALID", "dimension and evaluation belong to a candidate_recheck")
    if kind == "code_review" and not code_ref:
        raise ReviewError("REVIEW_INVALID", "a code_review names --code-ref, the commit the reviewer reads")
    if code_ref and kind != "code_review":
        raise ReviewError("REVIEW_INVALID", "code_ref belongs to a code_review")
    if not about or not brief:
        raise ReviewError("REVIEW_INVALID", "a review names --about and --brief")
    marker = tree.read_marker(cwd)
    root = Path(marker["root"]).resolve()
    conf = tree.show_config(cwd)["effective"]
    reviewer = (conf.get("models") or {}).get("reviewer")
    if not reviewer:
        raise ReviewError("REVIEW_UNAVAILABLE", "research-tree.yaml has no models.reviewer (configuration version 3)")
    brief_path = (Path(brief) if Path(brief).is_absolute() else root / brief).resolve()
    if not brief_path.is_file() or not brief_path.is_relative_to(root):
        raise ReviewError("REVIEW_INVALID", f"the brief is a file under {root}: {brief_path} is missing or outside it")
    rld = ResearchDB(Path(marker["db"]), "rld/main")
    try:
        with rld.reader() as tx:
            subject = tx.get(about)
            if subject is None and not CANDIDATE_ID_RE.fullmatch(about):
                raise ReviewError("REVIEW_INVALID", f"{about} is neither a record nor a discovery candidate (CAND-…)")
            if CANDIDATE_ID_RE.fullmatch(about) and kind in ("code_review", "candidate_recheck", "ablation_plan"):
                raise ReviewError("REVIEW_INVALID", f"REVIEW_SUBJECT_UNSUPPORTED: {kind} needs a hypothesis subject")
            if kind == "candidate_recheck":
                ev = tx.require(evaluation, ("evaluation",))
                exp = tx.require(ev["experiment_id"], ("experiment",))
                if exp.get("hypothesis_id") != about:
                    raise ReviewError("REVIEW_INVALID", f"{evaluation} does not evaluate hypothesis {about}")
        basis = rld.review_basis(about, kind, dimension, evaluation, code_ref)
        if kind == "code_review" and (not basis.get("code_ref") or not basis.get("method_spec_doc_ids")):
            raise ReviewError("REVIEW_INVALID", "REVIEW_SUBJECT_UNSUPPORTED: code_review needs a valid commit and "
                                                "an exact method identity for this subject")
    except ResearchDBError as exc:
        raise ReviewError("REVIEW_INVALID", f"the review's basis cannot be determined: {exc}") from None
    backend_name = "claude_code" if reviewer["model"].split("/", 1)[0] == "anthropic" else "pi"
    if session:
        state = _sessions(root).get(session)
        if state is None or (state["kind"], state["about"], state["backend"]) != (kind, about, backend_name):
            raise ReviewError("REVIEW_INVALID", f"{session} is not a {kind} session of {about} on {backend_name}")
    evidence = followup_evidence(root, Path(marker["db"]), evidence_set, kind, about, basis) if evidence_set else None
    identity = {"kind": kind, "about": about, "dimension": dimension, "evaluation": evaluation, "session": session,
                "code_ref": basis.get("code_ref") if code_ref else None, "actor": actor, "basis": basis,
                "brief": str(brief_path.relative_to(root)), "brief_sha256": hashlib.sha256(brief_path.read_bytes()).hexdigest(),
                "configuration": conf, "leader_model": leader_model(root), "evidence_set": evidence,
                "add_dirs": sorted({str((Path(d) if Path(d).is_absolute() else root / d).resolve()) for d in add_dirs or []})}
    key = hashlib.sha256(json.dumps(identity, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
    return {"root": root, "marker": marker, "conf": conf, "reviewer": reviewer, "brief_path": brief_path,
            "basis": basis, "evidence": evidence, "identity": identity, "request_key": key}


def review(cwd: Path, kind: str, brief: str, about: str, dimension: str | None = None,
           evaluation: str | None = None, session: str | None = None, add_dirs: list[str] | None = None,
           actor: str = "rld/main", code_ref: str | None = None, deadline_s: int | None = None,
           evidence_set: str | None = None, *, job_ticket: str | None = None,
           request_key: str | None = None) -> dict:
    prepared = _prepare_review(cwd, kind, brief, about, dimension, evaluation, session, add_dirs, actor, code_ref,
                               evidence_set)
    root, marker, conf = prepared["root"], prepared["marker"], prepared["conf"]
    reviewer, basis, brief_path = prepared["reviewer"], prepared["basis"], prepared["brief_path"]
    if request_key is not None and request_key != prepared["request_key"]:
        raise ReviewError("REVIEW_INVALID", "the review basis, brief or configuration changed after the ticket was "
                                            "created; no model was called; start a review of the current inputs")
    alert = (conf.get("budget") or {}).get("review_usd_alert")
    so_far = spent(root)
    if alert is not None and so_far >= alert:
        raise ReviewError("REVIEW_BUDGET", f"review cost {so_far:.4f} USD reached budget.review_usd_alert {alert}; "
                                           "the user decides (raise it in research-tree.yaml and config apply)")
    if reviewer.get("require_cross_family", True):
        leader = prepared["identity"]["leader_model"]
        if family(leader) is None:
            raise ReviewError("REVIEW_UNAVAILABLE", f"the Leader's observed model ({leader or 'none recorded'}) "
                                                    "cannot be placed in a model family; require_cross_family")
        if family(reviewer["model"]) is None:
            raise ReviewError("REVIEW_UNAVAILABLE", f"the reviewer {reviewer['model']} cannot be placed in a model "
                                                    "family; require_cross_family cannot be met")
        if family(leader) == family(reviewer["model"]):
            raise ReviewError("REVIEW_UNAVAILABLE", f"reviewer {reviewer['model']} is the Leader's family "
                                                    f"({leader}); require_cross_family refuses the call")
    backend = backend_for(reviewer, root)
    backend.precheck()
    schema = json.loads((REVIEWS_DIR / f"{kind}.schema.json").read_text(encoding="utf-8"))
    system_file = REVIEWS_DIR / f"{kind}.md"
    db = ResearchDB(Path(marker["db"]), "reviewer/" + backend.name)
    allocation = None
    # Everything after reservation belongs to this finalizer, including publishing the ticket pointer.
    # If publication fails, this process must release its session without ever entering a model call.
    try:
        with _Lock(root):
            allocation = _allocate(root, session, kind, about, backend.name, job_ticket)
        rv, uid, version, first, state = allocation
        if job_ticket:
            _update_job(root, job_ticket, session=rv, version=version)
        log_call(root, {"kind": kind, "about": about, "dimension": dimension, "session": rv, "outcome": "started",
                        "backend": backend.name, **({"ticket": job_ticket} if job_ticket else {})})
        deadline = time.monotonic() + min(2 * int(reviewer["timeout_s"]) + 120, MAX_CALL_S, deadline_s or MAX_CALL_S)
        backend.deadline, backend.code_ref, backend.basis = deadline, code_ref, basis
        backend.evidence = prepared["evidence"]
        reviewed = code_ref if kind == "code_review" else basis.get("code_ref") if dimension == "method_code" else None
        if reviewed:
            with ResearchDB(Path(marker["db"]), "rld/main").reader() as tx:
                repo = (tx.get(tx.ids("project")[0]) or {}).get("repo_path")
            snapshot = code_snapshot(root, repo, basis.get("code_ref") or code_ref)
            if snapshot:
                add_dirs = [*(add_dirs or []), str(snapshot)]
                backend.snapshot = snapshot
        return _run_review(root, backend, reviewer, kind, brief_path, about, dimension, evaluation, add_dirs, schema,
                           system_file, db, alert, so_far, rv, uid, version, first, state)
    finally:
        if allocation is not None:
            rv, _, _, _, state = allocation
            with _Lock(root):
                sessions = _sessions(root)
                current = sessions.get(rv, state)
                if current.get("allocation_token") == state.get("allocation_token"):
                    sessions[rv] = {**current, "busy": False, "active_ticket": None, "active_version": None,
                                    "allocation_token": None}
                    _save_sessions(root, sessions)


def followup_evidence(root: Path, db_path: Path, manifest: str, kind: str, about: str, basis: dict) -> dict:
    """S4 §8.4: the follow-up manifest literature_followup wrote for an earlier receipt of the same subject. The
    subject must not have changed since that receipt (otherwise a new review starts from the new subject)."""
    path = (root / manifest).resolve() if not Path(manifest).is_absolute() else Path(manifest).resolve()
    base = (root / "cache" / "literature" / "followup").resolve()
    if path.name != "manifest.json" or not path.is_file() or path.parent.parent != base:
        raise ReviewError("REVIEW_INVALID", f"evidence_set is a cache/literature/followup/<review>/manifest.json "
                                            f"under {root}")
    parent_id = path.parent.name
    rld = ResearchDB(db_path, "rld/main")
    parent = next((d for d in rld.reviews() if d["id"] == parent_id), None)
    subjects = {edge["target_id"] for edge in rld.edges("rel_describes", source_id=parent_id)} if parent else set()
    if parent is None or parent.get("review_kind") != kind or subjects != {about}:
        raise ReviewError("REVIEW_INVALID", f"{parent_id} is not a {kind} review of {about}")
    recorded = (parent.get("followup") or {}).get("sha256")
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    if recorded != digest:
        raise ReviewError("REVIEW_INVALID", f"{path.name} is not the manifest recorded on {parent_id}")
    if parent.get("review_basis") != basis:
        raise ReviewError("REVIEW_INVALID", f"the subject changed since {parent_id} (its basis differs): its "
                                            "follow-up does not carry over; review the current subject anew")
    return {"path": str(path.relative_to(root.resolve())), "sha256": digest, "parent_review_id": parent_id,
            "parent_path": parent["path"]}


def code_snapshot(root: Path, repo: str | None, ref: str | None) -> Path | None:
    """cache/reviews/code/<commit>/: the files of one commit, extracted once and made read-only."""
    if not repo or not ref:
        return None
    sha = subprocess.run(["git", "-C", repo, "rev-parse", "--verify", "--quiet", f"{ref}^{{commit}}"],
                         capture_output=True, text=True).stdout.strip()
    if not sha:
        return None
    target = root / "cache" / "reviews" / "code" / sha
    with _Lock(root):
        if not (target / ".complete").is_file():
            tmp = target.with_name(sha + ".tmp")
            shutil.rmtree(tmp, ignore_errors=True)
            tmp.mkdir(parents=True)
            archive = subprocess.run(["git", "-C", repo, "archive", sha], capture_output=True)
            if archive.returncode != 0:
                return None
            subprocess.run(["tar", "-x", "-C", str(tmp)], input=archive.stdout, check=True)
            # A committed symlink stays a link and is never followed: its target may be anything outside the
            # snapshot. .complete comes last, so a snapshot that failed part way is extracted again.
            for path in tmp.rglob("*"):
                if path.is_file() and not path.is_symlink():
                    path.chmod(0o444)
            (tmp / ".complete").write_text(sha + "\n")
            shutil.rmtree(target, ignore_errors=True)
            tmp.rename(target)
    return target


def _allocate(root: Path, session: str | None, kind: str, about: str, backend: str,
              job_ticket: str | None = None) -> tuple:
    sessions = _sessions(root)
    if session:
        if session not in sessions:
            raise ReviewError("REVIEW_INVALID", f"no review session {session}")
        state = sessions[session]
        if (state["kind"], state["about"], state["backend"]) != (kind, about, backend):
            raise ReviewError("REVIEW_INVALID", f"{session} is a {state['kind']} of {state['about']} on "
                                                f"{state['backend']}")
        rv, uid, version, first = session, state["uuid"], max(state["version"], state.get("allocated_version", 0)) + 1, False
    else:
        rv, uid, version, first = _next_rv(root, sessions), str(uuid.uuid4()), 1, True
        state = {"uuid": uid, "kind": kind, "about": about, "backend": backend, "version": 0, "doc_id": None}
    if session and state.get("busy"):
        raise ReviewError("REVIEW_INVALID", f"{session} has a round in progress")
    state = {**state, "busy": True, "allocated_version": version, "active_version": version,
             "active_ticket": job_ticket, "allocation_token": uuid.uuid4().hex}
    sessions[rv] = state
    _save_sessions(root, sessions)  # the number is taken before the call: a failed call never reuses it
    return rv, uid, version, first, state


def _run_review(root, backend, reviewer, kind, brief_path, about, dimension, evaluation, add_dirs, schema,
                system_file, db, alert, so_far, rv, uid, version, first, state) -> dict:
    raw_dir = root / "cache" / "reviews"
    raw_dir.mkdir(parents=True, exist_ok=True)
    budget = None if alert is None else alert - so_far
    prompt = PROMPT.format(brief=brief_path.resolve())
    evidence = getattr(backend, "evidence", None)
    if evidence:
        prompt += (f" This is a follow-up round: your earlier receipt is {root / 'docs' / evidence['parent_path']}; the "
                   f"searches it requested were run and their raw results are listed in {root / evidence['path']}. "
                   "Judge again from them; record what they settle and what they do not.")
    if getattr(backend, "snapshot", None):
        prompt += (f" The reviewed code is the read-only snapshot of commit {backend.snapshot.name} at "
                   f"{backend.snapshot}; read and cite the code files there (absolute paths), not a working tree.")
    rec, raw = backend.call(prompt, uid, system_file, first, add_dirs or [], schema, budget)
    suffix = "jsonl" if backend.name == "pi" else "json"
    (raw_dir / f"{rv}.v{version}.{suffix}").write_text(raw, encoding="utf-8")
    cost = rec["cost_usd"]
    if not rec["ok"]:
        raise ReviewError("REVIEW_UNAVAILABLE", f"{backend.name}: {rec['error']}", cost)
    if not review_rules.same_model(rec["model_observed"], reviewer["model"]):
        raise ReviewError("REVIEW_INVALID", f"the review ran on {rec.get('observed_models') or rec['model_observed']}, "
                                            f"not the requested {reviewer['model']}", cost)
    if reviewer.get("require_cross_family", True):  # S4 §8.3: the family the backend observed, not the channel
        leader = leader_model(root)
        if review_rules.family(rec["model_observed"]) is None or \
                review_rules.family(rec["model_observed"]) == review_rules.family(leader):
            raise ReviewError("REVIEW_INVALID", f"the review ran on {rec['model_observed']} (family "
                                                f"{review_rules.family(rec['model_observed']) or 'unknown'}), not "
                                                f"another family than the Leader's {leader}", cost)
    data = extract(rec)
    found = problems(kind, data, schema, dimension)
    if found:  # one follow-up in the same session, then invalid
        try:
            retry, raw2 = backend.call(FOLLOW_UP.format(problem="; ".join(found)[:500]), uid, system_file, False,
                                       add_dirs or [], schema, budget)
        except ReviewError as exc:  # the first round was billed already
            exc.cost += cost
            raise
        (raw_dir / f"{rv}.v{version}.retry.{suffix}").write_text(raw2, encoding="utf-8")
        cost += retry["cost_usd"]
        if not retry["ok"]:
            raise ReviewError("REVIEW_UNAVAILABLE", f"{backend.name}: {retry['error']}", cost)
        if not review_rules.same_model(retry["model_observed"], reviewer["model"]):
            raise ReviewError("REVIEW_INVALID", f"the follow-up ran on {retry['model_observed']}", cost)
        data = extract(retry)
        found = problems(kind, data, schema, dimension)
        if found:
            raise ReviewError("REVIEW_INVALID", "; ".join(found)[:600], cost)
        rec["text"] += "\n\n(follow-up)\n" + retry["text"]
    result, reported = result_of(kind, data), None
    if kind == "candidate_recheck":  # S4 §8.1: the receipt states the result register_review records
        try:
            outcome = db.recheck_outcome(about, dimension, evaluation, data)
        except ResearchDBError as exc:
            raise ReviewError("REVIEW_INVALID", f"the receipt's result cannot be determined: {exc}", cost) from None
        if outcome["invalid"]:
            raise ReviewError("REVIEW_INVALID", "; ".join(outcome["invalid"])[:600], cost)
        result, reported = outcome["effective_result"], outcome["reported_result"]

    rel = f"reviews/{rv}.v{version}.md"
    fields = {"kind": kind, "about": about, "dimension": dimension, "evaluation_id": evaluation,
              "code_ref": getattr(backend, "code_ref", None), "result": result, "reported_result": reported,
              "backend": backend.name, "provider": rec["provider"], "model_requested": reviewer["model"],
              "model_observed": rec["model_observed"], "thinking": reviewer["thinking"], "session": rv,
              "session_id": uid, "brief": str(brief_path.relative_to(root)), "terminal_reason": rec["terminal_reason"],
              "cost_usd": round(cost, 6), "usage": rec["usage"], "permission_denials": rec["permission_denials"],
              "raw": f"cache/reviews/{rv}.v{version}.{suffix}", "created_at": now(),
              "basis": json.dumps(getattr(backend, "basis", None), ensure_ascii=False, sort_keys=True)}
    body = (_front_matter({k: v for k, v in fields.items() if v is not None}) +
            f"\n# {kind}：{about}{'（' + dimension + '）' if dimension else ''}\n\n## 评审原文\n\n{rec['text'].strip()}\n\n"
            f"## 结构化结论\n\n```json\n{json.dumps(data, ensure_ascii=False, indent=1)}\n```\n")
    (root / "docs" / "reviews").mkdir(parents=True, exist_ok=True)
    with _Lock(root):
        if (root / "docs" / rel).exists():  # never overwrite a review
            raise ReviewError("REVIEW_INVALID", f"{rel} exists already", cost)
        (root / "docs" / rel).write_text(body, encoding="utf-8")
    previous = db.get(state["doc_id"]) if state.get("doc_id") else None
    supersedes = state.get("doc_id") if not previous or previous.get("review_result") not in ("blocking", "fail") else None
    try:
        doc_id = db.register_review(rel, f"{kind} {about}{' ' + dimension if dimension else ''}", kind, [about],
                                    result, rv, backend.name, rec["model_observed"], cost, dimension=dimension,
                                    evaluation_id=evaluation, supersedes=supersedes,
                                    code_ref=getattr(backend, "code_ref", None),
                                    summary=f"{backend.name} {rec['model_observed']}: {result}",
                                    basis=getattr(backend, "basis", None), payload=data,
                                    model_requested=reviewer["model"],
                                    parent_review_id=(evidence or {}).get("parent_review_id"),
                                    evidence_set={k: evidence[k] for k in ("path", "sha256")} if evidence else None)
    except ResearchDBError as exc:
        raise ReviewError("REVIEW_INVALID", f"not registered: {exc}", cost) from None
    with _Lock(root):
        sessions = _sessions(root)
        sessions[rv] = {**state, "version": version, "doc_id": doc_id, "busy": True}
        _save_sessions(root, sessions)
    registered = db.reviews(kind=kind)
    doc = next((d for d in registered if d["id"] == doc_id), {})
    result = doc.get("review_result", result)
    extra = {k: doc[k] for k in ("reported_result", "effective_result", "normalization_warnings") if doc.get(k) is not None}
    return {"review_id": doc_id, "path": rel, "session": rv, "kind": kind, "result": result, **extra,
            "backend": backend.name,
            "model_observed": rec["model_observed"], "cost_usd": round(cost, 6),
            "permission_denials": rec["permission_denials"], "structured": data}


def record_failure(root: Path, entry: dict, exc: ReviewError) -> None:
    """Log a failed call; its cost, if any, also goes to the project record (the figure review_usd_alert gates)."""
    log_call(root, {**entry, "outcome": exc.code, "error": str(exc)[:600], "cost_usd": exc.cost})
    if exc.cost:
        try:
            ResearchDB(root / "research_tree.db", "reviewer/cost").add_review_cost(exc.cost)
        except ResearchDBError:
            pass


def log_call(root: Path, entry: dict) -> None:
    log = root / CALL_LOG
    log.parent.mkdir(parents=True, exist_ok=True)
    with log.open("a", encoding="utf-8") as f:
        f.write(json.dumps({"ts": now(), **entry}, ensure_ascii=False) + "\n")


JOBS_DIR = Path("cache") / "reviews" / "jobs"
_JOB_CHILDREN: dict[str, subprocess.Popen] = {}
_STARTUP_GRACE_S = 30


class _JobLock(_Lock):
    def __init__(self, root: Path):
        self.path = root / JOBS_DIR / ".lock"


def _atomic_json(path: Path, value: dict) -> None:
    """Readers see either complete version, including when a writer is interrupted."""
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
    try:
        with temporary.open("x", encoding="utf-8") as handle:
            json.dump(value, handle, ensure_ascii=False, indent=1)
            handle.flush()
            os.fsync(handle.fileno())
        temporary.replace(path)
        fd = os.open(path.parent, os.O_RDONLY)
        try:
            os.fsync(fd)
        finally:
            os.close(fd)
    finally:
        temporary.unlink(missing_ok=True)


def _job_file(root: Path, ticket: str) -> Path:
    if not re.fullmatch(r"RJ-[0-9a-f]{12}", ticket or ""):
        raise ReviewError("REVIEW_INVALID", f"{ticket!r} is not a review job ticket (RJ-…)")
    return root / JOBS_DIR / f"{ticket}.json"


def _read_job(root: Path, ticket: str) -> dict:
    path = _job_file(root, ticket)
    try:
        job = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        raise ReviewError("REVIEW_INVALID", f"no review job {ticket}") from None
    except (OSError, ValueError) as exc:
        raise ReviewError("REVIEW_UNAVAILABLE", f"review job {ticket} cannot be read; inspect it before retrying: {exc}") from None
    if (not isinstance(job, dict) or job.get("ticket") != ticket or job.get("status") not in ("running", "done")
            or (job.get("status") == "done" and not isinstance(job.get("answer"), dict))):
        raise ReviewError("REVIEW_UNAVAILABLE", f"review job {ticket} has invalid persisted state; do not resubmit it")
    return job


def _update_job(root: Path, ticket: str, **fields) -> dict:
    with _JobLock(root):
        job = _read_job(root, ticket)
        if job["status"] == "running":
            job = {**job, **fields}
            _atomic_json(_job_file(root, ticket), job)
        return job


def _job_call_args(argv: list[str]):
    try:
        args = _parser().parse_args(argv)
    except SystemExit:
        raise ReviewError("REVIEW_INVALID", "invalid background review arguments") from None
    if args.run_job or args.ticket or args.list_jobs:
        raise ReviewError("REVIEW_INVALID", "a new review job cannot contain job-control arguments")
    return args


def _prepare_job(cwd: Path, args) -> dict:
    return _prepare_review(cwd, args.kind, args.brief, args.about, args.dimension, args.evaluation, args.session,
                           args.add_dir, args.actor, args.code_ref, args.evidence_set)


def start_job(cwd: Path, root: Path, argv: list[str]) -> str:
    """Persist a ticket immediately. Identical inputs reuse a running or successfully completed job's ticket.

    Deduplication covers the current scientific basis, brief contents, effective configuration/model and
    review options. Only local validation runs here; backend setup and all model calls belong to the worker.
    A failed or interrupted job is never resumed or replayed: it stays collectable under its own ticket, and
    asking again for the same review is a new job with a new ticket. A changed request gets a new auditable ticket.
    """
    args = _job_call_args(argv)
    prepared = _prepare_job(cwd, args)
    root = Path(root).resolve()
    if root != prepared["root"]:
        raise ReviewError("REVIEW_INVALID", "review job root does not match the project marker")
    with _JobLock(root):
        for path in sorted((root / JOBS_DIR).glob("RJ-*.json")):
            job = _read_job(root, path.stem)
            if job.get("request_key") == prepared["request_key"]:
                job = _refresh_job(root, job)
                if job["status"] == "running" or job["answer"].get("ok"):
                    return job["ticket"]
        ticket = f"RJ-{uuid.uuid4().hex[:12]}"
        job = {"ticket": ticket, "argv": argv, "status": "running", "phase": "queued", "started_at": now(),
               "request_key": prepared["request_key"], "request": prepared["identity"],
               "db_path": str(Path(prepared["marker"]["db"]).resolve())}
        _atomic_json(_job_file(root, ticket), job)
        log_call(root, {"outcome": "background_started", "ticket": ticket, "argv": argv})
        try:
            proc = subprocess.Popen([sys.executable, str(Path(__file__).resolve()), "--run-job", ticket], cwd=cwd,
                                    start_new_session=True, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                                    stderr=subprocess.DEVNULL)
        except (OSError, subprocess.SubprocessError) as exc:
            failure = ReviewError("REVIEW_UNAVAILABLE", f"could not start background review: {exc}; no model was called")
            record_failure(root, {"ticket": ticket, "kind": args.kind, "about": args.about,
                                  "dimension": args.dimension}, failure)
            _atomic_json(_job_file(root, ticket), {**job, "status": "done", "phase": "spawn_failed",
                         "answer": {"ok": False, "error": str(failure), "ticket": ticket}, "finished_at": now()})
        else:
            _JOB_CHILDREN[ticket] = proc
            _atomic_json(_job_file(root, ticket), {**job, "pid": proc.pid})
        return ticket


def _process_alive(pid: int | None) -> bool:
    if not isinstance(pid, int) or pid <= 0:
        return False
    try:
        os.kill(pid, 0)
        stat = Path(f"/proc/{pid}/stat")
        return not (stat.exists() and stat.read_text().rsplit(")", 1)[1].strip().split()[0] == "Z")
    except ProcessLookupError:
        return False
    except (PermissionError, OSError):
        return True  # absence cannot be established; never risk a duplicate paid worker


def _lease_path(root: Path, ticket: str) -> Path:
    return _job_file(root, ticket).with_suffix(".worker.lock")


def _worker_active(root: Path, job: dict) -> bool:
    proc = _JOB_CHILDREN.get(job["ticket"])
    if proc is not None and proc.poll() is not None:
        del _JOB_CHILDREN[job["ticket"]]
    # Probed only under the job lock (_refresh_job), the lock a worker claims its lease under (_run_job): this brief
    # hold can never make a starting worker give up.
    with _lease_path(root, job["ticket"]).open("a") as lease:
        try:
            fcntl.flock(lease, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            return True
    if job.get("worker_started_at"):
        return False
    if job.get("pid"):
        return _process_alive(job["pid"])
    try:
        age = (datetime.now(timezone.utc) - datetime.fromisoformat(job["started_at"].replace("Z", "+00:00"))).total_seconds()
    except (KeyError, TypeError, ValueError):
        age = _STARTUP_GRACE_S
    # Old-format jobs had no PID/lease. Give their documented maximum runtime before classifying interruption.
    return age < (_STARTUP_GRACE_S if job.get("request_key") else MAX_CALL_S + 120)


def _registered_answer(root: Path, job: dict) -> dict | None:
    """Recover a committed receipt after a crash between registration and publishing the ticket answer."""
    if not job.get("session") or not job.get("version"):
        return None
    path = f"reviews/{job['session']}.v{job['version']}.md"
    db = ResearchDB(Path(job.get("db_path") or root / "research_tree.db"), "rld/main")
    with db.reader() as tx:
        found = tx.ids("document", "WHERE n.path = $path", path=path)
        doc = tx.get(found[0]) if found else None
    if not doc or doc.get("review_session") != job["session"] or doc.get("review_basis") != job["request"]["basis"]:
        return None
    file = root / "docs" / path
    raw = file.read_bytes()
    if hashlib.sha256(raw).hexdigest() != doc.get("sha256"):
        return None
    header = re.match(r"^---\n(.*?)\n---", raw.decode("utf-8"), re.S)
    if not header:
        return None
    fields = {}
    for line in header.group(1).splitlines():
        key, value = line.split(": ", 1)
        fields[key] = json.loads(value)
    extra = {k: doc[k] for k in ("reported_result", "effective_result", "normalization_warnings") if doc.get(k) is not None}
    return {"ok": True, "result": {"review_id": doc["id"], "path": path, "session": job["session"],
            "kind": doc["review_kind"], "result": doc["review_result"], **extra, "backend": doc["review_backend"],
            "model_observed": doc["reviewer_model"], "cost_usd": fields["cost_usd"],
            "permission_denials": fields.get("permission_denials", []), "structured": doc.get("review_payload")}}


def _finish_job(root: Path, job: dict, answer: dict, phase: str = "finished") -> dict:
    job = {**job, "status": "done", "phase": phase, "answer": answer, "finished_at": now()}
    _atomic_json(_job_file(root, job["ticket"]), job)
    return job


def _log_recovered(root: Path, job: dict, answer: dict) -> None:
    # Registration already charged ResearchDB. Restore only the append-only call log, if not present.
    log = root / CALL_LOG
    logged = []
    for line in log.read_text(encoding="utf-8").splitlines() if log.exists() else []:
        try:
            logged.append(json.loads(line))
        except ValueError:
            continue
    if not any(c.get("ticket") == job["ticket"] and c.get("outcome") == "ok" for c in logged):
        result = answer["result"]
        log_call(root, {"ticket": job["ticket"], "outcome": "ok", "recovered": True,
                        **{k: job["request"].get(k) for k in ("kind", "about", "dimension")},
                        **{k: result[k] for k in ("review_id", "session", "backend", "cost_usd")},
                        "model": result["model_observed"]})


def _recover_session(root: Path, job: dict, answer: dict) -> None:
    with _Lock(root):
        sessions = _sessions(root)
        session = job.get("session")
        if not session:
            # Allocation and job publication are separate atomic files. A killed process may have reserved
            # its session without publishing session/version to the ticket. The ownership tag is authoritative.
            owned = [name for name, state in sessions.items() if state.get("active_ticket") == job["ticket"]]
            if len(owned) != 1:
                return  # never guess at an unrelated or ambiguous session
            session = owned[0]
        state = sessions.get(session)
        if not state or state.get("active_ticket") not in (None, job["ticket"]):
            return
        version = job.get("version") or state.get("active_version")
        if not version or (state.get("active_version") and state["active_version"] != version):
            return
        # Keep the recovered pointer in the terminal ticket so repeated collection retains the audit trail.
        job.update(session=session, version=version)
        updated = {**state, "busy": False, "active_ticket": None, "active_version": None, "allocation_token": None}
        if answer.get("ok") and state["version"] <= version:
            updated.update(version=version, doc_id=answer["result"]["review_id"])
        if updated != state:
            sessions[session] = updated
            _save_sessions(root, sessions)


def _refresh_job(root: Path, job: dict) -> dict:
    """Under the job lock: observe liveness/recover a receipt, never start or resume a model call."""
    process = _JOB_CHILDREN.get(job["ticket"])
    if process is not None and process.poll() is not None:
        del _JOB_CHILDREN[job["ticket"]]
    if job["status"] != "running" or _worker_active(root, job):
        return job
    try:
        answer = _registered_answer(root, job)
    except (OSError, ValueError, KeyError, ResearchDBError):
        answer = None
    if answer is None:
        failure = ReviewError("REVIEW_UNAVAILABLE", "the background review was interrupted; inspect its session and "
                              "raw output before requesting another review (cost may be unknown); it was not restarted")
        answer = {"ok": False, "error": str(failure), "ticket": job["ticket"], "recovery_required": True}
        record_failure(root, {"ticket": job["ticket"], **{k: job.get("request", {}).get(k)
                               for k in ("kind", "about", "dimension")}}, failure)
    else:
        _log_recovered(root, job, answer)
    _recover_session(root, job, answer)
    return _finish_job(root, job, answer, "recovered" if answer.get("ok") else "interrupted")


def list_jobs(root: Path) -> list[dict]:
    """Persistent jobs, oldest first. A dead worker is a collectable failure, never endless pending."""
    with _JobLock(root):
        jobs = [_refresh_job(root, _read_job(root, path.stem)) for path in (root / JOBS_DIR).glob("RJ-*.json")]
    return sorted(({k: j.get(k) for k in ("ticket", "status", "phase", "started_at", "finished_at", "argv")}
                   for j in jobs), key=lambda j: (j["started_at"], j["ticket"]))


def wait_job(root: Path, ticket: str, wait_s: float) -> dict:
    """Return current state immediately by default; an explicit bounded wait never owns the worker."""
    deadline = time.monotonic() + max(0.0, min(float(wait_s), MAX_CALL_S))
    while True:
        with _JobLock(root):
            job = _refresh_job(root, _read_job(root, ticket))
        remaining = deadline - time.monotonic()
        if job["status"] != "running" or remaining <= 0:
            return job
        time.sleep(min(0.1, remaining))


def _job_answer(job: dict) -> tuple[dict, int]:
    if job["status"] == "running":
        return ({"ok": True, "pending": True, "ticket": job["ticket"], "started_at": job["started_at"],
                 "next": f"continue independent work; collect research_review ticket {job['ticket']} when needed "
                         "(collection returns immediately unless a wait is requested); do not restart this review"}, 0)
    return {**job["answer"], "ticket": job["ticket"]}, (0 if job["answer"].get("ok") else 2)


def _run_job(cwd: Path, root: Path, ticket: str) -> int:
    """A single-use worker lease prevents duplicate dispatch even across processes or repeated run-job calls."""
    path = _job_file(root, ticket)
    with _lease_path(root, ticket).open("a") as lease:
        with _JobLock(root):
            # Liveness probes hold the lease only under this lock, so it is busy here only while another worker
            # owns the job.
            try:
                fcntl.flock(lease, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:
                return 0
            job = _read_job(root, ticket)
            if job["status"] != "running" or job.get("worker_started_at"):
                return 0  # a claimed/interrupted job is never replayed
            job = {**job, "phase": "reviewing", "worker_started_at": now(), "worker_pid": os.getpid()}
            _atomic_json(path, job)
        try:
            call = _job_call_args(job["argv"])
            call.deadline_s = None
            answer, _ = _call(cwd, root, call, job_ticket=ticket, request_key=job.get("request_key"))
        except BaseException as exc:  # noqa: BLE001 — publish interruptions too; SIGKILL is recovered on collection
            current = _read_job(root, ticket)
            try:
                answer = _registered_answer(root, current)
            except (OSError, ValueError, KeyError, ResearchDBError):
                answer = None
            if answer:
                _log_recovered(root, current, answer)
            else:
                failure = ReviewError("REVIEW_UNAVAILABLE", f"the background review stopped: {type(exc).__name__}: {exc}")
                record_failure(root, {"ticket": ticket, **{k: job.get("request", {}).get(k)
                                       for k in ("kind", "about", "dimension")}}, failure)
                answer = {"ok": False, "error": str(failure), "ticket": ticket, "recovery_required": True}
        with _JobLock(root):
            current = _read_job(root, ticket)
            if current["status"] == "running":
                _recover_session(root, current, answer)
                _finish_job(root, current, answer)
        return 0


def _parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--kind", choices=REVIEW_KINDS)
    p.add_argument("--brief")
    p.add_argument("--about")
    p.add_argument("--dimension", choices=list(RECHECK_DIMENSIONS))
    p.add_argument("--evaluation")
    p.add_argument("--code-ref", help="code_review: the commit the reviewer reads")
    p.add_argument("--session", help="continue this review session (RV-xxxx): a new version of its review")
    p.add_argument("--evidence-set", help="a follow-up round: the manifest literature_followup wrote for the earlier "
                                          "receipt (cache/literature/followup/<review>/manifest.json)")
    p.add_argument("--add-dir", action="append", default=[], help="Claude Code backend: another readable directory")
    p.add_argument("--actor", default="rld/main")
    p.add_argument("--deadline-s", type=int, help="the host's limit on this process (seconds); the call ends before it")
    p.add_argument("--background", action="store_true",
                   help="return a persistent, deduplicated ticket immediately; only wait when --wait-s is explicitly set")
    p.add_argument("--ticket", help="collect a background review: wait at most --wait-s for its answer")
    p.add_argument("--wait-s", type=float, default=0.0)
    p.add_argument("--list-jobs", action="store_true", help="background review jobs and their state")
    p.add_argument("--run-job", help=argparse.SUPPRESS)
    return p


def _call(cwd: Path, root: Path, args, *, job_ticket: str | None = None,
          request_key: str | None = None) -> tuple[dict, int]:
    entry = {"kind": args.kind, "about": args.about, "dimension": args.dimension, "session": args.session,
             **({"ticket": job_ticket} if job_ticket else {})}
    try:
        result = review(cwd, args.kind, args.brief, args.about, args.dimension, args.evaluation, args.session,
                        args.add_dir, args.actor, args.code_ref, args.deadline_s, args.evidence_set,
                        job_ticket=job_ticket, request_key=request_key)
    except ReviewError as exc:
        record_failure(root, entry, exc)
        return {"ok": False, "error": str(exc)}, 2
    log_call(root, {**entry, "outcome": "ok", "review_id": result["review_id"], "session": result["session"],
                    "backend": result["backend"], "model": result["model_observed"], "cost_usd": result["cost_usd"]})
    return {"ok": True, "result": result}, 0


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    args = _parser().parse_args(argv)
    cwd = tree.find_project(Path.cwd())
    try:
        root = Path(tree.read_marker(cwd)["root"])
    except Exception as exc:  # noqa: BLE001 — reported as JSON like the other tools
        print(json.dumps({"ok": False, "error": f"REVIEW_UNAVAILABLE: no research project here ({exc})"}))
        return 2
    try:
        if args.run_job:
            return _run_job(cwd, root, args.run_job)
        if args.list_jobs:
            print(json.dumps({"ok": True, "jobs": list_jobs(root)}, ensure_ascii=False))
            return 0
        if args.ticket:
            answer, code = _job_answer(wait_job(root, args.ticket, args.wait_s))
            print(json.dumps(answer, ensure_ascii=False))
            return code
        missing = [k for k in ("kind", "brief", "about") if not getattr(args, k)]
        if missing:
            print(json.dumps({"ok": False, "error": f"REVIEW_INVALID: missing --{', --'.join(missing)}"}))
            return 2
        if args.background:
            forwarded = [a for a in argv if a != "--background"]
            ticket = start_job(cwd, root, forwarded)
            answer, code = _job_answer(wait_job(root, ticket, args.wait_s))
            print(json.dumps(answer, ensure_ascii=False))
            return code
    except ReviewError as exc:
        print(json.dumps({"ok": False, "error": str(exc)}, ensure_ascii=False))
        return 2
    answer, code = _call(cwd, root, args)
    print(json.dumps(answer, ensure_ascii=False))
    return code


if __name__ == "__main__":
    sys.exit(main())
