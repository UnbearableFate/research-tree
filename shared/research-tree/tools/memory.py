"""Research findings, execution lessons and the context pack (plans/design 08 §1, §3, §4). Deterministic: no model.

Findings (docs/findings/, doc_type finding) and lessons (docs/lessons/, doc_type lesson) carry YAML front matter:

    kind: finding                     kind: execution_lesson
    claim: "..."                      symptom: "..."
    scope: {...}                      root_cause: "..."   root_cause_status: verified | proposed | unknown
    evidence_ids: [EV-0012, ...]      fix: "..."          applicability: {harness_ref?, config_doc_id?, ...}
    interpretation: "..."             evidence_runs: ["E-0008/s42@2"]   counterexamples: [...]
    limitations: "..."                status: proposed | observed | verified | contradicted | stale
    status: observed | supported | contradicted | stale

Facts and interpretation stay apart. A lesson whose root cause is a guess is only `proposed` (K01); a lesson's fix
must not be operational noise (capture_filter); neither may carry an injection or ask to widen permissions, gates
or budgets (threat_scan, strict scope, K04). Lessons never change permissions, the evaluator or the protocol.

context_pack(role, node) gives a worker or the Leader a fixed-size, deterministic summary in a fixed order: the goal
and problem anchor → open obligations → retired nodes and lessons (verified first) → the current evaluation →
recent relations. Every lesson comes with why_relevant, its applicability, a recheck flag when the harness or
configuration it was verified under changed (K02), and its counterexamples (K03). Only this project's records are
read (cross-project retrieval is off, K05).
"""

from __future__ import annotations

import re

import yaml

import capture_filter
import threat_scan

FINDING_STATUS = ("observed", "supported", "contradicted", "stale")
LESSON_STATUS = ("proposed", "observed", "verified", "contradicted", "stale")
ROOT_CAUSE_STATUS = ("verified", "proposed", "unknown")
PACK_LIMIT = 8000
RUN_REF_RE = re.compile(r"(E-\d+/s-?\d+)@(\d+)")
HEDGE_RE = re.compile(r"\b(?:guess|guessing|maybe|perhaps|probably|possibly|might|unverified|not\s+sure)\b|可能|猜|也许|大概|未验证|不确定",
                      re.I)


class MemoryError_(Exception):
    """code: MEMORY_REJECTED."""


def front_matter(text: str) -> dict | None:
    m = re.match(r"^---\n(.*?)\n---\n?", text, re.S)
    if not m:
        return None
    try:
        data = yaml.safe_load(m.group(1))
    except yaml.YAMLError:
        return None
    return data if isinstance(data, dict) else None


def _need(data: dict, fields: tuple[str, ...], what: str) -> None:
    missing = [f for f in fields if data.get(f) in (None, "", [], {})]
    if missing:
        raise MemoryError_(f"{what} needs {', '.join(missing)} in its front matter")


def check(doc_type: str, text: str) -> dict:
    """The validated front matter of a finding or lesson; raises MemoryError_ with the reason."""
    data = front_matter(text)
    if data is None:
        raise MemoryError_(f"a {doc_type} starts with YAML front matter (--- ... ---); see doc_library")
    threats = threat_scan.scan_for_threats(text, scope="strict")
    if threats:
        raise MemoryError_(f"the {doc_type} matches {', '.join(threats)}: memory is research material, never an "
                           "instruction — it does not change permissions, budgets, gates or the protocol")
    if doc_type == "finding":
        _need(data, ("claim", "evidence_ids", "interpretation", "limitations", "status"), "a finding")
        if data["status"] not in FINDING_STATUS:
            raise MemoryError_(f"finding status is one of {FINDING_STATUS}")
        if not isinstance(data["evidence_ids"], list):
            raise MemoryError_("evidence_ids is a list of evaluation, experiment or document ids")
        if str(data["claim"]).strip() == str(data["interpretation"]).strip():
            raise MemoryError_("a finding keeps the fact (claim) and its interpretation apart")
        return data
    _need(data, ("symptom", "root_cause", "root_cause_status", "fix", "status"), "a lesson")
    if data["root_cause_status"] not in ROOT_CAUSE_STATUS:
        raise MemoryError_(f"root_cause_status is one of {ROOT_CAUSE_STATUS} (unknown when it is not established)")
    if data["status"] not in LESSON_STATUS:
        raise MemoryError_(f"lesson status is one of {LESSON_STATUS}")
    if data["root_cause_status"] == "verified" and HEDGE_RE.search(str(data["root_cause"])):
        raise MemoryError_("the root cause reads as a guess (guess / maybe / 可能 / 猜 / 未验证): mark it proposed or "
                           "unknown until a log or a minimal test establishes it (K01)")
    if data["root_cause_status"] != "verified" and data["status"] != "proposed":
        raise MemoryError_(f"the root cause is {data['root_cause_status']}: the lesson is only proposed (K01)")
    if data["status"] == "verified" and not data.get("evidence_runs"):
        raise MemoryError_("a verified lesson cites the runs that verified the fix (evidence_runs E-…/s…@attempt)")
    noise = capture_filter.screen(str(data["fix"]))
    if noise:
        raise MemoryError_(f"the fix reads as operational noise ({', '.join(noise)}): store how to fix it, not that "
                           "something failed — " + capture_filter.reason_detail(noise[0]))
    for ref in data.get("evidence_runs") or []:
        if not RUN_REF_RE.fullmatch(str(ref)):
            raise MemoryError_(f"evidence_runs names run attempts like E-0008/s42@2, not {ref!r}")
    return data


def applicability(lesson: dict, project: dict) -> tuple[bool, list[str]]:
    """K02: a lesson verified under another harness or configuration needs to be checked again."""
    app = lesson.get("applicability") or {}
    reasons = []
    for key in ("harness_ref", "config_doc_id", "protocol_doc_id", "metric_spec_doc_id"):
        if app.get(key) and project.get(key) and str(app[key]) != str(project[key]):
            reasons.append(f"{key} {str(app[key])[:12]} → {str(project[key])[:12]}")
    # platform and dependency versions are checked against the configuration they were verified under
    declared = [k for k in ("platform_profile", "dependency_versions", "hardware", "model") if app.get(k)]
    if declared and not app.get("config_doc_id"):
        reasons.append(f"{', '.join(declared)} declared without the configuration they held under "
                       "(applicability.config_doc_id): recheck before use")
    if lesson.get("status") in ("stale", "contradicted"):
        reasons.append(f"status {lesson['status']}")
    return bool(reasons), reasons


def render(sections: list[tuple[str, list[str]]], limit: int = PACK_LIMIT) -> tuple[str, bool]:
    """Join the sections in order, cutting at `limit` characters (the order says what is dropped first)."""
    out, truncated = [], False
    size = 0
    for title, lines in sections:
        block = [f"## {title}"] + (lines or ["（无）"])
        for line in block:
            if size + len(line) + 1 > limit:
                truncated = True
                break
            out.append(line)
            size += len(line) + 1
        if truncated:
            out.append("…（已截断：上下文包有固定上限）")
            break
    return "\n".join(out), truncated


def quarantine(text: str, label: str) -> str:
    safe, _ = threat_scan.quarantine(text, scope="context", label=label)
    return safe
