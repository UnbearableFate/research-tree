---
id: "D-0041"
doc_type: "hypothesis"
version: 1
title: "Kronecker因子对角近似"
summary: "对Kronecker预条件取对角近似，在低秩上以低成本获得二阶信息。"
about: []
author_role: "rld"
author_id: "main"
created_at: "2026-10-06T19:20:28Z"
parent: "P-demo-lora-opt"
---
> 本文档属于虚构示例项目，方法、文献与数字均为演示而编造，不代表真实研究结果。

## 假说

对Kronecker预条件取对角近似，在低秩上以低成本获得二阶信息。

## 创建理由

参考：D-0013, D-0014, D-0015。文献D的近似未在LoRA上评测。

## 计划的代码改动

在 `methods/` 中实现该优化器变体，不改动 `harness/`。

## 实验计划

按筛选预算运行，结果接近时扩展到3个seed。
