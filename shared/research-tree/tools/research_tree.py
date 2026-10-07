"""Set up and steer a research project in the current directory (what /research-tree runs).

The project is marked by `.research-tree.json` in the working directory, which records the research root
(research/<project-id>/ with research_tree.db and docs/), the database path and the start-up phase:

  planning               init done; the RLD turns the user's plan into goal, setup, nodes and the root task
  awaiting_confirmation  the RLD asked the user to confirm the plan
  confirmed              the user confirmed; workers may start on the root node

The project id defaults to the uv project's name (pyproject.toml [project].name, which `uv init .` takes
from the directory), else the directory's name, so research/<id>/ matches the uv project.

The project configuration is research-tree.yaml beside the marker (tools/project_config.py). Until it is first
applied the file itself is in effect; `config apply` registers it as docs/project/config.v<N>.yaml (the version
in effect from then on, recorded in the marker) and writes its budget and gates into the project record.

Before init, tools/prepare.sh makes the directory a uv project with the tools' dependencies and copies the plan
template (plan.md) and the default configuration (research-tree.yaml) for the user to fill in.

Usage (run with the project's own interpreter, ./.venv/bin/python, after prepare):
    research_tree.py init [PLAN.md] [--project-id NAME] [--config FILE]   # directories, database, registry, plan, config
    research_tree.py instruction --text "..." [--understanding "..."] [--about ID ...]
    research_tree.py phase [--set awaiting_confirmation|confirmed]
    research_tree.py config [show]                        # the configuration in effect and the file's state
    research_tree.py config apply [--words "..."] [--require-project]
    research_tree.py ui reply|confirm|instruction|question|submit --run RUN ...  # the UI agent's outbox
    research_tree.py requirement draft|list|submit ...    # the UI's requirement drafts and their documents
    research_tree.py query METHOD ['{"kwarg": ...}']      # the UI's read-only access to the database
    research_tree.py agent-log --agent ID --actor ROLE/ID --event requested|observed --model M
    research_tree.py status                               # the marker as JSON

init takes plan.md unless given another plan; a plan made from the template must have its research goal and
initial hypotheses filled in. It uses the directory's research-tree.yaml (from prepare), --config FILE to start
from another file, or the default configuration when there is none.
It also copies the cleanup template to research-tree-cleanup.py beside it, unless the project has one: the
project's own script that says which run outputs are disposable (research_db.run_cleanup runs it).

The UI agent of the research window acts only through its outbox: each run appends its reply and actions to
research/<id>/cache/ui/<run>.jsonl, and the research-tree mod carries them out when the run ends (it records
the person's message verbatim; the agent only adds its reading). A requirement the person and the UI clarify
over several messages lives as a draft in cache/ui/requirements/; submitting it (an outbox action) registers
docs/requirements/REQ-<n>.v<k>.md with the fields of the rules' requirement record and the person's cited
messages verbatim, taken from the window log messages/window.jsonl that the mod keeps.
"""

from __future__ import annotations

import argparse
import json
import re
import shutil
import sys
import tomllib
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "schema"))

import create_db  # noqa: E402
import notify  # noqa: E402
import project_config  # noqa: E402
from project_config import CONFIG_NAME, ConfigError  # noqa: E402
from research_db import (CAP_FIELDS, CLEANUP_SCRIPT, CLEANUP_TEMPLATE, EVIDENCE_DOC_FIELDS,  # noqa: E402
                         GATE_FIELDS, READ_METHODS, ResearchDB, ResearchDBError, describe, table_of)

MARKER = Path(".research-tree.json")
PHASES = ("planning", "awaiting_confirmation", "confirmed")
SUBDIRS = ("docs/project/reports", "docs/instructions", "docs/requirements", "docs/literature", "docs/hypotheses", "docs/tasks",
           "docs/baselines", "docs/workflow", "messages", "snapshots", "cache/literature", "outputs", "site", "logs")
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


PLAN_MARKER = "<!-- research-tree:plan -->"
PLAN_REQUIRED = ("研究目标", "初始假说")


