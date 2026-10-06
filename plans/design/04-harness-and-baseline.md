---
title: "阶段 3：根节点、框架冻结与基线"
stage: "阶段 3"
status: "proposed; not implemented"
prepared_on: "2026-10-06"
package: "plans/design（见 README.md）"
sources: "设计文档 5.1–5.3、5.7、7.6；ARIS experiment-integrity"
language: "zh-CN"
---

# 04 阶段 3：根节点、框架冻结与基线

## 1. 现状与目标

根节点只存放 baselines：worker 实现训练、评测与统计代码，在全部统一 seed 上实际运行 SOTA 基线，RLD 审核后用 `update_project(harness_ref, harness_paths)` 冻结；更换框架会清空 SOTA 指针（但不会使旧节点的通过字段失效，见 05 §4）。本阶段把 03 产出的 MetricSpec、配对规则与协议变成冻结框架的一部分，使 05 的重算有权威输入。

## 2. 目标与验收边界

权威的均值、差值和统计结论必须能从登记的输入重新计算。分两步完成，避免把 P0 扩成一个完整实验平台：

| 阶段 | 输入 | 能保证什么 | 不能保证什么 |
|---|---|---|---|
| P0-A：记录级重算 | 已登记的有效 run 指标 | 汇总与 run 一致，方向/单位/配对规则一致 | run 数字确实由训练产生 |
| P0-B：产物级导入 | runner 输出、冻结解析器、必要原始评分材料 | 数字与可核查产物绑定 | 在同一无限制写权限下抵御恶意伪造 |

两种结果都必须显示 `verification_level`。不能把 P0-A 的完成描述成“独立重跑验证完成”。设计借鉴 CoE 的证据关联原则，但不复制整套审计流水线。[R03]、[R03B]

## 3. MetricSpec

每个指标使用独立、版本化的规范：

| 字段 | 必需性 | 语义 |
|---|---|---|
| `name` | 必需 | 稳定的指标标识 |
| `direction` | 必需 | `higher` 或 `lower` |
| `input_unit` | 必需 | 输入值采用的单位，例如 fraction、seconds、bytes |
| `canonical_unit` | 必需 | 比较时使用的单位 |
| `effect_mode` | 必需 | `absolute` 或明确规定的 `relative_to_reference_mean` |
| `minimum_practical_gain` | 必需 | 有实际意义的最小收益 |
| `allowed_regression` | 可选 | 保护指标允许的最大退化 |
| `valid_range` | 可选 | 合法数值范围 |
| `relative_min_denominator` | 相对指标必需 | 分母过小时禁止相对比较的阈值 |
| `aggregation` | 必需 | 明确训练 run、任务或样本怎样聚合 |

不再用一个 `metric_is_percent` 推断所有指标的尺度。时间、显存、准确率各有规范；主指标不能随实验结果事后更换。

**示例：**输入准确率 0.701 和 0.699，转成百分数 70.1 与 69.9，绝对差为 0.2 个百分点，不是 20 个百分点，也不是直接称为相对提升 0.2%。

## 4. 配对单位

配对不能只检查两个实验都含有整数 seed 42。拟议的 `pair_key` 至少表示：

```text
数据切分版本 / 预训练来源 / 训练随机种子 /
初始化策略 / 验证协议版本 / 配对设计标识
```

仅纳入协议声明为必须匹配的字段；方法本身要改变的初始化或随机机制必须被标明，不能为了“匹配”而禁止研究干预。

相同 seed 是可追踪配对的线索，不自动意味着相同随机流、独立样本或相同训练历史。共享预训练权重上的多次后训练只能回答该预训练起点条件下的变动问题；不能宣称已经跨独立预训练复现。

## 5. 基线与保护指标

基线必须在匹配协议中实际运行。baseline 的合理调参机会、训练量、计算预算和数据处理必须记录；不能以一个未调好的单一配置代表全部现有方法。

主指标提升而关键成本或质量约束失败时，不能直接 GO。效率研究可将性能设为非劣性约束、时间/显存设为目标；这些比较关系必须预先声明，不能看到结果后交换主次。

## 6. 评测类型标签与结论上限

借 ARIS `experiment-integrity.md`。min_setup 必须声明评测类型，冻结解析器把它写进每个 Evaluation：

| 标签 | 含义 | 结论上限 |
|---|---|---|
| `real_gt` | 数据集提供的真实标签 | 完整性能声明 |
| `synthetic_proxy` | 模型生成的参照 | 只能说"代理一致性" |
| `self_supervised_proxy` | 设计上无 GT | 只能说相对提升 |
| `simulation_only` | 仿真环境 | 须加"在仿真中"限定 |
| `human_eval` | 人工评判 | 受评判者一致性统计约束 |

禁止：用另一个模型的输出当 GT；按自身输出的极值归一化；引用从未被调用的指标代码；把 2 个场景的 pilot 写成"全面评测"。这些由 03 §8 的代码审查与 07 的复核检查。

## 7. 根节点任务与里程碑

根节点任务请求（03 §6 的 M0、M1）须覆盖：实验骨架、统计代码（含 MetricSpec 与配对规则的实现）、按框架输出调整 `research-tree-cleanup.py`、运行基线家族。sanity（M0）通过后才跑全部 seed 的基线（M1）；基线的调参机会、训练量与数据处理写入 min_setup，不能以未调好的单一配置代表现有方法。

## 8. 证据保留与清理

逐 seed 指标、输入身份、统计输出和重算所需的最小原始材料属于 evidence，不得因文件名类似 `predictions`、`trace` 或 `scratch` 而自动删除。

保留整个训练 checkpoint 不是默认要求。若最终候选需要独立重评分或方法—代码核查，先登记该候选所需材料；完成核查或明确无需复用后再释放。清理与科学判定分开：清理失败可以阻塞行政收尾，但不能改变统计结论。

现有清理机制可保留，只调整“什么是重算必需证据”和最终候选的保留条件，不新增复杂的全生命周期产物平台。[S03]、[S04]

<!-- 引用链接 -->

[R03]: https://arxiv.org/abs/2605.26340
[R03B]: https://research.google/blog/science-one-framework-a-verifiable-autonomous-research-framework-via-chain-of-evidence/
[S03]: https://github.com/UnbearableFate/research-tree/blob/48b3841d97275b2e9ad010d91d261acc9c7c4f5c/shared/research-tree/tools/research_db.py
[S04]: https://github.com/UnbearableFate/research-tree/blob/48b3841d97275b2e9ad010d91d261acc9c7c4f5c/shared/research-tree/rules/research-tree-rules.md
