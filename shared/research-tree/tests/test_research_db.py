"""Tests for tools/research_db.py. Run: .venv/bin/python -m unittest discover -s tests"""

from __future__ import annotations

import importlib.util
import json
import shutil
import subprocess
import sys
import tempfile
import textwrap
import unittest
from pathlib import Path

from latticedb import Database

REPO = Path(__file__).resolve().parent.parent


def load(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


create_db = load("create_db", REPO / "schema" / "create_db.py")
metrics_mod = load("metrics", REPO / "tools" / "metrics.py")
MetricErrorAlias = metrics_mod.MetricError
rdb = load("research_db", REPO / "tools" / "research_db.py")
ResearchDB, ResearchDBError, PermissionDenied = rdb.ResearchDB, rdb.ResearchDBError, rdb.PermissionDenied

SEEDS = [42, 43, 44]
SECONDARY = ["final_loss", "peak_mem_gb"]
METRICS = ["acc"] + SECONDARY
BASE = {"acc": 70.0, "final_loss": 1.0, "peak_mem_gb": 40.0}  # every SOTA run
SIGN = {"acc": 1, "final_loss": -1, "peak_mem_gb": -1}  # +1: higher is better
SPECS = {"version": 1, "primary": "acc", "metrics": [
    {"name": "acc", "direction": "higher", "input_unit": "percentage", "canonical_unit": "percentage_point",
     "effect_mode": "absolute", "minimum_practical_gain": 0.05, "aggregation": "paired_run_mean",
     "valid_range": [0, 100]},
    {"name": "final_loss", "direction": "lower", "input_unit": "nats", "canonical_unit": "nats",
     "effect_mode": "absolute", "minimum_practical_gain": 0.0, "aggregation": "paired_run_mean"},
    {"name": "peak_mem_gb", "direction": "lower", "input_unit": "gib", "canonical_unit": "gib",
     "effect_mode": "absolute", "minimum_practical_gain": 0.0, "aggregation": "paired_run_mean"},
]}
PROTOCOL = {"version": 1, "eval_type": "real_gt", "pair_fields": ["seed"], "profile": "screening"}


class Fixture(unittest.TestCase):
    """A project with a metric specification, a protocol, a frozen harness and an evaluated SOTA baseline
    (0.5 node-hours per seed). Every number the tests evaluate comes from the runs: a method experiment's runs
    are the SOTA's (or a parent experiment's) values shifted by the effects the test names."""

    sota_nodes, sota_walltime_s = 1, 1800
    specs_content, protocol_content = SPECS, PROTOCOL

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name) / "research" / "P-test"
        (self.root / "docs").mkdir(parents=True)
        self.db = self.root / "research_tree.db"
        create_db.create_db(self.db)
        self.rld = ResearchDB(self.db, "rld/main")
        self.worker = ResearchDB(self.db, "worker/w1")
        self.n = 0
        self.effects: dict[str, tuple[str, tuple]] = {}

        self.repo = Path(self.tmp.name) / "code"
        (self.repo / "harness").mkdir(parents=True)
        self.git("init", "-q", "-b", "main")
        self.harness = self.commit({"harness/stats.py": "stats v1\n"})

        setup = self.doc(self.rld, "project/min-setup.v1.md", "min_setup")
        self.specs = self.doc(self.rld, "project/metric-spec.v1.json", "metric_spec",
                              body=json.dumps(self.specs_content))
        self.protocol = self.doc(self.rld, "project/protocol.v1.json", "protocol",
                                 body=json.dumps(self.protocol_content))
        self.rld.create_project("P-test", "test", setup, "acc", "higher", True, SECONDARY, SEEDS,
                                repo_path=str(self.repo), metric_spec_doc_id=self.specs,
                                protocol_doc_id=self.protocol)
        self.rld.update_project(harness_ref=self.harness, harness_paths=["harness"])
        self.literature = [self.doc(self.worker, f"literature/LIT-{i}.v1.md", "literature") for i in range(3)]
        self.sota = self.baseline(self.sota_nodes, self.sota_walltime_s)
        self.rld.update_project(sota_experiment_id=self.sota)

    def tearDown(self):
        self.tmp.cleanup()

    # -- helpers ------------------------------------------------------------------

    def git(self, *args: str) -> str:
        return subprocess.run(["git", "-C", str(self.repo), *args], check=True, capture_output=True,
                              text=True).stdout.strip()

    def commit(self, files: dict[str, str] | None = None) -> str:
        self.n += 1
        for path, text in (files or {"method.txt": f"change {self.n}\n"}).items():
            (self.repo / path).parent.mkdir(parents=True, exist_ok=True)
            (self.repo / path).write_text(text, encoding="utf-8")
        self.git("add", "-A")
        self.git("-c", "user.email=t@t", "-c", "user.name=t", "commit", "-q", "-m", f"c{self.n}")
        return self.git("rev-parse", "HEAD")

    def doc(self, actor: ResearchDB, path: str, doc_type: str, current: bool = True,
            about: tuple[str, ...] = (), body: str | None = None) -> str:
        self.n += 1
        file = self.root / "docs" / path
        file.parent.mkdir(parents=True, exist_ok=True)
        if body is None:
            body = f"doc {self.n}\n\n" + "".join(f"## {name}\n\n未知\n\n" for name in rdb.TASK_SECTIONS.get(doc_type, ()))
        file.write_text(body, encoding="utf-8")
        doc_id = actor.register_document(path, doc_type, f"title {self.n}", about=list(about))
        if current:
            actor.set_document_current(doc_id)
        return doc_id

    def decision_doc(self) -> str:
        """A decision document; it also says what is missing and what comes next (needed when it decides on an
        inconclusive result)."""
        self.n += 1
        return self.doc(self.rld, f"decisions/d{self.n}.v1.md", "decision",
                        body="decision\n\n## 缺失证据\n\n不适用\n\n## 下一实验\n\n不适用\n")

    def result_doc(self, actor: ResearchDB | None = None, exp: str | None = None, extra: list | None = None,
                   cite_runs: bool = True) -> str:
        """An experiment result citing its numbers from files, as every experiment result does: one number from a
        file of its own, and (exp) each imported run's primary metric from that run's metrics file."""
        self.n += 1
        source = self.root / "outputs" / "evidence" / f"r{self.n}.json"
        source.parent.mkdir(parents=True, exist_ok=True)
        source.write_text(json.dumps({"acc": 70.25}), encoding="utf-8")
        claims = [{"id": "acc", "value": "70.25", "source": f"outputs/evidence/r{self.n}.json"}]
        runs = [self.rld.get(f"{exp}/s{s}") for s in self.rld.get(exp)["seeds"]] if exp else []
        if runs and all(r and r.get("metric_value") is not None for r in runs):
            spec = next(m for m in self.specs_content["metrics"] if m["name"] == "acc")
            mean = sum(metrics_mod.canonical(spec, r["metric_value"], r["id"]) for r in runs) / len(runs)
            source.write_text(json.dumps({"acc": 70.25, "mean": round(mean, 9)}), encoding="utf-8")
            claims.append({"id": "mean:acc", "value": repr(round(mean, 9)), "source": f"outputs/evidence/r{self.n}.json"})
        for seed in (self.rld.get(exp)["seeds"] if exp and cite_runs else []):
            run = self.rld.get(f"{exp}/s{seed}")
            if run and run.get("evidence_paths"):
                claims.append({"id": f"acc-s{seed}", "value": str(run["metric_value"]),
                               "source": run["evidence_paths"][0]})
        body = f"result {self.n}\n\n```evidence\n{json.dumps(claims + (extra or []))}\n```\n"
        return self.doc(actor or self.worker, f"results/r{self.n}.v1.md", "experiment_result", body=body)

    def report_doc(self, name: str) -> str:
        """A GO / NOT GO report: it cites the numbers it rests on and accounts for every kind of open end."""
        self.n += 1
        source = self.root / "outputs" / "evidence" / f"report{self.n}.json"
        source.parent.mkdir(parents=True, exist_ok=True)
        source.write_text(json.dumps({"delta": 0.3}), encoding="utf-8")
        body = (f"report {self.n}\n\n```evidence\n"
                f'[{{"id": "delta", "value": "0.3", "source": "outputs/evidence/report{self.n}.json"}}]\n```\n'
                + "".join(f"\n## {s}\n\n无\n" for s in rdb.NOT_GO_SECTIONS + ("未经独立确认",)))
        return self.doc(self.rld, f"reports/{name}-{self.n}.v1.md", "report", body=body)

    def values_for(self, exp: str) -> dict:
        """The values every run of exp reports: the SOTA's, or its reference's shifted by the effects (oriented,
        positive = better)."""
        if exp not in self.effects:
            return dict(BASE)
        ref, deltas = self.effects[exp]
        base = self.values_for(ref)
        return {k: base[k] + SIGN[k] * d for k, d in zip(METRICS, deltas)}

    def finish_runs(self, actor: ResearchDB, exp: str, nodes: int = 1, walltime_s: int = 600,
                    metric_value: float | None = None, effect: tuple | None = None) -> None:
        if effect is not None:
            self.effects[exp] = effect
        values = self.values_for(exp)
        if metric_value is not None:
            values["acc"] = metric_value
        for seed in self.rld.get(exp)["seeds"]:
            run = f"{exp}/s{seed}"
            if self.rld.get(run) is None:
                actor.create_run(exp, seed)
            if self.rld.get(run).get("valid"):
                continue
            actor.update_run(run, exec_status="submitted")
            actor.update_run(run, exec_status="succeeded", valid=True, metric_value=values["acc"],
                             secondary={k: values[k] for k in SECONDARY},
                             nodes_used=nodes, walltime_used_s=walltime_s, output_path=f"outputs/{run}",
                             log_path=f"outputs/{run}/train.log")

    def baseline(self, nodes: int, walltime_s: int) -> str:
        self.n += 1
        design = self.doc(self.worker, f"exp/b{self.n}/design.v1.md", "experiment_design")
        exp = self.worker.create_experiment("baseline", "sota", design, self.harness, nodes, walltime_s, config_path=f"configs/{design}.yaml", estimated_node_h=1.0)
        self.finish_runs(self.worker, exp, nodes, walltime_s)
        self.worker.evaluate_experiment(exp, self.result_doc(exp=exp))
        return exp

    def hypothesis(self, parent: str | None = None) -> str:
        self.n += 1
        doc = self.doc(self.rld, f"h/{self.n}/hypothesis.v1.md", "hypothesis")
        return self.rld.create_hypothesis("h", "s", doc, self.literature, parent)

    def branch(self, hyp: str) -> str:
        return self.rld.create_branch(hyp, f"node/{hyp}", "main", self.harness,
                                      str(Path(self.tmp.name) / "wt" / hyp), owner="w1")

    def start(self, hyp: str) -> None:
        self.branch(hyp)
        self.rld.decide(hyp, {"experiment_status": "running", "status": "verifying"}, "start",
                        doc_id=self.decision_doc())

    def method(self, hyp: str, n_seeds: int | None = None, code_ref: str | None = None, walltime_s: int = 1800) -> str:
        """A node experiment with its runs not yet reported (evaluate or finish_runs reports them)."""
        self.n += 1
        design = self.doc(self.worker, f"exp/m{self.n}/design.v1.md", "experiment_design")
        return self.worker.create_experiment("method", "m", design, code_ref or self.commit(), 1, walltime_s,
                                             hypothesis_id=hyp, n_seeds=n_seeds, estimated_node_h=1.0)

    def comparisons(self, exp: str, sota: tuple[float, float, float], parent=None) -> list[dict]:
        """Claimed comparisons for record_verdict: sota (primary, final_loss, peak_mem_gb) deltas; parent:
        (experiment, primary, ...); positive = better."""
        seeds = set(self.rld.get(exp)["seeds"])
        out = []
        for role, target, deltas in (("sota", self.sota, sota), ("parent", parent and parent[0], parent and parent[1:])):
            if target is None:
                continue
            paired = len(seeds & set(self.rld.get(target)["seeds"]))
            out.append({"target_id": target, "role": role, "n_paired": paired, "delta_mean": deltas[0],
                        "delta_sd": 0.0 if paired > 1 else None, "deltas": dict(zip(SECONDARY, deltas[1:]))})
        return out

    def evaluate(self, exp: str, verdict: str, sota=(0.3, 0.1, 0.1), parent=None) -> dict:
        """Report the runs not yet valid with the given effects (against SOTA, or (experiment, ...) against a
        parent's experiment), then evaluate: the interface computes every number."""
        self.finish_runs(self.worker, exp, effect=(parent[0], tuple(parent[1:])) if parent else (self.sota, sota))
        return self.worker.evaluate_experiment(exp, self.result_doc(exp=exp), verdict)

    def concluded(self, verdict: str, sota=(0.3, 0.1, 0.1), parent=None, hyp: str | None = None) -> tuple[str, str]:
        h = hyp or self.hypothesis()
        if hyp is None:
            self.start(h)
        exp = self.method(h)
        self.evaluate(exp, verdict, sota=sota, parent=parent)
        return h, exp

    def candidate(self) -> tuple[str, str]:
        """A node eligible for GO: beats SOTA, rechecked."""
        h, exp = self.concluded("beats_sota")
        self.rld.decide(h, {"experiment_status": "beats_sota"}, "gate", based_on=[exp])
        self.recheck_pass(h, exp)
        self.assertEqual(self.rld.get_eligibility(h)["eligible"], True)
        return h, exp

    def recheck_pass(self, h: str, exp: str) -> None:
        """Both rechecks pass, bound to the experiment they examined."""
        novelty = self.doc(self.rld, f"h/{h}/novelty-{self.n}.v1.md", "novelty", about=(h,))
        theory = self.doc(self.rld, f"h/{h}/theory-{self.n}.v1.md", "theory", about=(h,))
        self.rld.decide(h, {"novelty_recheck": "pass", "theory_recheck": "pass"}, "rechecked",
                        based_on=[novelty, theory, exp])

    def clean_all(self) -> None:
        """Every due cleanup, as its owner; the first call copies the project's cleanup script."""
        if not (Path(self.tmp.name) / rdb.CLEANUP_SCRIPT).exists():
            shutil.copyfile(rdb.CLEANUP_TEMPLATE, Path(self.tmp.name) / rdb.CLEANUP_SCRIPT)
        for due in self.rld.cleanup_due():
            ResearchDB(self.db, f"worker/{due['owner']}").run_cleanup(due["experiment_id"])

    def manifest(self, exp: str, run_seed: int, values: dict | None = None, attempt: int = 1, **extra) -> str:
        """What a runner writes for one attempt: metrics.json, a log and manifest.json (the path returned); extra
        fields override the manifest's."""
        seed = run_seed
        run_dir = self.root / "outputs" / exp / f"s{seed}"
        run_dir.mkdir(parents=True, exist_ok=True)
        (run_dir / "metrics.json").write_text(json.dumps(values or self.values_for(exp)))
        (run_dir / "train.log").write_text("log\n")
        for name in extra.get("evidence_paths", []):
            (run_dir / name).write_text("{}\n")
        manifest = {"experiment_id": exp, "seed": seed, "attempt": attempt, "code_ref": self.rld.get(exp)["code_ref"],
                    "exit_status": 0, "metrics_path": "metrics.json", "counts": {"n_val": 400},
                    "data_version": "toy-v1", "config": {"lr": 0.05}, "env": {"python": "3.13"},
                    "log_path": "train.log", "output_path": ".", "nodes_used": 1, "walltime_used_s": 600,
                    "units": {m["name"]: m["input_unit"] for m in self.specs_content["metrics"]}, **extra}
        (run_dir / "manifest.json").write_text(json.dumps(manifest))
        return f"outputs/{exp}/s{seed}/manifest.json"

    def imported(self, exp: str, effect: tuple | None = None, accept: bool = True, **extra) -> None:
        """Every run of exp reported succeeded, imported through its manifest and (accept) made valid."""
        if effect is not None:
            self.effects[exp] = effect
        for seed in self.rld.get(exp)["seeds"]:
            run = f"{exp}/s{seed}"
            if self.rld.get(run) is None:
                self.worker.create_run(exp, seed)
            self.worker.update_run(run, exec_status="submitted")
            self.worker.update_run(run, exec_status="succeeded")
            self.worker.import_run_result(run, 1, self.manifest(exp, seed, **extra))
            if accept:
                self.worker.update_run(run, valid=True)

    def raw(self, entity_id: str, **props) -> None:
        """Change stored properties directly in LatticeDB, bypassing the interface (tampering, old records)."""
        with Database(self.db) as db, db.write() as txn:
            tx = rdb._Tx(txn)
            nid = tx.node_id(entity_id)
            for key, value in props.items():
                txn.set_property(nid, key, value)
            tx.bump_meta()
            txn.commit()

    def outputs(self, exp: str) -> None:
        """What a run writes: a log and metrics (evidence), final weights, optimizer state and a checkpoint."""
        for seed in self.rld.get(exp)["seeds"]:
            run_dir = self.root / "outputs" / exp / f"s{seed}"
            (run_dir / "ckpt-100").mkdir(parents=True)
            for name, text in {"train.log": "log", "metrics.json": "{}", "model.safetensors": "w" * 100,
                               "optimizer.pt": "o" * 50, "ckpt-100/model.pt": "c" * 10}.items():
                (run_dir / name).write_text(text)


class SpecTest(unittest.TestCase):
    def test_spec_parsing(self):
        spec = rdb.SPEC
        self.assertEqual(spec["hypothesis"].columns["experiment_status"].enum,
                         ("todo", "running", "no_gain", "beats_parent", "beats_sota", "inconclusive"))
        self.assertEqual(spec["experiment"].columns["verdict"].enum[-1], "needs_rld")
        self.assertFalse(spec["experiment"].columns["verdict"].required)
        self.assertEqual(spec["project"].columns["secondary_metrics"].type, "TEXT_LIST")
        self.assertEqual(spec["rel_compared_with"].columns["deltas"].type, "JSON")
        self.assertEqual(spec["project"].columns["screen_budget_node_h"].default, 10.0)
        self.assertNotIn("review", spec)


class ProjectTest(Fixture):
    def test_comparison_setup_and_freeze(self):
        with self.assertRaisesRegex(ResearchDBError, "fixed once experiments exist"):
            self.rld.update_project(go_margin=0.01)
        with self.assertRaisesRegex(ResearchDBError, "not a commit"):
            self.rld.update_project(harness_ref="no-such-ref")
        with self.assertRaisesRegex(ResearchDBError, "relative"):
            self.rld.update_project(harness_paths=["../outside"])
        design = self.doc(self.worker, "exp/x/design.v1.md", "experiment_design")
        unevaluated = self.worker.create_experiment("baseline", "other", design, self.harness, 1, 60, config_path=f"configs/{design}.yaml", estimated_node_h=1.0)
        with self.assertRaisesRegex(ResearchDBError, r"not evaluated yet: .*evaluate_experiment.*not yet valid: "
                                    rf"{unevaluated}/s\d+ \(no run\).*exec_status planned -> submitted"):
            self.rld.update_project(sota_experiment_id=unevaluated)
        v2 = self.commit({"harness/stats.py": "stats v2\n"})
        self.rld.update_project(harness_ref=v2)
        self.assertNotIn("sota_experiment_id", self.rld.get("P-test"))  # new harness: SOTA must be re-run
        with self.assertRaisesRegex(ResearchDBError, "run the baseline again with the frozen harness"):
            self.rld.update_project(sota_experiment_id=self.sota)
        with self.assertRaisesRegex(ResearchDBError, "SOTA baseline before node experiments"):
            self.rld.screen_seed_count()

    def test_new_project_validation(self):
        db = Path(self.tmp.name) / "other" / "research_tree.db"
        (db.parent / "docs").mkdir(parents=True)
        create_db.create_db(db)
        rld = ResearchDB(db, "rld/main")
        (db.parent / "docs" / "s.v1.md").write_text("s", encoding="utf-8")
        setup = rld.register_document("s.v1.md", "min_setup", "s")
        with self.assertRaisesRegex(ResearchDBError, "PROTOCOL_CHANGE_REQUIRED: a new project registers"):
            rld.create_project("P-x", "x", setup, "acc", "higher", True, SECONDARY, SEEDS)
        docs = {}
        for kind, content in zip(("metric_spec", "protocol"), (SPECS, PROTOCOL)):
            (db.parent / "docs" / f"{kind}.v1.json").write_text(json.dumps(content))
            docs[f"{kind}_doc_id"] = rld.register_document(f"{kind}.v1.json", kind, kind)
            rld.set_document_current(docs[f"{kind}_doc_id"])
        with self.assertRaisesRegex(ResearchDBError, "3 distinct"):
            rld.create_project("P-x", "x", setup, "acc", "higher", True, SECONDARY, [1, 1, 2], **docs)
        with self.assertRaisesRegex(ResearchDBError, "must not repeat the primary"):
            rld.create_project("P-x", "x", setup, "acc", "higher", True, ["acc"], SEEDS, **docs)
        with self.assertRaisesRegex(ResearchDBError, "must not look like another record"):
            rld.create_project("T-x", "x", setup, "acc", "higher", True, SECONDARY, SEEDS, **docs)
        # A project named like its directory / uv project.
        self.assertEqual(rld.create_project("my-study", "x", setup, "acc", "higher", True, SECONDARY, SEEDS, **docs), "my-study")
        self.assertEqual(rld.get("my-study")["title"], "x")


