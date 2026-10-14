---
name: research-tree
description: Run evidence-driven ML research with incremental hypotheses, a shared Experiment Architect, read-only Explorer and Evidence Analyst, bounded parallel screening, independent confirmation, and on-demand UI. Use for research-tree prepare, init, planning, confirmation, configuration, progress, role dispatch and resumption; not for ordinary coding outside a research project.
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

For research operations in the main session, act as the single Research Leader (RLD). Managed workers,
Architect, Explorer, Analyst and UI sessions keep their fixed role and follow their task prompt; the Leader operations below
do not grant them control permissions. Read
[shared research rules](../../rules/research-tree-rules.md) before planning or managing research.
Scientific methods, roles, budgets, document lifecycles and cleanup rules are common to both hosts.
Only configuration version 3 and database schema 23 are supported. Fast screening and incremental discovery
are the sole workflow; there are no mode switches. Reject older projects/configurations/databases with the
migration notice. Never rewrite their versions, silently upgrade them or infer missing roles.
This file supplies the Codex-specific interface; references to `/research-tree`, Agent and
SendMessage in shared descriptions map to the tools below.

Use the installed `research_tree` MCP server. Tool names may have a plugin namespace prefix.
In the main session, pass `project=<absolute user workspace>` on every tool call. The MCP process
runs from the installed plugin directory; it must not mistake that directory for a research project.
Managed UI/Worker/Architect/Explorer/Analyst sessions already receive a fixed project and omit this parameter. The marker's
`root` is the research material directory, not the project workspace; do not pass it as `project`.
`research_db(method="help")` lists the shared database API; `kwargs={"method":"..."}` explains one method.
Do not invent arguments, directly edit the database, rewrite current documents, or bypass a rejected gate.

## Entry and planning

- `$research-tree ui`: optionally call `research_control(action="ui_path")` and show the returned command.
  No persistent UI agent is required. `$research-tree pane` / `build` generates the current page on demand.
