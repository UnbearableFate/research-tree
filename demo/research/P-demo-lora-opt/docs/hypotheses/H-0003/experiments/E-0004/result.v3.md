---
id: "D-0031"
doc_type: "experiment_result"
version: 3
title: "E-0004 统计结果"
summary: "E-0004 判定 beats_sota"
about: []
author_role: "worker"
author_id: "h0003"
created_at: "2026-10-07T01:00:13Z"
---
> 本文档属于虚构示例项目，方法、文献与数字均为演示而编造，不代表真实研究结果。

## 判定：beats_sota

均值 acc 71.641，seeds [42, 43, 44]（train_time_s 为相对SOTA均值的比例，其余为差值；正值更好）

| 比较 | 配对seed | Δacc | Δfinal_loss | Δloss_auc | Δpeak_mem_gb | Δtrain_time_s |
|---|---|---|---|---|---|---|
| sota E-0001 | 3 | +0.241 | -0.000 | +0.013 | -1.075 | +0.001 |
| parent E-0002 | 1 | +0.087 | -0.000 | +0.005 | +0.119 | -0.001 |

## 数字来源

```evidence
[{"id": "acc-s42", "value": "71.6523", "source": "outputs/E-0004/s42/metrics.json"}, {"id": "acc-s43", "value": "71.674", "source": "outputs/E-0004/s43/metrics.json"}, {"id": "acc-s44", "value": "71.5978", "source": "outputs/E-0004/s44/metrics.json"}, {"id": "mean:acc", "value": "71.641367", "source": "outputs/E-0004/stats.json"}, {"id": "delta:sota:acc", "value": "0.2412", "source": "outputs/E-0004/stats.json"}, {"id": "delta:sota:final_loss", "value": "-3.3e-05", "source": "outputs/E-0004/stats.json"}, {"id": "delta:sota:loss_auc", "value": "0.0132", "source": "outputs/E-0004/stats.json"}, {"id": "delta:sota:peak_mem_gb", "value": "-1.075", "source": "outputs/E-0004/stats.json"}, {"id": "delta:sota:train_time_s", "value": "0.000544", "source": "outputs/E-0004/stats.json"}, {"id": "delta:parent:acc", "value": "0.0869", "source": "outputs/E-0004/stats.json"}, {"id": "delta:parent:final_loss", "value": "-0.0004", "source": "outputs/E-0004/stats.json"}, {"id": "delta:parent:loss_auc", "value": "0.0049", "source": "outputs/E-0004/stats.json"}, {"id": "delta:parent:peak_mem_gb", "value": "0.1187", "source": "outputs/E-0004/stats.json"}, {"id": "delta:parent:train_time_s", "value": "-0.00094", "source": "outputs/E-0004/stats.json"}]
```