class ScreenBudgetTest(unittest.TestCase):
    def test_seed_count_follows_sota_cost(self):
        cases = [((1, 1800), 3), ((8, 1500), 2), ((4, 3600), 2), ((5, 3600), 1), ((8, 3600), 1)]
        for (nodes, walltime), expected in cases:  # 0.5, 3.33.., 4, 5, 8 node-hours per seed
            with self.subTest(nodes=nodes, walltime=walltime):
                fixture = type("F", (Fixture,), {"sota_nodes": nodes, "sota_walltime_s": walltime,
                                                 "runTest": lambda self: None})()
                fixture.setUp()
                try:
                    self.assertEqual(fixture.rld.screen_seed_count(), expected)
                finally:
                    fixture.tearDown()


class HypothesisTest(Fixture):
    def test_create_tree_and_data_version(self):
        before = self.rld.export_snapshot()["meta"]["data_version"]
        h1 = self.hypothesis()
        h2 = self.hypothesis()  # initial hypotheses are siblings below the root
        rec = self.rld.get(h1)
        self.assertEqual((rec["status"], rec["experiment_status"], rec["novelty_recheck"], rec["parent_id"]),
                         ("pending", "todo", "pending", "P-test"))
        self.assertEqual(self.rld.children("P-test"), [h1, h2])
        self.assertEqual(self.rld.find("hypothesis", parent_id="P-test"), [rec, self.rld.get(h2)])
        # per hypothesis: register + set current its document, then create = 3 writes
        self.assertEqual(self.rld.export_snapshot()["meta"]["data_version"], before + 6)

    def test_creation_needs_related_work(self):
        doc = self.doc(self.rld, "h/x/hypothesis.v1.md", "hypothesis")
        with self.assertRaisesRegex(ResearchDBError, "at least 3 related-work"):
            self.rld.create_hypothesis("h", "s", doc, self.literature[:2])
        with self.assertRaisesRegex(ResearchDBError, "at least 3 related-work"):
            self.rld.create_hypothesis("h", "s", doc, [self.literature[0]] * 3)
        draft = self.doc(self.worker, "literature/draft.v1.md", "literature", current=False)
        with self.assertRaisesRegex(ResearchDBError, "current literature"):
            self.rld.create_hypothesis("h", "s", doc, self.literature[:2] + [draft])
        with self.assertRaises(PermissionDenied):
            self.worker.create_hypothesis("h", "s", doc, self.literature)
        h = self.rld.create_hypothesis("h", "s", doc, self.literature)
        self.assertEqual([e["target_id"] for e in self.rld.edges("rel_references", source_id=h)], self.literature)

    def test_start_needs_branch_and_running(self):
        h = self.hypothesis()
        with self.assertRaisesRegex(ResearchDBError, "needs a code branch"):
            self.rld.decide(h, {"experiment_status": "running", "status": "verifying"}, "x", doc_id=self.decision_doc())
        with self.assertRaisesRegex(ResearchDBError, "needs a code branch before experiments"):
            self.method(h)
        self.branch(h)
        with self.assertRaisesRegex(ResearchDBError, "only while verifying"):
            self.rld.decide(h, {"experiment_status": "running"}, "x")
        with self.assertRaisesRegex(ResearchDBError, "experiment_status running"):
            self.rld.decide(h, {"status": "verifying"}, "x", doc_id=self.decision_doc())
        self.rld.decide(h, {"experiment_status": "running", "status": "verifying"}, "go", doc_id=self.decision_doc())

    def test_user_can_decline_an_infeasible_node(self):
        h = self.hypothesis()
        ui = ResearchDB(self.db, "ui/ui")
        report = self.doc(self.rld, f"h/{h}/decisions/infeasible.v1.md", "decision")
        unrelated = self.doc(ui, "instructions/UI-0001.v1.md", "user_instruction")
        with self.assertRaisesRegex(ResearchDBError, "pending -> prunable is not allowed"):
            self.rld.decide(h, {"status": "prunable"}, "needs 32 nodes", doc_id=report, based_on=[unrelated], reconsider_when="new evidence on the mechanism")
        declined = self.doc(ui, "instructions/UI-0002.v1.md", "user_instruction", about=(h,))
        self.rld.decide(h, {"status": "prunable"}, "user declined the extra budget", doc_id=report, based_on=[declined], reconsider_when="new evidence on the mechanism")
        self.assertEqual((self.rld.get(h)["status"], self.rld.get(h)["experiment_status"]), ("prunable", "todo"))


class ExperimentTest(Fixture):
    def test_creation_rules(self):
        h = self.hypothesis()
        self.branch(h)
        design = self.doc(self.worker, "exp/d.v1.md", "experiment_design")
        code = self.commit()
        cases = [
            (dict(kind="method", code_ref=code, nodes=9, walltime_s=60, hypothesis_id=h), "per-run cap"),
            (dict(kind="method", code_ref=code, nodes=1, walltime_s=3601, hypothesis_id=h), "per-run cap"),
            (dict(kind="method", code_ref=code, nodes=1, walltime_s=60, hypothesis_id=h, n_seeds=4), "1..3 seeds"),
            (dict(kind="baseline", code_ref=code, nodes=1, walltime_s=60, hypothesis_id=h), "no hypothesis"),
            (dict(kind="method", code_ref="nope", nodes=1, walltime_s=60, hypothesis_id=h), "not a commit"),
        ]
        for kwargs, message in cases:
            with self.subTest(kwargs=kwargs), self.assertRaisesRegex(ResearchDBError, message):
                self.worker.create_experiment(method_name="m", design_doc_id=design, **kwargs, estimated_node_h=1.0)
        exp = self.worker.create_experiment("method", "m", design, code, 1, 60, hypothesis_id=h, estimated_node_h=1.0)
        self.assertEqual(self.rld.get(exp)["seeds"], SEEDS)  # 0.5 node-hours per seed: 3 seeds fit the budget

    def test_usage_alert_pauses_new_experiments(self):
        h = self.hypothesis()
        self.branch(h)
        design = self.doc(self.worker, "exp/d.v1.md", "experiment_design")
        exp = self.worker.create_experiment("method", "m", design, self.commit(), 1, 60, hypothesis_id=h, n_seeds=1, estimated_node_h=1.0)
        self.rld.update_project(alert_node_h=1.5)  # the SOTA baseline used 3 x 0.5 node-hours
        with self.assertRaisesRegex(ResearchDBError, "reached alert_node_h 1.5"):
            self.worker.create_experiment("method", "m", design, self.commit(), 1, 60, hypothesis_id=h, estimated_node_h=1.0)
        with self.assertRaisesRegex(ResearchDBError, "reached alert_node_h"):
            self.worker.extend_seeds(exp, 2)
        self.worker.create_run(exp, SEEDS[0])  # runs of an experiment already registered go on
        with self.assertRaisesRegex(ResearchDBError, "BUDGET_EXCEEDED: raising alert_node_h is the user's decision"):
            self.rld.update_project(alert_node_h=None)
        user = self.doc(ResearchDB(self.db, "ui/ui"), "instructions/UI-0900.v1.md", "user_instruction")
        self.rld.update_project(alert_node_h=None, user_instruction_doc_id=user)
        self.worker.create_experiment("method", "m", design, self.commit(), 1, 60, hypothesis_id=h, estimated_node_h=1.0)

    def test_runs(self):
        h = self.hypothesis()
        self.branch(h)
        design = self.doc(self.worker, "exp/d.v1.md", "experiment_design")
        exp = self.worker.create_experiment("method", "m", design, self.commit(), 1, 600, hypothesis_id=h, n_seeds=1, estimated_node_h=1.0)
        with self.assertRaisesRegex(ResearchDBError, "not one of"):
            self.worker.create_run(exp, 43)
        run = self.worker.create_run(exp, 42)
        # A planned run: the errors name the field and the next states, so no caller needs the source.
        with self.assertRaisesRegex(ResearchDBError, "does not take status; it takes .*exec_status"):
            self.rld.update_run(run, status="succeeded")
        with self.assertRaisesRegex(ResearchDBError, "planned -> succeeded is not allowed; from planned: submitted, cancelled"):
            self.worker.update_run(run, exec_status="succeeded")
        with self.assertRaisesRegex(ResearchDBError, "succeeded run's results"):
            self.worker.update_run(run, metric_value=1.0, secondary={"final_loss": 1.0, "peak_mem_gb": 2.0})
        with self.assertRaises(PermissionDenied):
            ResearchDB(self.db, "worker/w2").update_run(run, exec_status="submitted")
        self.worker.update_run(run, exec_status="submitted")
        with self.assertRaisesRegex(ResearchDBError, "record secondary"):
            self.worker.update_run(run, exec_status="succeeded", valid=True, metric_value=1.0, nodes_used=1,
                                   walltime_used_s=10)
        with self.assertRaisesRegex(ResearchDBError, "a number for each"):
            self.worker.update_run(run, exec_status="succeeded", valid=True, metric_value=1.0, nodes_used=1,
                                   walltime_used_s=10, secondary={"final_loss": 1.0}, log_path="outputs/a1.log")
        with self.assertRaisesRegex(ResearchDBError, "resubmit only a finished attempt"):
            self.worker.update_run(run, attempt=2, exec_status="submitted")
        ok = dict(metric_value=1.0, nodes_used=1, walltime_used_s=3600, secondary={"final_loss": 1.0, "peak_mem_gb": 2.0})
        with self.assertRaisesRegex(ResearchDBError, "log_path or output_path"):
            self.worker.update_run(run, exec_status="succeeded", valid=True, **ok)
        self.worker.update_run(run, exec_status="succeeded", **ok)
        # A succeeded seed is not rerun to replace its result unless it failed acceptance, with a reason.
        with self.assertRaisesRegex(ResearchDBError, "needs valid=false with invalid_reason"):
            self.worker.update_run(run, attempt=2, exec_status="submitted")
        with self.assertRaisesRegex(ResearchDBError, "valid=false needs invalid_reason"):
            self.worker.update_run(run, valid=False)
        self.worker.update_run(run, valid=False, invalid_reason="loss NaN at step 120 (outputs/a1.log)")
        self.worker.update_run(run, attempt=2, exec_status="submitted")
        resubmitted = self.rld.get(run)
        self.assertEqual(resubmitted["attempts"]["1"]["invalid_reason"], "loss NaN at step 120 (outputs/a1.log)")
        self.assertEqual(resubmitted["attempts"]["1"]["metric_value"], 1.0)
        self.assertNotIn("metric_value", resubmitted)
        self.assertEqual(rdb.node_hours([resubmitted]), 1.0)  # the first attempt's usage still counts
        self.worker.update_run(run, exec_status="succeeded", valid=True, log_path="outputs/a2.log", **ok)
        self.assertEqual(rdb.node_hours([self.rld.get(run)]), 2.0)
        with self.assertRaisesRegex(ResearchDBError, "frozen"):
            self.worker.update_run(run, metric_value=2.0)


class VerdictTest(Fixture):
    def setUp(self):
        super().setUp()
        self.h = self.hypothesis()
        self.start(self.h)

    def test_code_and_harness_checks(self):
        tampered = self.commit({"harness/stats.py": "tweaked\n"})
        exp = self.method(self.h, code_ref=tampered)
        with self.assertRaisesRegex(ResearchDBError, "differ from the frozen harness"):
            self.evaluate(exp, "beats_sota")
        unchanged = self.method(self.h, code_ref=self.harness)
        with self.assertRaisesRegex(ResearchDBError, "needs a code change"):
            self.evaluate(unchanged, "beats_sota")
        design = self.doc(self.worker, "exp/p.v1.md", "experiment_design")
        partial = self.worker.create_experiment("method", "m", design, self.commit({"m.txt": "x"}), 1, 60,
                                                hypothesis_id=self.h, estimated_node_h=1.0)
        self.worker.create_run(partial, SEEDS[0])
        with self.assertRaisesRegex(ResearchDBError, "needs a valid run for every seed"):
            self.worker.evaluate_experiment(partial, self.result_doc(exp=partial), "beats_sota")

    def test_verdict_consistency(self):
        cases = [
            ("no_gain", (0.3, 0.1, 0.1), "exactly when no metric is better"),
            ("beats_parent", (-0.1, -0.1, -0.1), "exactly when no metric is better"),
            ("beats_parent", (0.3, 0.0, 0.0), "the SOTA gate is passed"),
            ("beats_sota", (0.05, 0.0, 0.0), "primary lead over the minimum practical gain"),  # equal is no lead
            ("beats_parent", (0.0, 0.5, 0.0), "positive primary-metric difference"),
        ]
        for verdict, sota, message in cases:
            exp = self.method(self.h)
            with self.subTest(verdict=verdict, sota=sota), self.assertRaisesRegex(ResearchDBError, message):
                self.evaluate(exp, verdict, sota=sota)
            self.assertIsNone(self.rld.get(exp).get("evaluated_at"))
        three = self.method(self.h)
        self.finish_runs(self.worker, three, effect=(self.sota, (0.0501, 0.0, -0.2)))
        with self.assertRaisesRegex(ResearchDBError, "comparisons must be exactly"):
            self.worker.record_verdict(three, self.result_doc(exp=three), None, None, "beats_sota",
                                       self.comparisons(three, (0.0501, 0.0, -0.2), parent=(self.sota, 0, 0, 0)))
        bad = self.comparisons(three, (0.0501, 0.0, -0.2))
        bad[0]["n_paired"] = 2
        with self.assertRaisesRegex(ResearchDBError, "STAT_MISMATCH: .*sota pairs 3 seeds, not 2"):
            self.worker.record_verdict(three, self.result_doc(exp=three), 70.0501, None, "beats_sota", bad)
        result = self.worker.record_verdict(three, self.result_doc(exp=three), 70.0501, 0.0, "beats_sota",
                                            self.comparisons(three, (0.0501, 0.0, -0.2)))
        edge = self.rld.edges("rel_compared_with", source_id=three)[0]
        self.assertEqual((edge["role"], edge["passes_gate"], edge["n_paired"]), ("sota", True, 3))
        self.assertAlmostEqual(edge["delta_mean"], 0.0501, places=9)
        self.assertAlmostEqual(edge["deltas"]["final_loss"], 0.0, places=9)
        self.assertAlmostEqual(edge["deltas"]["peak_mem_gb"], -0.2, places=9)
        self.assertTrue(result["created"])
        with self.assertRaisesRegex(ResearchDBError, "already evaluated with these runs"):
            self.worker.evaluate_experiment(three, self.result_doc(exp=three), "needs_rld")

    def test_fewer_seeds_cannot_beat_sota_and_extension(self):
        one = self.method(self.h, n_seeds=1)
        with self.assertRaisesRegex(ResearchDBError, "primary lead"):
            self.evaluate(one, "beats_sota", sota=(1.0, 0.0, 0.0))
        self.evaluate(one, "beats_parent", sota=(1.0, 0.0, 0.0))
        self.assertIsNone(self.rld.get(one).get("metric_sd"))  # n=1: no SD, not 0
        with self.assertRaisesRegex(ResearchDBError, "extend to at most 3"):
            self.worker.extend_seeds(one, 4)
        self.worker.extend_seeds(one, 3)  # within the screening budget (3 seeds fit)
        record = self.rld.get(one)
        self.assertEqual((record["seeds"], record.get("verdict"), record.get("evaluation_id")), (SEEDS, None, None))
        self.assertEqual(self.rld.edges("rel_compared_with", source_id=one), [])
        self.finish_runs(self.worker, one)
        self.evaluate(one, "beats_sota")
        self.assertEqual(self.rld.latest_result(self.h)["id"], one)
        history = self.rld.evaluations(experiment_id=one)
        self.assertEqual([e["result_revision"] for e in history], [1, 2])  # the 1-seed evaluation is kept
        self.assertEqual(history[1]["supersedes_evaluation_id"], history[0]["id"])


class TightBudgetTest(Fixture):
    sota_nodes, sota_walltime_s = 4, 3600  # 4 node-hours per seed: screening runs 2 seeds

    def test_extension_beyond_budget_needs_close(self):
        h = self.hypothesis()
        self.start(h)
        exp = self.method(h)
        self.assertEqual(self.rld.get(exp)["seeds"], SEEDS[:2])
        self.evaluate(exp, "no_gain", sota=(-0.1, -0.1, 0.0))
        with self.assertRaisesRegex(ResearchDBError, "close or beats_parent"):
            self.worker.extend_seeds(exp, 3)
        close = self.method(h)
        self.evaluate(close, "close", sota=(0.01, 0.0, 0.0))
        self.worker.extend_seeds(close, 3)
        self.finish_runs(self.worker, close)
        self.evaluate(close, "beats_parent")  # 0.01 is below the minimum practical gain of 0.05


