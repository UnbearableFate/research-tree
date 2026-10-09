---
id: "D-0003"
doc_type: "min_setup"
version: 1
title: "最小实验设定与判定规则"
summary: "0.5B模型、1000步、8任务均值；冻结框架与判定规则"
about: []
author_role: "rld"
author_id: "main"
created_at: "2026-10-08T19:47:14Z"
---
> 本文档属于虚构示例项目，方法、文献与数字均为演示而编造，不代表真实研究结果。

## 最小实验设定

| 项目 | 设定 |
|---|---|
| 模型 | 0.5B参数的小型语言模型（虚构） |
| 数据 | 常识推理混合训练集2K条（虚构） |
| 训练 | LoRA秩16，1000步 |
| 评测 | 8个常识推理任务平均精度 |
| 主指标 | acc（百分比，越高越好） |
| 其他指标 | final_loss、loss_auc、peak_mem_gb、train_time_s（均越低越好） |
| seeds | 42, 43, 44 |
| 单次运行上限 | 8 nodes × 1 h；筛选预算 10 node·h |
| 评测类型 | real_gt（数据集自带标签；可作完整性能声明） |

## 冻结框架与判定规则

- 框架文件：`harness/`
- 指标规范见 `project/metric-spec.v1.json`：acc 取百分点差，final_loss、loss_auc、peak_mem_gb 取差值，train_time_s 取相对SOTA均值的比例；正值为更好；peak_mem_gb 允许退化 2 GiB，train_time_s 允许 10%
- 协议见 `project/protocol.v1.json`：按seed与数据版本配对，训练1000步，评测8000条
- 无提升：相对父节点所有指标都不更好
- 优于父节点：主指标更好
- 优于SOTA：3个seed，主指标领先超过0.05个百分点
- 需要RLD复核：主指标持平（|Δ|≤0.02）但其他指标有明显取舍
- 差不多：seed不足3个且主指标领先在0.02–0.10之间
