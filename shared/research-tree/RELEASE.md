# 验证范围说明（2026-10-11）

本轮为快速研究工作流改进（R01–R13），完整对应关系见仓库的 `plans/fast-research-workflow.md`。以下是本轮实际验证，不继承历史宿主验收作为新功能证明。

- **共享核心、仓库和构建后的 Codex 适配器**：`scripts/run_tests.py` 汇总 **511 个确定性测试、135 个测试类全部通过**。测试使用隔离 HOME 与仅供临时测试仓库使用的 Git 身份。Codex 传输为假 CLI 子进程夹具，不是真实模型调用。
- **两端安装包**：`scripts/build_plugins.py --target all` 成功生成 Claude 与 Codex 包；源码/打包一致性有仓库回归覆盖。
- **Claude 适配器**：`scripts/run_claude_fixtures.cjs` 在源码与构建后的包各通过 **37 个确定性 hook 回调**，失败为 0；另有 **7 个需要原生 SDK 的回调明确未运行**。Babel 只转译语法，不是 TypeScript 类型检查，也不验证真实宿主界面。复现说明在仓库 `claude-mod/research-tree/TESTING.md`。
- **静态和独立复核**：改动范围的 Python 编译、Ruff F/E9、Node 语法、内嵌评审 JSON schema 一致性及 `git diff --check` 通过。独立只读科学/安全复核发现的准入、身份、争议、任务生命周期、崩溃恢复和文件写保护问题均修复并加入回归；终轮无未解决 P0/P1。
- **兼容性**：schema 22 为增量扩展；测试覆盖 schema 21 升级幂等、历史证据不变与未显式选择新模式时保留 strict。旧数据库写入前仍须停写、备份并运行既有升级流程。

**未验证**：本轮未运行 Claude 原生 SDK/界面/安装场景、真实 Codex/Claude 模型端到端科研场景、GPU、PBS、生产调度器或固定资源 A/B/C 科研效能比较。现有原始证据、独立确认、预算和防重复机制经回归保留；测试数量不证明科学可靠性或发现质量，也不支持宣称科研速度已提高。

以下保留历史验证记录，其范围和遗留 OPEN 项不被本轮确定性测试改写。

## 历史验证记录（2026-10-07）

本轮修复以原始回执、运行产物和独立审计验证功能；测试数量不证明科学可靠性。

- **模拟与传输夹具**：共享核心、适配器和打包测试使用确定性输入；原生安装、exec/resume/UI 夹具使用实际 Codex CLI 和本地 Responses 服务，未调用实际模型。这些结果验证接口、权限与会话传输。
- **真实宿主测试**：实际 Codex v0.160.1（gpt-6-luna）及 Claude Code v2.1.292/v2.1.293（claude-sonnet-5-5），包含插件 MCP、固定身份 worker/lens、跨族 Claude Code/Pi 评审和本地 CPU toy training。部分功能场景使用预声明 simulation_only 指标公式；另有 synthetic_proxy 场景直接由验证集 correct/n 得到 accuracy。两者均只用于工程验收，不能据此声称真实科研改进。失败调用、权限拒绝与原始费用保留。
- **真实 GPU 或调度器训练**：本轮未执行 GPU、PBS 或集群科研作业；不将 CPU toy training、模拟指标或本地传输夹具记作此类验证。

11 §2 的完整固定资源 A/B/C 科研效能比较仍未执行、未获豁免；12 §1 整体 M8 完成标准仍 OPEN。模型宿主费用或未提供账单不从 reviewer CLI 费用推断。
