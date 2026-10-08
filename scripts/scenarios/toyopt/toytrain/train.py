"""ToyOpt training: logistic regression on the project's fixed synthetic splits, computed for real on the CPU.

    python -m toytrain.train --method sgd --lr 0.05 --seed 42 --out outputs/run [--epochs 8] [--batch 32]
        [--accum 1] [--eval-split explore] [--data-dir data] [--sanity]

The training seed only initialises the weights and shuffles the training order; the evaluation split (explore, c1,
c2) is a separate choice and its identity comes from data/splits.json. --accum k accumulates the gradients of k
micro-batches before one update (effective batch = batch x accum).

Writes into OUT: metrics.json (accuracy = correct / n from the predictions, eval_loss and final_loss from the
model's outputs, timing, counts), predictions.jsonl (id, label, pred, prob), model.json (the weights; reloadable),
curve.json and curve.csv (one loss per update step), train.log, and effective_config.json.
"""
from __future__ import annotations

import argparse
import json
import math
import random
import sys
import time
from pathlib import Path

from toytrain import data, methods

DEFAULTS = {"method": "sgd", "lr": 0.05, "epochs": 8, "batch": 32, "accum": 1, "eval_split": "explore"}


def sigmoid(z: float) -> float:
    return 1 / (1 + math.exp(-max(-30.0, min(30.0, z))))


def loss_and_grad(w, b, batch):
    gw, gb, loss = [0.0] * len(w), 0.0, 0.0
    for row in batch:
        x, y = row["x"], row["y"]
        p = sigmoid(sum(a * c for a, c in zip(w, x)) + b)
        loss -= math.log(p + 1e-12) if y else math.log(1 - p + 1e-12)
        d = p - y
        for i, v in enumerate(x):
            gw[i] += d * v
        gb += d
    n = len(batch)
    return loss / n, [g / n for g in gw], gb / n


def parse(argv=None) -> argparse.Namespace:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--method", default=DEFAULTS["method"], choices=sorted(methods.OPTIMIZERS))
    p.add_argument("--seed", type=int, required=True)
    p.add_argument("--out", required=True)
    p.add_argument("--epochs", type=int, default=DEFAULTS["epochs"])
    p.add_argument("--lr", type=float, default=DEFAULTS["lr"])
    p.add_argument("--batch", type=int, default=DEFAULTS["batch"])
    p.add_argument("--accum", type=int, default=DEFAULTS["accum"])
    p.add_argument("--eval-split", default=DEFAULTS["eval_split"])
    p.add_argument("--data-dir", default=str(Path(__file__).resolve().parents[1] / "data"))
    p.add_argument("--sanity", action="store_true",
                   help=f"2 epochs on the first {data.SANITY_TRAIN} training and {data.SANITY_EVAL} evaluation samples")
    return p.parse_args(argv)


