#!/usr/bin/env python3
"""Make a fresh version-3 ToyOpt Lab project for current-contract host scenarios.

ToyOpt Lab contains real CPU logistic-regression training, fixed train/explore/c1/c2 data splits, a manifest
runner, and tools/local_exec.py, which starts each job as a local process and measures its usage. Accuracy is
counted from predictions and loss comes from model outputs; this generator never supplies formula metrics.

Scenario provenance and any declared faults live outside the project, in DEST.ctl unless --controller-dir is set.
The stage and case are provenance labels only: they do not select a workflow or a configuration version.

Usage:
    python3 scripts/make_rt_test_project.py DEST --host claude|codex [--stage FAST] [--case SC-FAST-01]
        [--attempt 1] [--faults FAULTS.json] [--total-limit N] [--controller-dir DIR]
"""
from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import subprocess
import sys
import textwrap
from datetime import datetime, timezone
from pathlib import Path

SCENARIOS = Path(__file__).resolve().parent / "scenarios"
sys.path.insert(0, str(SCENARIOS / "toyopt"))
from toytrain import data as toydata  # noqa: E402

GENERATOR_VERSION = "toyopt-lab-3"
REVIEWER = {"claude": "openai/gpt-6-luna", "codex": "anthropic/claude-haiku-5-5"}  # §2.2: the other model family
# Frozen after the S0 development calibration (dev seeds 7-9 on the explore split, never the formal seeds or c1/c2
# instances): one epoch of plain SGD at a small learning rate under-fits, so a momentum candidate has room to show.
REFERENCE = {"method": "sgd", "lr": 0.005, "epochs": 1, "batch": 32, "accum": 1}
SEEDS = {"search": [42, 43, 44], "c1": [1042, 1043, 1044], "c2": [2042, 2043, 2044]}

TOYOPT_PLAN = '''<!-- research-tree:plan -->
# 研究计划：ToyOpt Lab

## 研究目标

在一个小型合成二分类任务上（code/ 中的 toytrain：纯 Python 逻辑回归，在 CPU 上实际计算梯度与参数更新），
比较优化器、学习率和微批处理策略对学习效果与执行成本的影响。这是 research-tree 插件的真实宿主测试项目
（虚构的研究项目、合成数据上的真实计算），不追求外部科研价值；每次运行在当前机器上一秒左右完成。

## 初始假说

### 假说 1：{hypothesis_title}
在固定数据与更新预算（相同训练轮数、相同 batch）下，带动量的方法可能比当前参考方法收敛更快，
因而在探索验证集上的准确率更高；理由：动量累积一致的梯度方向，在更新次数受限时走得更远。

## 期望使用的模型

不适用：toytrain 自带逻辑回归模型（code/toytrain/train.py）。

## 期望使用的训练数据集

不适用：code/data/train.jsonl（1200 条合成样本，数据版本 toyopt-data-1，身份见 code/data/splits.json）。

## 期望使用的评测数据集

探索与搜索：code/data/explore.jsonl（400 条）。独立确认：code/data/c1.jsonl（400 条，与探索集同一生成规律、
不同样本实例）；c2.jsonl 留给确认反馈之后的新候选。训练 seed 与评测切分分开选择：换训练 seed 不等于换了评测材料。

## 期望使用的基线

参考方法（已冻结，code/configs/reference.json）：`--method sgd --lr 0.005 --epochs 1 --batch 32 --accum 1`。
它是本虚构项目声明的参考方法，不是外部学术 SOTA。

## 评测与指标

主指标 accuracy（越高越好；metrics.json 中是由 predictions.jsonl 计数得到的 0–1 比例，比较与门槛按百分点）。
eval_loss、final_loss（由模型输出计算）与 train_time_s 作为诊断保留在原始产物。

## 实验范围

只改 code/toytrain/methods.py、code/configs/ 下的方法配置及新增的方法文件；不改数据、切分与评测代码。
所有运行在当前机器上经 tools/local_exec.py 提交，不提交集群作业，不使用 GPU。

## 已尝试与无效的方法

把学习率直接调大到 1.0：训练不稳定。

## 非目标

不做大模型、不下载任何数据或模型、不做超参网格搜索。

## 验收要求

由 RLD 决定。

## 参考资料

代码仓库：{code}（已有训练、runner 与数据切分；architect/root 在其上确认实验框架并运行基线）。
'''


