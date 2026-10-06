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
        ):
            with self.subTest(message=message), self.assertRaisesRegex(MetricError, message):
                metrics.check_metric_specs(bad)

    def test_protocol(self):
        metrics.check_protocol({"version": 1, "eval_type": "synthetic_proxy", "pair_fields": ["seed", "split"],
                                "profile": "screening"})
        with self.assertRaisesRegex(MetricError, "at least 3 confirmation_seeds"):
            metrics.check_protocol({"version": 1, "eval_type": "real_gt"})  # stage1_confirmed is the default
        metrics.check_protocol({"version": 1, "eval_type": "real_gt", "confirmation_seeds": [1042, 1043, 1044]})
        with self.assertRaisesRegex(MetricError, "including seed"):
            metrics.check_protocol({"version": 1, "eval_type": "real_gt", "pair_fields": ["split"]})
        with self.assertRaisesRegex(MetricError, "eval_type"):
            metrics.check_protocol({"version": 1, "eval_type": "proxy"})


class EffectTest(unittest.TestCase):
    def test_m04_fraction_to_percentage_points(self):
        cmp = metrics.compare(SPECS, None, [run(42, 0.701, 10.0)], [run(42, 0.699, 10.0)], ["acc", "train_time_s"])
        self.assertAlmostEqual(cmp["metrics"]["acc"]["delta_mean"], 0.2, places=9)  # not 20, not 0.2 %
        self.assertEqual(cmp["metrics"]["acc"]["unit"], "percentage_point")

    def test_m03_lower_is_better_and_relative(self):
        mine = [run(s, 0.7, 9.0) for s in (1, 2)]
        ref = [run(s, 0.7, 10.0) for s in (1, 2)]
        effect = metrics.compare(SPECS, None, mine, ref, ["acc", "train_time_s"])["metrics"]["train_time_s"]
        self.assertAlmostEqual(effect["delta_mean"], 0.1, places=9)  # 10% faster is +0.1
        self.assertIsNone(effect["delta_sd"])
        guard = metrics.guardrails(SPECS, metrics.compare(SPECS, None, [run(1, 0.7, 11.5)], [run(1, 0.7, 10.0)],
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
        protocol = {"version": 1, "eval_type": "real_gt", "pair_fields": ["seed", "split"]}
        cmp = metrics.compare(SPECS, protocol, [run(42, 0.7, 1.0, split="b")], [run(42, 0.7, 1.0, split="a")],
                              ["acc"])
        self.assertEqual((cmp["n_paired"], cmp["unpaired_same_seed"]), (0, [42]))
        with self.assertRaisesRegex(MetricError, "does not record"):
            metrics.compare(SPECS, protocol, [run(42, 0.7, 1.0)], [run(42, 0.7, 1.0, split="a")], ["acc"])
        with self.assertRaisesRegex(MetricError, "repeated seed"):
            metrics.compare(SPECS, None, [run(42, 0.7, 1.0), {**run(42, 0.7, 1.0), "id": "E-1/x"}], [], ["acc"])

    def test_m09_relative_denominator(self):
        effect = metrics.effect(TIME, [0.5], [0.4])
        self.assertEqual(effect["undefined"], "RELATIVE_EFFECT_UNDEFINED")
        self.assertIsNone(effect["delta_mean"])

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
