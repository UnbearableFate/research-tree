# Codex 补测基础设施 Fable 第二轮评审

日期：2026-10-07。新会话、模型 claude-fable-5-1、effort high。只给设计、改动与测试路径。无 CRITICAL/MAJOR。

## 元数据

```json
{
  "is_error": false,
  "terminal_reason": "completed",
  "modelUsage": {
    "claude-fable-5-1": {
      "inputTokens": 258,
      "outputTokens": 20478,
      "cacheReadInputTokens": 658347,
      "cacheCreationInputTokens": 133375,
      "webSearchRequests": 0,
      "costUSD": 3.85856675,
      "contextWindow": 1000000,
      "maxOutputTokens": 64000,
      "thinkingTokens": 10990,
      "canonicalModel": "claude-fable-5-1",
      "provider": "firstParty",
      "costBasis": "list"
    }
  },
  "total_cost_usd": 3.85856675
}
```

## 原文

**Review scope.** I read the three design files named in the brief, every changed file, the three test files, and the counterparts needed to judge parity and regression: the Codex runtime and MCP server, the Claude hook, the shared review wrapper, the config schema and templates, hooks.json, and the Codex test records.

**What is consistent with the design.** The MCP wait limit is now the same number in the plugin manifest, the background exec configuration and the server's own subprocess cap, and the Codex README states it. The hook's new observed-model recording on SessionStart and PostToolUse gives the reviewer wrapper the Leader family it needs under 09 §2.1 step 3, deduplicates per session, and records a real model change. The adapter test for that path drives the hook handler after a live init and checks the wrapper's own reader, so it exercises the behaviour rather than a fixture shortcut. The reviewer-bypass guard and the reviewer-identity block match the Claude hook clause for clause. The install check's six expected tool names equal the server's schema list, and both scripts strip credentials, isolate CODEX_HOME and refuse an existing evidence directory. The read-only method lists of both hosts are still tied to the shared constant by the packaging parity test. The generated test project's plan satisfies the plan validator and its version-2 configuration keys all exist in the schema.

**Gaps.** Nothing I read rises to CRITICAL or MAJOR. The remaining issues are about evidence and robustness. The whole observed-model path on Codex rests on a `model` field in the host's hook payload, and nothing in the repository shows that field exists: the only Codex test record has no observed entries, and the attach fallback writes the Leader model to leader.json only, so it does not unblock a cross-family review. The two supplement documents disagree on whether the install check has been re-run, and no Codex test log records the runs that the review record says passed. The server-side and client-side timeouts are equal, so a hang that reaches the cap expires on both sides at once and the server's error text can be lost. The Claude host still caps one review process at ten minutes while the Codex host allows an hour, and an earlier review record claims the hosts are aligned. No test pins the three timeout values together. Finally, the plan template still lacks the "已尝试与无效的方法" section that 01 §2 calls for and that the test-project generator already writes.

