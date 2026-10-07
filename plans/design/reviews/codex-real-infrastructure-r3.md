# Codex 补测基础设施 Fable 第三轮评审

日期：2026-10-07。claude-fable-5-1 high，新会话，只给路径。无 CRITICAL/MAJOR。评审 brief 的范围不包含随后真实 worker 测试发现的 CODEX_HOME、原生 Full access 继承和阻塞消息修复；该批新增修复需另行终审。

## 元数据

```json
{
  "is_error": false,
  "terminal_reason": "completed",
  "modelUsage": {
    "claude-fable-5-1": {
      "inputTokens": 194,
      "outputTokens": 23818,
      "cacheReadInputTokens": 499830,
      "cacheCreationInputTokens": 142827,
      "webSearchRequests": 0,
      "costUSD": 4.1743375,
      "contextWindow": 1000000,
      "maxOutputTokens": 64000,
      "thinkingTokens": 14071,
      "canonicalModel": "claude-fable-5-1",
      "provider": "firstParty",
      "costBasis": "list"
    }
  },
  "total_cost_usd": 4.1743375
}
```

## 原文

**Review of the Codex real-host supplement fixes**

I read the three design files, all ten changed files, the four named test files, and the counterparts needed for parity and regression: the Claude hook (`register.tsx`), the shared `review_call.py`, `codex_runtime.py`, `codex_state.py`, the config schema and template, the Codex hooks manifest and skill, `build_plugins.py`, the root README, and the two supplement records plus the M4 review record.

**What is consistent.** The Codex hook now records an observed model on SessionStart and PostToolUse, keyed by actor and session, deduplicated, and appends again on a real model change; the wrapper's `leader_model` reads exactly those records, so 09 §2.1 step 3 can resolve the Leader's family after an init in a live session. The new adapter test drives `codex_hook.handle` after a real `research_tree.init` and checks `review_call.leader_model`, and `codex_state.project_dir` honours the env override the test sets, so its first "no project yet" assertion is sound. The reviewer-bypass guard, reviewer-identity block and "only rld runs review_call" rule match the Claude hook clause for clause, and the packaging test still ties both hosts' read-only lists to `research_db.READ_METHODS`. The three Codex timeouts are ordered as the README states: wrapper cap 3600 < server subprocess cap 3800 < client waits 3900 in both `.mcp.json` and the exec config, and the new test pins all three together and checks the runtime failure text is returned. The install check's six expected tool names equal `codex_mcp.TOOLS`; the sessions check now waits for the persisted thread id before queuing a follow-up and documents that it has no live Leader. Both scripts isolate `CODEX_HOME` and strip credentials. The plan template gains the "已尝试与无效的方法" section 01 §2 requires, the template-based init test still passes by construction (only the two required sections are checked), and the test-project generator's plan and version-2 config agree with the schema.

**Gaps.** Nothing I read is CRITICAL or MAJOR. The remaining issues are documentation and evidence. The M4 review record still asserts both hosts wait 3900 s with no in-file erratum, while the Claude host caps a review process at 600 s. The Codex skill and README present `attach` as the substitute for hooks, but attach writes only `leader.json`, so without hook-observed records every cross-family review returns `REVIEW_UNAVAILABLE`, and the docs do not say so. The plan template's hypothesis hint omits the "由发现流程产生。" option that 01 §2 and 02 allow, the root README's section list omits the two added sections, and nothing in the shared tools consumes the new "已尝试" section that 01 §2 says feeds discovery and memory. Finally, the infrastructure test log records a 17-test adapter run, while the file now holds 18 tests, and the fixes made after the second review (3800 s cap, README sentence, template section) have no logged run.

