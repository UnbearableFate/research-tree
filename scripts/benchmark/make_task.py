#!/usr/bin/env python3
"""REG-only formula fixtures built on the current version-3 ToyOpt scaffold.

    python3 scripts/benchmark/make_task.py DEST --scenario zero|gain|combination|noisy|confound|faults [--seed N]

Writes DEST/project and DEST/truth.json. The private truth supplies synthetic score offsets for mechanism knobs;
these offsets do not describe optimizer performance, scientific validity, or model efficacy. The ordinary ToyOpt
prediction artifacts remain available as a control, and measured_accuracy records their unmodified accuracy.
The generated plan, provenance, metrics and run manifests explicitly label these substitutes as REG fixtures.

The truth file stays outside the project. A shell-capable agent can still read $RT_BENCH_TRUTH unless a separate
isolation boundary is enforced, so this layout alone never establishes blind evaluation.
"""

from __future__ import annotations

import argparse
import json
import random
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
KNOBS = ("lookahead", "clip", "ema", "warmup", "scale")
SCENARIOS = ("zero", "gain", "combination", "noisy", "confound", "faults")

HOOK = '''
def _benchmark_effect(knobs, seed, lr):
    """REG fixture only: a synthetic score offset, never measured optimizer effectiveness."""
    import os
    path = os.environ.get("RT_BENCH_TRUTH")
    if not path:
        return 0.0
    truth = json.loads(Path(path).read_text())
    key = "+".join(sorted(k for k in knobs if k))
    effect = truth["effects"].get(key, 0.0)
    if truth.get("confound"):
        # the knob only doubles the effective learning rate; any run at that rate gets the same gain
        effective = lr * (2 if truth["confound"] in knobs else 1)
        effect += truth.get("lr_slope", 0.0) * max(0.0, min(effective, 0.2) - 0.05) / 0.05
    for fault in truth.get("faults", []):
        if fault["seed"] == seed and fault["knobs"] == key:
            mark = Path(path).parent / "fault-state" / f"{seed}-{key or 'none'}"
            if not mark.exists():  # the first attempt fails, a retry succeeds
                mark.parent.mkdir(exist_ok=True)
                mark.write_text("failed once")
                raise RuntimeError("benchmark fixture fault: worker lost connection to the data loader")
    noise = random.Random(f"{truth['salt']}:{key}:{seed}").gauss(0, truth.get("noise_pp", 0.2))
    return (effect + noise) / 100
'''


def truth_for(scenario: str, rng: random.Random) -> dict:
    a, b = rng.sample(KNOBS, 2)
    base = {"evidence_class": "reg", "substitutes_used": ["formula_metric"],
            "scenario": scenario, "salt": rng.getrandbits(64), "noise_pp": 0.2, "effects": {}}
    if scenario == "gain":
        base["effects"] = {a: 3.0}
        base["best"] = [a]
    elif scenario == "combination":
        base["effects"] = {"+".join(sorted((a, b))): 3.0}
        base["best"] = sorted((a, b))
    elif scenario == "noisy":
        base.update(effects={a: 0.6}, noise_pp=1.0, best=[a])
    elif scenario == "confound":
        base.update(confound=a, lr_slope=1.5, best=[])  # the 'gain' disappears at a matched learning rate
    elif scenario == "faults":
        base.update(effects={a: 3.0}, best=[a], faults=[{"seed": s, "knobs": k} for s in (0, 1) for k in ("", a)])
    else:
        base["best"] = []
    return base


