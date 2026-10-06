---
id: "D-0021"
doc_type: "hypothesis"
version: 1
title: "正交化LoRA更新"
summary: "对LoRA因子更新做正交化可改善条件数，提高精度。"
about: []
author_role: "rld"
author_id: "main"
created_at: "2026-10-06T23:34:28Z"
parent: "P-demo-lora-opt"
---
> 本文档属于虚构示例项目，方法、文献与数字均为演示而编造，不代表真实研究结果。

## 假说

对LoRA因子更新做正交化可改善条件数，提高精度。

## 创建理由

参考：D-0011, D-0013, D-0014。文献C在全参数上有效，低秩情形未被检验。

## 计划的代码改动

在 `methods/` 中实现该优化器变体，不改动 `harness/`。

## 实验计划

按筛选预算运行，结果接近时扩展到3个seed。
