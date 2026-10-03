"""Build the offline progress-and-findings page for one research project.

Reads the database (read-only, via research_db.ResearchDB) and the document library, and writes a single
self-contained HTML file: inline CSS/JS/data, no network. Same inputs give the same page apart from the
generation time. See schema/web_builder.md for the views.

Usage:
    python tools/build_site.py --db research/P-x/research_tree.db [--out research/P-x/site/index.html]
    python tools/build_site.py --db ... --check    # exit 1 if the page is older than the database
"""

from __future__ import annotations

import argparse
import html
import json
import re
import shutil
import sys
from pathlib import Path

from research_db import ResearchDB, ResearchDBError, now_utc, sha256_file

MAX_DOC_CHARS = 20000
NODE_TIMES = ("created_at", "started_at", "first_experiment_at", "first_result_at", "beats_sota_at", "concluded_at")
CURVE_POINTS = 200
VERSION_RE = re.compile(r'<meta name="data-version" content="(\d+)">')


# ---------------------------------------------------------------------------
# Documents: escape first, then a small Markdown subset
# ---------------------------------------------------------------------------


def _inline(text: str) -> str:
    text = re.sub(r"`([^`]+)`", r"<code>\1</code>", text)
    return re.sub(r"\*\*([^*]+)\*\*", r"<strong>\1</strong>", text)


def render_markdown(source: str) -> str:
    """Markdown subset (headings, lists, tables, code fences, paragraphs). Input is HTML-escaped first, so
    document content can never inject markup or scripts."""
    source = re.sub(r"\A---\n.*?\n---\n", "", source, flags=re.S)  # front matter is shown from the database
    if len(source) > MAX_DOC_CHARS:
        source = source[:MAX_DOC_CHARS] + "\n\n…（已截断，完整内容见原文件）"
    lines = html.escape(source).split("\n")
    out, para, i = [], [], 0

    def flush():
        if para:
            out.append("<p>" + _inline(" ".join(para)) + "</p>")
            para.clear()

    while i < len(lines):
        line = lines[i]
        if line.startswith("```"):
            flush()
            block = []
            i += 1
            while i < len(lines) and not lines[i].startswith("```"):
                block.append(lines[i])
                i += 1
            out.append("<pre>" + "\n".join(block) + "</pre>")
        elif m := re.match(r"(#{1,4})\s+(.*)", line):
            flush()
            level = min(len(m.group(1)) + 2, 6)
            out.append(f"<h{level}>{_inline(m.group(2))}</h{level}>")
        elif line.startswith("|"):
            flush()
            rows = []
            while i < len(lines) and lines[i].startswith("|"):
                cells = [c.strip() for c in lines[i].strip().strip("|").split("|")]
                if not all(re.fullmatch(r":?-{2,}:?", c) for c in cells):
                    rows.append(cells)
                i += 1
            i -= 1
            if rows:
                head = "".join(f"<th>{_inline(c)}</th>" for c in rows[0])
                body = "".join("<tr>" + "".join(f"<td>{_inline(c)}</td>" for c in r) + "</tr>" for r in rows[1:])
                out.append(f"<table><thead><tr>{head}</tr></thead><tbody>{body}</tbody></table>")
        elif re.match(r"\s*([-*]|\d+\.)\s+", line):
            flush()
            ordered = bool(re.match(r"\s*\d+\.", line))
            items = []
            while i < len(lines) and re.match(r"\s*([-*]|\d+\.)\s+", lines[i]):
                items.append("<li>" + _inline(re.sub(r"\s*([-*]|\d+\.)\s+", "", lines[i], count=1)) + "</li>")
                i += 1
            i -= 1
            tag = "ol" if ordered else "ul"
            out.append(f"<{tag}>{''.join(items)}</{tag}>")
        elif not line.strip():
            flush()
        else:
            para.append(line.strip())
        i += 1
    flush()
    return "\n".join(out)


# ---------------------------------------------------------------------------
# Data assembly
# ---------------------------------------------------------------------------


def _downsample(values: list, n: int = CURVE_POINTS) -> list:
    if len(values) <= n:
        return values
    step = (len(values) - 1) / (n - 1)
    return [values[round(k * step)] for k in range(n)]


def load_curve(path_text: str | None, base: Path) -> tuple[dict | None, str | None]:
    """Curve file: JSON object of equal-length numeric series, one of them "step". Returns (curve, problem)."""
    if not path_text:
        return None, "未记录曲线文件"
    path = Path(path_text)
    path = path if path.is_absolute() else base / path
    if not path.is_file():
        return None, f"曲线文件缺失：{path_text}"
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(data, dict) or "step" not in data:
            raise ValueError("missing step series")
        return {k: _downsample(v) for k, v in data.items() if isinstance(v, list)}, None
    except (ValueError, OSError) as exc:
        return None, f"曲线文件无法读取：{path_text}（{exc}）"


