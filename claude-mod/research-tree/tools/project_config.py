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

import yaml
from jsonschema import Draft202012Validator

CONFIG_NAME = "research-tree.yaml"
SCHEMA_DIR = Path(__file__).resolve().parent.parent / "schema"
TEMPLATE_PATH = SCHEMA_DIR / "config.template.yaml"
SCHEMA_PATH = SCHEMA_DIR / "config.schema.json"
WALLTIME_RE = re.compile(r"^(?=\d)(?:(\d+)h)?(?:(\d+)m)?(?:(\d+)s)?$")


class ConfigError(Exception):
    pass


def template_text() -> str:
    return TEMPLATE_PATH.read_text(encoding="utf-8")


def defaults() -> dict:
    return yaml.safe_load(template_text())


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
    config = _merge(defaults(), given)
    validator = Draft202012Validator(json.loads(SCHEMA_PATH.read_text(encoding="utf-8")))
    errors = sorted(validator.iter_errors(config), key=lambda e: list(e.path))
    if errors:
        raise ConfigError(f"{source}: " + "; ".join(f"{'.'.join(map(str, e.path)) or '<top>'}: {e.message}"
                                                     for e in errors))
    return config


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
    """The project record's fields that the configuration sets."""
    budget, stage1 = config["budget"], config["stage1"]
    return {
        "max_nodes": budget["per_run"]["nodes"],
        "max_walltime_s": walltime_seconds(budget["per_run"]["walltime"]),
        "screen_budget_node_h": budget["screen_node_h"],
        "max_parallel_workers": budget["max_parallel_workers"],
        "alert_node_h": budget["alert_node_h"],
        "gate_seeds": stage1["gate_seeds"],
        "go_margin": stage1["go_margin"],
        "min_related_work": stage1["min_related_work"],
    }
