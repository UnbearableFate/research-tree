#!/usr/bin/env python3
"""Make a fresh ToyOpt Lab project for the real-host scenarios (plans/research-tree-implementation-and-real-scenarios.md
§3), or the older toytrain project the workflow benchmark builds on (--legacy-toytrain).

ToyOpt Lab: the user brings plan.md (a research direction and one hypothesis), research-tree.yaml (the model matrix
of §2.2 for the host) and a code repository code/ with real CPU training (pure Python logistic regression; accuracy
counted from predictions, loss from the model's outputs), a runner that writes the run manifest, and fixed data
splits code/data/{train,explore,c1,c2}.jsonl with their identities in splits.json. tools/local_exec.py is the
project's "scheduler": it really starts each job as a local process and measures its usage.

Everything the controller keeps for itself goes to the controller directory (default DEST.ctl, never inside the
project): scenario.json (host, stage, case, attempt, instance, generator inputs and the split identities, which
material was handed to the research), fault-plan.json (faults declared before the run) and the frozen reference.

Usage:
    python3 scripts/make_rt_test_project.py DEST --host claude|codex --stage S0 --case SC-S0-01 [--attempt 1]
        [--faults FAULTS.json] [--discovery off|precheck|full] [--total-limit N] [--controller-dir DIR]
    python3 scripts/make_rt_test_project.py DEST --host claude --legacy-toytrain [--hypotheses 0|1|2] ...
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

TRAIN = '''"""Toy training run: logistic regression on a fixed synthetic split (data version toy-v1).

    python -m toytrain.train --method adam --seed 42 --out outputs/run [--sanity] [--epochs 30] [--lr 0.05]

