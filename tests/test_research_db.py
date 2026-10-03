"""Tests for tools/research_db.py. Run: .venv/bin/python -m unittest discover -s tests"""

from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
import tempfile
import textwrap
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent


def load(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


create_db = load("create_db", REPO / "schema" / "create_db.py")
rdb = load("research_db", REPO / "tools" / "research_db.py")
ResearchDB, ResearchDBError, PermissionDenied = rdb.ResearchDB, rdb.ResearchDBError, rdb.PermissionDenied

SEEDS = [42, 43, 44]
SECONDARY = ["final_loss", "peak_mem_gb"]


class Fixture(unittest.TestCase):
    """A project with a frozen harness and an evaluated SOTA baseline (0.5 node-hours per seed)."""

    sota_nodes, sota_walltime_s = 1, 1800

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name) / "research" / "P-test"
        (self.root / "docs").mkdir(parents=True)
        self.db = self.root / "research_tree.db"
        create_db.create_db(self.db)
        self.rld = ResearchDB(self.db, "rld/main")
        self.worker = ResearchDB(self.db, "worker/w1")
        self.n = 0

        self.repo = Path(self.tmp.name) / "code"
        (self.repo / "harness").mkdir(parents=True)
        self.git("init", "-q", "-b", "main")
        self.harness = self.commit({"harness/stats.py": "stats v1\n"})

        setup = self.doc(self.rld, "project/min-setup.v1.md", "min_setup")
        self.rld.create_project("P-test", "test", setup, "acc", "higher", True, SECONDARY, SEEDS,
                                repo_path=str(self.repo))
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
            about: tuple[str, ...] = ()) -> str:
        self.n += 1
        file = self.root / "docs" / path
        file.parent.mkdir(parents=True, exist_ok=True)
        file.write_text(f"doc {self.n}\n", encoding="utf-8")
        doc_id = actor.register_document(path, doc_type, f"title {self.n}", about=list(about))
        if current:
            actor.set_document_current(doc_id)
        return doc_id

    def decision_doc(self) -> str:
        self.n += 1
        return self.doc(self.rld, f"decisions/d{self.n}.v1.md", "decision")

    def result_doc(self, actor: ResearchDB | None = None) -> str:
        self.n += 1
        return self.doc(actor or self.worker, f"results/r{self.n}.v1.md", "experiment_result")

    def finish_runs(self, actor: ResearchDB, exp: str, nodes: int = 1, walltime_s: int = 600) -> None:
        for seed in self.rld.get(exp)["seeds"]:
            run = f"{exp}/s{seed}"
            if self.rld.get(run) is None:
                actor.create_run(exp, seed)
            if self.rld.get(run).get("valid"):
                continue
            actor.update_run(run, exec_status="submitted")
            actor.update_run(run, exec_status="succeeded", valid=True, metric_value=70.0,
                             secondary={"final_loss": 1.0, "peak_mem_gb": 40.0},
                             nodes_used=nodes, walltime_used_s=walltime_s)

    def baseline(self, nodes: int, walltime_s: int) -> str:
        self.n += 1
        design = self.doc(self.worker, f"exp/b{self.n}/design.v1.md", "experiment_design")
        exp = self.worker.create_experiment("baseline", "sota", design, self.harness, nodes, walltime_s)
        self.finish_runs(self.worker, exp, nodes, walltime_s)
        self.worker.record_verdict(exp, self.result_doc(), 70.0, 0.1)
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

    def method(self, hyp: str, n_seeds: int | None = None, code_ref: str | None = None) -> str:
        self.n += 1
        design = self.doc(self.worker, f"exp/m{self.n}/design.v1.md", "experiment_design")
        exp = self.worker.create_experiment("method", "m", design, code_ref or self.commit(), 1, 1800,
                                            hypothesis_id=hyp, n_seeds=n_seeds)
        self.finish_runs(self.worker, exp)
        return exp

    def comparisons(self, exp: str, sota: tuple[float, float, float], parent=None) -> list[dict]:
        """sota: (primary, final_loss, peak_mem_gb) deltas; parent: (experiment, primary, ...); positive = better."""
        seeds = set(self.rld.get(exp)["seeds"])
        out = []
        for role, target, deltas in (("sota", self.sota, sota), ("parent", parent and parent[0], parent and parent[1:])):
            if target is None:
                continue
            paired = len(seeds & set(self.rld.get(target)["seeds"]))
            out.append({"target_id": target, "role": role, "n_paired": paired, "delta_mean": deltas[0],
                        "delta_sd": 0.01, "deltas": dict(zip(SECONDARY, deltas[1:]))})
        return out

    def evaluate(self, exp: str, verdict: str, sota=(0.3, 0.1, 0.1), parent=None) -> None:
        self.worker.record_verdict(exp, self.result_doc(), 70.3, 0.05, verdict, self.comparisons(exp, sota, parent))


