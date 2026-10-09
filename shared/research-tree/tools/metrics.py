"""Metric specifications and the statistics recomputed from registered runs (plans/design/04 §3–5, 05 §2).

Pure functions, no database: research_db.py gives them the runs and the documents and stores what they return.

A MetricSpec says how one metric is read and compared: direction, the unit the runs report (input_unit), the
unit comparisons use (canonical_unit), the effect (absolute paired difference, or relative to the reference
mean), the smallest gain that matters, an allowed regression for guardrails, a valid range of input values, and
the aggregation. The metric_spec document holds the list and names the primary metric; the protocol document
says which run fields must match for two runs to pair and the evaluation type.

Effects are oriented so that positive is better: d_i = s * (x_i - y_i) with s = +1 for higher-is-better.
"""

from __future__ import annotations

import math
import re
import statistics
from decimal import Decimal
from typing import Any

STATISTICS_VERSION = "rt-stats-1"
PARSER_VERSION = "rt-manifest-1"

DIRECTIONS = ("higher", "lower")
EFFECT_MODES = ("absolute", "relative_to_reference_mean")
AGGREGATIONS = ("paired_run_mean",)
EVAL_TYPES = ("real_gt", "synthetic_proxy", "self_supervised_proxy", "simulation_only", "human_eval")
# What each evaluation type allows a conclusion to claim (plans/design 04 §6); carried on every evaluation.
EVAL_TYPE_LIMITS = {
    "synthetic_proxy": "synthetic_proxy: model-generated references; claim proxy agreement only, not task performance",
    "self_supervised_proxy": "self_supervised_proxy: no ground truth; claim relative improvement only",
    "simulation_only": "simulation_only: results hold in simulation; say so in every claim",
    "human_eval": "human_eval: bounded by the judges' agreement statistics",
}
# input unit -> canonical unit -> factor (canonical = input x factor)
CONVERSIONS: dict[str, dict[str, float]] = {
    "fraction": {"fraction": 1.0, "percentage_point": 100.0},
    "percentage": {"percentage": 1.0, "percentage_point": 1.0},
    "percentage_point": {"percentage_point": 1.0},
    "seconds": {"seconds": 1.0, "minutes": 1 / 60, "hours": 1 / 3600},
    "milliseconds": {"milliseconds": 1.0, "seconds": 1e-3},
    "minutes": {"minutes": 1.0, "seconds": 60.0, "hours": 1 / 60},
    "hours": {"hours": 1.0, "seconds": 3600.0, "minutes": 60.0},
    "bytes": {"bytes": 1.0, "mib": 1 / 2**20, "gib": 1 / 2**30},
    "mib": {"mib": 1.0, "gib": 1 / 1024, "bytes": float(2**20)},
    "gib": {"gib": 1.0, "mib": 1024.0, "bytes": float(2**30)},
    "count": {"count": 1.0},
    "ratio": {"ratio": 1.0},
    "nats": {"nats": 1.0},
    "raw": {"raw": 1.0},
}
# Bounded units: a value outside them is a unit mix-up (0.701 against 70.1), with or without a declared range.
IMPLIED_RANGES = {"fraction": [0.0, 1.0], "percentage": [0.0, 100.0]}
SPEC_FIELDS = {"name", "direction", "input_unit", "canonical_unit", "effect_mode", "minimum_practical_gain",
               "allowed_regression", "valid_range", "relative_min_denominator", "aggregation"}
REQUIRED_SPEC_FIELDS = ("name", "direction", "input_unit", "canonical_unit", "effect_mode", "minimum_practical_gain",
                        "aggregation")
PROTOCOL_FIELDS = {"version", "eval_type", "pair_fields", "match", "required_counts", "gate_comparison",
                   "min_pairs", "require_artifact_import", "inference_mode", "description", "profile",
                   "confirmation_seeds", "min_confirmation_pairs", "max_confirmation_candidates",
                   "independence_fields", "confirmation_materials", "execution_fields", "sanity_overrides_allowed",
                   "review_applicability", "repetition"}
