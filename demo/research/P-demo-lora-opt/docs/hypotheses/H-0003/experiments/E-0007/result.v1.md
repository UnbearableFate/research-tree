---
id: "D-0040"
doc_type: "experiment_result"
version: 1
title: "E-0007 统计结果"
summary: "E-0007 判定 beats_parent"
about: []
author_role: "worker"
author_id: "h0003"
created_at: "2026-10-08T19:48:06Z"
---
> 本文档属于虚构示例项目，方法、文献与数字均为演示而编造，不代表真实研究结果。

## 判定：beats_parent

均值 acc 71.652，seeds [42]（train_time_s 为相对SOTA均值的比例，其余为差值；正值更好）

| 比较 | 配对seed | Δacc | Δfinal_loss | Δloss_auc | Δpeak_mem_gb | Δtrain_time_s |
|---|---|---|---|---|---|---|
| sota E-0001 | 1 | +0.262 | +0.002 | +0.005 | -1.000 | -0.008 |
| parent E-0003 | 1 | +0.087 | -0.000 | +0.005 | +0.119 | -0.001 |

## 数字来源

```evidence
[{"id": "acc-s42", "value": "71.6523", "source": "outputs/E-0007/s42/metrics.json"}, {"id": "mean:acc", "value": "71.6523", "source": "outputs/E-0007/stats.json"}, {"id": "delta:sota:acc", "value": "0.2616", "source": "outputs/E-0007/stats.json"}, {"id": "delta:sota:final_loss", "value": "0.0017", "source": "outputs/E-0007/stats.json"}, {"id": "delta:sota:loss_auc", "value": "0.0048", "source": "outputs/E-0007/stats.json"}, {"id": "delta:sota:peak_mem_gb", "value": "-0.9998", "source": "outputs/E-0007/stats.json"}, {"id": "delta:sota:train_time_s", "value": "-0.007679", "source": "outputs/E-0007/stats.json"}, {"id": "delta:parent:acc", "value": "0.0869", "source": "outputs/E-0007/stats.json"}, {"id": "delta:parent:final_loss", "value": "-0.0004", "source": "outputs/E-0007/stats.json"}, {"id": "delta:parent:loss_auc", "value": "0.0049", "source": "outputs/E-0007/stats.json"}, {"id": "delta:parent:peak_mem_gb", "value": "0.1187", "source": "outputs/E-0007/stats.json"}, {"id": "delta:parent:train_time_s", "value": "-0.00094", "source": "outputs/E-0007/stats.json"}]
```
