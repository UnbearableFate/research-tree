---
title: "阶段 0：准备、初始化与配置"
stage: "阶段 0"
status: "proposed; not implemented"
prepared_on: "2026-10-06"
package: "plans/design（见 README.md）"
sources: "设计文档 §13.6；05 §1；discovery 文档 §6；ARIS templates/RESEARCH_BRIEF_TEMPLATE.md"
language: "zh-CN"
---

# 01 阶段 0：准备、初始化与配置

## 1. 现状

`prepare` 用 uv 建环境并生成 `plan.md` 与 `research-tree.yaml`；`init` 建立 `research/<项目ID>/`、数据库、`agents.json`，把 `plan.md` 逐字登记为用户指令 `UI-0001`，写 `.research-tree.json`（phase=planning）；`config apply` 把用户修改登记为 `config.vN.yaml` 并同步项目记录；`gate_seeds`、`go_margin` 在第一个实验登记后锁定。配置键见 `shared/research-tree/schema/config.template.yaml`：`platform.{dev,experiment,skills}`、`budget.{per_run,screen_node_h,max_parallel_workers,alert_node_h}`、`stage1.{gate_seeds,go_margin,min_related_work}`、`models.{ui,worker}`。

## 2. plan.md 模板调整

ARIS 的 `RESEARCH_BRIEF.md` 是 `/idea-discovery` 的文档式输入模板：问题陈述、背景（领域、读过的论文、已尝试、无效的尝试）、约束（算力、时限、目标会议）、想要什么（新方向 / 改进现有方法 / 诊断研究）、领域直觉、非目标、已有结果，建议 1–2 页。它对应本项目的 `plan.md`。拟议改动：

| 节 | 变化 |
|---|---|
| 初始假说 | 可填用户假说，也可写"由发现流程产生。"；两种情况都进入 02 的发现流程（用户假说作为种子） |
| 新增"已尝试与无效的方法" | 作为 02 候选生成的禁止列表与 08 经验的初始条目 |
| 新增"非目标" | 写入问题锚点（03 §1）的 Non-goals |
| 参考资料 | 承担 ARIS `REF_PAPER` 的作用：给出论文或仓库，02 的文献阶段先摘要它 |
| 其余节 | 不变；"由 RLD 决定。"的节由 Leader 在立项计划中提出 |

## 3. 完整配置草案（拟议）

下面把设计文档 13.6、discovery §6 与 03 新增的键合并为一份；阈值均为演示值，实施时由具体研究计划确定，且不能由 agent 在看到结果后调低（设计文档 18.3）。新配置用 schema 校验，未知字段报错。

```yaml
version: 2

platform:
  dev: |
    在当前机器上运行。
  experiment: |
    在当前机器上运行。
  skills: []                 # 站点技能，例如 miyabi-pbs-cmd、miyabi-pbs-goal-wakeup；义务见 §4

discovery:                   # 02
  mode: full                 # off | precheck（只处理用户假说）| full（用户假说为种子，并发现更多候选）
  require_precheck: true     # create_hypothesis 要求 novelty_precheck + critical_review 回执
  lenses: [method-transfer, contradiction, untested-assumption, scaling-regime, diagnostic]
  seed_lenses: [variant, combination, competing, repair]
  max_candidates: 12
  triage_top_n: 4
  max_initial_nodes: 3
  pi_generator: false

design:                      # 03
  max_primary_claims: 2
  max_core_blocks: 5
  max_baseline_families: 3
  proposal_review_rounds: 1  # 0 关闭
  code_review: true          # worker 提交作业前的跨模型代码评审（09）
  sanity_first: true         # 每个节点先跑最小规模 smoke，不计 seed
  overrun_factor: 2.0        # 实际用量超过预估的倍数，达到即写 attention

evidence_policy:             # 04 / 05
  profile: stage1_confirmed  # screening | stage1_confirmed
  require_artifact_import: true
  preserve_raw_metrics: true

metric_specs:                # 04
  - name: accuracy
    direction: higher
    input_unit: fraction
    canonical_unit: percentage_point
    effect_mode: absolute
    minimum_practical_gain: 0.2
    aggregation: paired_run_mean
    valid_range: [0.0, 1.0]
  - name: train_time_s
    direction: lower
    input_unit: seconds
    canonical_unit: seconds
    effect_mode: relative_to_reference_mean
    relative_min_denominator: 1.0
    allowed_regression: 0.10
    aggregation: paired_run_mean

verification:                # 06
  screening_seeds: [42]
  replication_seeds: [43, 44]
  confirmation_seeds: [1042, 1043, 1044]
  min_confirmation_pairs: 3
  max_confirmation_candidates: 2
  allow_inconclusive_at_limit: true
  inference_mode: descriptive

budget:                      # 05
  per_run: {nodes: 8, walltime: 1h}
  compute_unit: node_seconds
  total_limit: 360000
  search_limit: 252000
  confirmation_limit: 72000
  repair_limit: 36000
  reserve_from_scheduler_limits: true
  unknown_submission_policy: hold_and_reconcile
  max_parallel_workers: null
  alert_node_h: null
  review_usd_alert: null     # 09：累计评审费用提醒阈值

search:                      # 06
  exploration_fraction: 0.15
  max_repairs_per_root_cause: 2
  require_selection_rationale: true
  allow_repair_from_retired_evidence: true
  stall_structural_at: 2     # 连续无新发现批次 → 强制换向
  stall_human_at: 4          # → 上报用户

memory:                      # 08
  enabled: true
  cross_project: false
  max_items_per_task: 5
  include_counterevidence: true

review:                      # 07
  trigger: candidate_ready
  permanent_reviewer: false
  require_method_code_alignment: true

models:
  ui: {model: inherit, effort: null}
  worker: {model: inherit, effort: null}
  lens_assistant: {model: inherit, effort: null}
  reviewer:                  # 09；基座按 provider 自动选择，不可覆盖
    model: openai/gpt-6-astra   # provider/model；anthropic/* → Claude Code CLI，其余 → pi（须在 pi --list-models 中）
    thinking: high
    require_cross_family: true
    timeout_s: 900
```

解释：`allowed_regression: 0.10` 表示该相对成本指标允许最多 10% 退化；总预算 360000 node-seconds 为 100 node-hours，三个分项上限之和恰好等于总量。`gate_seeds`、`go_margin` 的语义由 `metric_specs.minimum_practical_gain` 与 `verification` 接管（迁移见 10）。

`prepare` 不检查评审后端；`init` 在 `discovery.mode != off` 或 `review.trigger` 需要时按 reviewer 的 provider 检查对应基座（pi：`pi auth check --provider <p>`；Claude 系模型：`claude auth status` 的 `loggedIn`），不可用则在立项简报中写明并由用户决定。

## 4. 站点技能对插件的最小义务

执行层有意不在插件内实现（原因与分工见 05 §1）。配置模板与 README 应写明站点技能必须做到：

1. 提交后立即 `update_run(submitted, job_id)`；`job_id` 可被调度器再次查询。
2. 查询失败或提交超时保持 `unknown`，不重提（接口已拒绝从 unknown 重提）。
3. 作业结束后填实际用量（`nodes_used`、`walltime_used_s`），来源可追溯。
4. 唤醒后只核对原作业与导入结果，然后把控制交回 Leader；不作判定、不自动 accept。
5. 不修改 `research-tree.yaml`、冻结文档与冻结框架。
