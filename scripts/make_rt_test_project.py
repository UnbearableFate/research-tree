#!/usr/bin/env python3
"""Make a small research project for the real-host tests of plans/design/14 §4 (Herdr, Claude and Codex).

The project holds what a user would bring: plan.md (a research direction and the user hypotheses: two by default, as
14 §4.1 allows before M6; --hypotheses 0 gives only the direction), research-tree.yaml (the model matrix of 14 §5 for the host) and a code repository
code/ with a seconds-long, CPU-only training framework (pure Python logistic regression on a fixed synthetic
split). The framework writes per-seed metrics, a loss curve, a log and disposable weights, and has a --sanity
mode, so the root worker can wrap it as the harness and run baselines on every seed within seconds.

Usage:
    python3 scripts/make_rt_test_project.py DEST --host claude|codex [--hypotheses 0|1|2] [--alert-node-h 0.005]
        [--with-reviewer]
"""
from __future__ import annotations

import argparse
import subprocess
import textwrap
from pathlib import Path

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
其他指标 final_loss（越低越好）、train_time_s（越低越好，秒）。

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
           total_limit: int | None = None, min_gain: float = 0.5, profile: str = "stage1_confirmed") -> str:
    reviewer = ("openai/gpt-6-luna" if host == "claude" else "anthropic/claude-sonnet-5-5")
    alert_text = "null" if alert is None else str(alert)
    if version == 2:
        return config_v2(host, alert_text, reviewer, with_reviewer, total_limit, min_gain, profile)
    return textwrap.dedent(f'''\
        # research-tree 真实宿主测试配置（plans/design/14 §5，{host} 宿主）
        version: 1

        platform:
          dev: |
            在当前机器上运行。代码仓库 code/ 用项目的 .venv/bin/python 运行即可，不需要额外依赖。
          experiment: |
            在当前机器上运行，不提交集群作业。训练命令：
            cd <worktree 或 code/> && <项目目录>/.venv/bin/python -m toytrain.train --method <m> --seed <s> --out <输出目录>
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
              min_gain: float = 0.5, profile: str = "stage1_confirmed") -> str:
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
            每次不到几秒；--sanity 为最小规模检查。用量按 1 个节点记，walltime_used_s 为墙钟时间向上取整到整秒、至少 1 秒。
            本机没有调度器：提交身份（submission_key）就是本次运行的输出目录名；"作业"即本地进程，job_id 用 local-<submission_key>。
            用量文件由 worker 写在输出目录：{{"job_id": ..., "nodes_used": 1, "walltime_used_s": ...}}。
          skills: []

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


def git(code: Path, *args: str) -> None:
    subprocess.run(["git", "-C", str(code), *args], check=True, capture_output=True)


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("dest", type=Path)
    p.add_argument("--host", choices=("claude", "codex"), required=True)
    p.add_argument("--hypotheses", type=int, choices=(0, 1, 2), default=2,
                   help="user hypotheses in plan.md; 0 leaves the discovery flow to produce them (M6)")
    p.add_argument("--alert-node-h", type=float, default=0.005,
                   help="usage alert in node-h; the default 0.005 is 18 node-seconds, i.e. 18 toy runs of 1 s each "
                        "(14 §4.1: small budget)")
    p.add_argument("--with-reviewer", action="store_true",
                   help="write models.reviewer and models.lens_assistant (configuration schema of M4 and later)")
    p.add_argument("--config-version", type=int, choices=(1, 2), default=2,
                   help="research-tree.yaml schema; 2 from M3 on")
    p.add_argument("--min-gain", type=float, default=0.5,
                   help="primary metric's minimum_practical_gain (percentage points); 0 lets any gain pass the gate")
    p.add_argument("--profile", choices=("stage1_confirmed", "screening"), default="stage1_confirmed")
    p.add_argument("--total-limit", type=int, default=None,
                   help="budget.total_limit in node-seconds (version 2); small values test the admission limit")
    args = p.parse_args()
    dest = args.dest.resolve()
    if dest.exists() and any(dest.iterdir()):
        p.error(f"{dest} is not empty; every test uses a new directory")
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
    (dest / "research-tree.yaml").write_text(config(args.host, args.alert_node_h, args.with_reviewer,
                                                       args.config_version, args.total_limit, args.min_gain,
                                                       args.profile), encoding="utf-8")
    print(dest)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
