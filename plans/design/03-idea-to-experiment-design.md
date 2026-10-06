---
title: "阶段 2：从想法到实验设计"
stage: "阶段 2"
status: "proposed; not implemented"
prepared_on: "2026-10-06"
package: "plans/design（见 README.md）"
sources: "新写；ARIS skills/research-refine、experiment-plan、ablation-planner、experiment-bridge、result-to-claim、shared-references/experiment-integrity.md、templates/EXPERIMENT_PLAN_TEMPLATE.md、RESEARCH_CONTRACT_TEMPLATE.md；设计文档 9.6"
language: "zh-CN"
---

# 03 阶段 2：从想法到实验设计

## 1. 定位

输入是 02 的幸存想法（用户假说与新候选，各带文献、查新与评审文档）。输出是立项确认所需的一组文档：每个想法一份**假说文档**（问题锚点、方法 proposal、claim map、实验块），一份**最小实验设定**（协议与 MetricSpec 初稿，04 冻结），**根节点任务请求**（框架、统计代码、基线家族），以及按里程碑排列的运行顺序与预算分配。用户确认后，这些文档直接驱动 04（根节点）和 05–06（节点实验）。

ARIS 把这一步拆成 `research-refine`（方法精炼）→ `experiment-plan`（claim 驱动的实验路线图）→ `experiment-bridge`（实现、代码审查、sanity、部署）→ `ablation-planner`（结果后的消融设计）。本项目借其**方法与文档结构**，但判定与门由数据库和 pi 评审执行，不靠提示词常量。

当前实现的差距：假说文档只要求"创建理由、计划的代码改动、实验计划"三项自由文本；`min_setup` 由 Leader 一次写成；没有 claim → 证据 → 实验块的对应关系，没有里程碑门，没有消融规划，worker 提交作业前没有独立代码审查和 sanity 约定。

## 2. 问题锚点（冻结）

借 ARIS research-refine Phase 0。立项时在 goal 文档写入五个字段，之后每份假说文档、每轮评审 brief **逐字复制**：

| 字段 | 内容 |
|---|---|
| 底线问题 | 必须解决的技术问题 |
| 必须解决的瓶颈 | 现有方法中不可接受的具体弱点 |
| 非目标 | 明确不做的事（来自 `plan.md` 的"非目标"节） |
| 约束 | 算力、数据、时间、工具、目标场景 |
| 成功条件 | 什么证据会让用户说"这确实解决了问题" |

评审或后续轮次建议改变所解决的问题时标为 **drift**，Leader 要么推回、要么经用户同意后改锚点并记一条用户指令。锚点不是 `go_margin`：前者定义问题，后者是阶段 1 的筛选门槛。

## 3. 从想法到方法 proposal

借 research-refine Step 1.2–1.4，但精简为本项目假说文档的必需章节。每个想法必须回答：

1. **技术缺口**：基线在哪一步失败；为什么扩上下文、加数据、提示工程、堆模块这类朴素修补不够；最小充分干预是什么；核心机制声明是什么；需要什么最小证据。
2. **路线比较**（两条都可行时）：极简路线（直接针对瓶颈的最小机制）与前沿原语路线（LLM / 扩散 / RL / 蒸馏等，只在故事更干净时采用）；二者都弱时重新框定问题，不默认合并成更大的系统。
3. **方法具体化**（白话，先说做什么再说主张什么）：一句话方法论题；一个主贡献、至多一个辅助贡献；复杂度预算（复用什么、新增什么、有意排除什么）；系统图与数据流；表示设计；训练配方；推理路径；前沿原语的确切角色与必要性；失败处理与诊断。
4. **可证伪预测与竞争解释**：在什么匹配条件下，哪项观测能区别于竞争解释（规则 §6）；列出廉价替代解释与对照。

"加一个模块""用一个 planner"不算具体。ARIS 的 7 维加权打分与"≥9 分 READY"不采用：分数作参考，准入由下面的确定性门和评审 stance 决定。

## 4. Claim map 与实验块

借 experiment-plan P1–P3 与 `EXPERIMENT_PLAN_TEMPLATE.md`。

**Claim map**（每个想法至多 `design.max_primary_claims` 条主 claim）：

| Claim | 为什么重要 | 最小说服性证据 | 要排除的反 claim | 关联实验块 |
|---|---|---|---|---|

"反 claim"即规则 §6 的竞争解释：主指标提升可能来自学习率、容量、训练量而非机制本身。

**实验块**（每个想法至多 `design.max_core_blocks` 个）默认五类，与 research-tree 的对象对应：

| 块 | 回答什么 | research-tree 对应 |
|---|---|---|
| 主锚定结果 | 方法在协议下是否优于基线 | 节点的筛选 → 复制 → 确认实验（06） |
| 新颖性隔离 | 收益是否来自声明的机制 | `kind=ablation` 实验或子节点 |
| 简化 / 删除检查 | 更简单的变体是否同样有效 | `rel_related: competes` 的对照节点 |
| 前沿必要性检查 | 前沿原语是否必要（不用时跳过，并说明） | 同上 |
| 失败分析 | 负向或不确定结果意味着什么 | `analysis` 任务，写 finding（08） |

