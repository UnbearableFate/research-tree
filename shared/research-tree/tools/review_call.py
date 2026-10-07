"""Cross-model, non-interactive review (plans/design 09): one deterministic wrapper for every Type-B review.

    review_call.py --kind <triage|novelty_precheck|critical_review|proposal_review|ablation_plan|code_review|
                           candidate_recheck>
                   --brief <file under the research root, e.g. docs/reviews/briefs/H-0001-numbers.v1.md>
                   --about <candidate or node id> [--dimension D --evaluation EV-xxxx] [--session RV-xxxx]
                   [--add-dir DIR ...]

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
import fcntl
import json
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

import discovery  # noqa: E402
import research_tree as tree  # noqa: E402
from research_db import (CANDIDATE_ID_RE, RECHECK_DIMENSIONS, REVIEW_KINDS, ResearchDB,  # noqa: E402
                         ResearchDBError)

REVIEWS_DIR = Path(__file__).resolve().parent.parent / "schema" / "reviews"
PROMPT = ("Read the brief at {brief} and follow it. Executor notes are not evidence beyond the files they cite. "
          "End with exactly one ```json block that matches the schema in your instructions.")
FOLLOW_UP = ("Your answer did not contain one valid JSON block for the schema ({problem}). Output only that ```json "
             "block now, nothing else.")
THINKING_TO_EFFORT = {"off": "low", "minimal": "low", "low": "low", "medium": "medium", "high": "high",
                      "xhigh": "xhigh", "max": "max"}
JSON_BLOCK_RE = re.compile(r"```json[ \t]*\n(.*?)```", re.S)
CALL_LOG = Path("logs") / "review_calls.jsonl"
# One call's whole wall time is capped (both rounds and the prechecks); the hosts wait a little longer than this.
MAX_CALL_S = 3600
CODE_SUFFIXES = (".py", ".pyx", ".c", ".cc", ".cpp", ".cu", ".h", ".hpp", ".rs", ".go", ".jl", ".java", ".js",
                 ".ts", ".sh", ".lua", ".r", ".m", ".scala")


class ReviewError(Exception):
    """code is REVIEW_UNAVAILABLE, REVIEW_INVALID or REVIEW_BUDGET."""

    def __init__(self, code: str, message: str, cost: float = 0.0):
        super().__init__(f"{code}: {message}")
        self.code, self.cost = code, cost


def now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


family = discovery.family  # one model-family table for every review decision


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


def _run(cmd: list[str], cwd: Path, timeout: int, deadline: float | None = None) -> subprocess.CompletedProcess:
    if deadline is not None:
        timeout = int(min(timeout, deadline - time.monotonic()))
        if timeout <= 0:
            raise ReviewError("REVIEW_UNAVAILABLE", f"the review call reached its overall deadline before {cmd[0]} ran")
    try:
        return subprocess.run(cmd, cwd=cwd, capture_output=True, text=True, timeout=timeout, check=False,
                              stdin=subprocess.DEVNULL)
    except subprocess.TimeoutExpired:
        raise ReviewError("REVIEW_UNAVAILABLE", f"{cmd[0]} did not answer within {timeout} s") from None
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
        out = _run(cmd + [prompt], self.root, self.timeout, self.deadline)
        return self.parse(out.stdout, out.stderr), out.stdout

    def parse(self, stdout: str, stderr: str) -> dict:
        end = None
        for line in stdout.splitlines():
            try:
                event = json.loads(line)
            except json.JSONDecodeError:
                continue
            if event.get("type") == "turn_end":
                end = event
        rec = {"backend": "pi", "provider": self.provider, "model_requested": self.model, "ok": False,
               "error": None, "text": "", "structured": None, "cost_usd": 0.0, "usage": None,
               "model_observed": None, "terminal_reason": None, "permission_denials": []}
        if end is None:
            rec["error"] = f"no turn_end event; stderr: {stderr.strip()[:300]}"
            return rec
        msg = end.get("message") or {}
        usage = msg.get("usage") or {}
        rec.update(text="".join(c.get("text", "") for c in msg.get("content") or [] if c.get("type") == "text"),
                   cost_usd=float((usage.get("cost") or {}).get("total") or 0), usage=usage,
                   model_observed=f"{msg.get('provider')}/{msg.get('model')}",
                   terminal_reason=msg.get("stopReason"))
        rec["ok"] = msg.get("stopReason") == "stop"
        if not rec["ok"]:
            rec["error"] = msg.get("errorMessage") or f"stopReason {msg.get('stopReason')}"
        return rec


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
               "--append-system-prompt-file", str(system_file), "--json-schema", json.dumps(schema)]
        for d in add_dirs:
            cmd += ["--add-dir", d]
        if budget is not None:
            cmd += ["--max-budget-usd", f"{max(budget, 0.01):.2f}"]
        return cmd + [prompt]

    def call(self, prompt: str, session: str, system_file: Path, first: bool, add_dirs: list[str],
             schema: dict, budget: float | None) -> tuple[dict, str]:
        out = _run(self.command(prompt, session, system_file, first, add_dirs, schema, budget), self.root,
                   self.timeout, self.deadline)
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
    if kind == "novelty_precheck":
        named = {p.get("id") for p in data["closest_prior_work"]} | {p.get("title") for p in data["closest_prior_work"]}
        if data["verdict"] == "ABANDON" and (not data.get("abandon_paper") or data["abandon_paper"] not in named):
            found.append("ABANDON names the paper that already contains the result (abandon_paper, also in "
                         "closest_prior_work); without it the verdict is invalid, not negative")
    if kind == "candidate_recheck":
        if data["dimension"] != dimension:
            found.append(f"dimension is {data['dimension']!r}, the brief asked for {dimension!r}")
        if data["result"] == "pass" and not data["evidence_paths"]:
            found.append("a pass lists the files it relied on (evidence_paths)")
        if dimension == "method_code" and data["result"] == "pass" and not any(
                Path(p).suffix.lower() in CODE_SUFFIXES for p in data["evidence_paths"]):
            found.append("method_code pass without reading code: cite the code files checked (K06; reading the "
                         "report alone does not verify method-code alignment)")
        if data["result"] == "not_applicable" and not data["reason"].strip():
            found.append("not_applicable needs the reason the dimension is not part of the claim")
    return found


def result_of(kind: str, data: dict) -> str:
    """The review's recorded conclusion; the positive/negative reading follows 09 §3."""
    if kind == "candidate_recheck":
        return data["result"]
    if kind == "novelty_precheck":
        return data["verdict"]
    if kind == "critical_review":
        return data["stance"]
    if kind == "proposal_review":
        return data["verdict"]
    if kind == "code_review":
        blocking = [i for i in data["issues"] if i["severity"] in ("CRITICAL", "MAJOR")]
        return "blocking" if blocking or not data["method_implemented"] else "clear"
    return "ranked" if kind == "triage" else "planned"


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
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(sessions, ensure_ascii=False, indent=1), encoding="utf-8")
    tmp.replace(path)


