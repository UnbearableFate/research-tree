#!/usr/bin/env python3
"""Codex workflow/context and file guards. This guardrail is not an OS security boundary."""
from __future__ import annotations

import fnmatch
import json
import os
import re
import shlex
import subprocess
import sys
import time
from pathlib import Path

from codex_state import actor_key, cache_dir, locked, project_dir, read_json, write_json

ROOT = Path(__file__).resolve().parents[1]
CONFIG = "research-tree.yaml"
SHELL_BOUNDARIES = {";", "&&", "||", "|", "&", "\n"}
REDIRECTS = re.compile(r"[<>]+|>\||&>|>&|<&")
WRITE_REDIRECTS = {">", ">>", ">|", "&>", ">&"}
WRITERS = {"rm", "mv", "dd", "truncate", "sqlite3", "shred", "tee"}
WILDCARD = re.compile(r"[*?[]")
HEREDOC = re.compile(r"(?<!<)<<(?!<)(-?)[ \t]*(['\"]?)([A-Za-z_][\w.-]*)\2")
PATCH_PATHS = re.compile(r"^\*\*\* (?:Add File|Update File|Delete File|Move to): (.+)$", re.M)
# The adapter's own entry points run as the identity they are given (codex_runtime.py --actor rld/main) or record
# what a hook observed; Codex starts them, a session's shell does not.
ADAPTER_ENTRIES = {"codex_runtime.py", "codex_cli.py", "codex_mcp.py", "codex_agent.py", "codex_hook.py"}
ADVISOR_READ_ONLY = "研究顾问只读文件与科学记录；返回建议与来源，由Leader保存。"
# research_db.READ_METHODS; the hook runs without the project's packages, so the list is repeated (a test keeps
# the two equal).
READ_METHODS = {"help", "get", "find", "edges", "children", "history", "go_candidates", "latest_result",
                "screen_seed_count", "export_snapshot", "verify_document", "resume_package", "cleanup_due",
                "get_eligibility", "evaluations", "preview_evaluation", "obligations", "budget_status",
                "reconcile_submission", "reviews", "context_pack", "relations", "review_basis", "material_usage", "memory_status", "repetition_advice"}
WORKFLOW = f"""research-tree 项目已启用。主会话是唯一 Research Leader。
读取 {ROOT / 'skills/research-tree/SKILL.md'} 与 {ROOT / 'rules/research-tree-rules.md'}。
只通过 research_db 修改研究数据库；已生效文档写新版本；节点不能修改冻结框架。
用户确认最小范围前不启动执行角色；确认后先assign_architect或assign_worker并分配对应任务，再research_control architect实现根节点框架与baseline，worker执行假说节点。
research_control explorer与analyst是只读顾问；Explorer持续提出可证伪候选，Analyst整理证据与下一实验建议，由Leader登记并作方向、预算、争议与最终GO/NOT GO决定。
执行角色使用独立Codex会话，根节点只用architect/root，worker只负责假说节点；主会话不以原生spawn_agent绕开身份/确认/并发门槛。
仅支持version 3配置与schema 23数据库，快速筛选/增量发现按候选准入，不等待整批发现或每次廉价筛选的模型审批；旧项目须明确迁移，不静默转换。
保留原始证据、方法身份、公平配对、预算与防重复门槛；positive_signal不是GO。选定少量候选、必要重复与控制后再独立确认，最后集中五维复核。
research_review立即返回ticket，稍后以同一ticket收取；等待期间推进独立工作，不重复启动。
需要用户决定时post_to_ui；主会话的明确授权同样有效。UI按需build/pane，只有交互需要时使用ui_path，不运行常驻UI。轻量摘要GO=null/eligibility_checked=false表示未检查，用get_eligibility核验。
用research_control inbox处理未确认事件；已收到后acknowledge，收到回执不再回回执。
"""