def collect(db_path: Path) -> dict:
    snap = ResearchDB(db_path, "web_builder/site").export_snapshot()
    root = db_path.parent
    tables, edges = snap["tables"], snap["edges"]
    project = tables["project"][0] if tables["project"] else None
    if project is None:
        raise ResearchDBError("the database has no project yet")

    docs = {}
    for d in tables["document"]:
        path = root / "docs" / d["path"]
        exists = path.is_file()
        hash_ok = None if d["status"] == "draft" else (exists and sha256_file(path) == d.get("sha256"))
        docs[d["id"]] = {
            "id": d["id"], "path": d["path"], "title": d["title"], "type": d["doc_type"], "status": d["status"],
            "summary": d.get("summary", ""), "author": f"{d['author_role']}/{d['author_id']}",
            "created": d["created_at"], "exists": exists, "hash_ok": hash_ok,
            "html": render_markdown(path.read_text(encoding="utf-8")) if exists else "",
        }

    describes = {}
    for e in edges["rel_describes"]:
        describes.setdefault(e["target_id"], []).append(e["source_id"])
    references = {}
    for e in edges["rel_references"]:
        references.setdefault(e["source_id"], []).append(e["target_id"])
    comparisons = {}
    for e in edges["rel_compared_with"]:
        comparisons.setdefault(e["source_id"], []).append(e)

    runs_by_exp = {}
    for r in tables["run"]:
        node_h = r["nodes_used"] * r["walltime_used_s"] / 3600 if r.get("nodes_used") and r.get("walltime_used_s") else None
        curve, problem = load_curve(r.get("curve_path"), root)
        runs_by_exp.setdefault(r["experiment_id"], []).append({
            "id": r["id"], "seed": r["seed"], "status": r["exec_status"], "valid": r.get("valid"),
            "attempt": r["attempt"], "job": r.get("job_id"), "metric": r.get("metric_value"),
            "secondary": r.get("secondary", {}), "node_h": node_h, "curve": curve, "curve_problem": problem,
            "log": r.get("log_path"),
        })

    harness = project.get("harness_ref")
    experiments = {}
    for x in tables["experiment"]:
        experiments[x["id"]] = {
            "id": x["id"], "hyp": x.get("hypothesis_id"), "kind": x["kind"], "method": x["method_name"],
            "seeds": x["seeds"], "verdict": x.get("verdict"), "mean": x.get("metric_mean"), "sd": x.get("metric_sd"),
            "code": x["code_ref"][:10], "evaluated": x.get("evaluated_at"), "created": x["created_at"],
            "stale_harness": bool(x.get("evaluated_at")) and x.get("harness_ref") != harness,
            "design": x["design_doc_id"], "result": x.get("result_doc_id"), "owner": x["owner"],
            "runs": sorted(runs_by_exp.get(x["id"], []), key=lambda r: r["seed"]),
            "comparisons": sorted(comparisons.get(x["id"], []), key=lambda c: c["role"]),
        }

    branches = {b["hypothesis_id"]: b for b in tables["branch"]}
    decisions = []
    based_on = {}
    for e in edges["rel_based_on"]:
        based_on.setdefault(e["source_id"], []).append(e["target_id"])
    for d in tables["decision"]:
        decisions.append({**{k: d.get(k) for k in ("id", "target_id", "field", "from_value", "to_value", "reason",
                                                   "doc_id", "decided_by", "decided_at")},
                          "based_on": based_on.get(d["id"], [])})
    decisions.sort(key=lambda d: (d["decided_at"], int(d["id"].split("-")[1])))

    nodes = []
    for h in tables["hypothesis"]:
        exps = sorted((e for e in experiments.values() if e["hyp"] == h["id"]), key=lambda e: int(e["id"].split("-")[1]))
        evaluated = [e for e in exps if e["kind"] == "method" and e["verdict"] and not e["stale_harness"]]
        latest = evaluated[-1] if evaluated else None
        b = branches.get(h["id"])
        nodes.append({
            "id": h["id"], "title": h["title"], "statement": h["statement"], "parent": h["parent_id"],
            "status": h["status"], "exp_status": h["experiment_status"], "novelty": h["novelty_recheck"],
            "theory": h["theory_recheck"], "priority": h["priority"], "reason": h.get("status_reason", ""),
            "doc": h["doc_id"], "references": sorted(references.get(h["id"], [])),
            "notes": sorted(describes.get(h["id"], [])), "created": h["created_at"],
            "times": {k: h.get(k) for k in NODE_TIMES},
            "experiments": [e["id"] for e in exps], "latest": latest and latest["id"],
            "branch": b and {"name": b["name"], "status": b["status"], "base": b["base_commit"][:10],
                             "head": (b.get("head_commit") or "")[:10]},
            "go": h["experiment_status"] == "beats_sota" and h["novelty_recheck"] == h["theory_recheck"] == "pass",
        })

    attention = []
    for e in experiments.values():
        if e["verdict"] == "close":
            attention.append({"kind": "待扩展seed", "id": e["hyp"], "text": f"{e['id']} 判定为差不多，需扩展到3个seed"})
        if e["verdict"] == "needs_rld":
            attention.append({"kind": "需要RLD复核", "id": e["hyp"], "text": f"{e['id']} 的统计代码无法判定，等待RLD决定"})
        if e["stale_harness"]:
            attention.append({"kind": "框架已更换", "id": e["hyp"] or e["id"], "text": f"{e['id']} 用旧框架判定，结果不可比"})
        for r in e["runs"]:
            if r["status"] == "unknown":
                attention.append({"kind": "作业状态未知", "id": r["id"], "text": f"{r['id']} 执行状态 unknown"})
            if r["valid"] and r["curve_problem"]:
                attention.append({"kind": "曲线缺失", "id": r["id"], "text": f"{r['id']}：{r['curve_problem']}"})
    for n in nodes:
        latest = n["latest"] and experiments[n["latest"]]
        if latest and latest["verdict"] in ("no_gain", "beats_parent", "beats_sota") and latest["verdict"] != n["exp_status"]:
            attention.append({"kind": "结论待更新", "id": n["id"],
                              "text": f"{n['id']} 最新判定为 {latest['verdict']}，节点结论仍为 {n['exp_status']}"})
    for t in tables["task"]:
        if t["status"] in ("open", "in_progress", "delivered", "rejected"):
            attention.append({"kind": "任务", "id": t["id"],
                              "text": f"{t['id']}（{t['kind']}，{t['assignee_role']}/{t.get('assignee_id') or '未指派'}）：{t['status']}"})
    for d in docs.values():
        if d["hash_ok"] is False:
            attention.append({"kind": "文档完整性", "id": d["id"], "text": f"{d['id']} {d['path']} 与登记的哈希不一致或文件缺失"})

    node_hours = sum(r["node_h"] or 0 for e in experiments.values() for r in e["runs"])
    return {
        "meta": {**snap["meta"], "generated_at": now_utc()},
        "project": {k: v for k, v in project.items() if k != "_table"},
        "docs": docs, "nodes": nodes, "experiments": experiments, "decisions": decisions,
        "tasks": [{k: v for k, v in t.items() if k != "_table"} for t in tables["task"]],
        "attention": attention, "node_hours": round(node_hours, 2),
        "active_worktrees": sorted(b["worktree_path"] for b in tables["branch"]
                                   if b["status"] == "active" and b.get("worktree_path")),
        "screen_seeds": _screen_seeds(experiments, project),
    }