class DecisionTest(Fixture):
    def test_status_follows_latest_verdict(self):
        h, exp = self.concluded("no_gain", sota=(-0.1, -0.1, -0.1))
        with self.assertRaisesRegex(ResearchDBError, "needs based_on the latest evaluated experiment"):
            self.rld.decide(h, {"experiment_status": "no_gain", "status": "prunable"}, "x", doc_id=self.decision_doc(), reconsider_when="new evidence on the mechanism")
        with self.assertRaisesRegex(ResearchDBError, "verdict no_gain"):
            self.rld.decide(h, {"experiment_status": "beats_parent"}, "x", based_on=[exp])
        # F03: a node without gain is not forced out; retiring it is a separate, reasoned decision
        self.rld.decide(h, {"experiment_status": "no_gain"}, "no gain", based_on=[exp])
        self.assertEqual(self.rld.get(h)["status"], "verifying")
        self.rld.decide(h, {"status": "prunable"}, "no gain, nothing to repair", doc_id=self.decision_doc(),
                        based_on=[exp], reconsider_when="new evidence on the mechanism")
        self.assertEqual(self.rld.history(h)[-1]["based_on"], [exp])
        self.assertEqual(self.rld.get(h)["disposition"], "retired")

    def test_key_timestamps(self):
        ticks = iter(f"2026-10-04T{h:02d}:{m:02d}:00Z" for h in range(24) for m in range(60))
        saved, rdb.now_utc = rdb.now_utc, lambda: next(ticks)
        try:
            h = self.hypothesis()
            keys = ("started_at", "first_experiment_at", "first_result_at", "beats_sota_at", "concluded_at")
            self.assertEqual([self.rld.get(h).get(k) for k in keys], [None] * 5)
            self.start(h)
            exp = self.method(h)
            self.evaluate(exp, "no_gain", sota=(-0.1, -0.1, -0.1))
            self.rld.decide(h, {"experiment_status": "no_gain", "status": "prunable"}, "no gain",
                            doc_id=self.decision_doc(), based_on=[exp], reconsider_when="new evidence on the mechanism")
            first = self.rld.get(h)
            order = [first["created_at"]] + [first[k] for k in ("started_at", "first_experiment_at",
                                                                "first_result_at", "concluded_at")]
            self.assertEqual(order, sorted(order))
            self.assertEqual(len(set(order)), 5)
            self.assertIsNone(first.get("beats_sota_at"))

            # Re-verifying clears the completion time; first-time stamps are kept. A retired node is reopened
            # explicitly first.
            with self.assertRaisesRegex(ResearchDBError, "is retired: decide_disposition active"):
                self.rld.decide(h, {"status": "verifying", "experiment_status": "running"}, "retry",
                                doc_id=self.decision_doc())
            self.rld.decide_disposition(h, "active", "a fix for the failure mode", [exp])
            self.rld.decide(h, {"status": "verifying", "experiment_status": "running"}, "retry with a fix",
                            doc_id=self.decision_doc())
            self.assertIsNone(self.rld.get(h).get("concluded_at"))
            exp2 = self.method(h)
            self.evaluate(exp2, "beats_sota")
            self.rld.decide(h, {"experiment_status": "beats_sota", "status": "expandable"}, "gate",
                            doc_id=self.decision_doc(), based_on=[exp2])
            final = self.rld.get(h)
            for k in ("started_at", "first_experiment_at", "first_result_at"):
                self.assertEqual(final[k], first[k], k)
            self.assertGreater(final["beats_sota_at"], first["concluded_at"])
            self.assertEqual(final["concluded_at"], final["beats_sota_at"])  # same decision
            with self.assertRaisesRegex(ResearchDBError, "does not take concluded_at"):
                self.rld.update_hypothesis(h, concluded_at="2000-01-01T00:00:00Z")
        finally:
            rdb.now_utc = saved

    def test_user_declined_node_has_completion_but_no_start(self):
        h = self.hypothesis()
        declined = self.doc(ResearchDB(self.db, "ui/ui"), "instructions/UI-0009.v1.md", "user_instruction", about=(h,))
        self.rld.decide(h, {"status": "prunable"}, "declined", doc_id=self.decision_doc(), based_on=[declined], reconsider_when="new evidence on the mechanism")
        record = self.rld.get(h)
        self.assertIsNotNone(record.get("concluded_at"))
        self.assertIsNone(record.get("started_at"))

    def test_needs_rld(self):
        h, exp = self.concluded("beats_parent", sota=(0.02, 0.0, 0.0))
        self.rld.decide(h, {"experiment_status": "beats_parent", "status": "expandable"}, "better",
                        doc_id=self.decision_doc(), based_on=[exp])
        h2, latest = self.concluded("needs_rld", sota=(0.0, 0.0, 0.3))
        with self.assertRaisesRegex(ResearchDBError, "must beat its parent"):
            self.rld.decide(h2, {"status": "expandable"}, "x", doc_id=self.decision_doc())
        with self.assertRaisesRegex(ResearchDBError, "needs a decision document"):
            self.rld.decide(h2, {"experiment_status": "beats_parent"}, "x", based_on=[latest])
        with self.assertRaisesRegex(ResearchDBError, "to pass the SOTA gate"):
            self.rld.decide(h2, {"experiment_status": "beats_sota"}, "x", doc_id=self.decision_doc(), based_on=[latest])
        self.rld.decide(h2, {"experiment_status": "beats_parent", "status": "expandable"}, "memory win is worth it",
                        doc_id=self.decision_doc(), based_on=[latest])

    def test_close_must_be_extended(self):
        h, exp = self.concluded("beats_parent", sota=(0.02, 0.0, 0.0))
        one = self.method(h, n_seeds=1)
        self.evaluate(one, "close", sota=(0.01, 0.0, 0.0))
        with self.assertRaisesRegex(ResearchDBError, "extend its seeds first"):
            self.rld.decide(h, {"experiment_status": "beats_parent"}, "x", based_on=[one])

    def test_children_only_below_expandable_nodes(self):
        pending = self.hypothesis()
        with self.assertRaisesRegex(ResearchDBError, "is pending: new nodes go below the root"):
            self.hypothesis(parent=pending)
        h, exp = self.concluded("beats_parent", sota=(0.02, 0.0, 0.0))
        with self.assertRaisesRegex(ResearchDBError, "is verifying"):
            self.hypothesis(parent=h)
        self.rld.decide(h, {"experiment_status": "beats_parent", "status": "expandable"}, "keep",
                        doc_id=self.decision_doc(), based_on=[exp])
        child = self.hypothesis(parent=h)
        self.assertEqual(self.rld.children(h), [child])
        self.assertEqual(self.rld.get(self.hypothesis(parent="P-test"))["parent_id"], "P-test")  # the root by name

    def test_child_compares_with_parent_result(self):  # E06
        parent, parent_exp = self.concluded("beats_parent", sota=(0.02, 0.0, 0.0))
        self.rld.decide(parent, {"experiment_status": "beats_parent", "status": "expandable"}, "keep",
                        doc_id=self.decision_doc(), based_on=[parent_exp])
        child = self.hypothesis(parent=parent)
        self.start(child)
        exp = self.method(child)
        self.assertEqual((self.rld.get(exp)["parent_experiment_id"], self.rld.get(exp)["baseline_experiment_id"]),
                         (parent_exp, self.sota))
        # The parent's later experiment does not move the child's reference.
        later = self.method(parent)
        self.evaluate(later, "beats_parent", sota=(0.04, 0.0, 0.0))
        # better than SOTA on the primary metric, but no metric better than the parent: no gain
        with self.assertRaisesRegex(ResearchDBError, "exactly when no metric is better"):
            self.evaluate(exp, "beats_parent", parent=(parent_exp, -0.01, 0.0, -0.1))
        self.evaluate(exp, "no_gain", parent=(parent_exp, -0.01, 0.0, -0.1))
        edges = {e["role"]: e for e in self.rld.edges("rel_compared_with", source_id=exp)}
        self.assertEqual({r: e["target_id"] for r, e in edges.items()}, {"sota": self.sota, "parent": parent_exp})
        self.assertAlmostEqual(edges["parent"]["delta_mean"], -0.01, places=9)
        self.assertAlmostEqual(edges["sota"]["delta_mean"], 0.01, places=9)

    def test_recheck_and_go(self):
        h, exp = self.concluded("beats_sota")
        other = self.hypothesis()
        novelty = self.doc(self.rld, f"h/{h}/novelty.v1.md", "novelty", about=(h,))
        with self.assertRaisesRegex(ResearchDBError, "only after the node beats SOTA"):
            self.rld.decide(h, {"novelty_recheck": "pass"}, "x", based_on=[novelty])
        self.rld.decide(h, {"experiment_status": "beats_sota"}, "gate", based_on=[exp])
        unrelated = self.doc(self.rld, "notes/theory.v1.md", "theory")
        with self.assertRaisesRegex(ResearchDBError, "theory document about"):
            self.rld.decide(h, {"theory_recheck": "pass"}, "x", based_on=[unrelated])
        with self.assertRaisesRegex(ResearchDBError, "GO needs .*RECHECK_PENDING"):
            self.rld.decide("P-test", {"status": "go"}, "x", doc_id=self.decision_doc())
        theory = self.doc(self.rld, f"h/{h}/theory.v1.md", "theory", about=(h,))
        with self.assertRaisesRegex(ResearchDBError, "needs based_on the experiment it rechecks"):
            self.rld.decide(h, {"novelty_recheck": "pass", "theory_recheck": "pass"}, "rechecked",
                            based_on=[novelty, theory])
        self.rld.decide(h, {"novelty_recheck": "pass", "theory_recheck": "pass"}, "rechecked",
                        based_on=[novelty, theory, exp])
        self.assertEqual(self.rld.go_candidates(), [h])
        self.assertTrue(self.rld.get_eligibility(h)["eligible"])
        self.rld.decide("P-test", {"status": "go"}, "GO", doc_id=self.report_doc("go"))
        self.assertEqual((self.rld.get("P-test")["status"], self.rld.get(other)["status"]), ("go", "pending"))

    def test_recheck_failure_prunes(self):
        h, exp = self.concluded("beats_sota")
        self.rld.decide(h, {"experiment_status": "beats_sota"}, "gate", based_on=[exp])
        prior = self.doc(self.rld, f"h/{h}/novelty.v1.md", "novelty", about=(h,))
        with self.assertRaisesRegex(ResearchDBError, "retiring a node .* needs based_on its evidence"):
            self.rld.decide(h, {"status": "prunable"}, "x", doc_id=self.decision_doc(), reconsider_when="new evidence on the mechanism")
        self.rld.decide(h, {"novelty_recheck": "fail", "status": "prunable"}, "direct prior",
                        doc_id=self.decision_doc(), based_on=[prior], reconsider_when="new evidence on the mechanism")
        self.assertEqual(self.rld.go_candidates(), [])

    def test_not_go(self):  # 06 §3.3: no active node, a report that accounts for the open ends
        h, exp = self.concluded("no_gain", sota=(-0.1, -0.1, -0.1))
        self.rld.decide(h, {"experiment_status": "no_gain", "status": "prunable"}, "no gain",
                        doc_id=self.decision_doc(), based_on=[exp], reconsider_when="new evidence on the mechanism")
        h2 = self.hypothesis()
        with self.assertRaisesRegex(ResearchDBError, f"still active: \\['{h2}'\\]"):
            self.rld.decide("P-test", {"status": "not_go"}, "x", doc_id=self.report_doc("not-go"))
        # a node never tested is set aside only by the user; paused needs its reopening condition
        with self.assertRaisesRegex(ResearchDBError, "needs reconsider_when"):
            self.rld.decide_disposition(h2, "paused", "budget", [self.decision_doc()])
        with self.assertRaisesRegex(ResearchDBError, "given up only by the user"):
            self.rld.decide_disposition(h2, "retired", "low value", [self.decision_doc()], reconsider_when="new data")
        self.rld.decide_disposition(h2, "paused", "the budget is spent", [self.decision_doc()],
                                    reconsider_when="the user extends the budget")
        bare = self.root / "docs" / "reports" / "bare.v1.md"
        bare.parent.mkdir(parents=True, exist_ok=True)
        (self.root / "outputs" / "evidence").mkdir(parents=True, exist_ok=True)
        (self.root / "outputs" / "evidence" / "b.json").write_text('{"d": 0.1}')
        bare.write_text('```evidence\n[{"id": "d", "value": "0.1", "source": "outputs/evidence/b.json"}]\n```\n')
        doc = self.rld.register_document("reports/bare.v1.md", "report", "bare")
        self.rld.set_document_current(doc)
        with self.assertRaisesRegex(ResearchDBError, "a NOT GO report: .*missing 未探索"):
            self.rld.decide("P-test", {"status": "not_go"}, "NOT GO", doc_id=doc)
        # the cleanup does not hold the decision back; it stays due
        self.rld.decide("P-test", {"status": "not_go"}, "NOT GO", doc_id=self.report_doc("not-go"))
        self.assertTrue(self.rld.cleanup_due())
        with self.assertRaisesRegex(ResearchDBError, "user_instruction"):
            self.rld.decide("P-test", {"status": "active"}, "resume", doc_id=self.decision_doc())

    def test_a_closed_project_starts_no_new_work(self):
        h = self.hypothesis()
        stop = self.doc(self.rld, "instructions/stop.v1.md", "user_instruction")
        self.rld.decide("P-test", {"status": "stopped"}, "user stop", doc_id=self.decision_doc(), based_on=[stop])
        design = self.doc(self.worker, "exp/stopped.v1.md", "experiment_design")
        req = self.doc(self.rld, "tasks/stopped/request.v1.md", "task_request")
        for start in (lambda: self.rld.create_hypothesis("h", "s", self.rld.get(h)["doc_id"], self.literature),
                      lambda: self.worker.create_experiment("baseline", "b", design, self.harness, 1, 60, config_path=f"configs/{design}.yaml", estimated_node_h=1.0),
                      lambda: self.worker.create_run(self.sota, SEEDS[0]),
                      lambda: self.rld.create_task("experiment", "worker", req, target_id=h)):
            with self.assertRaisesRegex(ResearchDBError, "is stopped: no new research work"):
                start()
        self.rld.create_task("web_build", "web_builder", req)  # the page is still kept up to date
        resume = self.doc(self.rld, "instructions/resume.v1.md", "user_instruction")
        self.rld.decide("P-test", {"status": "active"}, "user resumes", doc_id=self.decision_doc(), based_on=[resume])
        self.rld.create_task("experiment", "worker", req, target_id=h)


class KnownDefectTest(Fixture):
    """F01 and F02 (plans/design/00 §2.3), pinned as expected failures in M0 and fixed in M1: the numbers are
    recomputed from the runs, and GO eligibility is bound to current evidence."""

    def test_f01_summary_must_match_the_runs(self):  # M01
        design = self.doc(self.worker, "exp/f01/design.v1.md", "experiment_design")
        exp = self.worker.create_experiment("baseline", "sota", design, self.harness, 1, 60, config_path=f"configs/{design}.yaml", estimated_node_h=1.0)
        self.finish_runs(self.worker, exp)  # every run 70.0
        with self.assertRaisesRegex(ResearchDBError, "STAT_MISMATCH"):
            self.worker.record_verdict(exp, self.result_doc(exp=exp), 70.3, 0.0)  # the SD (0) is true
        self.assertIsNone(self.rld.get(exp).get("evaluated_at"))

    def test_f01_comparison_must_match_the_runs(self):  # M02
        h = self.hypothesis()
        self.start(h)
        exp = self.method(h)
        self.finish_runs(self.worker, exp)  # every run 70.0, like the SOTA baseline's
        claimed = self.comparisons(exp, (0.3, 0.0, 0.0))
        claimed[0]["delta_sd"] = 0.0  # true, like the secondary deltas: only delta_mean is false
        with self.assertRaisesRegex(ResearchDBError, "STAT_MISMATCH"):
            self.worker.record_verdict(exp, self.result_doc(exp=exp), 70.0, 0.0, "beats_sota", claimed)
        self.assertIsNone(self.rld.get(exp).get("evaluated_at"))
        self.assertEqual(self.rld.edges("rel_compared_with", source_id=exp), [])

    def go_candidate(self, new_harness: bool = True) -> str:
        """A node that beats SOTA with numbers consistent with its runs (70.3 against 70.0 on every seed),
        rechecked, then (new_harness) a new harness."""
        h = self.hypothesis()
        self.start(h)
        self.n += 1
        design = self.doc(self.worker, f"exp/m{self.n}/design.v1.md", "experiment_design")
        exp = self.worker.create_experiment("method", "m", design, self.commit(), 1, 1800, hypothesis_id=h, estimated_node_h=1.0)
        self.finish_runs(self.worker, exp, metric_value=70.3)
        claimed = self.comparisons(exp, (0.3, 0.0, 0.0))
        claimed[0]["delta_sd"] = 0.0
        self.worker.record_verdict(exp, self.result_doc(exp=exp), 70.3, 0.0, "beats_sota", claimed)
        self.rld.decide(h, {"experiment_status": "beats_sota"}, "gate", based_on=[exp])
        self.recheck_pass(h, exp)
        if new_harness:
            self.rld.update_project(harness_ref=self.commit({"harness/stats.py": "stats v2\n"}))
        return h

    def test_a_consistent_candidate_is_listed(self):  # the F02 tests' precondition, outside expectedFailure
        h = self.go_candidate(new_harness=False)
        self.assertEqual(self.rld.go_candidates(), [h])

    def test_f02_a_new_harness_ends_go_candidacy(self):  # F02 (E01 in part)
        self.go_candidate()
        self.assertEqual(self.rld.go_candidates(), [])

    def test_f02_a_new_harness_refuses_go(self):  # F02 (E01 in part)
        self.go_candidate()
        with self.assertRaisesRegex(ResearchDBError, "EVIDENCE_STALE"):
            self.rld.decide("P-test", {"status": "go"}, "GO", doc_id=self.report_doc("go"))
        self.assertEqual(self.rld.get("P-test")["status"], "active")


class NumbersTest(Fixture):
    """plans/design 11 §1.2: the statistics come from the runs (M01–M12)."""

    def setUp(self):
        super().setUp()
        self.h = self.hypothesis()
        self.start(self.h)

    def test_m02_authoritative_delta_from_identical_runs(self):
        exp = self.method(self.h)
        self.finish_runs(self.worker, exp)  # identical to SOTA
        result = self.worker.evaluate_experiment(exp, self.result_doc(exp=exp), "no_gain")
        self.assertEqual(result["comparisons"]["sota"]["delta_mean"], 0.0)
        self.assertEqual(result["verification_level"], "record_recomputed")

    def test_m03_lower_is_better_is_oriented_by_the_spec(self):
        exp = self.method(self.h)
        self.finish_runs(self.worker, exp, effect=(self.sota, (0.3, 0.1, 0.0)))  # final_loss 0.9 < 1.0: better
        claimed = self.comparisons(exp, (0.3, -0.1, 0.0))  # the opposite orientation
        with self.assertRaisesRegex(ResearchDBError, r"STAT_MISMATCH: .*deltas.final_loss -0.1"):
            self.worker.record_verdict(exp, self.result_doc(exp=exp), None, None, "beats_sota", claimed)
        result = self.worker.record_verdict(exp, self.result_doc(exp=exp), None, None, "beats_sota",
                                            self.comparisons(exp, (0.3, 0.1, 0.0)))
        self.assertAlmostEqual(result["comparisons"]["sota"]["deltas"]["final_loss"], 0.1, places=9)

    def test_m06_one_seed_has_no_sd(self):
        one = self.method(self.h, n_seeds=1)
        result = self.evaluate(one, "beats_parent", sota=(0.2, 0.0, 0.0))
        self.assertIsNone(result["comparisons"]["sota"]["delta_sd"])
        ev = self.rld.evaluations(experiment_id=one)[0]
        self.assertEqual(ev["metrics"]["acc"]["sd_missing"], "n=1: no standard deviation")
        self.assertIn("n=1: no standard deviation", ev["limitations"])
        claimed_sd = self.method(self.h, n_seeds=1)
        self.finish_runs(self.worker, claimed_sd, effect=(self.sota, (0.2, 0.0, 0.0)))
        with self.assertRaisesRegex(ResearchDBError, "STAT_MISMATCH: .*metric_sd 0.0"):
            self.worker.record_verdict(claimed_sd, self.result_doc(exp=claimed_sd), None, 0.0, "beats_parent")

    def test_m07_nonfinite_and_out_of_range_values(self):
        exp = self.method(self.h, n_seeds=1)
        run = f"{exp}/s42"
        self.worker.create_run(exp, 42)
        self.worker.update_run(run, exec_status="submitted")
        common = dict(exec_status="succeeded", valid=True, secondary={"final_loss": 1.0, "peak_mem_gb": 40.0},
                      nodes_used=1, walltime_used_s=60, log_path="outputs/x.log")
        for value, code in ((float("nan"), "NONFINITE_METRIC"), (float("inf"), "NONFINITE_METRIC"),
                            (170.0, "METRIC_UNIT_MISMATCH")):
            with self.subTest(value=value), self.assertRaisesRegex(ResearchDBError, code):
                self.worker.update_run(run, metric_value=value, **common)
        self.assertIsNone(self.rld.get(run).get("valid"))

    def test_m08_m12_pairing_and_protocol_fields(self):
        protocol = self.doc(self.rld, "project/protocol.v2.json", "protocol", body=json.dumps(
            {"version": 1, "eval_type": "real_gt", "pair_fields": ["seed", "data_version"], "profile": "screening",
             "match": {"epochs": 30}, "required_counts": {"n_val": 400}}))
        design = self.doc(self.worker, "exp/pb.v1.md", "experiment_design")
        instruction = self.doc(ResearchDB(self.db, "ui/ui"), "instructions/UI-0100.v1.md", "user_instruction")
        with self.assertRaisesRegex(ResearchDBError, "PROTOCOL_CHANGE_REQUIRED"):
            self.rld.update_project(protocol_doc_id=protocol)
        self.rld.update_project(protocol_doc_id=protocol, user_instruction_doc_id=instruction)
        base = self.worker.create_experiment("baseline", "sota", design, self.harness, 1, 1800, config_path=f"configs/{design}.yaml", estimated_node_h=1.0)
        self.imported(base, epochs=30)
        self.worker.evaluate_experiment(base, self.result_doc(exp=base))
        self.rld.update_project(sota_experiment_id=base)
        # M12: a run trained with other settings does not join the comparison
        exp = self.method(self.h, n_seeds=1)
        self.worker.create_run(exp, 42)
        self.worker.update_run(f"{exp}/s42", exec_status="submitted")
        self.worker.update_run(f"{exp}/s42", exec_status="succeeded")
        with self.assertRaisesRegex(ResearchDBError, "PAIRING_MISMATCH: .*epochs is 10"):
            self.worker.import_run_result(f"{exp}/s42", 1, self.manifest(exp, 42, epochs=10))
        with self.assertRaisesRegex(ResearchDBError, "PAIRING_MISMATCH: .*counts.n_val is 100"):
            self.worker.import_run_result(f"{exp}/s42", 1, self.manifest(exp, 42, epochs=30, counts={"n_val": 100}))
        # M08: the same seed on another data split is not a pair
        self.worker.import_run_result(f"{exp}/s42", 1, self.manifest(exp, 42, epochs=30, data_version="toy-v2"))
        self.worker.update_run(f"{exp}/s42", valid=True)
        with self.assertRaisesRegex(ResearchDBError, r"PAIRING_MISMATCH: .*share seeds \[42\]"):
            self.worker.evaluate_experiment(exp, self.result_doc(exp=exp), "beats_parent")

    def test_m10_m11_imports_and_evaluations_are_idempotent(self):
        exp = self.method(self.h, n_seeds=1)
        self.effects[exp] = (self.sota, (0.3, 0.1, 0.1))
        run = f"{exp}/s42"
        self.worker.create_run(exp, 42)
        self.worker.update_run(run, exec_status="submitted")
        with self.assertRaisesRegex(ResearchDBError, "report exec_status succeeded"):
            self.worker.import_run_result(run, 1, self.manifest(exp, 42))
        self.worker.update_run(run, exec_status="succeeded")
        first = self.worker.import_run_result(run, 1, self.manifest(exp, 42))
        self.assertTrue(first["imported"])
        self.assertFalse(self.worker.import_run_result(run, 1, self.manifest(exp, 42))["imported"])  # M10
        with self.assertRaisesRegex(ResearchDBError, "EVIDENCE_CHANGED"):
            self.worker.import_run_result(run, 1, self.manifest(exp, 42, values={**self.values_for(exp), "acc": 71}))
        self.manifest(exp, 42)  # the original files again
        with self.assertRaisesRegex(ResearchDBError, "STAT_MISMATCH: .*was imported"):
            self.worker.update_run(run, metric_value=99.0)
        self.worker.update_run(run, valid=True)
        record = self.rld.get(run)
        self.assertEqual((record["metric_value"], record["manifest_path"]), (70.3, f"outputs/{exp}/s42/manifest.json"))
        self.assertIn(f"outputs/{exp}/s42/metrics.json", record["evidence_paths"])
        with self.assertRaisesRegex(ResearchDBError, "STAT_MISMATCH: .*metrics.json is not cited"):
            self.worker.evaluate_experiment(exp, self.result_doc(exp=exp, cite_runs=False), "beats_parent")
        with self.assertRaisesRegex(ResearchDBError, "STAT_MISMATCH: .*states no mean:acc"):
            self.worker.evaluate_experiment(exp, self.result_doc(), "beats_parent")
        stats = self.root / "outputs" / exp / "stats.json"  # the worker's own statistics output, mistaken
        stats.write_text(json.dumps({"mean": 70.4}))
        with self.assertRaisesRegex(ResearchDBError, r"STAT_MISMATCH: .*mean:acc '70.4' \(recomputed 70.3"):
            self.worker.evaluate_experiment(exp, self.result_doc(exp=exp, extra=[
                {"id": "mean:acc", "value": "70.4", "source": f"outputs/{exp}/stats.json"}]), "beats_parent")
        doc = self.result_doc(exp=exp, extra=[{"id": "mean:acc", "value": "70.3",
                                               "source": f"outputs/{exp}/s42/metrics.json"}])
        a = self.worker.evaluate_experiment(exp, doc, "beats_parent")
        b = self.worker.evaluate_experiment(exp, doc, "beats_parent")  # M11
        self.assertEqual((a["evaluation_id"], a["created"], b["evaluation_id"], b["created"]),
                         (a["evaluation_id"], True, a["evaluation_id"], False))
        self.assertEqual(len(self.rld.evaluations(experiment_id=exp)), 1)
        # the SOTA baseline's runs were not imported: record level only
        self.assertEqual(a["verification_level"], "record_recomputed")

    def test_import_checks_identity(self):
        exp = self.method(self.h, n_seeds=1)
        run = f"{exp}/s42"
        self.worker.create_run(exp, 42)
        self.worker.update_run(run, exec_status="submitted")
        self.worker.update_run(run, exec_status="succeeded")
        for extra, message in (({"seed": 43}, "seed is 43"), ({"exit_status": 1}, "exit_status is 1"),
                               ({"code_ref": self.harness}, "is not the experiment's code"),
                               ({"counts": {}}, "counts must give"), ({"metrics_path": "../../../../x.json"},
                                                                     "outside the project directory|does not exist")):
            with self.subTest(extra=extra), self.assertRaisesRegex(ResearchDBError, message):
                self.worker.import_run_result(run, 1, self.manifest(exp, 42, **extra))
        with self.assertRaisesRegex(ResearchDBError, "outside the project directory"):
            self.worker.import_run_result(run, 1, "/etc/hostname")
        with self.assertRaises(PermissionDenied):
            ResearchDB(self.db, "worker/w2").import_run_result(run, 1, self.manifest(exp, 42))