def deny(reason):
    return {"hookSpecificOutput": {"hookEventName": "PreToolUse", "permissionDecision": "deny",
                                    "permissionDecisionReason": f"research-tree: {reason}"}}


def operand(path, cwd):
    """A path operand as the shell reaches it: ~ expanded and the literal components resolved against cwd;
    components from the first shell wildcard on stay patterns (see reaches)."""
    parts = Path(os.path.expanduser(str(path))).parts
    first = next((i for i, part in enumerate(parts) if WILDCARD.search(part)), len(parts))
    literal = Path(*parts[:first])
    return (literal if literal.is_absolute() else cwd / literal).resolve().joinpath(*parts[first:])


def reaches(target, path, inside=False):
    """Whether target names path (inside: path or anything under it). A wildcard component matches one name, as
    in the shell, against the protected name itself: a WAL file that appears only while the database is open is
    protected before it exists."""
    if not WILDCARD.search(str(target)):
        return target == path or (inside and path in target.parents)
    if len(target.parts) < len(path.parts) or (len(target.parts) > len(path.parts) and not inside):
        return False
    return all(fnmatch.fnmatchcase(name, pattern) for pattern, name in zip(target.parts, path.parts))


def protected(path, cwd, summary, db, actor):
    target = operand(path, cwd)
    if reaches(target, db) or str(target).startswith(f"{db}-") or any(
            reaches(target, Path(f"{db}-{suffix}")) for suffix in ("wal", "shm", "journal")):
        return "不要直接改数据库文件；调用 research_db。"
    if reaches(target, db.parent.parent.parent / CONFIG) and actor != "rld/main":
        # the Leader edits it when the user asks (then research_control config apply with the user's words)
        return f"{CONFIG} 只由用户或按用户指示的 Leader（主会话）修改，{actor} 不写它；需要变更时交给 Leader。"
    guards = summary.get("guards", {})
    if any(reaches(target, Path(p).resolve()) for p in guards.get("frozen_docs", [])):
        return "这是已生效文档；写 vN+1 并登记为新版本。"
    if any(reaches(target, Path(prefix).resolve(), inside=True) for prefix in guards.get("harness", [])):
        return "节点不能修改冻结的实验框架或统计代码。"
    return None


def research_calls(tokens):
    """The research tools and adapter entry points among shell tokens: (script, actor named, method or
    subcommand)."""
    calls = []
    for i, token in enumerate(tokens):
        script = Path(token).name
        if script not in {"research_db.py", "research_tree.py", "review_call.py"} | ADAPTER_ENTRIES:
            continue
        actor = method = None
        j = i + 1
        while j < len(tokens) and tokens[j] not in SHELL_BOUNDARIES:
            flag, _, inline = tokens[j].partition("=")
            if flag in {"--actor", "--db", "--root"}:
                value = inline or (tokens[j + 1] if j + 1 < len(tokens) else None)
                j += 0 if inline else 1
                actor = value if flag == "--actor" else actor
            elif not tokens[j].startswith("-") and method is None:
                method = tokens[j]
            j += 1
        calls.append((script, actor, method))
    return calls


def reviewer_bypass(tokens):
    """A review goes through research_review (review_call.py), which records it: never pi or claude -p directly
    (plans/design 09 §4)."""
    start = True
    for i, token in enumerate(tokens):
        if token in SHELL_BOUNDARIES:
            start = True
            continue
        name = Path(token).name
        if start and name == "pi":
            return "评审只经 research_review（review_call.py）调用，它登记 review 文档并记录费用；不要直接运行 pi。"
        if start and name == "claude":
            rest = []
            for t in tokens[i + 1:]:
                if t in SHELL_BOUNDARIES:
                    break
                rest.append(t)
            if any(t in {"-p", "--print"} or t.startswith("--print=") for t in rest):
                return "评审只经 research_review（review_call.py）调用；不要直接运行 claude -p / --print。"
        start = start and (name in {"env", "nohup", "timeout", "exec", "command"} or "=" in token)
    return None


