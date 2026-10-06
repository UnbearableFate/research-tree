---
id: "D-0055"
doc_type: "experiment_result"
version: 2
title: "E-0009 统计结果"
summary: "E-0009 判定 needs_rld"
about: []
author_role: "worker"
author_id: "h0007"
created_at: "2026-10-06T23:17:07Z"
---
> 本文档属于虚构示例项目，方法、文献与数字均为演示而编造，不代表真实研究结果。

## 判定：needs_rld

均值 acc 71.431，seeds [42, 43]（train_time_s 为相对SOTA均值的比例，其余为差值；正值更好）

| 比较 | 配对seed | Δacc | Δfinal_loss | Δloss_auc | Δpeak_mem_gb | Δtrain_time_s |
|---|---|---|---|---|---|---|
| sota E-0001 | 2 | +0.013 | -0.001 | -0.001 | +6.005 | -0.015 |

## 数字来源

```evidence
[{"id": "acc-s42", "value": "71.4136", "source": "outputs/E-0009/s42/metrics.json"}, {"id": "acc-s43", "value": "71.4488", "source": "outputs/E-0009/s43/metrics.json"}, {"id": "mean:acc", "value": "71.4312", "source": "outputs/E-0009/stats.json"}, {"id": "delta:sota:acc", "value": "0.01305", "source": "outputs/E-0009/stats.json"}, {"id": "delta:sota:final_loss", "value": "-0.00065", "source": "outputs/E-0009/stats.json"}, {"id": "delta:sota:loss_auc", "value": "-0.0006", "source": "outputs/E-0009/stats.json"}, {"id": "delta:sota:peak_mem_gb", "value": "6.0051", "source": "outputs/E-0009/stats.json"}, {"id": "delta:sota:train_time_s", "value": "-0.015405", "source": "outputs/E-0009/stats.json"}]
```
