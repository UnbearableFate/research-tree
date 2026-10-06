---
title: "阶段 4：节点实验、数字重算、证据版本与预算记账"
stage: "阶段 4"
status: "proposed; not implemented"
prepared_on: "2026-10-06"
package: "plans/design（见 README.md）"
sources: "设计文档 5.4–5.6、§6 D2、§11 D7；05 §1、§4.1（evidence_check）"
language: "zh-CN"
---

# 05 阶段 4：节点实验、数字重算、证据版本与预算记账

## 1. 执行层：插件与站点技能的分工

| 事项 | 站点技能（`platform.skills`，本站点为 `miyabi-pbs-cmd` / `miyabi-pbs-goal-wakeup`） | 插件（平台无关） |
|---|---|---|
| 提交、查询、取消作业 | 负责；知道 `qsub/qstat/qdel` 方言、队列与节点规则 | 不知道调度器；只接受 `create_run(job_id)` 与 `update_run(exec_status, 用量)` |
| 作业结束后的接续 | 负责唤醒 Leader 或 worker | 提供 `resume_package`；规则 §7 规定醒来后先按原 job_id 核对 |
| 用量 | 由技能从调度器读出并填入 | 只按 `nodes_used × walltime_used_s` 记账并检查上限 |

这个分工与 ARIS 把算力声明放在 `CLAUDE.md`、按提供商分技能的做法一致。插件侧仍可改进、且不依赖任何调度器的两点：

- **把"站点技能必须交给插件什么"写成约定。** 现在 `platform.experiment` 是自由文本，`job_id` 是任意字符串。建议在配置模板与 README 里写明站点技能的最小义务：提交后立即 `update_run(submitted, job_id)`；查询失败或超时保持 `unknown` 不重提（接口已拒绝从 unknown 重提）；结束后填实际用量；唤醒后只核对与导入，不作判定。这样第三方写自己的平台技能时有据可依。
- **设计文档 D7 只保留记账部分。** `Reservation`、`submission_key`、幂等结算、`held_unknown` 都是数据库内的约定，不碰调度器，可以实现；`scheduler.py`"最薄适配"和轮询脚本交给站点技能，不进插件。

因此本文件中 D7 的"调度器最薄适配"与"轮询脚本"不在插件内；保留的是数据库内的记账、预留、对账与恢复语义。

## 2. 统计重算与产物导入（D1）

### 2.1 基础计算

对合法配对后的主指标，令方法结果为 `x_i`，参照为 `y_i`，`s=1` 表示越大越好、`s=-1` 表示越小越好。

```text
d_i = s × (x_i - y_i)
delta_mean = mean(d_i)
delta_sd = sample_standard_deviation(d_i), n >= 2
```

`n=1` 时，`delta_sd` 为缺失值并附原因，不能填 0。方法自身 SD 与配对差值 SD 必须分别存储。

若预注册相对比较，则采用：

```text
relative_gain = s × (mean(x) - mean(y)) / abs(mean(y))
```

分母低于 `relative_min_denominator` 时返回不可进行相对比较，不丢弃该 seed、不静默夹紧分母、不临时改口径。必要时按预先定义的绝对比较备用规则报告，否则等待协议修订。

此定义不是“逐 seed 相对收益的平均”，报告必须说明。相对效应的置信区间不能把一个随机分母简单视为固定常数并声称精确覆盖；需要任务明确的成对重采样或其他已声明的方法。

### 2.2 运行材料与数字导入

拟议接口：

```python
import_run_result(run_id, attempt, manifest_path)
evaluate_experiment(experiment_id, protocol_id)
```

`manifest_path` 由受限路径规则解析。manifest 至少包含实验与 attempt 身份、实际代码版本、配置快照、数据版本、有效训练/评分计数、结束状态、原始指标文件及运行环境摘要。