def call_block(calls, actor):
    """Only the RLD drives the tools from a shell; a worker acts as itself, any other session only reads. No one
    writes as the reviewer: reviews are registered by review_call.py alone. The observed model and the
    confirmation phase are recorded in-process by the adapter (hooks, confirm), never from a shell."""
    for script, named, method in calls:
        if script == "research_db.py" and (named or "").startswith("reviewer/"):
            return "reviewer 身份只属于 review_call.py；评审用 research_review。"
        if script == "review_call.py" and actor != "rld/main":
            return f"{actor} 不发起评审：由 Leader 用 research_review 组织。"
        if script == "codex_hook.py":
            return "codex_hook.py 只由 Codex hooks 运行：会话地址与观察到的模型不从 shell 记录。"
        if script == "research_tree.py" and method in {"agent-log", "phase"}:
            return (f"research_tree.py {method} 由插件在进程内调用（hook 观察到的模型、立项确认流程），不从 shell 运行；"
                    "确认用 research_control confirm，阶段用 research_control status 查看。")
        if script in ADAPTER_ENTRIES and actor != "rld/main":
            return f"{actor} 不运行插件入口 {script}：身份由控制器固定，用本会话的 MCP research_tree 工具。"
    if actor == "rld/main":
        return None
    for script, named, method in calls:
        if script == "research_tree.py" and method != "query":
            return f"{actor} 不运行 research_tree.py {method or ''}：它是插件与UI控制器的入口。"
        if script != "research_db.py":
            continue
        if actor.startswith(("worker/", "architect/")) and named != actor:
            return f"{actor} 只能以自己的身份调用 research_db（--actor {actor}）；MCP research_db 自动固定身份。"
        if not actor.startswith(("worker/", "architect/")) and named != actor:
            return f"{actor} 只能以自己的只读身份查询 research_db（--actor {actor}）。"
        if not actor.startswith(("worker/", "architect/")) and method not in READ_METHODS:
            return f"{actor} 只读研究数据库（{method or '未知方法'} 会写入）。"
    return None


def copy_destinations(tokens, start, cwd):
    """Literal cp operands: sources are reads, including when copying into a directory. cwd is None after a cd
    that cannot be resolved: a relative destination is then returned as written (and refused)."""
    operands, target = [], None
    no_directory = parents = literal = False
    i = start
    while i < len(tokens) and tokens[i] not in SHELL_BOUNDARIES and not REDIRECTS.fullmatch(tokens[i]):
        token = tokens[i]
        if literal:
            operands.append(token)
        elif token == "--":
            literal = True
        elif token == "--target-directory" or (token.startswith("-") and not token.startswith("--") and "t" in token[1:]):
            suffix = token.split("t", 1)[1] if token != "--target-directory" else ""
            if suffix:
                target = suffix
            elif i + 1 < len(tokens) and tokens[i + 1] not in SHELL_BOUNDARIES:
                i += 1
                target = tokens[i]
        elif token.startswith("--target-directory="):
            target = token.partition("=")[2]
        elif token in {"--suffix", "-S"}:
            i += 1  # backup suffix is not a destination path
        elif token.startswith("-"):
            no_directory |= token == "--no-target-directory" or (not token.startswith("--") and "T" in token[1:])
            parents |= token == "--parents"
        else:
            operands.append(token)
        i += 1
    if target is None:
        if len(operands) < 2:
            return [], i
        target = operands.pop()
    if cwd is None and not os.path.isabs(os.path.expanduser(target)):
        return [target], i
    destination = operand(target, cwd)
    paths = [destination]
    if not no_directory and destination.is_dir():
        paths += [destination / (source.lstrip("/") if parents else Path(source).name) for source in operands]
    return paths, i


