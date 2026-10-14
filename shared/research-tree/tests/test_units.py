"""S3 (plans/research-tree-implementation-and-real-scenarios.md §7.4): imported values keep the units they were
reported in; history is never reinterpreted; independence fields are complete on both sides; incomplete records
are rejected without reconstruction. REG-S3-01..07. The numbers are REG fixtures, not measurements."""

from __future__ import annotations

import json
import math
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))

from test_research_db import PROTOCOL, SPECS, Fixture, MetricErrorAlias, ResearchDB, ResearchDBError, metrics_mod  # noqa: E402

GUARDED = json.loads(json.dumps(SPECS))
GUARDED["metrics"][2]["allowed_regression"] = 1.0  # peak memory may grow by at most 1 GiB


class S3Test(Fixture):
    specs_content = GUARDED

    def setUp(self):
        super().setUp()
        self.base = self.imported_baseline()
        self.h = self.hypothesis()
        self.start(self.h)
        self.n_spec = 1

    def imported_baseline(self, **per_seed) -> str:
        design = self.doc(self.worker, f"exp/ib{self.n}.v1.md", "experiment_design")
        base = self.architect.create_experiment("baseline", "sota", design, self.harness, 1, 1800,
                                             method_config={"lr": 0.05, "design": design}, estimated_node_h=1.0)
        self.import_all(base, **per_seed)
        self.owner_for(base).evaluate_experiment(base, self.result_doc(exp=base))
        self.rld.update_project(sota_experiment_id=base)
        return base

    def import_all(self, exp: str, effect: tuple | None = None, **per_seed) -> None:
        """Every run of exp imported and accepted; per_seed: field -> [value per seed] (None: left out)."""
        if effect is not None:
            self.effects[exp] = effect
        for i, seed in enumerate(self.rld.get(exp)["seeds"]):
            run = f"{exp}/s{seed}"
            self.owner_for(exp).create_run(exp, seed)
            self.owner_for(exp).update_run(run, exec_status="submitted")
            self.owner_for(exp).update_run(run, exec_status="succeeded")
            extra = {k: v[i] for k, v in per_seed.items() if v[i] is not None}
            self.owner_for(exp).import_run_result(run, 1, self.manifest(exp, seed, **extra))
            self.owner_for(exp).update_run(run, valid=True)

    def respec(self, edit, **project) -> str:
        """The user's specification change (a new metric_spec document and the instruction that records it)."""
        specs = json.loads(json.dumps(self.specs_content if self.n_spec == 1 else self.current_spec))
        edit(specs)
        self.n_spec += 1
        self.n_doc = getattr(self, "n_doc", 1) + 1
        doc = self.doc(self.rld, f"project/metric-spec.v{self.n_doc}.json", "metric_spec", body=json.dumps(specs))
        ui = self.doc(ResearchDB(self.db, "ui/ui"), f"instructions/UI-09{self.n_doc:02d}.v1.md", "user_instruction")
        self.rld.update_project(metric_spec_doc_id=doc, user_instruction_doc_id=ui, **project)
        self.current_spec = specs
        return doc

    def evaluated(self, exp: str) -> dict:
        self.owner_for(exp).evaluate_experiment(exp, self.result_doc(exp=exp))
        return self.rld.evaluations(experiment_id=exp)[-1]

    def mem(self, specs, **changes):
        specs["metrics"][2].update(changes)

    def test_reg_s3_01_old_values_are_not_reinterpreted(self):
        exp = self.method(self.h)
        self.import_all(exp, effect=(self.base, (0.3, 0.1, -2.0)))  # 40 -> 42 GiB, allowed +1 GiB
        ev = self.evaluated(exp)
        self.assertFalse(ev["guardrails_passed"])
        n_before = len(self.rld.evaluations())
        self.respec(lambda s: self.mem(s, input_unit="mib"))  # read "42" as MiB (0.04 GiB): would pass
        with self.assertRaisesRegex(ResearchDBError, "METRIC_UNIT_MISMATCH: .*reported peak_mem_gb in gib"):
            self.owner_for(self.base).evaluate_experiment(self.base, self.result_doc(exp=self.base))
        with self.assertRaisesRegex(ResearchDBError, "METRIC_UNIT_MISMATCH: .*reported peak_mem_gb in gib"):
            self.owner_for(exp).evaluate_experiment(exp, self.result_doc(exp=exp))
        self.assertEqual(len(self.rld.evaluations()), n_before)
        self.assertFalse(self.rld.evaluations(experiment_id=exp)[-1]["guardrails_passed"])
        self.assertNotIn("METRIC_SPEC_CHANGED", self.rld.get_eligibility(self.h)["reasons"])  # the old one stands
        # a future run stating the new unit is read in it; a run still stating gib is refused at import
        later = self.method(self.h, n_seeds=1)
        run = f"{later}/s42"
        self.owner_for(later).create_run(later, 42)
        self.owner_for_run(run).update_run(run, exec_status="submitted")
        self.owner_for_run(run).update_run(run, exec_status="succeeded")
        with self.assertRaisesRegex(ResearchDBError, "METRIC_UNIT_MISMATCH: .*declares units"):
            self.owner_for_run(run).import_run_result(run, 1, self.manifest(later, 42))

    def test_reg_s3_02_an_auxiliary_canonical_unit_converts_equivalently(self):
        exp = self.method(self.h)
        self.import_all(exp, effect=(self.base, (0.3, 0.1, -2.0)))
        old = self.evaluated(exp)
        self.respec(lambda s: self.mem(s, canonical_unit="mib", allowed_regression=1024.0))
        self.evaluated(self.base)
        new = self.evaluated(exp)
        g_old, g_new = (e["comparisons"]["sota"]["guardrails"]["peak_mem_gb"] for e in (old, new))
        self.assertAlmostEqual(g_new["effect"], g_old["effect"] * 1024)
        self.assertEqual((g_old["passed"], g_new["passed"], new["guardrails_passed"]), (False, False, False))
        self.respec(lambda s: self.mem(s, allowed_regression=2048.0))  # 2 GiB allowed: both readings pass
        self.evaluated(self.base)
        self.assertTrue(self.evaluated(exp)["guardrails_passed"])
        self.assertEqual(new["comparisons"]["sota"]["n_paired"], 3)  # no new training, no new pairs

    def test_reg_s3_03_the_import_snapshot_is_kept(self):
        exp = self.method(self.h, n_seeds=1)
        run = f"{exp}/s42"
        self.owner_for(exp).create_run(exp, 42)
        self.owner_for_run(run).update_run(run, exec_status="submitted")
        self.owner_for_run(run).update_run(run, exec_status="succeeded")
        config = {"lr": 0.05, "optimizer": {"name": "sgd", "betas": [0.9, 0.99]}}
        env = {"python": "3.13", "libs": {"numpy": "2.1.0"}}
        path = self.manifest(exp, 42, config=config, env=env)
        self.owner_for_run(run).import_run_result(run, 1, path)
        original = json.loads((self.root / path).read_text())
        stored = self.rld.get(run)
        self.assertEqual(stored["manifest_snapshot"], original)
        self.assertEqual(stored["manifest_snapshot"]["config"]["optimizer"]["betas"], [0.9, 0.99])
        self.assertEqual(stored["import_record"]["units"], original["units"])
        self.assertEqual(stored["import_record"]["metric_spec_doc_id"], self.specs)
        (self.root / path).write_text(json.dumps({**original, "units": {"acc": "fraction"}, "config": {"lr": 9}}))
        self.assertEqual(self.rld.get(run)["manifest_snapshot"], original)  # the file changed, the snapshot did not

    def test_reg_s3_05_scale_is_a_hint_range_is_a_rule(self):
        frac = {"name": "f", "direction": "higher", "input_unit": "fraction", "canonical_unit": "fraction",
                "effect_mode": "absolute", "minimum_practical_gain": 0.0, "aggregation": "paired_run_mean"}
        self.assertIsNotNone(metrics_mod.check_unit_mix(frac, [0.001, 0.1], "r"))  # a hint, not an error
        for value in (0.001, 0.1):
            self.assertEqual(metrics_mod.canonical(frac, value, "r"), value)
        for bad in (1.5, -0.1, math.nan, math.inf):
            with self.assertRaises(MetricErrorAlias):
                metrics_mod.canonical(frac, bad, "r")
        with self.assertRaisesRegex(MetricErrorAlias, "no conversion from fraction to gib"):
            metrics_mod.check_spec({**frac, "canonical_unit": "gib"})
        with self.assertRaisesRegex(MetricErrorAlias, "no conversion from gib to seconds"):
            metrics_mod.check_spec({**frac, "input_unit": "gib", "canonical_unit": "seconds"})

    def test_reg_s3_06_missing_raw_units_are_rejected_without_rewriting_history(self):
        exp = self.method(self.h)
        self.import_all(exp, effect=(self.base, (0.3, 0.1, 0.1)))
        run = f"{exp}/s42"
        before = self.rld.get(run)
        record = {k: v for k, v in before["import_record"].items() if k not in ("units", "raw_values")}
        self.raw(run, import_record=record)
        with self.assertRaisesRegex(ResearchDBError, "RAW_METADATA_UNVERIFIED"):
            self.rld.preview_evaluation(exp)
        self.assertFalse(hasattr(self.rld, "migrate_units"))
        self.assertEqual(self.rld.get(run)["import_record"], record)
        self.assertEqual(self.rld.get(run)["secondary"], before["secondary"])
        self.assertEqual(self.rld.evaluations(experiment_id=exp), [])

    def test_reg_s3_07_the_primary_contract_and_the_imported_encoding_are_frozen(self):
        exp = self.method(self.h)
        self.import_all(exp, effect=(self.base, (0.3, 0.1, 0.1)))
        raise_gain = lambda s: s["metrics"][0].update(minimum_practical_gain=0.5)  # noqa: E731
        for edit, project, refusal in (
                (lambda s: s["metrics"][0].update(canonical_unit="percentage"), {},
                 "METRIC_UNIT_MISMATCH: .*canonical_unit is frozen"),
                (raise_gain, {}, "METRIC_UNIT_MISMATCH: .*must equal the project's go_margin"),
                (raise_gain, {"go_margin": 0.5}, "go_margin.*fixed once experiments exist")):
            with self.assertRaisesRegex(ResearchDBError, refusal):
                self.respec(edit, **project)
            self.n_spec -= 1
        self.assertEqual(self.rld.get("P-test")["go_margin"], 0.05)
        run = f"{exp}/s42"
        before = self.rld.get(run)
        units = {**before["import_record"]["units"], "peak_mem_gb": "mib"}
        with self.assertRaises(ResearchDBError):  # same attempt, another encoding: no overwrite
            self.owner_for_run(run).import_run_result(run, 1, self.manifest(exp, 42, units=units))
        with self.assertRaisesRegex(ResearchDBError, "valid and frozen"):  # no new attempt for a valid result
            self.owner_for_run(run).update_run(run, attempt=2, exec_status="submitted")
        after = self.rld.get(run)
        self.assertEqual((after["attempt"], after["import_record"], after["secondary"]),
                         (before["attempt"], before["import_record"], before["secondary"]))


