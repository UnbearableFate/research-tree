"""What a review receipt concludes, as the system reads it (plans/research-tree-implementation-and-real-scenarios.md
S4 §8.1, §8.3). Pure functions: review_call.py (before registering) and research_db.register_review (when
registering) use the same ones, so no entry point accepts a top-level pass the checklist contradicts.

A candidate_recheck receipt names one dimension and a checklist with exactly the items of that dimension. The
effective result follows one rule (fail > uncertain > pass; not_applicable only for a dimension the frozen protocol
lets the current claim exempt); the reviewer's own top-level result is kept as reported_result, and every
disagreement is a warning, never a silent override. A receipt whose checklist is missing, duplicated or foreign is
structurally invalid (REVIEW_INVALID) — that is the only case a reviewer is asked to rewrite its answer.

Model identity: a provider is only a channel; the family is read from the model's own name (claude-… is
Anthropic's whether reached directly, through an aggregator or a cloud), and an unknown family is never assumed.
"""

from __future__ import annotations

import re

RESULTS = ("pass", "fail", "uncertain", "not_applicable")
# the checklist items every candidate_recheck of a dimension answers (and only those)
RECHECK_ITEMS = {
    "numbers": ("A", "B", "C", "D", "E", "F"),
    "protocol": ("P1", "P2", "P3", "P4", "P5"),
    "method_code": ("D", "G", "M"),
    "novelty": ("H",),
    "theory": ("I",),
}
ITEM_MEANING = {
    "A": "ground truth from the dataset split", "B": "no self-normalized scores", "C": "traceable numbers",
    "D": "the reported metric code is called", "E": "wording matches the evidence", "F": "evaluation type label",
    "G": "the declared intervention is in the executed code", "M": "the run's configuration is the method's",
    "H": "novelty against the closest prior work", "I": "argument, assumptions and scope; no unfounded guarantee",
    "P1": "commands", "P2": "versions", "P3": "training amount", "P4": "data", "P5": "evaluation path and split",
}
# dimensions an empirical result can never exempt as a whole; the others only when the protocol allows it and the
# current claim declares it
NEVER_EXEMPT = ("numbers", "protocol", "method_code")
EXEMPTIBLE = ("novelty", "theory")


def applicability(protocol: dict | None, declared: dict | None) -> dict:
    """Per dimension: required, whether the protocol allows a whole-dimension exemption, and the claim's own
    declaration (scope_ref, reason). declared is the claim's '评审适用性' block: {dimension: {"required": false,
    "scope_ref": ..., "reason": ...}}; anything it says about numbers/protocol/method_code is ignored."""
    allowed = ((protocol or {}).get("review_applicability") or {})
    out = {}
    for dim in RECHECK_ITEMS:
        entry = {"required": True, "exempt_allowed": False, "exempt": False}
        if dim in EXEMPTIBLE:
            entry["exempt_allowed"] = bool((allowed.get(dim) or {}).get("exemptible"))
            mine = (declared or {}).get(dim) or {}
            if mine.get("required") is False and str(mine.get("reason") or "").strip():
                entry.update(scope_ref=mine.get("scope_ref"), reason=mine["reason"])
                if entry["exempt_allowed"]:
                    entry.update(required=False, exempt=True)
        out[dim] = entry
    return out


def structure_problems(dimension: str, data: dict) -> list[str]:
    """Why a candidate_recheck receipt is structurally invalid (missing, duplicated or foreign items)."""
    want = RECHECK_ITEMS.get(dimension)
    if want is None:
        return [f"dimension {dimension!r} is not one of {list(RECHECK_ITEMS)}"]
    items = data.get("checklist")
    if not isinstance(items, list) or not items:
        return [f"checklist answers the items of {dimension}: {', '.join(want)}"]
    seen, problems = [], []
    for entry in items:
        if not isinstance(entry, dict) or entry.get("result") not in RESULTS:
            problems.append(f"checklist entry {entry!r} needs item, result and note")
            continue
        seen.append(entry.get("item"))
    foreign = sorted({i for i in seen if i not in want}, key=str)
    duplicated = sorted({i for i in seen if seen.count(i) > 1}, key=str)
    missing = [i for i in want if i not in seen]
    if foreign:
        problems.append(f"items {foreign} do not belong to {dimension} ({', '.join(want)})")
    if duplicated:
        problems.append(f"items {duplicated} appear more than once")
    if missing:
        problems.append(f"items {missing} of {dimension} are missing")
    for entry in items:
        if isinstance(entry, dict) and not str(entry.get("note") or "").strip():
            problems.append(f"item {entry.get('item')} has no note")
    return problems