```json
[
  {"severity": "MINOR", "file": "codex-plugin/research-tree/tools/codex_hook.py", "line": 185, "claim": "Observed-model recording on Codex depends on a `model` field in the host's hook payload; the repository holds no evidence that Codex supplies it, and the attach fallback does not cover the gap, so every Codex-host review could return REVIEW_UNAVAILABLE and `inherit` workers could fail until a real-host run proves otherwise.", "evidence": "codex_hook.py:185 writes an observed record only when event.get('model') is truthy; hooks.json registers the four events without documenting fields; plans/design/test-logs/M1-codex.md:18 reports agent_models.jsonl with four requested records and no observed entry; codex_runtime.py:401-404 attach writes leader.json only, while review_call.py:77-89 leader_model reads only logs/agent_models.jsonl; README.md:39 states hooks record the actual model.", "suggested_fix": "Record one real SessionStart and one PostToolUse hook input (fields only) in the Codex test log as evidence; if `model` is absent, have research_control attach with a model also append an rld/main observed record via tree.log_agent_model, and say in SKILL.md that attach is what satisfies the reviewer family check when hooks are unavailable."},
  {"severity": "MINOR", "file": "plans/design/test-logs/codex-real-test-plan.md", "line": 41, "claim": "The supplement's own records disagree on the install check's status, and no Codex test log exists for the runs the review record says passed, so 14 §6 has no evidence for the modified scripts.", "evidence": "codex-real-test-plan.md:41 says 待重新运行安装检查; plans/design/reviews/codex-real-infrastructure-r1.md:33 says 安装、会话检查已通过; plans/design/test-logs/ contains no Codex entry newer than M1-codex.md; the saved mcp.json cited at r1 line 29 lives under /tmp, not in the repository.", "suggested_fix": "Add plans/design/test-logs/codex-infrastructure.md with the commands, the evidence directory, the tools object from mcp.json and the sessions result.json, then update line 41 to point at it."},
  {"severity": "MINOR", "file": "plans/design/test-logs/codex-real-test-plan.md", "line": 36, "claim": "The plan cites AGENTS.md for a rule that the current AGENTS.md does not contain, so the stated basis for restricting final-stage tests to claude-mod is dangling.", "evidence": "codex-real-test-plan.md:36 says 按 AGENTS.md 只针对 claude-mod; AGENTS.md has three lines about codegraph, git and a reference repository, none about test scope.", "suggested_fix": "Either restore the rule to AGENTS.md or state the rule and its source inside the test plan."},
  {"severity": "MINOR", "file": "codex-plugin/research-tree/tools/codex_mcp.py", "line": 87, "claim": "The server's subprocess cap for research_review equals the Codex client's tool timeout, so a call that reaches the cap expires on both sides in the same instant and the server's error text naming the review session may never reach the Leader.", "evidence": "codex_mcp.py:87 timeout=3900 for research_review; .mcp.json:7 tool_timeout_sec 3900; codex_agent.py:40 tool_timeout_sec 3900; review_call.py:57 MAX_CALL_S 3600 leaves 300 s shared between the runtime exit and the client wait.", "suggested_fix": "Keep the server cap strictly below the client timeout, for example 3800 in codex_mcp.py with 3900 on both client sides, and note the ordering in the README sentence at line 57."},
  {"severity": "MINOR", "file": "codex-plugin/research-tree/README.md", "line": 57, "claim": "Effective review wall time differs between hosts: Codex allows the full 3600 s, the Claude host caps one process at 600 s and passes a 570 s deadline, and an earlier review record states the hosts are aligned at 3900 s; with the template's timeout_s of 900 a Claude-host round is cut before the reviewer's own timeout.", "evidence": "codex-plugin/research-tree/README.md:57 states 3900 s; claude-mod/research-tree/hooks/register.tsx:21 MAX_PROCESS_MS = 600_000 and line 1267 passes --deadline-s 570; shared/research-tree/schema/config.template.yaml:130 timeout_s: 900; plans/design/reviews/M4-r1.md:48 says 两端宿主统一等待 3900 s.", "suggested_fix": "State the per-host limit in each README and in 09 §5 (Codex 3600 s, Claude 570 s), and correct the M4-r1 fix note; optionally lower the template's timeout_s or document that Claude-host reviews should set it below 570."},
  {"severity": "MINOR", "file": "codex-plugin/research-tree/tests/test_codex_adapter.py", "line": 223, "claim": "No test ties the three Codex timeout values together, so the plugin manifest, the background exec configuration and the server cap can drift apart again without a failing test.", "evidence": "test_codex_adapter.py:223 asserts only default_tools_approval_mode in the exec argv; tests/test_packaging.py:20-33 checks parity only for READ_METHODS; the 3900 value appears in .mcp.json:7, codex_agent.py:40 and codex_mcp.py:87 with no assertion.", "suggested_fix": "In the adapter test, read .mcp.json's tool_timeout_sec, assert the exec argv contains the same value, and assert codex_mcp's research_review timeout does not exceed it."},
  {"severity": "MINOR", "file": "shared/research-tree/schema/plan.template.md", "line": 58, "claim": "The plan template lacks the 已尝试与无效的方法 section that 01 §2 adds, while the real-host test-project generator already writes it, so user plans made by prepare and test plans differ in structure.", "evidence": "plan.template.md headings (grep ^##) are 研究目标, 非目标, 初始假说, 期望使用的模型, 期望使用的训练数据集, 期望使用的评测数据集, 期望使用的基线, 评测与指标, 实验范围, 验收要求, 参考资料; scripts/make_rt_test_project.py:209 writes ## 已尝试与无效的方法; plans/design/01-setup-and-config.md:24 lists it as a new section.", "suggested_fix": "Add the section with a hint comment to plan.template.md so prepare's plan matches 01 §2 and the test-project plan."}
]
```

## 处理

- 实际原生 M0r2 会话已写入 rld/main observed=gpt-6-luna；先 init 后工具事件的缺口修复经原生流程核实。不用 attach 参数伪造观察；完整后台 SessionStart 的真实记录留待 worker 测试。
- 基础设施检查与当前状态已写入 codex-infrastructure.md，方案状态同步；用户改动 AGENTS.md 的时间与本轮委派依据已明确，未恢复用户删除的条款。
- 评审 timeout 先退出的余量缺陷由新增回归测试复现（3900 not less than 3900），将服务子进程 cap 改为 3800 秒，客户端仍 3900 秒。新测试约束 MAX_CALL_S < 服务 cap < 两个客户端，并核对失败信息透传。
- Codex README 明确 Claude 当前 570 秒与 Codex 3600 秒的有效差别。既有 M4-r1 的两端统一等待描述不符合当前 Claude 代码；保留原始历史评审，附加本轮勘误，不将旧描述当作验证证据。Claude 评审时限行为不在本次 Codex 补测的改动范围。
- plan.template.md 补上 01 §2 指定的“已尝试与无效的方法”；真实测试计划原已有该节。
- 以上新增修复需重新验证与终审；本轮仅证明评审时版本无 CRITICAL/MAJOR。