class SpecTest(unittest.TestCase):
    def test_spec_parsing(self):
        spec = rdb.SPEC
        self.assertEqual(spec["hypothesis"].columns["experiment_status"].enum,
                         ("todo", "running", "no_gain", "beats_parent", "beats_sota"))
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
        unevaluated = self.worker.create_experiment("baseline", "other", design, self.harness, 1, 60)
        with self.assertRaisesRegex(ResearchDBError, "evaluated with the current frozen harness"):
            self.rld.update_project(sota_experiment_id=unevaluated)
        v2 = self.commit({"harness/stats.py": "stats v2\n"})
        self.rld.update_project(harness_ref=v2)
        self.assertNotIn("sota_experiment_id", self.rld.get("P-test"))  # new harness: SOTA must be re-run
        with self.assertRaisesRegex(ResearchDBError, "SOTA baseline before node experiments"):
            self.rld.screen_seed_count()

    def test_new_project_validation(self):
        db = Path(self.tmp.name) / "other" / "research_tree.db"
        (db.parent / "docs").mkdir(parents=True)
        create_db.create_db(db)
        rld = ResearchDB(db, "rld/main")
        (db.parent / "docs" / "s.v1.md").write_text("s", encoding="utf-8")
        setup = rld.register_document("s.v1.md", "min_setup", "s")
        with self.assertRaisesRegex(ResearchDBError, "3 distinct"):
            rld.create_project("P-x", "x", setup, "acc", "higher", True, SECONDARY, [1, 1, 2])
        with self.assertRaisesRegex(ResearchDBError, "must not repeat the primary"):
            rld.create_project("P-x", "x", setup, "acc", "higher", True, ["acc"], SEEDS)
        with self.assertRaisesRegex(ResearchDBError, "must not look like another record"):
            rld.create_project("T-x", "x", setup, "acc", "higher", True, SECONDARY, SEEDS)
        # A project named like its directory / uv project.
        self.assertEqual(rld.create_project("my-study", "x", setup, "acc", "higher", True, SECONDARY, SEEDS), "my-study")
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
            self.rld.decide(h, {"status": "prunable"}, "needs 32 nodes", doc_id=report, based_on=[unrelated])
        declined = self.doc(ui, "instructions/UI-0002.v1.md", "user_instruction", about=(h,))
        self.rld.decide(h, {"status": "prunable"}, "user declined the extra budget", doc_id=report, based_on=[declined])
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
                self.worker.create_experiment(method_name="m", design_doc_id=design, **kwargs)
        exp = self.worker.create_experiment("method", "m", design, code, 1, 60, hypothesis_id=h)
        self.assertEqual(self.rld.get(exp)["seeds"], SEEDS)  # 0.5 node-hours per seed: 3 seeds fit the budget

    def test_runs(self):
        h = self.hypothesis()
        self.branch(h)
        design = self.doc(self.worker, "exp/d.v1.md", "experiment_design")
        exp = self.worker.create_experiment("method", "m", design, self.commit(), 1, 600, hypothesis_id=h, n_seeds=1)
        with self.assertRaisesRegex(ResearchDBError, "not one of"):
            self.worker.create_run(exp, 43)
        run = self.worker.create_run(exp, 42)
        with self.assertRaises(PermissionDenied):
            ResearchDB(self.db, "worker/w2").update_run(run, exec_status="submitted")
        self.worker.update_run(run, exec_status="submitted")
        with self.assertRaisesRegex(ResearchDBError, "record secondary"):
            self.worker.update_run(run, exec_status="succeeded", valid=True, metric_value=1.0, nodes_used=1,
                                   walltime_used_s=10)
        with self.assertRaisesRegex(ResearchDBError, "a number for each"):
            self.worker.update_run(run, exec_status="succeeded", valid=True, metric_value=1.0, nodes_used=1,
                                   walltime_used_s=10, secondary={"final_loss": 1.0})
        self.worker.update_run(run, exec_status="failed", valid=False)
        self.worker.update_run(run, attempt=2, exec_status="submitted")
        self.worker.update_run(run, exec_status="succeeded", valid=True, metric_value=1.0, nodes_used=1,
                               walltime_used_s=10, secondary={"final_loss": 1.0, "peak_mem_gb": 2.0})
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
        partial = self.worker.create_experiment("method", "m", design, self.commit(), 1, 60, hypothesis_id=self.h)
        with self.assertRaisesRegex(ResearchDBError, "has no valid run"):
            self.evaluate(partial, "beats_sota")

    def test_verdict_consistency(self):
        three = self.method(self.h)
        cases = [
            ("no_gain", (0.3, 0.1, 0.1), "exactly when no metric is better"),
            ("beats_parent", (-0.1, -0.1, -0.1), "exactly when no metric is better"),
            ("close", (0.01, 0.0, 0.0), "must be conclusive"),
            ("beats_parent", (0.3, 0.0, 0.0), "the SOTA gate is passed"),
            ("beats_sota", (0.05, 0.0, 0.0), "primary lead over 0.05"),  # equal to the margin is not a lead
            ("beats_parent", (0.0, 0.5, 0.0), "positive primary-metric difference"),
        ]
        for verdict, sota, message in cases:
            with self.subTest(verdict=verdict, sota=sota), self.assertRaisesRegex(ResearchDBError, message):
                self.evaluate(three, verdict, sota=sota)
        with self.assertRaisesRegex(ResearchDBError, "comparisons must be exactly"):
            self.worker.record_verdict(three, self.result_doc(), 70.0, None, "beats_sota", [])
        bad = self.comparisons(three, (0.3, 0.1, 0.1))
        bad[0]["n_paired"] = 2
        with self.assertRaisesRegex(ResearchDBError, "pairs 3 seeds, not 2"):
            self.worker.record_verdict(three, self.result_doc(), 70.0, None, "beats_sota", bad)
        self.evaluate(three, "beats_sota", sota=(0.0501, 0.0, -0.2))
        edge = self.rld.edges("rel_compared_with", source_id=three)[0]
        self.assertEqual((edge["role"], edge["passes_gate"], edge["deltas"]),
                         ("sota", True, {"final_loss": 0.0, "peak_mem_gb": -0.2}))
        with self.assertRaisesRegex(ResearchDBError, "already evaluated"):
            self.evaluate(three, "beats_sota")

    def test_fewer_seeds_cannot_beat_sota_and_extension(self):
        one = self.method(self.h, n_seeds=1)
        with self.assertRaisesRegex(ResearchDBError, "primary lead"):
            self.evaluate(one, "beats_sota", sota=(1.0, 0.0, 0.0))
        self.evaluate(one, "no_gain", sota=(-0.2, 0.0, -0.1))
        with self.assertRaisesRegex(ResearchDBError, "extend to at most 3"):
            self.worker.extend_seeds(one, 4)
        self.worker.extend_seeds(one, 3)  # within the screening budget (3 seeds fit)
        record = self.rld.get(one)
        self.assertEqual((record["seeds"], record.get("verdict")), (SEEDS, None))
        self.assertEqual(self.rld.edges("rel_compared_with", source_id=one), [])
        self.finish_runs(self.worker, one)
        self.evaluate(one, "beats_sota")
        self.assertEqual(self.rld.latest_result(self.h)["id"], one)


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
        self.evaluate(close, "beats_sota")


