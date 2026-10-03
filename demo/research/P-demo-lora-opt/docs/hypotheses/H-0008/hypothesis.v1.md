---
id: "D-0049"
doc_type: "hypothesis"
version: 1
title: "自适应秩分配"
summary: "按层的子批次方差分配LoRA秩，可在同等参数量下提升精度。"
about: []
author_role: "rld"
author_id: "main"
created_at: "2026-10-03T16:30:05Z"
parent: "H-0003"
---
> 本文档属于虚构示例项目，方法、文献与数字均为演示而编造，不代表真实研究结果。

## 假说

按层的子批次方差分配LoRA秩，可在同等参数量下提升精度。

## 创建理由

参考：D-0008, D-0009, D-0010。H-0003 优于SOTA；按层统计可能进一步提升。

## 计划的代码改动

在 `methods/` 中实现该优化器变体，不改动 `harness/`。

## 实验计划

按筛选预算运行，结果接近时扩展到3个seed。