def check_plan(text: str, plan: Path) -> None:
    """A plan made from the template (prepare) has its required sections filled; comments do not count. A plan
    written without the template is taken as it is."""
    if PLAN_MARKER not in text:
        return
    sections = dict(re.findall(r"^## +(.+?)[ \t]*\n(.*?)(?=^## |\Z)", text, re.M | re.S))
    empty = [name for name in PLAN_REQUIRED if not re.sub(r"<!--.*?-->", "", sections.get(name, ""), flags=re.S).strip()]
    if empty:
        raise TreeError(f"{plan}: fill in {', '.join(empty)} first (the template's comments are only hints)")


def init(cwd: Path, plan: Path, project_id: str | None, config: Path | None = None) -> dict:
    if (cwd / MARKER).exists():
        raise TreeError(f"{cwd / MARKER} already exists; this directory already holds a research project")
    if not plan.is_file():
        raise TreeError(f"plan file not found: {plan}")
    check_plan(plan.read_text(encoding="utf-8"), plan)
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
    config_file = cwd / CONFIG_NAME
    if config is None and config_file.is_file():
        config = config_file  # the one prepare copied and the user edited
    if config is None:
        config_text = project_config.template_text()
    else:
        if not config.is_file():
            raise TreeError(f"config file not found: {config}")
        if config.resolve() != config_file.resolve() and config_file.exists():
            raise TreeError(f"{config_file} already exists; delete it or pass it as --config")
        config_text = config.read_text(encoding="utf-8")
        project_config.db_fields(project_config.parse(config_text, str(config)))
    if config is None or config.resolve() != config_file.resolve():
        config_file.write_text(config_text, encoding="utf-8")
    # The project's own cleanup script, from the plugin's template; an existing one is the project's and stays.
    if not (cwd / CLEANUP_SCRIPT).exists():
        shutil.copyfile(CLEANUP_TEMPLATE, cwd / CLEANUP_SCRIPT)
    for sub in SUBDIRS:
        (root / sub).mkdir(parents=True)
    db = root / "research_tree.db"
    create_db.create_db(db)
    (root / "agents.json").write_text(json.dumps(AGENTS, indent=1), encoding="utf-8")
    plan_text = plan.read_text(encoding="utf-8")
    instruction = register_instruction(
        root, plan_text, f"立项：研究目标与初始假说、实验设计见原文（{plan}）。由RLD整理为目标、最小实验设定、初始节点和根节点任务，请用户确认后再启动worker。",
        "指令（立项）", [])
    marker = {"project_id": project_id, "root": str(root), "db": str(db), "plan": str(plan.resolve()),
              "plan_instruction": instruction, "phase": "planning", "created_at": now_utc(), "confirmed_at": None,
              "config": None}
    write_marker(cwd, marker)
    config_parsed = project_config.parse(config_text)
    if config_parsed["version"] == 2:  # the metric specification the Leader passes to create_project
        register_metric_spec(cwd, marker, ResearchDB(db, "rld/main"), config_parsed, None)
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


def show_config(cwd: Path) -> dict:
    """The configuration in effect (the registered version, else the file, else the template), whether the file
    has changes not yet applied, and why the file cannot be used if it cannot."""
    marker = read_marker(cwd) if (cwd / MARKER).is_file() else {}
    file = cwd / CONFIG_NAME
    text = file.read_text(encoding="utf-8") if file.is_file() else None
    file_config, file_error = None, None
    if text is not None:
        try:
            file_config = project_config.parse(text)
            project_config.db_fields(file_config)
        except ConfigError as exc:
            file_error = str(exc)
    registered = marker.get("config")
    if registered:
        registered_text = (Path(marker["root"]) / "docs" / registered["path"]).read_text(encoding="utf-8")
        effective, source = project_config.parse(registered_text, registered["path"]), registered["doc_id"]
        pending = text != registered_text
    elif file_config is not None:
        effective, source, pending = file_config, "file", False
    else:
        effective, source, pending = project_config.defaults(), "template", False
    return {"file": str(file), "exists": text is not None, "source": source, "registered": registered,
            "pending": pending, "file_error": file_error, "effective": effective,
            "db_fields": project_config.db_fields(effective), "metric_spec": marker.get("metric_spec"),
            "protocol_requirements": (project_config.protocol_requirements(effective)
                                      if effective["version"] == 2 else None)}


