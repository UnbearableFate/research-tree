"""Tests for tools/metrics.py: specifications, units, effects and the rounding cross-check (plans/design 04, 05)."""

from __future__ import annotations

import math
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "tools"))
import metrics  # noqa: E402
from metrics import MetricError  # noqa: E402

ACC = {"name": "acc", "direction": "higher", "input_unit": "fraction", "canonical_unit": "percentage_point",
       "effect_mode": "absolute", "minimum_practical_gain": 0.2, "aggregation": "paired_run_mean",
       "valid_range": [0.0, 1.0]}
TIME = {"name": "train_time_s", "direction": "lower", "input_unit": "seconds", "canonical_unit": "seconds",
        "effect_mode": "relative_to_reference_mean", "relative_min_denominator": 1.0, "allowed_regression": 0.10,
        "minimum_practical_gain": 0.0, "aggregation": "paired_run_mean"}
SPECS = {"version": 1, "primary": "acc", "metrics": [ACC, TIME]}
PROTOCOL = {"version": 1, "eval_type": "real_gt", "pair_fields": ["seed"],
            "profile": "stage1_confirmed", "confirmation_seeds": [1042, 1043, 1044]}


def run(seed, acc, time, **manifest):
    return {"id": f"E-1/s{seed}", "seed": seed, "metric_value": acc, "secondary": {"train_time_s": time},
            "manifest": manifest or None}


class SpecTest(unittest.TestCase):
    def test_specs_are_checked(self):
        metrics.check_metric_specs(SPECS)
        for bad, message in (
            ({**SPECS, "primary": "f1"}, "primary 'f1'"),
            ({**SPECS, "metrics": [ACC, ACC]}, "repeat"),
            ({**SPECS, "metrics": [{**ACC, "canonical_unit": "seconds"}]}, "no conversion"),
            ({**SPECS, "metrics": [{**TIME, "relative_min_denominator": None}]}, "needs relative_min_denominator"),
            ({**SPECS, "metrics": [{**ACC, "colour": "red"}]}, "unknown"),
            ({**SPECS, "legacy": True}, "unknown"),
            ({**SPECS, "legacy_relative_percent": True}, "unknown"),
            ({**SPECS, "metrics": [{**ACC, "minimum_practical_gain": math.inf}]}, "finite"),
            ({**SPECS, "metrics": [{**ACC, "name": ""}]}, "nonempty"),
        ):
            with self.subTest(message=message), self.assertRaisesRegex(MetricError, message):
                metrics.check_metric_specs(bad)

    def test_protocol_requires_explicit_independent_confirmation(self):
        metrics.check_protocol({**PROTOCOL, "eval_type": "synthetic_proxy", "pair_fields": ["seed", "split"]})
        for bad, reason in (
            (None, "protocol document"),
            ({k: v for k, v in PROTOCOL.items() if k != "profile"}, "explicitly be stage1_confirmed"),
            ({**PROTOCOL, "profile": "screening"}, "independent confirmation is required"),
            ({k: v for k, v in PROTOCOL.items() if k != "confirmation_seeds"}, "at least 3 confirmation_seeds"),
            ({**PROTOCOL, "confirmation_seeds": [1042]}, "at least 3 confirmation_seeds"),
            ({**PROTOCOL, "confirmation_seeds": [1042, 1042, 1043]}, "distinct integers"),
            ({k: v for k, v in PROTOCOL.items() if k != "pair_fields"}, "explicit list"),
            ({**PROTOCOL, "pair_fields": ["split"]}, "including seed"),
            ({**PROTOCOL, "pair_fields": ["seed", "seed"]}, "distinct"),
            ({**PROTOCOL, "eval_type": "proxy"}, "eval_type"),
            ({**PROTOCOL, "legacy": True}, "unknown keys"),
            ({**PROTOCOL, "inference_mode": "descriptive"}, "unknown keys"),
        ):
            with self.subTest(bad=bad), self.assertRaisesRegex(MetricError, reason):
                metrics.check_protocol(bad)

    def test_protocol_preserves_independence_and_repetition(self):
        protocol = {**PROTOCOL, "independence_fields": ["data_order"],
                    "confirmation_materials": [{"name": "holdout", "seeds": [2042, 2043, 2044]}],
                    "repetition": {"enabled": True, "se_multiple": 2.0,
                                   "batch": 2, "seed_pool": [45, 46, 47]}}
        self.assertEqual(metrics.check_protocol(protocol), protocol)
        for bad, reason in (
            ({**protocol, "independence_fields": ["data_order", "data_order"]}, "distinct manifest fields"),
            ({**protocol, "repetition": {**protocol["repetition"], "seed_pool": [45, 1042]}}, "never confirmation seeds"),
            ({**protocol, "repetition": {**protocol["repetition"], "seed_pool": [45, 2042]}}, "never confirmation seeds"),
            ({**protocol, "repetition": {**protocol["repetition"], "seed_pool": [45, 45]}}, "repetition"),
            ({**protocol, "repetition": {**protocol["repetition"], "auto": True}}, "repetition"),
            ({**protocol, "repetition": {**protocol["repetition"], "batch": True}}, "repetition"),
        ):
            with self.subTest(bad=bad), self.assertRaisesRegex(MetricError, reason):
                metrics.check_protocol(bad)

    def test_repetition_advice_is_read_only_and_rejects_removed_auto_flag(self):
        pairs = [{"diff": 0.2, "unit": "a"}, {"diff": 0.2, "unit": "b"}]
        policy = {"enabled": True, "se_multiple": 2.0, "batch": 1, "seed_pool": [43]}
        advice = metrics.repetition_advice(ACC, pairs, 0.2, policy, [42], 10, 100)
        self.assertEqual(advice["advice"], "add_repeats")
        self.assertNotIn("auto", advice)
        with self.assertRaisesRegex(MetricError, "repetition advice accepts only"):
            metrics.repetition_advice(ACC, pairs, 0.2, {**policy, "auto": True}, [42], 10, 100)

    def test_minimal_documents_use_the_current_protocol(self):
        specs, protocol = metrics.minimal_documents("acc", "higher", ["time"])
        self.assertEqual(metrics.check_metric_specs(specs), specs)
        self.assertEqual(metrics.check_protocol(protocol), protocol)
        self.assertEqual(protocol["profile"], "stage1_confirmed")
        self.assertFalse(hasattr(metrics, "legacy_specs"))


