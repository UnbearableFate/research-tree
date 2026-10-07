---
id: "D-0007"
doc_type: "task_request"
version: 1
title: "根节点：实现实验框架并运行SOTA"
summary: "根节点框架任务"
about: []
author_role: "rld"
author_id: "main"
created_at: "2026-10-07T01:28:35Z"
---
> 本文档属于虚构示例项目，方法、文献与数字均为演示而编造，不代表真实研究结果。

## 任务与节点

根节点 P-demo-lora-opt，任务类型 harness，owner worker/root。

## 问题与预测

不适用（框架与基线任务）。

## 干预与对照

实现训练/评测骨架与统计代码，记录过程曲线；在3个seed上运行SOTA基线 BaseOpt-A。

## 范围与权限

本仓库的 harness/ 与 baselines/。

## 资源与预算

每个seed 4 nodes × 1h。

## 验收与停止条件

RLD 审核后冻结框架；SOTA 的3个seed均为有效运行。

## 交付

tasks/T-0001/delivery.v1.md

