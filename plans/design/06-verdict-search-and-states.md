---
title: "阶段 5：判定、不确定性、状态与搜索"
stage: "阶段 5"
status: "proposed; not implemented"
prepared_on: "2026-10-06"
package: "plans/design（见 README.md）"
sources: "设计文档 §7 D3、§8 D4、§9 D5（除 9.6）；对照文档 §4.1–4.2（iteration_log、forensics_gate、acceptance-gate、result-to-claim）"
language: "zh-CN"
---

# 06 阶段 5：判定、不确定性、状态与搜索

## 1. Type-A / Type-B 门分类

借 ARIS `acceptance-gate.md`："loop 可以 DRIVE，不能 ACQUIT"。对本阶段每个决定标注：

| 门 | 类型 | 谁判 |
|---|---|---|
| run 有效（退出码、有效计数、指标文件存在、数值有限） | A | `research_db` |
| 配对与 `passes_gate`、`delta_mean`、保护指标 | A | 冻结统计代码 + 共享内核重算 |
| 预算计数、seed 数、重试次数、停滞计数 | A | `research_db` |
| 声明是否成立、机制是否解释结果、是否值得继续投入 | B | reviewer 文档（09）或 Leader 有据决定，不得由 worker 自评 |
| 新颖性、方法—代码一致性 | B | 07 的定向复核 |

定时唤醒与监视器只能推进 A 类事实（查状态、导入结果、触发 Leader），不能重跑 B 类判定、不能自动 accept。

## 2. 不确定性、筛选与独立确认（D3）

### 2.1 预算不足不创造确定性

移除“达到 `gate_seeds` 后必须给出确定结论”的硬约束。`max_seeds` 只代表当前协议允许投入的最大重复数，不代表统计不确定性必然消失。[S11]

实验的拟议结论为：

| `outcome` | 含义 |
|---|---|
| `positive_signal` | 在既定尺度与协议下观察到值得后续验证的收益 |
| `negative_signal` | 在已声明规则下存在不利信号；只在对应条件范围解释 |
| `inconclusive` | 当前实验不能支持明确投入/科学结论，或统计口径存在待解决限制 |
| `invalid` | 未通过工程或协议有效性检查，不是科学反证 |

保留原始效应量，即使结论是不确定也可用于调度。`negative_signal` 不等于“该研究方向在所有条件下被证伪”。

### 2.2 三级流程

```text
screen：廉价探索
   ↓
replicate：仅对有信息价值的候选追加重复或诊断
   ↓
confirm：冻结候选后，使用未参与候选选择的重复/评测材料
```

screen 可从 1 个 seed 开始，目的包括尽快暴露工程问题与发现大幅效应。一个轻微负向的 seed 不自动导致科学淘汰。

replicate 不只服务当前赢家。高不确定性但可能改变决策的节点、竞争解释对照、机制组合的关键前提都可以进入下一轮。

confirm 的数量、切分与准入成本在开始选择前声明。默认只确认少量最终候选，避免把 Stage 1 变为全面实验矩阵。

### 2.3 seed 与验证保真度是两种维度

更多 seed 估计重复训练波动；更大模型、更长训练、不同数据域则检查跨设定适用性。两者不能互相替代。

同一保真度上的结果进入同一比较组。改变训练量、模型规模或数据子集时，建立新协议/实验，而不是把差异混入同一个均值。

可借鉴 Hyperband 的分层资源分配思想，但不声称它对开放式假说搜索直接提供保证。尤其要避免小规模代理任务的排名反转造成过早剪枝。[R10]

### 2.4 默认 gate 不冒充统计显著

建议区分两个配置档：

| 档位 | 用途 | 结果标签 |
|---|---|---|
| `screening` | 极低成本探索、兼容旧行为的观察 | `candidate_ready`，不是独立确认完成 |
| `stage1_confirmed` | 少数候选独立重复后形成投入判断 | `go`，明确标注 Stage 1 与推断限制 |

`stage1_confirmed` 默认 gate 可以采用“预设数量的独立确认配对齐备、确认均值超过最小实际收益、保护指标通过、复核通过”。这仍是投入筛选规则，不自动具有某个显著性水平。

需要显著性声明的项目必须另外声明推断方法及假设。例如固定确认样本数下的成对分析；若反复查看结果并自适应停止，应使用适用的顺序推断方法或明确放弃固定样本置信区间的覆盖声明。confidence sequence 是可选后续方向，不是 P0/P1 的默认实现要求。[R11]

### 2.5 搜索集与确认集

搜索中可反复使用探索 seeds/validation。候选代码和配置冻结后，再使用未用于选择的确认 seeds，并在适当场景加入未参与调参的确认数据切分。

只换 seed 只能检查训练随机性，对已反复使用的数据切分的过拟合无能为力。反复挑选有限样本上的最佳结果会产生选择偏差，因此需要如实记录探索次数和确认材料的使用史。[R09]

