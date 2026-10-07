---
title: "横切：数据模型、接口、错误码与迁移"
stage: "横切"
status: "proposed; not implemented"
prepared_on: "2026-10-06"
package: "plans/design（见 README.md）"
sources: "设计文档 §13.1–13.5、§14"
language: "zh-CN"
---

# 10 横切：数据模型、接口、错误码与迁移

## 1. 数据模型与接口草案

### 1.1 最小新增实体

优先只新增两个核心实体：`Evaluation` 和 `Reservation`。协议、MetricSpec、确认计划、复核和记忆使用现有 Document 的版本化结构化内容；查询确实需要时才额外索引。

当前 SQL 文件是 LatticeDB 的结构规格，不是可直接对后端执行的数据库迁移脚本。新增标签、字段和关系必须同步 Python 规格解析及写入校验。[S03]、[S05]

#### Evaluation

| 字段组 | 字段 |
|---|---|
| 身份 | `id`、`experiment_id`、`result_revision`、`created_at` |
| 输入 | `run_attempt_refs`、`pair_keys`、`input_revisions` |
| 方法与协议 | `method_code_ref`、`harness_ref`、`protocol_doc_id`、`metric_spec_doc_id` |
| 比较对象 | `baseline_experiment_id`、`parent_experiment_id` |
| 计算 | `metrics`、`comparisons`、`statistics_version`、`parser_version` |
| 结果 | `outcome`、`gate_passed`、`guardrails_passed`、`limitations` |
| 可核查性 | `verification_level`、`artifact_refs` |
| 历史关系 | `supersedes_evaluation_id`；撤回和失效通过追加决定记录 |

Evaluation 的科学内容不可就地覆盖。当前适用性可以由依赖查询计算并缓存；缓存必须可重建，不能成为唯一依据。

#### Reservation

| 字段组 | 字段 |
|---|---|
| 身份 | `id`、`project_id`、`submission_key` |
| 调度单位 | `run_attempt_refs`、`job_id`、`platform_profile` |
| 成本 | `resource_class`、`reserved_units`、`actual_units` |
| 状态 | `accounting_status`、`submission_phase`、`claim_generation` |
| 时间与证据 | `created_at`、`settled_at`、`accounting_ref` |

Reservation 的记账状态允许受约束更新；关键转换通过现有决定/事件记录保留，不要求额外完整事件溯源框架。

### 1.2 现有实体的最小调整

| 实体 | 拟议变更 |
|---|---|
| Project | 当前协议/MetricSpec 引用、总预算、确认预算、准入暂停原因 |
| Hypothesis | lifecycle 与 disposition；当前 Evaluation 指针作为可重建缓存 |
| Experiment | 固定 baseline/parent 引用、验证阶段、协议与配置快照、结果修订 |
| Run | manifest 引用、实际代码/协议绑定、结果修订、导入来源；保留 attempt 语义 |
| Document | 支持 protocol、metric_spec、finding、execution_lesson、review、confirmation_plan 等受约束类型 |
| Relation | 少量研究关系；Evaluation 与输入记录的依赖，Reservation 与作业尝试的关系 |

不同字段无需全部直接暴露为任意更新接口。预算、资格与有效性由专用操作维护。

### 1.3 本设计包其他阶段新增的实体与类型

| 新增 | 用途 | 来源 |
|---|---|---|
| `document.doc_type` 新增 `review`、`finding`、`execution_lesson`、`protocol`、`metric_spec`、`confirmation_plan` | 评审、经验、协议文档 | 02、08、04 |
| 角色 `reviewer`（`DOC_AUTHORS["review"] = ("reviewer",)`） | Leader 不能以 rld 登记 review 文档 | 09 |
| `obligation` 实体 | 未决问题账本 | 06 §6 |
| hypothesis 字段 `new_findings_streak`、`direction` | 停滞计数 | 06 §5 |
| experiment 字段 `estimated_node_h`、`milestone`、`design_doc_id`、`config_hash` | 成本预估、里程碑、去重 | 03、05 |
| run 字段 `is_sanity` | sanity attempt 不计 seed | 03 §8 |
| 候选与发现状态 `cache/discovery/<run>.json` | 发现流程的可恢复状态；不入数据库 | 02 |
| literature 前言 `verification` | verified / unverified | 08 |

### 1.4 公共接口草案

以下是拟议协议，不是当前可运行的 API：