def _next_rv(root: Path, sessions: dict) -> str:
    numbers = [int(m.group(1)) for p in (root / "docs" / "reviews").glob("RV-*.v*.md")
               if (m := re.match(r"RV-(\d+)\.v\d+\.md$", p.name))]
    numbers += [int(k.split("-")[1]) for k in sessions]
    return f"RV-{max(numbers, default=0) + 1:04d}"


def _front_matter(fields: dict) -> str:
    return "---\n" + "".join(f"{k}: {json.dumps(v, ensure_ascii=False)}\n" for k, v in fields.items()) + "---\n"


def review(cwd: Path, kind: str, brief: str, about: str, dimension: str | None = None,
           evaluation: str | None = None, session: str | None = None, add_dirs: list[str] | None = None,
           actor: str = "rld/main", code_ref: str | None = None, deadline_s: int | None = None) -> dict:
    if not actor.startswith("rld/"):
        raise ReviewError("REVIEW_UNAVAILABLE", "the Leader (rld) organizes reviews; other roles ask the Leader")
    if kind not in REVIEW_KINDS:
        raise ReviewError("REVIEW_INVALID", f"kind is one of {REVIEW_KINDS}")
    if kind == "candidate_recheck" and (dimension not in RECHECK_DIMENSIONS or not evaluation):
        raise ReviewError("REVIEW_INVALID", f"a candidate_recheck names --dimension ({', '.join(RECHECK_DIMENSIONS)}) "
                                            "and --evaluation (the evaluation it rechecks)")
    if kind == "code_review" and not code_ref:
        raise ReviewError("REVIEW_INVALID", "a code_review names --code-ref, the commit the reviewer reads")
    marker = tree.read_marker(cwd)
    root = Path(marker["root"])
    conf = tree.show_config(cwd)["effective"]
    reviewer = (conf.get("models") or {}).get("reviewer")
    if not reviewer:
        raise ReviewError("REVIEW_UNAVAILABLE", "research-tree.yaml has no models.reviewer (configuration version 2)")
    alert = (conf.get("budget") or {}).get("review_usd_alert")
    so_far = spent(root)
    if alert is not None and so_far >= alert:
        raise ReviewError("REVIEW_BUDGET", f"review cost {so_far:.4f} USD reached budget.review_usd_alert {alert}; "
                                           "the user decides (raise it in research-tree.yaml and config apply)")
    backend = backend_for(reviewer, root)
    backend.precheck()
    if reviewer.get("require_cross_family", True):
        leader = leader_model(root)
        if family(leader) is None:
            raise ReviewError("REVIEW_UNAVAILABLE", f"the Leader's observed model ({leader or 'none recorded'}) "
                                                    "cannot be placed in a model family; require_cross_family")
        if family(leader) == family(reviewer["model"]):
            raise ReviewError("REVIEW_UNAVAILABLE", f"reviewer {reviewer['model']} is the Leader's family "
                                                    f"({leader}); require_cross_family refuses the call")
    brief_path = Path(brief) if Path(brief).is_absolute() else root / brief
    if not brief_path.is_file() or not brief_path.resolve().is_relative_to(root.resolve()):
        raise ReviewError("REVIEW_INVALID", f"the brief is a file under {root}: {brief}")
    schema = json.loads((REVIEWS_DIR / f"{kind}.schema.json").read_text(encoding="utf-8"))
    system_file = REVIEWS_DIR / f"{kind}.md"
    db = ResearchDB(Path(marker["db"]), "reviewer/" + backend.name)
    with ResearchDB(Path(marker["db"]), "rld/main").reader() as tx:
        if tx.get(about) is None and not CANDIDATE_ID_RE.fullmatch(about):
            raise ReviewError("REVIEW_INVALID", f"{about} is neither a record nor a discovery candidate (CAND-…)")

    with _Lock(root):
        rv, uid, version, first, state = _allocate(root, session, kind, about, backend.name)
    log_call(root, {"kind": kind, "about": about, "dimension": dimension, "session": rv, "outcome": "started",
                    "backend": backend.name})  # a call the host kills stays visible
    # the whole call: both rounds within the reviewer's timeout, the hard cap, and the host's own process limit
    deadline = time.monotonic() + min(2 * int(reviewer["timeout_s"]) + 120, MAX_CALL_S, deadline_s or MAX_CALL_S)
    backend.deadline = deadline
    backend.code_ref = code_ref
    return _review(root, backend, reviewer, kind, brief_path, about, dimension, evaluation, add_dirs, schema,
                   system_file, db, alert, so_far, rv, uid, version, first, state)


