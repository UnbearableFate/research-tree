# Changelog

## Unreleased

Merges 0.1.1 into the 0.2.0 line and fixes what a full review of the code found. Contract changes:

- `config apply` needs the user's own words (`--words`) whenever it would register or change anything; it no longer
  makes up words. Everything is checked before anything is registered, so a refused apply leaves no configuration
  version, metric specification or instruction behind. The user's words carry every change that is the user's
  decision, including turning a gate off or lowering the exploration share. Plan confirmation passes the user's
  confirmation words.
- Raising `screen_budget_node_h`, `max_parallel_workers`, `stall_structural_at` or `stall_human_at` is the user's
  decision (a larger screening budget also widens cheap search, which skips per-run code review).
- Evidence currency (0.1.1 kept every configuration change from voiding evaluations): an evaluation still becomes
  stale when a tightened evidence rule no longer accepts it (more `independence_fields`, or artifact import now
  required of a record-level evaluation; `PROTOCOL_CHANGED`), or when a metric it compared changed how it is judged
  (direction, canonical unit, effect mode, aggregation, allowed regression, valid range, relative denominator;
  `METRIC_SPEC_CHANGED`). Protocol versions are compared by their normalized comparison content, so descriptions and
  spelled-out defaults no longer count; an unreadable version reads as changed instead of failing the read.
- A configuration-only protocol change keeps the SOTA baseline usable, code-review adjudications and approved
  minimum controls.
- `waive_code_review(experiment_id, doc_id, user_instruction_doc_id)` needs the user's instruction.
- A method whose confirmation used its material cannot be put into another confirmation batch; a negative
  confirmation stands. Material counts as used from the claimed submission.
- A review request whose earlier job failed or was interrupted starts a new job (a new ticket).
- Documents record `frozen_at` and run attempts `submitted_at` (system-written, nullable: existing schema-23
  databases keep working); fix verification compares them instead of draft or reported times.

Also fixed: the private-evaluation sandbox (`scripts/private_eval/sandbox.sh`) binds the tool-state directories at
their resolved paths, so a home whose `.claude`, `.codex`, `.cache` or `.config` is a symlink no longer stops bwrap.

## 0.1.1 — 2026-10-10

Two changes to how the project configuration (`research-tree.yaml`) is handled, on both hosts.

### The Leader may edit `research-tree.yaml` when the user asks

- Claude Code: the mod refuses writes to the configuration (Edit, Write, NotebookEdit, shell writes) only from
  subagents (workers, the UI, lens assistants); the main session may write it. When the main session runs
  `research_tree.py config apply`, it must pass `--words` with the user's request, which is registered as the user
  instruction; the mod then reloads the configuration and re-registers the agents, as `/research-tree config apply`
  does.
- Codex: the hook refuses writes to the configuration from every actor except `rld/main`; applying still goes through
  `research_control config apply` with the user's words.
- Rules, prompts, the Codex skill and the README say the Leader edits the file only on the user's instruction and only
  the items the user named.

### A configuration change no longer voids earlier experiments and conclusions

A configuration change governs later work. In `research_db`:

- A new metric specification no longer makes earlier evaluations stale (the `METRIC_SPEC_CHANGED` reason is gone).
  Each evaluation keeps the specification it was computed under, and an experiment can be re-evaluated under the new
  one when wanted. The primary metric's gate stays frozen once experiments exist, as before.
- A protocol version that differs only in the fields the configuration sets (`profile`, confirmation settings,
  `require_artifact_import`, `independence_fields`, `repetition`; `CONFIG_PROTOCOL_FIELDS`) no longer makes
  evaluations stale, no longer makes them unusable as references (`EVIDENCE_STALE`), and keeps method identities: an
  experiment registered under such a version reuses the method spec registered under the earlier one, so frozen
  candidates, confirmation batches and code reviews stay bound. A change to the comparison protocol itself
  (evaluation type, pair fields, `match`, counts, `min_pairs`, …) or to the harness still makes dependent evidence
  stale.
- Evaluating the SOTA baseline again on the same runs (for example under a new metric specification) no longer
  reports `BASELINE_CHANGED` for node evaluations compared with it; a baseline evaluated on other runs still does.
- A lesson bound to a configuration (`applicability.config_doc_id`) needs a recheck only when the configuration's
  `platform` section changed, not after a budget or model change; protocol and metric-specification changes follow
  the rules above.

The S5 scenario (`scripts/scenarios/s5.sh`, plan §9.6 SC-S5-03; the scenario controllers were removed in 0.2.0) now
checks that a configuration protocol change leaves the finding current, then uses a comparison-protocol change
(`min_pairs`) for the recheck path.
