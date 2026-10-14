# Fast research workflow: implementation and verification

Date: 2026-10-11. Base: `bug-fix-1008` at `fd608aa15c531a855ea4fbc23f942236c4a1b303`.
Design source: [the user-supplied workflow discussion](https://chatgpt.com/share/6acad363-4f9c-83ee-86c1-c1dd1ee5859b?ogimg=plain), including its later role and on-demand UI refinements.

## Scope and claim

The change shortens the software admission path to a bounded, valid paired screening experiment. It does **not** establish an empirical research-quality or speed improvement. No GPU, production scheduler, real-model research run, or fixed-resource A/B/C efficacy benchmark was performed for this change. Deterministic test values are fixtures, never measured scientific evidence.

The existing independent-confirmation, raw-result/provenance, accounting, duplicate-submission, and final-decision machinery remains authoritative. A positive screening outcome is not GO; a negative node or engineering failure is not project NOT GO.

## Operational contract

- New version-2 templates explicitly select `workflow.mode: fast_screening` and `discovery.mode: incremental`. Existing v2 files omitting these keys remain `strict` / `full`; v1 remains strict and retains its prior discovery behavior. Plugin upgrade alone does not relax a project. Applying a mode change records the user's instruction.
- Initial user confirmation of objectives, protocol, minimum scope, permissions and budget still precedes execution. Incremental discovery permits that confirmation while candidates are pending, then admits each current selected candidate independently. A candidate PASS is not user approval or a global discovery PASS.
- Explorer and Analyst are bounded read-only sessions. The Leader registers their advice, starts/delivers their task records and accepts them with evidence. A Leader-authored advisory delivery must describe its exact task and preserve the advisor's assigned role/id; its body cites the actual session/report and sources. Workers still start/deliver their own tasks.
- Architect is the root worker, shares the root's identity/lock with legacy `worker/root`, and owns only shared harness/baseline work. Hypothesis workers retain their own fixed identities. The Leader alone allocates scope and makes research decisions. No persistent UI session is needed.
- Cheap screen/replicate experiments must state five fields: falsifiable prediction, intervention, matched comparator, resource ceiling and stop/continue conditions. The problem anchor matches the approved goal. Candidate admission binds the current revision/hash and the hypothesis cannot borrow another candidate's scope or drop it through a document update.
- Cheap means method/ablation in search stages whose registered total node-seconds fit `screen_budget_node_h`; the hypothesis ceiling, project caps, seed limits and existing budget pools also apply. Actual fast-mode reservations must equal the aggregate registered node-seconds and fit the aggregate node/walltime bounds. Declare scheduler overhead in the experiment, not in a larger late reservation.
- The ordinary cheap path does not require a fresh model code review each time. Sanity when configured, method/config identity, frozen harness, imported/raw evidence requirements, pairing, units, guardrails, reservations and duplicate prevention still apply. Novelty/argument-only objections do not block cheap screening, but block promotion. Applicable validity blockers do block it.
- Review disputes preserve the original blocking receipt. A current independent recheck must explicitly identify the original receipt, dispute and evidence. `overturned` addresses a mistaken objection; it cannot waive a verified validity defect. `fixed` requires a new method identity, a clear evidence-bound recheck and a Leader decision. It releases only that exact experiment/claim/protocol/evidence basis. Verified defects carry across same-code config changes, successors on the same hypothesis, descendant commits (including renamed nodes), and unchanged cited source blobs on other branches; missing source identity is not proof of a fix. Changing source bytes alone is not a verified repair. The old bad method remains blocked.
- Intellectual ancestry (`parent_id` and typed relations), code source (`code_parent_id` / branch base), comparator (`comparator_experiment_id`) and investment disposition are distinct. An unproven idea may have parallel variants without being relabeled a winner. The actual comparator's scientific method still cannot be presented as a new intervention.
- A bound baseline's valid initial seed prefix may support search before later baseline seeds finish. Matching availability is checked at reservation, claim and submission, before scheduler cost. Comparisons use the method's actual matching seeds. Later unused baseline seeds do not stale an earlier consistent result; changing/retracting a used run does. Full replication remains required for promotion.
- Minimum controls: before any target submission, the Leader approves a design's `预声明最小对照` JSON with 1–3 exact code/config/resource/seed entries. The total matrix must fit the screening budget and each entry fit the target request. `predeclared_control_id` bypasses only the redundant ablation-plan receipt, not validity or scope. Changed claims/designs, extra entries, bigger requests and confirmation do not inherit that exemption.
- Final independent confirmation remains a deliberate selection step. Freeze selected methods/claims after sufficient search replication and controls, use untouched declared confirmation material, bind final numbers/protocol reviews to confirmation evidence, then make the stage decision. No automatic confirmation purchase follows `positive_signal`.
- High-frequency status is a DB projection (plus the message logs' unanswered items) with `go: null` / `eligibility_checked: false`, explicit freshness and current recorded outcomes. Full eligibility/doc/curve rendering runs only on explicit full refresh. Burst display updates coalesce; a display failure cannot undo a committed scientific write. File-write authorization reads fresh DB guard paths independently of the presentation cache and fails closed if that authority is unavailable.
- Review start returns a durable ticket immediately. Equivalent requests deduplicate; one live owner dispatches a ticket. Collection is nonblocking. Interrupted/error results remain inspectable, registered receipts survive publication interruptions, and orphan sessions recover through ticket ownership without silently paying for a second model call.

## Requirement-to-code and regression matrix

All `test_*.py` paths below are under `shared/research-tree/tests/` unless explicitly marked as host tests.

| Requirement | Implementation and retained boundaries | Executable evidence |
|---|---|---|
| R01 Roles and continuing research loop | Both host role routing/prompts; `project_config.py`; `send_message.py`; `research_db.py` role/owner checks, root aliases and Leader-owned advisory task records | `test_fast_workflow.RoleBoundaryTest`; `test_send_message`; Codex `test_advisors_are_real_bound_read_only_sessions_with_distinct_messages`, `test_architect_is_root_only_and_shares_the_legacy_worker_lock`, `test_bound_roles_cannot_impersonate_or_control_execution`; Claude role/hook fixture callbacks |
| R02 On-demand UI | No automatic UI spawn; explicit full refresh/UI session preserved; main-session confirmation and display-failure isolation in both adapters | Codex `test_committed_write_survives_display_failure_and_ui_is_on_demand`, direct-main instruction tests; Claude on-demand and display-failure fixtures; `test_build_site` full-page tests |
| R03 Cheap search vs confirmation | Five-field contracts and exact ceilings; `_cheap_search`, `_check_ready`, reservation/claim checks; existing protocol, import, sanity and budget gates retained | `test_fast_workflow.CheapScreeningTest`, `FastConfirmationTest`; `test_budget_s6`, `test_import`, `test_units`, `test_identity`, existing confirmation regressions |
| R04 Review disputes | `dispute_code_review`, `adjudicate_code_review`; original receipt retained; current evidence manifests; verified defects carry forward; exact `fixed` resolution | `test_fast_workflow.ReviewDisputesTest`; known-leakage/claim-change/cloned-node checks in `CheapScreeningTest`; `test_review_tickets` retains original receipt and failed-round output |
| R05 Correct review subject | Experiment code review resolves exact method/claim/experiment; unsupported subjects rejected before backend/precheck/model | `test_fast_research.IdentityReplicationsTest`; `test_review_tickets.ReviewSubjectTest` and unsupported-subject tests |
| R06 Scientific config intervention | Compare canonical scientific method identity against the explicit comparator (or ablation target), not just branch commit; operational-only differences excluded | `test_fast_research` same-code scientific and operational-only tests; `test_fast_workflow.IndependentLineageTest.test_different_code_origin_cannot_launder_an_identical_comparator_method`; identity regressions |
| R07 Current positive follow-up | Current applicable `positive_signal` permits bounded worker replication; old close/beats_parent compatibility; stale/newer/inconclusive results do not grant expansion | `test_fast_research` positive/inconclusive/stale replication tests; `CheapScreeningTest`; existing budget/seed tests |
| R08 Incremental scope/discovery | `discovery.evaluate_candidate`, `select_candidate`, CLI candidate gate; initial confirmation independent from pending discovery; candidate revision/hash/scope binding | All `test_incremental_discovery` classes (A ready/B pending; strict own receipts; no global PASS; confirmation remains pending; scope borrowing/doc-update rejection); `test_fast_workflow.StrictIncrementalIntegrationTest`; both host prompt-combination fixtures |
| R09 Decoupled lineage | New code/comparator fields, typed relation validation and cycle rejection; current comparator/harness checks; snapshot and UI separated lineage | `test_fast_workflow.IndependentLineageTest`; `test_build_site.SummaryTest.test_intellectual_ancestry_code_source_and_comparator_are_separate`; legacy tree/relation tests |
| R10 Incremental baseline | `_available_baseline`, matching seed admission at reserve/claim/submit, partial evaluation view, matched-input evidence fingerprint, full promotion replication gate | `test_fast_workflow.IncrementalBaselineTest` (42 first, 43/44 later, unchanged earlier evidence, retraction staleness, missing pair blocked before scheduling); `FastConfirmationTest`; existing protocol/identity tests |
| R11 Minimum controls | `approve_minimum_controls`, exact identity/seeds/ceilings and frozen design/claim check; unapproved/complex controls retain ablation review | `test_fast_workflow.MinimumControlTest`; legacy ablation/design tests |
| R12 Independent final confirmation | Existing candidate/batch/material-use ledger and final five-dimensional rechecks retained; default prompts postpone selection/confirmation until warranted | `test_fast_workflow.FastConfirmationTest`; `test_confirmation`, `test_rechecks`, `test_states_s3`, `test_s7`, existing project GO/NOT GO tests |
| R13 Lightweight status and tickets | `build_site` DB projection; modern outcomes visible without legacy verdict; host coalescing; `review_call` atomic ticket, lease, collection and crash recovery | `test_build_site.SummaryTest`; modern lightweight/full outcome check in `CheapScreeningTest`; all `test_review_tickets`; immediate/nonblocking Codex handler tests; Claude coalescing/failure fixtures |

No requirement is counted as satisfied by a prompt change alone where an executable gate or host permission was required. Existing final-confirmation functionality is deliberately preserved and retested rather than reimplemented.

## Schema and legacy compatibility

Schema **22** adds workflow/discovery modes, code/comparator lineage, screening contract, minimum-control approval and review-dispute audit fields. The existing additive `schema/create_db.py --upgrade` procedure is retained: stop writers and back up the research directory first. Upgrade raises metadata/index availability without rewriting old scientific results. Missing new properties use strict/legacy fallbacks; `test_fast_workflow.FastSchemaCompatibilityTest` checks schema-21 upgrade idempotence, unchanged evidence and strict admission. Historical evaluations remain historical; upgrade never invents missing identity, confirmations or review bindings.

Legacy actor names, full/precheck discovery, strict design requirements, explicit full UI and verdict labels remain supported. New fast workflow is an explicit project choice. Known unresolved review objections cannot be erased merely by superseding a receipt; this is an intentional validity correction, with an evidence-backed resolution path.

## Reproduction

Use an isolated HOME and fixture-only Git author/committer for tests that create temporary Git histories; do not use that test identity for actual repository commits.

```sh
python3 scripts/build_plugins.py --target all
HOME=/path/to/test-home \
GIT_AUTHOR_NAME='Research Tree Test' GIT_AUTHOR_EMAIL=test@example.invalid \
GIT_COMMITTER_NAME='Research Tree Test' GIT_COMMITTER_EMAIL=test@example.invalid \
UV_CACHE_DIR=/path/to/uv-cache .venv/bin/python scripts/run_tests.py
node scripts/run_claude_fixtures.cjs
node scripts/run_claude_fixtures.cjs dist/claude/plugins/research-tree
```

The Python runner includes shared core, repository packaging/regressions and the **built Codex** adapter. The adapter uses deterministic fake-CLI subprocess transport, not real model calls. Claude's fixture runner uses already-installed Babel/Playwright tooling and clearly labels native-SDK callbacks as unrun. See `claude-mod/research-tree/TESTING.md` for compiler selection and native validation commands.

Final aggregate: **511 tests in 135 classes passed**; both host packages built. Claude source and built-package fixture runs each passed **37 callbacks**, with **7 native-SDK callbacks explicitly unrun**. Changed-scope Ruff F/E9, Python compilation, Node syntax, review schema parity and diff checks passed. Independent read-only final review found no unresolved P0/P1. Counts and limitations are also recorded in `shared/research-tree/RELEASE.md`. Native Claude SDK/UI/type compatibility, actual installed-host/model end-to-end scenarios, scheduler/GPU execution, and controlled scientific efficacy remain unverified by these fixtures.

## Milestones and independent review

1. `683ca4855262e6bf08bf132ed06e1d005443111d`: coherent method-bound review, scientific-config intervention and current-signal replication patch. Both packages built; exact staged snapshot passed 441 tests before commit. Pushed and remote SHA verified.
2. Integrated role/search/discovery/lineage/control/status/ticket implementation: a separate read-only scientific/safety review reproduced and drove fixes for claim/config laundering of blockers, candidate scope borrowing, no-op comparator identity, allocation inflation, pre-scheduler pairing, advisory task lifecycle, modern outcome display and crash-safe review ownership. Targeted regressions accompany the fixes. Final build/suite outcomes are recorded with the milestone, without claiming fixture counts prove scientific quality.
