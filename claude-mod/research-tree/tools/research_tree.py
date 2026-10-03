"""Set up and steer a research project in the current directory (what /research-tree runs).

The project is marked by `.research-tree.json` in the working directory, which records the research root
(research/<project-id>/ with research_tree.db and docs/), the database path and the start-up phase:

  planning               init done; the RLD turns the user's plan into goal, setup, nodes and the root task
  awaiting_confirmation  the RLD asked the user to confirm the plan
  confirmed              the user confirmed; workers may start on the root node

The project id defaults to the uv project's name (pyproject.toml [project].name, which `uv init .` takes
from the directory), else the directory's name, so research/<id>/ matches the uv project.

Usage (run with the project's own interpreter, ./.venv/bin/python, after `uv init .`):
    research_tree.py init PLAN.md [--project-id NAME]     # directories, database, registry, plan as instruction
    research_tree.py instruction --text "..." [--understanding "..."] [--about ID ...]
    research_tree.py phase [--set awaiting_confirmation|confirmed]
    research_tree.py status                               # the marker as JSON
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import tomllib
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "schema"))

import create_db  # noqa: E402
from research_db import ResearchDB, ResearchDBError, table_of  # noqa: E402

MARKER = Path(".research-tree.json")
PHASES = ("planning", "awaiting_confirmation", "confirmed")
SUBDIRS = ("docs/project/reports", "docs/instructions", "docs/literature", "docs/hypotheses", "docs/tasks",
           "docs/baselines", "docs/workflow", "messages", "snapshots", "cache/literature", "outputs", "site")
# Node workers are named after their node (worker/h0007) and only send; the root's worker also receives.
AGENTS = ["ui/ui", "rld/main", "worker/root", "assistant/a1", "web_builder/site"]


class TreeError(Exception):
    pass


def now_utc() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def read_marker(cwd: Path) -> dict:
    path = cwd / MARKER
    if not path.is_file():
        raise TreeError(f"no research project here: {path} not found; run /research-tree init <plan.md>")
    return json.loads(path.read_text(encoding="utf-8"))


def write_marker(cwd: Path, marker: dict) -> None:
    tmp = cwd / (MARKER.name + ".tmp")
    tmp.write_text(json.dumps(marker, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    tmp.replace(cwd / MARKER)


def default_project_id(cwd: Path) -> str:
    """The uv project's name when there is one, else the directory's name."""
    pyproject = cwd / "pyproject.toml"
    if pyproject.is_file():
        name = tomllib.loads(pyproject.read_text(encoding="utf-8")).get("project", {}).get("name")
        if name:
            return str(name)
    return cwd.resolve().name


def next_instruction_path(docs: Path) -> str:
    numbers = [int(m.group(1)) for p in (docs / "instructions").glob("UI-*.v*.md")
               if (m := re.match(r"UI-(\d+)\.v\d+\.md$", p.name))]
    return f"instructions/UI-{max(numbers, default=0) + 1:04d}.v1.md"


def register_instruction(root: Path, verbatim: str, understanding: str, kind: str, about: list[str]) -> dict:
    """Write and register a user instruction the way the UI does: the user's words verbatim, then the reading."""
    ui = ResearchDB(root / "research_tree.db", "ui/ui")
    rel = next_instruction_path(root / "docs")
    fence = "~~~~" if "```" in verbatim else "```"
    body = (f"## 用户原话\n\n{fence}\n{verbatim.rstrip()}\n{fence}\n\n## UI的理解\n\n{understanding}\n\n"
            f"## 类型\n\n{kind}\n\n## 登记时间\n\n{now_utc()}\n")
    (root / "docs" / rel).write_text(body, encoding="utf-8")
    first_line = next((line.strip("# ").strip() for line in verbatim.splitlines() if line.strip()), kind)
    doc_id = ui.register_document(rel, "user_instruction", first_line[:80] or kind, summary=understanding[:300],
                                  about=about)
    ui.set_document_current(doc_id)
    return {"doc_id": doc_id, "path": rel}


def init(cwd: Path, plan: Path, project_id: str | None) -> dict:
    if (cwd / MARKER).exists():
        raise TreeError(f"{cwd / MARKER} already exists; this directory already holds a research project")
    if not plan.is_file():
        raise TreeError(f"plan file not found: {plan}")
    project_id = project_id or default_project_id(cwd)
    try:
        valid = table_of(project_id) == "project"
    except ResearchDBError:
        valid = False
    if not valid:
        raise TreeError(f"project id {project_id!r} must be letters, digits, _ . - and must not look like another "
                        "record's id (H-, E-, BR-, D-, DEC-, T-); pass --project-id")
    root = cwd / "research" / project_id
    if root.exists():
        raise TreeError(f"{root} already exists")
    for sub in SUBDIRS:
        (root / sub).mkdir(parents=True)
    db = root / "research_tree.db"
    create_db.create_db(db)
    (root / "agents.json").write_text(json.dumps(
        {agent: {"channel": "native", "thread": f"claude-code:{agent}"} for agent in AGENTS}, indent=1),
        encoding="utf-8")
    plan_text = plan.read_text(encoding="utf-8")
    instruction = register_instruction(
        root, plan_text, f"立项：研究目标与初始假说、实验设计见原文（{plan}）。由RLD整理为目标、最小实验设定、初始节点和根节点任务，请用户确认后再启动worker。",
        "指令（立项）", [])
    marker = {"project_id": project_id, "root": str(root), "db": str(db), "plan": str(plan.resolve()),
              "plan_instruction": instruction, "phase": "planning", "created_at": now_utc(), "confirmed_at": None}
    write_marker(cwd, marker)
    return marker


def set_phase(cwd: Path, phase: str) -> dict:
    marker = read_marker(cwd)
    order = {p: i for i, p in enumerate(PHASES)}
    if phase not in order:
        raise TreeError(f"phase must be one of {PHASES}")
    if order[phase] < order[marker["phase"]]:
        raise TreeError(f"phase {marker['phase']} does not go back to {phase}")
    marker["phase"] = phase
    if phase == "confirmed" and not marker.get("confirmed_at"):
        marker["confirmed_at"] = now_utc()
    write_marker(cwd, marker)
    return marker


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="Set up and steer a research project in the current directory.")
    sub = p.add_subparsers(dest="cmd", required=True)
    i = sub.add_parser("init")
    i.add_argument("plan", type=Path)
    i.add_argument("--project-id")
    ins = sub.add_parser("instruction")
    ins.add_argument("--text", required=True, help="the user's words, verbatim")
    ins.add_argument("--understanding", default="", help="the UI's reading of them")
    ins.add_argument("--kind", default="指令")
    ins.add_argument("--about", nargs="*", default=[])
    ph = sub.add_parser("phase")
    ph.add_argument("--set", choices=PHASES)
    sub.add_parser("status")
    args = p.parse_args(argv)
    cwd = Path.cwd()
    try:
        if args.cmd == "init":
            result = init(cwd, args.plan, args.project_id)
        elif args.cmd == "instruction":
            marker = read_marker(cwd)
            result = register_instruction(Path(marker["root"]), args.text, args.understanding or args.text,
                                          args.kind, args.about)
        elif args.cmd == "phase":
            result = set_phase(cwd, args.set) if args.set else read_marker(cwd)
        else:
            result = read_marker(cwd)
    except (TreeError, ResearchDBError) as exc:
        print(json.dumps({"ok": False, "error": str(exc)}, ensure_ascii=False))
        return 2
    print(json.dumps({"ok": True, "result": result}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