Writes OUT/metrics.json (accuracy as a fraction of the validation split, final_loss, train_time_s, counts),
OUT/curve.csv (step, loss), OUT/curve.json (the same as {"step": [...], "loss": [...]}: manifest curve_path), OUT/train.log and OUT/model.pt (final weights as JSON text, disposable: the cleanup template removes *.pt).
"""
from __future__ import annotations

import argparse
import json
import math
import random
import sys
import time
from pathlib import Path

from toytrain import methods

DATA_VERSION = "toy-v1"
DATA_SEED = 1234
N_FEATURES = 16


def make_split(n_train: int, n_val: int):
    rng = random.Random(DATA_SEED)
    teacher = [rng.gauss(0, 1) for _ in range(N_FEATURES)]

    def sample():
        x = [rng.gauss(0, 1) for _ in range(N_FEATURES)]
        z = sum(w * v for w, v in zip(teacher, x)) + 0.8 * x[0] * x[1] + rng.gauss(0, 1.2)
        return x, 1 if z > 0 else 0

    data = [sample() for _ in range(n_train + n_val)]
    return data[:n_train], data[n_train:]


def sigmoid(z: float) -> float:
    return 1 / (1 + math.exp(-max(-30.0, min(30.0, z))))


def loss_and_grad(w, b, batch):
    gw, gb, loss = [0.0] * len(w), 0.0, 0.0
    for x, y in batch:
        p = sigmoid(sum(a * c for a, c in zip(w, x)) + b)
        loss -= math.log(p + 1e-12) if y else math.log(1 - p + 1e-12)
        d = p - y
        for i, v in enumerate(x):
            gw[i] += d * v
        gb += d
    n = len(batch)
    return loss / n, [g / n for g in gw], gb / n


def main(argv=None) -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--method", default="adam", choices=sorted(methods.OPTIMIZERS))
    p.add_argument("--seed", type=int, required=True)
    p.add_argument("--out", required=True)
    p.add_argument("--epochs", type=int, default=30)
    p.add_argument("--lr", type=float, default=0.05)
    p.add_argument("--batch", type=int, default=32)
    p.add_argument("--sanity", action="store_true", help="2 epochs on 200 samples: checks the pipeline only")
    args = p.parse_args(argv)
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    n_train, n_val, epochs = (200, 100, 2) if args.sanity else (1200, 400, args.epochs)
    train, val = make_split(n_train, n_val)
    rng = random.Random(args.seed)
    w = [rng.gauss(0, 0.01) for _ in range(N_FEATURES)]
    b = 0.0
    opt = methods.OPTIMIZERS[args.method](lr=args.lr, n=N_FEATURES + 1)
    start = time.perf_counter()
    curve, step = [], 0
    log = open(out / "train.log", "w", encoding="utf-8")
    log.write(f"method={args.method} seed={args.seed} epochs={epochs} n_train={n_train} data={DATA_VERSION}\\n")
    for epoch in range(epochs):
        rng.shuffle(train)
        for i in range(0, len(train), args.batch):
            loss, gw, gb = loss_and_grad(w, b, train[i:i + args.batch])
            params = opt.step(w + [b], gw + [gb], step)
            w, b = params[:-1], params[-1]
            step += 1
            curve.append((step, loss))
        log.write(f"epoch {epoch} loss {loss:.5f}\\n")
    final_loss, _, _ = loss_and_grad(w, b, train)
    correct = sum((sigmoid(sum(a * c for a, c in zip(w, x)) + b) > 0.5) == bool(y) for x, y in val)
    elapsed = time.perf_counter() - start
    if not all(math.isfinite(v) for v in w + [b, final_loss]):
        log.write("ERROR non-finite parameters\\n")
        return 1
    metrics = {"accuracy": correct / len(val), "final_loss": final_loss, "train_time_s": round(elapsed, 4),
               "n_train": n_train, "n_val": len(val), "epochs": epochs, "steps": step, "seed": args.seed,
               "method": args.method, "data_version": DATA_VERSION, "sanity": args.sanity}
    (out / "metrics.json").write_text(json.dumps(metrics, indent=1) + "\\n")
    (out / "curve.csv").write_text("step,loss\\n" + "".join(f"{s},{v:.6f}\\n" for s, v in curve))
    # the plugin's curve contract (build_site.load_curve): a JSON object of equal-length series with "step"
    (out / "curve.json").write_text(json.dumps({"step": [s for s, _ in curve], "loss": [v for _, v in curve]}))
    (out / "model.pt").write_text(json.dumps({"w": w, "b": b}))
    log.write(f"done accuracy={metrics['accuracy']:.4f} final_loss={final_loss:.5f}\\n")
    log.close()
    print(json.dumps(metrics))
    return 0


if __name__ == "__main__":
    sys.exit(main())
'''

METHODS = '''"""Optimizers; a method is a new entry here (or a new option of one)."""
from __future__ import annotations

import math


class SGD:
    def __init__(self, lr: float, n: int):
        self.lr = lr

    def step(self, params, grads, t):
        return [p - self.lr * g for p, g in zip(params, grads)]


class Momentum:
    def __init__(self, lr: float, n: int, beta: float = 0.9):
        self.lr, self.beta, self.v = lr, beta, [0.0] * n

    def step(self, params, grads, t):
        self.v = [self.beta * v + g for v, g in zip(self.v, grads)]
        return [p - self.lr * v for p, v in zip(params, self.v)]


class Adam:
    def __init__(self, lr: float, n: int, b1: float = 0.9, b2: float = 0.999, eps: float = 1e-8):
        self.lr, self.b1, self.b2, self.eps = lr, b1, b2, eps
        self.m, self.v = [0.0] * n, [0.0] * n

    def step(self, params, grads, t):
        t += 1
        self.m = [self.b1 * m + (1 - self.b1) * g for m, g in zip(self.m, grads)]
        self.v = [self.b2 * v + (1 - self.b2) * g * g for v, g in zip(self.v, grads)]
        mh = [m / (1 - self.b1 ** t) for m in self.m]
        vh = [v / (1 - self.b2 ** t) for v in self.v]
        return [p - self.lr * a / (math.sqrt(c) + self.eps) for p, a, c in zip(params, mh, vh)]


OPTIMIZERS = {"sgd": SGD, "momentum": Momentum, "adam": Adam}
'''

PLAN = '''<!-- research-tree:plan -->
# 研究计划

## 研究目标

在一个秒级、CPU 的玩具设定（code/ 中 toytrain：合成数据上的逻辑回归，数据版本 toy-v1）上，寻找能在相同
训练轮数下提高验证集准确率的优化器改动。这是 research-tree 插件的真实宿主测试项目，不追求真实研究价值；
所有运行都在当前机器上、几秒内完成。

## 初始假说

{hypotheses}

## 期望使用的模型

不适用：toytrain 自带逻辑回归模型（code/toytrain/train.py）。

## 期望使用的训练数据集

不适用：toytrain 内置的合成数据（data_version toy-v1，固定 DATA_SEED，训练 1200 条）。

## 期望使用的评测数据集

toytrain 内置的验证集（400 条，与训练集不重叠）。

## 期望使用的基线

SOTA 基线为 `--method adam --lr 0.05`；另一个基线 `--method momentum`。

## 评测与指标

主指标 accuracy（越高越好；metrics.json 中是 0–1 的比例，比较与门槛按百分点：go_margin 0.5 即 0.5 个百分点）；
final_loss（越低越好）与 train_time_s（秒）作为诊断保留在原始产物，不进入统计比较或 gate；
本测试配置的 MetricSpec 只声明 accuracy。

## 实验范围

只改 code/toytrain/methods.py 及新增的方法文件；不改数据生成与评测。每个 seed 一次运行几秒，不提交集群作业。

## 已尝试与无效的方法

把学习率直接调大到 0.5：训练发散。

## 非目标

不做大模型、不下载任何数据或模型、不做超参网格。

## 验收要求

由 RLD 决定。

## 参考资料

代码仓库：{code}（已有 toytrain 训练框架，作为实验骨架起点；根节点 worker 在其上实现统计代码与基线运行）。
'''

HYPOTHESES = '''### 假说 1：Adam 加线性学习率 warmup
在 toytrain 上给 Adam 加前 10% 步数的线性 warmup，预期相同轮数下验证准确率略高、final_loss 不变差；理由：
初期大步长在小批量上噪声大，warmup 减少早期震荡。'''

HYPOTHESIS_2 = '''

### 假说 2：Nesterov 动量
把 momentum 基线改为 Nesterov 形式（梯度在前瞻点估计），预期相同轮数下 final_loss 更低、验证准确率不低于 momentum；
理由：前瞻修正减少动量带来的过冲。'''

DIRECTION = "由发现流程产生。"


def config(host: str, alert: float | None, with_reviewer: bool = False, version: int = 2,
           total_limit: int | None = None, min_gain: float = 0.5, profile: str = "stage1_confirmed",
           discovery_mode: str = "off") -> str:
    reviewer = REVIEWER[host]
    alert_text = "null" if alert is None else str(alert)
    if version == 2:
        return config_v2(host, alert_text, reviewer, with_reviewer, total_limit, min_gain, profile, discovery_mode)
    return textwrap.dedent(f'''\
        # research-tree 真实宿主测试配置（plans/design/14 §5，{host} 宿主）
        version: 1

        platform:
          dev: |
            在当前机器上运行。代码仓库 code/ 用项目的 .venv/bin/python 运行即可，不需要额外依赖。
          experiment: |
            在当前机器上运行，不提交集群作业。训练命令：
            cd <worktree 或 code/> && <项目目录>/.venv/bin/python -m toytrain.train --method <m> --seed <s> --out <输出目录>
            上述命令仅训练；根 worker 还须实现输出完整 manifest 的 runner。框架验收后，方法与 sanity 都通过该 runner 运行并导入原始 manifest，不能只调用 train 后补造产物。
            每次不到几秒；--sanity 为最小规模检查。用量按 1 个节点记，walltime_used_s 为墙钟时间向上取整到整秒、至少 1 秒。
          skills: []

        budget:
          per_run:
            nodes: 1
            walltime: 10m
          screen_node_h: 0.05
          max_parallel_workers: 2
          alert_node_h: {alert_text}

        stage1:
          gate_seeds: 3
          go_margin: 0.5
          min_related_work: 1

        models:
          ui:
            model: inherit
            effort: medium
          worker:
            model: inherit
            effort: medium
        ''') + (f"  lens_assistant:\n    model: inherit\n    effort: medium\n  reviewer:\n    model: {reviewer}\n"
              "    thinking: medium\n    require_cross_family: true\n    timeout_s: 900\n"
              if with_reviewer else f"# reviewer（M4 起，--with-reviewer）：{reviewer}，thinking medium\n")


def config_v2(host: str, alert_text: str, reviewer: str, with_reviewer: bool, total_limit: int | None,
              min_gain: float = 0.5, profile: str = "stage1_confirmed", discovery_mode: str = "off") -> str:
    """The version-2 schema (01 §3, M3 and later): metric specs, seed tiers and a node-seconds budget."""
    total = "null" if total_limit is None else str(total_limit)
    return textwrap.dedent(f'''\
        # research-tree 真实宿主测试配置（plans/design/14 §5，{host} 宿主，version 2）
        version: 2

        platform:
          dev: |
            在当前机器上运行。代码仓库 code/ 用项目的 .venv/bin/python 运行即可，不需要额外依赖。
          experiment: |
            在当前机器上运行，不提交集群作业。训练命令：
            cd <worktree 或 code/> && <项目目录>/.venv/bin/python -m toytrain.train --method <m> --seed <s> --out <输出目录>
            上述命令仅训练；根 worker 还须实现输出完整 manifest 的 runner。框架验收后，方法与 sanity 都通过该 runner 运行并导入原始 manifest，不能只调用 train 后补造产物。
            每次不到几秒；--sanity 为最小规模检查。用量按 1 个节点记，walltime_used_s 为墙钟时间向上取整到整秒、至少 1 秒。
            本机没有调度器：提交身份（submission_key）就是本次运行的输出目录名；"作业"即本地进程，job_id 用 local-<submission_key>。
            用量文件由 worker 写在输出目录：{{"job_id": ..., "nodes_used": 1, "walltime_used_s": ...}}。
          skills: []

        discovery:
          mode: {discovery_mode}
          lenses: [method-transfer, contradiction]
          triage_top_n: 2
          max_initial_nodes: 3

        design:
          overrun_factor: 2.0

        evidence_policy:
          profile: {profile}

        metric_specs:
          - name: accuracy
            direction: higher
            input_unit: fraction
            canonical_unit: percentage_point
            effect_mode: absolute
            minimum_practical_gain: {min_gain}
            aggregation: paired_run_mean
            valid_range: [0.0, 1.0]

        verification:
          screening_seeds: [0]
          replication_seeds: [1, 2]
          confirmation_seeds: [100, 101, 102]
          min_confirmation_pairs: 3
          max_confirmation_candidates: 2

        budget:
          per_run: {{nodes: 1, walltime: 10m}}
          compute_unit: node_seconds
          total_limit: {total}
          screen_node_h: 0.05
          max_parallel_workers: 2
          alert_node_h: {alert_text}

        literature:
          min_related_work: 1

        models:
          ui: {{model: inherit, effort: medium}}
          worker: {{model: inherit, effort: medium}}
        ''') + (f"  lens_assistant: {{model: inherit, effort: medium}}\n  reviewer:\n    model: {reviewer}\n"
              "    thinking: medium\n    require_cross_family: true\n    timeout_s: 900\n"
              if with_reviewer else f"# reviewer（M4 起，--with-reviewer）：{reviewer}，thinking medium\n")




# ---------------------------------------------------------------------------------------------------------------
# ToyOpt Lab (§3): the project every stage's real scenarios start from
# ---------------------------------------------------------------------------------------------------------------

GENERATOR_VERSION = "toyopt-lab-1"
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

代码仓库：{code}（已有训练、runner 与数据切分；根节点 worker 在其上确认实验框架并运行基线）。
'''


def toyopt_config(host: str, stage: str, discovery_mode: str, total_limit: int | None, min_gain: float,
                  alert_node_h: float | None, review_usd_alert: float | None) -> str:
    total = "null" if total_limit is None else str(total_limit)
    alert = "null" if alert_node_h is None else str(alert_node_h)
    review_alert = "null" if review_usd_alert is None else str(review_usd_alert)
    return textwrap.dedent(f'''\
        # ToyOpt Lab 真实宿主测试配置（{host} 宿主，{stage}；模型矩阵见实施文档 §2.2）
        version: 2

        platform:
          dev: |
            在当前机器上运行。代码仓库 code/ 是纯 Python，用项目的 .venv/bin/python 运行，不需要额外依赖。
          experiment: |
            在当前机器上运行（CPU），不提交集群作业，不使用 GPU。代码仓库 code/ 已有训练与 runner：
              cd <worktree 或 code/> && <项目目录>/.venv/bin/python -m toytrain.run --experiment <E-id> --seed <seed> \\
                  --attempt <n> --out <输出目录> --config <方法配置.json> [--eval-split explore|c1|c2] [--sanity]
            runner 写 run_manifest.json（import_run_result 用它）、metrics.json、predictions.jsonl、model.json、
            curve.json、train.log、effective_config.json；失败时也写 manifest（exit_status 非 0）并以非 0 退出。
            作业一律经本地执行适配器提交，它就是本项目的“调度器”，真实启动本地进程并实测用量：
              <项目目录>/.venv/bin/python <项目目录>/tools/local_exec.py submit --key <submission_key> \\
                  --cwd <代码目录> --out <输出目录> -- <上面的 runner 命令>
            job_id 取回答中的 job_id；status / wait --key 按提交身份查询；同一 key 再提交不会启动新进程。
            回答丢失或超时：按 key 用 status 查询，绝不换 key 重提。作业结束后
              tools/local_exec.py accounting --key <key> --write <输出目录>/accounting.json
            生成用量文件（适配器实测；输出目录的 usage.json 同源）。用量按 1 个节点记。
            评测切分：搜索与探索用 explore；确认 seed 的运行用 c1（确认反馈之后的新候选用 c2），身份见
            code/data/splits.json。训练 seed 与评测切分分开选择。
          skills: []

        discovery:
          mode: {discovery_mode}
          require_precheck: true
          lenses: [method-transfer, contradiction]
          triage_top_n: 2
          max_initial_nodes: 2

        design:
          code_review: true
          sanity_first: true
          overrun_factor: 2.0

        evidence_policy:
          profile: stage1_confirmed
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

        verification:
          screening_seeds: [{SEEDS["search"][0]}]
          replication_seeds: [{SEEDS["search"][1]}, {SEEDS["search"][2]}]
          confirmation_seeds: [{", ".join(map(str, SEEDS["c1"]))}]
          min_confirmation_pairs: 3
          max_confirmation_candidates: 2

        budget:
          per_run: {{nodes: 1, walltime: 10m}}
          compute_unit: node_seconds
          total_limit: {total}
          screen_node_h: 0.05
          max_parallel_workers: 2
          alert_node_h: {alert}
          review_usd_alert: {review_alert}

        literature:
          min_related_work: 1
          require_verified: true

        models:
          ui: {{model: inherit, effort: medium}}
          worker: {{model: inherit, effort: medium}}
          lens_assistant: {{model: inherit, effort: medium}}
          reviewer:
            model: {REVIEWER[host]}
            thinking: medium
            require_cross_family: true
            timeout_s: 420
        ''')


def sha_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def make_toyopt(dest: Path, host: str, stage: str, case: str, attempt: int, controller: Path,
                faults: Path | None, discovery_mode: str, total_limit: int | None, min_gain: float,
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
    (dest / "research-tree.yaml").write_text(toyopt_config(host, stage, discovery_mode, total_limit, min_gain,
                                                           alert_node_h, review_usd_alert), encoding="utf-8")
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
    p.add_argument("--stage", default="S0")
    p.add_argument("--case", default="SC-COMMON-01")
    p.add_argument("--attempt", type=int, default=1)
    p.add_argument("--controller-dir", type=Path, help="default: DEST.ctl beside the project")
    p.add_argument("--faults", type=Path, help="a fault plan (record.py faults checks it), copied to the controller")
    p.add_argument("--discovery", choices=("off", "precheck", "full"), default="off")
    p.add_argument("--total-limit", type=int, default=None,
                   help="budget.total_limit in node-seconds; small values test the admission limit")
    p.add_argument("--min-gain", type=float, default=1.0, help="primary metric's minimum_practical_gain (pp)")
    p.add_argument("--alert-node-h", type=float, default=None)
    p.add_argument("--review-usd-alert", type=float, default=None)
    p.add_argument("--hypothesis-title", default="带动量的方法收敛更快",
                   help="the user hypothesis's title in plan.md (S1 names it Zebra so a later Alpha sorts first)")
    p.add_argument("--legacy-toytrain", action="store_true",
                   help="the older toytrain project (the workflow benchmark's base)")
    p.add_argument("--hypotheses", type=int, choices=(0, 1, 2), default=2, help="legacy: user hypotheses in plan.md")
    p.add_argument("--with-reviewer", action="store_true", help="legacy: write models.reviewer")
    p.add_argument("--config-version", type=int, choices=(1, 2), default=2, help="legacy: configuration schema")
    p.add_argument("--profile", choices=("stage1_confirmed", "screening"), default="stage1_confirmed")
    args = p.parse_args()
    dest = args.dest.resolve()
    if dest.exists() and any(dest.iterdir()):
        p.error(f"{dest} is not empty; every test uses a new directory")
    if not args.legacy_toytrain:
        controller = (args.controller_dir or dest.with_name(dest.name + ".ctl")).resolve()
        if controller.is_relative_to(dest):
            p.error("the controller directory must lie outside the project")
        if controller.exists() and any(controller.iterdir()):
            p.error(f"{controller} is not empty")
        dest.mkdir(parents=True, exist_ok=True)
        scenario = make_toyopt(dest, args.host, args.stage, args.case, args.attempt, controller, args.faults,
                               args.discovery, args.total_limit, args.min_gain, args.alert_node_h,
                               args.review_usd_alert, args.hypothesis_title)
        print(json.dumps({"project": str(dest), "controller": str(controller), "instance": scenario["instance"]}))
        return 0
    code = dest / "code"
    (code / "toytrain").mkdir(parents=True)
    (code / "toytrain" / "__init__.py").write_text("")
    (code / "toytrain" / "train.py").write_text(TRAIN)
    (code / "toytrain" / "methods.py").write_text(METHODS)
    (code / ".gitignore").write_text("outputs/\n__pycache__/\n")
    git(code, "init", "-q", "-b", "main")
    git(code, "add", "-A")
    git(code, "-c", "user.name=rt-test", "-c", "user.email=rt@test.invalid", "commit", "-q", "-m", "toytrain framework")
    (dest / "plan.md").write_text(PLAN.format(hypotheses=(DIRECTION, HYPOTHESES, HYPOTHESES + HYPOTHESIS_2)[args.hypotheses],
                                              code=code), encoding="utf-8")
    (dest / "research-tree.yaml").write_text(config(args.host, args.alert_node_h if args.alert_node_h is not None
                                                    else 0.005, args.with_reviewer, args.config_version, args.total_limit,
                                                    0.5 if args.min_gain == 1.0 else args.min_gain, args.profile,
                                                    args.discovery), encoding="utf-8")
    print(dest)
    return 0


def git(code: Path, *args: str) -> None:
    subprocess.run(["git", "-C", str(code), *args], check=True, capture_output=True)


if __name__ == "__main__":
    raise SystemExit(main())
