# 验证范围说明（2026-10-07）

本轮修复以原始回执、运行产物和独立审计验证功能；测试数量不证明科学可靠性。

- **模拟与传输夹具**：共享核心、适配器和打包测试使用确定性输入；原生安装、exec/resume/UI 夹具使用实际 Codex CLI 和本地 Responses 服务，未调用实际模型。这些结果验证接口、权限与会话传输。
- **真实宿主测试**：实际 Codex v0.160.1（gpt-6-luna）及 Claude Code v2.1.292/v2.1.293（claude-sonnet-5-5），包含插件 MCP、固定身份 worker/lens、跨族 Claude Code/Pi 评审和本地 CPU toy training。部分功能场景使用预声明 simulation_only 指标公式；另有 synthetic_proxy 场景直接由验证集 correct/n 得到 accuracy。两者均只用于工程验收，不能据此声称真实科研改进。失败调用、权限拒绝与原始费用保留。
- **真实 GPU 或调度器训练**：本轮未执行 GPU、PBS 或集群科研作业；不将 CPU toy training、模拟指标或本地传输夹具记作此类验证。

11 §2 的完整固定资源 A/B/C 科研效能比较仍未执行、未获豁免；12 §1 整体 M8 完成标准仍 OPEN。模型宿主费用或未提供账单不从 reviewer CLI 费用推断。