class DecisionTest(Fixture):
    def concluded(self, verdict: str, sota=(0.3, 0.1, 0.1), parent=None, hyp: str | None = None) -> tuple[str, str]:
        h = hyp or self.hypothesis()
        if hyp is None:
            self.start(h)
        exp = self.method(h)
        self.evaluate(exp, verdict, sota=sota, parent=parent)
        return h, exp

    def test_status_follows_latest_verdict(self):
        h, exp = self.concluded("no_gain", sota=(-0.1, -0.1, -0.1))
        with self.assertRaisesRegex(ResearchDBError, "needs based_on the latest evaluated experiment"):
            self.rld.decide(h, {"experiment_status": "no_gain", "status": "prunable"}, "x", doc_id=self.decision_doc())
        with self.assertRaisesRegex(ResearchDBError, "verdict no_gain"):
            self.rld.decide(h, {"experiment_status": "beats_parent"}, "x", based_on=[exp])
        with self.assertRaisesRegex(ResearchDBError, "without gain is pruned"):
            self.rld.decide(h, {"experiment_status": "no_gain"}, "x", based_on=[exp])
        self.rld.decide(h, {"experiment_status": "no_gain", "status": "prunable"}, "no gain",
                        doc_id=self.decision_doc(), based_on=[exp])
        self.assertEqual(self.rld.history(h)[-1]["based_on"], [exp])

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
                            doc_id=self.decision_doc(), based_on=[exp])
            first = self.rld.get(h)
            order = [first["created_at"]] + [first[k] for k in ("started_at", "first_experiment_at",
                                                                "first_result_at", "concluded_at")]
            self.assertEqual(order, sorted(order))
            self.assertEqual(len(set(order)), 5)
            self.assertIsNone(first.get("beats_sota_at"))

            # Re-verifying clears the completion time; first-time stamps are kept.
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
            with self.assertRaises(PermissionDenied):
                self.rld.update_hypothesis(h, concluded_at="2000-01-01T00:00:00Z")
        finally:
            rdb.now_utc = saved

    def test_user_declined_node_has_completion_but_no_start(self):
        h = self.hypothesis()
        declined = self.doc(ResearchDB(self.db, "ui/ui"), "instructions/UI-0009.v1.md", "user_instruction", about=(h,))
        self.rld.decide(h, {"status": "prunable"}, "declined", doc_id=self.decision_doc(), based_on=[declined])
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

    def test_child_compares_with_parent_result(self):
        parent, parent_exp = self.concluded("beats_parent", sota=(0.02, 0.0, 0.0))
        self.rld.decide(parent, {"experiment_status": "beats_parent", "status": "expandable"}, "keep",
                        doc_id=self.decision_doc(), based_on=[parent_exp])
        child = self.hypothesis(parent=parent)
        self.start(child)
        exp = self.method(child)
        with self.assertRaisesRegex(ResearchDBError, "comparisons must be exactly"):
            self.evaluate(exp, "beats_parent", sota=(0.02, 0.0, 0.0))
        # better than SOTA on the primary metric, but no metric better than the parent: no gain
        self.evaluate(exp, "no_gain", sota=(0.02, 0.0, 0.0), parent=(parent_exp, -0.01, 0.0, -0.1))
        self.assertEqual({e["role"] for e in self.rld.edges("rel_compared_with", source_id=exp)}, {"sota", "parent"})

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
        with self.assertRaisesRegex(ResearchDBError, "GO needs"):
            self.rld.decide("P-test", {"status": "go"}, "x", doc_id=self.decision_doc())
        theory = self.doc(self.rld, f"h/{h}/theory.v1.md", "theory", about=(h,))
        self.rld.decide(h, {"novelty_recheck": "pass", "theory_recheck": "pass"}, "rechecked",
                        based_on=[novelty, theory])
        self.assertEqual(self.rld.go_candidates(), [h])
        self.rld.decide("P-test", {"status": "go"}, "GO", doc_id=self.doc(self.rld, "reports/go.v1.md", "report"))
        self.assertEqual((self.rld.get("P-test")["status"], self.rld.get(other)["status"]), ("go", "pending"))

    def test_recheck_failure_prunes(self):
        h, exp = self.concluded("beats_sota")
        self.rld.decide(h, {"experiment_status": "beats_sota"}, "gate", based_on=[exp])
        prior = self.doc(self.rld, f"h/{h}/novelty.v1.md", "novelty", about=(h,))
        with self.assertRaisesRegex(ResearchDBError, "a prunable node needs"):
            self.rld.decide(h, {"status": "prunable"}, "x", doc_id=self.decision_doc())
        self.rld.decide(h, {"novelty_recheck": "fail", "status": "prunable"}, "direct prior",
                        doc_id=self.decision_doc(), based_on=[prior])
        self.assertEqual(self.rld.go_candidates(), [])

    def test_not_go(self):
        h, exp = self.concluded("no_gain", sota=(-0.1, -0.1, -0.1))
        self.rld.decide(h, {"experiment_status": "no_gain", "status": "prunable"}, "no gain",
                        doc_id=self.decision_doc(), based_on=[exp])
        h2 = self.hypothesis()
        with self.assertRaisesRegex(ResearchDBError, f"still open: \\['{h2}'\\]"):
            self.rld.decide("P-test", {"status": "not_go"}, "x", doc_id=self.decision_doc())
        self.start(h2)
        _, exp2 = self.concluded("no_gain", sota=(-0.1, -0.1, -0.1), hyp=h2)
        self.rld.decide(h2, {"experiment_status": "no_gain", "status": "prunable"}, "no gain",
                        doc_id=self.decision_doc(), based_on=[exp2])
        self.rld.decide("P-test", {"status": "not_go"}, "NOT GO", doc_id=self.decision_doc())
        with self.assertRaisesRegex(ResearchDBError, "user_instruction"):
            self.rld.decide("P-test", {"status": "active"}, "resume", doc_id=self.decision_doc())


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
            self.worker.create_experiment("method", "m", design, self.commit(), 1, 60, hypothesis_id=h)
        exp = own.create_experiment("method", "m", design, self.commit(), 1, 60, hypothesis_id=h)
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
        with self.assertRaises(PermissionDenied):
            self.worker.update_task(task, status="accepted")
        self.rld.update_task(task, status="accepted")
        self.assertEqual(self.rld.find("task", target_id=h)[0]["status"], "accepted")


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

    def test_snapshot(self):
        h = self.hypothesis()
        snap = self.rld.export_snapshot()
        self.assertEqual([r["id"] for r in snap["tables"]["hypothesis"]], [h])
        self.assertEqual(snap["tables"]["project"][0]["sota_experiment_id"], self.sota)
        self.assertEqual(snap["meta"]["schema_version"], create_db.SCHEMA_VERSION)
        json.dumps(snap)  # JSON-ready


if __name__ == "__main__":
    unittest.main()
