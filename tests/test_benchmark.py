"""REG-only formula fixture generation and current-contract, explicit-evidence scoring."""

import hashlib
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts" / "benchmark"))
sys.path.insert(0, str(ROOT / "scripts" / "scenarios"))

import score  # noqa: E402
import scorer  # noqa: E402
import make_task  # noqa: E402


class ScoreTest(unittest.TestCase):
    def episode(self, outcome="go", candidates=(), tested=(), system="C", host="claude", executor="claude-haiku-5-5"):
        return {"evidence_class": "reg", "system": system, "host": host, "version": "v", "executor_model": executor, "outcome": outcome,
                "go_candidates": [{"decision_id": f"DC-{i}", "node": f"H-{i}", "knobs": k} for i, k in enumerate(candidates)],
                "tested": [{"node": f"H-{i}", "knobs": k, "retired": r} for i, (k, r) in enumerate(tested)],
                "valid_runs": 12, "node_seconds": 7200, "user_instructions": 3, "review_cost_usd": 0.4}

    def test_reg_s7_03_another_effective_set_is_not_a_false_go(self):
        truth = {"evidence_class": "reg", "scenario": "combination", "best": ["clip", "ema"], "effective": [["clip", "ema"], ["wd"]]}
        other = score.score_episode(self.episode(candidates=[["wd"]]), truth)
        self.assertEqual((other["false_go"], other["found_effective"], other["found_best"]), (0, True, False))
        wrong = score.score_episode(self.episode(candidates=[["clip"]], tested=[(["clip", "ema"], True)]), truth)
        self.assertEqual((wrong["false_go"], wrong["found_effective"], wrong["best_retired"]), (1, False, True))
        self.assertEqual((wrong["efficiency"], wrong["user_burden"], wrong["coverage"]), (6.0, 2, 1))
        zero = score.score_episode(self.episode("not_go"), {"evidence_class": "reg", "scenario": "zero", "best": []})
        self.assertEqual((zero["false_go"], zero["found_effective"]), (0, False))

    def test_reg_s7_04_every_candidate_and_outcome_is_kept(self):
        truth = {"evidence_class": "reg", "scenario": "combination", "best": ["clip", "ema"]}
        two = score.score_episode(self.episode(candidates=[["clip", "ema"], ["clip"]]), truth)
        self.assertEqual(([c["supported"] for c in two["go_candidates"]], two["false_go"]), ([True, False], 1))
        scores = [score.score_episode(self.episode(o), truth) for o in ("blocked", "budget_stopped", "incomplete", "not_go")]
        grouped = score.group(scores)["C/claude"]
        self.assertEqual({k: v for k, v in grouped["outcomes"].items() if v},
                         {"blocked": 1, "budget_stopped": 1, "incomplete": 1, "not_go": 1})
        self.assertEqual((grouped["episodes"], grouped["false_go"]), (4, 0))  # stopping is not success, nor a false GO

    def test_reg_s7_05_one_label_one_executor_and_normalized_events(self):
        truth = {"evidence_class": "reg", "scenario": "zero", "best": []}
        mixed = [score.score_episode(self.episode("not_go", executor=m), truth) for m in ("claude-haiku-5-5", "gpt-6-luna")]
        with self.assertRaisesRegex(ValueError, "mixes executors"):
            score.group(mixed)

    def event_tables(self, status="go"):
        """The parts of a real export_snapshot the scorer reads: a project decision's field is project_status and
        its evidence is the rel_based_on edge, never a column of the decision."""
        tables = {"project": [{"id": "P-1", "status": status, "admission_paused": None, "review_cost_usd": 0.0}],
                  "run": [], "hypothesis": [{"id": "H-0001", "disposition": "active", "experiment_status": "running"}],
                  "experiment": [{"id": "E-0002", "hypothesis_id": "H-0001", "kind": "method", "stage": "screen"}],
                  "evaluation": [],
                  "decision": [{"id": "DEC-0004", "target_id": "P-1", "field": "project_status", "from_value": "active",
                                "to_value": "go", "reason": "GO", "doc_id": "D-0010", "decided_by": "main",
                                "decided_at": "2026-10-14T00:00:00Z", "basis": None}],
                  "reservation": [], "document": []}
        return tables, {"rel_based_on": []}

    def imported_run(self, root: Path, exp_id: str, metrics: dict, seed: int = 42) -> dict:
        """A valid run as import_run_result leaves it: its metrics file first in evidence_paths (relative to the
        research root) and that file's hash in import_record."""
        rel = f"outputs/{exp_id}/s{seed}/metrics.json"
        (root / rel).parent.mkdir(parents=True, exist_ok=True)
        (root / rel).write_text(json.dumps(metrics))
        return {"id": f"{exp_id}/s{seed}", "experiment_id": exp_id, "seed": seed, "attempt": 1,
                "exec_status": "succeeded", "valid": True, "manifest_path": f"outputs/{exp_id}/s{seed}/run_manifest.json",
                "evidence_paths": [rel, f"outputs/{exp_id}/s{seed}/predictions.jsonl"],
                "import_record": {"metrics_sha256": hashlib.sha256((root / rel).read_bytes()).hexdigest()}}

    def test_go_requires_exact_candidate_evidence(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            tables, edges = self.event_tables()
            tables["decision"][0]["reason"] = "E-0002 seems to help"
            # A status label or a mention in prose cannot identify a GO candidate.
            tables["hypothesis"][0]["experiment_status"] = "beats_sota"
            with self.assertRaisesRegex(ValueError, "explicit based_on"):
                score.events(tables, edges, root, "current", "codex", "v", "gpt-6-luna", "completed", None)
            # nor can another decision's evidence
            edges["rel_based_on"] = [{"source_id": "DEC-0003", "target_id": "E-0002"}]
            with self.assertRaisesRegex(ValueError, "explicit based_on"):
                score.events(tables, edges, root, "current", "codex", "v", "gpt-6-luna", "completed", None)
            edges["rel_based_on"] = [{"source_id": "DEC-0004", "target_id": "E-0002"}]
            with self.assertRaisesRegex(ValueError, "lacks explicit REG knob artifacts"):
                score.events(tables, edges, root, "current", "codex", "v", "gpt-6-luna", "completed", None)
            tables["run"] = [self.imported_run(root, "E-0002", {"accuracy": 0.81, "evidence_class": "reg",
                                                                 "knobs": ["ema"]})]
            tables["evaluation"] = [{"id": "EV-0003", "experiment_id": "E-0002"}]
            edges["rel_based_on"] = [{"source_id": "DEC-0004", "target_id": "E-0002"},
                                     {"source_id": "DEC-0004", "target_id": "EV-0003"}]
            # A later unrelated method must not replace the explicitly cited experiment.
            tables["experiment"].append({"id": "E-0010", "hypothesis_id": "H-0001", "kind": "method"})
            ep = score.events(tables, edges, root, "current", "codex", "v", "gpt-6-luna", "completed", None)
            self.assertEqual([(c["node"], c["experiment_id"], c["knobs"]) for c in ep["go_candidates"]],
                             [("H-0001", "E-0002", ["ema"])])
            self.assertIsNone(ep["tested"][1]["knobs"])
            edges["rel_based_on"] = [{"source_id": "DEC-0004", "target_id": "E-0010"}]
            with self.assertRaisesRegex(ValueError, "E-0010 lacks"):
                score.events(tables, edges, root, "current", "codex", "v", "gpt-6-luna", "completed", None)

    def test_zero_usage_and_missing_knob_evidence_are_not_reinterpreted(self):
        tables, edges = self.event_tables("active")
        tables["decision"] = []
        tables["reservation"] = [{"actual_units": 0, "reserved_units": 100, "accounting_status": "settled"}]
        ep = score.events(tables, edges, Path("/nonexistent"), "current", None, None, None, None, None)
        self.assertEqual(ep["node_seconds"], 0)
        scored = score.score_episode(ep, {"evidence_class": "reg", "best": []})
        self.assertEqual((scored["coverage"], scored["unscored_experiments"]), (0, ["E-0002"]))
        tables["project"][0]["status"] = "closed_not_go"
        with self.assertRaisesRegex(ValueError, "unsupported project status"):
            score.events(tables, edges, Path("/nonexistent"), "current", None, None, None, None, None)

    def test_formula_scoring_cannot_masquerade_as_real_evidence(self):
        episode = self.episode(candidates=[["ema"]])
        truth = {"evidence_class": "reg", "best": ["ema"]}
        for unlabeled in ({}, {"evidence_class": "real_sc"}):
            with self.assertRaisesRegex(ValueError, "REG episode and truth labels"):
                score.score_episode({**episode, **unlabeled, "evidence_class": unlabeled.get("evidence_class")}, truth)
            with self.assertRaisesRegex(ValueError, "REG episode and truth labels"):
                score.score_episode(episode, {**truth, "evidence_class": unlabeled.get("evidence_class")})
        with self.assertRaisesRegex(ValueError, "explicit candidate evidence"):
            score.score_episode(self.episode(), truth)

    def test_snapshot_rejects_old_or_absent_project_contract(self):
        with tempfile.TemporaryDirectory() as tmp:
            project = Path(tmp)
            for version in (None, 1, 2, True):
                (project / ".research-tree.json").write_text(json.dumps({"format_version": version}))
                with self.assertRaisesRegex(ValueError, "version-3"):
                    score.snapshot(project, Path("/nonexistent"))

    def test_snapshot_requires_current_schema_and_exact_read_only_actor(self):
        with tempfile.TemporaryDirectory() as tmp:
            project = Path(tmp)
            (project / ".research-tree.json").write_text(json.dumps({"format_version": 3, "db": "fixture.db", "root": tmp}))
            for version in (22, 23):
                exported = {"ok": True, "result": {"meta": {"schema_version": version}, "tables": {}, "edges": {}}}
                with mock.patch.object(score.subprocess, "run", return_value=subprocess.CompletedProcess(
                        args=[], returncode=0, stdout=json.dumps(exported))) as run:
                    if version == 22:
                        with self.assertRaisesRegex(ValueError, "schema 23"):
                            score.snapshot(project, Path("/tools"))
                    else:
                        self.assertEqual(score.snapshot(project, Path("/tools")), ({}, {}, project))
                    argv = run.call_args.args[0]
                    self.assertEqual(argv[argv.index("--actor") + 1], "ui/ui")

    def test_snapshot_runs_research_db_under_the_repository_environment(self):
        """The system python3 lacks the database's dependencies: the export runs under the repository's .venv
        whenever it exists, whichever interpreter runs the scorer."""
        venv = ROOT / ".venv" / "bin" / "python"
        with tempfile.TemporaryDirectory() as tmp:
            project = Path(tmp)
            (project / ".research-tree.json").write_text(json.dumps({"format_version": 3, "db": "fixture.db", "root": tmp}))
            exported = {"ok": True, "result": {"meta": {"schema_version": 23}, "tables": {}, "edges": {}}}
            with mock.patch.object(score.subprocess, "run", return_value=subprocess.CompletedProcess(
                    args=[], returncode=0, stdout=json.dumps(exported))) as run:
                score.snapshot(project, Path("/tools"))
            self.assertEqual(run.call_args.args[0][0], str(venv) if venv.is_file() else sys.executable)

    def test_conflicting_or_unmarked_artifacts_never_identify_a_candidate(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            runs = [self.imported_run(root, "E-0002", {"evidence_class": "reg", "knobs": knobs}, seed)
                    for seed, knobs in ((42, ["ema"]), (43, ["clip"]))]
            with self.assertRaisesRegex(ValueError, "disagree"):
                score._knobs(root, runs, "E-0002")
            runs = [self.imported_run(root, "E-0002", {"knobs": ["ema"]}, seed) for seed in (42, 43)]
            self.assertIsNone(score._knobs(root, runs, "E-0002"))
            # a metrics file changed after its import is not the imported artifact
            run = self.imported_run(root, "E-0002", {"evidence_class": "reg", "knobs": ["ema"]})
            self.assertEqual(score._knobs(root, [run], "E-0002"), ["ema"])
            (root / run["evidence_paths"][0]).write_text(json.dumps({"evidence_class": "reg", "knobs": ["clip"]}))
            self.assertIsNone(score._knobs(root, [run], "E-0002"))
            # a run reported without an import (no import_record) carries no artifact
            self.assertIsNone(score._knobs(root, [{**run, "import_record": None}], "E-0002"))

    def test_task_truth_stays_outside_the_project(self):
        with tempfile.TemporaryDirectory() as tmp:
            dest = Path(tmp) / "t"
            out = subprocess.run([sys.executable, str(ROOT / "scripts" / "benchmark" / "make_task.py"), str(dest),
                                  "--scenario", "combination", "--seed", "3"], capture_output=True, text=True)
            self.assertEqual(out.returncode, 0, out.stderr)
            truth = json.loads((dest / "truth.json").read_text())
            project = dest / "project"
            self.assertNotIn(str(truth["salt"]), "".join(p.read_text(errors="ignore") for p in project.rglob("*")
                                                         if p.is_file() and ".git" not in p.parts))
            code = project / "code"

            def accuracy(knobs, with_truth=True):
                env = {"PATH": "/usr/bin:/bin"}
                if with_truth:
                    env["RT_BENCH_TRUTH"] = str(dest / "truth.json")
                run = subprocess.run([sys.executable, "-m", "toytrain.train", "--seed", "1", "--out", str(dest / "o"),
                                      "--knobs", ",".join(knobs)], cwd=code, env=env, capture_output=True, text=True)
                return json.loads(run.stdout)["accuracy"]
            plain = accuracy([], with_truth=False)
            self.assertAlmostEqual(accuracy(truth["best"]) - plain, 0.03, delta=0.006)
            self.assertAlmostEqual(accuracy(truth["best"][:1]) - plain, 0.0, delta=0.006)


def make(dest: Path, scenario: str) -> dict:
    out = subprocess.run([sys.executable, str(ROOT / "scripts" / "benchmark" / "make_task.py"), str(dest),
                          "--scenario", scenario, "--seed", "5"], capture_output=True, text=True)
    assert out.returncode == 0, out.stderr
    return json.loads((dest / "truth.json").read_text())


def run(dest: Path, knobs, seed=1, lr=0.05, epochs=8):
    env = {"PATH": "/usr/bin:/bin", "RT_BENCH_TRUTH": str(dest / "truth.json")}
    done = subprocess.run([sys.executable, "-m", "toytrain.train", "--seed", str(seed), "--out", str(dest / "o"),
                           "--knobs", ",".join(knobs), "--lr", str(lr), "--epochs", str(epochs)],
                          cwd=dest / "project" / "code", env=env, capture_output=True, text=True)
    return json.loads(done.stdout)["accuracy"] if done.returncode == 0 else None


def search_seeds(dest: Path) -> list[int]:
    """The seeds the generated project's configuration runs its search on."""
    import yaml
    verification = yaml.safe_load((dest / "project" / "research-tree.yaml").read_text())["verification"]
    return verification["screening_seeds"] + verification["replication_seeds"]


class ScenarioTest(unittest.TestCase):
    def test_current_runner_records_fixture_labels_and_measured_control(self):
        with tempfile.TemporaryDirectory() as tmp:
            dest = Path(tmp) / "t"
            truth = make(dest, "gain")
            project, out = dest / "project", dest / "out"
            config = project / "code/configs/knobs.json"
            config.write_text(json.dumps({"knobs": ",".join(truth["best"]), "epochs": 1}))
            env = {**os.environ, "RT_BENCH_TRUTH": str(dest / "truth.json")}
            done = subprocess.run([sys.executable, "-m", "toytrain.run", "--experiment", "E-1", "--seed", "42",
                                   "--out", str(out), "--config", str(config)], cwd=project / "code", env=env,
                                  capture_output=True, text=True)
            self.assertEqual(done.returncode, 0, done.stderr)
            manifest = json.loads((out / "run_manifest.json").read_text())
            metrics = json.loads((out / "metrics.json").read_text())
            provenance = json.loads((dest / "project.ctl/scenario.json").read_text())
            for artifact in (truth, manifest, metrics, provenance):
                self.assertEqual(artifact["evidence_class"], "reg")
                self.assertIn("formula_metric", artifact["substitutes_used"])
            self.assertEqual(metrics["knobs"], truth["best"])
            self.assertEqual(manifest["config"]["knobs"], ",".join(truth["best"]))
            independent = scorer.score_output(out, project / "code/data")
            self.assertEqual(independent["accuracy"], metrics["measured_accuracy"])
            self.assertFalse(independent["accuracy_matches"])
            self.assertAlmostEqual(metrics["accuracy"] - independent["accuracy"], 0.03, delta=0.006)
            self.assertIn("REG-only", (project / "plan.md").read_text())

    def test_runner_fault_leaves_a_real_failed_manifest_then_recovers(self):
        with tempfile.TemporaryDirectory() as tmp:
            dest = Path(tmp) / "t"
            truth = make(dest, "faults")
            seed = str(truth["faults"][0]["seed"])
            env = {**os.environ, "RT_BENCH_TRUTH": str(dest / "truth.json")}
            for attempt in (1, 2):
                out = dest / f"out-{attempt}"
                done = subprocess.run([sys.executable, "-m", "toytrain.run", "--experiment", "E-1", "--seed", seed,
                                       "--attempt", str(attempt), "--out", str(out), "--knobs", "", "--epochs", "1"],
                                      cwd=dest / "project/code", env=env, capture_output=True, text=True)
                self.assertEqual(done.returncode, 1 if attempt == 1 else 0, done.stderr)
                manifest = json.loads((out / "run_manifest.json").read_text())
                self.assertEqual(manifest["exit_status"], done.returncode)
                self.assertEqual(manifest["attempt"], attempt)
                self.assertEqual(manifest["evidence_class"], "reg")
                if attempt == 1:
                    self.assertIn("RuntimeError: benchmark fixture fault", manifest["error"])

    def test_fixture_patching_fails_closed_when_the_scaffold_changes(self):
        with self.assertRaisesRegex(ValueError, "exactly one"):
            make_task.replace_once("new scaffold", "old scaffold", "fixture")
        with self.assertRaisesRegex(ValueError, "exactly one"):
            make_task.replace_once("anchor anchor", "anchor", "fixture")

    def test_confound_gain_is_explained_by_the_learning_rate(self):
        with tempfile.TemporaryDirectory() as tmp:
            dest = Path(tmp) / "t"
            truth = make(dest, "confound")
            knob = truth["confound"]
            # at the generated project's frozen reference setting, where its baseline and screening runs train
            reference = json.loads((dest / "project/code/configs/reference.json").read_text())
            lr, epochs = reference["lr"], reference["epochs"]
            self.assertGreater(run(dest, [knob], lr=lr, epochs=epochs) - run(dest, [], lr=lr, epochs=epochs),
                               0.01)  # the knob seems to help
            self.assertAlmostEqual(run(dest, [knob], lr=lr, epochs=epochs), run(dest, [], lr=2 * lr, epochs=epochs),
                                   delta=0.012)  # matched lr: same

    def test_faults_fail_once_then_recover(self):
        with tempfile.TemporaryDirectory() as tmp:
            dest = Path(tmp) / "t"
            truth = make(dest, "faults")
            seeds = {f["seed"] for f in truth["faults"]}
            # the faults hit seeds the generated project really runs, not seeds no version-3 run uses
            self.assertTrue(seeds and seeds <= set(search_seeds(dest)))
            seed = min(seeds)
            self.assertIsNone(run(dest, [], seed=seed))
            self.assertIsNotNone(run(dest, [], seed=seed))
            self.assertIsNotNone(run(dest, [], seed=0))


class GatherTest(unittest.TestCase):
    def fixture(self):
        """A real project database (the shared tests' Fixture) and the version-3 marker that points at it."""
        sys.path.insert(0, str(ROOT / "shared" / "research-tree" / "tests"))
        from test_research_db import Fixture
        fixture = type("F", (Fixture,), {"runTest": lambda self: None})()
        fixture.setUp()
        self.addCleanup(fixture.tearDown)
        marker = fixture.root.parent.parent / ".research-tree.json"
        marker.write_text(json.dumps({"format_version": 3, "db": str(fixture.db), "root": str(fixture.root)}))
        return fixture, marker

    def test_gather_reads_a_project_database(self):
        fixture, marker = self.fixture()
        h = fixture.hypothesis()
        fixture.start(h)
        exp = fixture.method(h, n_seeds=1)
        fixture.finish_runs(fixture.worker, exp)
        ep = score.normalize(marker.parent, ROOT / "shared" / "research-tree" / "tools", "C", "claude", "test")
        self.assertEqual(ep["outcome"], "active")
        self.assertGreaterEqual(ep["valid_runs"], 1)
        self.assertTrue(any(t["knobs"] is None for t in ep["tested"]))
        self.assertEqual(ep["attempts"]["duplicate_jobs"], 0)
        before = hashlib.sha256(fixture.db.read_bytes()).hexdigest()
        for name in ("db_snapshot", "usage_snapshot"):
            path = fixture.root / f"{name}.json"
            done = subprocess.run([sys.executable, str(ROOT / "scripts/scenarios" / f"{name}.py"), str(marker.parent),
                                   str(ROOT / "shared/research-tree/tools"), str(path)], capture_output=True, text=True)
            self.assertEqual(done.returncode, 0, done.stderr)
            result = json.loads(path.read_text())
            self.assertIn("tables" if name == "db_snapshot" else "material_usage", result)
        self.assertEqual(hashlib.sha256(fixture.db.read_bytes()).hexdigest(), before)

    def test_a_recorded_go_names_its_candidate_from_the_snapshot(self):
        """A GO made through the interface (a project_status decision whose evidence is a rel_based_on edge), on a
        method whose runs were imported from REG-marked metrics files, yields exactly that candidate and knobs."""
        fixture, marker = self.fixture()
        h = fixture.hypothesis()
        fixture.start(h)
        exp = fixture.method(h)
        fixture.effects[exp] = (fixture.sota, (0.3, 0.1, 0.1))
        fixture.imported(exp, values={**fixture.values_for(exp), "evidence_class": "reg", "knobs": ["ema"]})
        actor = fixture.owner_for(exp)
        evaluation = actor.evaluate_experiment(exp, fixture.result_doc(actor=actor, exp=exp))["evaluation_id"]
        fixture.rld.decide(h, {"experiment_status": "beats_sota"}, "gate", based_on=[exp])
        fixture.recheck_pass(h, exp)
        fixture.complete_confirmation(h, exp)
        fixture.rld.decide("P-test", {"status": "go"}, "GO", doc_id=fixture.report_doc("go"), based_on=[evaluation])
        ep = score.normalize(marker.parent, ROOT / "shared" / "research-tree" / "tools", "C", "claude", "test")
        self.assertEqual(ep["outcome"], "go")
        self.assertEqual([(c["node"], c["experiment_id"], c["knobs"]) for c in ep["go_candidates"]],
                         [(h, exp, ["ema"])])

if __name__ == "__main__":
    unittest.main()