class S3IndependenceTest(S3Test):
    protocol_content = {**PROTOCOL, "independence_fields": ["data_order"]}

    def setUp(self):
        Fixture.setUp(self)
        self.base = self.imported_baseline(data_order=["a", "b", "c"])
        self.h = self.hypothesis()
        self.start(self.h)
        self.n_spec = 1

    test_reg_s3_01_old_values_are_not_reinterpreted = None
    test_reg_s3_02_an_auxiliary_canonical_unit_converts_equivalently = None
    test_reg_s3_03_the_import_snapshot_is_kept = None
    test_reg_s3_05_scale_is_a_hint_range_is_a_rule = None
    test_reg_s3_06_missing_raw_units_are_rejected_without_rewriting_history = None
    test_reg_s3_07_the_primary_contract_and_the_imported_encoding_are_frozen = None

    def test_reg_s3_04_a_missing_key_is_not_an_independent_unit(self):
        exp = self.method(self.h)
        with self.assertRaisesRegex(ResearchDBError, "INDEPENDENCE_UNVERIFIED: .*data_order"):
            self.import_all(exp, effect=(self.base, (0.3, 0.1, 0.1)), data_order=["a", "b", None])
        self.assertIsNone(self.rld.get(f"{exp}/s44").get("import_record"))  # nothing half-written
        run = f"{exp}/s44"
        self.owner_for_run(run).import_run_result(run, 1, self.manifest(exp, 44, data_order="b"))
        self.owner_for_run(run).update_run(run, valid=True)
        again = self.owner_for_run(run).import_run_result(run, 1, self.manifest(exp, 44, data_order="b"))  # a repeated import
        self.assertFalse(again["imported"])
        ev = self.evaluated(exp)
        self.assertEqual((ev["comparisons"]["sota"]["n_paired"], ev["comparisons"]["sota"]["n_independent"]), (3, 2))
        # a run missing its bound field on either side: unverified, not a third unit
        for side in (f"{exp}/s44", f"{self.base}/s44"):
            manifest = dict(self.rld.get(side)["manifest"])
            self.raw(side, manifest={k: v for k, v in manifest.items() if k != "data_order"})
            with self.assertRaisesRegex(ResearchDBError, "INDEPENDENCE_UNVERIFIED"):
                self.owner_for(exp).evaluate_experiment(exp, self.result_doc(exp=exp))
            self.raw(side, manifest=manifest)


