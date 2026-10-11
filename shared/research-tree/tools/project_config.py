"""The project configuration, research-tree.yaml in the project directory.

It says where development and experiments run (text handed to the RLD and every worker, plus skills preloaded
into workers), the resource budget, the stage-1 gates and the subagents' models. Keys left out take the values
of schema/config.template.yaml, which is also the file /research-tree init writes. The budget and gate values
are mirrored into the database's project record (db_fields), where the API enforces them.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import sys

import yaml
from jsonschema import Draft202012Validator

sys.path.insert(0, str(Path(__file__).resolve().parent))
import metrics  # noqa: E402

CONFIG_NAME = "research-tree.yaml"
SCHEMA_DIR = Path(__file__).resolve().parent.parent / "schema"
CONFIG_VERSION = 3
TEMPLATE_PATH = SCHEMA_DIR / "config.template.yaml"
SCHEMA_PATH = SCHEMA_DIR / "config.schema.json"
WALLTIME_RE = re.compile(r"^(?=\d)(?:(\d+)h)?(?:(\d+)m)?(?:(\d+)s)?$")
CLAUDE_DISPLAY_RE = re.compile(r"(?:claude\s+)?(haiku|sonnet|opus)\s+(\d+)(?:[.-](\d+))?", re.IGNORECASE)
GPT_DISPLAY_RE = re.compile(r"gpt[\s-]+(\d+(?:\.\d+)?)(?:[\s-]+([a-z]+(?:[\s-]+[a-z0-9]+)*))?", re.IGNORECASE)


def _normalize_models(config: dict) -> None:
    """Resolve display names once, before validation and either host consumes the config."""
    models = config.get("models")
    if not isinstance(models, dict):
        return  # schema validation reports malformed configuration
    for role in ("ui", "worker", "explorer", "architect", "analyst", "reviewer"):
        spec = models.get(role)
        if not isinstance(spec, dict) or not isinstance(spec.get("model"), str):
            continue
        value = spec["model"].strip()
        name = value.removeprefix("anthropic/") if role == "reviewer" else value
        match = CLAUDE_DISPLAY_RE.fullmatch(name)
        if match:
            family, major, minor = match.groups()
            family = family.lower()
            # The user-facing Haiku 5 name denotes the pinned 5.5 model.
            if (family, major, minor) == ("haiku", "5", None):
                minor = "5"
            version = major + (f"-{minor}" if minor is not None else "")
            name = f"claude-{version}-{family}" if int(major) < 4 else f"claude-{family}-{version}"
            value = f"anthropic/{name}" if role == "reviewer" else name
        else:
            name = value.removeprefix("openai/") if role == "reviewer" else value
            match = GPT_DISPLAY_RE.fullmatch(name)
            if match:
                version, variant = match.groups()
                name = "gpt-" + version
                if variant:
                    name += "-" + re.sub(r"[\s-]+", "-", variant.lower())
                value = f"openai/{name}" if role == "reviewer" else name
            elif role != "reviewer" and value.lower() in ("inherit", "haiku", "sonnet", "opus"):
                value = value.lower()
        spec["model"] = value


class ConfigError(Exception):
    pass


def template_text() -> str:
    return TEMPLATE_PATH.read_text(encoding="utf-8")


def defaults() -> dict:
    return yaml.safe_load(TEMPLATE_PATH.read_text(encoding="utf-8"))


def _merge(base: dict, given: dict) -> dict:
    merged = dict(base)
    for key, value in given.items():
        merged[key] = _merge(base[key], value) if isinstance(base.get(key), dict) and isinstance(value, dict) else value
    return merged


def parse(text: str, source: str = CONFIG_NAME) -> dict:
    """The configuration in `text`, completed from the template and validated."""
    try:
        given = yaml.safe_load(text)
    except yaml.YAMLError as exc:
        raise ConfigError(f"{source}: not valid YAML: {exc}") from None
    if given is None:
        given = {}
    if not isinstance(given, dict):
        raise ConfigError(f"{source}: expected a mapping at the top level")
    version = given.get("version")
    if type(version) is not int or version != CONFIG_VERSION:
        raise ConfigError(f"{source}: UNSUPPORTED_CONFIG_VERSION {version!r}; only version {CONFIG_VERSION} "
                          "is supported. Start from the current template and explicitly re-authorize a new "
                          "project. Do not relabel an older project or reinterpret its recorded evidence.")
    # Lists are supplied whole, never merged with the template's metric or seed examples.
    config = _merge(defaults(), given)
    _normalize_models(config)
    validator = Draft202012Validator(json.loads(SCHEMA_PATH.read_text(encoding="utf-8")))
    errors = sorted(validator.iter_errors(config), key=lambda e: list(e.path))
    if errors:
        raise ConfigError(f"{source}: unsupported or invalid version-3 configuration; " + "; ".join(f"{'.'.join(map(str, e.path)) or '<top>'}: {e.message}"
                                                     for e in errors))
    try:
        metrics.check_metric_specs(metric_spec_document(config))
    except metrics.MetricError as exc:
        raise ConfigError(f"{source}: metric_specs: {exc}") from None
    v = config["verification"]
    search = v["screening_seeds"] + v["replication_seeds"]
    if len(set(search)) != len(search) or set(search) & set(v["confirmation_seeds"]):
        raise ConfigError(f"{source}: verification: screening and replication seeds are distinct and never "
                          "confirmation seeds")
    if len(v["confirmation_seeds"]) < v["min_confirmation_pairs"]:
        raise ConfigError(f"{source}: verification: stage1_confirmed needs at least min_confirmation_pairs "
                          "confirmation_seeds")
    b = config["budget"]
    parts = [b[k] for k in ("search_limit", "confirmation_limit", "repair_limit") if b[k] is not None]
    if b["total_limit"] is not None and sum(parts) > b["total_limit"]:
        raise ConfigError(f"{source}: budget: the parts sum to more than total_limit")
    if b["total_limit"] is None and parts:
        raise ConfigError(f"{source}: budget: parts need a total_limit")
    try:
        metrics.check_protocol({"version": 1, "eval_type": "real_gt", "pair_fields": ["seed"],
                                **protocol_requirements(config)})
    except metrics.MetricError as exc:
        raise ConfigError(f"{source}: verification: {exc}") from None
    repetition = v.get("repetition", {})
    if set(repetition.get("seed_pool", [])) - set(search):
        raise ConfigError(f"{source}: verification.repetition.seed_pool must be within the declared search seeds")
    return config


def metric_spec_document(config: dict) -> dict:
    """The metric_spec document a version-3 configuration states (the first metric is the primary)."""
    specs = config["metric_specs"]
    return {"version": 1, "primary": specs[0].get("name") if specs else None, "metrics": specs}


def protocol_requirements(config: dict) -> dict:
    """What a version-3 configuration fixes in the protocol document: profile and confirmation settings."""
    v = config["verification"]
    return {"profile": "stage1_confirmed", "confirmation_seeds": v["confirmation_seeds"],
            "min_confirmation_pairs": v["min_confirmation_pairs"],
            "max_confirmation_candidates": v["max_confirmation_candidates"],
            "require_artifact_import": config["evidence_policy"]["require_artifact_import"],
            "confirmation_materials": v.get("confirmation_materials", []),
            "independence_fields": v.get("independence_fields", []),
            "repetition": v.get("repetition", {"enabled": False})}


def walltime_seconds(value: int | str) -> int:
    if isinstance(value, int):
        return value
    m = WALLTIME_RE.match(value)
    if not m:
        raise ConfigError(f"walltime {value!r}: use seconds or a form like 90m, 1h, 1h30m")
    h, mins, secs = (int(g or 0) for g in m.groups())
    seconds = h * 3600 + mins * 60 + secs
    if seconds <= 0:
        raise ConfigError(f"walltime {value!r} must be positive")
    return seconds


def db_fields(config: dict) -> dict:
    """Active admission controls, derived from the sole version-3 project contract."""
    budget, v = config["budget"], config["verification"]
    seeds = v["screening_seeds"] + v["replication_seeds"]
    return {
        "max_nodes": budget["per_run"]["nodes"],
        "max_walltime_s": walltime_seconds(budget["per_run"]["walltime"]),
        "screen_budget_node_h": budget["screen_node_h"],
        "max_parallel_workers": budget["max_parallel_workers"],
        "alert_node_h": budget["alert_node_h"],
        "gate_seeds": len(seeds), "seeds": seeds, "screen_seeds": len(v["screening_seeds"]),
        "go_margin": config["metric_specs"][0]["minimum_practical_gain"],
        "stall_structural_at": config["search"]["stall_structural_at"],
        "stall_human_at": config["search"]["stall_human_at"],
        "total_limit": budget["total_limit"], "search_limit": budget["search_limit"],
        "confirmation_limit": budget["confirmation_limit"], "repair_limit": budget["repair_limit"],
        "overrun_factor": config["design"]["overrun_factor"],
        "review_usd_alert": budget["review_usd_alert"],
        "code_review_required": config["design"]["code_review"],
        "sanity_required": config["design"]["sanity_first"],
        "memory_enabled": config["memory"]["enabled"], "memory_pack_limit": config["memory"]["pack_limit_chars"],
        "memory_max_items": config["memory"]["max_items_per_task"],
        "memory_counterevidence": config["memory"]["include_counterevidence"],
        "exploration_fraction": config["search"]["exploration_fraction"],
        "require_selection_rationale": config["search"]["require_selection_rationale"],
        "allow_repair_from_retired": config["search"]["allow_repair_from_retired_evidence"],
        "max_repairs_per_root_cause": config["search"]["max_repairs_per_root_cause"],
    }