class UnitsTest(Fixture):
    """M04, M05: inputs as fractions, compared in percentage points; a run reporting percent is refused."""

    specs_content = {"version": 1, "primary": "acc", "metrics": [
        {**SPECS["metrics"][0], "input_unit": "fraction", "valid_range": [0.0, 1.0], "minimum_practical_gain": 0.1},
        *SPECS["metrics"][1:]]}

    def setUp(self):  # a project whose primary metric is reported as a fraction; no SOTA yet
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name) / "research" / "P-test"
        (self.root / "docs").mkdir(parents=True)
        self.db = self.root / "research_tree.db"
        create_db.create_db(self.db)
        self.rld, self.worker, self.n, self.effects = ResearchDB(self.db, "rld/main"), ResearchDB(self.db, "worker/w1"), 0, {}
        self.repo = Path(self.tmp.name) / "code"
        (self.repo / "harness").mkdir(parents=True)
        self.git("init", "-q", "-b", "main")
        self.harness = self.commit({"harness/stats.py": "stats v1\n"})
        setup = self.doc(self.rld, "project/min-setup.v1.md", "min_setup")
        specs = self.doc(self.rld, "project/metric-spec.v1.json", "metric_spec", body=json.dumps(self.specs_content))
        protocol = self.doc(self.rld, "project/protocol.v1.json", "protocol", body=json.dumps(PROTOCOL))
        with self.assertRaisesRegex(ResearchDBError, "missing protocol_doc_id"):
            self.rld.create_project("P-test", "test", setup, "acc", "higher", False, SECONDARY, SEEDS,
                                    repo_path=str(self.repo), metric_spec_doc_id=specs, go_margin=0.1)
        with self.assertRaisesRegex(ResearchDBError, "must equal the project's go_margin 0.05"):
            self.rld.create_project("P-test", "test", setup, "acc", "higher", False, SECONDARY, SEEDS,
                                    repo_path=str(self.repo), metric_spec_doc_id=specs, protocol_doc_id=protocol)
        self.rld.create_project("P-test", "test", setup, "acc", "higher", False, SECONDARY, SEEDS,
                                repo_path=str(self.repo), metric_spec_doc_id=specs, protocol_doc_id=protocol,
                                go_margin=0.1)
        self.rld.update_project(harness_ref=self.harness, harness_paths=["harness"])
        self.literature = [self.doc(self.worker, f"literature/LIT-{i}.v1.md", "literature") for i in range(3)]

    def test_m04_m05(self):
        design = self.doc(self.worker, "exp/b.v1.md", "experiment_design")
        base = self.worker.create_experiment("baseline", "sota", design, self.harness, 1, 600, config_path=f"configs/{design}.yaml", estimated_node_h=1.0)
        self.finish_runs(self.worker, base, metric_value=0.699)
        self.worker.evaluate_experiment(base, self.result_doc(exp=base))
        self.rld.update_project(sota_experiment_id=base)
        self.assertAlmostEqual(self.rld.get(base)["metric_mean"], 69.9, places=9)  # canonical: percent
        h = self.hypothesis()
        self.start(h)
        exp = self.method(h)
        self.finish_runs(self.worker, exp, metric_value=0.701)
        result = self.worker.evaluate_experiment(exp, self.result_doc(exp=exp), "beats_sota")
        self.assertAlmostEqual(result["comparisons"]["sota"]["delta_mean"], 0.2, places=9)  # M04: 0.2 points
        mixed = self.method(h, n_seeds=1)
        with self.assertRaisesRegex(ResearchDBError, "METRIC_UNIT_MISMATCH: .*70.1 is outside its valid range"):
            self.finish_runs(self.worker, mixed, metric_value=70.1)  # M05: a percentage among fractions
        unranged = json.loads(json.dumps(self.specs_content))
        del unranged["metrics"][0]["valid_range"]
        with self.assertRaisesRegex(MetricErrorAlias, "outside its valid range"):  # implied for fractions
            metrics_mod.canonical(unranged["metrics"][0], 70.1, "r")


class RelativeTest(Fixture):
    """M09: a relative effect against a reference mean near zero is undefined, not a dropped seed."""

    specs_content = {"version": 1, "primary": "acc", "metrics": [
        {**SPECS["metrics"][0], "effect_mode": "relative_to_reference_mean", "relative_min_denominator": 1.0,
         "valid_range": [-100, 100]}, *SPECS["metrics"][1:]]}

    def test_m09(self):
        design = self.doc(self.worker, "exp/z.v1.md", "experiment_design")
        zero = self.worker.create_experiment("baseline", "zero", design, self.harness, 1, 600, config_path=f"configs/{design}.yaml", estimated_node_h=1.0)
        self.finish_runs(self.worker, zero, metric_value=0.5)
        self.worker.evaluate_experiment(zero, self.result_doc(exp=zero))
        self.rld.update_project(sota_experiment_id=zero)
        h = self.hypothesis()
        self.start(h)
        exp = self.method(h)
        self.finish_runs(self.worker, exp, metric_value=0.4)
        with self.assertRaisesRegex(ResearchDBError, "RELATIVE_EFFECT_UNDEFINED: .*below relative_min_denominator"):
            self.worker.evaluate_experiment(exp, self.result_doc(exp=exp), "no_gain")
        self.assertEqual(len(self.rld.get(exp)["seeds"]), 3)  # nothing dropped; no result recorded
        self.assertIsNone(self.rld.get(exp).get("evaluated_at"))


class EligibilityTest(Fixture):
    """plans/design 11 §1.3 (E01–E10): GO eligibility follows current evidence."""

    def go(self) -> None:
        self.rld.decide("P-test", {"status": "go"}, "GO", doc_id=self.report_doc("go"))

    def test_e01_new_harness_history_kept(self):
        h, exp = self.candidate()
        self.go()
        self.rld.update_project(harness_ref=self.commit({"harness/stats.py": "stats v2\n"}))
        result = self.rld.get_eligibility(h)
        self.assertEqual((result["eligible"], result["evidence_state"]), (False, "stale"))
        self.assertIn("HARNESS_CHANGED", result["reasons"])
        self.assertEqual(self.rld.get("P-test")["status"], "go")  # the historical GO stays a fact
        self.assertEqual(self.rld.history("P-test")[-1]["to_value"], "go")

    def test_e02_new_baseline_then_rescoring(self):
        h, exp = self.candidate()
        old = self.rld.get_eligibility(h)["basis_evaluation_id"]
        tuned = self.baseline(1, 1800)
        self.rld.update_project(sota_experiment_id=tuned)
        self.assertIn("BASELINE_CHANGED", self.rld.get_eligibility(h)["reasons"])
        with self.assertRaisesRegex(ResearchDBError, "rescoring is against the current SOTA"):
            self.worker.evaluate_experiment(exp, self.result_doc(exp=exp), "beats_sota", baseline_experiment_id=self.sota)
        self.worker.evaluate_experiment(exp, self.result_doc(exp=exp), "beats_sota", baseline_experiment_id=tuned)
        result = self.rld.get_eligibility(h)
        self.assertTrue(result["eligible"], result)
        self.assertNotEqual(result["basis_evaluation_id"], old)
        self.assertEqual([e["baseline_experiment_id"] for e in self.rld.evaluations(experiment_id=exp)],
                         [self.sota, tuned])  # the earlier comparison is kept

    def test_e03_code_change_needs_new_rechecks(self):
        h, exp = self.candidate()
        newer = self.method(h)
        self.evaluate(newer, "beats_sota", sota=(0.4, 0.1, 0.1))
        self.assertEqual(self.rld.get_eligibility(h)["reasons"], ["RECHECK_STALE"])
        # a recheck of the new code is a new review: fail, then pass bound to the new experiment
        novelty = self.doc(self.rld, f"h/{h}/novelty-b.v1.md", "novelty", about=(h,))
        theory = self.doc(self.rld, f"h/{h}/theory-b.v1.md", "theory", about=(h,))
        with self.assertRaisesRegex(ResearchDBError, "already 'pass'"):  # not without the new experiment
            self.rld.decide(h, {"novelty_recheck": "pass"}, "again", based_on=[novelty, exp])
        self.rld.decide(h, {"novelty_recheck": "pass", "theory_recheck": "pass"}, "rechecked the new code",
                        based_on=[novelty, theory, newer])
        self.assertTrue(self.rld.get_eligibility(h)["eligible"])

    def test_e03_more_seeds_keep_the_rechecks(self):
        h = self.hypothesis()
        self.start(h)
        exp = self.method(h, n_seeds=1)
        self.evaluate(exp, "beats_parent", sota=(0.3, 0.1, 0.1))
        self.worker.extend_seeds(exp, 3)
        self.assertIn("RESULT_REVISION_PENDING", self.rld.get_eligibility(h)["reasons"])
        self.finish_runs(self.worker, exp)
        self.evaluate(exp, "beats_sota")
        self.rld.decide(h, {"experiment_status": "beats_sota"}, "gate", based_on=[exp])
        self.recheck_pass(h, exp)
        self.assertTrue(self.rld.get_eligibility(h)["eligible"])

    def test_e04_retracted_run(self):
        h, exp = self.candidate()
        with self.assertRaises(PermissionDenied):
            self.worker.retract_run(f"{exp}/s43", "wrong evaluator", self.decision_doc())
        self.rld.retract_run(f"{exp}/s43", "the evaluator read the training split", self.decision_doc())
        result = self.rld.get_eligibility(h)
        self.assertEqual((result["eligible"], result["evidence_state"]), (False, "stale"))
        self.assertIn("RUN_RETRACTED", result["reasons"])
        run = self.rld.get(f"{exp}/s43")
        self.assertEqual((run["valid"], run["metric_value"]), (False, 70.3))  # kept, no longer valid
        self.assertEqual(self.rld.go_candidates(), [])
        # resubmitted as a new attempt and evaluated again: current once more
        self.worker.update_run(f"{exp}/s43", attempt=2, exec_status="planned")
        self.finish_runs(self.worker, exp)
        self.worker.evaluate_experiment(exp, self.result_doc(exp=exp), "beats_sota")
        self.assertTrue(self.rld.get_eligibility(h)["eligible"])

    def test_e05_unrelated_changes_keep_eligibility(self):
        h, exp = self.candidate()
        before = self.rld.get_eligibility(h)
        self.rld.update_hypothesis(h, title="renamed")
        self.doc(self.rld, "workflow/page-style.v1.md", "workflow")
        self.assertEqual(self.rld.get_eligibility(h), before)

    def test_e07_e08_changes_while_computing(self):
        h = self.hypothesis()
        self.start(h)
        other = self.hypothesis()
        exp = self.method(h)
        self.finish_runs(self.worker, exp, effect=(self.sota, (0.3, 0.1, 0.1)))
        worker = ResearchDB(self.db, "worker/w1")
        worker._after_compute = lambda: self.rld.update_hypothesis(other, title="unrelated")  # E08
        worker.evaluate_experiment(exp, self.result_doc(exp=exp), "beats_sota")
        exp2 = self.method(h)
        self.finish_runs(self.worker, exp2, effect=(self.sota, (0.3, 0.1, 0.1)))
        protocol = self.doc(self.rld, "project/protocol.v3.json", "protocol",
                            body=json.dumps({**PROTOCOL, "description": "fixed evaluator"}))
        instruction = self.doc(ResearchDB(self.db, "ui/ui"), "instructions/UI-0200.v1.md", "user_instruction")
        worker._after_compute = lambda: self.rld.update_project(protocol_doc_id=protocol,
                                                                user_instruction_doc_id=instruction)  # E07
        with self.assertRaisesRegex(ResearchDBError, "EVIDENCE_CHANGED"):
            worker.evaluate_experiment(exp2, self.result_doc(exp=exp2), "beats_sota")
        self.assertIsNone(self.rld.get(exp2).get("evaluated_at"))

    def test_e09_cached_labels_do_not_make_a_candidate(self):
        h = self.hypothesis()
        self.start(h)
        self.raw(h, experiment_status="beats_sota", novelty_recheck="pass", theory_recheck="pass")
        self.assertEqual(self.rld.go_candidates(), [])
        self.assertEqual(self.rld.get_eligibility(h)["reasons"], ["NO_EVALUATION"])
        with self.assertRaisesRegex(ResearchDBError, "GO needs .*no node has an evaluation"):
            self.go()

    def test_e10_closed_project_is_not_reopened(self):
        h, exp = self.candidate()
        stop = self.doc(self.rld, "instructions/stop.v1.md", "user_instruction")
        self.rld.decide("P-test", {"status": "stopped"}, "user stop", doc_id=self.decision_doc(), based_on=[stop])
        self.rld.retract_run(f"{exp}/s42", "corrupted metrics file", self.decision_doc())
        self.assertIn("RUN_RETRACTED", self.rld.get_eligibility(h)["reasons"])
        self.assertEqual(self.rld.get("P-test")["status"], "stopped")
        design = self.doc(self.worker, "exp/after.v1.md", "experiment_design")
        with self.assertRaisesRegex(ResearchDBError, "is stopped: no new research work"):
            self.worker.create_experiment("method", "m", design, self.commit(), 1, 60, hypothesis_id=h, estimated_node_h=1.0)

    def test_guardrail_failure_blocks_go(self):  # U09, 04 §5
        specs = json.loads(json.dumps(SPECS))
        specs["metrics"][2]["allowed_regression"] = 1.0  # peak memory may grow by at most 1 GiB
        doc = self.doc(self.rld, "project/metric-spec.v2.json", "metric_spec", body=json.dumps(specs))
        instruction = self.doc(ResearchDB(self.db, "ui/ui"), "instructions/UI-0300.v1.md", "user_instruction")
        self.rld.update_project(metric_spec_doc_id=doc, user_instruction_doc_id=instruction)
        with self.assertRaisesRegex(ResearchDBError, "EVIDENCE_STALE: the sota reference"):
            self.concluded("beats_sota", sota=(0.3, 0.1, -2.0))
        self.worker.evaluate_experiment(self.sota, self.result_doc(exp=self.sota))  # the baseline under the new specification
        h, exp = self.concluded("beats_sota", sota=(0.3, 0.1, -2.0))  # +2 GiB
        ev = self.rld.evaluations(experiment_id=exp)[-1]
        self.assertEqual((ev["gate_passed"], ev["guardrails_passed"]), (True, False))
        self.rld.decide(h, {"experiment_status": "beats_sota"}, "gate", based_on=[exp])
        self.recheck_pass(h, exp)
        self.assertEqual(self.rld.get_eligibility(h)["reasons"], ["GUARDRAIL_FAILED"])


class ReviewFixesTest(Fixture):
    """M1 review r1: protocol changes, rescoring, retraction records, basis choice, concurrency."""

    def test_e01_e02_protocol_change_needs_runs_that_meet_it(self):
        h, exp = self.candidate()
        protocol = self.doc(self.rld, "project/protocol.v5.json", "protocol",
                            body=json.dumps({**PROTOCOL, "match": {"epochs": 30}}))
        instruction = self.doc(ResearchDB(self.db, "ui/ui"), "instructions/UI-0500.v1.md", "user_instruction")
        self.rld.update_project(protocol_doc_id=protocol, user_instruction_doc_id=instruction)
        self.assertIn("PROTOCOL_CHANGED", self.rld.get_eligibility(h)["reasons"])
        # the old runs carry no manifest with the newly fixed setting: no evaluation of them under it
        with self.assertRaisesRegex(ResearchDBError, "EVIDENCE_STALE: the sota reference"):
            self.worker.evaluate_experiment(exp, self.result_doc(exp=exp), "beats_sota")
        with self.assertRaisesRegex(ResearchDBError, "PAIRING_MISMATCH: .*has no imported manifest"):
            self.worker.evaluate_experiment(self.sota, self.result_doc(exp=self.sota))
        self.assertFalse(self.rld.get_eligibility(h)["eligible"])
        self.assertEqual(self.rld.go_candidates(), [])

    def test_sticky_rescoring_and_basis(self):
        h = self.hypothesis()
        self.start(h)
        one = self.method(h, n_seeds=1)
        self.evaluate(one, "beats_parent", sota=(0.3, 0.1, 0.1))
        tuned = self.baseline(1, 1800)
        self.rld.update_project(sota_experiment_id=tuned)
        self.worker.evaluate_experiment(one, self.result_doc(exp=one), "beats_parent", baseline_experiment_id=tuned)
        self.worker.extend_seeds(one, 3)
        self.finish_runs(self.worker, one)
        self.worker.evaluate_experiment(one, self.result_doc(exp=one), "beats_sota")  # no baseline argument
        self.assertEqual(self.rld.evaluations(experiment_id=one)[-1]["baseline_experiment_id"], tuned)
        # the basis is the node's latest experiment's current evaluation, not the newest evaluation id
        newer = self.method(h)
        self.evaluate(newer, "beats_sota", sota=(0.4, 0.1, 0.1))
        again = self.baseline(1, 1800)
        self.rld.update_project(sota_experiment_id=again)
        self.worker.evaluate_experiment(one, self.result_doc(exp=one), "beats_sota", baseline_experiment_id=again)
        self.assertEqual(self.rld.get_eligibility(h)["experiment_id"], newer)

    def test_retraction_is_a_decision(self):
        h, exp = self.candidate()
        doc = self.decision_doc()
        basis = self.rld.get_eligibility(h)["basis_evaluation_id"]
        self.rld.retract_run(f"{exp}/s42", "corrupted metrics file", doc)
        record = self.rld.history(h)[-1]
        self.assertEqual((record["field"], record["to_value"]), ("run_validity", f"{exp}/s42@1 retracted"))
        self.assertEqual(set(record["based_on"]), {doc, basis})

    def test_concurrent_identical_evaluations_write_once(self):
        h = self.hypothesis()
        self.start(h)
        exp = self.method(h)
        self.finish_runs(self.worker, exp, effect=(self.sota, (0.3, 0.1, 0.1)))
        doc = self.result_doc(exp=exp)
        first = ResearchDB(self.db, "worker/w1")
        first._after_compute = lambda: ResearchDB(self.db, "worker/w1").evaluate_experiment(exp, doc, "beats_sota")
        self.assertFalse(first.evaluate_experiment(exp, doc, "beats_sota")["created"])
        self.assertEqual(len(self.rld.evaluations(experiment_id=exp)), 1)

    def test_eval_type_missing(self):
        h, exp = self.candidate()
        self.raw("P-test", protocol_doc_id=None)  # a project that lost its protocol
        self.worker.evaluate_experiment(self.sota, self.result_doc(exp=self.sota))
        self.worker.evaluate_experiment(exp, self.result_doc(exp=exp), "beats_sota", baseline_experiment_id=self.sota)
        self.assertIn("EVAL_TYPE_MISSING", self.rld.get_eligibility(h)["reasons"])

    def test_no_self_citation(self):
        path = self.root / "docs" / "results" / "self.v1.md"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text('acc "0.9"\n```evidence\n[{"id": "a", "value": "0.9", "source": "docs/results/self.v1.md"}]\n```\n')
        doc = self.worker.register_document("results/self.v1.md", "experiment_result", "r")
        with self.assertRaisesRegex(ResearchDBError, "path_missing"):
            self.worker.set_document_current(doc)


