"""Generate a fictional research project that exercises the whole workflow.

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
            "match": {"train_steps": 1000}, "required_counts": {"n_eval": 8000},
            "description": "（虚构示例）8个常识推理任务、1000步LoRA训练；按seed与数据版本配对"}
def task_body(*contents: str, kind: str = "task_request") -> str:
    """A task request's or delivery's text: its required sections, in order, with these contents."""
    return "".join(f"## {name}\n\n{text}\n\n" for name, text in zip(TASK_SECTIONS[kind], contents, strict=True))


FICTION = "> 本文档属于虚构示例项目，方法、文献与数字均为演示而编造，不代表真实研究结果。\n\n"


class Demo:
    def __init__(self, dest: Path):
        self.dest = dest.resolve()
        self.code = self.dest / "code"
        self.root = self.dest / "research" / PROJECT_ID
        self.docs = self.root / "docs"
        self.rng = random.Random(20261003)
        self.rld = None

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

    def doc(self, actor: ResearchDB, path: str, doc_type: str, title: str, body: str, summary: str,
            about: tuple[str, ...] = (), parent: str | None = None) -> str:
        """Write, register (draft), add the front matter with the assigned id, then make it current. JSON documents
        (metric specification, protocol) are written as they are."""
        file = self.docs / path
        file.parent.mkdir(parents=True, exist_ok=True)
        if path.endswith(".json"):
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
                "data_version": "commonsense-mix-v1（虚构）", "train_steps": 1000, "config": {"lora_rank": 16},
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
        """The comparison as the metric specification defines it (the frozen statistics rule reads it to pick a
        verdict; the interface recomputes and checks every number): absolute differences, train time relative to
        the reference mean."""
        seeds = sorted(set(mine) & set(theirs))
        diffs = {k: [SIGN[k] * (mine[s][k] - theirs[s][k]) for s in seeds] for k in SIGN}
        mean = lambda xs: sum(xs) / len(xs)
        sd = lambda xs: math.sqrt(sum((x - mean(xs)) ** 2 for x in xs) / (len(xs) - 1)) if len(xs) > 1 else None
        deltas = {k: mean(diffs[k]) for k in SECONDARY if k != "train_time_s"}
        ref_time = mean([theirs[s]["train_time_s"] for s in seeds])
        deltas["train_time_s"] = -(mean([mine[s]["train_time_s"] for s in seeds]) - ref_time) / ref_time
        return {"target_id": target, "role": role, "n_paired": len(seeds), "delta_mean": mean(diffs["acc"]),
                "delta_sd": sd(diffs["acc"]), "deltas": deltas}

    # -- the story ----------------------------------------------------------------

    def build(self) -> None:
        if self.dest.exists():
            raise SystemExit(f"refusing to overwrite {self.dest}; remove it or choose another --dest")
        self.docs.mkdir(parents=True)
        shutil.copyfile(CLEANUP_TEMPLATE, self.dest / CLEANUP_SCRIPT)  # what init gives a project
        create_db.create_db(self.root / "research_tree.db")
        db = self.root / "research_tree.db"
        rld, ui = ResearchDB(db, "rld/main"), ResearchDB(db, "ui/ui")
        librarian = ResearchDB(db, "worker/lit")  # caches the related work before the nodes exist
        self.rld = rld

        # User instruction, goal and minimal setup.
        (self.root / "agents.json").write_text(json.dumps(["ui/ui", "rld/main", "worker/root"], indent=1),
                                               encoding="utf-8")
        instr = self.doc(ui, "instructions/UI-0001.v1.md", "user_instruction", "立项：寻找可发表的LoRA优化器改进",
                         "## 用户原话\n\n“在最小设定下寻找能超过当前最强LoRA优化器的新方法，目标是AI顶会论文。”\n\n"
                         "## UI的理解\n\n- 类型：指令\n- 范围：阶段1快速验证；阶段2另行授权\n", "立项指令（虚构）")
        goal = self.doc(rld, "project/goal.v1.md", "goal", "研究目标",
                        "## 研究问题\n\n能否改进LoRA微调的优化器，使小模型常识推理平均精度稳定超过最强基线？\n\n"
                        f"## 依据\n\n用户指令 {instr}。\n", "LoRA优化器方法发现（虚构）")
        setup_body = (
            "## 最小实验设定\n\n| 项目 | 设定 |\n|---|---|\n| 模型 | 0.5B参数的小型语言模型（虚构） |\n"
            "| 数据 | 常识推理混合训练集2K条（虚构） |\n| 训练 | LoRA秩16，1000步 |\n"
            "| 评测 | 8个常识推理任务平均精度 |\n| 主指标 | acc（百分比，越高越好） |\n"
            "| 其他指标 | final_loss、loss_auc、peak_mem_gb、train_time_s（均越低越好） |\n"
            "| seeds | 42, 43, 44 |\n| 单次运行上限 | 8 nodes × 1 h；筛选预算 10 node·h |\n"
            "| 评测类型 | real_gt（数据集自带标签；可作完整性能声明） |\n\n"
            "## 冻结框架与判定规则\n\n- 框架文件：`harness/`\n- 指标规范见 `project/metric-spec.v1.json`：acc 取百分点差，final_loss、loss_auc、"
            "peak_mem_gb 取差值，train_time_s 取相对SOTA均值的比例；正值为更好；peak_mem_gb 允许退化 2 GiB，train_time_s 允许 10%\n"
            "- 协议见 `project/protocol.v1.json`：按seed与数据版本配对，训练1000步，评测8000条\n"
            "- 无提升：相对父节点所有指标都不更好\n- 优于父节点：主指标更好\n- 优于SOTA：3个seed，主指标领先超过0.05个百分点\n"
            "- 需要RLD复核：主指标持平（|Δ|≤0.02）但其他指标有明显取舍\n- 差不多：seed不足3个且主指标领先在0.02–0.10之间\n")
        setup = self.doc(rld, "project/min-setup.v1.md", "min_setup", "最小实验设定与判定规则", setup_body,
                         "0.5B模型、1000步、8任务均值；冻结框架与判定规则")
        config_text = project_config.template_text().replace(
            "  dev: |\n    在当前机器上运行。", "  dev: |\n    （虚构示例）在登录节点编辑代码；单元测试在交互式计算节点上运行。").replace(
            "  experiment: |\n    在当前机器上运行。", "  experiment: |\n    （虚构示例）训练与评测以批处理作业提交到集群的GPU节点。")
        head, _, rest = config_text.partition("metric_specs:\n")  # version 2: the demo's own metric specification
        config_text = (head + "metric_specs:\n" + yaml.safe_dump(METRIC_SPECS["metrics"], allow_unicode=True,
                                                                sort_keys=False, default_flow_style=None)
                       + "\n# seed 层级" + rest.partition("\n# seed 层级")[2])
        (self.dest / project_config.CONFIG_NAME).write_text(config_text, encoding="utf-8")
        (self.docs / "project" / "config.v1.yaml").write_text(config_text, encoding="utf-8")
        config = rld.register_document("project/config.v1.yaml", "config", "项目配置",
                                       summary="research-tree.yaml：开发与实验平台、资源预算、阶段1门槛、子代理模型")
        rld.set_document_current(config)
        specs = self.doc(rld, "project/metric-spec.v1.json", "metric_spec", "指标规范",
                         json.dumps(METRIC_SPECS, ensure_ascii=False, indent=1), "主指标acc（百分点）与4个次指标的方向、单位与保护阈值")
        protocol = self.doc(rld, "project/protocol.v1.json", "protocol", "实验协议",
                            json.dumps(PROTOCOL, ensure_ascii=False, indent=1), "real_gt；按seed与数据版本配对；1000步")
        rld.create_project(PROJECT_ID, "虚构示例：LoRA优化器方法发现", setup, "acc", "higher", True, SECONDARY,
                           SEEDS, goal_doc_id=goal, repo_path=str(self.code), config_doc_id=config,
                           metric_spec_doc_id=specs, protocol_doc_id=protocol,
                           **{k: v for k, v in project_config.db_fields(project_config.parse(config_text)).items()
                              if k != "seeds"})

        # Root node (baselines): harness and SOTA baseline by the root's worker, reviewed and frozen by RLD.
        w1 = ResearchDB(db, f"worker/{rld.assign_worker(PROJECT_ID)}")
        self.code.mkdir(parents=True)
        self.git("init", "-q", "-b", "main")
        harness = self.commit(self.code, {
            "harness/train.py": "# 虚构示例：最小实验训练骨架，记录loss、显存、吞吐曲线\n",
            "harness/stats.py": "# 虚构示例：按seed配对比较并给出判定（规则见最小实验设定文档）\n",
            "baselines/sota_opt.py": "# 虚构SOTA优化器 BaseOpt-A\n",
        }, "harness v1 and SOTA baseline")
        req = self.doc(rld, "tasks/T-0001/request.v1.md", "task_request", "根节点：实现实验框架并运行SOTA", task_body(
            f"根节点 {PROJECT_ID}，任务类型 harness，owner {w1.role}/{w1.agent}。", "不适用（框架与基线任务）。",
            "实现训练/评测骨架与统计代码，记录过程曲线；在3个seed上运行SOTA基线 BaseOpt-A。",
            "本仓库的 harness/ 与 baselines/。", "每个seed 4 nodes × 1h。",
            "RLD 审核后冻结框架；SOTA 的3个seed均为有效运行。", "tasks/T-0001/delivery.v1.md"), "根节点框架任务")
        t_root = rld.create_task("harness", "worker", req, target_id=PROJECT_ID, assignee_id=w1.agent)
        w1.update_task(t_root, status="in_progress")
        rld.update_project(harness_ref=harness, harness_paths=["harness"])
        sota_design = self.doc(w1, "baselines/E-0001/design.v1.md", "experiment_design", "SOTA基线 BaseOpt-A",
                               "在冻结框架下运行虚构的SOTA优化器 BaseOpt-A，3个seed，每个seed 4 nodes。\n", "SOTA基线设计")
        sota = w1.create_experiment("baseline", "BaseOpt-A（虚构SOTA）", sota_design, harness, 4, 3600, estimated_node_h=12.0)
        self.values = {sota: self.finish_experiment(w1, sota, {}, nodes=4)}
        accs = [v["acc"] for v in self.values[sota].values()]
        sota_result = self.doc(w1, "baselines/E-0001/result.v1.md", "experiment_result", "SOTA基线结果",
                               "| seed | acc |\n|---|---|\n" + "".join(f"| {s} | {v['acc']} |\n" for s, v in self.values[sota].items())
                               + self.evidence(sota), f"BaseOpt-A 均值 {sum(accs) / 3:.2f}")
        w1.evaluate_experiment(sota, sota_result)
        w1.run_cleanup(sota)
        rld.update_project(sota_experiment_id=sota)
        delivery = self.doc(w1, "tasks/T-0001/delivery.v1.md", "task_delivery", "根节点交付", task_body(
            f"框架提交 {harness[:10]}（harness/）。", f"SOTA实验 {sota}，3个seed，输出见 outputs/{sota}/。",
            "3个seed均有效；结果见 baselines/E-0001/result.v1.md。", "12 node·h。", "无。", kind="task_delivery"),
            "框架与SOTA完成")
        w1.update_task(t_root, status="delivered", delivery_doc_id=delivery)
        rld.update_task(t_root, status="accepted", evidence_ids=[sota, delivery])
        self.sota, self.harness = sota, harness

        # Cached related work.
        lit = []
        for i, (title, gist) in enumerate([
            ("子批次梯度统计用于自适应预条件（虚构文献A）", "用微批次梯度平方估计二阶矩"),
            ("低秩适配中的因子不平衡（虚构文献B）", "LoRA的A、B因子尺度失衡导致有效学习率偏差"),
            ("正交化更新在矩阵参数上的作用（虚构文献C）", "对更新做正交化可改善条件数"),
            ("Kronecker因子预条件的近似（虚构文献D）", "用对角或低秩近似降低Kronecker预条件成本"),
            ("优化器状态低比特压缩（虚构文献E）", "8-bit状态在多数任务上精度损失可忽略"),
        ], start=1):
            (self.root / "cache" / "literature").mkdir(parents=True, exist_ok=True)
            (self.root / "cache" / "literature" / f"LIT-{i:04d}.txt").write_text(f"{title}\n（虚构原文缓存）\n", encoding="utf-8")
            lit.append(self.doc(librarian, f"literature/LIT-{i:04d}.v1.md", "literature", title,
                                f"- 出处：{title}，2026（虚构）\n- 访问日期：2026-10-03\n- 本地缓存：`cache/literature/LIT-{i:04d}.txt`\n"
                                f"- 核心方法：{gist}\n- 与本项目的关系：作为节点创建时的参考\n", gist))

        def node(title, statement, refs, parent=None, rationale=""):
            n = len(rld.find("hypothesis")) + 1
            body = (f"## 假说\n\n{statement}\n\n## 创建理由\n\n参考：{', '.join(refs)}。{rationale}\n\n"
                    "## 计划的代码改动\n\n在 `methods/` 中实现该优化器变体，不改动 `harness/`。\n\n"
                    "## 实验计划\n\n按筛选预算运行，结果接近时扩展到3个seed。\n")
            doc = self.doc(rld, f"hypotheses/H-{n:04d}/hypothesis.v1.md", "hypothesis", title, body, statement,
                           parent=parent or PROJECT_ID)
            return rld.create_hypothesis(title, statement, doc, refs, parent)

        def start(h, base_commit, base_ref="main"):
            worker = ResearchDB(db, f"worker/{rld.assign_worker(h)}")  # one node, one worker identity
            wt = self.dest / "worktrees" / h
            self.git("worktree", "add", "-q", "-b", f"node/{h}", str(wt), base_commit)
            rld.create_branch(h, f"node/{h}", base_ref, base_commit, str(wt))
            dd = self.decision(f"hypotheses/{h}/decisions/start.v1.md", f"{h} 开始验证", "代码分支已建立，开始实验。", h)
            rld.decide(h, {"experiment_status": "running", "status": "verifying"}, "开始代码改进与实验", doc_id=dd)
            return wt, worker

        def experiment(h, worker, wt, change, effect, verdict_fn, n_seeds=None):
            code = self.commit(wt, {f"methods/{h.lower()}.py": f"# 虚构示例：{change}\n# rev {self.rng.random():.6f}\n"}, change)
            dsg = self.doc(worker, f"hypotheses/{h}/experiments/{change[:8]}-{self.rng.randint(100, 999)}/design.v1.md",
                           "experiment_design", f"{h} 实验设计", f"代码 {code[:10]}：{change}。\n", change)
            exp = worker.create_experiment("method", change, dsg, code, 4, 3600, hypothesis_id=h, n_seeds=n_seeds, estimated_node_h=12.0)
            self.git("tag", f"exp/{exp}", code)
            self.values[exp] = self.finish_experiment(worker, exp, effect, nodes=4)
            return self.evaluate(h, worker, exp, verdict_fn)

        self.experiment, self.start = experiment, start
        self.lit, self.node = lit, node
        self.story(rld, ui, instr)

        # Messages through the send tool (logged and printed).
        for args in (
            ["--from", "ui/ui", "--to", "rld/main", "--type", "instruction", "--text", "立项指令已登记，请开始阶段1。",
             "--docs", "instructions/UI-0001.v1.md", "--about", PROJECT_ID],
            ["--from", "rld/main", "--to", "worker/root", "--type", "task", "--text", "T-0001：实现框架并运行SOTA。",
             "--docs", "tasks/T-0001/request.v1.md", "--about", "T-0001"],
            ["--from", "worker/root", "--to", "rld/main", "--type", "delivery", "--re", "main-0001",
             "--text", "T-0001完成：框架已提交，SOTA三个seed有效。", "--docs", "tasks/T-0001/delivery.v1.md",
             "--about", "T-0001", "E-0001"],
        ):
            if send_message.main(["--root", str(self.root), *args]) != 0:
                raise SystemExit(f"send_message failed for {args}")

        snapshot = rld.export_snapshot()
        (self.root / "snapshots").mkdir(exist_ok=True)
        (self.root / "snapshots" / f"data-{snapshot['meta']['data_version']:05d}.json").write_text(
            json.dumps(build_site.portable(snapshot, self.dest), ensure_ascii=False, indent=1), encoding="utf-8")
        build_site.build(self.root / "research_tree.db", self.root / "site" / "index.html")

    def decision(self, path: str, title: str, body: str, about: str) -> str:
        return self.doc(self.rld, path, "decision", title, body, title, about=(about,))

    def evaluate(self, h: str, worker: ResearchDB, exp: str, verdict_fn) -> tuple[str, str]:
        """Compare with SOTA and (below the top level) the parent's latest evaluated experiment, then apply the
        project's verdict rule as the frozen statistics code would."""
        hyp = self.rld.get(h)
        cmps = [self.paired(self.values[exp], self.values[self.sota], "sota", self.sota)]
        if hyp["parent_id"].startswith("H-"):
            ref = self.rld.latest_result(hyp["parent_id"])["id"]
            cmps.append(self.paired(self.values[exp], self.values[ref], "parent", ref))
        verdict = verdict_fn(cmps)
        accs = [v["acc"] for v in self.values[exp].values()]
        mean = sum(accs) / len(accs)
        table = "| 比较 | 配对seed | Δacc | " + " | ".join(f"Δ{k}" for k in SECONDARY) + " |\n|---|---|---|" + "---|" * len(SECONDARY) + "\n"
        table += "".join(f"| {c['role']} {c['target_id']} | {c['n_paired']} | {c['delta_mean']:+.3f} | "
                         + " | ".join(f"{c['deltas'][k]:+.3f}" for k in SECONDARY) + " |\n" for c in cmps)
        result = self.doc(worker, f"hypotheses/{h}/experiments/{exp}/result.v{len(self.rld.get(exp)['seeds'])}.md",
                          "experiment_result", f"{exp} 统计结果",
                          f"## 判定：{verdict}\n\n均值 acc {mean:.3f}，seeds {sorted(self.values[exp])}（train_time_s 为相对SOTA均值的比例，"
                          f"其余为差值；正值更好）\n\n{table}" + self.evidence(exp, cmps), f"{exp} 判定 {verdict}")
        worker.evaluate_experiment(exp, result, verdict)
        worker.run_cleanup(exp)
        return exp, verdict

    def evidence(self, exp: str, cmps: list | None = None) -> str:
        """The result document's evidence block: each seed's primary metric from its metrics file, and the summary
        the frozen statistics code wrote (outputs/<exp>/stats.json) under the ids the interface checks against its
        own recomputation (mean:<metric>, delta:<role>:<metric>)."""
        claims = [{"id": f"acc-s{seed}", "value": str(v["acc"]), "source": f"outputs/{exp}/s{seed}/metrics.json"}
                  for seed, v in sorted(self.values[exp].items())]
        accs = [v["acc"] for v in self.values[exp].values()]
        stats = {"mean:acc": round(sum(accs) / len(accs), 6)}
        for c in cmps or []:
            stats[f"delta:{c['role']}:acc"] = round(c["delta_mean"], 6)
            stats.update({f"delta:{c['role']}:{k}": round(v, 6) for k, v in c["deltas"].items()})
        (self.root / "outputs" / exp / "stats.json").write_text(json.dumps(stats), encoding="utf-8")
        claims += [{"id": k, "value": repr(v), "source": f"outputs/{exp}/stats.json"} for k, v in stats.items()]
        return "\n## 数字来源\n\n```evidence\n" + json.dumps(claims, ensure_ascii=False) + "\n```\n"

    def story(self, rld: ResearchDB, ui: ResearchDB, instr: str) -> None:
        lit, node, start, experiment = self.lit, self.node, self.start, self.experiment

        def rule(cmps):  # the frozen statistics rule from the minimal-setup document
            by = {c["role"]: c for c in cmps}
            parent = by.get("parent", by["sota"])
            gate = by["sota"]["n_paired"] == 3 and by["sota"]["delta_mean"] > 0.05
            if parent["delta_mean"] <= 0 and all(v <= 0 for v in parent["deltas"].values()):
                return "no_gain"
            if gate:
                return "beats_sota"
            if abs(parent["delta_mean"]) <= 0.02:
                return "needs_rld"
            if by["sota"]["n_paired"] < 3 and 0.02 < by["sota"]["delta_mean"] <= 0.10:
                return "close"
            return "beats_parent" if parent["delta_mean"] > 0 else "no_gain"

        def conclude(h, exp, status, reason):
            dd = self.decision(f"hypotheses/{h}/decisions/{status}.v1.md", f"{h} 结论",
                               f"{reason}\n\n## 缺失证据\n\n第3个seed与更长训练下的结果（筛选只用了部分seed）。\n\n"
                               "## 下一实验\n\n可拓展时在子节点补足；可消灭时不再投入，除非出现新的机制依据。\n", h)
            verdict = rld.get(exp)["verdict"]
            changes = {"experiment_status": verdict if verdict != "needs_rld" else status_for[h], "status": status}
            rld.decide(h, changes, reason, doc_id=dd, based_on=[exp],
                       reconsider_when="出现能修复该缺陷的新机制依据" if status == "prunable" else None)

        status_for = {}
        # H-0001: sub-batch second moments — beats the parent (SOTA) without the gate; expandable.
        h1 = node("子批次二阶矩预条件", "用未裁剪的微批次梯度平方替代全批次二阶矩，可改善LoRA更新方向。", lit[:3],
                  rationale="文献A给出估计方法，但未用于低秩因子；文献B指出因子尺度问题可能放大估计误差。")
        wt1, wk1 = start(h1, self.harness)
        e1, _ = experiment(h1, wk1, wt1, "subbatch-moment", {"acc": 0.15, "peak_mem_gb": 1.2, "loss_auc": -0.01}, rule)
        conclude(h1, e1, "expandable", "优于SOTA父节点但2个seed不足以判定优于SOTA；领先较大，拓展子节点。")
        head1 = self.git("rev-parse", "HEAD", cwd=wt1)
        rld.find("branch")  # noqa: B018 — read path exercised
        # H-0002: orthogonalised updates — no gain; pruned, branch deleted after tagging.
        h2 = node("正交化LoRA更新", "对LoRA因子更新做正交化可改善条件数，提高精度。", [lit[0], lit[2], lit[3]],
                  rationale="文献C在全参数上有效，低秩情形未被检验。")
        wt2, wk2 = start(h2, self.harness)
        e2, _ = experiment(h2, wk2, wt2, "orthogonal-update", {"acc": -0.25, "final_loss": 0.01, "loss_auc": 0.02,
                                                               "peak_mem_gb": 0.6, "train_time_s": 140}, rule)
        conclude(h2, e2, "prunable", "所有指标都不优于SOTA，按规则消灭。")
        self.close_branch(h2, wk2, wt2, "deleted", "无提升，删除分支（实验提交已打标签）。")
        # H-0003: child of H-0001 — 2 seeds close to SOTA, extended to 3, beats SOTA; rechecked; GO candidate.
        h3 = node("子批次二阶矩 + 因子尺度平衡", "在子批次二阶矩基础上平衡A、B因子尺度，可进一步提升精度。", lit[:3], parent=h1,
                  rationale="H-0001 已优于SOTA父节点；文献B的尺度平衡与其互补。")
        wt3, wk3 = start(h3, head1, base_ref=f"node/{h1}")
        e3, v3 = experiment(h3, wk3, wt3, "moment-balance", {"acc": 0.24, "peak_mem_gb": 1.0, "loss_auc": -0.02}, rule)
        if v3 in ("close", "beats_parent"):
            wk3.extend_seeds(e3, 3)
            self.values[e3] = self.finish_experiment(wk3, e3, {"acc": 0.24, "peak_mem_gb": 1.0, "loss_auc": -0.02}, nodes=4)
            self.evaluate(h3, wk3, e3, rule)
        rld.decide(h3, {"experiment_status": rld.get(e3)["verdict"]}, "3个seed判定", based_on=[e3])
        nov = self.doc(rld, f"hypotheses/{h3}/novelty.v1.md", "novelty", f"{h3} 新颖性复核",
                       "## 最接近工作对比\n\n| 工作 | 机制 | 差异 |\n|---|---|---|\n| 文献A | 子批次二阶矩 | 未处理低秩因子尺度 |\n"
                       "| 文献B | 因子尺度分析 | 未结合二阶矩预条件 |\n\n## 结论\n\n未发现直接覆盖本方法的工作（虚构检索）。\n",
                       "未被直接覆盖", about=(h3,))
        theo = self.doc(rld, f"hypotheses/{h3}/theory.v1.md", "theory", f"{h3} 理论复核",
                        "## 核对\n\n尺度平衡使A、B因子的有效学习率一致；与实验中loss_auc改善一致。\n", "推导核对无误", about=(h3,))
        rld.decide(h3, {"novelty_recheck": "pass", "theory_recheck": "pass"}, "复核通过", based_on=[nov, theo, e3])
        dd3 = self.decision(f"hypotheses/{h3}/decisions/expandable.v1.md", f"{h3} 可拓展",
                            "优于SOTA且两项复核通过；作为GO候选，同时可派生子节点。", h3)
        rld.decide(h3, {"status": "expandable"}, "优于SOTA且复核通过，可拓展", doc_id=dd3)
        # Independent confirmation of the frozen candidate on unseen seeds (stage1_confirmed).
        w_root = ResearchDB(db_path := self.root / "research_tree.db", "worker/root")
        cb_design = self.doc(w_root, "baselines/confirm/design.v1.md", "experiment_design", "确认基线",
                             "在确认 seed 1042–1044 上运行 BaseOpt-A，作为确认的参照。\n", "确认基线设计")
        cbase = w_root.create_experiment("baseline", "BaseOpt-A（确认基线）", cb_design, self.harness, 4, 3600,
                                         stage="confirm", estimated_node_h=12.0)
        self.values[cbase] = self.finish_experiment(w_root, cbase, {}, nodes=4)
        cb_result = self.doc(w_root, "baselines/confirm/result.v1.md", "experiment_result", "确认基线结果",
                             "确认 seed 上的基线结果。\n" + self.evidence(cbase), "确认基线")
        w_root.evaluate_experiment(cbase, cb_result)
        c_design = self.doc(wk3, f"hypotheses/{h3}/experiments/confirm/design.v1.md", "experiment_design",
                            f"{h3} 独立确认", f"冻结代码 {rld.get(e3)['code_ref'][:10]}，确认 seed 1042–1044。\n", "独立确认")
        conf = wk3.create_experiment("method", "moment-balance（确认）", c_design, rld.get(e3)["code_ref"], 4, 3600,
                                     hypothesis_id=h3, stage="confirm", estimated_node_h=12.0)
        self.values[conf] = self.finish_experiment(wk3, conf, {"acc": 0.24, "peak_mem_gb": 1.0, "loss_auc": -0.02}, nodes=4)
        cmps = [self.paired(self.values[conf], self.values[cbase], "sota", cbase)]
        c_result = self.doc(wk3, f"hypotheses/{h3}/experiments/{conf}/result.v3.md", "experiment_result",
                            f"{conf} 确认结果", f"确认 seed 上相对确认基线 Δacc {cmps[0]['delta_mean']:+.3f}。\n"
                            + self.evidence(conf, cmps), f"{conf} 独立确认")
        wk3.evaluate_experiment(conf, c_result)
        # Cross-model rechecks of the candidate (09 candidate_recheck), as review_call.py records them (fictional).
        reviewer = ResearchDB(db_path, "reviewer/pi")
        basis = rld.get_eligibility(h3)["recheck_evaluation_id"]  # the confirmation the GO rests on
        notes = {"numbers": "结果文档的数字均可在所引指标文件中找到；归一化与评测标签来源无问题（虚构）。",
                 "protocol": "训练步数、评测条数与协议一致（虚构）。",
                 "method_code": "尺度平衡在优化器 step 中执行，并被训练脚本调用（虚构）。",
                 "novelty": "最接近的文献A、B未同时处理二阶矩与因子尺度（虚构）。",
                 "theory": "尺度平衡的论证与 loss_auc 的改善一致，结论范围未超出证据（虚构）。"}
        for n, (dimension, note) in enumerate(notes.items(), 1):
            rel = f"reviews/RV-{n:04d}.v1.md"
            (self.docs / "reviews").mkdir(parents=True, exist_ok=True)
            (self.docs / rel).write_text(
                f"---\nkind: candidate_recheck\nabout: {h3}\ndimension: {dimension}\nevaluation_id: {basis}\n"
                "result: pass\nbackend: pi\nmodel_observed: openai/gpt-6-astra\n---\n\n"
                f"{FICTION}# candidate_recheck：{h3}（{dimension}）\n\n{note}\n", encoding="utf-8")
            reviewer.register_review(rel, f"candidate_recheck {h3} {dimension}", "candidate_recheck", [h3], "pass",
                                     f"RV-{n:04d}", "pi", "openai/gpt-6-astra", 0.05, dimension=dimension,
                                     evaluation_id=basis, summary=f"pi openai/gpt-6-astra: pass")
        del db_path
        # H-0004: child of H-0001 — no gain against the parent; pruned.
        h4 = node("子批次二阶矩 + 动量重标度", "按子批次方差重标度动量可减少噪声。", [lit[0], lit[1], lit[4]], parent=h1,
                  rationale="H-0001 的变体，检验噪声来源。")
        wt4, wk4 = start(h4, head1, base_ref=f"node/{h1}")
        e4, _ = experiment(h4, wk4, wt4, "momentum-rescale", {"acc": 0.0, "final_loss": 0.02, "loss_auc": 0.03,
                                                              "peak_mem_gb": 1.6, "train_time_s": 90}, rule)
        conclude(h4, e4, "prunable", "相对父节点各项指标都不更好，按规则消灭。")
        self.close_branch(h4, wk4, wt4, "deleted", "无提升，删除分支。")
        # H-0005: diagonal Kronecker approximation — 2 seeds, close; extension pending (attention item).
        h5 = node("Kronecker因子对角近似", "对Kronecker预条件取对角近似，在低秩上以低成本获得二阶信息。", [lit[2], lit[3], lit[4]],
                  rationale="文献D的近似未在LoRA上评测。")
        wt5, wk5 = start(h5, self.harness)
        experiment(h5, wk5, wt5, "kron-diag", {"acc": 0.06, "peak_mem_gb": 0.4}, rule)
        # H-0006: full Kronecker preconditioning — infeasible within caps; user declined.
        h6 = node("完整Kronecker二阶预条件", "对每层使用完整Kronecker因子预条件。", [lit[2], lit[3], lit[0]],
                  rationale="理论上最充分利用二阶信息，但成本未知。")
        declined = self.doc(ui, "instructions/UI-0002.v1.md", "user_instruction", "放弃H-0006",
                            "## 用户原话\n\n“单个实验需要32个节点，超出预算，放弃这个方向。”\n", "用户决定放弃H-0006", about=(h6,))
        dd = self.decision(f"hypotheses/{h6}/decisions/infeasible.v1.md", f"{h6} 无法在上限内实验",
                           "估算单次运行需要32 nodes，超过8 nodes上限，已上报用户。", h6)
        rld.decide(h6, {"status": "prunable"}, "用户决定放弃（超出单次运行上限）", doc_id=dd, based_on=[declined], reconsider_when="用户提供新的预算或资源")
        # H-0007: 8-bit optimizer state — accuracy level with parent, memory much lower; needs RLD.
        h7 = node("8-bit优化器状态", "以8-bit存储优化器状态，在精度不变时显著降低显存。", [lit[4], lit[0], lit[1]],
                  rationale="文献E在全参数微调上验证，LoRA场景未知。")
        wt7, wk7 = start(h7, self.harness)
        experiment(h7, wk7, wt7, "state-8bit", {"acc": 0.0, "peak_mem_gb": -6.0, "train_time_s": 30}, rule)
        # H-0008: child of H-0003 — created, not started yet (pending).
        node("自适应秩分配", "按层的子批次方差分配LoRA秩，可在同等参数量下提升精度。", lit[:3], parent=h3,
             rationale="H-0003 优于SOTA；按层统计可能进一步提升。")
        # Open work: extension task for H-0005, decision pending for H-0007.
        req = self.doc(rld, "tasks/T-0002/request.v1.md", "task_request", "H-0005 扩展到3个seed", task_body(
            f"节点 {h5}，任务类型 experiment，owner {wk5.role}/{wk5.agent}。", "判定为差不多：补足seed后能否优于父节点。",
            "同一代码版本，扩展到3个统一seed。", f"{h5} 的分支与 outputs/。", "每个seed 1 node·h 以内。",
            "3个seed均有效后重新判定。", "tasks/T-0002/delivery.v1.md"), "扩展seed")
        t = rld.create_task("experiment", "worker", req, target_id=h5, assignee_id=wk5.agent)
        wk5.update_task(t, status="in_progress")
        # H-0007: memory saving without accuracy gain: paused, with what would reopen it.
        e7 = rld.latest_result(h7)["id"]
        rld.decide_disposition(h7, "paused", "精度持平、只省显存；阶段1目标是精度，暂不投入", [e7],
                               reconsider_when="用户把显存列为阶段目标，或出现精度改进的组合依据")
        # A review finding about H-0003's code, resolved with the re-checked code file.
        ob = rld.add_obligation(e3, "code_review:RV-demo", "seed_config", "（虚构）复核指出配置中 seed 列表与协议不一致",
                                "MAJOR", "config.yaml seeds")
        fix = self.root / "outputs" / "fixes" / "seed-config-check.txt"
        fix.parent.mkdir(parents=True, exist_ok=True)
        fix.write_text("（虚构）seed 列表已与协议核对一致：42, 43, 44\n", encoding="utf-8")
        rld.resolve_obligation(ob["obligation_id"], "code_fixed", "outputs/fixes/seed-config-check.txt")
        # Decision batch: the H-0001 subtree brought one finding (H-0003), the next batch none.
        rld.note_findings(h1, 1, direction="二阶矩估计")
        rld.note_findings(h1, 0)

    def close_branch(self, h: str, worker: ResearchDB, wt: Path, to_status: str, reason: str) -> None:
        br = self.rld.find("branch", hypothesis_id=h)[0]["id"]
        worker.return_branch(br, self.git("rev-parse", "HEAD", cwd=wt))
        self.git("worktree", "remove", str(wt))
        doc = self.decision(f"hypotheses/{h}/decisions/branch-{to_status}.v1.md", f"{h} 分支处置", reason, h)
        self.rld.close_branch(br, to_status, reason, doc)
        if to_status == "deleted":
            self.git("branch", "-D", f"node/{h}")


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="Generate the fictional demo research project.")
    p.add_argument("--dest", type=Path, default=Path("demo"))
    args = p.parse_args(argv)
    Demo(args.dest).build()
    root = args.dest / "research" / PROJECT_ID
    print(f"demo project: {root}\npage: {root / 'site' / 'index.html'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
