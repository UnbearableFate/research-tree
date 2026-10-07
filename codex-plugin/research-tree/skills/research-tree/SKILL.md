---
name: research-tree
description: Run a multi-agent ML research project with a hypothesis tree, versioned evidence, experiment gates, a separate research UI, and one persistent worker per node. Use for research-tree prepare, init, planning, confirmation, configuration, research progress, worker dispatch and resumption; not for ordinary coding outside a research project.
---

For `$research-tree prepare [--python 3.13] [--update-uv]`, run the shared shell helper directly:
`sh <plugin-root>/tools/prepare.sh [--python=3.13] [--update-uv] <absolute user workspace>`.
Resolve `<plugin-root>` as two directories above this SKILL.md's directory; quote both paths.
It makes the workspace a uv project with the tools' dependencies (`uv init`, `uv add`), then copies the plan
template to `plan.md` and the default configuration to `research-tree.yaml`; existing files are preserved. It
needs uv but no Python, MCP or project. Dependency installation can take a while: run it through a persistent
shell. Report its output and stop; the user fills in `plan.md` (research goal and initial hypotheses are
required) and edits `research-tree.yaml`, then asks for `init`. `config show` and `config apply` are project
operations described below.

For research operations, act as the single Research Leader (RLD) in the current Codex session. Read
[shared research rules](../../rules/research-tree-rules.md) before planning or managing research.
Scientific methods, roles, budgets, document lifecycles and cleanup rules are common to both hosts.
This file supplies the Codex-specific interface; references to `/research-tree`, Agent and
SendMessage in shared descriptions map to the tools below.

Use the installed `research_tree` MCP server. Tool names may have a plugin namespace prefix.
In the main session, pass `project=<absolute user workspace>` on every tool call. The MCP process
runs from the installed plugin directory; it must not mistake that directory for a research project.
Managed UI/worker sessions already receive a fixed project and may omit this parameter.
`research_db(method="help")` lists the shared database API; `kwargs={"method":"..."}` explains one method.
Do not invent arguments, directly edit the database, rewrite current documents, or bypass a rejected gate.

## Entry and planning