class ArtifactImportTest(Fixture):
    """04 §2 P0-B: every participating run imported gives artifact_imported; a protocol may require it."""

    def test_artifact_level(self):
        design = self.doc(self.worker, "exp/ai.v1.md", "experiment_design")
        base = self.worker.create_experiment("baseline", "sota", design, self.harness, 1, 1800, config_path=f"configs/{design}.yaml", estimated_node_h=1.0)
        self.imported(base)
        self.worker.evaluate_experiment(base, self.result_doc(exp=base))
        self.rld.update_project(sota_experiment_id=base)
        h = self.hypothesis()
        self.start(h)
        exp = self.method(h)
        self.imported(exp, effect=(base, (0.3, 0.1, 0.1)))
        result = self.worker.evaluate_experiment(exp, self.result_doc(exp=exp), "beats_sota")
        self.assertEqual(result["verification_level"], "artifact_imported")
        ev = self.rld.evaluations(experiment_id=exp)[-1]
        self.assertEqual(ev["parser_version"], metrics_mod.PARSER_VERSION)
        self.assertIn(f"outputs/{exp}/s42/metrics.json", ev["artifact_refs"])
        self.assertIn(f"outputs/{base}/s42/metrics.json", ev["artifact_refs"])

    def test_required_import(self):
        protocol = self.doc(self.rld, "project/protocol.v7.json", "protocol",
                            body=json.dumps({**PROTOCOL, "require_artifact_import": True}))
        instruction = self.doc(ResearchDB(self.db, "ui/ui"), "instructions/UI-0700.v1.md", "user_instruction")
        self.rld.update_project(protocol_doc_id=protocol, user_instruction_doc_id=instruction)
        h = self.hypothesis()
        self.start(h)
        exp = self.method(h, n_seeds=1)
        with self.assertRaisesRegex(ResearchDBError, "the protocol requires imported results"):
            self.finish_runs(self.worker, exp)
        self.imported(exp, effect=(self.sota, (0.3, 0.1, 0.1)))
        # the SOTA's runs were reported, not imported: no comparison with them under this protocol
        with self.assertRaisesRegex(ResearchDBError, "EVIDENCE_STALE|PROTOCOL_CHANGE_REQUIRED: the protocol requires imported"):
            self.worker.evaluate_experiment(exp, self.result_doc(exp=exp), "beats_parent")
        with self.assertRaisesRegex(ResearchDBError, "PROTOCOL_CHANGE_REQUIRED: the protocol requires imported"):
            self.worker.evaluate_experiment(self.sota, self.result_doc(exp=self.sota))


class GateTieTest(Fixture):
    """05 §2.3: the protocol's '>' or '>=' decides a tie, not binary rounding (0.701 x 100 - 0.699 x 100)."""

    def test_tie(self):
        spec = {**SPECS["metrics"][0], "input_unit": "fraction", "valid_range": [0, 1], "minimum_practical_gain": 0.2}
        self.assertFalse(metrics_mod.passes(0.701 * 100 - 0.699 * 100, 0.2, ">"))
        self.assertTrue(metrics_mod.passes(0.701 * 100 - 0.699 * 100, 0.2, ">="))
        e = metrics_mod.effect(spec, [metrics_mod.canonical(spec, 0.701, "r")], [metrics_mod.canonical(spec, 0.699, "r")])
        self.assertTrue(metrics_mod.passes(e["delta_mean"], 0.2, ">="))
        self.assertFalse(metrics_mod.passes(e["delta_mean"], 0.2, ">"))


class ReportAndRetractionTest(Fixture):
    def test_go_report_claims_are_verified(self):
        h, exp = self.candidate()
        fake = self.root / "docs" / "decisions" / "go.v1.md"
        fake.parent.mkdir(parents=True, exist_ok=True)
        fake.write_text('```evidence\n[{"id": "d", "value": "9.99", "source": "outputs/none.json"}]\n```\n')
        doc = self.rld.register_document("decisions/go.v1.md", "decision", "go")
        self.rld.set_document_current(doc)  # a decision document's claims are not checked when it is frozen
        with self.assertRaisesRegex(ResearchDBError, "is a decision document"):
            self.rld.decide("P-test", {"status": "go"}, "GO", doc_id=doc)
        self.rld.decide("P-test", {"status": "go"}, "GO", doc_id=self.report_doc("go"))

    def test_retracted_attempt_stays_invalid(self):
        h, exp = self.candidate()
        self.rld.retract_run(f"{exp}/s42", "wrong split", self.decision_doc())
        with self.assertRaisesRegex(ResearchDBError, "was retracted"):
            self.worker.update_run(f"{exp}/s42", valid=True)
        self.worker.update_run(f"{exp}/s42", attempt=2, exec_status="planned")


class FinalReviewTest(Fixture):
    """M1 final review: gate stated once, preview, statistics version, manifest reuse, retraction links."""

    def test_preview_matches_the_evaluation(self):
        h = self.hypothesis()
        self.start(h)
        exp = self.method(h)
        self.finish_runs(self.worker, exp, effect=(self.sota, (0.3, 0.1, 0.1)))
        preview = ResearchDB(self.db, "ui/ui").preview_evaluation(exp)
        self.assertAlmostEqual(preview["metrics"]["acc"]["mean"], 70.3, places=9)
        self.assertAlmostEqual(preview["comparisons"]["sota"]["effects"]["acc"], 0.3, places=9)
        self.assertEqual(self.rld.evaluations(experiment_id=exp), [])  # nothing recorded
        self.assertIn("preview_evaluation", rdb.READ_METHODS)

    def test_statistics_version_change(self):
        h, exp = self.candidate()
        saved = metrics_mod.STATISTICS_VERSION
        rdb.metrics.STATISTICS_VERSION = "rt-stats-2"
        try:
            self.assertIn("STATISTICS_CHANGED", self.rld.get_eligibility(h)["reasons"])
        finally:
            rdb.metrics.STATISTICS_VERSION = saved

    def test_imported_runs_meet_a_later_protocol(self):
        design = self.doc(self.worker, "exp/mr.v1.md", "experiment_design")
        base = self.worker.create_experiment("baseline", "sota", design, self.harness, 1, 1800, config_path=f"configs/{design}.yaml", estimated_node_h=1.0)
        self.imported(base, epochs=30)
        self.worker.evaluate_experiment(base, self.result_doc(exp=base))
        self.rld.update_project(sota_experiment_id=base)
        h = self.hypothesis()
        self.start(h)
        exp = self.method(h)
        self.imported(exp, effect=(base, (0.3, 0.1, 0.1)), epochs=30)
        protocol = self.doc(self.rld, "project/protocol.v8.json", "protocol",
                            body=json.dumps({**PROTOCOL, "match": {"epochs": 30}}))
        instruction = self.doc(ResearchDB(self.db, "ui/ui"), "instructions/UI-0800.v1.md", "user_instruction")
        self.rld.update_project(protocol_doc_id=protocol, user_instruction_doc_id=instruction)
        self.worker.evaluate_experiment(base, self.result_doc(exp=base))  # no re-run: the manifests record epochs
        result = self.worker.evaluate_experiment(exp, self.result_doc(exp=exp), "beats_sota")
        self.assertTrue(result["gate_passed"])

    def test_retracting_a_baseline_run_links_the_node_evaluations(self):
        h, exp = self.candidate()
        node_ev = self.rld.get(exp)["evaluation_id"]
        self.rld.retract_run(f"{self.sota}/s42", "baseline evaluator bug", self.decision_doc())
        decision = [d for d in self.rld.history("P-test") if d["field"] == "run_validity"][-1]
        self.assertIn(node_ev, decision["based_on"])
        self.assertIn("RUN_RETRACTED", self.rld.get_eligibility(h)["reasons"])


class FrozenSetTest(Fixture):
    """M1 final review r4: the frozen file set, documents edited in place, glob sources."""

    def test_narrowing_the_harness_paths_ends_eligibility(self):
        h, exp = self.candidate()
        self.rld.update_project(harness_paths=["harness/stats.py"])
        result = self.rld.get_eligibility(h)
        self.assertIn("HARNESS_CHANGED", result["reasons"])
        self.assertIsNone(self.rld.get("P-test").get("sota_experiment_id"))  # the SOTA is run again

    def test_documents_edited_in_place_are_refused(self):
        h = self.hypothesis()
        self.start(h)
        exp = self.method(h)
        self.finish_runs(self.worker, exp, effect=(self.sota, (0.3, 0.1, 0.1)))
        doc = self.result_doc(exp=exp)
        path = self.root / "docs" / self.rld.get(doc)["path"]
        path.write_text(path.read_text() + "\nedited after it became current\n")
        with self.assertRaisesRegex(ResearchDBError, "no longer matches its recorded hash"):
            self.worker.evaluate_experiment(exp, doc, "beats_sota")

    def test_glob_sources_name_files(self):
        (self.root / "outputs" / "a").mkdir(parents=True, exist_ok=True)
        (self.root / "outputs" / "a" / "x.json").write_text('{"v": 0.123}')
        for source, status in (("outputs/**/*.json", "path_missing"), ("outputs/a/*.json", "verified")):
            got = rdb.claims_check.check_claim("0.123", source, self.root, self.root)["status"]
            self.assertEqual(got, status, source)

    def test_percentage_metrics_declare_their_range(self):
        bad = {**SPECS, "metrics": [{k: v for k, v in SPECS["metrics"][0].items() if k != "valid_range"},
                                    *SPECS["metrics"][1:]]}
        with self.assertRaisesRegex(MetricErrorAlias, "a percentage metric declares valid_range"):
            metrics_mod.check_metric_specs(bad)


class UnitMixTest(Fixture):
    """M05 in both directions: a fraction among percentages is refused at import and at comparison."""

    def test_reverse_mix(self):
        h = self.hypothesis()
        self.start(h)
        exp = self.method(h, n_seeds=1)
        self.finish_runs(self.worker, exp, metric_value=0.703)  # inside [0, 100], but a fraction
        with self.assertRaisesRegex(ResearchDBError, "METRIC_UNIT_MISMATCH: the compared runs: acc values range from 0.703"):
            self.worker.evaluate_experiment(exp, self.result_doc(exp=exp), "beats_parent")
        other = self.method(h, n_seeds=1)
        self.worker.create_run(other, 42)
        self.worker.update_run(f"{other}/s42", exec_status="submitted")
        self.worker.update_run(f"{other}/s42", exec_status="succeeded")
        with self.assertRaisesRegex(ResearchDBError, "METRIC_UNIT_MISMATCH: .*declares units"):
            self.worker.import_run_result(f"{other}/s42", 1, self.manifest(other, 42, units={"acc": "fraction"}))
        self.assertTrue(metrics_mod.passes(-0.0, 0.0, ">="))
        self.assertFalse(metrics_mod.passes(-4e-10, 0.0, ">="))  # no absolute rounding at the gate


class ReviewSixTest(Fixture):
    def test_one_fraction_among_percentages(self):
        design = self.doc(self.worker, "exp/mix.v1.md", "experiment_design")
        mixed = self.worker.create_experiment("baseline", "sota", design, self.harness, 1, 1800, config_path=f"configs/{design}.yaml", estimated_node_h=1.0)
        for seed, value in zip(SEEDS, (69.9, 69.9, 0.699)):
            self.worker.create_run(mixed, seed)
            self.worker.update_run(f"{mixed}/s{seed}", exec_status="submitted")
            self.worker.update_run(f"{mixed}/s{seed}", exec_status="succeeded", valid=True, metric_value=value,
                                   secondary={"final_loss": 1.0, "peak_mem_gb": 40.0}, nodes_used=1,
                                   walltime_used_s=60, log_path="x.log")
        with self.assertRaisesRegex(ResearchDBError, "METRIC_UNIT_MISMATCH: E-0002: acc values range from 0.699 to 69.9"):
            self.worker.evaluate_experiment(mixed, self.result_doc(exp=mixed))

    def test_eval_type_limit_is_carried(self):
        protocol = self.doc(self.rld, "project/protocol.v9.json", "protocol",
                            body=json.dumps({**PROTOCOL, "eval_type": "synthetic_proxy"}))
        instruction = self.doc(ResearchDB(self.db, "ui/ui"), "instructions/UI-0900.v1.md", "user_instruction")
        self.rld.update_project(protocol_doc_id=protocol, user_instruction_doc_id=instruction)
        self.worker.evaluate_experiment(self.sota, self.result_doc(exp=self.sota))
        ev = self.rld.evaluations(experiment_id=self.sota)[-1]
        self.assertEqual(ev["eval_type"], "synthetic_proxy")
        self.assertTrue(any("proxy agreement only" in x for x in ev["limitations"]))

    def test_protocol_match_values_are_scalars(self):
        with self.assertRaisesRegex(MetricErrorAlias, "match values are scalars"):
            metrics_mod.check_protocol({**PROTOCOL, "match": {"layers": [1, 2]}})