def apply_config(cwd: Path, actor: str, words: str | None = None, require_project: bool = False) -> dict:
    """Put research-tree.yaml in effect: register it as a new config version when it changed, write the budget
    and gates into the project record, and register the user's words as an instruction when anything changed."""
    marker = read_marker(cwd)
    root, file = Path(marker["root"]), cwd / CONFIG_NAME
    if not file.is_file():
        raise TreeError(f"{file} not found")
    text = file.read_text(encoding="utf-8")
    config = project_config.parse(text)
    fields = project_config.db_fields(config)
    rld = ResearchDB(root / "research_tree.db", actor)
    projects = rld.find("project")
    project = projects[0] if projects else None
    if require_project and project is None:
        raise TreeError("the RLD has not created the project record yet (create_project)")
    spec = register_metric_spec(cwd, marker, rld, config, project)
    if project is not None and spec and spec["doc_id"] != project.get("metric_spec_doc_id"):
        fields["metric_spec_doc_id"] = spec["doc_id"]
    changes = {k: v for k, v in fields.items() if project is not None and project.get(k) != v}
    if project is not None and config["version"] == 2:
        check_protocol(root, project, config)
    if "gate_seeds" in changes and "seeds" not in changes:
        seeds = list(project["seeds"])
        while len(seeds) < changes["gate_seeds"]:
            seeds.append(max(seeds, default=-1) + 1)
        changes["seeds"] = seeds[:changes["gate_seeds"]]
    locked = sorted(set(changes) & set(GATE_FIELDS))
    if locked and rld.find("experiment"):
        raise TreeError(f"experiments exist, so {', '.join(locked)} can no longer change; set them back in "
                        f"{CONFIG_NAME} to {', '.join(f'{k}={project[k]!r}' for k in locked)}")

    if project is not None and changes:
        try:  # before anything is registered: a refused change leaves the configuration in effect as it was
            rld.check_project_changes(**changes)
        except ResearchDBError as exc:
            raise TreeError(f"{CONFIG_NAME} cannot take effect: {exc}. A new go_margin or gate_seeds needs a metric "
                            "specification (and protocol) that state the same gate; the RLD registers those first, "
                            "then apply again") from None
    registered = marker.get("config")
    new_version = registered is None or (root / "docs" / registered["path"]).read_text(encoding="utf-8") != text
    if new_version:
        numbers = [int(m.group(1)) for p in (root / "docs" / "project").glob("config.v*.yaml")
                   if (m := re.match(r"config\.v(\d+)\.yaml$", p.name))]
        rel = f"project/config.v{max(numbers, default=0) + 1}.yaml"
        (root / "docs" / rel).write_text(text, encoding="utf-8")
        doc_id = rld.register_document(rel, "config", "项目配置", summary=f"{CONFIG_NAME}：开发与实验平台、资源预算、阶段1门槛、子代理模型",
                                       about=[project["id"]] if project else [])
        rld.set_document_current(doc_id)
        if registered:
            rld.supersede_document(registered["doc_id"], doc_id)
        registered = marker["config"] = {"doc_id": doc_id, "path": rel}
        write_marker(cwd, marker)
    instruction = None
    # The file is the user's (agents may not write it): a cap it raises or a document it changes rests on it.
    if not words and project is not None and set(changes) & set(CAP_FIELDS + EVIDENCE_DOC_FIELDS):
        words = f"（用户的 {CONFIG_NAME}，经 config apply 或立项确认生效）"
    if words and (new_version or changes):  # first: a new metric specification rests on the user's instruction
        updated = f"；项目记录中的 {', '.join(sorted(changes))} 随之更新" if changes else ""
        instruction = register_instruction(root, words, f"项目配置改为 {registered['path']}"
                                           f"（{registered['doc_id']}）{updated}。", "配置变更",
                                           [project["id"]] if project else [])
    if project is not None and (changes or project.get("config_doc_id") != registered["doc_id"]):
        extra = ({"user_instruction_doc_id": instruction["doc_id"]}
                 if instruction and set(changes) & set(CAP_FIELDS + EVIDENCE_DOC_FIELDS) else {})
        rld.update_project(**changes, config_doc_id=registered["doc_id"], **extra)
    return {"config": registered, "new_version": new_version, "updated_fields": changes,
            "instruction": instruction, "effective": config}


