---
id: "D-0046"
doc_type: "hypothesis"
version: 1
title: "8-bit优化器状态"
summary: "以8-bit存储优化器状态，在精度不变时显著降低显存。"
about: []
author_role: "rld"
author_id: "main"
created_at: "2026-10-04T13:37:12Z"
parent: "P-demo-lora-opt"
---
> 本文档属于虚构示例项目，方法、文献与数字均为演示而编造，不代表真实研究结果。

## 假说

以8-bit存储优化器状态，在精度不变时显著降低显存。

## 创建理由

参考：D-0013, D-0009, D-0010。文献E在全参数微调上验证，LoRA场景未知。

## 计划的代码改动

在 `methods/` 中实现该优化器变体，不改动 `harness/`。

## 实验计划

按筛选预算运行，结果接近时扩展到3个seed。