def normalize_recheck(dimension: str, data: dict, applies: dict | None = None) -> dict:
    """{reported_result, effective_result, warnings, findings, invalid}: the one rule of S4 §8.1. findings are the
    failed or uncertain items (an item 'summary' holds a top-level fail with no failed item)."""
    reported = data.get("result")
    invalid = structure_problems(dimension, data)
    if reported not in RESULTS:
        invalid.append(f"result {reported!r} is not one of {RESULTS}")
    if invalid:
        return {"reported_result": reported, "effective_result": None, "warnings": [], "findings": [],
                "invalid": invalid}
    applies = (applies or applicability(None, None)).get(dimension) or {"required": True, "exempt": False}
    items = {e["item"]: e for e in data["checklist"]}
    results = [e["result"] for e in items.values()]
    warnings = []
    findings = [{"item": i, "result": e["result"], "note": e["note"]} for i, e in items.items()
                if e["result"] in ("fail", "uncertain")]
    if "fail" in results or reported == "fail":
        effective = "fail"
        if reported == "fail" and "fail" not in results:
            findings.insert(0, {"item": "summary", "result": "fail", "note": str(data.get("reason") or "")})
    elif "uncertain" in results or reported == "uncertain":
        effective = "uncertain"
        if reported == "uncertain" and "uncertain" not in results:
            findings.insert(0, {"item": "summary", "result": "uncertain", "note": str(data.get("reason") or "")})
    elif all(r == "not_applicable" for r in results):
        if applies.get("exempt") and reported == "not_applicable":
            effective = "not_applicable"
        else:
            effective = "uncertain"
            warnings.append("NOT_APPLICABLE_UNAUTHORIZED: every item is N/A but the frozen protocol and the current "
                            f"claim do not exempt {dimension}")
    elif reported == "not_applicable":
        effective = "uncertain"  # a top-level N/A over applicable items that passed
        warnings.append("NOT_APPLICABLE_UNAUTHORIZED: a top-level N/A over applicable items")
    else:
        effective = "pass"
    if reported != effective and not (reported in ("pass", "not_applicable") and effective == "uncertain"
                                      and any(w.startswith("NOT_APPLICABLE") for w in warnings)):
        warnings.append(f"SUMMARY_CHECKLIST_MISMATCH: reported {reported}, the checklist gives {effective}")
    if applies.get("exempt") and effective in ("fail", "uncertain"):
        warnings.append(f"APPLICABILITY_CONFLICT: {dimension} is exempted for the current claim, but the reviewer "
                        "found an applicable problem; the finding stands")
    return {"reported_result": reported, "effective_result": effective, "warnings": warnings, "findings": findings,
            "invalid": []}


# -- model identity --------------------------------------------------------------------------------------------

# channels that carry other vendors' models: their name says nothing about the family
AGGREGATORS = {"openrouter", "bedrock", "amazon-bedrock", "aws", "vertex", "vertex_ai", "google-vertex",
               "google-vertex-anthropic", "azure", "azure-openai", "together", "together_ai", "groq", "fireworks",
               "fireworks_ai", "github-copilot", "copilot", "litellm", "proxy", "deepinfra", "perplexity",
               "cloudflare", "ollama", "lmstudio", "requesty", "vercel"}
VENDORS = {"anthropic": "anthropic", "openai": "openai", "google": "google", "gemini": "google",
           "deepseek": "deepseek", "mistral": "mistral", "xai": "xai", "meta": "meta", "qwen": "alibaba",
           "alibaba": "alibaba", "moonshot": "moonshot", "zhipu": "zhipu"}
NAME_FAMILIES = (("claude", "anthropic"), ("gpt", "openai"), ("chatgpt", "openai"), ("codex", "openai"),
                 ("o1", "openai"), ("o3", "openai"), ("o4", "openai"), ("gemini", "google"), ("gemma", "google"),
                 ("deepseek", "deepseek"), ("llama", "meta"), ("mistral", "mistral"), ("mixtral", "mistral"),
                 ("codestral", "mistral"), ("magistral", "mistral"), ("qwen", "alibaba"), ("qwq", "alibaba"),
                 ("grok", "xai"), ("kimi", "moonshot"), ("glm", "zhipu"))
_REGION = re.compile(r"^(us|eu|apac|global|ap)\.")


def parse_model(model: str | None) -> dict:
    """{provider, model_id, family}: provider is the channel named first (None for a bare id); model_id the
    vendor's own model name, lower case, without channel, region or vendor prefixes; family from the name, else
    from a provider that is itself the vendor; None when it cannot be told."""
    if not model or not isinstance(model, str):
        return {"provider": None, "model_id": None, "family": None}
    parts = model.strip().lower().split("/")
    provider = parts[0] if len(parts) > 1 else None
    name = parts[-1]
    name = _REGION.sub("", name)
    for vendor in ("anthropic.", "meta.", "mistral.", "amazon.", "google.", "openai."):
        if name.startswith(vendor):
            name = name[len(vendor):]
    name = name.split("@")[0].split(":")[0]  # version pins and tags (…-v1:0, llama3:8b, …@20250101)
    name = re.sub(r"-v\d+$", "", name)  # a cloud's deployment version of the same model
    fam = next((f for prefix, f in NAME_FAMILIES if re.match(rf"{re.escape(prefix)}([-_.0-9]|$)", name)), None)
    if fam is None:
        for vendor in parts[:-1]:
            if vendor in VENDORS and vendor not in AGGREGATORS:
                fam = VENDORS[vendor]
                break
    return {"provider": provider, "model_id": name, "family": fam}


def family(model: str | None) -> str | None:
    return parse_model(model)["family"]


def same_model(a: str | None, b: str | None) -> bool:
    """The same vendor model, whatever channel each names."""
    pa, pb = parse_model(a), parse_model(b)
    return pa["model_id"] is not None and pa["model_id"] == pb["model_id"] and pa["family"] == pb["family"]
