# 交接文档：research-tree 证据一致性改进轮（S0–S7）

更新：2026-10-09。主分支 `bug-fix-1008`（起点 `253d50d`）。任务定义：
[`plans/research-tree-implementation-and-real-scenarios.md`](plans/research-tree-implementation-and-real-scenarios.md)（下称实施文档）。
状态总表、各次场景的结论与修复：[`plans/design/test-logs/implementation-status.md`](plans/design/test-logs/implementation-status.md)。

**结论先行：没有任何阶段是 PASS。** Fable 5.1 不可用（账户缺 usage credits），所有阶段评审/终审 BLOCKED；
S1 的两端真实场景仍在重测；S2–S7 已实现并有 REG，真实场景未跑。

## 1. 代码在哪里（按阶段叠加的分支，每个都有独立 worktree）

| 阶段 | 分支 / worktree | 内容 | 测试 |
| --- | --- | --- | --- |
| S0 | 已在 `bug-fix-1008` | 场景底座、REG-S0、real-run-error #1–#19 | `tests/test_scenarios.py` |
| S1 | 已并入 `bug-fix-1008`（`s1-dev` 合并） | 方法身份、主张版本、稳定候选 revision、评审依据 | `test_identity.py` |
| S2 | `s2-dev` / `/home/yu/workspace/rt-s2-wt` | 冻结候选、确认批次、材料使用账 | `test_confirmation.py` |
| S3 | `s3-dev` / `rt-s3-wt` | 原始单位与 manifest 快照、独立性字段、`migrate_units` | `test_units.py` |
| S4 | `s4-dev` / `rt-s4-wt` | 回执清单规则 `review_rules.py`、证据路径核验、findings→obligation 闭环、模型家族、补查 `literature_followup`、ABANDON 证据 | `test_reviews_s4.py`、`test_review_call.py` |
| S5 | `s5-dev` / `rt-s5-wt` | `fix_verification` 固定检查器、`memory_status`、过滤规则、`migrate_memory` | `test_memory_s5.py` |
| S6 | `s6-dev` / `rt-s6-wt` | 分池由实验决定、请求身份、`migrate_budget`、`attempt_metrics.py` | `test_budget_s6.py`、`tests/test_attempt_metrics.py` |
| S7 | `s7-dev` / `rt-s7-wt` | `repetition_advice`、`note_findings(finding_ids)`、评分器重写、私有评测器与 bwrap 沙箱 | `test_s7.py`、`tests/test_benchmark.py`、`tests/test_private_eval.py` |

分支是线性叠加的（s2←s1，s3←s2 … s7←s6）。S1 之后在 `bug-fix-1008` 上做的修复（ToyOpt runner 的优化器选项、
`review_basis` 报错、发现命令注入、控制器改进）**尚未合入 s2–s7**；按阶段顺序把 sN-dev 合入 bug-fix-1008 时一并解决冲突
（register.tsx、codex_runtime.py、research_db.py 可能有小冲突）。每个分支的 schema 版本依次是 v16…v21。

## 2. 真实场景（`scripts/scenarios/run_s1.sh`、`run_s2.sh`）

- 用法：`bash scripts/scenarios/run_sN.sh <claude|codex> <attempt两位> <agent-pane> <scheduler-pane>`，先 `herdr tab create`
  并 `herdr pane split` 出两个 pane。控制器只以虚构用户身份输入；每步后写只读检查点；遇到宿主用量上限立即停止（BLOCKED）；
  agent 提问时记录并关闭对话框；结束时关闭 pane、删除 Codex 登录副本、把本次构建打包到 `rt-scenarios/archive/`。
- **用户要求：herdr 测试结束后及时关闭 pane。**
- 记录：`python3 scripts/scenarios/s1_records.py <host> <n> [--blocked "原因" --blocked-scenario SC-…]`，证据归档进
  `plans/design/test-logs/scenarios/S1/<host>/evidence-aNN/`。
- 注意：测试宿主（Claude Code）与实施会话共用账户额度；Codex 周额度约剩 25%（10-14 重置），Codex 场景只在 Claude 先跑通后再跑。
- S1 历史：a01 夹具缺陷 FAIL；a02 发现命令缺失 FAIL + 用量上限 BLOCKED；a03 因旧构建污染中止；a04 运行中（见状态表）。

## 3. 剩余工作（按顺序）

1. S1：Claude a04 → 记录；然后 Codex S1（新 tab）。两端 PASS 后等待 Fable 终审。
2. 把 s2-dev…s7-dev 依次合入 bug-fix-1008（每次合并后跑全部测试、重建），再跑该阶段两端场景：S2 有 `run_s2.sh`；
   S3–S7 的控制器尚未写（参照 run_s2.sh 与实施文档 §7.5、§8.7、§9.6、§10.6、§11.7）。
3. S7 pilot（12 个 episode）需要冻结 B=`616d646` 与 C 的构建、在 bwrap 沙箱中运行宿主与调度服务、私有评测器在沙箱外
   （`scripts/private_eval/`）；预算很可能不足，届时按实施文档 §11.5 标注“S7-pilot 未完成”。
4. Fable 恢复后：按顺序补 S0 终审（第 4 轮）与 S1–S7 的评审/终审（`scripts/stage_review.py`）。

## 4. 环境与约定

- 测试：`.venv/bin/python -m unittest discover -s shared/research-tree/tests`（约 7 分钟）；`-s tests`；
  `python3 scripts/build_plugins.py`；Codex 适配器测试在构建目录 `dist/codex/plugins/research-tree` 内运行。
- 模型矩阵（§2.2 最后修订，effort 均为 medium）：Claude 宿主 `claude-haiku-5-5`、reviewer `openai/gpt-6-luna`（pi）；
  Codex 宿主 `gpt-6-luna`、reviewer `anthropic/claude-haiku-5-5`；阶段评审 `claude-fable-5-1` high（BLOCKED）。
- 场景数据：`/home/yu/workspace/rt-scenarios/`；助手脚本 `say.sh`、`waitidle.sh`、`drive_codex.sh`（副本在 `scripts/scenarios/`）。
- 不要在驱动运行时修改它正在执行的 bash 脚本；pkill 时不要用会匹配自身命令行的模式。