确认结果一旦被用于修改候选，该结果就成为探索信息。新候选不能继续把同一份反馈称为未见确认。对同一个冻结候选重算数字是完整性核验，不是额外独立样本。

设置每个研究周期的确认候选数量与成本上限。多候选重复确认、多个指标和多轮研究周期不自动享有单次检验的错误率；正式错误率控制需要预注册额外规则。

## 3. 研究状态与投入决策分离（D4）

### 3.1 三个独立问题

```text
执行生命周期：这个节点的工作进行到哪里？
实验证据：目前的结果支持什么？
投入处置：是否还要继续为它投入资源？
```

拟议模型：

| 维度 | 取值 | 权威来源 |
|---|---|---|
| `lifecycle` | `pending`、`verifying`、`assessed` | 任务/实验与受约束的状态转换 |
| `outcome` | 第 7 节定义；未实验时为 null | 当前适用 Evaluation |
| `disposition` | `active`、`paused`、`retired` | Leader 的有据决定或用户指令 |

不把这三个字段各自由 agent 任意填写。`outcome` 来自 Evaluation；`disposition` 必须记录理由、依据与复议条件。

### 3.2 必须允许的组合

| 情形 | 合理记录 |
|---|---|
| 工程失败但值得修复 | `verifying + invalid + active` |
| 证据不足、暂无预算 | `assessed + inconclusive + paused` |
| 有小幅收益、但预计价值不足 | `assessed + positive_signal + retired` |
| 负向结果揭示了可修复前提 | 原节点保留负向证据；新节点记录修复关系 |
| 用户在实验前决定放弃 | `pending + null + retired`，不是科学反证 |
| 暂停新提交但已有作业在运行 | disposition 可为 paused；run 继续保持真实状态 |

节点因新实验从 `assessed` 返回 `verifying` 时，历史 Evaluation 不消失。`retired` 只表示当前不再投入，不表示删掉节点、分支历史或证据。

### 3.3 GO、NOT GO 与暂停

GO 通过第 6、7、12 节的资格检查形成；Stage 2 仍需要用户决定。

NOT GO 表示“在当前问题、范围和证据下，不建议继续投入”，不是“所有可能假说均已被科学证伪”。Leader 应逐项交代未探索、工程失败、不确定、重复方向、明确反证及投入价值判断。

不再为了满足“所有节点必须科学失败”而制造假阴性；但也不能把预算耗尽直接记为 NOT GO。预算不足默认停止新增准入、进入等待用户决定，并让模型休眠；不必为保持项目 active 而持续生成低价值工作。

当前 `not_go` 要求所有节点 prunable 且清理完成的规则需要与这里同步修订；只改提示词不够。[S12]

### 3.4 清理与研究判断解耦

可以先作出有充分证据的投入判断，另行记录 `cleanup_pending`。项目是否完成全部收尾由执行清点决定，不能靠删除是否成功改变科学结论。

这不授权跳过清理。清理、取消作业、关闭 worker、停止监视器各有执行结果；未知状态保持未知，不能把一项成功替代全部完成。

## 4. 有限非贪心搜索与研究关系（D5）

### 4.1 代码继承与研究依据不是一回事

保留单一代码基准，避免复杂的自动多分支合并。一个新节点必须指向明确的 `base_commit`；同时允许它在科学意义上参考多个旧节点。

已有 `rel_related` 可扩展少量关系：

| 关系 | 含义 | 不代表什么 |
|---|---|---|
| `combines` | 组合两个方向的关键机制 | 不代表代码可以无冲突自动合并 |
| `repairs` | 修正此前结果揭示的具体缺陷 | 不抹去原节点的失败证据 |
| `tests_assumption` | 检验另一个节点的必要前提 | 不要求它自身成为性能赢家 |
| `competes` | 区分竞争解释 | 不预先判定任一解释正确 |
| `shares_control` | 共享对照设计或结果 | 不把共享结果当多次独立实验 |

现有属性图和关系管理可承载这些信息，不需要迁移数据库。[S03]、[S05]

### 4.2 修改扩展许可

普通渐进改进可以继续从已有正向节点扩展，但 `repairs`、`combines`、`tests_assumption` 允许从负向或不确定的历史依据提出新节点。

创建时必须给出：具体待检验差异、预期能排除的解释、已有证据、最小实验、所需成本与停止条件。不允许仅改名字反复提出已被同一对照排除的方案。

新节点的代码父版本和科学父关系可以不同。旧节点已 retired 并不自动禁止引用其历史代码或证据；是否执行新节点由当前项目范围、授权和预算决定。

### 4.3 每批实验的选择对象

Leader 每个决策批次比较三类行动：

1. 推进已有正向方向：扩大重复、微调关键机制或升级验证。
2. 减少关键不确定性：竞争解释、必要性对照、复现与诊断。
3. 探索不同机制：与当前赢家不同的路线或有明确依据的组合。

