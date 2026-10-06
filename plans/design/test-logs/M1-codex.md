# M1 Codex 宿主测试记录（未完成，用户决定放弃）

日期：2026-10-06。用户决定：阶段末测试只覆盖 Claude 宿主，Codex 宿主测试中止。本文只记录中止前的观察，**M1 场景（STAT_MISMATCH）在 Codex 端未执行，状态为 blocked/dropped**，不得写成通过。

## 1. rt-test-M1-codex（第一次尝试）

宿主 codex-cli，agent `rt-codex`，gpt-6-luna medium，隔离 `CODEX_HOME=$T/codex-home`。prepare → init → 规划 → 确认均完成；根 worker 由适配器以后台 `codex exec` 启动后，
第一次调用 research_db 即被拒：`MCP tool call requires approval, but approval policy is never`。worker 没有绕过，Leader 记录为阻塞（报告 D-0016）；框架未改，sanity/基线/冻结/SOTA 均未完成。
修复（主 agent）：适配器给后台 worker 传 `mcp_servers.research_tree.default_tools_approval_mode="approve"`，并重建 dist/codex。同时 Codex 周额度只剩 2%。

## 2. rt-test-M1b-codex（修复后，部分运行）

- `CODEX_HOME=$T/codex-home codex plugin add research-tree@research-tree --json` 成功，缓存与 dist/codex 逐文件一致（diff 无差异）。
- 过程中的测试环境问题（不是插件缺陷）：`herdr agent start` 不继承调用方的 `CODEX_HOME`，第一次 pane 启动用的是默认 `~/.codex`（该会话已退出，只跑过一次没有匹配技能的 prepare）；之后先在 pane shell 里 `export CODEX_HOME` 再启动。
  新项目未被信任时工作区只读，`prepare` 无法写 `.git`/`uv init`；在 `codex-home/config.toml` 增加该项目 `trust_level="trusted"` 后重启通过。
- 审批：prepare 的 uv/网络、research_tree 的 MCP 工具（research_control、research_db、post_to_ui）均以 "Allow for this session" 通过；文献下载（arxiv/mlr，保存到 `research/<id>/cache/literature/`）与 Leader 提交 harness 的 git commit 各批准一次。
- `$research-tree prepare`、`init`、确认（用户原话）均执行；确认后根 worker 能调用 research_db（旧 bug 不再出现）。
- 中止时数据库（只读核对）：project `rt-test-m1b-codex` active；6 个 run，EV-0001、EV-0002，seed 17/23/42；`agent_models.jsonl` 中 worker/root 的 requested 为 gpt-6-luna medium（4 条，无 observed 条目）。
- 可疑点：Leader 本人（而不是 worker）提交 harness（git add/commit 请求审批，理由 "May I commit the reviewed harness"），可能是 worker 沙箱不能提交；未进一步核实。
- 未执行：sanity/基线/冻结/SOTA 的数据库核对、M1 错数字场景、build_site --check。无 reviewer 费用。
