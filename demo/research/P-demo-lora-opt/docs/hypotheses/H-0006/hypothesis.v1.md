---
id: "D-0049"
doc_type: "hypothesis"
version: 1
title: "完整Kronecker二阶预条件"
summary: "对每层使用完整Kronecker因子预条件。"
about: []
author_role: "rld"
author_id: "main"
created_at: "2026-10-06T23:35:13Z"
parent: "P-demo-lora-opt"
---
> 本文档属于虚构示例项目，方法、文献与数字均为演示而编造，不代表真实研究结果。

## 假说

对每层使用完整Kronecker因子预条件。

## 创建理由

参考：D-0013, D-0014, D-0011。理论上最充分利用二阶信息，但成本未知。

## 计划的代码改动

在 `methods/` 中实现该优化器变体，不改动 `harness/`。

## 实验计划

按筛选预算运行，结果接近时扩展到3个seed。