冻结解析器必须检查身份一致、文件存在、数值有限、必需字段、计数合理、单位、退出状态和协议匹配。指标文件存在不等于实验有效；进程返回 0 也不能自动变成有效实验。

通用层负责基础聚合。涉及特殊统计量、按任务聚合或样本级评测时，由项目冻结评测器计算，通用层核验输入身份、版本和可重算基础量。不得强迫所有 ML 任务采用同一个平均方式。

### 2.3 不再让外部接口填写权威结论

`record_verdict()` 在兼容期只做两件事：调用新计算路径；将旧调用提供的值作为预期值进行交叉核验。有不一致返回 `STAT_MISMATCH`，不写入权威 Evaluation。

浮点容差只能用于重算结果的数值一致性检查。GO 门槛的 `>` 或 `>=` 应由协议固定，不能用较宽的数值容差把不达标结果改成达标。

### 2.4 文档数字与文件核对

借 ARIS `tools/evidence_check.py`（212 行，12 个测试）：每条声明记为 `(claim_id, value, source_path)`，核验该数值是否以精确十进制形式出现在所引文件中，状态为 verified / value_not_found / path_missing / unparseable；找不到即拒绝，不给模型兜底。接入点：`record_verdict`（或新的 `evaluate_experiment`）前、`set_document_current` 对 `experiment_result` 与 `report` 类型前。它与记录级重算互补：重算管汇总与 run 一致，核对管文档与文件一致。

## 3. 证据版本与 GO 资格失效（D2）

### 3.1 把“通过”绑定到具体证据

新增不可就地改写科学内容的 `Evaluation` 记录。一次统计计算绑定：

```text
evaluation_id
experiment_id + run/attempt 引用
method_code_ref
harness_ref
protocol_id
metric_spec_id
baseline_experiment_id
parent_experiment_id（可选）
数据/模型/切分的身份与版本
实际参与比较的 pair_keys
解析器与统计实现版本
```

这里使用已有 Git 版本和文档 ID 即可，不要求新建密码学签名、全文件哈希链或远程证明系统。

### 3.2 在实验创建时锁定参照

当前比较会查找父节点最新已判定实验。拟议设计改为：创建实验时固定 `parent_experiment_id` 和 `baseline_experiment_id`，不因父节点后续补实验而自动改换参照。[S11]

同一方法对新 baseline 重评分时，新增一条 Evaluation；不改写此前“当时相对旧 baseline 的结果”。因此历史记录与当前候选可以同时正确存在。

### 3.3 资格查询以有效证据为准

拟议接口：

```python
get_eligibility(hypothesis_id, protocol_id=None)
```

返回至少包括：

```json
{
  "hypothesis_id": "H-0003",
  "eligible": false,
  "basis_evaluation_id": "EV-0012",
  "evidence_state": "stale",
  "reasons": ["HARNESS_CHANGED", "BASELINE_CHANGED"]
}
```

`go_candidates()` 必须调用同一 eligibility 逻辑；项目转 GO 也必须在写事务中重新检查，不能信任之前的 UI 快照。

GO 需要有效、当前适用的 Evaluation，预定 gate 通过，保护指标满足，必要复核绑定到该方法和评估依据，且无撤回/失效阻断。单纯将 `experiment_status` 改成 `beats_sota` 无效。

### 3.4 失效规则

| 变化 | 默认处理 |
|---|---|
| 评测代码、指标单位或统计协议变更 | 旧 Evaluation 不再支持当前 GO；必要时重评分 |
| baseline 改变 | 重新比较；不得继续沿用旧的相对领先结论 |
| 方法代码或方法性配置改变 | 新实验/新 Evaluation；代码相关复核需要重新绑定 |
| 某个 run 被证明无效 | 引用它的 Evaluation 失效；原记录保留 |
| 只是新增不同分支的实验 | 不使无关 Evaluation 失效 |
| 文档排版或 UI 样式改变 | 不使科学证据失效 |
| 新文献出现 | 根据具体覆盖关系更新新颖性复核，不自动重跑训练 |
| 补充 seed | 新的结果修订，旧统计快照保留 |