# 06 §2.4: screening ends at candidate_ready; stage1_confirmed needs an independent confirmation for GO.
PROFILES = ("screening", "stage1_confirmed")
OUTCOMES = ("positive_signal", "negative_signal", "inconclusive", "invalid")
GATE_COMPARISONS = (">", ">=")


class MetricError(Exception):
    """A refused metric computation; `code` is one of the stable error codes of plans/design/10 §1.6."""

    def __init__(self, code: str, message: str):
        super().__init__(f"{code}: {message}")
        self.code = code


# ---------------------------------------------------------------------------
# Specifications
# ---------------------------------------------------------------------------


def check_metric_specs(doc: Any) -> dict:
    """A metric_spec document's content, checked: {"version": 1, "primary": name, "metrics": [spec, ...]}."""
    if not isinstance(doc, dict) or doc.get("version") != 1 or not isinstance(doc.get("metrics"), list):
        raise MetricError("METRIC_UNIT_MISMATCH", 'a metric_spec document is {"version": 1, "primary": <name>, '
                                                  '"metrics": [<spec>, ...]}')
    extra = set(doc) - {"version", "primary", "metrics", "description"}
    if extra:
        raise MetricError("METRIC_UNIT_MISMATCH", f"metric_spec has unknown keys {sorted(extra)}")
    names = []
    for spec in doc["metrics"]:
        check_spec(spec)
        names.append(spec["name"])
    if len(set(names)) != len(names):
        raise MetricError("METRIC_UNIT_MISMATCH", f"metric names repeat: {names}")
    if doc.get("primary") not in names:
        raise MetricError("METRIC_UNIT_MISMATCH", f"primary {doc.get('primary')!r} is not one of the metrics {names}")
    return doc


def check_spec(spec: Any) -> None:
    if not isinstance(spec, dict):
        raise MetricError("METRIC_UNIT_MISMATCH", f"a metric spec is an object, got {spec!r}")
    name = spec.get("name", "?")
    missing = [f for f in REQUIRED_SPEC_FIELDS if spec.get(f) is None]
    extra = set(spec) - SPEC_FIELDS
    if missing or extra:
        raise MetricError("METRIC_UNIT_MISMATCH", f"metric {name}: missing {missing}, unknown {sorted(extra)}")
    if spec["direction"] not in DIRECTIONS or spec["effect_mode"] not in EFFECT_MODES \
            or spec["aggregation"] not in AGGREGATIONS:
        raise MetricError("METRIC_UNIT_MISMATCH", f"metric {name}: direction in {DIRECTIONS}, effect_mode in "
                                                  f"{EFFECT_MODES}, aggregation in {AGGREGATIONS}")
    if spec["canonical_unit"] not in CONVERSIONS.get(spec["input_unit"], {}):
        raise MetricError("METRIC_UNIT_MISMATCH", f"metric {name}: no conversion from {spec['input_unit']} to "
                                                  f"{spec['canonical_unit']}")
    for field in ("minimum_practical_gain", "allowed_regression", "relative_min_denominator"):
        value = spec.get(field)
        if value is not None and not (_number(value) and value >= 0):
            raise MetricError("METRIC_UNIT_MISMATCH", f"metric {name}: {field} must be a number >= 0")
    if spec["effect_mode"] == "relative_to_reference_mean" and spec.get("relative_min_denominator") is None:
        raise MetricError("METRIC_UNIT_MISMATCH", f"metric {name}: a relative effect needs relative_min_denominator")
    rng = spec.get("valid_range")
    if spec["input_unit"] == "percentage" and rng is None:
        raise MetricError("METRIC_UNIT_MISMATCH", f"metric {name}: a percentage metric declares valid_range, narrow "
                                                  "enough that a fraction (0.7 for 70%) cannot pass unnoticed")
    if rng is not None and not (isinstance(rng, list) and len(rng) == 2 and all(_number(v) for v in rng)
                                and rng[0] <= rng[1]):
        raise MetricError("METRIC_UNIT_MISMATCH", f"metric {name}: valid_range is [low, high]")