def summary(data: dict, db_path: Path) -> dict:
    """Compact view of collect()'s data for tools that show progress elsewhere (the Claude Code mod): counts,
    the tree with each node's latest comparison, attention items, and the paths a guard should protect."""
    root, project = db_path.resolve().parent, data["project"]
    nodes = []
    for n in data["nodes"]:
        latest = n["latest"] and data["experiments"][n["latest"]]
        deltas = {c["role"]: c["delta_mean"] for c in latest["comparisons"]} if latest else {}
        nodes.append({k: n[k] for k in ("id", "title", "parent", "status", "exp_status", "novelty", "theory", "go")}
                     | {"verdict": latest and latest["verdict"], "seeds": latest and len(latest["seeds"]),
                        "vs_sota": deltas.get("sota"), "vs_parent": deltas.get("parent", deltas.get("sota")),
                        "concluded_at": n["times"]["concluded_at"]})
    count = lambda key: {v: sum(1 for n in nodes if n[key] == v) for v in sorted({n[key] for n in nodes})}
    harness = project.get("harness_paths") or []
    return {
        "meta": data["meta"], "db_path": str(db_path.resolve()),
        "project": {k: project.get(k) for k in ("id", "title", "status", "stage", "sota_experiment_id", "go_margin",
                                                 "harness_ref", "repo_path")},
        "counts": {"status": count("status"), "exp_status": count("exp_status"),
                   "go": sum(n["go"] for n in nodes), "node_hours": data["node_hours"],
                   "screen_seeds": data["screen_seeds"]},
        "nodes": nodes, "attention": data["attention"],
        "guards": {
            "frozen_docs": sorted(str(root / "docs" / d["path"]) for d in data["docs"].values() if d["status"] != "draft"),
            "harness": sorted(f"{wt.rstrip('/')}/{p.strip('/')}" for wt in data["active_worktrees"] for p in harness),
        },
    }


def summary_or_empty(db_path: Path) -> dict:
    """summary(), or for a database whose project record the RLD has not created yet (just after
    /research-tree init) the same shape with project null and only the documents to guard."""
    snap = ResearchDB(db_path, "web_builder/site").export_snapshot()
    if snap["tables"]["project"]:
        return summary(collect(db_path), db_path)
    root = db_path.resolve().parent
    return {
        "meta": {**snap["meta"], "generated_at": now_utc()}, "db_path": str(db_path.resolve()), "project": None,
        "counts": {"status": {}, "exp_status": {}, "go": 0, "node_hours": 0, "screen_seeds": None},
        "nodes": [], "attention": [],
        "guards": {"frozen_docs": sorted(str(root / "docs" / d["path"]) for d in snap["tables"]["document"]
                                         if d["status"] != "draft"), "harness": []},
    }


def _screen_seeds(experiments: dict, project: dict) -> int | None:
    sota = experiments.get(project.get("sota_experiment_id") or "")
    if not sota or not sota["runs"] or sota["runs"][0]["node_h"] is None:
        return None
    cost, n = sota["runs"][0]["node_h"], 1
    while n < project["gate_seeds"] and (n + 1) * cost < project["screen_budget_node_h"]:
        n += 1
    return n


# ---------------------------------------------------------------------------
# Page
# ---------------------------------------------------------------------------


def render_page(data: dict) -> str:
    payload = json.dumps(data, ensure_ascii=False, separators=(",", ":"))
    payload = payload.replace("<", "\\u003c").replace(">", "\\u003e").replace("&", "\\u0026")
    title = html.escape(data["project"]["title"])
    return (PAGE.replace("__TITLE__", title)
                .replace("__VERSION__", str(data["meta"]["data_version"]))
                .replace("__DATA__", payload))


def page_version(page: Path) -> int | None:
    if not page.is_file():
        return None
    m = VERSION_RE.search(page.read_text(encoding="utf-8", errors="replace")[:4000])
    return int(m.group(1)) if m else None


def build(db_path: Path, out: Path) -> dict:
    data = collect(db_path)
    out.parent.mkdir(parents=True, exist_ok=True)
    if out.is_file():
        shutil.copyfile(out, out.with_name("previous.html"))
    tmp = out.with_suffix(".tmp")
    tmp.write_text(render_page(data), encoding="utf-8")
    tmp.replace(out)
    return data


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="Build the offline research progress page.")
    p.add_argument("--db", type=Path, required=True)
    p.add_argument("--out", type=Path, help="default: <db dir>/site/index.html")
    p.add_argument("--check", action="store_true", help="only report whether the page is up to date")
    p.add_argument("--summary", action="store_true", help="print a compact JSON summary instead of building")
    args = p.parse_args(argv)
    out = args.out or args.db.parent / "site" / "index.html"
    try:
        if args.check:
            current = ResearchDB(args.db, "web_builder/site").export_snapshot()["meta"]["data_version"]
            built = page_version(out)
            print(json.dumps({"page_version": built, "db_version": current, "stale": built != current}))
            return 0 if built == current else 1
        if args.summary:
            print(json.dumps(summary_or_empty(args.db), ensure_ascii=False))
            return 0
        data = build(args.db, out)
    except ResearchDBError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    print(f"built {out} (data_version {data['meta']['data_version']}, {len(data['nodes'])} nodes, "
          f"{len(data['attention'])} attention items)")
    return 0