def toyopt_config(host: str, stage: str, total_limit: int | None, min_gain: float,
                  alert_node_h: float | None, review_usd_alert: float | None, splits: dict) -> str:
    total = "null" if total_limit is None else str(total_limit)
    alert = "null" if alert_node_h is None else str(alert_node_h)
    review_alert = "null" if review_usd_alert is None else str(review_usd_alert)
    return textwrap.dedent(f'''\
        # ToyOpt Lab 真实宿主测试配置（{host} 宿主，{stage}；模型矩阵见实施文档 §2.2）
        version: 3

        platform:
          dev: |
            在当前机器上运行。代码仓库 code/ 是纯 Python，用 python3 运行，不需要额外依赖。
          experiment: |
            在当前机器上运行（CPU），不提交集群作业，不使用 GPU。代码仓库 code/ 已有训练与 runner：
              cd <worktree 或 code/> && python3 -m toytrain.run --experiment <E-id> --seed <seed> \\
                  --attempt <n> --out <输出目录> --config <方法配置.json> [--eval-split explore|c1|c2] [--sanity]
            runner 写 run_manifest.json（import_run_result 用它）、metrics.json、predictions.jsonl、model.json、
            curve.json、train.log、effective_config.json；失败时也写 manifest（exit_status 非 0）并以非 0 退出。
            作业一律经本地执行适配器提交，它就是本项目的“调度器”，真实启动本地进程并实测用量：
              python3 <项目目录>/tools/local_exec.py submit --key <submission_key> \\
                  --cwd <代码目录> --out <输出目录> -- <上面的 runner 命令>
            job_id 取回答中的 job_id；status / wait --key 按提交身份查询；同一 key 再提交不会启动新进程。
            回答丢失或超时：按 key 用 status 查询，绝不换 key 重提。作业结束后
              tools/local_exec.py accounting --key <key> --write <输出目录>/accounting.json
            生成用量文件（适配器实测；输出目录的 usage.json 同源）。用量按 1 个节点记。
            评测切分：搜索与探索用 explore；确认 seed 的运行用 c1（确认反馈之后的新候选用 c2），身份见
            code/data/splits.json。训练 seed 与评测切分分开选择。
          skills: []

        design:
          code_review: true
          sanity_first: true
          overrun_factor: 2.0

        evidence_policy:
          require_artifact_import: true

        metric_specs:
          - name: accuracy
            direction: higher
            input_unit: fraction
            canonical_unit: percentage_point
            effect_mode: absolute
            minimum_practical_gain: {min_gain}
            aggregation: paired_run_mean
            valid_range: [0.0, 1.0]
          - name: model_bytes
            direction: lower
            input_unit: bytes
            canonical_unit: bytes
            effect_mode: absolute
            minimum_practical_gain: 0
            allowed_regression: 1024
            aggregation: paired_run_mean

        verification:
          independence_fields: [train_seed]
          screening_seeds: [{SEEDS["search"][0]}]
          replication_seeds: [{SEEDS["search"][1]}, {SEEDS["search"][2]}]
          confirmation_seeds: [{", ".join(map(str, SEEDS["c1"]))}]
          min_confirmation_pairs: 3
          max_confirmation_candidates: 2
          confirmation_materials:
            - {{name: c1, seeds: [{", ".join(map(str, SEEDS["c1"]))}], split_sha256: {splits["c1"]["sha256"]}, manifest_field: eval_split_sha256}}
            - {{name: c2, seeds: [{", ".join(map(str, SEEDS["c2"]))}], split_sha256: {splits["c2"]["sha256"]}, manifest_field: eval_split_sha256}}

        budget:
          per_run: {{nodes: 1, walltime: 10m}}
          total_limit: {total}
          screen_node_h: 0.05
          max_parallel_workers: 2
          alert_node_h: {alert}
          review_usd_alert: {review_alert}

        models:
          ui: {{model: inherit, effort: medium}}
          worker: {{model: inherit, effort: medium}}
          architect: {{model: inherit, effort: medium}}
          explorer: {{model: inherit, effort: medium}}
          analyst: {{model: inherit, effort: medium}}
          reviewer:
            model: {REVIEWER[host]}
            thinking: medium
            require_cross_family: true
            timeout_s: 420
        ''')