def train(args: argparse.Namespace) -> dict:
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    data_dir = Path(args.data_dir)
    log = open(out / "train.log", "w", encoding="utf-8")
    log.write(f"start method={args.method} lr={args.lr} seed={args.seed} epochs={args.epochs} batch={args.batch} "
              f"accum={args.accum} eval_split={args.eval_split} data_dir={data_dir} sanity={args.sanity}\n")
    log.flush()
    train_rows, train_entry = data.load_split(data_dir, "train")
    eval_rows, eval_entry = data.load_split(data_dir, args.eval_split)
    epochs = args.epochs
    if args.sanity:
        train_rows, eval_rows, epochs = train_rows[:data.SANITY_TRAIN], eval_rows[:data.SANITY_EVAL], 2
    config = {"method": args.method, "lr": args.lr, "epochs": epochs, "batch": args.batch, "accum": args.accum,
              "effective_batch": args.batch * args.accum, "eval_split": args.eval_split, "sanity": args.sanity,
              "data_version": data.GENERATOR_VERSION}
    rng = random.Random(args.seed)
    w = [rng.gauss(0, 0.01) for _ in range(data.N_FEATURES)]
    b = 0.0
    opt = methods.OPTIMIZERS[args.method](lr=args.lr, n=data.N_FEATURES + 1)
    start = time.perf_counter()
    curve, step = [], 0
    order = list(train_rows)
    for epoch in range(epochs):
        rng.shuffle(order)
        acc_w, acc_b, acc_loss, k = [0.0] * len(w), 0.0, 0.0, 0
        for i in range(0, len(order), args.batch):
            loss, gw, gb = loss_and_grad(w, b, order[i:i + args.batch])
            acc_w = [a + g for a, g in zip(acc_w, gw)]
            acc_b, acc_loss, k = acc_b + gb, acc_loss + loss, k + 1
            if k == args.accum or i + args.batch >= len(order):
                params = opt.step(w + [b], [g / k for g in acc_w] + [acc_b / k], step)
                w, b = params[:-1], params[-1]
                step += 1
                curve.append((step, acc_loss / k))
                acc_w, acc_b, acc_loss, k = [0.0] * len(w), 0.0, 0.0, 0
        log.write(f"epoch {epoch} loss {curve[-1][1]:.5f}\n")
    final_loss, _, _ = loss_and_grad(w, b, train_rows)
    preds, eval_loss = [], 0.0
    for row in eval_rows:
        p = sigmoid(sum(a * c for a, c in zip(w, row["x"])) + b)
        eval_loss -= math.log(p + 1e-12) if row["y"] else math.log(1 - p + 1e-12)
        preds.append({"id": row["id"], "label": row["y"], "pred": int(p > 0.5), "prob": round(p, 6)})
    elapsed = time.perf_counter() - start
    if not all(math.isfinite(v) for v in w + [b, final_loss]):
        log.write("ERROR non-finite parameters\n")
        log.close()
        raise FloatingPointError("non-finite parameters")
    correct = sum(p["pred"] == p["label"] for p in preds)
    metrics = {"accuracy": correct / len(preds), "correct": correct, "n_eval": len(preds),
               "eval_loss": eval_loss / len(preds), "final_loss": final_loss, "train_time_s": round(elapsed, 4),
               "n_train": len(train_rows), "epochs": epochs, "steps": step, "seed": args.seed,
               "method": args.method, "eval_split": args.eval_split, "eval_split_id": eval_entry["split_id"],
               "train_split_id": train_entry["split_id"], "data_version": data.GENERATOR_VERSION,
               "sanity": args.sanity}
    (out / "predictions.jsonl").write_text("".join(json.dumps(p) + "\n" for p in preds), encoding="utf-8")
    (out / "model.json").write_text(json.dumps({"format": "toyopt-logreg-1", "w": w, "b": b,
                                                "n_features": data.N_FEATURES}) + "\n", encoding="utf-8")
    (out / "metrics.json").write_text(json.dumps(metrics, indent=1) + "\n", encoding="utf-8")
    (out / "curve.csv").write_text("step,loss\n" + "".join(f"{s},{v:.6f}\n" for s, v in curve), encoding="utf-8")
    (out / "curve.json").write_text(json.dumps({"step": [s for s, _ in curve], "loss": [v for _, v in curve]}),
                                    encoding="utf-8")
    (out / "effective_config.json").write_text(json.dumps(config, indent=1, sort_keys=True) + "\n", encoding="utf-8")
    log.write(f"done accuracy={metrics['accuracy']:.4f} correct={correct}/{len(preds)} final_loss={final_loss:.5f}\n")
    log.close()
    return {"metrics": metrics, "config": config, "splits": {"train": train_entry, "eval": eval_entry}}


def main(argv=None) -> int:
    result = train(parse(argv))
    print(json.dumps(result["metrics"]))
    return 0


if __name__ == "__main__":
    sys.exit(main())