每块九个字段：检验的 claim、存在理由、数据/切分/任务、比较系统、指标、设定（骨干、冻结与可训练部分、超参、预算、seed）、**成功判据**、**失败解释**、表/图目标；加优先级 `MUST / NICE` 和成本估计。成功判据必须在实验前写定，不能看到结果后改口径。

## 5. 从 claim map 到最小实验设定与 MetricSpec

设计文档 18.3 列出的"不能由插件硬编码的项目参数"在本阶段由 Leader 提出、用户确认：

- 主指标及方向、输入与规范单位、`minimum_practical_gain`（取代笼统的 `go_margin`）；
- 保护指标与 `allowed_regression`；主次关系预先声明，不能看到结果后交换；
- **评测类型标签**（借 ARIS experiment-integrity）：`real_gt` / `synthetic_proxy` / `self_supervised_proxy` / `simulation_only` / `human_eval`，写入 min_setup 并限制结论措辞——proxy 只能说"代理一致性"，自监督只能说相对提升；
- 基线家族（至多 `design.max_baseline_families`）及其合理调参机会、训练量、数据处理；
- seed 层级（预训练来源 / 后训练优化 / 初始化）与统一 seeds；
- 训练量与单次运行上限的关系（必须能在 `budget.per_run` 内跑完一个 seed）。

这些进入 04 的 MetricSpec 与协议，框架冻结后不可改。

## 6. 里程碑与运行顺序

借 experiment-plan P4，映射到本项目：

| 里程碑 | 目标 | research-tree 对应 | 决策门 |
|---|---|---|---|
| M0 sanity | 流水线能跑、loss 下降、指标能解析 | 根节点 worker 的 smoke；各节点首次提交前的最小规模 attempt，**不计 seed** | 退出码 0 不算过，需有效计数与指标文件（05 §2） |
| M1 基线 | 在协议上实际运行 SOTA 与其他基线 | 根节点 harness 任务；RLD 审核后冻结 | 基线数字可重算、落在合理范围 |
| M2 主结果 | 各想法的筛选 → 复制 → 确认 | 节点实验（06 三级流程） | Evaluation 的 outcome 与 eligibility |
| M3 决策 | 消融、简化检查、竞争解释 | ablation 实验、对照节点 | obligation 账本无 OPEN 项 |
| M4 收尾 | 补充 seed、复核 | 07 | GO / NOT GO 条件 |

每个里程碑写成本估计与 stop/go 门；`MUST` 与 `NICE` 分开列。预算按 `budget.search_limit / confirmation_limit / repair_limit` 分配（05）。

## 7. 消融规划

借 ARIS ablation-planner，但触发点与分工按本项目：

- **时机**：节点的主锚定结果为 `positive_signal` 或进入 `candidate_ready`（06）后；或复核指出缺少消融时。
- **出题者是 reviewer**：pi 评审（kind=`ablation_plan`，09）以审稿人视角设计：`name`、`what_it_tests`、`expected_if_component_matters`、`priority 1–5`、`coverage_assessment`、`unnecessary_ablations`、`suggested_order`、`estimated_compute`。Leader 不在 reviewer 看到之前预筛。
- **Leader 做工程判断**：预算是否够、哪些只改配置、哪些要改代码、哪些可并行；预算不够时提出裁剪并送回 reviewer 确认，不静默删除。
- **规则**：组件消融优先于超参扫描；配置级消融优先于改代码；不做与基线等价的 no-op 消融；每个消融必须有 `what_it_tests` 与预期；结果（包括"去掉也没影响"）写入 finding（08）。
- **登记**：消融作为 `kind=ablation` 实验或子节点，引用来源 review 文档。

## 8. 实现、代码审查与 sanity

借 experiment-bridge Phase 2–3。worker 实现节点改动后、提交任何作业前：

1. **代码审查**（`design.code_review`）：pi 评审（kind=`code_review`，09），只给代码路径与假说文档路径，重点查：GT 来源（不得用另一个模型的输出当标签）、自归一化分数、指标代码是否真被调用、seed 与配置是否与协议一致、方法是否确实实现了假说。`CRITICAL` 修复后重审，至多 2 轮；reviewer 不可用时记 `REVIEW_UNAVAILABLE`，由 Leader 决定是否放行并记录。
2. **sanity 先行**（`design.sanity_first`）：最小规模跑一次，不计 seed、不占筛选预算以外的额度；验收看有效计数、loss、指标文件、保存读回，不看退出码。
3. **失败预算**：同一失败至多 2 次补丁，再至多 2 次从假说文档重写；两次重写以同样方式失败 → 归咎计划或环境，上报 Leader，不再重试。与 `search.max_repairs_per_root_cause` 共用计数。
4. **超时**：实际用量达到预估的 `design.overrun_factor` 倍时写 attention，Leader 决定是否继续，不自动取消。
5. **跟踪**：实验的状态跟随数据库（`exec_status`、`valid`、Evaluation），不另维护 tracker 文件；结果一律存 JSON/CSV 以便重算。