def replace_once(text: str, old: str, new: str) -> str:
    """Fail closed if the current scaffold changes; never silently produce an unpatched fixture."""
    if text.count(old) != 1:
        raise ValueError(f"current ToyOpt scaffold must contain exactly one {old!r}")
    return text.replace(old, new, 1)


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("dest", type=Path)
    p.add_argument("--scenario", choices=SCENARIOS, required=True)
    p.add_argument("--seed", type=int, default=0)
    p.add_argument("--host", choices=("claude", "codex"), default="claude")
    p.add_argument("--alert-node-h", type=float, default=0.1,
                   help="usage alert of the task project; a whole benchmark run stays below it by default")
    args = p.parse_args()
    dest = args.dest.resolve()
    project = dest / "project"
    subprocess.run([sys.executable, str(ROOT / "scripts" / "make_rt_test_project.py"), str(project),
                    "--host", args.host, "--stage", "REG", "--case", f"REG-FORMULA-{args.scenario}",
                    "--alert-node-h", str(args.alert_node_h)], check=True, capture_output=True)
    train = project / "code" / "toytrain" / "train.py"
    text = train.read_text(encoding="utf-8")
    text = replace_once(text, "def sigmoid(z: float) -> float:",
                        HOOK.strip() + "\n\n\ndef sigmoid(z: float) -> float:")
    text = replace_once(text, '"eval_split": "explore"}', '"eval_split": "explore", "knobs": ""}')
    text = replace_once(text, '    p.add_argument("--sanity"',
                        f'    p.add_argument("--knobs", default="", help="REG formula knobs: {", ".join(KNOBS)}")\n'
                        '    p.add_argument("--sanity"')
    text = replace_once(text, '              "data_version": data.GENERATOR_VERSION, **options}',
                        '              "data_version": data.GENERATOR_VERSION, "knobs": args.knobs, **options}')
    text = replace_once(text, '    metrics = {"accuracy": correct / len(preds),',
                        '    knobs = sorted(set(k for k in args.knobs.split(",") if k))\n'
                        '    measured_accuracy = correct / len(preds)\n'
                        '    accuracy = min(1.0, max(0.0, measured_accuracy + _benchmark_effect(knobs, args.seed, args.lr)))\n'
                        '    metrics = {"accuracy": accuracy, "knobs": knobs, "measured_accuracy": measured_accuracy,\n'
                        '               "evidence_class": "reg", "substitutes_used": ["formula_metric"],')
    train.write_text(text, encoding="utf-8")
    runner = project / "code" / "toytrain" / "run.py"
    text = runner.read_text(encoding="utf-8")
    text = replace_once(text, '("method", "eval_split", "data_dir")', '("method", "eval_split", "data_dir", "knobs")')
    text = replace_once(text, '("method", "lr", "epochs", "batch", "accum", "eval_split")',
                        '("method", "lr", "epochs", "batch", "accum", "eval_split", "knobs")')
    text = replace_once(text, '"--accum", str(settings["accum"]), "--eval-split", str(settings["eval_split"])]',
                        '"--accum", str(settings["accum"]), "--eval-split", str(settings["eval_split"]),\n'
                        '                  "--knobs", str(settings["knobs"])]')
    text = replace_once(text, '    manifest = {',
                        '    manifest = {\n        "evidence_class": "reg", "substitutes_used": ["formula_metric"],')
    runner.write_text(text, encoding="utf-8")
    subprocess.run(["git", "-C", str(project / "code"), "-c", "user.name=rt-test", "-c",
                    "user.email=rt@test.invalid", "commit", "-qam", "REG-only formula fixture knobs"],
                   check=True, capture_output=True)
    plan = project / "plan.md"
    text = plan.read_text(encoding="utf-8")
    text = text.replace("# 研究计划：ToyOpt Lab", "# REG-only 回归测试：公式指标 ToyOpt fixture", 1)
    text = text.replace("## 研究目标", "## 研究目标\n\n"
                        "这是 REG / simulation 测试。accuracy 包含预设公式偏移，不能用作科学结论、优化器效果或模型能力证据。\n"
                        "基础训练实际运行；其预测准确率单独保存为 measured_accuracy。独立 scorer 会指出公式值与预测计数的差异。", 1)
    text = text.replace("## 初始假说", "## 可调机制\n\ntoytrain.run 与 toytrain.train 接受 --knobs（逗号分隔）："
                        + "、".join(KNOBS) + "。也可在方法配置 JSON 中设置 knobs。\n\n## 初始假说", 1)
    text = text.replace("主指标 accuracy（越高越好；metrics.json 中是由 predictions.jsonl 计数得到的 0–1 比例，比较与门槛按百分点）。",
                        "fixture 指标 accuracy = measured_accuracy 加上 REG-only 公式偏移；比较单位是百分点。")
    plan.write_text(text, encoding="utf-8")
    provenance = dest / "project.ctl" / "scenario.json"
    scenario = json.loads(provenance.read_text(encoding="utf-8"))
    scenario.update(evidence_class="reg", substitutes_used=["formula_metric"], benchmark_fixture_version=3)
    provenance.write_text(json.dumps(scenario, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    truth = truth_for(args.scenario, random.Random(args.seed))
    (dest / "truth.json").write_text(json.dumps(truth, indent=1) + "\n", encoding="utf-8")
    print(json.dumps({"project": str(project), "truth": str(dest / "truth.json"), "evidence_class": "reg",
                      "run_with": f"RT_BENCH_TRUTH={dest / 'truth.json'}"}))
    return 0


if __name__ == "__main__":
    sys.exit(main())