def register_metric_spec(cwd: Path, marker: dict, rld: ResearchDB, config: dict, project: dict | None) -> dict | None:
    """A version-2 configuration states the metric specification: register it as the metric_spec document when its
    content is new (rld/main, current; the previous version superseded). Returns {doc_id, path} or None (v1)."""
    if config["version"] != 2:
        return None
    root = Path(marker["root"])
    text = json.dumps(project_config.metric_spec_document(config), ensure_ascii=False, indent=1) + "\n"
    current = marker.get("metric_spec")
    if current and (root / "docs" / current["path"]).read_text(encoding="utf-8") == text:
        return current
    numbers = [int(m.group(1)) for p in (root / "docs" / "project").glob("metric-spec.v*.json")
               if (m := re.match(r"metric-spec\.v(\d+)\.json$", p.name))]
    rel = f"project/metric-spec.v{max(numbers, default=0) + 1}.json"
    (root / "docs" / rel).write_text(text, encoding="utf-8")
    doc_id = rld.register_document(rel, "metric_spec", "指标规范（research-tree.yaml）",
                                   summary="research-tree.yaml 的 metric_specs：第一个为主指标",
                                   about=[project["id"]] if project else [])
    rld.set_document_current(doc_id)
    if current:
        rld.supersede_document(current["doc_id"], doc_id)
    marker["metric_spec"] = {"doc_id": doc_id, "path": rel}
    write_marker(cwd, marker)
    return marker["metric_spec"]


def check_protocol(root: Path, project: dict, config: dict) -> None:
    """The Leader's protocol states what the configuration fixes (profile and confirmation settings) the same way."""
    if not project.get("protocol_doc_id"):
        return
    doc = ResearchDB(root / "research_tree.db", "ui/ui").get(project["protocol_doc_id"])
    protocol = json.loads((root / "docs" / doc["path"]).read_text(encoding="utf-8"))
    defaults = {"profile": "stage1_confirmed", "confirmation_seeds": [], "min_confirmation_pairs": 3,
                "max_confirmation_candidates": None, "require_artifact_import": False}
    wrong = {k: (protocol.get(k, defaults[k]), v) for k, v in project_config.protocol_requirements(config).items()
             if protocol.get(k, defaults[k]) != v}
    if wrong:
        raise TreeError(f"the protocol {project['protocol_doc_id']} differs from {CONFIG_NAME}: "
                        + "; ".join(f"{k} is {a!r}, the configuration says {b!r}" for k, (a, b) in wrong.items())
                        + ". The RLD registers a protocol version that agrees, then apply again")


REQ_RE = re.compile(r"^REQ-[0-9]{4}$")
# The fields of a requirement record (rules, section 3), in the order the document shows them.
REQ_FIELDS = {
    "goal": "目标与理由", "scope": "范围", "constraints": "约束", "acceptance": "验收", "priority": "优先级",
    "open": "授权与待决定项", "changes": "版本与变更",
}


def window_messages(root: Path) -> dict[str, dict]:
    """The research window's log (messages/window.jsonl, written by the mod): id -> entry."""
    log = root / "messages" / "window.jsonl"
    if not log.is_file():
        return {}
    entries = (json.loads(line) for line in log.read_text(encoding="utf-8").splitlines() if line.strip())
    return {e["id"]: e for e in entries if e.get("id")}


def requirement_dir(cwd: Path) -> tuple[Path, Path]:
    root = Path(read_marker(cwd)["root"])
    return root, root / "cache" / "ui" / "requirements"