class EffectTest(unittest.TestCase):
    def test_m04_fraction_to_percentage_points(self):
        cmp = metrics.compare(SPECS, PROTOCOL, [run(42, 0.701, 10.0)], [run(42, 0.699, 10.0)], ["acc", "train_time_s"])
        self.assertAlmostEqual(cmp["metrics"]["acc"]["delta_mean"], 0.2, places=9)  # not 20, not 0.2 %
        self.assertEqual(cmp["metrics"]["acc"]["unit"], "percentage_point")

    def test_m03_lower_is_better_and_relative(self):
        mine = [run(s, 0.7, 9.0) for s in (1, 2)]
        ref = [run(s, 0.7, 10.0) for s in (1, 2)]
        effect = metrics.compare(SPECS, PROTOCOL, mine, ref, ["acc", "train_time_s"])["metrics"]["train_time_s"]
        self.assertAlmostEqual(effect["delta_mean"], 0.1, places=9)  # 10% faster is +0.1
        self.assertIsNone(effect["delta_sd"])
        guard = metrics.guardrails(SPECS, metrics.compare(SPECS, PROTOCOL, [run(1, 0.7, 11.5)], [run(1, 0.7, 10.0)],
                                                          ["acc", "train_time_s"]))
        self.assertFalse(guard["train_time_s"]["passed"])  # 15% slower exceeds the 10% allowed

    def test_m06_n1_has_no_sd(self):
        s = metrics.summary([70.0])
        self.assertIsNone(s["sd"])
        self.assertIn("n=1", s["sd_missing"])
        e = metrics.effect(ACC, [70.5], [70.0])
        self.assertIsNone(e["delta_sd"])

    def test_m07_values(self):
        for value, code in ((math.nan, "NONFINITE_METRIC"), (math.inf, "NONFINITE_METRIC"), ("0.7", "NONFINITE_METRIC"),
                            (70.1, "METRIC_UNIT_MISMATCH"), (True, "NONFINITE_METRIC")):
            with self.subTest(value=value), self.assertRaises(MetricError) as caught:
                metrics.canonical(ACC, value, "r")
            self.assertEqual(caught.exception.code, code)

    def test_m08_pair_keys(self):
        protocol = {**PROTOCOL, "pair_fields": ["seed", "split"]}
        cmp = metrics.compare(SPECS, protocol, [run(42, 0.7, 1.0, split="b")], [run(42, 0.7, 1.0, split="a")],
                              ["acc"])
        self.assertEqual((cmp["n_paired"], cmp["unpaired_same_seed"]), (0, [42]))
        with self.assertRaisesRegex(MetricError, "does not record"):
            metrics.compare(SPECS, protocol, [run(42, 0.7, 1.0)], [run(42, 0.7, 1.0, split="a")], ["acc"])
        with self.assertRaisesRegex(MetricError, "repeated seed"):
            metrics.compare(SPECS, PROTOCOL, [run(42, 0.7, 1.0), {**run(42, 0.7, 1.0), "id": "E-1/x"}], [], ["acc"])

    def test_m09_relative_denominator(self):
        effect = metrics.effect(TIME, [0.5], [0.4])
        self.assertEqual(effect["undefined"], "RELATIVE_EFFECT_UNDEFINED")
        self.assertIsNone(effect["delta_mean"])

    def test_unknown_or_missing_metric_specs_fail_even_without_pairs(self):
        for mine, theirs in (([], []), ([run(1, 0.7, 1.0)], [run(2, 0.7, 1.0)]),
                             ([run(1, 0.7, 1.0)], [run(1, 0.7, 1.0)])):
            with self.subTest(mine=mine, theirs=theirs), self.assertRaisesRegex(MetricError, "no specification"):
                metrics.compare(SPECS, PROTOCOL, mine, theirs, ["acc", "unregistered_metric"])
        with self.assertRaisesRegex(MetricError, "no specification"):
            metrics.run_values(SPECS, run(1, 0.7, 1.0), ["unregistered_metric"])
        for specs in (None, {}, {**SPECS, "metrics": [{"name": "acc"}]}):
            with self.subTest(specs=specs), self.assertRaises(MetricError):
                metrics.compare(specs, PROTOCOL, [], [], ["acc"])
        with self.assertRaisesRegex(MetricError, "protocol document"):
            metrics.compare(SPECS, None, [], [], ["acc"])
        with self.assertRaisesRegex(MetricError, "protocol document"):
            metrics.pair_key(None, run(1, 0.7, 1.0))

    def test_legacy_percent_scaling_cannot_be_requested(self):
        self.assertAlmostEqual(metrics.effect(TIME, [9.0], [10.0])["delta_mean"], 0.1)
        self.assertEqual(metrics.effect(TIME, [9.0], [10.0])["unit"], "fraction")
        with self.assertRaises(TypeError):
            metrics.effect(TIME, [9.0], [10.0], legacy_percent=True)
        for field in ("legacy", "legacy_relative_percent"):
            with self.subTest(field=field), self.assertRaisesRegex(MetricError, "unknown keys"):
                metrics.compare({**SPECS, field: True}, PROTOCOL, [], [], ["acc"])

    def test_independence_is_required_on_both_sides_and_shared_units_are_not_repeats(self):
        protocol = {**PROTOCOL, "independence_fields": ["data_order"]}
        runs = [run(seed, 0.7, 1.0, data_order="shared") for seed in (1, 2)]
        comparison = metrics.compare(SPECS, protocol, runs, runs, ["acc"])
        self.assertEqual((comparison["n_paired"], comparison["n_independent"]), (2, 1))
        distinct = [run(seed, 0.7, 1.0, data_order=f"unit-{seed}") for seed in (1, 2)]
        for mine, theirs in ((runs, distinct), (distinct, runs)):
            comparison = metrics.compare(SPECS, protocol, mine, theirs, ["acc"])
            self.assertEqual(comparison["n_independent"], 1)
        chained_mine = [run(seed, 0.7, 1.0, data_order=unit) for seed, unit in ((1, "a"), (2, "a"), (3, "c"))]
        chained_ref = [run(seed, 0.7, 1.0, data_order=unit) for seed, unit in ((1, "d"), (2, "b"), (3, "b"))]
        self.assertEqual(metrics.compare(SPECS, protocol, chained_mine, chained_ref, ["acc"])["n_independent"], 1)
        missing = [run(1, 0.7, 1.0)]
        for mine, theirs in ((runs, missing), (missing, runs)):
            with self.subTest(mine=mine), self.assertRaisesRegex(MetricError, "INDEPENDENCE_UNVERIFIED"):
                metrics.compare(SPECS, protocol, mine, theirs, ["acc"])

    def test_guardrail_missing_values_fail_closed_and_unknown_specs_are_refused(self):
        guard = metrics.guardrails(SPECS, {"metrics": {}})
        self.assertFalse(guard["train_time_s"]["passed"])
        self.assertIsNone(guard["train_time_s"]["effect"])
        with self.assertRaisesRegex(MetricError, "no specification"):
            metrics.guardrails(SPECS, {"metrics": {"unregistered_metric": {"delta_mean": 1.0}}})

    def test_effect_requires_nonempty_finite_pairs(self):
        for xs, ys in (([], []), ([1.0], [1.0, 2.0])):
            with self.subTest(xs=xs), self.assertRaisesRegex(MetricError, "PAIRING_MISMATCH"):
                metrics.effect(TIME, xs, ys)
        with self.assertRaisesRegex(MetricError, "NONFINITE_METRIC"):
            metrics.effect(TIME, [math.inf], [1.0])

    def test_gate_comparison(self):
        self.assertFalse(metrics.passes(0.2, 0.2, ">"))
        self.assertTrue(metrics.passes(0.2, 0.2, ">="))
        self.assertFalse(metrics.passes(None, 0.0, ">="))


class GivenTest(unittest.TestCase):
    def test_rounding_cross_check(self):
        self.assertTrue(metrics.matches_given(0.904, 0.90417))
        self.assertTrue(metrics.matches_given(70.0, 70.000004))
        self.assertFalse(metrics.matches_given(70.3, 70.0))  # M01
        self.assertFalse(metrics.matches_given(0.3, 0.0))  # M02
        self.assertFalse(metrics.matches_given(0.0, None))
        self.assertTrue(metrics.matches_given(None, 1.0))
        self.assertFalse(metrics.matches_given(1e-5, 2e-5))
        self.assertFalse(metrics.matches_given(70.0, 70.3))  # a whole-number claim keeps its written decimal
        self.assertFalse(metrics.matches_given(1.0, 0.6))
        self.assertTrue(metrics.matches_text("-3.3e-05", -3.333e-05))
        self.assertFalse(metrics.matches_text("70.0", 70.4))
        self.assertFalse(metrics.matches_text("n/a", 1.0))


if __name__ == "__main__":
    unittest.main()