def _allocate(root: Path, session: str | None, kind: str, about: str, backend: str) -> tuple:
    sessions = _sessions(root)
    if session:
        if session not in sessions:
            raise ReviewError("REVIEW_INVALID", f"no review session {session}")
        state = sessions[session]
        if (state["kind"], state["about"], state["backend"]) != (kind, about, backend):
            raise ReviewError("REVIEW_INVALID", f"{session} is a {state['kind']} of {state['about']} on "
                                                f"{state['backend']}")
        rv, uid, version, first = session, state["uuid"], state["version"] + 1, False
    else:
        rv, uid, version, first = _next_rv(root, sessions), str(uuid.uuid4()), 1, True
        state = {"uuid": uid, "kind": kind, "about": about, "backend": backend, "version": 0, "doc_id": None}
    if session and state.get("busy"):
        raise ReviewError("REVIEW_INVALID", f"{session} has a round in progress")
    sessions[rv] = {**state, "busy": True}
    _save_sessions(root, sessions)  # the number is taken before the call: a failed call never reuses it
    return rv, uid, version, first, state


def _review(root, backend, reviewer, kind, brief_path, about, dimension, evaluation, add_dirs, schema, system_file,
            db, alert, so_far, rv, uid, version, first, state) -> dict:
    try:
        return _run_review(root, backend, reviewer, kind, brief_path, about, dimension, evaluation, add_dirs, schema,
                           system_file, db, alert, so_far, rv, uid, version, first, state)
    finally:
        with _Lock(root):
            sessions = _sessions(root)
            sessions[rv] = {**sessions.get(rv, state), "busy": False}
            _save_sessions(root, sessions)


