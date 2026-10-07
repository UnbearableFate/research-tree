---
id: "D-0021"
doc_type: "experiment_result"
version: 1
title: "E-0003 统计结果"
summary: "E-0003 判定 beats_parent"
about: []
author_role: "worker"
author_id: "h0001"
created_at: "2026-10-07T01:28:49Z"
---
> 本文档属于虚构示例项目，方法、文献与数字均为演示而编造，不代表真实研究结果。

## 判定：beats_parent

均值 acc 71.565，seeds [42]（train_time_s 为相对SOTA均值的比例，其余为差值；正值更好）

| 比较 | 配对seed | Δacc | Δfinal_loss | Δloss_auc | Δpeak_mem_gb | Δtrain_time_s |
|---|---|---|---|---|---|---|
| sota E-0001 | 1 | +0.175 | +0.002 | -0.000 | -1.118 | -0.007 |

## 数字来源

```evidence
[{"id": "acc-s42", "value": "71.5654", "source": "outputs/E-0003/s42/metrics.json"}, {"id": "mean:acc", "value": "71.5654", "source": "outputs/E-0003/stats.json"}, {"id": "delta:sota:acc", "value": "0.1747", "source": "outputs/E-0003/stats.json"}, {"id": "delta:sota:final_loss", "value": "0.0021", "source": "outputs/E-0003/stats.json"}, {"id": "delta:sota:loss_auc", "value": "-0.0001", "source": "outputs/E-0003/stats.json"}, {"id": "delta:sota:peak_mem_gb", "value": "-1.1185", "source": "outputs/E-0003/stats.json"}, {"id": "delta:sota:train_time_s", "value": "-0.006733", "source": "outputs/E-0003/stats.json"}]
```