不必在每次版本变化时全项目重跑。协议兼容规则可以允许复用未受影响的评分材料，但必须明确哪些字段没有改变。

### 3.5 避免“查询时有效、提交时失效”

评测与读取产物可以在锁外进行；写入 Evaluation 时，在一个短事务中再次核对协议、输入修订及参照版本。任一依据变化，返回 `EVIDENCE_CHANGED`，重新计算或重新确认依据。

不要用每次全局 `data_version` 改变就否定计算，否则其他 worker 的无关更新会造成无意义重试。优先核对涉及的实体修订号和版本元组。

### 3.6 历史 GO 与当前有效性

已经作出的 GO 决定是历史事实，不应静默改写为“从未通过”。若后来发现证据有问题，追加撤回或失效说明，并将当前资格标成失效。

已结束项目不会因为资格失效自动重新启动。重新开展实验仍需新的用户指令和范围记录。

## 4. 预算预留、作业身份与恢复（D7，记账部分）

### 4.1 总预算与提醒阈值分开

保留现有提醒机制，但新增明确的 `total_budget`。若未配置硬预算，只能声称提醒，不声称严格成本封顶。

以一种已定义计算资源为例：

```text
available = authorized_total - settled_usage - outstanding_reservations
```

计算成本与 LLM 成本分开记账。node-hours 不自动等于 GPU-hours；不同硬件的 node-hours 也不一定可比。初版按 resource class 分开记录，需要统一折算时由项目预先定义权重。

### 4.2 用整数单位记账

数据库内部优先使用整数 node-seconds、GPU-seconds 和 token 数；显示时转换为小时。预留值向上取整，避免浮点边界下小额超额准入。

对可由调度器强制 walltime 的作业，预留按申请资源与上限计算，而不是只按预计平均训练时间。

总成本保证有条件：共享内核能阻止自己管理的超额提交，但不能阻止用户在外部另起作业；调度器未强制时长上限、LLM 计费能力不完整时，也不能宣称绝对硬封顶。

### 4.3 Reservation 模型

一条 Reservation 对应一个实际可计费的调度分配。若一个调度 job 一次跑多个 seed，不得为每个 seed 再重复预留同一整块节点时长；job array 则按明确的计费单元预留。

```text
reservation_id
project_id
submission_key
run_attempt_refs
resource_class
reserved_units
actual_units
accounting_status: reserved / held_unknown / settled / released
job_id
created_at / settled_at
```

`submission_key` 在项目内唯一。节点实验重试增加 attempt，不复用旧 attempt 的提交身份。

### 4.4 准入必须是单一短事务

在现有写事务内完成：检查授权与暂停状态、检查总预算和并发资源、检查提交身份是否已存在、建立 Reservation、登记提交意图。不能先查剩余预算、释放锁，再另起事务预留。

外部调度器调用在事务之外执行。数据库锁不能覆盖几十秒或更久的网络请求。

### 4.5 提交协议

```text
1. reserve：事务内建立唯一提交意图与资源预留。
2. claim：一个执行者领取该意图；其他执行者不能并发提交它。
3. submit：向调度器提交，携带可查询的 submission_key。
4. attach：保存返回的 job_id。
5. reconcile：查询真实状态并接续。
6. settle：终态和用量确认后结算。
```

提交超时不能被视为“调度器肯定没收到”。记录为 held_unknown，保留预占，通过 submission_key、已知 job_id 或平台可用历史查询对账。

没有可用的幂等提交或查询身份时，系统无法保证外部作业 exactly-once。正确做法是停止自动重提并报告需核对，而不是用重试循环掩盖不确定性。

提交协议的第 3、5 步（向调度器提交、查询真实状态）由站点技能执行；插件负责第 1、2、4、6 步，并要求站点技能按 01 §4 的义务回填。