def check_protocol(doc: Any) -> dict:
    """A protocol document's content: {"version": 1, "eval_type": ..., "pair_fields": [...], "match": {...}, ...}."""
    if not isinstance(doc, dict) or doc.get("version") != 1:
        raise MetricError("PROTOCOL_CHANGE_REQUIRED", 'a protocol document is {"version": 1, "eval_type": ..., ...}')
    extra = set(doc) - PROTOCOL_FIELDS
    if extra:
        raise MetricError("PROTOCOL_CHANGE_REQUIRED", f"protocol has unknown keys {sorted(extra)}")
    if doc.get("eval_type") not in EVAL_TYPES:
        raise MetricError("PROTOCOL_CHANGE_REQUIRED", f"protocol eval_type must be one of {EVAL_TYPES}")
    pair = doc.get("pair_fields", ["seed"])
    if not (isinstance(pair, list) and all(isinstance(f, str) and f for f in pair) and "seed" in pair):
        raise MetricError("PROTOCOL_CHANGE_REQUIRED", "pair_fields is a list of manifest fields including seed")
    for key in ("match", "required_counts"):
        if not isinstance(doc.get(key, {}), dict):
            raise MetricError("PROTOCOL_CHANGE_REQUIRED", f"protocol {key} is an object")
    if any(not isinstance(v, (str, int, float, bool)) for v in doc.get("match", {}).values()):
        raise MetricError("PROTOCOL_CHANGE_REQUIRED", "protocol match values are scalars (string, number, boolean)")
    if any(not (isinstance(v, int) and v > 0) for v in doc.get("required_counts", {}).values()):
        raise MetricError("PROTOCOL_CHANGE_REQUIRED", "required_counts values are positive integers")
    if doc.get("gate_comparison", ">") not in GATE_COMPARISONS:
        raise MetricError("PROTOCOL_CHANGE_REQUIRED", f"gate_comparison is one of {GATE_COMPARISONS}")
    if doc.get("min_pairs") is not None and not (isinstance(doc["min_pairs"], int) and doc["min_pairs"] >= 1):
        raise MetricError("PROTOCOL_CHANGE_REQUIRED", "min_pairs is a positive integer")
    if doc.get("profile", "stage1_confirmed") not in PROFILES:
        raise MetricError("PROTOCOL_CHANGE_REQUIRED", f"profile is one of {PROFILES}")
    seeds = doc.get("confirmation_seeds", [])
    if not (isinstance(seeds, list) and all(isinstance(x, int) and not isinstance(x, bool) for x in seeds)
            and len(set(seeds)) == len(seeds)):
        raise MetricError("PROTOCOL_CHANGE_REQUIRED", "confirmation_seeds is a list of distinct integers")
    for key in ("min_confirmation_pairs", "max_confirmation_candidates"):
        if doc.get(key) is not None and not (isinstance(doc[key], int) and doc[key] >= 1):
            raise MetricError("PROTOCOL_CHANGE_REQUIRED", f"{key} is a positive integer")
    if doc.get("profile", "stage1_confirmed") == "stage1_confirmed":
        need = doc.get("min_confirmation_pairs", 3)
        if len(seeds) < need:
            raise MetricError("PROTOCOL_CHANGE_REQUIRED", f"profile stage1_confirmed declares at least {need} "
                                                          "confirmation_seeds, unused during the search")
    materials = doc.get("confirmation_materials", [])
    if not isinstance(materials, list):
        raise MetricError("PROTOCOL_CHANGE_REQUIRED", "confirmation_materials is a list")
    names = set()
    for m in materials:
        ok = (isinstance(m, dict) and isinstance(m.get("name"), str) and m["name"] and m["name"] not in names
              and set(m) <= {"name", "seeds", "split_sha256", "manifest_field", "description"}
              and isinstance(m.get("seeds"), list) and m["seeds"]
              and all(isinstance(x, int) and not isinstance(x, bool) for x in m["seeds"])
              and len(set(m["seeds"])) == len(m["seeds"])
              and len(m["seeds"]) >= doc.get("min_confirmation_pairs", 3)
              and (m.get("split_sha256") is None or (isinstance(m["split_sha256"], str)
                                                     and re.fullmatch(r"[0-9a-f]{64}", m["split_sha256"]))))
        if not ok:
            raise MetricError("PROTOCOL_CHANGE_REQUIRED", "a confirmation material is {name, seeds (distinct "
                                                          "integers, at least min_confirmation_pairs), split_sha256? "
                                                          "(the evaluation split's content hash), manifest_field?}; "
                                                          f"names are unique; got {m!r}")
        names.add(m["name"])
    for key in ("execution_fields", "sanity_overrides_allowed"):
        if not (isinstance(doc.get(key, []), list) and all(isinstance(f, str) and f for f in doc.get(key, []))):
            raise MetricError("PROTOCOL_CHANGE_REQUIRED", f"{key} is a list of configuration field names")
    fields = doc.get("independence_fields", [])
    if not (isinstance(fields, list) and all(isinstance(f, str) and f for f in fields)):
        raise MetricError("PROTOCOL_CHANGE_REQUIRED", "independence_fields is a list of manifest fields")
    # S4 §8.1: which recheck dimensions a claim may exempt as a whole (only novelty and theory; an empirical
    # result's numbers, protocol and method-code are always reviewed)
    allowed = doc.get("review_applicability", {})
    if not (isinstance(allowed, dict) and set(allowed) <= {"novelty", "theory"} and all(
            isinstance(v, dict) and set(v) <= {"exemptible", "reason"} and isinstance(v.get("exemptible"), bool)
            for v in allowed.values())):
        raise MetricError("PROTOCOL_CHANGE_REQUIRED", 'review_applicability is {"novelty"|"theory": {"exemptible": '
                                                      'true|false, "reason": ...}}; numbers, protocol and '
                                                      "method_code are never exempt")
    rep = doc.get("repetition")
    if rep is not None:
        ok = (isinstance(rep, dict) and set(rep) <= {"enabled", "se_multiple", "batch", "seed_pool", "auto"}
              and isinstance(rep.get("enabled"), bool) and _number(rep.get("se_multiple", 2.0))
              and rep.get("se_multiple", 2.0) > 0 and isinstance(rep.get("batch", 2), int) and rep.get("batch", 2) >= 1
              and isinstance(rep.get("seed_pool", []), list)
              and all(isinstance(s, int) and not isinstance(s, bool) for s in rep.get("seed_pool", []))
              and not set(rep.get("seed_pool", [])) & set(doc.get("confirmation_seeds", []))
              and not any(set(rep.get("seed_pool", [])) & set(m.get("seeds", [])) for m in materials if isinstance(m, dict)))
        if not ok:
            raise MetricError("PROTOCOL_CHANGE_REQUIRED", "repetition is {enabled, se_multiple > 0, batch >= 1, "
                                                          "seed_pool: search/replicate seeds (never confirmation seeds), "
                                                          "auto?}, fixed before the experiments")
    return doc


