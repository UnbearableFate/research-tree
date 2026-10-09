---
id: "D-0027"
doc_type: "experiment_design"
version: 1
title: "H-0002 实验设计"
summary: "orthogonal-update"
about: []
author_role: "worker"
author_id: "h0002"
created_at: "2026-10-08T19:47:47Z"
---
> 本文档属于虚构示例项目，方法、文献与数字均为演示而编造，不代表真实研究结果。

代码 94b67d5516：orthogonal-update。

## 检验的 claim

相同步数下 acc 更高。

## 存在理由

主锚定结果。

## 数据与切分

常识推理训练集 2K 条，8 任务评测（虚构）。

## 比较系统

SOTA 基线与父节点。

## 指标

acc（主），final_loss、loss_auc、peak_mem_gb、train_time_s。

## 设定

0.5B 模型，LoRA 秩 16，1000 步，统一 seed。

## 成功判据

配对领先超过 0.05 个百分点。

## 失败解释

不过门槛：该改动在此设定下不足以改进。

## 表图目标

主结果表一行。

## 优先级与成本

MUST；约 12 node·h。
