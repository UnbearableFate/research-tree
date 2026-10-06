---
id: "D-0042"
doc_type: "experiment_result"
version: 2
title: "E-0007 统计结果"
summary: "E-0007 判定 no_gain"
about: []
author_role: "worker"
author_id: "h0004"
created_at: "2026-10-06T23:16:50Z"
---
> 本文档属于虚构示例项目，方法、文献与数字均为演示而编造，不代表真实研究结果。

## 判定：no_gain

均值 acc 71.437，seeds [42, 43]（train_time_s 为相对SOTA均值的比例，其余为差值；正值更好）

| 比较 | 配对seed | Δacc | Δfinal_loss | Δloss_auc | Δpeak_mem_gb | Δtrain_time_s |
|---|---|---|---|---|---|---|
| sota E-0001 | 2 | +0.019 | -0.019 | -0.035 | -1.631 | -0.032 |
| parent E-0002 | 2 | -0.145 | -0.018 | -0.037 | -0.446 | -0.027 |

## 数字来源

```evidence
[{"id": "acc-s42", "value": "71.4047", "source": "outputs/E-0007/s42/metrics.json"}, {"id": "acc-s43", "value": "71.4694", "source": "outputs/E-0007/s43/metrics.json"}, {"id": "mean:acc", "value": "71.43705", "source": "outputs/E-0007/stats.json"}, {"id": "delta:sota:acc", "value": "0.0189", "source": "outputs/E-0007/stats.json"}, {"id": "delta:sota:final_loss", "value": "-0.01895", "source": "outputs/E-0007/stats.json"}, {"id": "delta:sota:loss_auc", "value": "-0.03475", "source": "outputs/E-0007/stats.json"}, {"id": "delta:sota:peak_mem_gb", "value": "-1.63135", "source": "outputs/E-0007/stats.json"}, {"id": "delta:sota:train_time_s", "value": "-0.031779", "source": "outputs/E-0007/stats.json"}, {"id": "delta:parent:acc", "value": "-0.14485", "source": "outputs/E-0007/stats.json"}, {"id": "delta:parent:final_loss", "value": "-0.0183", "source": "outputs/E-0007/stats.json"}, {"id": "delta:parent:loss_auc", "value": "-0.0366", "source": "outputs/E-0007/stats.json"}, {"id": "delta:parent:peak_mem_gb", "value": "-0.44575", "source": "outputs/E-0007/stats.json"}, {"id": "delta:parent:train_time_s", "value": "-0.026672", "source": "outputs/E-0007/stats.json"}]
```
