"""Generate a fictional research project that exercises the current bounded workflow.

Everything here is invented for demonstration (methods, numbers, literature notes); the page and the
documents say so. The project is built only through the public tools, so it also serves as an end-to-end
check: a git code repository with a frozen harness and per-node branches/worktrees, the LatticeDB database,
the document library, agent messages, and the generated page.

Usage:
    python tools/make_demo.py [--dest demo]      # refuses to overwrite an existing destination
"""

from __future__ import annotations

import argparse
import json
import math
import random
import shutil
import subprocess
import sys
from pathlib import Path

import yaml

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "schema"))

import build_site  # noqa: E402
import create_db  # noqa: E402
import discovery  # noqa: E402
import project_config  # noqa: E402
import send_message  # noqa: E402
from research_db import CLEANUP_SCRIPT, CLEANUP_TEMPLATE, TASK_SECTIONS, ResearchDB  # noqa: E402

PROJECT_ID = "P-demo-lora-opt"
SEEDS = [42, 43, 44]
SECONDARY = ["final_loss", "loss_auc", "peak_mem_gb", "train_time_s"]
# Orientation for paired deltas: +1 when higher is better.
SIGN = {"acc": 1, "final_loss": -1, "loss_auc": -1, "peak_mem_gb": -1, "train_time_s": -1}
# The project's metric specification (plans/design 04 §3): how the interface recomputes every comparison.
METRIC_SPECS = {"version": 1, "primary": "acc", "metrics": [
    {"name": "acc", "direction": "higher", "input_unit": "percentage", "canonical_unit": "percentage_point",
     "effect_mode": "absolute", "minimum_practical_gain": 0.05, "aggregation": "paired_run_mean", "valid_range": [0, 100]},
    {"name": "final_loss", "direction": "lower", "input_unit": "nats", "canonical_unit": "nats",
     "effect_mode": "absolute", "minimum_practical_gain": 0.0, "aggregation": "paired_run_mean"},
    {"name": "loss_auc", "direction": "lower", "input_unit": "raw", "canonical_unit": "raw",
     "effect_mode": "absolute", "minimum_practical_gain": 0.0, "aggregation": "paired_run_mean"},
    {"name": "peak_mem_gb", "direction": "lower", "input_unit": "gib", "canonical_unit": "gib",
     "effect_mode": "absolute", "minimum_practical_gain": 0.0, "allowed_regression": 2.0, "aggregation": "paired_run_mean"},
    {"name": "train_time_s", "direction": "lower", "input_unit": "seconds", "canonical_unit": "seconds",
     "effect_mode": "relative_to_reference_mean", "relative_min_denominator": 1.0, "allowed_regression": 0.10,
     "minimum_practical_gain": 0.0, "aggregation": "paired_run_mean"},
]}
PROTOCOL = {"version": 1, "eval_type": "real_gt", "pair_fields": ["seed", "data_version"],
            "profile": "stage1_confirmed", "confirmation_seeds": [1042, 1043, 1044], "max_confirmation_candidates": 2,
            "min_confirmation_pairs": 3, "require_artifact_import": True,
            "confirmation_materials": [{"name": "holdout", "seeds": [1042, 1043, 1044]}],
            "independence_fields": ["replicate_id"],
            "match": {"train_steps": 1000}, "required_counts": {"n_eval": 8000},
            "description": "（虚构示例）8个常识推理任务、1000步LoRA训练；按seed与数据版本配对"}
def task_body(*contents: str, kind: str = "task_request") -> str:
    """A task request's or delivery's text: its required sections, in order, with these contents."""
    return "".join(f"## {name}\n\n{text}\n\n" for name, text in zip(TASK_SECTIONS[kind], contents, strict=True))


ANCHOR = ("## 问题锚点\n\n- 底线问题：LoRA 微调中优化器在小批量下的二阶矩估计噪声\n"
          "- 必须解决的瓶颈：最强基线在 1000 步内精度不稳定\n- 非目标：不改模型结构、不扩大数据\n"
          "- 约束：单次运行 8 nodes × 1 h，筛选预算 10 node·h\n- 成功条件：3 个统一 seed 上配对领先超过最小实际收益\n\n")