def cd_target(tokens, start, cwd):
    """The directory a cd (operands from tokens[start]) moves to, or None when it is not known statically: a
    variable, command substitution, wildcard, cd -, ~+/~-, or a relative move from an unknown directory."""
    operands, i = [], start
    while i < len(tokens) and tokens[i] not in SHELL_BOUNDARIES:
        token = tokens[i]
        if REDIRECTS.fullmatch(token):
            i += 2  # the redirection and its target
            continue
        descriptor = token.isdigit() and i + 1 < len(tokens) and REDIRECTS.fullmatch(tokens[i + 1])
        if not descriptor and not (not operands and re.fullmatch(r"-[LPe@]+|--", token)):
            operands.append(token)
        i += 1
    if not operands:
        return Path(os.environ["HOME"]).resolve() if os.environ.get("HOME") else None
    target = os.path.expanduser(operands[0])
    if len(operands) > 1 or target == "-" or target.startswith("~") or re.search(r"[$`*?[]", target) \
            or (cwd is None and not os.path.isabs(target)):
        return None
    return (Path(target) if os.path.isabs(target) else cwd / target).resolve()


def in_place(program, tokens, start):
    """sed/perl options that edit files in place: -i alone or in an option cluster before any option that takes the
    rest as its argument (-i.bak, -Ei, -ni, -pi), or sed's --in-place (getopt also accepts it abbreviated)."""
    cluster = r"-[^-efl]*i" if program == "sed" else r"-[^-eEMmIxCdDF]*i"
    for token in tokens[start:]:
        if token in SHELL_BOUNDARIES:
            return False
        flag = token.partition("=")[0]
        if re.match(cluster, token) or (program == "sed" and flag.startswith("--i") and "--in-place".startswith(flag)):
            return True
    return False


def words(command):
    """Shell words and operators (boundaries, redirections) of one command text."""
    lexer = shlex.shlex(command, posix=True, punctuation_chars=";&|<>\n")
    lexer.whitespace = " \t\r"
    return [part for token in lexer for part in (re.findall(r"&&|\|\||&>|>&|<&|>\||>>|<<|[;&|<>\n]", token)
                                                  if re.fullmatch(r"[;&|<>\n]+", token) else [token])]


def heredocs(command):
    """Split here-document bodies off a command: (the command without them, the bodies). A body is data, often
    with unbalanced quotes (a patch), or a script its reader runs (bash <<EOF)."""
    lines, kept, bodies, i = command.split("\n"), [], [], 0
    while i < len(lines):
        kept.append(lines[i])
        i += 1
        for match in HEREDOC.finditer(kept[-1]):
            end = i
            while end < len(lines) and (lines[end].lstrip("\t") if match.group(1) else lines[end]) != match.group(3):
                end += 1
            bodies.append("\n".join(lines[i:end]))
            i = end + 1
    return "\n".join(kept), bodies


def authoritative_guards(project, marker):
    """Fresh DB-only authority, independent of the best-effort presentation cache."""
    python = project / ".venv/bin/python"
    if not python.is_file():
        raise ValueError(f"missing project interpreter: {python}")
    result = subprocess.run([str(python), str(ROOT / "tools/build_site.py"), "--db", marker["db"], "--summary"],
                            cwd=project, capture_output=True, text=True, timeout=30)
    if result.returncode:
        raise ValueError(result.stderr.strip() or f"guard reader exit {result.returncode}")
    snapshot = json.loads(result.stdout)
    guards = snapshot.get("guards") if isinstance(snapshot, dict) else None
    if not isinstance(guards, dict) or snapshot.get("db_path") != marker["db"] or any(
            not isinstance(guards.get(key), list)
            or any(not isinstance(path, str) or not Path(path).is_absolute() for path in guards[key])
            for key in ("frozen_docs", "harness")):
        raise ValueError("database did not return complete file guards for this project")
    return {"guards": guards}