class AdviceIndependenceTest(Fixture):
    protocol_content = {**PROTOCOL, "independence_fields": ["data_order"],
                        "repetition": {"enabled": True, "se_multiple": 2.0, "batch": 2,
                                       "seed_pool": [45, 46, 47]}}

    def test_shared_reference_and_cross_pair_units_never_get_numeric_advice(self):
        h = self.hypothesis()
        self.start(h)
        exp = self.method(h)
        self.finish_runs(self.worker, exp, effect=(self.sota, (0.6, 0.0, 0.0)))
        for e in (exp, self.sota):
            for seed, unit in zip((42, 43, 44), ("a", "b", "c")):
                self.raw(f"{e}/s{seed}", manifest={"data_order": unit})
        before = len(self.rld.find("run"))
        verified = self.rld.repetition_advice(exp)
        self.assertEqual(verified["n_independent"], 3)
        self.raw(f"{self.sota}/s43", manifest={"data_order": "a"})
        shared = self.rld.repetition_advice(exp)
        self.assertEqual(shared["advice"], "independence_unverified")
        self.assertNotIn("se", shared)
        # Every side has distinct units, but another pair reuses the reference's unit.
        self.raw(f"{self.sota}/s43", manifest={"data_order": "c"})
        self.raw(f"{self.sota}/s44", manifest={"data_order": "d"})
        chained = self.rld.repetition_advice(exp)
        self.assertEqual(chained["advice"], "independence_unverified")
        self.assertNotIn("seeds", chained)
        self.assertEqual(len(self.rld.find("run")), before)


if __name__ == "__main__":
    unittest.main()
