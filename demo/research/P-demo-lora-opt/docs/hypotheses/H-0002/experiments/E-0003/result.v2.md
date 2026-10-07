---
id: "D-0024"
doc_type: "experiment_result"
version: 2
title: "E-0003 统计结果"
summary: "E-0003 判定 no_gain"
about: []
author_role: "worker"
author_id: "h0002"
created_at: "2026-10-07T00:41:34Z"
---
> 本文档属于虚构示例项目，方法、文献与数字均为演示而编造，不代表真实研究结果。

## 判定：no_gain

均值 acc 71.175，seeds [42, 43]（train_time_s 为相对SOTA均值的比例，其余为差值；正值更好）

| 比较 | 配对seed | Δacc | Δfinal_loss | Δloss_auc | Δpeak_mem_gb | Δtrain_time_s |
|---|---|---|---|---|---|---|
| sota E-0001 | 2 | -0.243 | -0.010 | -0.025 | -0.635 | -0.042 |

## 数字来源

```evidence
[{"id": "acc-s42", "value": "71.1512", "source": "outputs/E-0003/s42/metrics.json"}, {"id": "acc-s43", "value": "71.1994", "source": "outputs/E-0003/s43/metrics.json"}, {"id": "mean:acc", "value": "71.1753", "source": "outputs/E-0003/stats.json"}, {"id": "delta:sota:acc", "value": "-0.24285", "source": "outputs/E-0003/stats.json"}, {"id": "delta:sota:final_loss", "value": "-0.01025", "source": "outputs/E-0003/stats.json"}, {"id": "delta:sota:loss_auc", "value": "-0.02545", "source": "outputs/E-0003/stats.json"}, {"id": "delta:sota:peak_mem_gb", "value": "-0.63525", "source": "outputs/E-0003/stats.json"}, {"id": "delta:sota:train_time_s", "value": "-0.042191", "source": "outputs/E-0003/stats.json"}]
```
