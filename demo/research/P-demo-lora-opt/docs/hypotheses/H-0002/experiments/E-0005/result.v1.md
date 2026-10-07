---
id: "D-0028"
doc_type: "experiment_result"
version: 1
title: "E-0005 统计结果"
summary: "E-0005 判定 no_gain"
about: []
author_role: "worker"
author_id: "h0002"
created_at: "2026-10-07T01:28:58Z"
---
> 本文档属于虚构示例项目，方法、文献与数字均为演示而编造，不代表真实研究结果。

## 判定：no_gain

均值 acc 71.151，seeds [42]（train_time_s 为相对SOTA均值的比例，其余为差值；正值更好）

| 比较 | 配对seed | Δacc | Δfinal_loss | Δloss_auc | Δpeak_mem_gb | Δtrain_time_s |
|---|---|---|---|---|---|---|
| sota E-0001 | 1 | -0.239 | -0.012 | -0.031 | -0.548 | -0.045 |

## 数字来源

```evidence
[{"id": "acc-s42", "value": "71.1512", "source": "outputs/E-0005/s42/metrics.json"}, {"id": "mean:acc", "value": "71.1512", "source": "outputs/E-0005/stats.json"}, {"id": "delta:sota:acc", "value": "-0.2395", "source": "outputs/E-0005/stats.json"}, {"id": "delta:sota:final_loss", "value": "-0.0116", "source": "outputs/E-0005/stats.json"}, {"id": "delta:sota:loss_auc", "value": "-0.0315", "source": "outputs/E-0005/stats.json"}, {"id": "delta:sota:peak_mem_gb", "value": "-0.5478", "source": "outputs/E-0005/stats.json"}, {"id": "delta:sota:train_time_s", "value": "-0.044949", "source": "outputs/E-0005/stats.json"}]
```