def design_body(lead: str) -> str:
    """An experiment design's sections (plans/design 03 §4): one experiment block."""
    return (f"{lead}\n\n## 检验的 claim\n\n相同步数下 acc 更高。\n\n## 存在理由\n\n主锚定结果。\n\n"
            "## 数据与切分\n\n常识推理训练集 2K 条，8 任务评测（虚构）。\n\n## 比较系统\n\nSOTA 基线与父节点。\n\n"
            "## 指标\n\nacc（主），final_loss、loss_auc、peak_mem_gb、train_time_s。\n\n"
            "## 设定\n\n0.5B 模型，LoRA 秩 16，1000 步，统一 seed。\n\n## 成功判据\n\n配对领先超过 0.05 个百分点。\n\n"
            "## 失败解释\n\n不过门槛：该改动在此设定下不足以改进。\n\n## 表图目标\n\n主结果表一行。\n\n"
            "## 优先级与成本\n\nMUST；每个 seed 最多 1 node·h。\n"
            "## 可证伪预测\n\n匹配条件下 acc 的提升超过最小实际收益。\n\n"
            "## 干预\n\n只改变优化器实现或其科学配置。\n\n"
            "## 匹配对照\n\n相同模型、数据版本、步数与训练种子的已登记基线。\n\n"
            '## 资源上限\n\n{"nodes":1,"walltime_s":3600,"n_seeds":3}\n\n'
            "## 停止与继续条件\n\n最多三个搜索 seed；正向结果才考虑冻结候选，独立确认后再做最终复核。\n")


FICTION = "> 本文档属于虚构示例项目，方法、文献与数字均为演示而编造，不代表真实研究结果。\n\n"