```json
[
  {"severity": "MINOR", "file": "plans/design/reviews/M4-r1.md", "line": 48, "claim": "The M4 review record still states that both hosts wait 3900 s for a review, which contradicts the Claude adapter and the Codex README; no erratum was added to the file.", "evidence": "M4-r1.md:48 says 两端宿主统一等待 3900 s; grep for 勘误 or 570 in that file finds nothing. claude-mod/research-tree/hooks/register.tsx:21 MAX_PROCESS_MS = 600_000 and :1267 passes --deadline-s 570; codex-plugin/research-tree/README.md:59 states the Claude host's 570 s deadline. codex-real-infrastructure-r2.md:56 says an erratum was appended, but only in the r2 record itself.", "suggested_fix": "Append one line to M4-r1.md item 4 pointing to codex-real-infrastructure-r2.md and stating the actual per-host limits (Codex 3600 s wrapper cap under a 3900 s client wait; Claude 570 s)."},
  {"severity": "MINOR", "file": "codex-plugin/research-tree/skills/research-tree/SKILL.md", "line": 124, "claim": "The skill and README present research_control attach as the fallback when hooks are unavailable, but attach records the model only in leader.json; review_call reads observed records in logs/agent_models.jsonl, so without hooks every research_review fails with REVIEW_UNAVAILABLE and the docs do not say so.", "evidence": "SKILL.md:124-127 and README.md:77-78 describe attach as registering the session ID and model when hooks are unavailable. codex_runtime.py:401-404 writes leader.json only. review_call.py:77-89 leader_model reads only logs/agent_models.jsonl, and review_call.py:380-384 raises REVIEW_UNAVAILABLE when no family can be placed. codex_hook.py:185-209 is the only Codex writer of observed records.", "suggested_fix": "State in SKILL.md and README.md that attach satisfies inherit for workers/UI but that cross-family reviews (require_cross_family) need the hook-observed model record; with hooks untrusted, reviews return REVIEW_UNAVAILABLE until hooks are enabled."},
  {"severity": "MINOR", "file": "shared/research-tree/schema/plan.template.md", "line": 20, "claim": "The 初始假说 hint does not mention the 由发现流程产生。 option that 01 §2 and 02 define, and the root README's list of plan sections omits the two sections the template now has (非目标, 已尝试与无效的方法).", "evidence": "plan.template.md:20-25 only shows the hypothesis format. plans/design/01-setup-and-config.md:23 and 02-discovery.md:43 allow 由发现流程产生。; scripts/make_rt_test_project.py:236 writes it for --hypotheses 0. README.md:90 lists the sections without 非目标 or 已尝试与无效的方法.", "suggested_fix": "Add a line to the template's 初始假说 comment: 没有假说时写“由发现流程产生。”（需要 discovery.mode 为 precheck/full）; add the two sections to README.md:90."},
  {"severity": "MINOR", "file": "shared/research-tree/schema/plan.template.md", "line": 63, "claim": "The new 已尝试与无效的方法 section is declared by 01 §2 as the ban list for discovery candidate generation and the initial memory lessons, and its comment promises it avoids repeated directions, but no shared tool reads it.", "evidence": "plan.template.md:63-66 comment says 避免重复方向. plans/design/01-setup-and-config.md:24 states the section feeds 02 and 08. A grep for 无效/已尝试/tried in shared/research-tree/tools/{discovery,memory,research_tree,codex_prompts}.py finds nothing; repo-wide the string appears only in the template and scripts/make_rt_test_project.py:209.", "suggested_fix": "Either wire the section into discovery (exclude listed approaches from candidate generation) and memory (seed lessons at init) or soften the template comment to say the Leader reads it when planning, and record the gap against the M6/M7 batches."},
  {"severity": "MINOR", "file": "plans/design/test-logs/codex-infrastructure.md", "line": 23, "claim": "The logged adapter run (17 tests) predates the current test file (18 tests), and the fixes made after the second review (server cap 3800, README sentence, template section, the deadline test) have no recorded run, so 14 §6 has no evidence that the current state passes.", "evidence": "codex-infrastructure.md:23 records 17 tests; codex-plugin/research-tree/tests/test_codex_adapter.py defines 18 test methods (17 in AdapterTest, 1 in PrepareEntryTest), including test_review_deadlines_leave_time_to_return_the_runtime_failure at line 167. codex-real-infrastructure-r2.md:55-58 lists those fixes and says they still need re-verification; codex-infrastructure.md:38 says the second review was still running.", "suggested_fix": "Re-run the 14 §2 command list on the current tree and build, then update the table with the new counts, the rebuilt dist, and the r2 completion status."}
]
```

## 处理

- 18 项 deadline 修复版 adapter 测试、10 项打包测试和 16 项 prepare/config 核心测试均已通过；随后实际 worker 修复版 adapter 为 19 项，记录同步至 codex-infrastructure.md。
- M4 历史记录的超时说明、attach 的 observed 限制与模板/README 提示已列入待同步文档，不把历史描述当作当前验证证据。
- “已尝试”如何约束发现与记忆由 M6/M7 的真实测试核验。RLD 当前会读取完整用户计划，静态检索不到专用字段读取本身不足以证明其被忽略；不增加尚无真实失败证据的解析路径。