每项行动写一段简短的 `selection_rationale`，回答“为什么现在做，它的结果如何改变下一步”。不要求为所有候选填长表。

### 4.4 首版不采用虚假精确的效用分数

可以用高/中/低表示潜在收益、判别价值、成本与重复程度；它们是排序线索，不是校准过的概率。不要让 LLM 随意填入 `P(success)=0.83` 再把它当作贝叶斯后验。

首版建议先做确定性过滤：越权、无预算、重复、未解决依赖、没有可区分预测的候选不准入；再由 Leader 对剩余候选做简短排序。

研究次数积累后才评估是否需要 bandit、Bayesian optimization 或 MCTS。引入前必须与更简单排序对照，不把算法复杂度当成效果证据。

### 4.5 有限探索预算

可在预先批准的总预算内，为不同机制保留一小部分探索额度。示例起点为 10%–20%，属于待验证的策略超参数，不是文献已经证明的最优比例。

没有值得验证的新机制时可以不花这笔钱。不能为了“多样性配额”创建无意义分支。

给修复循环单独设上限：同一根因有限重试；同一假说的等价修改不得无限重开。超过上限后，明确选择重新设计、暂停或向用户说明阻碍。

### 4.6 关系边的合并

9.1 的 `combines / repairs / tests_assumption / competes / shares_control` 与 ARIS research-wiki 的类型化边合并，补 `supports`、`invalidates`（Evaluation → hypothesis）、`tested_by`（hypothesis → experiment）。它们都落在现有 `rel_related` / `rel_describes` 属性图上，不迁移数据库。

## 5. 停滞计数与强制换向

借 ARIS `tools/iteration_log.py`（143 行）：每个决策批次 Leader 用 `note_findings(node_id, new_findings, doc_id)` 为相关子树填本批新增的 finding 数；`doc_id` 是本批次的现行决定文档。同节点/同文档的重复调用不追加账本、不累计或复位，返回当前停滞状态；改变计数须提交新的决定文档。连续 `search.stall_structural_at`（默认 2）个不同批次为 0 → 该子树进入 `structural`：拒绝再创建与已记录 `direction` 相同的子节点，必须换机制、换对照或暂停；连续 `search.stall_human_at`（默认 4）批 → `post_to_ui` 上报用户。计数是纯确定性的，不需要模型判断质量；它与 9.5 的修复上限并列。旧匿名批次账本保留，新调用不再接受缺失批次文档。

## 6. 未决问题账本

借 ARIS `tools/forensics_gate.py` 的账本部分：复核发现、协议不匹配、`STAT_MISMATCH`、代码审查的 CRITICAL 项都写成一条 obligation：

```text
obligation_id, about(节点/实验/Evaluation), source(review 文档或错误码), fingerprint(来源+模式+证据片段),
severity, status: OPEN / RESOLVED / WAIVED, resolved_by(类型化修复 + 证据文件哈希 + 核验者), waived_by(用户指令)
```

规则：只追加；严重度只升不降；已 RESOLVED 的指纹再次出现则重开；从后续报告中消失不等于解决（标 `UNRESOLVED_DISAPPEARANCE`，仍 OPEN）；关闭只能通过 `resolve`（带证据）或用户 `waive`。节点进入 `candidate_ready`、项目 GO 之前要求相关 obligation 无 OPEN 项。

## 7. 结果 → claim 路由

03 §9 定义了支持 / 部分支持 / 不支持 / 无效四种处理；本阶段用 `outcome`（7.1）承载：`positive_signal` ↔ 支持，`inconclusive` ↔ 部分支持或证据不足，`negative_signal` ↔ 不支持，`invalid` ↔ 工程失败。"部分支持"必须附缺失证据与下一实验；同一 claim 多轮 inconclusive 后由 Leader 决定收窄 claim、换向或暂停，并写 `selection_rationale`。

<!-- 引用链接 -->

[R09]: https://jmlr.org/papers/v11/cawley10a.html
[R10]: https://arxiv.org/abs/1603.06560
[R11]: https://arxiv.org/abs/1810.08240
[S03]: https://github.com/UnbearableFate/research-tree/blob/48b3841d97275b2e9ad010d91d261acc9c7c4f5c/shared/research-tree/tools/research_db.py
[S05]: https://github.com/UnbearableFate/research-tree/blob/48b3841d97275b2e9ad010d91d261acc9c7c4f5c/shared/research-tree/schema/research_tree.sql
[S11]: https://github.com/UnbearableFate/research-tree/blob/48b3841d97275b2e9ad010d91d261acc9c7c4f5c/shared/research-tree/tools/research_db.py#L1030-L1170
[S12]: https://github.com/UnbearableFate/research-tree/blob/48b3841d97275b2e9ad010d91d261acc9c7c4f5c/shared/research-tree/tools/research_db.py#L780-L858
