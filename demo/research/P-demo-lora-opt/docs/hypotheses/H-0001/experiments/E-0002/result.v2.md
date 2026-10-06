---
id: "D-0019"
doc_type: "experiment_result"
version: 2
title: "E-0002 统计结果"
summary: "E-0002 判定 beats_parent"
about: []
author_role: "worker"
author_id: "h0001"
created_at: "2026-10-06T23:53:29Z"
---
> 本文档属于虚构示例项目，方法、文献与数字均为演示而编造，不代表真实研究结果。

## 判定：beats_parent

均值 acc 71.582，seeds [42, 43]（train_time_s 为相对SOTA均值的比例，其余为差值；正值更好）

| 比较 | 配对seed | Δacc | Δfinal_loss | Δloss_auc | Δpeak_mem_gb | Δtrain_time_s |
|---|---|---|---|---|---|---|
| sota E-0001 | 2 | +0.164 | -0.001 | +0.002 | -1.186 | -0.005 |

## 数字来源

```evidence
[{"id": "acc-s42", "value": "71.5654", "source": "outputs/E-0002/s42/metrics.json"}, {"id": "acc-s43", "value": "71.5984", "source": "outputs/E-0002/s43/metrics.json"}, {"id": "mean:acc", "value": "71.5819", "source": "outputs/E-0002/stats.json"}, {"id": "delta:sota:acc", "value": "0.16375", "source": "outputs/E-0002/stats.json"}, {"id": "delta:sota:final_loss", "value": "-0.00065", "source": "outputs/E-0002/stats.json"}, {"id": "delta:sota:loss_auc", "value": "0.00185", "source": "outputs/E-0002/stats.json"}, {"id": "delta:sota:peak_mem_gb", "value": "-1.1856", "source": "outputs/E-0002/stats.json"}, {"id": "delta:sota:train_time_s", "value": "-0.004974", "source": "outputs/E-0002/stats.json"}]
```