def draft_requirement(cwd: Path, req: str | None, title: str | None, fields: dict, messages: list[str],
                      about: list[str]) -> dict:
    """Create or update the UI's working draft of one requirement; given fields replace, messages and about add.
    A draft that was submitted opens again for its next version."""
    root, drafts = requirement_dir(cwd)
    window = window_messages(root)
    for mid in messages:
        if window.get(mid, {}).get("role") != "user":
            raise TreeError(f"{mid} is not a message of the person in the research window")
    drafts.mkdir(parents=True, exist_ok=True)
    if req is None:
        numbers = [int(p.stem[4:]) for p in drafts.glob("REQ-*.json")]
        req = f"REQ-{max(numbers, default=0) + 1:04d}"
        draft = {"id": req, "title": "", **{k: "" for k in REQ_FIELDS}, "messages": [], "about": [],
                 "status": "open", "version": 0, "doc_id": None, "created_at": now_utc()}
    else:
        if not REQ_RE.match(req) or not (drafts / f"{req}.json").is_file():
            raise TreeError(f"no requirement draft {req}")
        draft = json.loads((drafts / f"{req}.json").read_text(encoding="utf-8"))
    if title is not None:
        draft["title"] = title
    draft.update({k: v for k, v in fields.items() if v is not None})
    draft["messages"] += [m for m in messages if m not in draft["messages"]]
    draft["about"] += [a for a in about if a not in draft["about"]]
    draft["status"], draft["updated_at"] = "open", now_utc()
    (drafts / f"{req}.json").write_text(json.dumps(draft, ensure_ascii=False, indent=1), encoding="utf-8")
    return draft


def list_requirements(cwd: Path) -> list[dict]:
    _, drafts = requirement_dir(cwd)
    return [json.loads(p.read_text(encoding="utf-8")) for p in sorted(drafts.glob("REQ-*.json"))]


def submit_requirement(cwd: Path, req: str) -> dict:
    """Register the draft as the next version of its requirement document: the fields, then every cited message
    of the person verbatim. The previous version is superseded."""
    root, drafts = requirement_dir(cwd)
    if not REQ_RE.match(req) or not (drafts / f"{req}.json").is_file():
        raise TreeError(f"no requirement draft {req}")
    draft = json.loads((drafts / f"{req}.json").read_text(encoding="utf-8"))
    if draft["status"] != "open":
        raise TreeError(f"{req} has no changes since version {draft['version']}")
    missing = [REQ_FIELDS[k] for k in ("goal", "scope") if not draft[k].strip()]
    if not draft["title"].strip() or missing or not draft["messages"]:
        raise TreeError(f"{req} needs a title, {', '.join(missing) or 'its fields'} and the person's messages it rests on")
    window = window_messages(root)
    version = draft["version"] + 1
    rel = f"requirements/{req}.v{version}.md"
    parts = [f"# {req} {draft['title']}（v{version}）\n"]
    parts += [f"## {label}\n\n{draft[key].strip() or '未知'}\n" for key, label in REQ_FIELDS.items()]
    parts.append("## 用户原话\n")
    for mid in draft["messages"]:
        text = window[mid]["text"]
        fence = "~~~~" if "```" in text else "```"
        parts.append(f"{mid}（{window[mid].get('ts', '')}）\n\n{fence}\n{text.rstrip()}\n{fence}\n")
    (root / "docs" / "requirements").mkdir(parents=True, exist_ok=True)
    (root / "docs" / rel).write_text("\n".join(parts), encoding="utf-8")
    ui = ResearchDB(root / "research_tree.db", "ui/ui")
    doc_id = ui.register_document(rel, "user_instruction", f"{req} {draft['title']}"[:80],
                                  summary=draft["goal"].strip()[:300], about=draft["about"])
    ui.set_document_current(doc_id)
    if draft["doc_id"]:
        ui.supersede_document(draft["doc_id"], doc_id)
    draft.update(status="submitted", version=version, doc_id=doc_id, submitted_at=now_utc())
    (drafts / f"{req}.json").write_text(json.dumps(draft, ensure_ascii=False, indent=1), encoding="utf-8")
    return {"req": req, "version": version, "doc_id": doc_id, "path": rel, "title": draft["title"]}