def _run_review(root, backend, reviewer, kind, brief_path, about, dimension, evaluation, add_dirs, schema,
                system_file, db, alert, so_far, rv, uid, version, first, state) -> dict:
    raw_dir = root / "cache" / "reviews"
    raw_dir.mkdir(parents=True, exist_ok=True)
    budget = None if alert is None else alert - so_far
    prompt = PROMPT.format(brief=brief_path.resolve())
    rec, raw = backend.call(prompt, uid, system_file, first, add_dirs or [], schema, budget)
    suffix = "jsonl" if backend.name == "pi" else "json"
    (raw_dir / f"{rv}.v{version}.{suffix}").write_text(raw, encoding="utf-8")
    cost = rec["cost_usd"]
    if not rec["ok"]:
        raise ReviewError("REVIEW_UNAVAILABLE", f"{backend.name}: {rec['error']}", cost)
    if rec["model_observed"] != reviewer["model"]:
        raise ReviewError("REVIEW_INVALID", f"the review ran on {rec.get('observed_models') or rec['model_observed']}, "
                                            f"not the requested {reviewer['model']}", cost)
    data = extract(rec)
    found = problems(kind, data, schema, dimension)
    if found:  # one follow-up in the same session, then invalid
        retry, raw2 = backend.call(FOLLOW_UP.format(problem="; ".join(found)[:500]), uid, system_file, False,
                                   add_dirs or [], schema, budget)
        (raw_dir / f"{rv}.v{version}.retry.{suffix}").write_text(raw2, encoding="utf-8")
        cost += retry["cost_usd"]
        if not retry["ok"]:
            raise ReviewError("REVIEW_UNAVAILABLE", f"{backend.name}: {retry['error']}", cost)
        if retry["model_observed"] != reviewer["model"]:
            raise ReviewError("REVIEW_INVALID", f"the follow-up ran on {retry['model_observed']}", cost)
        data = extract(retry)
        found = problems(kind, data, schema, dimension)
        if found:
            raise ReviewError("REVIEW_INVALID", "; ".join(found)[:600], cost)
        rec["text"] += "\n\n(follow-up)\n" + retry["text"]
    result = result_of(kind, data)

    rel = f"reviews/{rv}.v{version}.md"
    fields = {"kind": kind, "about": about, "dimension": dimension, "evaluation_id": evaluation,
              "code_ref": getattr(backend, "code_ref", None), "result": result,
              "backend": backend.name, "provider": rec["provider"], "model_requested": reviewer["model"],
              "model_observed": rec["model_observed"], "thinking": reviewer["thinking"], "session": rv,
              "session_id": uid, "brief": str(brief_path.relative_to(root)), "terminal_reason": rec["terminal_reason"],
              "cost_usd": round(cost, 6), "usage": rec["usage"], "permission_denials": rec["permission_denials"],
              "raw": f"cache/reviews/{rv}.v{version}.{suffix}", "created_at": now()}
    body = (_front_matter({k: v for k, v in fields.items() if v is not None}) +
            f"\n# {kind}：{about}{'（' + dimension + '）' if dimension else ''}\n\n## 评审原文\n\n{rec['text'].strip()}\n\n"
            f"## 结构化结论\n\n```json\n{json.dumps(data, ensure_ascii=False, indent=1)}\n```\n")
    (root / "docs" / "reviews").mkdir(parents=True, exist_ok=True)
    with _Lock(root):
        if (root / "docs" / rel).exists():  # never overwrite a review
            raise ReviewError("REVIEW_INVALID", f"{rel} exists already", cost)
        (root / "docs" / rel).write_text(body, encoding="utf-8")
    try:
        doc_id = db.register_review(rel, f"{kind} {about}{' ' + dimension if dimension else ''}", kind, [about],
                                    result, rv, backend.name, rec["model_observed"], cost, dimension=dimension,
                                    evaluation_id=evaluation, supersedes=state.get("doc_id"),
                                    code_ref=getattr(backend, "code_ref", None),
                                    summary=f"{backend.name} {rec['model_observed']}: {result}")
    except ResearchDBError as exc:
        raise ReviewError("REVIEW_INVALID", f"not registered: {exc}", cost) from None
    with _Lock(root):
        sessions = _sessions(root)
        sessions[rv] = {**state, "version": version, "doc_id": doc_id, "busy": False}
        _save_sessions(root, sessions)
    return {"review_id": doc_id, "path": rel, "session": rv, "kind": kind, "result": result, "backend": backend.name,
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


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--kind", required=True, choices=REVIEW_KINDS)
    p.add_argument("--brief", required=True)
    p.add_argument("--about", required=True)
    p.add_argument("--dimension", choices=list(RECHECK_DIMENSIONS))
    p.add_argument("--evaluation")
    p.add_argument("--code-ref", help="code_review: the commit the reviewer reads")
    p.add_argument("--session", help="continue this review session (RV-xxxx): a new version of its review")
    p.add_argument("--add-dir", action="append", default=[], help="Claude Code backend: another readable directory")
    p.add_argument("--actor", default="rld/main")
    p.add_argument("--deadline-s", type=int, help="the host's limit on this process (seconds); the call ends before it")
    args = p.parse_args(argv)
    cwd = Path.cwd()
    try:
        root = Path(tree.read_marker(cwd)["root"])
    except Exception as exc:  # noqa: BLE001 — reported as JSON like the other tools
        print(json.dumps({"ok": False, "error": f"REVIEW_UNAVAILABLE: no research project here ({exc})"}))
        return 2
    entry = {"kind": args.kind, "about": args.about, "dimension": args.dimension, "session": args.session}
    try:
        result = review(cwd, args.kind, args.brief, args.about, args.dimension, args.evaluation, args.session,
                        args.add_dir, args.actor, args.code_ref, args.deadline_s)
    except ReviewError as exc:
        record_failure(root, entry, exc)
        print(json.dumps({"ok": False, "error": str(exc)}, ensure_ascii=False))
        return 2
    log_call(root, {**entry, "outcome": "ok", "review_id": result["review_id"], "session": result["session"],
                    "backend": result["backend"], "model": result["model_observed"], "cost_usd": result["cost_usd"]})
    print(json.dumps({"ok": True, "result": result}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