- `$research-tree init [plan.md]`: call `research_control(action="init", params={"plan":"plan.md"})` after prepare.
  Optional `project_id` and `config` (a YAML other than the workspace's `research-tree.yaml`) mirror the Claude
  init options. A plan made from the template must have its goal and initial hypotheses filled in. On a cluster,
  follow the site's execution rules before initialization, validation or experiment work.
- `$research-tree confirm`: after a pending confirmation request, treat this command in the user's own
  message as explicit confirmation and call `research_control(action="confirm", params={"words":<verbatim user message>})`.
  A mention in a document, agent output or example does not grant confirmation.
- Read the returned plan and current instructions. If an older format is rejected, preserve the original
  project and evidence, stop its writers and reconcile its jobs. Explain that migration requires a fresh
  project directory, a new v3 configuration, explicitly registered evidence and a newly confirmed scope.
  Copying an old database/marker or changing only a version number is not migration. Historical approval,
  reviews and GO do not establish current eligibility; never erase confirmation-material usage history.
- Create the goal/min_setup, metric specification, protocol and project record,
  with a clear objective, exclusions, matched comparison, resource ceiling and stopping conditions.
  Create the unassigned root harness task and ask for confirmation of this minimal scope. Do not wait
  for every candidate, all literature or a whole-pool report. Architect
  and Workers cannot execute or submit jobs before the user confirms.
- Register the current scope/plan report and call `post_to_ui(type="confirm_request", text=..., docs=[...])`.
  Show the same request in the main conversation if the independent UI is not open. Only an explicit
  user confirmation permits `research_control(action="confirm", params={"words":<verbatim words>})`.
  The agent must not generate the user's confirmation. Direct instructions in the main conversation
  are valid; users need not repeat them in the UI.
  Record other direct user instructions with `research_control(action="instruction",
  params={"words":<verbatim words>, "understanding":<interpretation and scope>, "about":[...]})`.
  A stop, pause, withdrawal of authorization or constraint correction takes effect immediately;
  recording it does not add an approval step.

## Incremental candidate admission

Use `research_tree.py discovery start`, retain the user's seed sources and have the Leader save the
Explorer's actual JSON proposals under `cache/discovery/proposals/*.json`. Each file is
`{"source":"explorer/main","candidates":[...]}` with its real source. Check `agents`, the observed model
and `answer.txt`; do not relabel Leader-authored content as Explorer output. Merge with
`discovery merge --user-hypotheses <user seed file>`, keeping other current inputs/proposals present.
For each ready candidate use `discovery select --candidate CAND-编号`, then
`discovery gate --candidate CAND-编号`. Candidate A is independent of incomplete B. PASS is a current
readiness result, not user authorization; `create_hypothesis(candidate_id=...)` rechecks authoritative
current content/scope. A changed revision needs a fresh check. Never hand-write PASS or reuse another
candidate's clearance. Use only the supported discovery actions: start, status, merge, feasibility,
select with a candidate, cite, gate with a candidate, and check. There is no whole-pool clearance.

Each candidate needs `prediction`, `intervention`, `comparator`,
`resource_ceiling: {nodes: int, walltime_s: int}` (positive values within scope and budget), and
`stop_conditions` (a string). For the node and experiment_design, use the exact headings
`可证伪预测`, `干预`, `匹配对照`, `资源上限`, `停止与继续条件`; the node also copies the approved
`问题锚点` verbatim. The resource section contains JSON `{nodes, walltime_s, n_seeds?}`.
Describe the matched conditions and falsifying outcome; estimates are not observations. Detailed
related work and arguments can be reused and completed for promotion, without blocking all cheap runs.
Unresolved current leakage/metric issues remain blockers. Literature existence and its support for a
specific claim are separate checks; cite the actual source and preserve uncertainty.

## Roles and worker sessions

Leader owns direction, scope/budget allocation, prioritization, dispute resolution and project GO/NOT GO.
Use `research_control(action="explorer", params={"task":<question and source paths>})` for ongoing
literature, foundational hypotheses, negative findings, variants and combinations. Use `action="analyst"`
for comparisons of current evaluations/raw evidence and proposals for the next most informative experiments.
Both are read-only advisory roles: no file/DB writes, task claims or deliveries, experiments, jobs,
reviews or scientific/investment decisions. They return evidence-linked recommendations/messages;
the Leader records task state and versioned deliverables. Send negative/inconclusive findings back to
Explorer and promising candidates to independent Reviewer and Leader. Their configured role models/effort
are used, with stable identities and resumable sessions; do not create a permanent committee.

After confirmation, `assign_architect(architect_id="root")` binds the root's sole execution identity,
`architect/root`. Assign its harness/baseline task with `update_task`, then use
`research_control(action="architect", params={"node_id":<project/root ID>, "task":...})`.
The root uses `architect_id`, `architect_agent_id` and `architect_session_at`; its session is bound by
`bind_architect_session(agent_id)`. The Architect owns shared harness/statistics, protocol implementation,
sanity and baselines only; Leader freezes the harness and chooses research directions. There is no root
Worker alias or role fallback. Start Explorer alongside Architect, not after the entire baseline finishes.
For a hypothesis, `assign_worker` and `bind_worker_session` bind its separate fixed Worker identity/session.
Use `research_control(action="worker", params={"node_id":<hypothesis ID>, "task":...})`. Pass the concrete task, request documents, writable code/worktree, resources, acceptance
and delivery requirements. Use the configured platform and skills; creating a worker does not itself
authorize new compute work.

The adapter starts a separate `codex exec` session, binds its returned thread ID to the node, fixes its
database actor and applies the explicit role's `models.worker` or `models.architect` and its effort. `inherit` uses the model recorded from the
RLD's hook context. Check `agents` for actual startup/exit evidence; accepted launch is not successful
execution. Per-identity locks prohibit duplicate active writers.

Continue the node through the same `worker`/`architect` action and its stored session. If a previous session cannot
be resumed, first check that its turn is no longer active, then use `restart=true` to create a new session
with the same identity and the database recovery package. `resume_package.actor` is the role-qualified identity.
Never restart solely because observation timed out. Research jobs can outlive agent turns: reconcile original run/job IDs before any new submission.
Do not use native `spawn_agent` to evade the plugin's ownership, confirmation or worker-limit checks.

Review worker delivery documents, results and code. The Architect first registers and validates harness
sanity; Leader reviews/freezes the harness and statistics before non-sanity experiments. A
valid baseline seed can support the same matched method seed via an explicit `comparator_experiment_id`
while other baseline seeds continue. Missing/invalid/mismatched controls do not qualify; partial evidence
is not a complete SOTA, candidate promotion or GO. Keep detailed validity/provenance guards and
follow the outcome/decision workflow.
Statistics are never supplied by an agent: runs are imported through their manifests (`import_run_result`)
or reported per run, and `evaluate_experiment` recomputes means, SDs, paired effects, the gate and guardrails
into an evaluation record. Result documents cite each number in an `evidence` block that is checked against the
cited files. GO eligibility comes from `get_eligibility` (current evaluation, gate, guardrails, rechecks bound
to the evaluated method and claim, no OPEN obligation, and mandatory independent confirmation on
untouched declared material), never from cached labels. Each evaluation carries a deterministic outcome (positive_signal,
negative_signal, inconclusive); a seed limit does not force a conclusion. Investment is a separate decision
(`decide_disposition`: active, paused, retired, with reason, evidence and reopening condition); NOT GO needs no
active node and a report covering unexplored, failed, uncertain, repeated, refuted and value judgements. Record
new findings per decision batch with `note_findings(node_id, finding_ids=[<new current finding documents>],
doc_id=<current decision document>, rationale=<why they are new>)`; a bare count resets nothing, a finding already
counted (or the same claim and evidence repackaged) is not new, and reuse of the same node/document does not count
again. `repetition_advice(experiment_id)` says whether the protocol asks for more search seeds. Autonomous
follow-up seeds require current applicable `positive_signal` evidence, matching method/config/claims,
protocol/reference, authorization, seed ceiling and budget; stale evidence, cached node labels,
negative or inconclusive outcomes are not automatic permission. Do not recast history to gain permission.
Close review findings through the applicable evidence-based resolution/adjudication API, never by silently
replacing the original receipt. Accept tasks with `evidence_ids`.

For a small selected set of promising methods, first lock methods and claims, complete needed replication
and key controls, freeze the eligible candidate/reference and use independent confirmation materials.
Then perform the final five-dimensional review and resolve current obligations before the Leader's GO.
Do not spend confirmation material automatically at the first positive signal or mechanically review all
five dimensions before confirmation and then repeat them. All projects require cross-model rechecks:
use `research_review(kind="candidate_recheck", dimension, evaluation)` per dimension (numbers,
protocol, method_code, novelty, theory), each in a new reviewer session. Numbers/protocol bind final
confirmation evidence; other receipts are reusable only while their method/claim/evidence basis is unchanged. Write the brief under
`docs/reviews/briefs/` with file paths and structured metadata only (evaluation id, code version and directory,
result document, protocol, metric files), never your summary or leaning. The `brief` argument is relative to the research root and includes `docs/`, for
example `brief="docs/reviews/briefs/H-0001-numbers.v1.md"`. If the argument omits `docs/`, correct the argument to match the file's actual path. Pass `add_dirs` for a code directory
outside the research root (Claude Code backend). Report `REVIEW_UNAVAILABLE`, `REVIEW_INVALID` or
`REVIEW_BUDGET` as they are; never replace a review with your own judgement, and never run `pi` or `claude -p`
directly. `get_eligibility` lists in `rechecks` which review checked which evaluation or code, with backend and
model. Review start returns a ticket immediately; continue independent work and retrieve the same task with
`research_review(ticket=...)`. Do not use a long synchronous wait, duplicate a pending review, or treat pending
as failure. The receipt's checklist decides the result
(a failed item fails the dimension even under a top-level pass); never ask a reviewer to turn a legal fail into a
pass. A failed item becomes an OPEN obligation; close it with `resolve_obligation(id, fix_type, evidence=<a later
current recheck of that dimension that passes the item>)` — a new overall pass closes nothing by itself. When a
reviewer returns an uncertain novelty recheck with `requested_queries`, run
`literature_followup(review_id)` once and continue the same review session with `evidence_set` set to its manifest.

Every experiment states its configuration (`method_config` or `config_path`); the interface registers its method
identity (`method_spec`, execution fields such as output paths, walltime, seeds and the evaluation split excluded)
and refuses an import whose reported configuration differs (`METHOD_SPEC_MISMATCH`). Same code with a
meaningful scientific configuration change is a method intervention; changing only execution metadata is not.
A changed claim (`update_hypothesis` statement or document) is a new claim revision: reviews, waivers and your recheck decisions
of the old revision stop applying and are redone; `review_basis` shows what a review would be bound to.
Independent confirmation is mandatory and bound end to end: `freeze_candidate(hypothesis_id,
search_evaluation_id)` freezes the selected method from the node's current search basis; `create_confirmation_batch(
[candidate_spec ids], material)` freezes the list, the reference they were selected against and one of the
protocol's named confirmation materials (evaluation split and seed block). The Architect registers the batch's
confirmation baseline (`kind="baseline", stage="confirm", confirmation_batch_id, confirmation_of=<frozen reference>,
method_config=<reference's configuration>`). The hypothesis Worker registers its candidate's confirmation (`stage="confirm", candidate_spec_id,
confirmation_batch_id`, the candidate's configuration). A material in use is never declared again for a later
candidate (`CONFIRMATION_MATERIAL_REUSED`): a method changed after confirmation feedback is a new candidate on
another declared material, or stays unconfirmed. Execution failures may be retried as new attempts; an imported
valid result is never marked invalid or retracted to run again. `material_usage` shows the record.

Before method/ablation submission, retain the configured valid same-method sanity run (`kind="sanity"`,
method configuration plus only allowed `sanity_overrides`), raw metrics/provenance, correct data and metric
implementation, matched controls, method identity, scope, reservation budgets and duplicate protection.
Ordinary authorized cheap screen/replicate runs do not require a fresh cross-model code review each time. Current applicable true leakage or incorrect metric findings still
block valid evidence. Novelty or incomplete explanation generally gate promotion/claims, not every run.

Experiments outside the cheap search allowance and confirmation retain applicable code-review admission:
after experiment registration, prepare a neutral brief (code directory/commit, hypothesis, protocol) and call
`research_review(kind="code_review", about=<node or supported experiment>, code_ref=<commit>, add_dirs=[...])`.
`review_basis` must identify the exact method/claim; unsupported subjects must fail before model cost.
When the bounded API permits reviewer-unavailability relief, require an explicit user instruction and
a recorded Leader decision (`waive_code_review`). Obligation waivers likewise require the applicable
explicit user instruction. Neither path can waive a verified validity defect or silently replace final evidence. Unreadable review input needs repaired materials, not scientific rejection.
For an evidence-backed objection use `dispute_code_review(experiment_id, review_id, category,
evidence_doc_id, reason)`, obtain an independent structured recheck tied to that dispute, then Leader
`adjudicate_code_review(review_id, dispute_id, recheck_review_id, resolution, decision_doc_id, reason)`.
Resolution is `overturned`, `upheld` or `fixed`; preserve original objection, evidence, binding and provenance.
`fixed` requires a new method identity, an independent clear recheck and evidence of the actual repair,
and releases only the exact experiment/claim/protocol/evidence basis. Verified defects carry across
same-code configuration changes, successors on the same hypothesis, descendant commits and unchanged
cited source on other branches. A changed filename, comment or source byte alone is not a verified repair.
An unrelated/stale clear review cannot erase the issue; confirmed leakage/metric faults cannot be waived
by overturning them, and the original bad method remains blocked.

An exact predeclared minimum control needs no separate reviewer-created `ablation_plan`: before the target
experiment is submitted, its design's `## 预声明最小对照` contains fenced JSON
`{"controls":[{"id":"remove-b","code_ref":"<commit>","method_config":{"b":false},"nodes":1,"walltime_s":60,"n_seeds":1}]}`
(replace the illustrative values with the exact authorized method/resources), and Leader records
`approve_minimum_controls(experiment_id, decision_doc_id)`. The ablation names `ablation_of` and
`predeclared_control_id`, matching the approved code/configuration/resources exactly. A retroactive,
changed or expanded control cannot use this exemption. New complex ablations, expanded claims and costly
matrices require the applicable deeper review/authorization; ordinary reviewed ablations cite
`source_review_id` from `ablation_plan`. No-op ablations are refused. A task blocked by its failure budget
(`task_blocked`) needs a Leader decision document and `unblock_task`.

Name each new node's `direction` (the mechanism it tests; a rename keeps it). `parent_id`
records intellectual ancestry; an unproven parent can yield parallel variants. State `code_parent_id`
for the code source, the branch's exact `base_commit`, and `comparator_experiment_id` for the explicit
comparison independently. Do not fake a parent's win/investment status to create a variant.
New nodes may also state scientific links with `relations=[{kind, target}]`:
`combines` (two or more nodes), `repairs` and `tests_assumption` may rest on negative or inconclusive history
(targets need an evaluation); `competes`, `shares_control` and `variant_of` record controls. A node in the
direction of a retired node must repair it, and one root cause is repaired at most
`search.max_repairs_per_root_cause` times (`REPEATED_DIRECTION`). Compare advancing a positive direction,
reducing a key uncertainty and exploring a different mechanism in each decision batch, and record a
`selection_rationale` on each experiment (why now, how its result changes the next step); mark the latter
`exploration=true` — it may use the exploration share of the search budget that other work cannot take. Never
create work just to use that share. `relations(node)` lists typed relations, including tested_by, supports and
invalidates.
Before each decision batch read `context_pack(node_id=<project>, role="rld")`; write a finding or lesson when an experiment is accepted, a fix is confirmed, a key control completes or the direction changes.

## User communication

`research_control(action="ui_path")` returns a command the user runs in another terminal. That console
is an optional on-demand UI: ordinary text starts one temporary read-only UI Codex session, which records requirement
drafts and returns structured actions. The controller records the user's original words, applies
confirmation/instruction/submission actions once, and queues messages to the RLD. The main model must
not start a UI agent or fabricate input to this human-facing console.

Use `post_to_ui` for notices, replies (`re` required), and decision requests (`docs` required). Messages
and dialogue persist under `messages/`. UI replies do not run workers or make scientific decisions. Normal research needs no persistent UI agent;
UI generation failure does not undo a successful scientific DB operation or block unrelated experiments.
Worker `research_message` calls validate and log messages before delivery to the RLD.

Hooks record the RLD address/model and protect known frozen paths. Review and trust installed plugin
hooks using Codex's hook controls; installation does not imply trust. Trusted hooks are required: without
them no session address or observed model is recorded, so `inherit` fails, cross-family reviews return
REVIEW_UNAVAILABLE and file guards do not run. `research_control(action="attach", params={"session_id":...})`
is not a fallback for missing hooks: it only hands the Leader role to a main session the hooks have already
observed (attach from that session after its first tool call). The model comes from that observation; a
`model` parameter that differs is refused. The plugin cannot wake an unregistered main session.

`codex queue` notifications are distinct from receipt and execution. In the RLD session, read `inbox` after resume and when
notified; process references, acknowledge received event IDs, and send substantive instruction receipts
via `post_to_ui(type="reply", re=<original message id>, ...)`. Failed/unknown delivery remains in the inbox;
inspect the original event and destination instead of repeatedly generating messages. A receipt does not
mean the requested action has been completed.
Workers recover their assigned work with `research_db(resume_package)` and communicate through
`research_message`; they do not use the RLD's `inbox`, `acknowledge` or `post_to_ui` operations.

## Progress and configuration

- `status` / `refresh`: lightweight current tree/counts, attention, resource usage and agent state, without
  full document/curve/render traversal. GO `null` means unchecked, not failed; explicitly call
  `get_eligibility` for a scientific qualification decision instead of interpreting cached labels.
- `pane` / `build`: produce the offline six-view HTML progress page and return its path. Codex has no
  equivalent to the Claude mod's custom dock pane; generate/open it when needed and check its data version.
  Preserve tree visualization, result comparisons and GO/NOT GO display without making a page build an experiment gate.
- `check`: compare page and database versions; `chat`: persisted research dialogue.
- `config show`: call `research_control(action="config")` for the effective version and pending YAML
  changes. `config apply`: call that tool with `params={"apply":true,"words":<user's words>}`; this
  applies an authorized change. Gates lock after experiments begin. Edit `research-tree.yaml` only when the
  user asks, and only the items they named (workers cannot write it), then apply with their words. Evidence
  stays current for GO while the harness, the comparison protocol, the baseline and the runs it used are
  unchanged. Tightening `independence_fields`, newly requiring artifact import, or changing a compared
  metric's direction, units, `allowed_regression` or `valid_range` also makes it stale; other configuration
  changes govern only later work. New turns use the current model/platform settings; tell active workers
  about changes.

Workers use workspace-write unless the user's CODEX_HOME/config.toml explicitly sets
sandbox_mode="danger-full-access", in which case they inherit Full access. UI, Explorer and Analyst
remain read-only. Background exec cannot request interactive approval. If the platform needs an unavailable permission, report it to RLD; do not
retry with bypass flags. File hooks are guardrails, not a security sandbox for arbitrary shell programs.