class GateStatedOnceTest(unittest.TestCase):
    def test_go_margin_follows_the_specification(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "research" / "P-g"
            (root / "docs").mkdir(parents=True)
            db = root / "research_tree.db"
            create_db.create_db(db)
            rld = ResearchDB(db, "rld/main")
            docs = {}
            (root / "docs" / "s.v1.md").write_text("s")
            setup = rld.register_document("s.v1.md", "min_setup", "s")
            for kind, content in zip(("metric_spec", "protocol"), (SPECS, PROTOCOL)):
                (root / "docs" / f"{kind}.v1.json").write_text(json.dumps(content))
                docs[f"{kind}_doc_id"] = rld.register_document(f"{kind}.v1.json", kind, kind)
                rld.set_document_current(docs[f"{kind}_doc_id"])
            rld.create_project("P-g", "g", setup, "acc", "higher", True, SECONDARY, SEEDS, **docs)
            with self.assertRaisesRegex(ResearchDBError, "METRIC_UNIT_MISMATCH: .*must equal the project's go_margin 0.1"):
                rld.update_project(go_margin=0.1)  # e.g. config apply at confirmation
            with self.assertRaisesRegex(ResearchDBError, "METRIC_UNIT_MISMATCH: .*must equal the project's go_margin 0.2"):
                rld.update_project(go_margin=0.2, metric_spec_doc_id=docs["metric_spec_doc_id"])


class UncertaintyTest(Fixture):
    """plans/design 11 §1.4 (U01–U05, U10): uncertainty, screening and confirmation."""

    def test_u01_one_slightly_negative_seed_is_inconclusive(self):
        h = self.hypothesis()
        self.start(h)
        exp = self.method(h, n_seeds=1)
        result = self.evaluate(exp, None, sota=(-0.03, 0.0, 0.0))
        self.assertEqual(result["outcome"], "inconclusive")
        self.rld.decide(h, {"experiment_status": "inconclusive"}, "one seed", based_on=[exp],
                        doc_id=self.decision_doc())
        self.assertEqual((self.rld.get(h)["status"], self.rld.get(h)["disposition"]), ("verifying", "active"))

    def test_u02_seed_limit_near_threshold_stays_inconclusive(self):
        h = self.hypothesis()
        self.start(h)
        exp = self.method(h)  # all 3 seeds
        self.assertEqual(self.evaluate(exp, "close", sota=(0.02, 0.0, 0.0))["outcome"], "inconclusive")
        neg = self.method(h)
        self.assertEqual(self.evaluate(neg, None, sota=(-0.2, 0.0, 0.0))["outcome"], "negative_signal")
        pos = self.method(h)
        self.assertEqual(self.evaluate(pos, None, sota=(0.2, 0.0, 0.0))["outcome"], "positive_signal")

    def test_u03_engineering_failure_is_no_negative_evidence(self):
        h = self.hypothesis()
        self.start(h)
        exp = self.method(h, n_seeds=1)
        self.worker.create_run(exp, 42)
        self.worker.update_run(f"{exp}/s42", exec_status="submitted")
        self.worker.update_run(f"{exp}/s42", exec_status="failed")
        self.assertEqual(self.rld.evaluations(experiment_id=exp), [])
        self.assertEqual(self.rld.get_eligibility(h)["reasons"], ["NO_EVALUATION"])
        with self.assertRaisesRegex(ResearchDBError, "retiring a node .* needs based_on"):
            self.rld.decide(h, {"status": "prunable"}, "it failed", doc_id=self.decision_doc(), reconsider_when="new evidence on the mechanism")

    def test_inconclusive_decisions_name_the_missing_evidence(self):
        h = self.hypothesis()
        self.start(h)
        exp = self.method(h, n_seeds=1)
        self.evaluate(exp, None, sota=(0.01, 0.0, 0.0))
        bare = self.doc(self.rld, "decisions/bare.v1.md", "decision", body="x\n")
        with self.assertRaisesRegex(ResearchDBError, "inconclusive: .*missing 缺失证据, 下一实验"):
            self.rld.decide(h, {"experiment_status": "inconclusive"}, "x", based_on=[exp], doc_id=bare)
        second = self.method(h, n_seeds=1)
        self.evaluate(second, None, sota=(0.0, 0.01, 0.0))
        with self.assertRaisesRegex(ResearchDBError, "last two results were inconclusive"):
            self.method(h)
        design = self.doc(self.worker, "exp/why.v1.md", "experiment_design")
        self.worker.create_experiment("method", "m", design, self.commit(), 1, 60, hypothesis_id=h,
                                      selection_rationale="2 more seeds separate a 0.05 gain from noise", estimated_node_h=1.0)


class ConfirmationTest(Fixture):
    """U04, U05: a search winner is candidate_ready; GO needs an unseen confirmation of the same code."""

    protocol_content = {**PROTOCOL, "profile": "stage1_confirmed", "confirmation_seeds": [1042, 1043, 1044],
                        "max_confirmation_candidates": 1}

    def confirm_baseline(self) -> str:
        design = self.doc(self.worker, "exp/cb.v1.md", "experiment_design")
        base = self.worker.create_experiment("baseline", "sota", design, self.harness, 1, 1800, stage="confirm", config_path=f"configs/{design}.yaml", estimated_node_h=1.0)
        self.assertEqual(self.rld.get(base)["seeds"], [1042, 1043, 1044])
        self.finish_runs(self.worker, base)
        self.worker.evaluate_experiment(base, self.result_doc(exp=base))
        return base

    def test_u04_u05(self):
        h, exp = self.candidate_ready()
        result = self.rld.get_eligibility(h)
        self.assertEqual((result["stage"], result["reasons"]), ("candidate_ready", ["CONFIRMATION_REQUIRED"]))
        with self.assertRaisesRegex(ResearchDBError, "CONFIRMATION_REQUIRED: GO needs"):
            self.rld.decide("P-test", {"status": "go"}, "GO", doc_id=self.report_doc("go"))
        design = self.doc(self.worker, "exp/c1.v1.md", "experiment_design")
        with self.assertRaisesRegex(ResearchDBError, "no confirmation baseline"):
            self.worker.create_experiment("method", "m", design, self.rld.get(exp)["code_ref"], 1, 60,
                                          hypothesis_id=h, stage="confirm", estimated_node_h=1.0)
        self.confirm_baseline()
        with self.assertRaisesRegex(ResearchDBError, "runs the frozen candidate"):
            self.worker.create_experiment("method", "m", design, self.commit(), 1, 60, hypothesis_id=h,
                                          stage="confirm", estimated_node_h=1.0)
        conf = self.worker.create_experiment("method", "m", design, self.rld.get(exp)["code_ref"], 1, 60,
                                             hypothesis_id=h, stage="confirm", estimated_node_h=1.0)
        self.evaluate(conf, None, sota=(0.3, 0.1, 0.1))
        result = self.rld.get_eligibility(h)
        self.assertEqual((result["eligible"], result["stage"]), (True, "confirmed"), result)
        # U05: the confirmation's feedback changes the code: the same seeds are no longer unseen
        newer = self.method(h)
        self.evaluate(newer, "beats_sota", sota=(0.4, 0.1, 0.1))
        self.recheck_pass(h, newer)
        conf2 = self.worker.create_experiment("method", "m", design, self.rld.get(newer)["code_ref"], 1, 60,
                                              hypothesis_id=h, stage="confirm", estimated_node_h=1.0)
        self.evaluate(conf2, None, sota=(0.4, 0.1, 0.1))
        self.assertEqual(self.rld.get_eligibility(h)["reasons"], ["CONFIRMATION_REUSED"])
        # a second node cannot also enter confirmation (max_confirmation_candidates 1)
        h2, exp2 = self.candidate_ready()
        with self.assertRaisesRegex(ResearchDBError, "BUDGET_EXCEEDED: max_confirmation_candidates"):
            self.worker.create_experiment("method", "m", design, self.rld.get(exp2)["code_ref"], 1, 60,
                                          hypothesis_id=h2, stage="confirm", estimated_node_h=1.0)

    def candidate_ready(self) -> tuple[str, str]:
        h, exp = self.concluded("beats_sota")
        self.rld.decide(h, {"experiment_status": "beats_sota"}, "gate", based_on=[exp])
        self.recheck_pass(h, exp)
        return h, exp


class IndependenceTest(Fixture):
    """U10: runs that share a data order are one independent repeat, not several."""

    protocol_content = {**PROTOCOL, "independence_fields": ["data_order"]}

    def test_u10(self):
        design = self.doc(self.worker, "exp/ib.v1.md", "experiment_design")
        base = self.worker.create_experiment("baseline", "sota", design, self.harness, 1, 1800, config_path=f"configs/{design}.yaml", estimated_node_h=1.0)
        self.imported(base, data_order="fixed")
        self.worker.evaluate_experiment(base, self.result_doc(exp=base))
        self.rld.update_project(sota_experiment_id=base)
        h = self.hypothesis()
        self.start(h)
        exp = self.method(h)
        self.imported(exp, effect=(base, (0.3, 0.1, 0.1)), data_order="fixed")
        result = self.worker.evaluate_experiment(exp, self.result_doc(exp=exp), None)
        self.assertFalse(result["gate_passed"])  # 3 pairs, 1 independent repeat
        ev = self.rld.evaluations(experiment_id=exp)[-1]
        self.assertEqual(ev["comparisons"]["sota"]["n_independent"], 1)


class LedgerTest(Fixture):
    """06 §6 (O01–O04)."""

    def test_o01_o04(self):
        h, exp = self.candidate()
        add = lambda severity, excerpt="acc read from the train split": self.rld.add_obligation(
            h, "code_review:RV-0001", "gt_source", "labels come from the training split", severity, excerpt)
        first = add("MINOR")
        self.assertEqual(self.rld.get_eligibility(h)["reasons"], ["OBLIGATION_OPEN"])
        with self.assertRaisesRegex(ResearchDBError, "OBLIGATION_OPEN"):
            self.rld.decide("P-test", {"status": "go"}, "GO", doc_id=self.report_doc("go"))
        again = add("MAJOR")  # the same finding: no second entry, severity only rises
        self.assertEqual((again["obligation_id"], again["created"], again["severity"]),
                         (first["obligation_id"], False, "MAJOR"))
        self.assertEqual(add("MINOR")["severity"], "MAJOR")
        evidence = self.root / "outputs" / "fix.txt"
        evidence.parent.mkdir(parents=True, exist_ok=True)
        evidence.write_text("labels now read from the validation split\n")
        with self.assertRaises(PermissionDenied):
            self.worker.resolve_obligation(first["obligation_id"], "code_fixed", "outputs/fix.txt")
        self.rld.resolve_obligation(first["obligation_id"], "code_fixed", "outputs/fix.txt")
        self.assertTrue(self.rld.get_eligibility(h)["eligible"])
        reopened = add("MINOR")  # O01: the same fingerprint again reopens it
        self.assertEqual((reopened["obligation_id"], reopened["status"]), (first["obligation_id"], "OPEN"))
        # O02: absent from a later report of the same family: still OPEN, marked
        self.assertEqual(self.rld.reconcile_obligations(h, "code_review:RV-0002", []), [first["obligation_id"]])
        ob = self.rld.obligations(about=h)[0]
        self.assertEqual((ob["status"], ob["disappearance"]["code"]), ("OPEN", "UNRESOLVED_DISAPPEARANCE"))
        # O04: the user waives it
        with self.assertRaisesRegex(ResearchDBError, "the user's"):
            self.rld.waive_obligation(first["obligation_id"], self.decision_doc())
        user = self.doc(ResearchDB(self.db, "ui/ui"), "instructions/UI-1000.v1.md", "user_instruction")
        self.rld.waive_obligation(first["obligation_id"], user)
        self.assertEqual(self.rld.obligations(status="WAIVED")[0]["id"], first["obligation_id"])
        self.assertTrue(self.rld.get_eligibility(h)["eligible"])

    def test_mismatches_are_ledgered(self):
        h = self.hypothesis()
        self.start(h)
        exp = self.method(h)
        self.finish_runs(self.worker, exp, effect=(self.sota, (0.3, 0.1, 0.1)))
        for _ in range(2):
            with self.assertRaisesRegex(ResearchDBError, "STAT_MISMATCH"):
                self.worker.record_verdict(exp, self.result_doc(exp=exp), 71.0, None, "beats_sota")
        obs = self.rld.obligations(about=exp)
        self.assertEqual([(o["source"], o["status"]) for o in obs], [("STAT_MISMATCH:interface", "OPEN")])  # once
        result = self.worker.evaluate_experiment(exp, self.result_doc(exp=exp), "beats_sota")
        self.rld.resolve_obligation(obs[0]["id"], "re_evaluated", result["evaluation_id"])


class StallTest(Fixture):
    """06 §5 (T01, T02)."""

    def test_t01_t02(self):
        root = self.hypothesis()
        self.rld.update_hypothesis(root, title="root of the subtree")
        self.rld.note_findings(root, 1, direction="optimizer-state")
        first = self.rld.note_findings(root, 0)
        self.assertEqual((first["streak"], first["stall_state"]), (1, "none"))
        second = self.rld.note_findings(root, 0)
        self.assertEqual(second["stall_state"], "structural")
        self.start(root)  # the subtree root must be expandable for children: make it so
        self.evaluate(self.method(root), None, sota=(0.3, 0.1, 0.1))
        self.rld.decide(root, {"experiment_status": "beats_sota", "status": "expandable"}, "gate",
                        doc_id=self.decision_doc(), based_on=[self.rld.latest_result(root)["id"]])
        doc = self.doc(self.rld, "h/stall/hypothesis.v1.md", "hypothesis")
        with self.assertRaisesRegex(ResearchDBError, "STALL_STRUCTURAL"):
            self.rld.create_hypothesis("same", "s", doc, self.literature, root, direction="optimizer-state")
        with self.assertRaisesRegex(ResearchDBError, "STALL_STRUCTURAL"):
            self.rld.create_hypothesis("unnamed", "s", doc, self.literature, root)
        self.rld.create_hypothesis("other", "s", doc, self.literature, root, direction="data-order control")
        self.rld.note_findings(root, 0)
        human = self.rld.note_findings(root, 0)
        self.assertEqual((human["stall_state"], human["report_to_user"]), ("human", True))
        self.assertEqual(self.rld.note_findings(root, 2)["stall_state"], "none")


class StateMigrationTest(Fixture):
    def test_old_states(self):
        h, exp = self.concluded("no_gain", sota=(-0.1, -0.1, -0.1))
        self.rld.decide(h, {"experiment_status": "no_gain", "status": "prunable"}, "no gain",
                        doc_id=self.decision_doc(), based_on=[exp], reconsider_when="new evidence on the mechanism")
        h2 = self.hypothesis()
        for node in (h, h2):
            self.raw(node, disposition=None)  # as an old project left them
        report = self.rld.migrate_states()
        self.assertEqual({n["hypothesis_id"]: (n["lifecycle"], n["disposition"]) for n in report["nodes"]},
                         {h: ("assessed", "retired"), h2: ("pending", "active")})
        self.assertIsNone(self.rld.get(h2).get("disposition"))  # dry run
        self.rld.migrate_states(dry_run=False)
        self.assertEqual((self.rld.get(h)["disposition"], self.rld.get(h2)["disposition"]), ("retired", "active"))

    def test_resume_point(self):
        req = self.doc(self.rld, "tasks/r/request.v1.md", "task_request")
        first = self.rld.create_task("harness", "worker", req, target_id="P-test", assignee_id="w1")
        self.rld.create_task("analysis", "worker", req, target_id="P-test", assignee_id="w1")
        self.assertEqual(self.rld.resume_package("P-test")["first_unaccepted_task"], first)


class M2ReviewTest(Fixture):
    """M2 review: admission follows disposition; candidate_ready before confirmation; project obligations; the
    screening GO disclaimer; invalid outcome; closed branches; never-tested nodes migrate as pending."""

    def test_paused_nodes_take_no_new_work(self):
        h = self.hypothesis()
        self.start(h)
        exp = self.method(h, n_seeds=1)
        self.evaluate(exp, None, sota=(0.01, 0.0, 0.0))
        self.rld.decide_disposition(h, "paused", "budget held for H-other", [exp], reconsider_when="budget frees up")
        with self.assertRaisesRegex(ResearchDBError, "is paused .*no new experiments"):
            self.method(h)
        with self.assertRaisesRegex(ResearchDBError, "not active: no seed extensions"):
            self.worker.extend_seeds(exp, 3)
        self.rld.decide_disposition(h, "active", "budget freed", [exp])
        self.method(h)

    def test_confirmation_after_candidate_ready_and_project_obligations(self):
        self.rld.update_project(protocol_doc_id=self.doc(self.rld, "project/protocol.v20.json", "protocol", body=json.dumps(
            {**PROTOCOL, "confirmation_seeds": [1042, 1043, 1044]})), user_instruction_doc_id=self.doc(
            ResearchDB(self.db, "ui/ui"), "instructions/UI-1999.v1.md", "user_instruction"))
        self.worker.evaluate_experiment(self.sota, self.result_doc(exp=self.sota))
        h, exp = self.candidate()
        self.rld.add_obligation(h, "code_review:RV-0001", "seed_config", "seeds differ from the protocol", "MAJOR")
        design = self.doc(self.worker, "exp/c.v1.md", "experiment_design")
        with self.assertRaisesRegex(ResearchDBError, "OBLIGATION_OPEN: .* not candidate_ready"):
            self.worker.create_experiment("method", "m", design, self.rld.get(exp)["code_ref"], 1, 60,
                                          hypothesis_id=h, stage="confirm", estimated_node_h=1.0)
        user = self.doc(ResearchDB(self.db, "ui/ui"), "instructions/UI-2000.v1.md", "user_instruction")
        self.rld.waive_obligation(self.rld.obligations(about=h)[0]["id"], user)
        self.rld.add_obligation("P-test", "audit:A1", "scope", "the harness reads the wrong split", "CRITICAL")
        with self.assertRaisesRegex(ResearchDBError, "OBLIGATION_OPEN: open obligations about the project"):
            self.rld.decide("P-test", {"status": "go"}, "GO", doc_id=self.report_doc("go"))

    def test_screening_go_says_it_is_unconfirmed(self):
        h, exp = self.candidate()
        path = self.root / "docs" / "reports" / "go-bare.v1.md"
        path.parent.mkdir(parents=True, exist_ok=True)
        (self.root / "outputs" / "evidence").mkdir(parents=True, exist_ok=True)
        (self.root / "outputs" / "evidence" / "g.json").write_text('{"d": 0.3}')
        path.write_text('```evidence\n[{"id": "d", "value": "0.3", "source": "outputs/evidence/g.json"}]\n```\n')
        doc = self.rld.register_document("reports/go-bare.v1.md", "report", "go")
        self.rld.set_document_current(doc)
        with self.assertRaisesRegex(ResearchDBError, "screening profile: .*missing 未经独立确认"):
            self.rld.decide("P-test", {"status": "go"}, "GO", doc_id=doc)

    def test_invalid_outcome_and_closed_branch(self):
        h = self.hypothesis()
        self.start(h)
        exp = self.method(h, n_seeds=1)
        self.worker.create_run(exp, 42)
        self.worker.update_run(f"{exp}/s42", exec_status="submitted")
        self.worker.update_run(f"{exp}/s42", exec_status="failed")
        self.assertEqual(self.rld.get_eligibility(h)["outcome"], "invalid")
        br = self.rld.find("branch", hypothesis_id=h)[0]["id"]
        self.git("tag", f"exp/{exp}", self.rld.get(exp)["code_ref"])
        self.worker.return_branch(br, self.commit())
        self.rld.close_branch(br, "deleted", "pruned", self.decision_doc())
        with self.assertRaisesRegex(ResearchDBError, "is deleted"):
            self.method(h)

    def test_never_tested_prunable_migrates_as_pending(self):
        h = self.hypothesis()
        declined = self.doc(ResearchDB(self.db, "ui/ui"), "instructions/UI-2100.v1.md", "user_instruction", about=(h,))
        self.rld.decide(h, {"status": "prunable"}, "user declined", doc_id=self.decision_doc(), based_on=[declined],
                        reconsider_when="the user asks again")
        self.raw(h, disposition=None)
        node = self.rld.migrate_states()["nodes"][0]
        self.assertEqual((node["lifecycle"], node["disposition"]), ("pending", "retired"))


class BudgetTest(Fixture):
    """plans/design 11 §1.5 (B01–B14): reservations, submission identity and settlement."""

    def setUp(self):
        super().setUp()
        # 3 SOTA runs at 1800 node-s are recorded outside reservations: 5400 committed
        self.rld.update_project(total_limit=12600, search_limit=9000, confirmation_limit=3600)
        self.h = self.hypothesis()
        self.start(self.h)

    def planned(self, n_seeds: int = 1) -> tuple[str, list[str]]:
        exp = self.method(self.h, n_seeds=n_seeds, walltime_s=100)
        refs = []
        for seed in self.rld.get(exp)["seeds"]:
            self.worker.create_run(exp, seed)
            refs.append(f"{exp}/s{seed}@1")
        return exp, refs

    def accounting(self, name: str, job: str, units: int) -> str:
        path = self.root / "outputs" / "accounting" / f"{name}.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps({"job_id": job, "node_seconds": units}))
        return f"outputs/accounting/{name}.json"

    def test_b02_b10_one_key_one_reservation_per_allocation(self):
        exp, refs = self.planned(3)
        r = self.worker.reserve_submission("k1", refs, {"nodes": 1, "walltime_s": 1000})
        self.assertEqual((r["reserved_units"], r["budget_pool"], r["created"]), (1000, "search", True))  # B10
        again = self.worker.reserve_submission("k1", refs, {"nodes": 1, "walltime_s": 1000})
        self.assertEqual((again["reservation_id"], again["created"]), (r["reservation_id"], False))  # B02
        with self.assertRaisesRegex(ResearchDBError, "SUBMISSION_AMBIGUOUS: .*under k1"):
            self.worker.reserve_submission("k2", refs[:1], {"nodes": 1, "walltime_s": 100})

    def test_submission_protocol_b03_b05_b06(self):
        exp, refs = self.planned(1)
        run = refs[0].rpartition("@")[0]
        with self.assertRaisesRegex(ResearchDBError, "BUDGET_EXCEEDED: .*only under a reservation"):
            self.worker.update_run(run, exec_status="submitted")
        self.worker.reserve_submission("k1", refs, {"nodes": 1, "walltime_s": 1000})
        with self.assertRaisesRegex(ResearchDBError, "only under a reservation"):  # intent, not yet claimed
            self.worker.update_run(run, exec_status="submitted")
        gen = self.worker.claim_submission("k1")["claim_generation"]
        with self.assertRaisesRegex(ResearchDBError, "SUBMISSION_AMBIGUOUS: .*is claimed"):  # no second submitter
            self.worker.claim_submission("k1")
        self.worker.update_run(run, exec_status="submitted")
        # B03: the scheduler took it but the answer was lost: held, never resubmitted blindly
        self.worker.update_run(run, exec_status="unknown")
        self.assertEqual(self.worker.reconcile_submission("k1")["accounting_status"], "held_unknown")
        self.assertIn("SUBMISSION_AMBIGUOUS", self.worker.reconcile_submission("k1")["next"])
        # B05: found again by the key: attach the original job, no second job
        self.worker.attach_job("k1", "job-17", gen)
        self.assertEqual(self.rld.get(run)["job_id"], "job-17")
        with self.assertRaisesRegex(ResearchDBError, "SUBMISSION_AMBIGUOUS: .*is job job-17"):
            self.worker.attach_job("k1", "job-18", gen)
        self.worker.update_run(run, exec_status="succeeded")
        res = self.worker.reconcile_submission("k1")["reservation_id"]
        settled = self.worker.settle_reservation(res, self.accounting("a1", "job-17", 900))
        self.assertEqual((settled["accounting_status"], settled["actual_units"], settled["overrun"]), ("settled", 900, False))
        self.assertEqual(self.worker.settle_reservation(res, self.accounting("a1", "job-17", 900))["actual_units"], 900)  # B06
        with self.assertRaisesRegex(ResearchDBError, "EVIDENCE_CHANGED"):
            self.worker.settle_reservation(res, self.accounting("a2", "job-17", 950))

    def test_b01_last_quota_admits_one(self):
        e1, r1 = self.planned(1)
        e2, r2 = self.planned(1)
        # 9000 search limit, 5400 committed: room for one 3000 node-s allocation, not two
        results = []
        def go(key, refs):
            try:
                results.append(ResearchDB(self.db, "worker/w1").reserve_submission(key, refs, {"nodes": 1, "walltime_s": 3000}))
            except ResearchDBError as exc:
                results.append(exc)
        import threading
        threads = [threading.Thread(target=go, args=a) for a in (("a", r1), ("b", r2))]
        for th in threads:
            th.start()
        for th in threads:
            th.join()
        self.assertEqual(sum(isinstance(r, dict) for r in results), 1)
        self.assertTrue(any(isinstance(r, ResearchDBError) and "BUDGET_EXCEEDED" in str(r) for r in results))

    def test_b04_b07_release_rules(self):
        _, refs = self.planned(1)
        self.worker.reserve_submission("k1", refs, {"nodes": 1, "walltime_s": 500})
        self.worker.release_reservation("k1", "decided not to run")  # never claimed: safe
        self.worker.reserve_submission("k2", refs, {"nodes": 1, "walltime_s": 500})
        self.worker.claim_submission("k2")
        with self.assertRaisesRegex(ResearchDBError, "SUBMISSION_AMBIGUOUS: .*releasing needs the user's"):
            self.worker.release_reservation("k2", "executor crashed")  # B04/B07: the job may exist
        # B04: the claimer crashed before submitting; after checking the scheduler, reclaim the same intent
        self.assertEqual(self.worker.claim_submission("k2", reclaim=True)["claim_generation"], 2)
        user = self.doc(ResearchDB(self.db, "ui/ui"), "instructions/UI-3000.v1.md", "user_instruction")
        self.worker.release_reservation("k2", "user checked: nothing was submitted", user)
        self.assertEqual(self.rld.budget_status()["open_reservations"], [])

    def test_b08_b09_overrun_is_recorded_and_pauses_admission(self):
        _, refs = self.planned(1)
        run = refs[0].rpartition("@")[0]
        self.worker.reserve_submission("k1", refs, {"nodes": 1, "walltime_s": 600})
        gen = self.worker.claim_submission("k1")["claim_generation"]
        self.worker.update_run(run, exec_status="submitted")
        self.worker.attach_job("k1", "job-1", gen)
        self.worker.update_run(run, exec_status="failed")  # B09: a failure costs too
        res = self.worker.reconcile_submission("k1")["reservation_id"]
        settled = self.worker.settle_reservation(res, self.accounting("o1", "job-1", 2000))
        self.assertEqual((settled["actual_units"], settled["overrun"]), (2000, True))
        status = self.rld.budget_status()
        self.assertIn("used 2000", status["admission_paused"])
        self.assertEqual(status["committed"]["total"], 5400 + 2000)
        _, refs2 = self.planned(1)
        with self.assertRaisesRegex(ResearchDBError, "BUDGET_EXCEEDED: admission is paused"):
            self.worker.reserve_submission("k2", refs2, {"nodes": 1, "walltime_s": 100})
        user = self.doc(ResearchDB(self.db, "ui/ui"), "instructions/UI-3100.v1.md", "user_instruction")
        self.rld.resume_admission(user)
        self.worker.reserve_submission("k2", refs2, {"nodes": 1, "walltime_s": 100})

    def test_b12_settlement_waits_for_the_job_and_b14_pools(self):
        _, refs = self.planned(1)
        run = refs[0].rpartition("@")[0]
        self.worker.reserve_submission("k1", refs, {"nodes": 1, "walltime_s": 3500})
        gen = self.worker.claim_submission("k1")["claim_generation"]
        self.worker.update_run(run, exec_status="submitted")
        self.worker.attach_job("k1", "job-9", gen)
        res = self.worker.reconcile_submission("k1")["reservation_id"]
        with self.assertRaisesRegex(ResearchDBError, "runs not final yet"):  # B12: no zero-cost settlement
            self.worker.settle_reservation(res, self.accounting("b", "job-9", 10))
        # B14: the search budget is spent (5400 + 3500 of 9000); the confirmation part is still there
        _, refs2 = self.planned(1)
        with self.assertRaisesRegex(ResearchDBError, "BUDGET_EXCEEDED: .*search budget"):
            self.worker.reserve_submission("k2", refs2, {"nodes": 1, "walltime_s": 200})
        self.worker.reserve_submission("k2", refs2, {"nodes": 1, "walltime_s": 200, "budget_pool": "confirmation"})
        self.assertEqual(self.rld.budget_status()["available"]["confirmation"], 3400)

    def test_caps_are_raised_only_by_the_user(self):
        self.rld.update_project(total_limit=12000)  # lowering a cap is allowed
        for change in ({"total_limit": 20000}, {"search_limit": None}, {"max_nodes": 99}):
            with self.subTest(change=change), self.assertRaisesRegex(ResearchDBError, "BUDGET_EXCEEDED: raising"):
                self.rld.update_project(**change)
        user = self.doc(ResearchDB(self.db, "ui/ui"), "instructions/UI-3200.v1.md", "user_instruction")
        self.rld.update_project(total_limit=20000, user_instruction_doc_id=user)
        self.assertEqual(self.rld.budget_status()["limits"]["total"], 20000)

    def test_reservation_covers_the_registered_request(self):
        _, refs = self.planned(3)  # 3 runs of 1 node x 100 s
        with self.assertRaisesRegex(ResearchDBError, "BUDGET_EXCEEDED: the request .* is smaller"):
            self.worker.reserve_submission("k1", refs, {"nodes": 1, "walltime_s": 200})
        self.assertEqual(self.worker.reserve_submission("k1", refs, {"nodes": 1, "walltime_s": 300})["reserved_units"], 300)

    def test_submit_timeout_before_submitted_is_unknown(self):
        _, refs = self.planned(1)
        run = refs[0].rpartition("@")[0]
        self.worker.reserve_submission("k1", refs, {"nodes": 1, "walltime_s": 100})
        with self.assertRaisesRegex(ResearchDBError, "only under a reservation"):  # intent: nothing was submitted
            self.worker.update_run(run, exec_status="unknown")
        self.worker.claim_submission("k1")
        self.worker.update_run(run, exec_status="unknown")  # the submit call timed out: maybe the scheduler has it
        self.assertEqual(self.worker.reconcile_submission("k1")["accounting_status"], "held_unknown")

    def test_released_reservation_does_not_hide_usage(self):
        _, refs = self.planned(1)
        self.worker.reserve_submission("k1", refs, {"nodes": 1, "walltime_s": 100})
        self.worker.release_reservation("k1", "decided not to run")
        before = self.rld.budget_status()["committed"]["total"]
        self.worker.update_run(refs[0].rpartition("@")[0], nodes_used=1, walltime_used_s=50)
        self.assertEqual(self.rld.budget_status()["committed"]["total"], before + 50)

    def test_b11_session_restart_keeps_the_attempt(self):
        _, refs = self.planned(1)
        run = refs[0].rpartition("@")[0]
        self.worker.reserve_submission("k1", refs, {"nodes": 1, "walltime_s": 500})
        self.worker.claim_submission("k1")
        self.worker.update_run(run, exec_status="submitted")
        # a new session of the same worker reads the run: same attempt, same key, nothing to resubmit
        again = ResearchDB(self.db, "worker/w1").reconcile_submission("k1")
        self.assertEqual((self.rld.get(run)["attempt"], again["submission_phase"]), (1, "claimed"))
        self.assertIn("query it by the submission key", again["next"])


class CostEstimateTest(Fixture):
    """X04, X08: experiments carry a cost estimate; an overrun is an attention item, the job is not cancelled."""

    def test_same_configuration_is_not_run_twice(self):
        h = self.hypothesis()
        self.start(h)
        design = self.doc(self.worker, "exp/dd.v1.md", "experiment_design")
        code = self.commit()
        first = self.worker.create_experiment("method", "m", design, code, 1, 60, hypothesis_id=h, n_seeds=1,
                                              estimated_node_h=0.1)
        again = self.worker.create_experiment("method", "m", design, code, 1, 60, hypothesis_id=h, n_seeds=1,
                                              estimated_node_h=0.1)
        other = self.worker.create_experiment("method", "m", design, code, 1, 90, hypothesis_id=h, n_seeds=1,
                                              estimated_node_h=0.1)
        self.assertEqual((again, other != first), (first, True))

    def test_x04(self):
        h = self.hypothesis()
        self.start(h)
        design = self.doc(self.worker, "exp/x04.v1.md", "experiment_design")
        with self.assertRaisesRegex(ResearchDBError, "estimated_node_h .* is required"):
            self.worker.create_experiment("method", "m", design, self.commit(), 1, 60, hypothesis_id=h)

    def test_x08(self):
        import build_site
        h = self.hypothesis()
        self.start(h)
        design = self.doc(self.worker, "exp/x08.v1.md", "experiment_design")
        exp = self.worker.create_experiment("method", "m", design, self.commit(), 1, 1800, hypothesis_id=h,
                                            estimated_node_h=0.2)
        self.finish_runs(self.worker, exp, effect=(self.sota, (0.3, 0.1, 0.1)))  # 3 x 600 s = 0.5 node-h
        kinds = {(a["kind"], a["id"]) for a in build_site.build(self.db, self.root / "site" / "index.html")["attention"]}
        self.assertIn(("overrun", h), kinds)
        self.assertEqual(self.rld.get(f"{exp}/s42")["exec_status"], "succeeded")


class SchemaUpgradeTest(unittest.TestCase):
    """10 §2.5: a database of the previous schema is refused for writing until upgraded; reads still work."""

    def test_v6_database(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "research" / "P-old"
            (root / "docs").mkdir(parents=True)
            db = root / "research_tree.db"
            create_db.create_db(db)
            with Database(db) as d, d.write() as txn:  # what version 6 wrote
                txn.set_property(txn.get_nodes_by_label("Meta")[0], "schema_version", 6)
                txn.commit()
            rld = ResearchDB(db, "rld/main")
            self.assertEqual(rld.find("project"), [])
            setup = root / "docs" / "s.v1.md"
            setup.write_text("x")
            with self.assertRaisesRegex(ResearchDBError, "schema_version 6.*--upgrade"):
                rld.register_document("s.v1.md", "min_setup", "s")
            self.assertEqual(create_db.upgrade_db(db), 6)
            rld.register_document("s.v1.md", "min_setup", "s")
            self.assertEqual(create_db.upgrade_db(db), 9)  # nothing more to do
            self.assertEqual(rdb.SCHEMA_VERSION, create_db.SCHEMA_VERSION)


class V6MigrationTest(Fixture):
    """10 §2: a database shaped like schema 6 (evaluated experiments, no evaluations, no specification), upgraded
    and migrated."""

    def test_upgrade_and_migrate(self):
        h = self.hypothesis()
        self.start(h)
        exp = self.method(h)
        self.evaluate(exp, "beats_sota")
        with Database(self.db) as d, d.write() as txn:  # what version 6 left behind
            for ev in txn.get_nodes_by_label("Evaluation"):
                for edge in txn.get_outgoing_edges(ev):
                    txn.delete_edge(ev, edge.target_id, edge.edge_type)
                txn.delete_node(ev)
            tx = rdb._Tx(txn)
            for e in (exp, self.sota):
                txn.set_property(tx.node_id(e), "evaluation_id", None)
            txn.set_property(tx.node_id("P-test"), "metric_spec_doc_id", None)
            txn.set_property(tx.node_id("P-test"), "protocol_doc_id", None)
            txn.set_property(txn.get_nodes_by_label("Meta")[0], "schema_version", 6)
            txn.commit()
        with self.assertRaisesRegex(ResearchDBError, "schema_version 6"):
            self.rld.migrate_evaluations(dry_run=False)
        self.assertEqual(create_db.upgrade_db(self.db), 6)
        report = self.rld.migrate_evaluations(dry_run=False)
        self.assertEqual(sorted(r["experiment_id"] for r in report["recorded"]), sorted([exp, self.sota]))
        ev = self.rld.evaluations(experiment_id=exp)[-1]
        self.assertEqual((ev["verification_level"], ev["migrated"]), ("legacy_unverified", True))
        self.rld.decide(h, {"experiment_status": "beats_sota"}, "gate", based_on=[exp])
        self.recheck_pass(h, exp)
        self.assertIn("LEGACY_RESULT_UNVERIFIED", self.rld.get_eligibility(h)["reasons"])


class DocumentNumbersTest(Fixture):
    """05 §2.4: an experiment result's numbers must appear in the files it cites."""

    def write(self, name: str, body: str) -> str:
        path = self.root / "docs" / "results" / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(body)
        return self.worker.register_document(f"results/{name}", "experiment_result", "r")

    def test_result_claims(self):
        (self.root / "outputs").mkdir(exist_ok=True)
        (self.root / "outputs" / "m.json").write_text('{"accuracy": 0.9075}')
        none = self.write("a.v1.md", "acc 0.9075\n")
        with self.assertRaisesRegex(ResearchDBError, "STAT_MISMATCH: .*cites no numbers"):
            self.worker.set_document_current(none)
        wrong = self.write("b.v1.md", '```evidence\n[{"id": "acc", "value": "0.91", "source": "outputs/m.json"}]\n```\n')
        with self.assertRaisesRegex(ResearchDBError, "STAT_MISMATCH: .*acc '0.91' in 'outputs/m.json': value_not_found"):
            self.worker.set_document_current(wrong)
        missing = self.write("c.v1.md", '```evidence\n[{"id": "acc", "value": "0.9075", "source": "outputs/n.json"}]\n```\n')
        with self.assertRaisesRegex(ResearchDBError, "path_missing"):
            self.worker.set_document_current(missing)
        outside = self.write("d.v1.md", '```evidence\n[{"id": "h", "value": "1", "source": "/etc/hostname"}]\n```\n')
        with self.assertRaisesRegex(ResearchDBError, "path_missing"):
            self.worker.set_document_current(outside)
        good = self.write("e.v1.md", '```evidence\n[{"id": "acc", "value": "0.9075", "source": "outputs/m.json"}]\n```\n')
        self.worker.set_document_current(good)
        self.assertEqual(self.rld.get(good)["status"], "current")

    def test_report_claims_checked_when_present(self):
        (self.root / "outputs").mkdir(exist_ok=True)
        (self.root / "outputs" / "m.json").write_text('{"delta": 0.21}')
        plain = self.doc(self.rld, "reports/plain.v1.md", "report")  # no block: a narrative report
        self.assertEqual(self.rld.get(plain)["status"], "current")
        path = self.root / "docs" / "reports" / "go.v1.md"
        path.write_text('GO\n```evidence\n[{"id": "d", "value": "0.3", "source": "outputs/m.json"}]\n```\n')
        doc = self.rld.register_document("reports/go.v1.md", "report", "go")
        with self.assertRaisesRegex(ResearchDBError, "STAT_MISMATCH"):
            self.rld.set_document_current(doc)

    def test_metric_spec_and_protocol_documents_are_checked(self):
        bad = self.root / "docs" / "project" / "metric-spec.v9.json"
        bad.write_text(json.dumps({"version": 1, "primary": "acc", "metrics": [{"name": "acc"}]}))
        doc = self.rld.register_document("project/metric-spec.v9.json", "metric_spec", "bad")
        with self.assertRaisesRegex(ResearchDBError, "METRIC_UNIT_MISMATCH: metric acc: missing"):
            self.rld.set_document_current(doc)
        wrong = self.doc(self.rld, "project/metric-spec.v8.json", "metric_spec",
                         body=json.dumps({**SPECS, "metrics": SPECS["metrics"][:2]}))
        instruction = self.doc(ResearchDB(self.db, "ui/ui"), "instructions/UI-0400.v1.md", "user_instruction")
        with self.assertRaisesRegex(ResearchDBError, "must specify exactly the project's metrics"):
            self.rld.update_project(metric_spec_doc_id=wrong, user_instruction_doc_id=instruction)
        proto = self.root / "docs" / "project" / "protocol.v9.json"
        proto.write_text(json.dumps({"version": 1, "eval_type": "vibes"}))
        doc = self.rld.register_document("project/protocol.v9.json", "protocol", "bad")
        with self.assertRaisesRegex(ResearchDBError, "PROTOCOL_CHANGE_REQUIRED: protocol eval_type"):
            self.rld.set_document_current(doc)


class LegacyTest(Fixture):
    """10 §2: a project without a metric specification, and evaluations recorded before evaluations existed."""

    def test_legacy_project_and_migration(self):
        project = self.rld.get("P-test")
        self.raw("P-test", metric_spec_doc_id=None, protocol_doc_id=None)  # an old project: no documents
        self.worker.evaluate_experiment(self.sota, self.result_doc(exp=self.sota))  # its baseline, evaluated the old way
        h = self.hypothesis()
        self.start(h)
        exp = self.method(h)
        self.finish_runs(self.worker, exp, effect=(self.sota, (0.3, 0.1, 0.1)))
        with self.assertRaisesRegex(ResearchDBError, "deltas must give a number for each of"):
            self.worker.record_verdict(exp, self.result_doc(exp=exp), None, None, "beats_sota",
                                       [{**self.comparisons(exp, (0.3, 0.1, 0.1))[0], "deltas": {"final_loss": 0.1}}])
        self.worker.record_verdict(exp, self.result_doc(exp=exp), None, None, "beats_sota", self.comparisons(exp, (0.3, 9.0, 9.0)))
        ev = self.rld.evaluations(experiment_id=exp)[-1]
        self.assertEqual(ev["verification_level"], "legacy_unverified")
        self.assertEqual(self.rld.edges("rel_compared_with", source_id=exp)[0]["deltas"],
                         {"final_loss": 9.0, "peak_mem_gb": 9.0})  # the caller's: no direction is known
        self.rld.decide(h, {"experiment_status": "beats_sota"}, "gate", based_on=[exp])
        self.recheck_pass(h, exp)
        self.assertEqual(self.rld.get_eligibility(h)["reasons"], ["LEGACY_RESULT_UNVERIFIED"])
        self.assertTrue(project["metric_spec_doc_id"])  # what the raw change removed

    def test_shadow_migration(self):
        h = self.hypothesis()
        self.start(h)
        exp = self.method(h)
        self.evaluate(exp, "beats_sota")
        h2 = self.hypothesis()
        self.start(h2)
        bad = self.method(h2)
        self.evaluate(bad, "beats_sota")
        # Records written before evaluations existed: no evaluation, and one with a summary its runs do not give.
        for e in (exp, bad, self.sota):
            self.raw(e, evaluation_id=None)
        self.raw(bad, metric_mean=71.5)
        report = self.rld.migrate_evaluations()
        self.assertEqual(sorted(report["consistent"]), sorted([exp, self.sota]))
        self.assertEqual([m["experiment_id"] for m in report["mismatched"]], [bad])
        self.assertIn("STAT_MISMATCH", report["mismatched"][0]["error"])
        self.assertEqual(report["recorded"], [])  # dry run
        done = self.rld.migrate_evaluations(dry_run=False)
        self.assertEqual(sorted(r["experiment_id"] for r in done["recorded"]), sorted([exp, self.sota]))
        self.assertEqual(self.rld.get(bad)["metric_mean"], 71.5)  # nothing recorded for it, nothing changed
        self.assertTrue(self.rld.get(exp)["evaluation_id"].startswith("EV-"))
        migrated = self.rld.evaluations(experiment_id=exp)[-1]
        self.assertEqual(migrated["baseline_evaluation_id"], self.rld.get(self.sota)["evaluation_id"])  # in order
        self.assertTrue(migrated["migrated"])
        reasons = self.rld.get_eligibility(h)["reasons"]
        self.assertIn("LEGACY_RESULT_UNVERIFIED", reasons)
        self.assertNotIn("BASELINE_CHANGED", reasons)
        self.worker.evaluate_experiment(exp, self.result_doc(exp=exp), "beats_sota")  # evaluated again under the new rules
        self.assertNotIn("LEGACY_RESULT_UNVERIFIED", self.rld.get_eligibility(h)["reasons"])
        with self.assertRaises(PermissionDenied):
            self.worker.migrate_evaluations()


class EvidenceCleanupTest(Fixture):
    """K08: files an evaluation is recomputed from are evidence; the cleanup may not delete them."""

    def test_k08(self):
        h = self.hypothesis()
        self.start(h)
        exp = self.method(h, n_seeds=1)
        self.imported(exp, effect=(self.sota, (0.3, 0.1, 0.1)), evidence_paths=["predictions.jsonl"])
        run_dir = self.root / "outputs" / exp / "s42"
        self.worker.evaluate_experiment(exp, self.result_doc(exp=exp), "beats_parent")
        shutil.copyfile(rdb.CLEANUP_TEMPLATE, Path(self.tmp.name) / rdb.CLEANUP_SCRIPT)
        script = Path(self.tmp.name) / rdb.CLEANUP_SCRIPT
        for name in ("predictions.jsonl", "metrics.json", "manifest.json"):
            script.write_text(textwrap.dedent(f"""\
                import json, sys
                request = json.load(sys.stdin)
                run = request["runs"][0]
                items = [{{"run": run["run"], "path": run["output_dir"] + "/{name}", "class": "predictions", "bytes": 1}}]
                print(json.dumps({{"items": items if sys.argv[1] == "plan" else []}}))
                """))
            with self.subTest(name=name), self.assertRaisesRegex(ResearchDBError, "holds evidence"):
                self.worker.run_cleanup(exp)
        self.assertTrue((run_dir / "predictions.jsonl").exists())

    def test_cited_sources_are_evidence(self):
        h = self.hypothesis()
        self.start(h)
        exp = self.method(h, n_seeds=1)
        self.finish_runs(self.worker, exp, effect=(self.sota, (0.3, 0.1, 0.1)))
        run_dir = self.root / "outputs" / exp / "s42"
        run_dir.mkdir(parents=True, exist_ok=True)
        (run_dir / "scores.tmp").write_text('{"acc": 70.3}')  # a statistics output named like scratch
        doc = self.result_doc(exp=exp, extra=[{"id": "acc-s42", "value": "70.3", "source": f"outputs/{exp}/s42/scores.tmp"}])
        self.worker.evaluate_experiment(exp, doc, "beats_parent")
        shutil.copyfile(rdb.CLEANUP_TEMPLATE, Path(self.tmp.name) / rdb.CLEANUP_SCRIPT)
        self.assertEqual(self.worker.run_cleanup(exp, dry_run=True)["items"], [])  # the template leaves it
        (Path(self.tmp.name) / rdb.CLEANUP_SCRIPT).write_text(textwrap.dedent("""\
            import json, sys
            request = json.load(sys.stdin)
            run = request["runs"][0]
            items = [{"run": run["run"], "path": run["output_dir"] + "/scores.tmp", "class": "scratch", "bytes": 1}]
            print(json.dumps({"items": items if sys.argv[1] == "plan" else []}))
            """))
        with self.assertRaisesRegex(ResearchDBError, "holds evidence"):
            self.worker.run_cleanup(exp)
        self.assertTrue((run_dir / "scores.tmp").exists())


class CleanupTest(Fixture):
    def setUp(self):
        super().setUp()
        self.h = self.hypothesis()
        self.start(self.h)
        self.script = Path(self.tmp.name) / rdb.CLEANUP_SCRIPT

    def test_outputs_go_once_the_statistics_are_recorded(self):
        exp = self.method(self.h)
        self.outputs(exp)
        with self.assertRaisesRegex(ResearchDBError, "no cleanup due"):
            self.worker.run_cleanup(exp)
        task = self.rld.create_task("experiment", "worker", self.doc(self.rld, "tasks/c/request.v1.md", "task_request"),
                                    target_id=self.h, assignee_id="w1")
        self.worker.update_task(task, status="in_progress")
        self.evaluate(exp, "beats_parent", sota=(0.01, 0.0, 0.0))
        self.assertEqual([d["experiment_id"] for d in self.rld.cleanup_due(self.h)], [exp])
        delivery = self.doc(self.worker, "tasks/c/delivery.v1.md", "task_delivery")
        with self.assertRaisesRegex(ResearchDBError, f"clean up first: {exp}"):
            self.worker.update_task(task, status="delivered", delivery_doc_id=delivery)
        with self.assertRaisesRegex(ResearchDBError, "copied the cleanup template"):
            self.worker.run_cleanup(exp)
        self.assertEqual(self.script.read_text(), rdb.CLEANUP_TEMPLATE.read_text())  # the project's copy from now on
        with self.assertRaises(PermissionDenied):
            ResearchDB(self.db, "worker/w2").run_cleanup(exp)
        run_dir = self.root / "outputs" / exp / "s42"
        preview = self.worker.run_cleanup(exp, dry_run=True)
        self.assertEqual(sorted({i["class"] for i in preview["items"]}), ["final_weights", "optimizer_state", "periodic_ckpt"])
        self.assertTrue((run_dir / "model.safetensors").exists())  # a preview deletes nothing
        done = self.worker.run_cleanup(exp)
        self.assertEqual(sorted(p.name for p in run_dir.iterdir()), ["metrics.json", "train.log"])
        self.assertEqual(done["freed_bytes"], 3 * 160)
        ledger = self.rld.get(exp)["cleanup"]
        self.assertEqual((list(ledger), ledger["1"]["by"], ledger["1"]["failed"]), (["1"], "worker/w1", 0))
        self.assertEqual(self.rld.cleanup_due(self.h), [])
        self.worker.update_task(task, status="delivered", delivery_doc_id=delivery)

    def test_new_seeds_are_due_again_however_soon_they_are_evaluated(self):
        exp = self.method(self.h, n_seeds=1)
        self.evaluate(exp, "close", sota=(0.01, 0.0, 0.0))
        self.clean_all()
        self.assertEqual(self.rld.cleanup_due(self.h), [])
        self.worker.extend_seeds(exp, 3)
        self.finish_runs(self.worker, exp)
        self.evaluate(exp, "beats_parent", sota=(0.01, 0.0, 0.0))  # within the same second as the first cleanup
        self.assertEqual([d["experiment_id"] for d in self.rld.cleanup_due(self.h)], [exp])
        self.clean_all()
        self.assertEqual(self.rld.get(exp)["cleanup"]["2"]["covered"], [f"{exp}/s{s}@1" for s in SEEDS])
        self.assertEqual(self.rld.cleanup_due(self.h), [])

    def test_the_project_script_may_not_touch_evidence_or_leave_the_run(self):
        exp = self.method(self.h, n_seeds=1)
        self.outputs(exp)
        self.evaluate(exp, "beats_parent", sota=(0.01, 0.0, 0.0))
        # The project may rewrite its script; whatever it plans is checked before anything is deleted.
        for planned, problem in (("{d}/train.log", "holds evidence"), ("{d}", "outside the run's output directory"),
                                 ("/etc/passwd", "outside the run's output directory")):
            self.script.write_text(textwrap.dedent(f"""\
                import json, sys
                request = json.load(sys.stdin)
                run = request["runs"][0]
                path = {planned!r}.format(d=run["output_dir"])
                items = [{{"run": run["run"], "path": path, "class": "scratch", "bytes": 1}}]
                print(json.dumps({{"items": items if sys.argv[1] == "plan" else []}}))
                """))
            with self.subTest(planned=planned), self.assertRaisesRegex(ResearchDBError, f"which is {problem}"):
                self.worker.run_cleanup(exp)
        self.assertTrue((self.root / "outputs" / exp / "s42" / "train.log").exists())

    def test_kept_outputs_wait_until_the_node_is_pruned_and_their_users_are_evaluated(self):
        design = self.doc(self.worker, "exp/keep.v1.md", "experiment_design")
        with self.assertRaisesRegex(ResearchDBError, "keep needs keep_reason"):
            self.worker.create_experiment("method", "m", design, self.commit(), 1, 1800, hypothesis_id=self.h,
                                          keep=["final_weights"], estimated_node_h=1.0)
        exp = self.worker.create_experiment("method", "m", design, self.commit(), 1, 1800, hypothesis_id=self.h,
                                            keep=["final_weights"], keep_reason="the next experiment trains on from them", estimated_node_h=1.0)
        self.finish_runs(self.worker, exp)
        self.outputs(exp)
        self.evaluate(exp, "no_gain", sota=(-0.1, -0.1, -0.1))
        self.clean_all()
        weights = self.root / "outputs" / exp / "s42" / "model.safetensors"
        self.assertTrue(weights.exists())
        self.assertFalse((self.root / "outputs" / exp / "s42" / "optimizer.pt").exists())
        user = self.method(self.h)
        self.worker.link("rel_depends_on", user, exp, artifact="final_weights")
        self.evaluate(user, "no_gain", sota=(-0.1, -0.1, -0.1))
        self.rld.decide(self.h, {"experiment_status": "no_gain", "status": "prunable"}, "no gain",
                        doc_id=self.decision_doc(), based_on=[user], reconsider_when="new evidence on the mechanism")
        due = {d["experiment_id"]: d["reason"] for d in self.rld.cleanup_due(self.h)}
        self.assertEqual(due, {exp: "kept outputs released", user: "statistics recorded"})
        self.clean_all()
        self.assertFalse(weights.exists())
        self.assertEqual(self.rld.get(exp)["cleanup"]["2"]["kept"], [])


class WorkerTest(Fixture):
    def test_assignment(self):
        h = self.hypothesis()
        self.assertEqual(self.rld.assign_worker(h), h.replace("-", "").lower())
        self.assertEqual(self.rld.assign_worker(h), "h0001")  # idempotent
        with self.assertRaisesRegex(ResearchDBError, "already belongs to worker/h0001"):
            self.rld.assign_worker(h, "other")
        self.assertEqual(self.rld.assign_worker("P-test"), "root")
        h2 = self.hypothesis()
        with self.assertRaisesRegex(ResearchDBError, "already works on"):
            self.rld.assign_worker(h2, "h0001")
        with self.assertRaisesRegex(ResearchDBError, "letters, digits"):
            self.rld.assign_worker(h2, "bad/id")
        with self.assertRaises(PermissionDenied):
            self.worker.assign_worker(h2)

    def test_sessions_and_ownership(self):
        h = self.hypothesis()
        with self.assertRaisesRegex(ResearchDBError, "assign H-0001 a worker"):
            self.rld.bind_worker_session(h, "agent-1")
        wid = self.rld.assign_worker(h)
        self.rld.bind_worker_session(h, "agent-1")
        first = self.rld.get(h)
        self.assertEqual((first["worker_agent_id"], bool(first["worker_session_at"])), ("agent-1", True))
        self.rld.bind_worker_session(h, "agent-2")  # a new session takes over under the same identity
        self.assertEqual(self.rld.get(h)["worker_agent_id"], "agent-2")

        br = self.rld.create_branch(h, f"node/{h}", "main", self.harness, str(Path(self.tmp.name) / "wt"))
        self.assertEqual(self.rld.get(br)["owner"], wid)  # the node's worker owns its branch
        self.rld.decide(h, {"experiment_status": "running", "status": "verifying"}, "start", doc_id=self.decision_doc())
        own = ResearchDB(self.db, f"worker/{wid}")
        design = self.doc(own, "exp/w/design.v1.md", "experiment_design")
        with self.assertRaisesRegex(PermissionDenied, f"worker/{wid}'s node"):
            self.worker.create_experiment("method", "m", design, self.commit(), 1, 60, hypothesis_id=h, estimated_node_h=1.0)
        exp = own.create_experiment("method", "m", design, self.commit(), 1, 60, hypothesis_id=h, estimated_node_h=1.0)
        self.assertEqual(self.rld.get(exp)["owner"], wid)

    def test_resume_documents(self):
        h = self.hypothesis()
        hyp_doc = self.rld.get(h)["doc_id"]
        self.assertEqual(self.rld.get(h)["resume_doc_ids"], [hyp_doc])
        self.assertEqual(self.rld.get("P-test")["resume_doc_ids"], ["D-0001"])  # the root starts with the setup
        wid = self.rld.assign_worker(h)
        own = ResearchDB(self.db, f"worker/{wid}")
        req = self.doc(self.rld, "tasks/t/request.v1.md", "task_request")
        task = self.rld.create_task("experiment", "worker", req, target_id=h, assignee_id=wid)
        own.update_task(task, status="in_progress")
        delivery = self.doc(own, "tasks/t/delivery.v1.md", "task_delivery")
        own.update_task(task, status="delivered", delivery_doc_id=delivery)
        note = self.doc(own, "h/notes/n.v1.md", "experiment_design")
        own.add_resume_docs(h, [note])
        with self.assertRaises(PermissionDenied):
            self.worker.add_resume_docs(h, [note])
        self.assertEqual(self.rld.get(h)["resume_doc_ids"], [hyp_doc, req, delivery, note])

        # The package resolves a superseded document to its current version.
        new = self.doc(self.rld, f"h/{h}/hypothesis.v2.md", "hypothesis")
        self.rld.supersede_document(hyp_doc, new)
        package = self.rld.resume_package(h)
        self.assertEqual(package["worker"], f"worker/{wid}")
        self.assertEqual(package["documents"][0]["id"], new)
        self.assertEqual(package["documents"][0]["listed_as"], hyp_doc)
        self.assertEqual([d["id"] for d in package["documents"][1:]], [req, delivery, note])
        self.assertEqual(package["tasks"][0]["id"], task)
        self.assertEqual(package["experiments"], [])
        root = self.rld.resume_package("P-test")
        self.assertEqual([b["id"] for b in root["baselines"]], [self.sota])


class DocumentTest(Fixture):
    def test_paths_roles_and_freeze(self):
        (self.root / "docs" / "a.md").write_text("x", encoding="utf-8")
        for path in ("a.md", "/abs/a.v1.md", "x/../a.v1.md"):
            with self.subTest(path=path), self.assertRaisesRegex(ResearchDBError, "document path"):
                self.rld.register_document(path, "other", "t")
        with self.assertRaisesRegex(ResearchDBError, "not found"):
            self.rld.register_document("missing.v1.md", "other", "t")
        (self.root / "docs" / "h.v1.md").write_text("x", encoding="utf-8")
        for doc_type in ("hypothesis", "novelty"):
            with self.subTest(doc_type=doc_type), self.assertRaises(PermissionDenied):
                self.worker.register_document("h.v1.md", doc_type, "t")
        doc = self.worker.register_document("h.v1.md", "literature", "t")
        self.assertEqual(self.rld.get(doc)["version"], 1)
        with self.assertRaisesRegex(ResearchDBError, "already registered"):
            self.worker.register_document("h.v1.md", "literature", "t")
        with self.assertRaises(PermissionDenied):
            ResearchDB(self.db, "assistant/a1").set_document_current(doc)
        self.worker.update_document(doc, summary="draft edit")
        self.worker.set_document_current(doc)
        with self.assertRaisesRegex(ResearchDBError, "write a new version"):
            self.worker.update_document(doc, summary="late edit")
        self.assertTrue(self.rld.verify_document(doc))
        (self.root / "docs" / "h.v1.md").write_text("tampered", encoding="utf-8")
        self.assertFalse(self.rld.verify_document(doc))

    def test_supersede(self):
        h = self.hypothesis()
        old = self.rld.get(h)["doc_id"]
        new = self.doc(self.rld, f"h/{h}/hypothesis.v2.md", "hypothesis")
        self.rld.supersede_document(old, new)
        self.assertEqual(self.rld.get(old)["status"], "superseded")
        self.assertEqual(self.rld.edges("rel_supersedes", source_id=new), [{"source_id": new, "target_id": old}])
        with self.assertRaisesRegex(ResearchDBError, "superseded"):
            self.rld.update_hypothesis(h, doc_id=old)
        self.rld.update_hypothesis(h, doc_id=new)


class TaskTest(Fixture):
    def test_lifecycle(self):
        h = self.hypothesis()
        req = self.doc(self.rld, "tasks/t/request.v1.md", "task_request")
        task = self.rld.create_task("experiment", "worker", req, target_id=h, assignee_id="w1")
        with self.assertRaisesRegex(ResearchDBError, "must be one of"):
            self.rld.create_task("review", "worker", req)
        with self.assertRaises(PermissionDenied):
            ResearchDB(self.db, "worker/w2").update_task(task, status="in_progress")
        self.worker.update_task(task, status="in_progress")
        draft = self.doc(self.worker, "tasks/t/delivery.v1.md", "task_delivery", current=False)
        with self.assertRaisesRegex(ResearchDBError, "needs delivery_doc_id"):
            self.worker.update_task(task, status="delivered")
        with self.assertRaisesRegex(ResearchDBError, "expected a current document"):
            self.worker.update_task(task, status="delivered", delivery_doc_id=draft)
        self.worker.set_document_current(draft)
        self.worker.update_task(task, status="delivered", delivery_doc_id=draft)
        with self.assertRaisesRegex(ResearchDBError, r"from delivered: accepted \(rld\), rejected \(rld\)"):
            self.worker.update_task(task, status="delivered", delivery_doc_id=draft)
        with self.assertRaises(PermissionDenied):
            self.worker.update_task(task, status="accepted")
        with self.assertRaisesRegex(ResearchDBError, "needs evidence_ids"):
            self.rld.update_task(task, status="accepted")
        self.rld.update_task(task, status="accepted", evidence_ids=[self.sota])
        self.assertEqual(self.rld.get(task)["accepted_by"], "rld/main")
        self.assertEqual(self.rld.find("task", target_id=h)[0]["status"], "accepted")

    def test_task_documents_have_their_sections(self):
        def bare(path: str, doc_type: str, actor: ResearchDB, text: str) -> str:
            (self.root / "docs" / path).parent.mkdir(parents=True, exist_ok=True)
            (self.root / "docs" / path).write_text(text, encoding="utf-8")
            doc_id = actor.register_document(path, doc_type, "t")
            actor.set_document_current(doc_id)
            return doc_id
        partial = bare("tasks/s/request.v1.md", "task_request", self.rld, "## 任务与节点\n\nH-0001\n\n## 交付（位置）\n\nx\n")
        with self.assertRaisesRegex(ResearchDBError, "lacks the sections 问题与预测, 干预与对照, 范围与权限, 资源与预算, "
                                                     "验收与停止条件; a task_request"):
            self.rld.create_task("analysis", "worker", partial, assignee_id="w1")
        task = self.rld.create_task("analysis", "worker", self.doc(self.rld, "tasks/s/request.v2.md", "task_request"),
                                    assignee_id="w1")
        self.worker.update_task(task, status="in_progress")
        thin = bare("tasks/s/delivery.v1.md", "task_delivery", self.worker, "done\n")
        with self.assertRaisesRegex(ResearchDBError, "lacks the sections 实际改动与版本"):
            self.worker.update_task(task, status="delivered", delivery_doc_id=thin)

    def test_parallel_workers(self):
        req = self.doc(self.rld, "tasks/t/request.v1.md", "task_request")
        with self.assertRaisesRegex(ResearchDBError, "positive or null"):
            self.rld.update_project(max_parallel_workers=0)
        self.rld.update_project(max_parallel_workers=2)
        self.rld.create_task("experiment", "worker", req, assignee_id="w1")
        self.rld.create_task("experiment", "worker", req, assignee_id="w2")
        self.rld.create_task("analysis", "worker", req, assignee_id="w1")  # w1 already has a task in hand
        self.rld.create_task("web_build", "web_builder", req, assignee_id="site")  # only workers count
        with self.assertRaisesRegex(ResearchDBError, "max_parallel_workers is 2"):
            self.rld.create_task("experiment", "worker", req, assignee_id="w3")
        waiting = self.rld.create_task("experiment", "worker", req)
        with self.assertRaisesRegex(ResearchDBError, "max_parallel_workers is 2"):
            self.rld.update_task(waiting, assignee_id="w3")
        # A delivery frees w1 only once it has nothing else in hand; clearing the limit lifts it.
        for task in self.rld.find("task", assignee_id="w1"):
            self.worker.update_task(task["id"], status="in_progress")
            self.worker.update_task(task["id"], status="delivered",
                                    delivery_doc_id=self.doc(self.worker, f"tasks/{task['id']}/delivery.v1.md", "task_delivery"))
        self.rld.update_task(waiting, assignee_id="w3")
        self.rld.update_project(max_parallel_workers=None)
        self.assertIsNone(self.rld.get("P-test").get("max_parallel_workers"))
        self.rld.create_task("experiment", "worker", req, assignee_id="w4")


class BranchTest(Fixture):
    def test_return_and_delete(self):
        h = self.hypothesis()
        worktree = Path(self.tmp.name) / "wt"
        worktree.mkdir()
        br = self.rld.create_branch(h, f"node/{h}", "main", self.harness, str(worktree), owner="w1")
        with self.assertRaisesRegex(ResearchDBError, "already has a branch"):
            self.rld.create_branch(h, "x", "main", self.harness, str(worktree), owner="w1")
        head = self.commit()
        with self.assertRaises(PermissionDenied):
            ResearchDB(self.db, "worker/w2").return_branch(br, head)
        self.worker.return_branch(br, head)
        self.assertEqual((self.rld.get(br)["status"], self.rld.get(br)["owner"]), ("returned", "main"))

        exp = self.method(h, code_ref=head)
        doc = self.decision_doc()
        with self.assertRaisesRegex(ResearchDBError, "remove the worktree"):
            self.rld.close_branch(br, "deleted", "pruned", doc)
        worktree.rmdir()
        with self.assertRaisesRegex(ResearchDBError, f"tag exp/{exp}"):
            self.rld.close_branch(br, "deleted", "pruned", doc)
        self.git("tag", f"exp/{exp}", head)
        decision = self.rld.close_branch(br, "deleted", "pruned", doc)
        record = self.rld.get(br)
        self.assertEqual(record["status"], "deleted")
        self.assertNotIn("worktree_path", record)
        self.assertEqual(self.rld.history(br)[0]["id"], decision)


class SessionTest(Fixture):
    def test_write_waits_for_a_short_lock(self):
        holder = subprocess.Popen(
            [sys.executable, "-c", textwrap.dedent(f"""
                import time
                from latticedb import Database
                with Database({str(self.db)!r}) as db:
                    print("held", flush=True)
                    time.sleep(1.0)
            """)],
            stdout=subprocess.PIPE, text=True,
        )
        try:
            self.assertEqual(holder.stdout.readline().strip(), "held")
            self.hypothesis()  # retries until the holder releases
        finally:
            holder.wait()
            holder.stdout.close()
        self.assertEqual(len(self.rld.find("hypothesis")), 1)

    def test_cli(self):
        doc = self.doc(self.rld, "h/cli/hypothesis.v1.md", "hypothesis")
        cmd = [sys.executable, str(REPO / "tools" / "research_db.py"), "--db", str(self.db), "--actor", "rld/main"]
        args = json.dumps({"title": "t", "statement": "s", "doc_id": doc, "related_work": self.literature})
        out = subprocess.run(cmd + ["create_hypothesis", args], capture_output=True, text=True)
        self.assertEqual((out.returncode, json.loads(out.stdout)), (0, {"ok": True, "result": "H-0001"}))
        out = subprocess.run(cmd[:-1] + ["worker/w1", "create_hypothesis", args], capture_output=True, text=True)
        self.assertEqual(out.returncode, 2)
        self.assertIn("PermissionDenied", json.loads(out.stdout)["error"])
        out = subprocess.run(cmd + ["get", '{"id": "H-0001"}'], capture_output=True, text=True)
        self.assertIn("get(entity_id: str)", json.loads(out.stdout)["error"])  # wrong arguments: the signature
        listed = json.loads(subprocess.run(cmd + ["help"], capture_output=True, text=True).stdout)["result"]
        update_task = next(m for m in listed if m["method"] == "update_task")
        self.assertEqual(update_task["parameters"], "(task_id: str, status: str | None = None, "
                         "delivery_doc_id: str | None = None, assignee_id: str | None = None, "
                         "evidence_ids: list[str] | None = None) -> None")
        self.assertEqual([m["method"] for m in listed if not m["summary"]], [])  # every method says what it does
        one = json.loads(subprocess.run(cmd + ["help", '{"method": "create_experiment"}'], capture_output=True,
                                        text=True).stdout)["result"]
        self.assertIn("screening count", one["description"])

    def test_snapshot(self):
        h = self.hypothesis()
        snap = self.rld.export_snapshot()
        self.assertEqual([r["id"] for r in snap["tables"]["hypothesis"]], [h])
        self.assertEqual(snap["tables"]["project"][0]["sota_experiment_id"], self.sota)
        self.assertEqual(snap["meta"]["schema_version"], create_db.SCHEMA_VERSION)
        json.dumps(snap)  # JSON-ready


if __name__ == "__main__":
    unittest.main()
