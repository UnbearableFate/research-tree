---
id: "D-0014"
doc_type: "hypothesis"
version: 1
title: "子批次二阶矩预条件"
summary: "用未裁剪的微批次梯度平方替代全批次二阶矩，可改善LoRA更新方向。"
about: []
author_role: "rld"
author_id: "main"
created_at: "2026-10-04T13:37:08Z"
parent: "P-demo-lora-opt"
---
> 本文档属于虚构示例项目，方法、文献与数字均为演示而编造，不代表真实研究结果。

## 假说

用未裁剪的微批次梯度平方替代全批次二阶矩，可改善LoRA更新方向。

## 创建理由

参考：D-0009, D-0010, D-0011。文献A给出估计方法，但未用于低秩因子；文献B指出因子尺度问题可能放大估计误差。

## 计划的代码改动

在 `methods/` 中实现该优化器变体，不改动 `harness/`。

## 实验计划

按筛选预算运行，结果接近时扩展到3个seed。