def guard(event, cwd, marker, project):
    name = event.get("tool_name", "")
    args = event.get("tool_input", {})
    if not isinstance(args, dict):
        return None
    if name in {"spawn_agent", "Agent"}:
        return "项目代理通过research_control worker/architect/explorer/analyst启动；UI仅按需由用户入口启动。"
    db = Path(marker["db"]).resolve()
    actor = os.environ.get("RESEARCH_TREE_ACTOR", "rld/main")
    authority = None

    def check(path, base=cwd):
        nonlocal authority
        if base is None and not os.path.isabs(os.path.expanduser(str(path))):
            return ("命令中 cd 的目标无法静态确定（变量、命令替换、通配符或 cd -），其后的相对路径写入不放行；"
                    "改用确定的目录或绝对路径。")
        fixed = protected(path, base, {}, db, actor)
        if fixed:
            return fixed
        try:
            if authority is None:
                authority = authoritative_guards(project, marker)
            return protected(path, base, authority, db, actor)
        except Exception as exc:
            return f"无法核验最新的研究文件保护状态，已拒绝本次写入；恢复项目数据库访问后重试：{str(exc)[:300]}"

    if name in {"apply_patch", "Edit", "Write", "NotebookEdit"}:
        if actor.startswith(("explorer/", "analyst/")):
            return ADVISOR_READ_ONLY
        patch = args.get("command", args.get("input", ""))
        paths = PATCH_PATHS.findall(patch)
        paths += [args[k] for k in ("file_path", "notebook_path") if args.get(k)]
        for path in paths:
            reason = check(path)
            if reason:
                return reason
    if name in {"Bash", "exec_command", "shell", "shell_command"}:
        command = args.get("command", args.get("cmd", ""))
        if isinstance(command, list):  # argv, e.g. ["apply_patch", patch]
            text, (command, bodies) = "\n".join(command), (shlex.join(command), [])
        else:
            text = command if isinstance(command, str) else ""
            command, bodies = heredocs(text)
        workdir = args.get("workdir")  # exec_command runs there; relative operands start from it
        start = (cwd / os.path.expanduser(workdir)).resolve() if isinstance(workdir, str) and workdir else cwd

        def writes(tokens, base):
            """The first refused write among shell words, and the directory the shell ends in (None: unknown)."""
            writer = moved = previous = None
            copy_end = -1
            for i, token in enumerate(tokens):
                if i < copy_end:
                    continue
                if token in SHELL_BOUNDARIES:
                    if moved and moved[1] != "|" and token not in {"|", "&"}:
                        base = moved[0]  # a cd in a pipeline or background job changes only its subshell
                    writer = moved = None
                    previous = token
                    continue
                if REDIRECTS.fullmatch(token) or (token.isdigit() and i + 1 < len(tokens)
                                                  and REDIRECTS.fullmatch(tokens[i + 1])):
                    continue
                if i > 0 and REDIRECTS.fullmatch(tokens[i - 1]):
                    # the redirection's target; >&2 and >&- duplicate or close a descriptor
                    if tokens[i - 1] in WRITE_REDIRECTS and not (tokens[i - 1] == ">&"
                                                                 and (token.isdigit() or token == "-")):
                        reason = check(token, base)
                        if reason:
                            return reason, base
                    continue
                name = Path(token).name
                if name == "cd" and (i == 0 or tokens[i - 1] in SHELL_BOUNDARIES):
                    moved = (cd_target(tokens, i + 1, base), previous)
                    continue
                if name == "cp":
                    paths, copy_end = copy_destinations(tokens, i + 1, base)
                    for path in paths:
                        reason = check(path, base)
                        if reason:
                            return reason, base
                    continue
                if name in {"apply_patch", "applypatch"}:  # Codex's patch tool, run from the shell
                    if actor.startswith(("explorer/", "analyst/")):
                        return ADVISOR_READ_ONLY, base
                    for path in PATCH_PATHS.findall(text):
                        reason = check(path, base)
                        if reason:
                            return reason, base
                    continue
                if name in WRITERS or (name in {"sed", "perl"} and in_place(name, tokens, i + 1)):
                    writer = name
                    continue
                if writer == "dd" and token.startswith("of="):
                    token = token[3:]  # dd writes only its of= operand
                elif writer in {None, "dd"} or token.startswith("-"):
                    continue
                reason = check(token, base)
                if reason:
                    return reason, base
            if moved and moved[1] != "|":
                base = moved[0]
            return None, base

        # Shell parsing is deliberately bounded: direct writes, redirection, wrappers, cd, wildcards
        # and literal protected paths. Arbitrary Python/shell indirection is not sandboxed.
        try:
            tokens = words(command)
        except ValueError:
            return None  # let the shell report its own syntax error
        scripts = [tokens]
        for body in bodies:
            if body.lstrip().startswith("*** Begin Patch"):
                continue  # apply_patch's input: writes() checks its file headers where apply_patch runs
            try:
                scripts.append(words(body))
            except ValueError:
                continue  # data that is not shell words
        for script in scripts:
            blocked = reviewer_bypass(script) or call_block(research_calls(script), actor)
            if blocked:
                return blocked
        reason, end = writes(tokens, start)
        for script in scripts[1:]:  # a here-document read as a script (bash <<EOF) starts where its command ran
            reason = reason or writes(script, end)[0]
        return reason
    return None