```python
from typing import Any, Protocol

class ResearchControlVNext(Protocol):
    def import_run_result(
        self, run_id: str, attempt: int, manifest_path: str
    ) -> dict[str, Any]: ...

    def evaluate_experiment(
        self, experiment_id: str, protocol_id: str
    ) -> dict[str, Any]: ...

    def get_eligibility(
        self, hypothesis_id: str, protocol_id: str | None = None
    ) -> dict[str, Any]: ...

    def reserve_submission(
        self, submission_key: str, run_attempt_refs: list[str],
        resource_request: dict[str, Any]
    ) -> dict[str, Any]: ...

    def reconcile_submission(self, submission_key: str) -> dict[str, Any]: ...

    def settle_reservation(
        self, reservation_id: str, accounting_ref: str
    ) -> dict[str, Any]: ...

    def decide_disposition(
        self, hypothesis_id: str, disposition: str,
        reason: str, evidence_ids: list[str],
        reconsider_when: str | None = None
    ) -> dict[str, Any]: ...
```

`settle_reservation` 从 accounting_ref 导入真实用量，不让模型随意填写结算值。平台无法提供独立用量时明确标记来源和不确定性。

补充接口（拟议）：`review(kind, brief_doc_id, about, session=None)`（09）、`add_obligation / resolve_obligation / waive_obligation`（06）、`note_findings(node_id, new_findings, direction)`（06）、`context_pack(role, node_id)`（08）、`verify_literature(doc_id)`（08）。

### 1.5 接口与角色

| 接口 | 允许调用者 | 关键约束 |
|---|---|---|
| 导入本节点 run | owner worker / 运行适配器 / Leader | 输入路径和身份必须匹配 |
| 计算 Evaluation | owner worker / Leader | 不接收外部权威 verdict |
| 查询 eligibility / budget / memory | 当前允许的只读角色 | 不产生副作用，不自动重开项目 |
| 修改 disposition / 建立研究关系 | Leader | 有依据、在现有范围内 |
| 准入与提交 | 经共享内核约束的执行者 | 预算与唯一提交身份检查 |
| 扩预算 / 改权限 | 用户经现有配置流程 | agent 不得自动修改 |

新增读接口必须加入共享只读 allowlist，并更新 Claude 与 Codex 两端的对应路由。不得只改其中一端的工具定义。

### 1.6 稳定错误码

```text
STAT_MISMATCH                 汇总与输入不一致
METRIC_UNIT_MISMATCH          单位不匹配
PAIRING_MISMATCH              配对或协议字段不匹配
NONFINITE_METRIC              存在 NaN 或无穷值
RELATIVE_EFFECT_UNDEFINED     相对比较分母不合法
EVIDENCE_CHANGED             计算与写入间依据发生变化
EVIDENCE_STALE               证据不适用于当前判断
CONFIRMATION_REQUIRED         尚未完成声明的最终确认
BUDGET_EXCEEDED              无法为新提交完成预算预留
SUBMISSION_AMBIGUOUS         调度器是否接受未知，禁止自动重提
PROTOCOL_CHANGE_REQUIRED     当前协议不能表达或允许该操作
LEGACY_RESULT_UNVERIFIED      历史结果缺少新规则要求的依据
```

错误消息同时给出具体对象、当前状态和允许的下一步。拒绝一次提交不应诱导 agent 绕开共享接口直接运行。

补充错误码：

```text
REVIEW_UNAVAILABLE            评审后端不可用；不得自评
REVIEW_INVALID                评审输出不符合 schema
REVIEW_BUDGET                 评审费用达到 review_usd_alert；新评审暂停，由用户决定
SANITY_REQUIRED               方法或消融实验提交前缺同一代码的有效 sanity 运行
CODE_REVIEW_REQUIRED          提交前缺该提交的通过的代码审查（或 reviewer 不可用时 Leader 的放行决定）
FAILURE_BUDGET                同一根因的补丁或重写次数用尽；任务阻塞，待 Leader 决定
CLAIM_EXCEEDS_EVAL_TYPE       结果或报告的措辞超出评测类型的结论上限
REPEATED_DIRECTION            同方向已被排除且未以 repairs 指向原节点，或修复次数用尽；未经实验搁置的方向须用户指令
PRECHECK_REQUIRED             创建节点缺少查新或评审回执
LITERATURE_UNVERIFIED         引用的文献未通过存在性核验
OBLIGATION_OPEN               存在未关闭的复核发现
STALL_STRUCTURAL              子树连续无新发现，需换向
DESIGN_SECTION_MISSING        假说或实验设计文档缺必需章节
```

## 2. 迁移与兼容策略

### 2.1 固定基准，不假定执行时 main 仍相同

实施开始前读取实际仓库版本，并对照本设计的基准提交。若相关缺陷已被修复，保留测试意图，不重复改造。

基准 schema 标为版本 6。后续版本号应以实施时实际版本为准，本文不占用某个必然为 7 的发布号。[S05]

### 2.2 先双读，后切换权威来源

推荐顺序：