UI_RUN_RE = re.compile(r"^[A-Za-z0-9_-]{1,64}$")


def ui_outbox(cwd: Path, run: str, entry: dict) -> dict:
    """Append one reply or action of the UI agent's run to its outbox, for the mod to carry out."""
    if not UI_RUN_RE.match(run):
        raise TreeError(f"--run {run!r} is not a UI run id")
    if entry["type"] in ("reply", "question") and not entry.get("text", "").strip():
        raise TreeError(f"{entry['type']} needs --text")
    outbox = Path(read_marker(cwd)["root"]) / "cache" / "ui" / f"{run}.jsonl"
    outbox.parent.mkdir(parents=True, exist_ok=True)
    with outbox.open("a", encoding="utf-8") as f:
        f.write(json.dumps(entry, ensure_ascii=False) + "\n")
    return {"outbox": str(outbox), **entry}


def query(cwd: Path, method: str, kwargs: dict):
    """A read of the research database as ui/ui: the UI's only way into it, so it cannot write."""
    if method not in READ_METHODS:
        raise TreeError(f"query reads only ({', '.join(READ_METHODS)}); {method} is not one of them")
    if method == "help":
        return describe(**kwargs)
    return getattr(ResearchDB(Path(read_marker(cwd)["db"]), "ui/ui"), method)(**kwargs)


AGENT_LOG = Path("logs") / "agent_models.jsonl"