def handle(event):
    cwd = Path(event.get("cwd", ".")).resolve()
    project = project_dir(cwd)
    marker = read_json(project / ".research-tree.json")
    if not marker:
        return {}
    cache = cache_dir(project)
    kind = event.get("hook_event_name")
    actor = os.environ.get("RESEARCH_TREE_ACTOR", "rld/main")
    actor_key(actor)
    # Only the main CLI records its address. Child sessions never become the Leader.
    lease_answer = None
    if actor == "rld/main" and kind in {"SessionStart", "PostToolUse"} and event.get("session_id"):
        with locked(cache / "leader.lock"):
            previous = read_json(cache / "leader.json", {})
            if not previous.get("session_id") or previous["session_id"] == event["session_id"]:
                write_json(cache / "leader.json", {"session_id": event["session_id"], "model": event.get("model") or previous.get("model")})
            elif kind == "SessionStart":
                # A new main session in a project whose Leader session is recorded (the usual resume after the
                # previous CLI ended): the model learns the supported takeover, not only the person (S0 Codex run).
                takeover = (f"research-tree：本项目已登记的 RLD 会话是 {previous['session_id']}，当前会话是 "
                            f"{event['session_id']}。恢复工作时：先用 research_control status 与 inbox、research_db "
                            "resume_package 核对原会话留下的任务、作业与未处理事件；确认原会话已不再工作后，用 "
                            f"research_control attach(session_id=\"{event['session_id']}\", model=当前模型) 登记交接，"
                            "再以 RLD 身份继续；不要重复提交已完成或状态 unknown 的工作。")
                lease_answer = {"systemMessage": "research-tree已有另一RLD会话；若需要接管，先核对原会话与作业，再用research_control attach登记交接。",
                                "hookSpecificOutput": {"hookEventName": kind, "additionalContext": WORKFLOW + "\n" + takeover}}
            else:
                lease_answer = {"systemMessage": "research-tree已有另一RLD会话；若需要接管，先核对原会话与作业，再用research_control attach登记交接。"}
    if kind in {"SessionStart", "PostToolUse"} and event.get("model") and event.get("session_id"):
        # The model the session actually runs on: the observed side of rule 2's model records (for rld/main also
        # the Leader's family, which a reviewer must differ from: plans/design 09 §2.1 step 3).
        log = Path(marker["root"]) / "logs" / "agent_models.jsonl"
        log.parent.mkdir(parents=True, exist_ok=True)
        # init usually happens after SessionStart, before a project exists. Its first PostToolUse supplies the
        # actual model too. Record that observation so cross-family reviews work without restarting the Leader.
        # Subsequent tool events do not create duplicates; a real model change gets a new observation.
        with locked(cache / "model-log.lock"):
            previous_model = None
            if log.is_file():
                for line in reversed(log.read_text(encoding="utf-8").splitlines()):
                    try:
                        record = json.loads(line)
                    except json.JSONDecodeError:
                        continue
                    if record.get("actor") == actor and record.get("agent") == event["session_id"] \
                            and record.get("event") == "observed":
                        previous_model = record.get("model")
                        break
            if previous_model != event["model"]:
                with log.open("a", encoding="utf-8") as stream:
                    stream.write(json.dumps({"ts": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                                             "agent": event["session_id"], "actor": actor,
                                             "event": "observed", "model": event["model"]}, ensure_ascii=False) + "\n")
    if lease_answer is not None:  # after the model record: a session waiting to take over is observed too
        return lease_answer
    if kind == "PreToolUse":
        reason = guard(event, cwd, marker, project)
        return deny(reason) if reason else {}
    if kind == "SessionStart":
        if actor == "rld/main":
            workflow = WORKFLOW
        elif actor.startswith(("worker/", "architect/")):
            workflow = f"""research-tree 固定身份 {actor}；你是节点执行者（architect仅负责根节点框架与baseline），主会话是唯一 Research Leader。
读取 {ROOT / 'rules/research-tree-rules.md'}，按本轮任务用 research_db resume_package 恢复。
只以自己的身份处理已指派任务、登记运行和交付；已生效文档写新版本，不改冻结框架。
用 research_message 的 delivery/alert 通知 Leader。主会话的收件箱、用户决定与代理调度由 Leader 处理。
"""
        elif actor.startswith(("explorer/", "analyst/")):
            workflow = f"""research-tree 固定身份 {actor}；你是只读研究顾问，主会话是唯一 Research Leader。
读取 {ROOT / 'rules/research-tree-rules.md'}，核对本轮文献、负向结果或当前成对证据，返回候选或下一实验建议及来源。
不写文件/数据库/配置，不提交作业、调用评审或调度代理，不确认计划或决定GO/NOT GO。需要登记的文档、任务状态与交付由Leader保存。
允许用research_message question/alert发送短建议；不得把建议当作用户授权。轻量GO=null表示未检查。
"""
        elif actor == "ui/ui":
            workflow = f"""research-tree 固定身份 ui/ui；主会话是唯一 Research Leader。
读取 {ROOT / 'rules/research-tree-rules.md'}。研究数据库与科学材料只读，不直接调用控制工具确认或调度代理、评审、训练。
可用 requirement_draft 保存需求草稿；最终返回 reply/actions JSON。用户明确确认当前立项计划时，输出 confirm 动作转交控制器；控制器记录用户原话并执行确认，UI 不直接写项目状态。
"""
        return {"hookSpecificOutput": {"hookEventName": kind, "additionalContext": workflow +
                                        f"\n项目 {marker['project_id']}：{marker['phase']}。当前数据摘要可能是旧快照，用status刷新。"}}
    if kind == "Stop" and actor == "rld/main":
        inbox = read_json(cache / "inbox.json", [])
        pending = [x for x in inbox if not x["acknowledged"]]
        if pending and not event.get("stop_hook_active"):
            return {"decision": "block", "reason": "research-tree有未处理事件，请读取research_control inbox并处理/acknowledge。"}
    return {}


def main():
    try:
        event = json.load(sys.stdin)
        response = handle(event)
    except Exception as exc:
        # Explicit denials for pre-tool failures; hook errors otherwise fail open in Codex.
        response = deny(f"无法核对项目保护状态：{exc}") if locals().get("event", {}).get("hook_event_name") == "PreToolUse" else {"systemMessage": f"research-tree hook: {exc}"}
    print(json.dumps(response, ensure_ascii=False))


if __name__ == "__main__":
    main()