def repetition_advice(spec: dict, pairs: list[dict], gain: float, policy: dict | None, used_seeds: list[int],
                      seed_cost: int | None, available: int | None) -> dict:
    """S7 §11.1: whether more repeats would help decide the comparison, by a rule fixed in the protocol. pairs:
    [{"diff": oriented paired difference in the canonical unit, "unit": the protocol's independence key}]. Only
    absolute effects over complete, distinct independence units get numbers: n < 2 states no variance; otherwise
    SD of the differences, SE = SD / sqrt(n), and the comparison is unclear when |mean - gain| <= se_multiple x SE.
    A descriptive allocation heuristic, never a significance claim. More seeds come only from the protocol's
    search/replicate seed_pool, within the available budget; nothing is run here."""
    policy = policy or {}
    base = {"effect_mode": spec.get("effect_mode"), "unit": spec.get("canonical_unit"), "gain": gain,
            "policy": {k: policy.get(k) for k in ("enabled", "se_multiple", "batch")}}
    if not policy.get("enabled"):
        return {**base, "advice": "disabled", "reason": "the protocol does not enable repetition advice"}
    if spec.get("effect_mode") != "absolute":
        return {**base, "advice": "unsupported_effect_mode",
                "reason": f"{spec.get('effect_mode')}: only absolute effects get a numeric advice"}
    keys = [p.get("unit") for p in pairs]
    if not pairs or any(k is None for k in keys) or len(set(map(str, keys))) != len(keys):
        return {**base, "advice": "independence_unverified",
                "reason": "every pair needs its own declared independence unit (missing or shared keys)"}
    diffs = [float(p["diff"]) for p in pairs]
    n = len(diffs)
    mean = statistics.fmean(diffs)
    out = {**base, "n_independent": n, "mean": mean}
    k = float(policy.get("se_multiple", 2.0))
    if n < 2:
        unclear, why = True, "n < 2: the variance is not known"
    else:
        sd = statistics.stdev(diffs)
        se = sd / math.sqrt(n)
        out.update(sd=sd, se=se)
        unclear = abs(mean - gain) <= k * se
        why = (f"|mean - gain| = {abs(mean - gain):.6g} {'<=' if unclear else '>'} {k:g} x SE {se:.6g}")
        signs = {d > 0 for d in diffs if d}
        if len(signs) > 1:
            why += "; the differences change sign"
    if not unclear:
        return {**out, "advice": "enough", "reason": why}
    pool = [s for s in policy.get("seed_pool", []) if s not in set(used_seeds)]
    batch = int(policy.get("batch", 2))
    proposed = pool[:batch]
    if not proposed:
        return {**out, "advice": "hold_inconclusive", "reason": why + "; the declared seed pool is used up"}
    if seed_cost is not None and available is not None and seed_cost * len(proposed) > available:
        fit = max(0, available // seed_cost) if seed_cost else len(proposed)
        proposed = proposed[:fit]
        if not proposed:
            return {**out, "advice": "hold_inconclusive", "reason": why + "; the available budget does not fit one more seed"}
    return {**out, "advice": "add_repeats", "seeds": proposed, "reason": why,
            "cost": None if seed_cost is None else seed_cost * len(proposed), "available": available,
            "auto": bool(policy.get("auto"))}


def legacy_specs(project: dict) -> dict:
    """The compatibility specification of a project without a metric_spec document (plans/design/10 §2.4): the
    primary metric's direction from the project, values taken as they are, and the old go_margin semantics
    (percentage-point difference when metric_is_percent, else relative difference in percent). Secondary
    metrics have no known direction; their deltas cannot be recomputed and stay the caller's."""
    percent = project["metric_is_percent"]
    primary = {"name": project["primary_metric"], "direction": project["metric_direction"], "input_unit": "raw",
               "canonical_unit": "raw", "effect_mode": "absolute" if percent else "relative_to_reference_mean",
               "minimum_practical_gain": project["go_margin"], "aggregation": "paired_run_mean",
               "relative_min_denominator": 0.0}
    return {"version": 1, "primary": primary["name"], "metrics": [primary], "legacy": True,
            "legacy_relative_percent": not percent}


def spec_by_name(specs: dict) -> dict[str, dict]:
    return {s["name"]: s for s in specs["metrics"]}


# ---------------------------------------------------------------------------
# Values
# ---------------------------------------------------------------------------


def is_number(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool)


_number = is_number


def canonical(spec: dict, value: Any, where: str) -> float:
    """One run value in the comparison unit; refuses non-finite and out-of-range inputs."""
    if not _number(value):
        raise MetricError("NONFINITE_METRIC", f"{where}: {spec['name']} is not a number ({value!r})")
    if not math.isfinite(value):
        raise MetricError("NONFINITE_METRIC", f"{where}: {spec['name']} is {value}")
    rng = spec.get("valid_range") or IMPLIED_RANGES.get(spec["input_unit"])
    if rng is not None and not rng[0] <= value <= rng[1]:
        raise MetricError("METRIC_UNIT_MISMATCH", f"{where}: {spec['name']}={value} is outside its valid range "
                                                  f"{rng} in {spec['input_unit']}; check the unit the run reports")
    return value * CONVERSIONS[spec["input_unit"]][spec["canonical_unit"]]


def run_values(specs: dict, run: dict, metrics: list[str]) -> dict[str, float]:
    """The canonical values of the named metrics of one valid run (primary from metric_value, others from
    secondary)."""
    by_name = spec_by_name(specs)
    out = {}
    for name in metrics:
        raw = run.get("metric_value") if name == specs["primary"] else (run.get("secondary") or {}).get(name)
        if name not in by_name:
            raise MetricError("METRIC_UNIT_MISMATCH", f"{run['id']}: metric {name} has no specification")
        out[name] = canonical(by_name[name], raw, run["id"])
    return out


def check_unit_mix(spec: dict, values: list[float], where: str) -> str | None:
    """Bounded units (fraction, percentage): values of one comparison differing by the unit factor (>= 50 times)
    may mean one of them is in another unit (0.699 among 69.9). S3 §7.1: legal values in the declared range are
    never refused for their scale (0.001 and 0.1 are both fractions); the range and the unit recorded at import
    are the hard checks, this returns a review hint (or None)."""
    if spec["input_unit"] not in IMPLIED_RANGES:
        return None
    nonzero = [abs(v) for v in values if v]
    if len(nonzero) >= 2 and max(nonzero) / min(nonzero) >= 50:
        return (f"{where}: {spec['name']} values range from {min(nonzero):g} to {max(nonzero):g} "
                f"({spec['input_unit']}); check that every run reports the same unit")
    return None


def pair_key(protocol: dict | None, run: dict) -> tuple:
    """The fields that must match for two runs to pair: the protocol's pair_fields, read from the run's imported
    manifest; without a manifest only the seed is known."""
    fields = (protocol or {}).get("pair_fields", ["seed"])
    manifest = run.get("manifest") or {}
    key = []
    for field in fields:
        if field == "seed":
            key.append(("seed", run["seed"]))
        elif field in manifest:
            key.append((field, manifest[field]))
        else:
            raise MetricError("PAIRING_MISMATCH", f"{run['id']}: the protocol pairs runs on {field}, which the run "
                                                  "does not record; import its manifest (import_run_result)")
    return tuple(key)


def key_text(key: tuple) -> str:
    return "/".join(f"{k}={v}" for k, v in key)


# ---------------------------------------------------------------------------
# Statistics
# ---------------------------------------------------------------------------


def summary(values: list[float]) -> dict:
    """Mean and sample standard deviation of one metric over runs; n=1 has no SD (not 0)."""
    n = len(values)
    out = {"n": n, "mean": statistics.fmean(values) if n else None, "values": values}
    if n >= 2:
        out["sd"] = statistics.stdev(values)
    else:
        out["sd"], out["sd_missing"] = None, "n=1: no standard deviation" if n == 1 else "no values"
    return out


def effect(spec: dict, xs: list[float], ys: list[float], legacy_percent: bool = False) -> dict:
    """The oriented effect of method values xs against reference values ys (paired, same order)."""
    s = 1 if spec["direction"] == "higher" else -1
    n = len(xs)
    out: dict[str, Any] = {"n_paired": n, "effect_mode": spec["effect_mode"], "unit": spec["canonical_unit"]}
    if spec["effect_mode"] == "absolute":
        d = [s * (x - y) for x, y in zip(xs, ys)]
        out["deltas"] = d
        out["delta_mean"] = statistics.fmean(d)
        if n >= 2:
            out["delta_sd"] = statistics.stdev(d)
        else:
            out["delta_sd"], out["delta_sd_missing"] = None, "n=1: no standard deviation"
        return out
    ref = statistics.fmean(ys)
    if abs(ref) < spec["relative_min_denominator"] or ref == 0:
        out.update(delta_mean=None, delta_sd=None, undefined="RELATIVE_EFFECT_UNDEFINED",
                   reason=f"|reference mean| {abs(ref):.6g} is below relative_min_denominator "
                          f"{spec['relative_min_denominator']}")
        return out
    rel = s * (statistics.fmean(xs) - ref) / abs(ref)
    out.update(delta_mean=rel * 100 if legacy_percent else rel, delta_sd=None,
               delta_sd_missing="a relative effect is the ratio of means, not a mean of per-seed ratios",
               unit="percent" if legacy_percent else "fraction")
    return out


def passes(value: float | None, threshold: float, comparison: str) -> bool:
    """The gate: an effect equal to the threshold up to binary rounding (relative 1e-9) is a tie that the protocol's
    '>' or '>=' decides, not rounding noise (0.701 x 100 - 0.699 x 100 is not exactly 0.2)."""
    if value is None:
        return False
    if math.isclose(value, threshold, rel_tol=1e-9, abs_tol=0.0):  # a tie, up to binary rounding
        return comparison == ">="
    return value > threshold if comparison == ">" else value >= threshold


def compare(specs: dict, protocol: dict | None, mine: list[dict], theirs: list[dict], metrics: list[str]) -> dict:
    """Pair two sets of valid runs on the protocol's pair keys and compute every metric's effect.

    Returns {"n_paired", "pair_keys", "metrics": {name: effect}, "unpaired": [...]}; a pair key that appears twice
    on one side is refused (no run counts twice)."""
    def keyed(runs):
        out = {}
        for run in runs:
            key = pair_key(protocol, run)
            if key in out:
                raise MetricError("PAIRING_MISMATCH", f"{run['id']} and {out[key]['id']} share the pair key "
                                                      f"{key_text(key)}; a repeated seed is not an independent pair")
            out[key] = run
        return out

    a, b = keyed(mine), keyed(theirs)
    keys = sorted(set(a) & set(b), key=key_text)
    seeds_a = {r["seed"] for r in mine}
    mismatched = sorted(r["seed"] for r in theirs if r["seed"] in seeds_a and pair_key(protocol, r) not in a)
    independence = (protocol or {}).get("independence_fields") or []
    if independence:  # runs that share these (e.g. the same data order) are one independent repeat, not several
        # S3 §7.2: on both sides every declared field is present and a scalar; a missing value is never counted
        # as one more independent unit
        for side in (a, b):
            for k in keys:
                manifest = side[k].get("manifest") or {}
                bad = [f for f in independence if not isinstance(manifest.get(f), (str, int, float, bool))
                       or manifest.get(f) is None]
                if bad:
                    raise MetricError("INDEPENDENCE_UNVERIFIED", f"{side[k]['id']} lacks the independence fields {bad} "
                                                                 "the protocol declares (a missing value is not a new "
                                                                 "independent unit)")
        distinct = {tuple((a[k].get("manifest") or {}).get(f) for f in independence) for k in keys}
        n_independent = len(distinct)
    else:
        n_independent = len(keys)
    result = {"n_paired": len(keys), "n_independent": n_independent, "pair_keys": [key_text(k) for k in keys],
              "metrics": {}, "unpaired_same_seed": mismatched}
    if not keys:
        return result
    legacy_pct = specs.get("legacy_relative_percent", False)
    by_name = spec_by_name(specs)
    for name in metrics:
        if name not in by_name:
            continue  # legacy secondary metrics: no direction known
        xs = [run_values(specs, a[k], [name])[name] for k in keys]
        ys = [run_values(specs, b[k], [name])[name] for k in keys]
        hint = check_unit_mix(by_name[name], xs + ys, "the compared runs")
        result["metrics"][name] = effect(by_name[name], xs, ys, legacy_pct)
        if hint:
            result.setdefault("hints", []).append(hint)
    return result


def guardrails(specs: dict, comparison: dict) -> dict:
    """Metrics with allowed_regression must not regress more than allowed; an undefined effect fails closed."""
    out = {}
    for spec in specs["metrics"]:
        limit = spec.get("allowed_regression")
        if limit is None or spec["name"] not in comparison["metrics"]:
            continue
        value = comparison["metrics"][spec["name"]].get("delta_mean")
        out[spec["name"]] = {"allowed_regression": limit, "effect": value,
                             "passed": value is not None and value >= -limit}
    return out


def matches_text(given: str, computed: float | None) -> bool:
    """A number written in a document ("70.0", "3.3e-05", "12.5%") agrees with the recomputed one when it is that
    number rounded to the decimals written (70.0 is not 70.4)."""
    try:
        value = Decimal(given.strip().rstrip("%"))
    except (ArithmeticError, ValueError):
        return False
    if computed is None or not value.is_finite():
        return False
    exponent = value.as_tuple().exponent
    decimals = max(0, -exponent) if isinstance(exponent, int) else 0
    return abs(float(value) - computed) <= 0.5 * 10 ** -decimals + 1e-12


def matches_given(given: Any, computed: float | None) -> bool:
    """A caller's number agrees with the recomputed one when it is that number rounded to the decimals the caller
    wrote (70.3 is not 70.0; 0.904 is 0.90417 rounded)."""
    if given is None:
        return True
    if computed is None or not _number(given) or not math.isfinite(given):
        return False
    # the decimals the caller wrote, also in scientific notation (-3.3e-05 has 6)
    exponent = Decimal(repr(float(given))).as_tuple().exponent  # repr is the shortest form: 70.0 keeps a decimal
    decimals = max(0, -exponent) if isinstance(exponent, int) else 0
    return abs(given - computed) <= 0.5 * 10 ** -decimals + 1e-12


def outcome(effect: float | None, gain: float, n_pairs: int, min_pairs: int, comparison: str = ">") -> tuple[str, str]:
    """The deterministic conclusion of one evaluation (plans/design 06 §2.1), from the primary metric's effect
    against the experiment's reference (the parent's experiment, or the SOTA at the top level):
    positive_signal: the effect clears the minimum practical gain;
    negative_signal: the effect is at least the minimum practical gain the wrong way, over the required pairs;
    inconclusive: anything else, including a small negative effect on one seed or a result at the seed limit
    near the threshold. The effect itself is always kept; 'negative' holds only in the tested conditions."""
    if effect is None:
        return "inconclusive", "the effect could not be computed"
    if passes(effect, gain, comparison):
        return "positive_signal", f"effect {effect:.6g} clears the minimum practical gain {gain:g}"
    if n_pairs >= min_pairs and passes(-effect, gain, comparison):
        return "negative_signal", (f"effect {effect:.6g} is below -{gain:g} over {n_pairs} pairs "
                                   "(within the tested setting only)")
    return "inconclusive", (f"effect {effect:.6g} over {n_pairs} pair(s): neither clear of {gain:g} nor below "
                            f"-{gain:g} with at least {min_pairs} pairs (what a negative signal needs)")


def minimal_documents(primary: str, direction: str, secondary: list[str], gain: float = 0.05) -> tuple[dict, dict]:
    """A metric specification and protocol with raw units and no guardrails, for fixtures and smoke checks only:
    a real project declares its units, ranges and guardrails (doc_library: metric_spec, protocol)."""
    def spec(name: str, way: str, mpg: float) -> dict:
        return {"name": name, "direction": way, "input_unit": "raw", "canonical_unit": "raw", "effect_mode": "absolute",
                "minimum_practical_gain": mpg, "aggregation": "paired_run_mean"}
    specs = {"version": 1, "primary": primary,
             "metrics": [spec(primary, direction, gain)] + [spec(n, "lower", 0.0) for n in secondary]}
    return specs, {"version": 1, "eval_type": "real_gt", "pair_fields": ["seed"], "profile": "screening"}