def log_agent_model(root: Path, entry: dict) -> dict:
    """Records which model an agent run asked for (requested, at its start) or ran on (observed, from the host's
    runtime report): the evidence for rule 2's model records. Appends to logs/agent_models.jsonl."""
    record = {"ts": now_utc(), **{k: v for k, v in entry.items() if v not in (None, "")}}
    log = root / AGENT_LOG
    log.parent.mkdir(parents=True, exist_ok=True)
    with log.open("a", encoding="utf-8") as f:
        f.write(json.dumps(record, ensure_ascii=False) + "\n")
    return record


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="Set up and steer a research project in the current directory.")
    sub = p.add_subparsers(dest="cmd", required=True)
    i = sub.add_parser("init")
    i.add_argument("plan", type=Path, nargs="?", default=Path("plan.md"))
    i.add_argument("--project-id")
    i.add_argument("--config", type=Path, help="start from this configuration instead of the default")
    ins = sub.add_parser("instruction")
    ins.add_argument("--text", required=True, help="the user's words, verbatim")
    ins.add_argument("--understanding", default="", help="the UI's reading of them")
    ins.add_argument("--kind", default="指令")
    ins.add_argument("--about", nargs="*", default=[])
    ph = sub.add_parser("phase")
    ph.add_argument("--set", choices=PHASES)
    cf = sub.add_parser("config")
    cf.add_argument("action", nargs="?", choices=("show", "apply"), default="show")
    cf.add_argument("--actor", default="rld/main", help="the RLD identity that registers the configuration")
    cf.add_argument("--words", help="the user's words, registered as an instruction when the configuration changed")
    cf.add_argument("--require-project", action="store_true", help="fail unless the project record exists")
    ui = sub.add_parser("ui", help="the UI agent's outbox")
    ui.add_argument("action", choices=("reply", "confirm", "instruction", "question", "submit"))
    ui.add_argument("--run", required=True)
    ui.add_argument("--text", default="", help="reply: the answer to the person; question: the note to the RLD")
    ui.add_argument("--understanding", default="", help="instruction: the UI's reading of the person's words")
    ui.add_argument("--kind", default="指令", help="instruction: 指令, 偏好, 约束, 授权, ...")
    ui.add_argument("--about", nargs="*", default=[])
    ui.add_argument("--docs", nargs="*", default=[], help="question: registered document paths relative to docs/")
    ui.add_argument("--req", help="submit: the requirement draft, REQ-<n>")
    rq = sub.add_parser("requirement", help="the UI's requirement drafts")
    rq.add_argument("action", choices=("draft", "list", "submit"))
    rq.add_argument("--req", help="REQ-<n>; draft without it starts a new requirement")
    rq.add_argument("--title")
    for key, label in REQ_FIELDS.items():
        rq.add_argument(f"--{key}", help=label)
    rq.add_argument("--messages", nargs="*", default=[], help="ids of the person's messages it rests on (w-<n>)")
    rq.add_argument("--about", nargs="*", default=[])
    q = sub.add_parser("query", help="read the research database as the UI (read methods only)")
    q.add_argument("method")
    q.add_argument("kwargs", nargs="?", default="{}", help="JSON object of keyword arguments")
    al = sub.add_parser("agent-log", help="record an agent run's requested or observed model")
    al.add_argument("--agent", required=True, help="the host's id of the agent run")
    al.add_argument("--actor", required=True, help="<role>/<id> the run acts as")
    al.add_argument("--event", required=True, choices=("requested", "observed"))
    al.add_argument("--model", default="")
    al.add_argument("--effort", default="")
    nt = sub.add_parser("notify", help="POST a confirmation request or usage alert to notify.url (optional)")
    nt.add_argument("--kind", required=True, choices=notify.KINDS)
    nt.add_argument("--text", required=True)
    nt.add_argument("--docs", nargs="*", default=[])
    sub.add_parser("inbox", help="messages to the RLD that still wait for its receipt or answer")
    sub.add_parser("status")
    args = p.parse_args(argv)
    cwd = Path.cwd()
    try:
        if args.cmd == "init":
            result = init(cwd, args.plan, args.project_id, args.config)
        elif args.cmd == "instruction":
            marker = read_marker(cwd)
            result = register_instruction(Path(marker["root"]), args.text, args.understanding or args.text,
                                          args.kind, args.about)
        elif args.cmd == "phase":
            result = set_phase(cwd, args.set) if args.set else read_marker(cwd)
        elif args.cmd == "config":
            result = (apply_config(cwd, args.actor, args.words, args.require_project) if args.action == "apply"
                      else show_config(cwd))
        elif args.cmd == "ui":
            fields = {"reply": ("text",), "confirm": (), "instruction": ("understanding", "kind", "about"),
                      "question": ("text", "about", "docs"), "submit": ("req",)}[args.action]
            if args.action == "submit" and not (args.req and REQ_RE.match(args.req)):
                raise TreeError("submit needs --req REQ-<n>")
            result = ui_outbox(cwd, args.run, {"type": args.action, **{k: getattr(args, k) for k in fields}})
        elif args.cmd == "query":
            kwargs = json.loads(args.kwargs)
            if not isinstance(kwargs, dict):
                raise TreeError("kwargs must be a JSON object")
            result = query(cwd, args.method, kwargs)
        elif args.cmd == "agent-log":
            result = log_agent_model(Path(read_marker(cwd)["root"]), {
                "agent": args.agent, "actor": args.actor, "event": args.event, "model": args.model,
                "effort": args.effort})
        elif args.cmd == "notify":
            result = notify.send(Path(read_marker(cwd)["root"]), show_config(cwd)["effective"], args.kind, args.text,
                                 args.docs)
        elif args.cmd == "inbox":
            import build_site
            result = build_site.unanswered(Path(read_marker(cwd)["root"]))
        elif args.cmd == "requirement":
            if args.action == "draft":
                result = draft_requirement(cwd, args.req, args.title, {k: getattr(args, k) for k in REQ_FIELDS},
                                           args.messages, args.about)
            elif args.action == "submit":
                if not args.req:
                    raise TreeError("submit needs --req")
                result = submit_requirement(cwd, args.req)
            else:
                result = list_requirements(cwd)
        else:
            result = read_marker(cwd)
    except (TreeError, ResearchDBError, ConfigError, TypeError, json.JSONDecodeError) as exc:
        print(json.dumps({"ok": False, "error": str(exc)}, ensure_ascii=False))
        return 2
    print(json.dumps({"ok": True, "result": result}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