### 4.6 崩溃恢复

| 崩溃位置 | 恢复动作 |
|---|---|
| 预留前 | 没有新作业身份；可以正常重新尝试 |
| 预留后、提交调用前 | 检查领取状态；确认未进入提交阶段后可继续同一意图 |
| 调度器已接收、job_id 未写回 | 查询原 submission_key，不生成新作业 |
| job_id 已写回、agent 会话丢失 | 使用原 job_id 接续；不重跑实验 |
| 作业终态、结算未写回 | 幂等结算一次 |
| 取消请求超时 | 保持 unknown 与预占，查询实际状态 |
| 实际用量暂不可获得 | 保留待结算状态或保守预留，不记为零成本 |

时间过去或 lease 过期不证明远端作业不存在。只有确认尚未提交、确认取消/结束并完成结算，或用户明确处理后才能释放对应预留。

### 4.7 实际超额也必须如实记账

实际用量超过申请上限或剩余预算时，仍保存真实用量并标记违规/异常，停止后续准入、向用户说明。

不能因为“超出 cap”而拒绝保存观测，导致预算账本丢失真实支出。授权约束用于准入；观测记录用于如实反映发生过的事，两者不能混淆。

### 4.8 保护确认预算

在总预算内为最终确认保留额度。该额度是总预算的一部分，不是总预算之外的追加授权。分项上限之和不得超过总授权。

搜索已经耗尽确认额度时，不得降低 GO 标准来收尾；应返回 candidate_ready 或 paused，并说明剩余确认需求。

### 4.9 事件驱动与低成本监控

复用已有 supervisor、事件日志、worker 身份和队列，不建立第二套 durable runtime。[S07]、[S08]

平台适配器提供 `submit / query / cancel / accounting` 的最薄封装；常规轮询由脚本完成，使用合理退避。只有新结果、故障、重要预算变化或真正的研究选择才唤醒 Leader。

当多个独立作业并行时，某个结果已足以改变下一步就应处理，不必总等预计最晚的作业。没有可执行独立工作时，Leader 休眠，项目记录继续存在。

不承诺宿主未实际支持的唤醒方式；机制不可用时，返回明确恢复命令或待人工接续状态，不能声称已安排自动接续。

补充：唤醒与监视由站点技能提供；插件不内置心跳守护进程。插件可做的只是依据数据库时间戳生成 attention 项（如长期无更新的 running run），供 Leader 唤醒后核对。

### 4.10 节点会话与外部作业身份分离

worker 会话重启不增加科研 run attempt。只有对应实验尝试确认无效/失败且决定重新运行时才增加 attempt。

同一逻辑 worker 可绑定新会话，但先确认旧会话不再写入；必要时用会话 generation 防止旧会话迟到写入。不要仅根据某台机器上的 PID 判断跨节点进程是否存活。

## 5. 成本预估与超时

`create_experiment` 增加必填 `estimated_node_h`（03 §8）；预留按申请资源与 walltime 上限计算；实际用量达到预估的 `design.overrun_factor` 倍写 attention。实验创建按 (code_ref, 配置快照哈希, seed) 去重，返回已有实验而不是新建（借 ARIS dse-loop "相同配置永不重跑"）。

<!-- 引用链接 -->

[S07]: https://github.com/UnbearableFate/research-tree/blob/48b3841d97275b2e9ad010d91d261acc9c7c4f5c/codex-plugin/research-tree/tools/codex_runtime.py
[S08]: https://github.com/UnbearableFate/research-tree/blob/48b3841d97275b2e9ad010d91d261acc9c7c4f5c/codex-plugin/research-tree/tools/codex_agent.py
[S11]: https://github.com/UnbearableFate/research-tree/blob/48b3841d97275b2e9ad010d91d261acc9c7c4f5c/shared/research-tree/tools/research_db.py#L1030-L1170
