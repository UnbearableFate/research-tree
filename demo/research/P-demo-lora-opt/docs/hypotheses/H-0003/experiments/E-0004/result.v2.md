---
id: "D-0030"
doc_type: "experiment_result"
version: 2
title: "E-0004 统计结果"
summary: "E-0004 判定 beats_parent"
about: []
author_role: "worker"
author_id: "h0003"
created_at: "2026-10-06T19:20:14Z"
---
> 本文档属于虚构示例项目，方法、文献与数字均为演示而编造，不代表真实研究结果。

## 判定：beats_parent

均值 acc 71.663，seeds [42, 43]（train_time_s 为相对SOTA均值的比例，其余为差值；正值更好）

| 比较 | 配对seed | Δacc | Δfinal_loss | Δloss_auc | Δpeak_mem_gb | Δtrain_time_s |
|---|---|---|---|---|---|---|
| sota E-0001 | 2 | +0.245 | +0.001 | +0.013 | -1.074 | -0.006 |
| parent E-0002 | 2 | +0.081 | +0.001 | +0.011 | +0.111 | -0.001 |

## 数字来源

```evidence
[{"id": "acc-s42", "value": "71.6523", "source": "outputs/E-0004/s42/metrics.json"}, {"id": "acc-s43", "value": "71.674", "source": "outputs/E-0004/s43/metrics.json"}, {"id": "mean:acc", "value": "71.66315", "source": "outputs/E-0004/stats.json"}, {"id": "delta:sota:acc", "value": "0.245", "source": "outputs/E-0004/stats.json"}, {"id": "delta:sota:final_loss", "value": "0.0008", "source": "outputs/E-0004/stats.json"}, {"id": "delta:sota:loss_auc", "value": "0.01255", "source": "outputs/E-0004/stats.json"}, {"id": "delta:sota:peak_mem_gb", "value": "-1.07445", "source": "outputs/E-0004/stats.json"}, {"id": "delta:sota:train_time_s", "value": "-0.00557", "source": "outputs/E-0004/stats.json"}, {"id": "delta:parent:acc", "value": "0.08125", "source": "outputs/E-0004/stats.json"}, {"id": "delta:parent:final_loss", "value": "0.00145", "source": "outputs/E-0004/stats.json"}, {"id": "delta:parent:loss_auc", "value": "0.0107", "source": "outputs/E-0004/stats.json"}, {"id": "delta:parent:peak_mem_gb", "value": "0.11115", "source": "outputs/E-0004/stats.json"}, {"id": "delta:parent:train_time_s", "value": "-0.000593", "source": "outputs/E-0004/stats.json"}]
```
