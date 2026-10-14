# Changelog

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

The S5 scenario (`scripts/scenarios/s5.sh`, plan §9.6 SC-S5-03) now checks that a configuration protocol change
leaves the finding current, then uses a comparison-protocol change (`min_pairs`) for the recheck path.