PAGE = r"""<!doctype html>
<html lang="zh">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta name="data-version" content="__VERSION__">
<title>__TITLE__ · 研究进度</title>
<style>
:root { --bg:#f7f7f5; --panel:#fff; --ink:#1d1d1f; --muted:#6b6b70; --line:#dedede; --accent:#2f6fde;
  --pending:#9a9aa0; --verifying:#d08a00; --expandable:#1f8a4c; --prunable:#c0392b; --go:#7b3fe4; --warn:#b3261e; }
@media (prefers-color-scheme: dark) { :root { --bg:#151517; --panel:#1f1f22; --ink:#ececee; --muted:#a0a0a8;
  --line:#34343a; --accent:#7aa7ff; --pending:#8a8a92; --verifying:#f0b030; --expandable:#45c47c; --prunable:#ef6b5b;
  --go:#b48cff; --warn:#ff8a80; } }
* { box-sizing:border-box; }
body { margin:0; background:var(--bg); color:var(--ink); font:14px/1.5 system-ui,-apple-system,"Segoe UI",sans-serif; }
header { padding:12px 16px; background:var(--panel); border-bottom:1px solid var(--line); }
header h1 { margin:0; font-size:18px; } header .sub { color:var(--muted); font-size:12px; }
.fiction { display:inline-block; margin-left:8px; padding:0 6px; border:1px solid var(--warn); color:var(--warn); border-radius:4px; font-size:12px; }
nav { display:flex; gap:4px; flex-wrap:wrap; padding:8px 16px; background:var(--panel); border-bottom:1px solid var(--line); position:sticky; top:0; z-index:2; }
nav button { border:1px solid var(--line); background:transparent; color:var(--ink); padding:6px 12px; border-radius:6px; cursor:pointer; }
nav button.on { background:var(--accent); color:#fff; border-color:var(--accent); }
main { padding:16px; max-width:1300px; margin:0 auto; }
section.view { display:none; } section.view.on { display:block; }
.cards { display:grid; grid-template-columns:repeat(auto-fit,minmax(170px,1fr)); gap:10px; margin-bottom:16px; }
.card { background:var(--panel); border:1px solid var(--line); border-radius:8px; padding:10px 12px; }
.card .k { color:var(--muted); font-size:12px; } .card .v { font-size:20px; font-weight:600; }
.panel { background:var(--panel); border:1px solid var(--line); border-radius:8px; padding:12px; margin-bottom:16px; overflow-x:auto; }
h2 { font-size:16px; margin:0 0 8px; } h3 { font-size:14px; margin:12px 0 6px; }
table { border-collapse:collapse; width:100%; font-size:13px; } th,td { border-bottom:1px solid var(--line); padding:4px 6px; text-align:left; vertical-align:top; }
th { color:var(--muted); font-weight:500; cursor:default; } th.sort { cursor:pointer; }
.badge { display:inline-block; padding:0 6px; border-radius:10px; font-size:12px; border:1px solid currentColor; margin-right:4px; white-space:nowrap; }
.s-pending{color:var(--pending)} .s-verifying{color:var(--verifying)} .s-expandable{color:var(--expandable)} .s-prunable{color:var(--prunable)}
.v-no_gain{color:var(--prunable)} .v-beats_parent{color:var(--expandable)} .v-beats_sota{color:var(--go)} .v-close{color:var(--verifying)} .v-needs_rld{color:var(--warn)}
.go { color:var(--go); font-weight:600; } .warn { color:var(--warn); } .muted { color:var(--muted); }
.layout { display:grid; grid-template-columns:minmax(260px,420px) 1fr; gap:16px; }
@media (max-width: 860px) { .layout { grid-template-columns:1fr; } }
.tree ul { list-style:none; padding-left:16px; margin:0; } .tree > ul { padding-left:0; }
.tree li { margin:3px 0; } .tree .node { cursor:pointer; padding:2px 4px; border-radius:4px; }
.tree .node:hover, .tree .node.sel { background:color-mix(in srgb, var(--accent) 15%, transparent); }
.tree .hidden { display:none; } .toggle { cursor:pointer; color:var(--muted); width:14px; display:inline-block; }
.controls { display:flex; gap:8px; flex-wrap:wrap; margin-bottom:8px; } .controls input, .controls select { padding:4px 6px; border:1px solid var(--line); border-radius:4px; background:var(--panel); color:var(--ink); }
.doc { border-top:1px solid var(--line); margin-top:8px; padding-top:8px; } .doc pre { background:var(--bg); padding:8px; overflow-x:auto; }
details summary { cursor:pointer; color:var(--accent); }
.heat td.num { text-align:right; font-variant-numeric:tabular-nums; }
svg text { fill:var(--muted); font-size:11px; } svg .axis { stroke:var(--line); } svg .margin { stroke:var(--go); stroke-dasharray:4 3; }
.legend span { margin-right:12px; } .swatch { display:inline-block; width:10px; height:10px; border-radius:2px; margin-right:4px; vertical-align:middle; }
</style>
</head>
<body>
<header>
  <h1 id="title"></h1>
  <div class="sub" id="sub"></div>
</header>
<nav id="tabs"></nav>
<main>
  <section class="view" id="v-overview"></section>
  <section class="view" id="v-tree"></section>
  <section class="view" id="v-results"></section>
  <section class="view" id="v-findings"></section>
  <section class="view" id="v-timeline"></section>
  <section class="view" id="v-attention"></section>
</main>
<script id="data" type="application/json">__DATA__</script>
<script>
"use strict";
const D = JSON.parse(document.getElementById("data").textContent);
const P = D.project, NODES = Object.fromEntries(D.nodes.map(n => [n.id, n])), EXP = D.experiments;
const esc = s => String(s ?? "").replace(/[&<>"']/g, c => ({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[c]));
const fmt = (x, d = 3) => x == null ? "未知" : (Math.round(x * 10 ** d) / 10 ** d).toString();
const LABEL = {pending:"待验证", verifying:"验证中", expandable:"可拓展", prunable:"可消灭", todo:"未开始", running:"进行中",
  no_gain:"无提升", beats_parent:"优于父节点", beats_sota:"优于SOTA", close:"差不多", needs_rld:"需要RLD复核",
  pass:"通过", fail:"未通过", active:"进行中", go:"GO", not_go:"NOT GO", stopped:"已停止"};
const L = k => LABEL[k] || k || "未知";
const badge = (k, cls) => `<span class="badge ${cls}">${esc(L(k))}</span>`;
const docLink = id => id && D.docs[id] ? `<a href="#" data-doc="${esc(id)}">${esc(D.docs[id].title)}</a> <span class="muted">${esc(id)}</span>` : (id ? esc(id) + " <span class='warn'>(未登记)</span>" : "未知");

function header() {
  document.getElementById("title").innerHTML = esc(P.title) + (P.title.includes("虚构") ? '<span class="fiction">虚构示例</span>' : "");
  document.title = P.title + " · 研究进度";
  document.getElementById("sub").textContent =
    `${P.id} · ${P.stage === "stage1" ? "阶段1" : "阶段2"} · 状态 ${L(P.status)} · data_version ${D.meta.data_version} · 生成于 ${D.meta.generated_at}`;
}

const TABS = [["overview","总览"],["tree","假说树"],["results","实验结果"],["findings","发现"],["timeline","时间线"],["attention",`待处理 (${D.attention.length})`]];
function tabs() {
  const nav = document.getElementById("tabs");
  nav.innerHTML = TABS.map(([k, t]) => `<button data-tab="${k}">${esc(t)}</button>`).join("");
  nav.addEventListener("click", e => { const k = e.target.dataset.tab; if (k) show(k); });
  const [k, id] = location.hash.slice(1).split("/");  // #tree/H-0003 opens a node
  show(k || "overview");
  if (id && NODES[id]) nodeDetail(id);
}
function show(k) {
  if (!document.getElementById("v-" + k)) k = "overview";
  document.querySelectorAll("section.view").forEach(s => s.classList.toggle("on", s.id === "v-" + k));
  document.querySelectorAll("nav button").forEach(b => b.classList.toggle("on", b.dataset.tab === k));
  history.replaceState(null, "", "#" + k + (k === "tree" && selected ? "/" + selected : ""));
}

function overview() {
  const count = (arr, key) => arr.reduce((m, x) => (m[x[key]] = (m[x[key]] || 0) + 1, m), {});
  const byStatus = count(D.nodes, "status"), byExp = count(D.nodes, "exp_status");
  const sota = EXP[P.sota_experiment_id];
  const cards = [
    ["节点", D.nodes.length], ["验证中", byStatus.verifying || 0], ["可拓展", byStatus.expandable || 0],
    ["可消灭", byStatus.prunable || 0], ["优于SOTA", byExp.beats_sota || 0], ["GO候选", D.nodes.filter(n => n.go).length],
    ["已用资源", D.node_hours + " node·h"], ["筛选seed数", D.screen_seeds ?? "未知"],
  ];
  const recent = D.decisions.slice(-10).reverse();
  document.getElementById("v-overview").innerHTML = `
    <div class="cards">${cards.map(([k, v]) => `<div class="card"><div class="k">${esc(k)}</div><div class="v">${esc(v)}</div></div>`).join("")}</div>
    <div class="panel"><h2>研究设定</h2><table>
      <tr><th>研究目标</th><td>${docLink(P.goal_doc_id)}</td></tr>
      <tr><th>最小实验设定</th><td>${docLink(P.min_setup_doc_id)}</td></tr>
      <tr><th>主指标</th><td>${esc(P.primary_metric)}（${P.metric_direction === "higher" ? "越高越好" : "越低越好"}${P.metric_is_percent ? "，百分比" : ""}）</td></tr>
      <tr><th>其他比较指标</th><td>${esc((P.secondary_metrics || []).join("、"))}</td></tr>
      <tr><th>SOTA基线</th><td>${sota ? `${esc(sota.id)} ${esc(sota.method)}，均值 ${fmt(sota.mean)} ± ${fmt(sota.sd)}（seeds ${esc(sota.seeds.join(", "))}）` : '<span class="warn">未设置</span>'}</td></tr>
      <tr><th>优于SOTA门槛</th><td>${P.gate_seeds} 个seed，主指标领先 &gt; ${P.go_margin}</td></tr>
      <tr><th>筛选预算</th><td>${P.screen_budget_node_h} node·h；单次运行上限 ${P.max_nodes} nodes × ${P.max_walltime_s / 3600} h</td></tr>
      <tr><th>冻结框架</th><td>${P.harness_ref ? esc(P.harness_ref.slice(0, 10)) + "：" + esc((P.harness_paths || []).join("、")) : '<span class="warn">未冻结</span>'}</td></tr>
    </table></div>
    <div class="panel"><h2>最近的决定</h2>${decisionTable(recent)}</div>`;
}

function decisionTable(list) {
  if (!list.length) return '<p class="muted">暂无</p>';
  return `<table><thead><tr><th>时间</th><th>对象</th><th>变更</th><th>理由</th><th>依据</th></tr></thead><tbody>${list.map(d => `
    <tr><td>${esc(d.decided_at)}</td><td>${nodeRef(d.target_id)}</td><td>${esc(d.field)}：${esc(L(d.from_value))} → <b>${esc(L(d.to_value))}</b></td>
    <td>${esc(d.reason)}${d.doc_id ? "<br>" + docLink(d.doc_id) : ""}</td><td>${d.based_on.map(x => D.docs[x] ? docLink(x) : esc(x)).join("<br>")}</td></tr>`).join("")}</tbody></table>`;
}
const nodeRef = id => NODES[id] ? `<a href="#" data-node="${esc(id)}">${esc(id)}</a>` : esc(id);

// ---- tree ----
let selected = null;
function tree() {
  const kids = {};
  D.nodes.forEach(n => (kids[n.parent] = kids[n.parent] || []).push(n));
  const li = n => {
    const c = kids[n.id] || [];
    return `<li data-id="${esc(n.id)}" data-status="${esc(n.status)}" data-text="${esc((n.id + " " + n.title + " " + n.statement).toLowerCase())}">
      <span class="toggle">${c.length ? "▾" : ""}</span><span class="node" data-node="${esc(n.id)}">
      <b>${esc(n.id)}</b> ${esc(n.title)} ${badge(n.status, "s-" + n.status)}${n.exp_status !== "todo" ? badge(n.exp_status, "v-" + n.exp_status) : ""}${n.go ? '<span class="badge go">GO候选</span>' : ""}
      ${deltaText(n)}</span>${c.length ? `<ul>${c.map(li).join("")}</ul>` : ""}</li>`;
  };
  document.getElementById("v-tree").innerHTML = `<div class="layout"><div class="panel tree">
      <div class="controls"><input id="q" placeholder="搜索 ID/标题/假说"><select id="st"><option value="">全部状态</option>
      ${["pending","verifying","expandable","prunable"].map(s => `<option value="${s}">${L(s)}</option>`).join("")}</select></div>
      <ul><li><b>${esc(P.id)}</b> <span class="muted">项目根（SOTA基线 ${esc(P.sota_experiment_id || "未设置")}）</span><ul>${(kids[P.id] || []).map(li).join("")}</ul></li></ul>
    </div><div class="panel" id="detail"><p class="muted">点击左侧节点查看详情。</p></div></div>`;
  const q = document.getElementById("q"), st = document.getElementById("st");
  const filter = () => {
    const text = q.value.trim().toLowerCase(), s = st.value;
    document.querySelectorAll(".tree li[data-id]").forEach(el => {
      const self = (!text || el.dataset.text.includes(text)) && (!s || el.dataset.status === s);
      const sub = [...el.querySelectorAll("li[data-id]")].some(c => (!text || c.dataset.text.includes(text)) && (!s || c.dataset.status === s));
      el.classList.toggle("hidden", !(self || sub));
    });
  };
  q.addEventListener("input", filter); st.addEventListener("change", filter);
  document.querySelector("#v-tree .tree").addEventListener("click", e => {
    const t = e.target.closest(".toggle");
    if (t && t.textContent) { const ul = t.parentElement.querySelector(":scope > ul"); ul.classList.toggle("hidden"); t.textContent = ul.classList.contains("hidden") ? "▸" : "▾"; }
  });
}
function deltaText(n) {
  const e = n.latest && EXP[n.latest]; if (!e) return "";
  return e.comparisons.map(c => `<span class="muted">${c.role === "sota" ? "vs SOTA" : "vs 父"} ${c.delta_mean >= 0 ? "+" : ""}${fmt(c.delta_mean)}</span>`).join(" ");
}
function nodeDetail(id) {
  const n = NODES[id]; if (!n) return;
  selected = id;
  history.replaceState(null, "", "#tree/" + id);
  document.querySelectorAll(".tree .node").forEach(el => el.classList.toggle("sel", el.dataset.node === id));
  const exps = n.experiments.map(x => EXP[x]);
  const hist = D.decisions.filter(d => d.target_id === id);
  document.getElementById("detail").innerHTML = `
    <h2>${esc(n.id)} ${esc(n.title)}</h2>
    <p>${esc(n.statement)}</p>
    <table>
      <tr><th>节点状态</th><td>${badge(n.status, "s-" + n.status)} ${esc(n.reason)}</td></tr>
      <tr><th>实验结论</th><td>${badge(n.exp_status, "v-" + n.exp_status)} 最新判定实验：${esc(n.latest || "无")}</td></tr>
      <tr><th>复核（优于SOTA后）</th><td>新颖性 ${esc(n.novelty === "pending" ? "未复核" : L(n.novelty))}；理论 ${esc(n.theory === "pending" ? "未复核" : L(n.theory))}</td></tr>
      <tr><th>关键时间</th><td>${keyTimes(n)}</td></tr>
      <tr><th>父节点</th><td>${n.parent === P.id ? "项目根（与SOTA比较）" : nodeRef(n.parent)}</td></tr>
      <tr><th>代码分支</th><td>${n.branch ? `${esc(n.branch.name)}（${esc(n.branch.status)}，基准 ${esc(n.branch.base)}${n.branch.head ? "，交还 " + esc(n.branch.head) : ""}）` : "无"}</td></tr>
      <tr><th>假说文档</th><td>${docLink(n.doc)}</td></tr>
      <tr><th>创建时参考的相关研究</th><td>${n.references.map(docLink).join("<br>") || "无"}</td></tr>
      ${n.notes.length ? `<tr><th>其他文档</th><td>${n.notes.map(docLink).join("<br>")}</td></tr>` : ""}
    </table>
    <h3>实验</h3>${exps.length ? exps.map(expBlock).join("") : '<p class="muted">暂无实验</p>'}
    <h3>决定历史</h3>${decisionTable(hist)}
    <div class="doc"><h3>假说文档全文</h3>${D.docs[n.doc] ? D.docs[n.doc].html : '<p class="warn">文档缺失</p>'}</div>`;
}
const TIME_LABEL = {created_at: "创建", started_at: "开始验证", first_experiment_at: "首次实验", first_result_at: "首次判定",
  beats_sota_at: "优于SOTA", concluded_at: "完成"};
function since(t0, t) {
  const h = (Date.parse(t) - Date.parse(t0)) / 3.6e6;
  return isNaN(h) ? "" : h < 1 ? `+${Math.round(h * 60)} 分钟` : h < 48 ? `+${h.toFixed(1)} 小时` : `+${(h / 24).toFixed(1)} 天`;
}
function keyTimes(n) {
  return Object.entries(TIME_LABEL).map(([k, label]) => {
    const t = n.times[k];
    if (!t) return `${label}：<span class="muted">${k === "concluded_at" && n.status === "verifying" ? "进行中" : "尚无"}</span>`;
    return `${label}：${esc(t)}${k === "created_at" ? "" : ` <span class="muted">(${since(n.times.created_at, t)})</span>`}`;
  }).join("<br>");
}
function expBlock(e) {
  const runs = e.runs.map(r => `<tr><td>${r.seed}</td><td>${esc(r.status)}${r.attempt > 1 ? "（第" + r.attempt + "次）" : ""}</td><td>${r.valid ? "有效" : r.valid === false ? '<span class="warn">无效</span>' : "未验收"}</td>
    <td class="num">${fmt(r.metric)}</td>${(P.secondary_metrics || []).map(k => `<td class="num">${fmt(r.secondary?.[k])}</td>`).join("")}<td class="num">${fmt(r.node_h, 2)}</td>
    <td>${r.curve_problem ? `<span class="warn">${esc(r.curve_problem)}</span>` : "有"}</td></tr>`).join("");
  return `<div class="panel"><b>${esc(e.id)}</b> ${esc(e.method)} · ${esc(e.kind)} · seeds ${esc(e.seeds.join(", "))} · 代码 ${esc(e.code)}
    ${e.verdict ? badge(e.verdict, "v-" + e.verdict) : '<span class="muted">未判定</span>'}${e.stale_harness ? '<span class="warn">框架已更换，结果不可比</span>' : ""}
    <div>设计：${docLink(e.design)}；结果：${docLink(e.result)}</div>
    <table class="heat"><thead><tr><th>seed</th><th>执行</th><th>验收</th><th>${esc(P.primary_metric)}</th>${(P.secondary_metrics || []).map(k => `<th>${esc(k)}</th>`).join("")}<th>node·h</th><th>曲线</th></tr></thead><tbody>${runs}</tbody></table>
    ${e.comparisons.length ? `<table class="heat"><thead><tr><th>比较</th><th>配对seed</th><th>Δ${esc(P.primary_metric)}</th>${(P.secondary_metrics || []).map(k => `<th>Δ${esc(k)}</th>`).join("")}<th>过SOTA门槛</th></tr></thead><tbody>
      ${e.comparisons.map(c => `<tr><td>${c.role === "sota" ? "SOTA " : "父节点 "}${esc(c.target_id)}</td><td>${c.n_paired}</td>${heatCell(c.delta_mean)}${(P.secondary_metrics || []).map(k => heatCell(c.deltas[k])).join("")}<td>${c.role === "sota" ? (c.passes_gate ? '<span class="go">是</span>' : "否") : ""}</td></tr>`).join("")}</tbody></table>` : ""}
    ${curveSvg(e)}</div>`;
}
function heatCell(v) {
  if (v == null) return '<td class="num muted">未知</td>';
  const a = Math.min(Math.abs(v) / 0.5, 1) * 0.45, col = v > 0 ? "31,138,76" : v < 0 ? "192,57,43" : "128,128,128";
  return `<td class="num" style="background:rgba(${col},${a})">${v >= 0 ? "+" : ""}${fmt(v)}</td>`;
}

// ---- curves: mean over seeds of this experiment vs. its comparison targets ----
const PALETTE = ["var(--accent)", "var(--go)", "var(--verifying)", "var(--expandable)"];
function meanCurve(exp, key) {
  const cs = exp.runs.filter(r => r.curve && r.curve[key]).map(r => r.curve);
  if (!cs.length) return null;
  const len = Math.min(...cs.map(c => c[key].length));
  return {x: cs[0].step.slice(0, len), y: Array.from({length: len}, (_, i) => cs.reduce((s, c) => s + c[key][i], 0) / cs.length)};
}
function curveSvg(e) {
  const keys = Object.keys((e.runs.find(r => r.curve) || {}).curve || {}).filter(k => k !== "step");
  if (!keys.length) return "";
  const series = [[e.id + " " + e.method, e]].concat(e.comparisons.map(c => [(c.role === "sota" ? "SOTA " : "父节点 ") + c.target_id, EXP[c.target_id]]));
  return keys.map(key => {
    const lines = series.map(([name, x], i) => ({name, color: PALETTE[i % PALETTE.length], c: x && meanCurve(x, key)})).filter(s => s.c);
    const xs = lines.flatMap(s => s.c.x), ys = lines.flatMap(s => s.c.y);
    const [x0, x1, y0, y1] = [Math.min(...xs), Math.max(...xs), Math.min(...ys), Math.max(...ys)];
    const W = 520, H = 160, m = 34, sx = x => m + (x - x0) / ((x1 - x0) || 1) * (W - 2 * m), sy = y => H - 20 - (y - y0) / ((y1 - y0) || 1) * (H - 40);
    return `<div><svg viewBox="0 0 ${W} ${H}" width="100%" style="max-width:${W}px" role="img" aria-label="${esc(key)} 曲线">
      <line class="axis" x1="${m}" y1="${H - 20}" x2="${W - m}" y2="${H - 20}"/><line class="axis" x1="${m}" y1="10" x2="${m}" y2="${H - 20}"/>
      <text x="${m}" y="${H - 6}">${fmt(x0, 0)}</text><text x="${W - m}" y="${H - 6}" text-anchor="end">${fmt(x1, 0)} step</text>
      <text x="2" y="14">${fmt(y1)}</text><text x="2" y="${H - 22}">${fmt(y0)}</text><text x="${W / 2}" y="14" text-anchor="middle">${esc(key)}（各seed均值）</text>
      ${lines.map(s => `<polyline fill="none" stroke="${s.color}" stroke-width="1.6" points="${s.c.x.map((x, i) => sx(x).toFixed(1) + "," + sy(s.c.y[i]).toFixed(1)).join(" ")}"/>`).join("")}
      </svg><div class="legend">${lines.map(s => `<span><i class="swatch" style="background:${s.color}"></i>${esc(s.name)}</span>`).join("")}</div></div>`;
  }).join("");
}

// ---- results ----
function results() {
  const rows = D.nodes.map(n => ({n, e: n.latest && EXP[n.latest]})).filter(r => r.e);
  const cmp = (e, role) => e.comparisons.find(c => c.role === role) || (role === "parent" ? e.comparisons.find(c => c.role === "sota") : null);
  const W = 680, rowH = 26, H = rows.length * rowH + 40, m = 190, right = 60;
  const vals = rows.flatMap(({e}) => { const c = cmp(e, "sota"); return c ? [c.delta_mean - (c.delta_sd || 0), c.delta_mean + (c.delta_sd || 0)] : []; }).concat([0, P.go_margin]);
  const lo = Math.min(...vals), hi = Math.max(...vals), sx = v => m + (v - lo) / ((hi - lo) || 1) * (W - m - right);
  const dots = rows.map(({n, e}, i) => { const c = cmp(e, "sota"), y = 24 + i * rowH; if (!c) return "";
    return `<text x="4" y="${y + 4}">${esc(n.id)} ${esc(n.title.slice(0, 14))}</text>
      <line x1="${sx(c.delta_mean - (c.delta_sd || 0))}" x2="${sx(c.delta_mean + (c.delta_sd || 0))}" y1="${y}" y2="${y}" stroke="var(--muted)"/>
      <circle cx="${sx(c.delta_mean)}" cy="${y}" r="5" fill="${c.passes_gate ? "var(--go)" : c.delta_mean > 0 ? "var(--expandable)" : "var(--prunable)"}"><title>${esc(e.id)}：Δ=${fmt(c.delta_mean)}，n=${c.n_paired}</title></circle>
      <text x="${W - 4}" y="${y + 4}" text-anchor="end">n=${c.n_paired}</text>`; }).join("");
  document.getElementById("v-results").innerHTML = `
    <div class="panel"><h2>相对SOTA的主指标配对差（各节点最新判定实验）</h2>
      <svg viewBox="0 0 ${W} ${H}" width="100%" style="max-width:${W}px" role="img" aria-label="相对SOTA配对差">
        <line class="axis" x1="${sx(0)}" x2="${sx(0)}" y1="8" y2="${H - 16}"/><text x="${sx(0)}" y="${H - 4}" text-anchor="middle">0</text>
        <line class="margin" x1="${sx(P.go_margin)}" x2="${sx(P.go_margin)}" y1="8" y2="${H - 16}"/><text x="${sx(P.go_margin)}" y="${H - 4}" text-anchor="start">门槛 ${P.go_margin}</text>
        ${dots}</svg>
      <div class="legend"><span><i class="swatch" style="background:var(--go)"></i>过门槛</span><span><i class="swatch" style="background:var(--expandable)"></i>领先但未过门槛</span><span><i class="swatch" style="background:var(--prunable)"></i>不领先</span><span class="muted">误差线：±配对差标准差</span></div></div>
    <div class="panel"><h2>相对父节点的各指标配对差（正值 = 更好）</h2>
      <table class="heat" id="rtab"><thead><tr><th class="sort" data-k="id">节点</th><th>判定</th><th class="sort" data-k="seeds">seeds</th><th class="sort" data-k="p">Δ${esc(P.primary_metric)}</th>
      ${(P.secondary_metrics || []).map(k => `<th class="sort" data-k="${esc(k)}">Δ${esc(k)}</th>`).join("")}<th>比较对象</th></tr></thead><tbody></tbody></table>
      <p class="muted">“无提升”= 所有指标都不更好；顶层节点的父节点为SOTA基线。点击表头排序，点击节点打开详情。</p></div>`;
  let key = "p", dir = -1;
  const body = () => {
    const data = rows.map(({n, e}) => { const c = cmp(e, "parent"); return {n, e, c, id: n.id, seeds: e.seeds.length, p: c?.delta_mean, ...(c?.deltas || {})}; });
    data.sort((a, b) => ((a[key] ?? -1e9) > (b[key] ?? -1e9) ? 1 : -1) * dir);
    document.querySelector("#rtab tbody").innerHTML = data.map(r => `<tr><td>${nodeRef(r.id)} ${esc(r.n.title)}</td><td>${badge(r.e.verdict, "v-" + r.e.verdict)}</td><td>${r.seeds}</td>
      ${heatCell(r.c?.delta_mean)}${(P.secondary_metrics || []).map(k => heatCell(r.c?.deltas[k])).join("")}<td>${esc(r.c?.target_id || "")}</td></tr>`).join("");
  };
  document.querySelector("#rtab thead").addEventListener("click", ev => { const k = ev.target.dataset.k; if (!k) return; dir = key === k ? -dir : -1; key = k; body(); });
  body();
}

// ---- findings ----
function findings() {
  const go = D.nodes.filter(n => n.exp_status === "beats_sota"), up = D.nodes.filter(n => n.exp_status === "beats_parent");
  const dead = D.nodes.filter(n => n.status === "prunable");
  const card = n => { const e = n.latest && EXP[n.latest], s = e && e.comparisons.find(c => c.role === "sota");
    return `<div class="panel"><h3>${nodeRef(n.id)} ${esc(n.title)} ${n.go ? '<span class="badge go">GO候选</span>' : ""}</h3><p>${esc(n.statement)}</p>
      <p>${s ? `相对SOTA ${s.delta_mean >= 0 ? "+" : ""}${fmt(s.delta_mean)}（${s.n_paired} seeds${s.passes_gate ? "，过门槛" : ""}）` : ""}
      ${n.exp_status === "beats_sota" ? ` · 新颖性复核 ${esc(n.novelty === "pending" ? "未复核" : L(n.novelty))} · 理论复核 ${esc(n.theory === "pending" ? "未复核" : L(n.theory))}` : ""}</p>
      ${D.docs[n.doc]?.summary && D.docs[n.doc].summary !== n.statement ? `<p class="muted">${esc(D.docs[n.doc].summary)}</p>` : ""}</div>`; };
  const why = n => { const d = [...D.decisions].reverse().find(x => x.target_id === n.id && x.field === "status" && x.to_value === "prunable");
    const user = d && d.based_on.some(b => D.docs[b]?.type === "user_instruction");
    const kind = user ? "用户决定放弃" : n.exp_status === "no_gain" ? "无提升" : (n.novelty === "fail" || n.theory === "fail") ? "复核未通过" : "其他";
    return `<tr><td>${nodeRef(n.id)} ${esc(n.title)}</td><td>${esc(kind)}</td><td>${esc(d ? d.reason : n.reason)}</td></tr>`; };
  document.getElementById("v-findings").innerHTML = `
    <h2>候选方法（优于SOTA）</h2>${go.length ? go.map(card).join("") : '<p class="muted">暂无</p>'}
    <h2>可拓展方向（优于父节点）</h2>${up.length ? up.map(card).join("") : '<p class="muted">暂无</p>'}
    <div class="panel"><h2>负结果（已消灭的节点）</h2>${dead.length ? `<table><thead><tr><th>节点</th><th>原因</th><th>理由</th></tr></thead><tbody>${dead.map(why).join("")}</tbody></table>` : '<p class="muted">暂无</p>'}</div>`;
}

// ---- timeline ----
function timeline() {
  const ev = [];
  D.nodes.forEach(n => {
    ev.push([n.created, "创建节点", `${nodeRef(n.id)} ${esc(n.title)}`]);
    for (const k of ["first_experiment_at", "first_result_at", "beats_sota_at", "concluded_at"])
      if (n.times[k]) ev.push([n.times[k], "节点" + TIME_LABEL[k], `${nodeRef(n.id)} ${esc(n.title)}（${since(n.created, n.times[k])}）`]);
  });
  Object.values(EXP).forEach(e => { ev.push([e.created, "创建实验", `${esc(e.id)} ${esc(e.method)}（${esc(e.kind)}）`]);
    if (e.evaluated) ev.push([e.evaluated, "统计判定", `${esc(e.id)} ${e.verdict ? badge(e.verdict, "v-" + e.verdict) : "基线结果"}`]); });
  D.decisions.forEach(d => ev.push([d.decided_at, "决定", `${nodeRef(d.target_id)} ${esc(d.field)} → <b>${esc(L(d.to_value))}</b>：${esc(d.reason)}`]));
  ev.sort((a, b) => a[0] < b[0] ? 1 : -1);
  document.getElementById("v-timeline").innerHTML = `<div class="panel"><table><thead><tr><th>时间</th><th>事件</th><th>内容</th></tr></thead><tbody>
    ${ev.map(([t, k, s]) => `<tr><td>${esc(t)}</td><td>${esc(k)}</td><td>${s}</td></tr>`).join("")}</tbody></table></div>`;
}

function attention() {
  const groups = {};
  D.attention.forEach(a => (groups[a.kind] = groups[a.kind] || []).push(a));
  document.getElementById("v-attention").innerHTML = Object.keys(groups).length
    ? Object.entries(groups).map(([k, items]) => `<div class="panel"><h2>${esc(k)}（${items.length}）</h2><ul>${items.map(a => `<li>${NODES[a.id] ? nodeRef(a.id) + " " : ""}${esc(a.text)}</li>`).join("")}</ul></div>`).join("")
    : '<p class="muted">没有待处理事项。</p>';
}

function docDialog(id) {
  const d = D.docs[id]; if (!d) return;
  const w = document.getElementById("detail") || document.getElementById("v-overview");
  show(w.id === "detail" ? "tree" : "overview");
  w.insertAdjacentHTML("afterbegin", `<div class="panel doc" id="doc-${esc(id)}"><h2>${esc(d.title)}</h2>
    <p class="muted">${esc(id)} · ${esc(d.path)} · ${esc(d.type)} · ${esc(d.status)} · ${esc(d.author)} · ${esc(d.created)}
    ${d.hash_ok === false ? ' · <span class="warn">与登记的哈希不一致或文件缺失</span>' : ""}</p>${d.html || '<p class="warn">文件缺失</p>'}</div>`);
  w.scrollIntoView();
}

document.addEventListener("click", e => {
  const n = e.target.closest("[data-node]"), d = e.target.closest("[data-doc]");
  if (n) { e.preventDefault(); show("tree"); nodeDetail(n.dataset.node); }
  else if (d) { e.preventDefault(); docDialog(d.dataset.doc); }
});
header(); overview(); tree(); results(); findings(); timeline(); attention(); tabs();
</script>
</body>
</html>
"""


if __name__ == "__main__":
    sys.exit(main())