class Demo:
    def __init__(self, dest: Path):
        self.dest = dest.resolve()
        self.code = self.dest / "code"
        self.root = self.dest / "research" / PROJECT_ID
        self.docs = self.root / "docs"
        self.rng = random.Random(20261003)
        self.rld = None
        self.values = {}
        self.proposals = []

    # -- infrastructure ---------------------------------------------------------

    def git(self, *args: str, cwd: Path | None = None) -> str:
        return subprocess.run(["git", "-C", str(cwd or self.code), *args], check=True, capture_output=True,
                              text=True).stdout.strip()

    def commit(self, cwd: Path, files: dict[str, str], message: str) -> str:
        for path, text in files.items():
            (cwd / path).parent.mkdir(parents=True, exist_ok=True)
            (cwd / path).write_text(text, encoding="utf-8")
        self.git("add", "-A", cwd=cwd)
        self.git("-c", "user.name=demo-worker", "-c", "user.email=demo@example.invalid", "commit", "-q", "-m",
                 message, cwd=cwd)
        return self.git("rev-parse", "HEAD", cwd=cwd)

    def ready(self, worker: ResearchDB, h: str | None, code: str, folder: str, change: str) -> None:
        """A fictional same-method sanity run; ordinary bounded search needs no model review."""
        design = self.doc(worker, f"{folder}/sanity-design.v1.md", "experiment_design", "sanity",
                          design_body("虚构的小规模完整性检查，未作科学比较。"), "sanity")
        sanity = worker.create_experiment("sanity", f"{change}（sanity）", design, code, 1, 3600,
            hypothesis_id=h, method_config={"optimizer": change, "lr": 2e-4, "lora_rank": 16}, estimated_node_h=1.0)
        self.values[sanity] = self.finish_experiment(worker, sanity, {}, nodes=1)

    def doc(self, actor: ResearchDB, path: str, doc_type: str, title: str, body: str, summary: str,
            about: tuple[str, ...] = (), parent: str | None = None) -> str:
        """Write, register (draft), add the front matter with the assigned id, then make it current. JSON and YAML documents
        (metric specification, protocol, configuration) are written as they are."""
        file = self.docs / path
        file.parent.mkdir(parents=True, exist_ok=True)
        if path.endswith((".json", ".yaml")):
            file.write_text(body, encoding="utf-8")
            doc_id = actor.register_document(path, doc_type, title, summary=summary, about=list(about))
            actor.set_document_current(doc_id)
            return doc_id
        file.write_text(FICTION + body, encoding="utf-8")
        doc_id = actor.register_document(path, doc_type, title, summary=summary, about=list(about))
        record = self.rld.get(doc_id)
        front = {"id": doc_id, "doc_type": doc_type, "version": record["version"], "title": title,
                 "summary": summary, "about": list(about), "author_role": actor.role, "author_id": actor.agent,
                 "created_at": record["created_at"]}
        if parent:
            front["parent"] = parent
        lines = ["---"] + [f"{k}: {json.dumps(v, ensure_ascii=False)}" for k, v in front.items()] + ["---", ""]
        file.write_text("\n".join(lines) + FICTION + body, encoding="utf-8")
        actor.set_document_current(doc_id)
        return doc_id

    # -- synthetic measurements --------------------------------------------------

    def run_values(self, effect: dict, seed: int) -> dict:
        """effect: per-metric offsets from the SOTA baseline (in natural units)."""
        r = random.Random(f"{seed}-{json.dumps(effect, sort_keys=True)}")
        base = {"acc": 71.40, "final_loss": 0.912, "loss_auc": 1.284, "peak_mem_gb": 38.0, "train_time_s": 3000.0}
        noise = {"acc": 0.01, "final_loss": 0.002, "loss_auc": 0.005, "peak_mem_gb": 0.05, "train_time_s": 15.0}
        seed_shift = {42: 0.0, 43: 0.05, 44: -0.03}.get(seed, 0.01 * (seed % 7 - 3))
        return {k: round(base[k] + effect.get(k, 0.0) + (seed_shift if k == "acc" else 0) + r.gauss(0, noise[k]), 4)
                for k in base}

    def curve(self, values: dict, seed: int) -> dict:
        r = random.Random(seed * 7 + int(values["final_loss"] * 1000))
        steps = list(range(0, 1001, 10))
        floor = values["final_loss"]
        loss = [round(floor + 1.6 * math.exp(-s / 180) + r.gauss(0, 0.01), 4) for s in steps]
        mem = [round(values["peak_mem_gb"] * (0.92 if s < 20 else 1.0) + r.gauss(0, 0.05), 3) for s in steps]
        tput = [round(3600 / values["train_time_s"] * 100 + r.gauss(0, 1.5), 2) for s in steps]
        return {"step": steps, "loss": loss, "mem_gb": mem, "samples_per_s": tput}

    def finish_experiment(self, actor: ResearchDB, exp: str, effect: dict, nodes: int) -> dict:
        record = self.rld.get(exp)
        values = {}
        for seed in record["seeds"]:
            run = f"{exp}/s{seed}"
            if self.rld.get(run) is None:
                actor.create_run(exp, seed, job_id=f"demo-{3480000 + self.rng.randint(1, 9999)}")
            if self.rld.get(run).get("valid"):
                values[seed] = {"acc": self.rld.get(run)["metric_value"], **self.rld.get(run)["secondary"]}
                continue
            v = self.run_values(effect, seed)
            run_dir = self.root / "outputs" / exp / f"s{seed}"
            run_dir.mkdir(parents=True, exist_ok=True)
            (run_dir / "curve.json").write_text(json.dumps(self.curve(v, seed)), encoding="utf-8")
            (run_dir / "train.log").write_text(f"（虚构）{exp} seed {seed}: done\n", encoding="utf-8")
            (run_dir / "metrics.json").write_text(json.dumps(v), encoding="utf-8")
            attempt = self.rld.get(run)["attempt"]
            # What the runner writes beside the outputs; the interface's frozen parser imports it.
            (run_dir / "manifest.json").write_text(json.dumps({
                "experiment_id": exp, "seed": seed, "attempt": attempt, "code_ref": record["code_ref"],
                "exit_status": 0, "metrics_path": "metrics.json", "counts": {"n_train": 2000, "n_eval": 8000},
                "data_version": "commonsense-mix-v1（虚构）", "train_steps": 1000, "replicate_id": f"seed-{seed}",
                "config": {"lora_rank": 16, **(record.get("effective_config") or {})},
                "env": {"cluster": "demo（虚构）"}, "log_path": "train.log", "curve_path": "curve.json",
                "output_path": ".", "nodes_used": nodes, "walltime_used_s": int(v["train_time_s"]) + 60,
                "units": {m["name"]: m["input_unit"] for m in METRIC_SPECS["metrics"]}},
                ensure_ascii=False), encoding="utf-8")
            actor.update_run(run, exec_status="submitted", started_at="2026-10-03T12:00:00Z")
            actor.update_run(run, exec_status="succeeded", finished_at="2026-10-03T13:00:00Z")
            actor.import_run_result(run, attempt, f"outputs/{exp}/s{seed}/manifest.json")
            actor.update_run(run, valid=True)
            values[seed] = v
        return values

    def paired(self, mine: dict, theirs: dict, role: str, target: str) -> dict:
        """The comparison as the metric specification defines it (the interface recomputes and checks every number): absolute differences, train time relative to
        the reference mean."""
        seeds = sorted(set(mine) & set(theirs))
        diffs = {k: [SIGN[k] * (mine[s][k] - theirs[s][k]) for s in seeds] for k in SIGN}
        def mean(xs):
            return sum(xs) / len(xs)

        def sd(xs):
            return math.sqrt(sum((x - mean(xs)) ** 2 for x in xs) / (len(xs) - 1)) if len(xs) > 1 else None
        deltas = {k: mean(diffs[k]) for k in SECONDARY if k != "train_time_s"}
        ref_time = mean([theirs[s]["train_time_s"] for s in seeds])
        deltas["train_time_s"] = -(mean([mine[s]["train_time_s"] for s in seeds]) - ref_time) / ref_time
        return {"target_id": target, "role": role, "n_paired": len(seeds), "delta_mean": mean(diffs["acc"]),
                "delta_sd": sd(diffs["acc"]), "deltas": deltas}

    # -- the current bounded workflow -------------------------------------------

    def build(self) -> None:
        if self.dest.exists():
            raise SystemExit(f"refusing to overwrite {self.dest}; choose another --dest")
        self.docs.mkdir(parents=True)
        shutil.copyfile(CLEANUP_TEMPLATE, self.dest / CLEANUP_SCRIPT)
        create_db.create_db(self.root / "research_tree.db")
        db = self.root / "research_tree.db"
        self.rld = rld = ResearchDB(db, "rld/main")
        ui = ResearchDB(db, "ui/ui")
        (self.root / "agents.json").write_text(json.dumps(
            ["ui/ui", "rld/main", "architect/root", "explorer/main", "analyst/main", "reviewer/demo"]), encoding="utf-8")

        # REG data only: this instruction and all measurements are explicitly fictional.
        instruction = self.doc(ui, "instructions/UI-0001.v1.md", "user_instruction", "虚构演示范围确认",
            "## 用户原话（REG虚构）\n\n确认本演示的预算和范围：每次 1 node × 1 h；先筛选一个种子，"
            "最多复制到三个搜索种子；仅对冻结候选使用预先声明的独立确认材料。不得推断真实研究结果。\n",
            "虚构范围确认，非真实用户授权")
        goal = self.doc(rld, "project/goal.v1.md", "goal", "虚构研究目标", ANCHOR,
                        "演示增量候选、有限筛选与独立确认")
        setup = self.doc(rld, "project/min-setup.v1.md", "min_setup", "虚构最小实验设定",
            "固定模型、数据、步数和指标。使用生成的 REG 数字检验协议与展示工具；不训练真实模型。\n"
            "每个候选先用一个匹配种子；需要时最多补足三个搜索种子。确认使用独立的 seed 1042–1044。\n",
            "所有数据均为明确标注的虚构 REG 夹具")
        config = project_config.defaults()
        config["metric_specs"] = METRIC_SPECS["metrics"]
        config["budget"]["per_run"] = {"nodes": 1, "walltime": "1h"}
        config["verification"]["confirmation_materials"] = PROTOCOL["confirmation_materials"]
        config["verification"]["independence_fields"] = PROTOCOL["independence_fields"]
        config_text = "# 虚构 REG 演示配置，不代表真实实验结果。\n" + yaml.safe_dump(config, allow_unicode=True, sort_keys=False)
        config = project_config.parse(config_text)
        (self.dest / project_config.CONFIG_NAME).write_text(config_text, encoding="utf-8")
        config_doc = self.doc(rld, "project/config.v1.yaml", "config", "版本3配置", config_text, "当前唯一配置格式")
        specs = self.doc(rld, "project/metric-spec.v1.json", "metric_spec", "显式指标规范",
                        json.dumps(METRIC_SPECS, ensure_ascii=False), "单位、方向、实际收益与保护指标")
        protocol = self.doc(rld, "project/protocol.v1.json", "protocol", "独立确认协议",
            json.dumps({**PROTOCOL, **project_config.protocol_requirements(config)}, ensure_ascii=False),
            "stage1_confirmed；搜索和确认 seed 分离；按独立单元计算")
        rld.create_project(PROJECT_ID, "虚构示例：有界增量研究", setup, "acc", "higher", SECONDARY, SEEDS,
            goal_doc_id=goal, repo_path=str(self.code), config_doc_id=config_doc,
            metric_spec_doc_id=specs, protocol_doc_id=protocol,
            **{k: v for k, v in project_config.db_fields(config).items() if k != "seeds"})
        architect = ResearchDB(db, f"architect/{rld.assign_architect()}")
        rld.bind_architect_session("demo-architect-session")
        self.code.mkdir(parents=True)
        self.git("init", "-q", "-b", "main")
        self.harness = self.commit(self.code, {"harness/train.py": "# REG fictional training scaffold\n",
            "harness/stats.py": "# Canonical metrics are recomputed by research_db.\n",
            "baselines/optimizer.py": "# REG fictional reference optimizer\n"}, "fictional shared harness")
        request = self.doc(rld, "tasks/T-0001/request.v1.md", "task_request", "根节点框架与基线", task_body(
            f"根节点 {PROJECT_ID}；architect/root。", "不适用，框架与基线任务。", "检查框架并建立匹配基线。",
            "harness/ 与 baselines/。", "每个 seed 最多 1 node × 1 h。", "有效 sanity 与导入基线证据。",
            "tasks/T-0001/delivery.v1.md"), "唯一 Architect 负责根节点")
        task = rld.create_task("harness", "architect", request, target_id=PROJECT_ID, assignee_id="root")
        architect.update_task(task, status="in_progress")
        self.ready(architect, None, self.harness, "baselines", "BaseOpt-A")
        rld.update_project(harness_ref=self.harness, harness_paths=["harness"])
        design = self.doc(architect, "baselines/design.v1.md", "experiment_design", "虚构匹配基线",
                         design_body("固定基线，依次导入匹配搜索种子。"), "匹配基线")
        self.sota = architect.create_experiment("baseline", "BaseOpt-A（虚构）", design, self.harness, 1, 3600,
            method_config={"optimizer": "BaseOpt-A", "lr": 2e-4, "lora_rank": 16}, estimated_node_h=3.0)
        self.values[self.sota] = self.finish_experiment(architect, self.sota, {}, 1)
        self.evaluate(architect, self.sota)
        rld.update_project(sota_experiment_id=self.sota)
        delivery = self.doc(architect, "tasks/T-0001/delivery.v1.md", "task_delivery", "根节点交付", task_body(
            f"框架 {self.harness[:10]}。", f"基线 {self.sota}。", "三个搜索种子有效，指标和过程曲线已导入。",
            "用量以导入 manifest 为准。", "全部为 REG 虚构数据。", kind="task_delivery"), "框架与基线就绪")
        architect.update_task(task, status="delivered", delivery_doc_id=delivery)
        rld.update_task(task, status="accepted", evidence_ids=[self.sota, delivery])
        discovery.start(self.root, executor_model="fictional-REG")

        positive, worker, exp = self.screen("尺度平衡", "平衡低秩因子尺度", {"acc": 0.30, "final_loss": -0.01})
        worker.extend_seeds(exp, 3)
        self.values[exp] = self.finish_experiment(worker, exp, {"acc": 0.30, "final_loss": -0.01}, 1)
        self.evaluate(worker, exp)
        rld.decide(positive, {"experiment_status": "beats_sota"}, "搜索复制通过预设门槛；尚未独立确认", based_on=[exp])
        self.confirm(architect, worker, positive, exp, {"acc": 0.30, "final_loss": -0.01})

        negative, neg_worker, neg_exp = self.screen("动量重标度", "重标度动量", {"acc": -0.30, "final_loss": 0.02})
        # More work on a nonpositive result is an explicit Leader allocation, never automatic permission.
        rld.extend_seeds(neg_exp, 3)
        self.values[neg_exp] = self.finish_experiment(neg_worker, neg_exp, {"acc": -0.30, "final_loss": 0.02}, 1)
        self.evaluate(neg_worker, neg_exp)
        rld.decide_disposition(negative, "retired", "三个匹配种子显示负向信号；停止本设定的投入", [neg_exp],
                               reconsider_when="有不同机制或新的证据能够解释该负向结果")
        uncertain, _, uncertain_exp = self.screen("低精度状态", "只改变优化器状态精度", {"peak_mem_gb": -3.0})
        rld.decide_disposition(uncertain, "paused", "主指标不确定；先解释取舍再决定是否追加种子", [uncertain_exp],
                               reconsider_when="出现能区分性能与内存取舍的新实验设计")
        # An idea may remain pending while another candidate completes its bounded work.
        self.node("组合变体", "把尺度平衡与状态压缩组合", parent=positive)

        for args in (
            ["--from", "ui/ui", "--to", "rld/main", "--type", "instruction", "--text", "虚构范围已登记。",
             "--docs", rld.get(instruction)["path"], "--about", PROJECT_ID],
            ["--from", "rld/main", "--to", "architect/root", "--type", "task", "--text", "建立共享框架与匹配基线。",
             "--docs", rld.get(request)["path"], "--about", task],
            ["--from", "architect/root", "--to", "rld/main", "--type", "delivery", "--re", "rld--main-0001",
             "--text", "虚构框架与基线证据已导入。", "--docs", rld.get(delivery)["path"], "--about", task, self.sota],
        ):
            if send_message.main(["--root", str(self.root), *args]):
                raise RuntimeError("demo message validation failed")
        snapshot = rld.export_snapshot()
        (self.root / "snapshots").mkdir(exist_ok=True)
        (self.root / "snapshots" / f"data-{snapshot['meta']['data_version']:05d}.json").write_text(
            json.dumps(build_site.portable(snapshot, self.dest), ensure_ascii=False, indent=1), encoding="utf-8")
        build_site.build(db, self.root / "site/index.html")

    def node(self, title: str, intervention: str, parent: str | None = None) -> str:
        candidate = {"title": title, "prediction": "在匹配条件下 acc 的提升超过 0.05 个百分点。",
            "intervention": intervention, "comparator": "同模型、同数据版本、同训练步数和同种子的 BaseOpt-A。",
            "resource_ceiling": {"nodes": 1, "walltime_s": 3600, "n_seeds": 3},
            "stop_conditions": "最多三个搜索种子；正向才考虑独立确认，负向或不确定可停止投入。"}
        self.proposals.append(candidate)
        candidates = discovery.merge([{"source": "fictional-explorer", "candidates": self.proposals}], [],
                                     discovery.read_candidates(self.root))
        discovery.write_candidates(self.root, candidates)
        admitted = next(c for c in candidates if c["title"] == title)
        discovery.select_candidate(self.root, admitted["id"])
        readiness = discovery.evaluate_candidate(self.root, admitted["id"], max_nodes=1, max_walltime_s=3600, screen_node_h=10)
        if readiness["verdict"] != "PASS":
            raise RuntimeError(readiness)
        body = ANCHOR + "\n".join(f"## {heading}\n\n{value}\n" for heading, value in (
            ("可证伪预测", candidate["prediction"]), ("干预", candidate["intervention"]),
            ("匹配对照", candidate["comparator"]), ("资源上限", json.dumps(candidate["resource_ceiling"])),
            ("停止与继续条件", candidate["stop_conditions"])))
        doc = self.doc(self.rld, f"hypotheses/{admitted['id']}/hypothesis.v1.md", "hypothesis", title, body, intervention)
        return self.rld.create_hypothesis(title, intervention, doc, [], parent_id=parent, direction=title,
            candidate_id=admitted["id"], code_parent_id=PROJECT_ID, comparator_experiment_id=self.sota)

    def screen(self, title: str, intervention: str, effect: dict) -> tuple[str, ResearchDB, str]:
        h = self.node(title, intervention)
        worker = ResearchDB(self.root / "research_tree.db", f"worker/{self.rld.assign_worker(h)}")
        self.rld.bind_worker_session(h, f"demo-{h}-session")
        wt = self.dest / "worktrees" / h
        self.git("worktree", "add", "-q", "-b", f"node/{h}", str(wt), self.harness)
        self.rld.create_branch(h, f"node/{h}", "main", self.harness, str(wt))
        decision = self.doc(self.rld, f"hypotheses/{h}/start.v1.md", "decision", "开始有限筛选",
                            "只在已确认的范围内运行匹配种子。", "开始筛选", about=(h,))
        self.rld.decide(h, {"status": "verifying", "experiment_status": "running"}, "开始有限筛选", doc_id=decision)
        code = self.commit(wt, {f"methods/{h}.py": f"# REG fictional method: {intervention}\n"}, title)
        self.ready(worker, h, code, f"hypotheses/{h}", title)
        design = self.doc(worker, f"hypotheses/{h}/design.v1.md", "experiment_design", title,
                          design_body(intervention), "一个匹配搜索种子")
        exp = worker.create_experiment("method", title, design, code, 1, 3600, hypothesis_id=h,
            method_config={"optimizer": title, "lr": 2e-4, "lora_rank": 16}, estimated_node_h=1.0,
            selection_rationale="检验已准入候选；正向则复制，其他结果回到 Leader 决定")
        self.values[exp] = self.finish_experiment(worker, exp, effect, 1)
        self.evaluate(worker, exp)
        return h, worker, exp

    def evaluate(self, actor: ResearchDB, exp: str) -> dict:
        record = self.rld.get(exp)
        refs = [("sota", record.get("baseline_experiment_id")), ("parent", record.get("parent_experiment_id"))]
        comparisons = [self.paired(self.values[exp], self.values[target], role, target)
                       for role, target in refs if target]
        version = len(record["seeds"])
        result = self.doc(actor, f"results/{exp}/result.v{version}.md", "experiment_result", f"{exp} 虚构结果",
            "统计结论由显式协议和已导入运行重算，调用方不提供判定。\n" + self.evidence(exp, comparisons),
            "REG 虚构数据；保留完整来源")
        evaluation = actor.evaluate_experiment(exp, result)
        actor.run_cleanup(exp)
        return evaluation

    def confirm(self, architect: ResearchDB, worker: ResearchDB, hypothesis: str, exp: str, effect: dict) -> None:
        search = self.rld.get(exp)
        candidate = self.rld.freeze_candidate(hypothesis, search["evaluation_id"])
        batch = self.rld.create_confirmation_batch([candidate], "holdout")
        baseline_design = self.doc(architect, "baselines/confirm/design.v1.md", "experiment_design", "独立确认参照",
                                  design_body("只使用预先声明的独立确认材料。"), "确认参照")
        baseline = architect.create_experiment("baseline", "BaseOpt-A（独立确认）", baseline_design, self.harness, 1, 3600,
            stage="confirm", method_config=self.rld.get(self.sota)["effective_config"], confirmation_of=self.sota,
            confirmation_batch_id=batch, estimated_node_h=3.0)
        self.values[baseline] = self.finish_experiment(architect, baseline, {}, 1)
        self.evaluate(architect, baseline)
        design = self.doc(worker, f"hypotheses/{hypothesis}/confirm/design.v1.md", "experiment_design", "独立确认",
                          design_body("冻结相同代码与科学配置；不根据确认反馈修改方法。"), "独立确认")
        confirmation = worker.create_experiment("method", "尺度平衡（独立确认）", design, search["code_ref"], 1, 3600,
            hypothesis_id=hypothesis, stage="confirm", method_config=search["effective_config"],
            candidate_spec_id=candidate, confirmation_batch_id=batch, estimated_node_h=3.0)
        reviewer = ResearchDB(self.root / "research_tree.db", "reviewer/demo")
        review_path = self.docs / "reviews/confirmation-code.v1.md"
        review_path.parent.mkdir(parents=True, exist_ok=True)
        review_path.write_text(FICTION + "# 虚构代码检查\n\n只用于 REG 流程测试，不是真实模型评审。\n", encoding="utf-8")
        reviewer.register_review("reviews/confirmation-code.v1.md", "虚构代码检查", "code_review", [hypothesis], "clear",
            "demo-code-review", "pi", "openai/gpt-6-astra", 0.0, code_ref=search["code_ref"],
            basis=reviewer.review_basis(hypothesis, "code_review", code_ref=search["code_ref"]),
            payload={"method_implemented": True, "issues": []}, summary="明确虚构的 REG 回执")
        self.values[confirmation] = self.finish_experiment(worker, confirmation, effect, 1)
        self.evaluate(worker, confirmation)
        # Deliberately leave final scientific review open. A positive confirmation is still not an automatic GO.
        self.doc(self.rld, f"hypotheses/{hypothesis}/next.v1.md", "decision", "等待最终独立复核",
                 "独立确认材料已使用；下一步是数字、协议、方法代码、新颖性、理论的最终独立复核。尚未宣布 GO。\n",
                 "确认与最终研究决策分离", about=(hypothesis,))

    def evidence(self, exp: str, comparisons: list | None = None) -> str:
        claims = [{"id": f"acc-s{seed}", "value": str(values["acc"]), "source": f"outputs/{exp}/s{seed}/metrics.json"}
                  for seed, values in sorted(self.values[exp].items())]
        stats = {"mean:acc": round(sum(v["acc"] for v in self.values[exp].values()) / len(self.values[exp]), 6)}
        for comparison in comparisons or []:
            stats[f"delta:{comparison['role']}:acc"] = round(comparison["delta_mean"], 6)
            stats.update({f"delta:{comparison['role']}:{key}": round(value, 6) for key, value in comparison["deltas"].items()})
        stats_file = f"stats-v{len(self.values[exp])}.json"
        (self.root / "outputs" / exp / stats_file).write_text(json.dumps(stats), encoding="utf-8")
        claims.extend({"id": key, "value": repr(value), "source": f"outputs/{exp}/{stats_file}"} for key, value in stats.items())
        return "\n## 数字来源\n\n```evidence\n" + json.dumps(claims, ensure_ascii=False) + "\n```\n"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Generate the explicitly fictional current-workflow REG demo.")
    parser.add_argument("--dest", type=Path, default=Path("demo"))
    args = parser.parse_args(argv)
    Demo(args.dest).build()
    root = args.dest / "research" / PROJECT_ID
    print(f"fictional demo project: {root}\npage: {root / 'site/index.html'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
