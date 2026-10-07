#!/usr/bin/env python3
"""A controlled research task for the workflow benchmark (plans/design 11 §2): a research-tree test project whose
toy trainer takes --knobs (a comma list of mechanism switches) and whose true effects are known only to the
evaluation environment.

    python3 scripts/benchmark/make_task.py DEST --scenario zero|gain|combination|noisy|confound [--seed N]

Writes DEST/project (the test project, as make_rt_test_project.py does, with the knob menu in plan.md) and
DEST/truth.json (never inside the project). The trainer reads the truth from $RT_BENCH_TRUTH; without it the knobs
have no effect, so a run outside the benchmark is an ordinary toy run. Scenarios:

  zero         every knob and combination has no effect: any GO is a false GO
  gain         one knob gives a recoverable +1.5 pp
  combination  two knobs do nothing alone and give +1.5 pp together (non-greedy search)
  noisy        a +0.6 pp effect under seed noise of 1.0 pp (replication decides)
  confound     a knob 'helps' only because it doubles the effective learning rate: the same gain comes from a larger
               --lr without the knob (a cheaper competing explanation)
  faults       a +1.5 pp knob, and the first attempt of some (seed, knob set) runs fails: recovery, no duplicate
               submissions, lesson reuse

Limit: the truth file is outside the project, but an agent with shell access that looks for $RT_BENCH_TRUTH can
read it. For a comparison run, start the agent without the variable and inject it only in the job launcher (or
run the trainer as another user); record which isolation was used with the results.
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
    """Benchmark tasks only: the hidden true effect of a knob set (pp), read from $RT_BENCH_TRUTH."""
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
                raise SystemExit("benchmark fault: worker lost connection to the data loader")
    noise = random.Random(f"{truth['salt']}:{key}:{seed}").gauss(0, truth.get("noise_pp", 0.2))
    return (effect + noise) / 100
'''


def truth_for(scenario: str, rng: random.Random) -> dict:
    a, b = rng.sample(KNOBS, 2)
    base = {"scenario": scenario, "salt": rng.getrandbits(64), "noise_pp": 0.2, "effects": {}}
    if scenario == "gain":
        base["effects"] = {a: 1.5}
        base["best"] = [a]
    elif scenario == "combination":
        base["effects"] = {"+".join(sorted((a, b))): 1.5}
        base["best"] = sorted((a, b))
    elif scenario == "noisy":
        base.update(effects={a: 0.6}, noise_pp=1.0, best=[a])
    elif scenario == "confound":
        base.update(confound=a, lr_slope=1.5, best=[])  # the 'gain' disappears at a matched learning rate
    elif scenario == "faults":
        base.update(effects={a: 1.5}, best=[a], faults=[{"seed": s, "knobs": k} for s in (0, 1) for k in ("", a)])
    else:
        base["best"] = []
    return base


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("dest", type=Path)
    p.add_argument("--scenario", choices=SCENARIOS, required=True)
    p.add_argument("--seed", type=int, default=0)
    p.add_argument("--host", default="claude")
    args = p.parse_args()
    dest = args.dest.resolve()
    project = dest / "project"
    subprocess.run([sys.executable, str(ROOT / "scripts" / "make_rt_test_project.py"), str(project),
                    "--host", args.host, "--hypotheses", "0", "--with-reviewer"], check=True, capture_output=True)
    train = project / "code" / "toytrain" / "train.py"
    text = train.read_text(encoding="utf-8")
    text = text.replace("def sigmoid(z: float) -> float:", HOOK.strip() + "\n\n\ndef sigmoid(z: float) -> float:", 1)
    text = text.replace('    p.add_argument("--sanity"', f'    p.add_argument("--knobs", default="", help="comma list of: {", ".join(KNOBS)}")\n'
                        '    p.add_argument("--sanity"', 1)
    text = text.replace('    metrics = {"accuracy": correct / len(val),',
                        '    knobs = [k for k in args.knobs.split(",") if k]\n'
                        '    accuracy = min(1.0, max(0.0, correct / len(val) + _benchmark_effect(knobs, args.seed, args.lr)))\n'
                        '    metrics = {"accuracy": accuracy, "knobs": knobs,', 1)
    train.write_text(text, encoding="utf-8")
    subprocess.run(["git", "-C", str(project / "code"), "commit", "-qam", "benchmark knobs"], check=True,
                   capture_output=True)
    plan = project / "plan.md"
    plan.write_text(plan.read_text(encoding="utf-8").replace(
        "## 初始假说", "## 可调机制\n\ntoytrain.train 接受 --knobs（逗号分隔）：" + "、".join(KNOBS) +
        "。每个开关是一种机制；它们单独或组合是否有效未知。\n\n## 初始假说"), encoding="utf-8")
    truth = truth_for(args.scenario, random.Random(args.seed))
    (dest / "truth.json").write_text(json.dumps(truth, indent=1) + "\n", encoding="utf-8")
    print(json.dumps({"project": str(project), "truth": str(dest / "truth.json"),
                      "run_with": f"RT_BENCH_TRUTH={dest / 'truth.json'}"}))
    return 0


if __name__ == "__main__":
    sys.exit(main())