def sha_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def make_toyopt(dest: Path, host: str, stage: str, case: str, attempt: int, controller: Path,
                faults: Path | None, total_limit: int | None, min_gain: float,
                alert_node_h: float | None, review_usd_alert: float | None,
                hypothesis_title: str = "带动量的方法收敛更快") -> dict:
    code = dest / "code"
    shutil.copytree(SCENARIOS / "toyopt" / "toytrain", code / "toytrain",
                    ignore=shutil.ignore_patterns("__pycache__"))
    splits = toydata.write_splits(code / "data")
    (code / "configs").mkdir()
    (code / "configs" / "reference.json").write_text(json.dumps(REFERENCE, indent=1) + "\n", encoding="utf-8")
    (code / ".gitignore").write_text("outputs/\n__pycache__/\n")
    git(code, "init", "-q", "-b", "main")
    git(code, "add", "-A")
    git(code, "-c", "user.name=rt-test", "-c", "user.email=rt@test.invalid", "commit", "-q", "-m",
        "ToyOpt Lab: training, runner, fixed splits, frozen reference configuration")
    (dest / "tools").mkdir()
    shutil.copyfile(SCENARIOS / "local_exec.py", dest / "tools" / "local_exec.py")
    (dest / "plan.md").write_text(TOYOPT_PLAN.replace("{code}", str(code)).replace("{hypothesis_title}", hypothesis_title),
                                  encoding="utf-8")
    (dest / "research-tree.yaml").write_text(toyopt_config(host, stage, total_limit, min_gain,
                                                           alert_node_h, review_usd_alert, splits["splits"]),
                                             encoding="utf-8")
    controller.mkdir(parents=True, exist_ok=True)
    plan = json.loads(faults.read_text(encoding="utf-8")) if faults else {"faults": []}
    (controller / "fault-plan.json").write_text(json.dumps(plan, ensure_ascii=False, indent=1) + "\n",
                                                encoding="utf-8")
    inputs = {name: sha_file(SCENARIOS / "toyopt" / "toytrain" / name)
              for name in sorted(p.name for p in (SCENARIOS / "toyopt" / "toytrain").glob("*.py"))}
    scenario = {
        "generator_version": GENERATOR_VERSION, "host": host, "stage": stage, "case": case, "attempt": attempt,
        "instance": f"{stage}-{host}-{case}-a{attempt:02d}", "project": str(dest), "created_at":
        datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"), "code_inputs_sha256": inputs,
        "local_exec_sha256": sha_file(SCENARIOS / "local_exec.py"), "reference": REFERENCE,
        "splits": splits, "seed_blocks": SEEDS, "blind": False,
        "material_access": "non-blind functional test (§3.2): c1 and c2 are inside the project repository",
        "material_handed_to_research": ["train", "explore", "c1", "c2"], "fault_plan": "fault-plan.json",
    }
    (controller / "scenario.json").write_text(json.dumps(scenario, ensure_ascii=False, indent=1) + "\n",
                                              encoding="utf-8")
    return scenario


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("dest", type=Path)
    p.add_argument("--host", choices=("claude", "codex"), required=True)
    p.add_argument("--stage", default="FAST", help="provenance label, never a workflow selector")
    p.add_argument("--case", default="SC-FAST-01")
    p.add_argument("--attempt", type=int, default=1)
    p.add_argument("--controller-dir", type=Path, help="default: DEST.ctl beside the project")
    p.add_argument("--faults", type=Path, help="a fault plan (record.py faults checks it), copied to the controller")
    p.add_argument("--total-limit", type=int, default=None,
                   help="budget.total_limit in node-seconds; small values test the admission limit")
    p.add_argument("--min-gain", type=float, default=1.0, help="primary metric's minimum_practical_gain (pp)")
    p.add_argument("--alert-node-h", type=float, default=None)
    p.add_argument("--review-usd-alert", type=float, default=None)
    p.add_argument("--hypothesis-title", default="带动量的方法收敛更快",
                   help="the user hypothesis's title in plan.md")
    args = p.parse_args()
    dest = args.dest.resolve()
    if dest.exists() and any(dest.iterdir()):
        p.error(f"{dest} is not empty; every test uses a new directory")
    controller = (args.controller_dir or dest.with_name(dest.name + ".ctl")).resolve()
    if controller.is_relative_to(dest):
        p.error("the controller directory must lie outside the project")
    if controller.exists() and any(controller.iterdir()):
        p.error(f"{controller} is not empty")
    dest.mkdir(parents=True, exist_ok=True)
    scenario = make_toyopt(dest, args.host, args.stage, args.case, args.attempt, controller, args.faults,
                           args.total_limit, args.min_gain, args.alert_node_h,
                           args.review_usd_alert, args.hypothesis_title)
    print(json.dumps({"project": str(dest), "controller": str(controller), "instance": scenario["instance"]}))
    return 0


def git(code: Path, *args: str) -> None:
    subprocess.run(["git", "-C", str(code), *args], check=True, capture_output=True)


if __name__ == "__main__":
    raise SystemExit(main())
