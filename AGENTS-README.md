# 当前维护入口与历史档案说明

当前接口只支持配置 version 3、数据库 schema 23，以及固定的快速筛选与增量发现。请以 [README](README.md)、[当前规则](shared/research-tree/rules/research-tree-rules.md) 和 [验证范围](shared/research-tree/RELEASE.md) 为准。

下文是 2026-10-09 的历史交接记录，保留用于理解既有证据和未完成项，不是当前执行计划。旧 S0–S7 驱动、升级控制器及对应助手脚本已从活动代码中移除；其中的命令、配置、角色和旧数据库要求不适用于当前版本。不要据此恢复兼容模式或改写历史项目。当前仍可用的虚构测试底座见 [scripts/scenarios/README.md](scripts/scenarios/README.md)。

---

# 交接文档：research-tree 证据一致性改进轮（S0–S7）

更新：2026-10-09。主分支 `bug-fix-1008`（起点 `253d50d`）。任务定义：
[`plans/research-tree-implementation-and-real-scenarios.md`](plans/research-tree-implementation-and-real-scenarios.md)（下称实施文档）。
状态总表、各次场景的结论与修复：[`plans/design/test-logs/implementation-status.md`](plans/design/test-logs/implementation-status.md)。

**结论先行：没有任何阶段是 PASS。** Fable 5.1 不可用（账户缺 usage credits），所有阶段评审/终审 BLOCKED；
S1 的真实场景两端 PASS（只差终审）；S2–S7 已实现、有 REG、已合入主分支，真实场景控制器已写好但尚未运行。

## 1. 代码在哪里

S1–S7 的实现都已合入 `bug-fix-1008`（2026-10-09，经集成分支 `integ` / worktree `rt-integ` 合并并全量测试；之后
`run_tests.py` 并行全量 435 项通过）。各阶段分支 `s2-dev`…`s7-dev` 与其 worktree（`/home/yu/workspace/rt-sN-wt`）保留作历史，
不再在上面开发。schema 版本 21。各阶段 REG：`test_identity.py`（S1）、`test_confirmation.py`（S2）、`test_units.py`（S3）、
`test_reviews_s4.py` + `test_review_call.py`（S4）、`test_memory_s5.py`（S5）、`test_budget_s6.py` + `tests/test_attempt_metrics.py`
（S6）、`test_s7.py` + `tests/test_benchmark.py` + `tests/test_private_eval.py`（S7）。

## 2. 真实场景

- 控制器：S0/S1 用 `scripts/scenarios/run_s0.sh`、`run_s1.sh`；S2–S7 用 `scenario.sh <S2..S7> <claude|codex> <两位 attempt>
  <agent-pane> <scheduler-pane>`（共用 `lib.sh`，阶段正文 `s2.sh`…`s7.sh`；S7 只含 SC-S7-01/02）；SC-S3-03 用
  `run_s3_upgrade.sh`（旧项目经 bwrap 绑定在原路径上由新构建迁移，两份副本 kept/moved）。先 `herdr tab create` 再
  `herdr pane split` 出两个 pane。
- **加速（用户 2026-10-09 批准）**：①`scripts/run_tests.py` 并行测试（约 45 秒）；②`scripts/scenarios/smoke.sh <阶段> [host]`
  冒烟检查控制器管道（约 30 秒，永远不是证据），每次改控制器或助手脚本后先跑；③完整运行在开场后存快照
  `rt-scenarios/<阶段>/prefix-<host>-aNN.tar.gz`，阶段专属场景的重试用 `FORK=<快照> bash scenario.sh ...` 从开场分叉
  （偏离 §2.5；每个阶段 × 宿主仍须一次完整不分叉运行证明 SC-COMMON-01；改动开场路径的修复不能分叉）。细节见
  `scripts/scenarios/README.md`。控制器只以虚构用户身份输入；每步后写只读检查点；宿主用量上限 → 立即
  BLOCKED 停止；agent 提问 → 记录并关闭对话框；结束时关闭 pane、删 Codex 登录副本、把本次构建打包到 `rt-scenarios/archive/`。
- 记录：`s1_records.py`、`s2_records.py`（S3–S7 的记录脚本尚未写，按同样方式从检查点计算断言；分叉 attempt 要读
  `forked_from.json`，把数据库里的原路径映射到副本，并且不写 SC-COMMON-01，见 `s2_records.py`）。
- **用户要求：herdr 测试结束后及时关闭 pane。**
- 测试宿主（Claude Code）与实施会话共用账户额度；Codex 周额度约剩 7%（10-14 重置），Codex 场景只在 Claude 先跑通后再跑。
- S1 进度：两端四个 SC 全部 PASS（Claude a07、Codex a03），只差 Fable 终审。2026-10-09 按用户指示在此停止。
  S2 Claude a01/a02 的发现与修复见 implementation-status.md（含尚未处理的“代码审查发现无异议通道”问题）。

## 3. 剩余工作（按顺序）

1. S1：完成（两端 PASS），等待 Fable 终审。
2. S2…S7 依次：Claude 场景 → 记录脚本 → Codex 场景；S3 另跑 `run_s3_upgrade.sh`（旧项目用 S1 的真实项目，新构建用当前 dist）。
3. S7 pilot（12 个 episode）：需冻结 B=`616d646` 与 C 的构建，宿主与调度服务在 `scripts/private_eval/sandbox.sh` 中运行，
   私有评测器在沙箱外；预算很可能不足，届时按实施文档 §11.5 标注“S7-pilot 未完成”。
4. Fable 恢复后：按顺序补 S0 终审与 S1–S7 的评审/终审（`scripts/stage_review.py`）。

## 4. 环境与约定

- 测试：`python3 scripts/build_plugins.py && python3 scripts/run_tests.py`（共享、仓库、Codex 适配器并行，约 45 秒，434 项）；
  开发中 `python3 scripts/run_tests.py <模块...>`。串行 `unittest discover` 仍可用（约 8 分钟）。
- 模型矩阵（§2.2 最后修订，effort 均为 medium）：Claude 宿主 `claude-haiku-5-5`、reviewer `openai/gpt-6-luna`（pi）；
  Codex 宿主 `gpt-6-luna`、reviewer `anthropic/claude-haiku-5-5`；阶段评审 `claude-fable-5-1` high（BLOCKED）。
- 场景数据：`/home/yu/workspace/rt-scenarios/`；助手脚本 `say.sh`、`waitidle.sh`、`drive_codex.sh`（副本在 `scripts/scenarios/`）。
- 不要在驱动运行时修改它正在执行的 bash 脚本；pkill 时不要用会匹配自身命令行的模式。