```text
A. 添加新实体、解析器与计算函数，不改变旧项目的展示。
B. 对可重算历史记录生成 Evaluation，进行 shadow comparison。
C. 修复不一致的测试夹具与真实数据异常，分别记录原因。
D. 新项目启用新规范；旧项目由显式迁移流程切换。
E. 兼容旧调用，但旧调用不能再绕过重算写入权威结果。
F. 完成一个兼容发布周期后，再移除冗余旧写路径。
```

shadow comparison 是比较计算结果，不自动重跑历史训练，不因为新规则加载而重新开展已结束研究。

### 2.3 旧字段映射

| 旧记录 | 初步迁移结果 | 额外要求 |
|---|---|---|
| pending | lifecycle=pending，disposition=active | 不凭空创建科学结论 |
| verifying | lifecycle=verifying，disposition=active | 对账实际 task/run 后确认 |
| expandable | lifecycle=assessed，disposition=active | 保留历史标签；重新核验当前 Evaluation |
| prunable | lifecycle=assessed 或 pending，disposition=retired | 根据是否实际实验决定 lifecycle，保留原理由 |
| beats_sota + 两项 pass | 历史通过记录 | 不自动获得新规则的独立确认资格 |
| close | inconclusive | 不因为达到旧 seed 上限升级为确定结论 |
| 无法获得原始评分材料 | legacy_unverified | 允许查看；不能伪装成产物级重算完成 |

旧 `no_gain` 不能统一解释成显著负向。应从原始差值和原判定规则重建；没有足够材料时保留历史陈述并标记核验限制。

### 2.4 指标规范迁移

旧主指标方向可读取已有字段，但百分比单位、次指标方向、实际收益阈值和相对比较定义不能仅凭名字猜测。优先读取已冻结的最小设定与统计代码；无法确认时生成待用户核对项，不让新协议悄悄改变科学问题。

只依赖旧 `metric_is_percent` 的记录先进入兼容规范；在确认输入尺度后再生成正式 MetricSpec。

### 2.5 数据迁移过程

停止新的研究写入，核对所有 Leader/worker/runtime 版本；保存现有 JSON 快照与文档索引。不能把正在使用中的数据库文件直接复制就当作一致备份。

通过 LatticeDB 支持的读取/导出与写入方式在独立位置迁移，检查 ID、边、文档引用、run attempt 和历史决定数量。不要对 LatticeDB 执行 SQL `ALTER TABLE`。

可让已经运行的训练作业继续完成，但其控制写入必须被暂停或导入明确的待处理队列。新内核就绪后按原 job_id 对账，不能因迁移重提训练。

切换前保证旧进程不会继续写旧数据库；原地文件替换并不会自动关闭其他进程已有句柄。版本不匹配的写入者必须拒绝启动或转为只读。

### 2.6 回滚

切换后、没有新写入或新提交前，可以恢复迁移前快照。已经产生新作业、结算或 Evaluation 后，不能简单用旧快照覆盖；应优先前向修复，或先导出新增事实并逐项对账。

回滚不撤销已经发生的外部作业和费用，不自动重开旧实验。迁移失败时保留旧系统可读和外部 job 身份，明确需要人工处理的部分。

### 2.7 必须同步修改的位置

除了核心函数，还需检查：

| 区域 | 同步工作 |
|---|---|
| `research_tree.sql`、规格解析 | 新字段、实体、枚举、引用关系 |
| `research_db.py` | ID 前缀、实体集合、关系端点、文档类型、权限、事务、读接口 |
| `project_config.py` 与配置 schema/template | 新协议和预算字段、用户变更流程 |
| 文档模板与工作规则 | 删除“必须改代码/必须得出结论”等不再适用约束 |
| Codex MCP/控制层、prompts | 新工具 schema、只读权限、恢复摘要 |
| Claude register/types/guards | 同样的接口与状态语义 |
| `build_site.py`、snapshot 与 demo | 新结果、不确定、失效、预留、待确认展示 |
| packaging tests | 发布包包含新模块和模板，两端共享核心不漂移 |

仅修一个函数而不修改展示和 agent 规则，会造成模型继续尝试旧流程，因此不能算完成。

补充同步位置：两端的 agent 类型（`assistant`、reviewer 工具入口 `research_review`）、Bash guard（拒绝直接调用 `pi` 与 `claude -p`）、`planningPrompt` / `codex_prompts.planning` 的发现与设计分支、规则 §1 的新角色、README 的站点技能义务。

<!-- 引用链接 -->

[S03]: https://github.com/UnbearableFate/research-tree/blob/48b3841d97275b2e9ad010d91d261acc9c7c4f5c/shared/research-tree/tools/research_db.py
[S05]: https://github.com/UnbearableFate/research-tree/blob/48b3841d97275b2e9ad010d91d261acc9c7c4f5c/shared/research-tree/schema/research_tree.sql