## 9. 结果 → claim 的路由

借 result-to-claim。判定（06）产生后，对每条 claim：

| 结论 | 处理 |
|---|---|
| 支持 | 记 finding；按 §7 规划消融；进入复制/确认 |
| 部分支持 | 必须列出缺失证据与下一实验；补充后重判；同一 claim 多轮"部分支持" → 收窄 claim 或换想法，不无限补充 |
| 不支持 | 记 postmortem finding；按 06 的 `repairs / combines / tests_assumption` 关系决定是否派生，不保留原节点硬撑 |
| 无效 | 工程失败，不是科学反证；走 §8 的失败预算 |

数字先过 05 的确定性核验（引用的数字必须出现在所引文件中），再交 reviewer；"部分支持"不得四舍五入成"支持"；reviewer 不可用时不得由 Leader 代判。

## 10. 文档与接口

| 文档 | 必需章节 | 检查方式 |
|---|---|---|
| `goal` | 研究目标；**问题锚点**（五字段） | 章节存在 |
| `hypothesis` | 问题锚点（逐字）；方法步骤（白话）；技术缺口；可证伪预测与竞争解释；最接近工作与差异（引用 02 的 review 文档）；claim map；实验块；成本估计；停止条件；有意舍弃的复杂度 | 像 `TASK_SECTIONS` 一样由接口检查章节；引用的 literature 须 verified；`require_precheck` 下须有查新与评审回执 |
| `min_setup` | 协议；MetricSpec 列表；评测类型标签；基线家族；seed 层级；训练量 | schema 校验（04） |
| `experiment_design` | 单个实验块的九字段 + 优先级 + 成本 | 章节检查；实验创建时引用 |
| `task_request`（根节点） | 现有章节 + 基线家族与里程碑 M0/M1 | 现有检查 |
| `review`（kind=`ablation_plan` / `code_review`） | 09 的 schema | `pi_review.py` 校验 |

接口拟议：`create_hypothesis` 增加 `design_doc_id`（假说文档）与 claim 数量上限检查；`create_experiment` 要求引用一个 `experiment_design` 文档并带 `estimated_node_h`、`milestone`；`update_run(valid=true)` 对 sanity attempt 不计入 seed 计数。

## 11. 不采用的 ARIS 做法

- 7 维加权评分与 `SCORE_THRESHOLD=9` 作为准入；本项目用确定性门（锚点无 drift、claim 数量在限、每块有成功判据与失败解释、预算内）加评审 stance。
- `MAX_ROUNDS=5` 的同线程多轮精炼：研究精炼默认 `proposal_review_rounds: 1`，每轮新会话、只给新版本文档路径（ARIS 自己的 reviewer-independence 也要求如此）。
- `EXPERIMENT_TRACKER.md` 等文件状态：状态只存数据库。
- `AUTO_DEPLOY`、`MAX_PARALLEL_RUNS`：部署由站点技能与 `budget.max_parallel_workers` 管。

## 12. 防止长期准备而不实验

一个候选已经具有明确可证伪预测、匹配对照、合法资源和最小运行路径后，就应进行小实验。额外阅读、完整工具化和机制解释只有会改变本次实验有效性或选择时才作为前置。

文献研究节点可以是 analysis 任务，不强制每个有信息价值的问题都产生代码修改。方法实验仍需记录实际改动；复现或控制实验不应为满足“必须改代码”而提交空改动。

## 13. 测试

| 编号 | 场景 | 预期 |
|---|---|---|
| X01 | 假说文档缺少 claim map 或成功判据 | `create_hypothesis` 拒绝并指出缺哪节 |
| X02 | 问题锚点与 goal 文档不逐字一致 | 拒绝；提示 drift |
| X03 | claim 数超过 `max_primary_claims` | 拒绝 |
| X04 | `create_experiment` 未引用 `experiment_design` 或无 `estimated_node_h` | 拒绝 |
| X05 | sanity attempt 标 valid | 不计入 seed 数与筛选 seed 预算 |
| X06 | 同一失败第 3 次补丁 | 拒绝，要求重写或上报 |
| X07 | 两次重写同样失败 | 任务标阻塞并生成 attention，不再自动重试 |
| X08 | 实际用量 ≥ 2× 预估 | attention 项出现；作业不被自动取消 |
| X09 | 消融计划含与基线等价的 no-op | 校验拒绝该条 |
| X10 | reviewer 不可用时的代码审查 | 记 `REVIEW_UNAVAILABLE`；Leader 放行需决定记录 |
| X11 | 评测类型为 `synthetic_proxy` 的结果文档使用"优于 SOTA"措辞 | 文档校验提示超出结论上限 |