- `$research-tree init [plan.md]`: call `research_control(action="init", params={"plan":"plan.md"})` after prepare.
  Optional `project_id` and `config` (a YAML other than the workspace's `research-tree.yaml`) mirror the Claude
  init options. A plan made from the template must have its goal and initial hypotheses filled in. On a cluster,
  follow the site's execution rules before initialization, validation or experiment work.
- Read the returned plan document and planning instructions. Create goal/min_setup documents and the
  project record, retrieve and cache related work, and create all initial hypotheses as direct children
  of the root. The root contains only baselines. Create the unassigned root harness task.
- Register the complete plan report and call `post_to_ui(type="confirm_request", text=..., docs=[...])`.
  Show the same request in the main conversation if the independent UI is not open. Only an explicit
  user confirmation permits `research_control(action="confirm", params={"words":<verbatim words>})`.
  The agent must not generate the user's confirmation. Direct instructions in the main conversation
  are valid; users need not repeat them in the UI.
  Record other direct user instructions with `research_control(action="instruction",
  params={"words":<verbatim words>, "understanding":<interpretation and scope>, "about":[...]})`.
  A stop, pause, withdrawal of authorization or constraint correction takes effect immediately;
  recording it does not add an approval step.

## Roles and worker sessions

After confirmation, `assign_worker` binds a stable worker identity to the project/root or hypothesis.
Assign its task with `update_task`, then call `research_control(action="worker", params={"node_id":...,
"task":...})`. Pass the concrete task, request documents, writable code/worktree, resources, acceptance
and delivery requirements. Use the configured platform and skills; creating a worker does not itself
authorize new compute work.

The adapter starts a separate `codex exec` session, binds its returned thread ID to the node, fixes its
database actor and applies `models.worker` and its effort. `inherit` uses the model recorded from the
RLD's hook context. Check `agents` for actual startup/exit evidence; accepted launch is not successful
execution. Per-identity locks prohibit duplicate active writers.

Continue the node through the same `worker` action and its stored session. If a previous session cannot
be resumed, first check that its turn is no longer active, then use `restart=true` to create a new session
with the same identity and the database recovery package. Never restart solely because observation
timed out. Research jobs can outlive agent turns: reconcile original run/job IDs before any new submission.
Do not use native `spawn_agent` to evade the plugin's ownership, confirmation or worker-limit checks.

Review worker delivery documents, results and code. Freeze the root harness and statistics, establish
SOTA, then proceed through the hypothesis/experiment/verdict/decision workflows in the shared rules.
Statistics are never supplied by an agent: runs are imported through their manifests (`import_run_result`)
or reported per run, and `evaluate_experiment` recomputes means, SDs, paired effects, the gate and guardrails
into an evaluation record. Result documents cite each number in an `evidence` block that is checked against the
cited files. GO eligibility comes from `get_eligibility` (current evaluation, gate, guardrails, rechecks bound
to the evaluated code, no OPEN obligation, and under profile stage1_confirmed an unseen confirmation of the
same code), never from cached labels. Each evaluation carries a deterministic outcome (positive_signal,
negative_signal, inconclusive); a seed limit does not force a conclusion. Investment is a separate decision
(`decide_disposition`: active, paused, retired, with reason, evidence and reopening condition); NOT GO needs no
active node and a report covering unexplored, failed, uncertain, repeated, refuted and value judgements. Record
new findings per decision batch with `note_findings`; close review findings only through `resolve_obligation`
(with evidence) or a user waiver. Accept tasks with `evidence_ids`.

GO candidates (candidate_ready or confirmed) in a project whose configuration requires cross-model rechecks
also need one `research_review(kind="candidate_recheck", dimension, evaluation)` per dimension (numbers,
protocol, method_code, novelty, theory), each in a new reviewer session. Write the brief under
`docs/reviews/briefs/` with file paths and structured metadata only (evaluation id, code version and directory,
result document, protocol, metric files), never your summary or leaning; pass `add_dirs` for a code directory
outside the research root (Claude Code backend). Report `REVIEW_UNAVAILABLE`, `REVIEW_INVALID` or
`REVIEW_BUDGET` as they are; never replace a review with your own judgement, and never run `pi` or `claude -p`
directly. `get_eligibility` lists in `rechecks` which review checked which evaluation or code, with backend and
model.

Before a method or ablation experiment is submitted (design.sanity_first / design.code_review), the node needs a
valid `kind="sanity"` run of the same code and a cross-model code review of that commit: write the brief (code
directory and commit, hypothesis document, protocol; no conclusions) and call `research_review(kind="code_review",
about=<node>, code_ref=<commit>, add_dirs=[<code dir>])`; when the reviewer is unavailable, releasing it is your
recorded decision (`waive_code_review` with a decision document). After a positive signal or candidate_ready ask
for an `ablation_plan` review and register ablations as `kind="ablation"` with `ablation_of` and
`source_review_id`. A task blocked by the failure budget (`task_blocked`) needs your decision document and
`unblock_task`.

Before each decision batch read `context_pack(node_id=<project>, role="rld")`; write a finding or lesson when an experiment is accepted, a fix is confirmed, a key control completes or the direction changes.

## User communication

`research_control(action="ui_path")` returns a command the user runs in another terminal. That console
is the independent UI: ordinary text starts a read-only UI Codex session, which records requirement
drafts and returns structured actions. The controller records the user's original words, applies
confirmation/instruction/submission actions once, and queues messages to the RLD. The main model must
not start a UI agent or fabricate input to this human-facing console.

Use `post_to_ui` for notices, replies (`re` required), and decision requests (`docs` required). Messages
and dialogue persist under `messages/`. UI replies do not run workers or make scientific decisions.
Worker `research_message` calls validate and log messages before delivery to the RLD.

Hooks record the RLD address/model and protect known frozen paths. Review and trust installed plugin
hooks using Codex's hook controls; installation does not imply trust. If hooks are unavailable, explicitly
attach the actual current session and model with `research_control(action="attach", params={"session_id":...,
"model":...})`; do not guess them. The plugin cannot wake an unregistered main session.

`codex queue` notifications are distinct from receipt and execution. Read `inbox` after resume and when
notified; process references, acknowledge received event IDs, and send substantive instruction receipts
via `post_to_ui(type="reply", re=<original message id>, ...)`. Failed/unknown delivery remains in the inbox;
inspect the original event and destination instead of repeatedly generating messages. A receipt does not
mean the requested action has been completed.

## Progress and configuration

- `status` / `refresh`: current tree, counts, attention, resource usage and agent state.
- `pane` / `build`: produce the offline six-view HTML progress page and return its path. Codex has no
  equivalent to the Claude mod's custom dock pane; open the generated page and rebuild after each batch.
- `check`: compare page and database versions; `chat`: persisted research dialogue.
- `config show`: call `research_control(action="config")` for the effective version and pending YAML
  changes. `config apply`: call that tool with `params={"apply":true,"words":<user's words>}`; this
  applies an authorized change. Gates lock after experiments begin. Do not edit the user's configuration
  autonomously. New turns use the current model/platform settings; tell active workers about changes.

Agents run with workspace-write (worker) or read-only (UI) sandboxing and cannot request interactive
approval in background exec. If the platform needs an unavailable permission, report it to RLD; do not
retry with bypass flags. File hooks are guardrails, not a security sandbox for arbitrary shell programs.
