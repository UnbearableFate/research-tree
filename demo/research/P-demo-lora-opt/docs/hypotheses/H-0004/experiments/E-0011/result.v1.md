---
id: "D-0055"
doc_type: "experiment_result"
version: 1
title: "E-0011 统计结果"
summary: "E-0011 判定 no_gain"
about: []
author_role: "worker"
author_id: "h0004"
created_at: "2026-10-07T07:14:33Z"
---
> 本文档属于虚构示例项目，方法、文献与数字均为演示而编造，不代表真实研究结果。

## 判定：no_gain

均值 acc 71.405，seeds [42]（train_time_s 为相对SOTA均值的比例，其余为差值；正值更好）

| 比较 | 配对seed | Δacc | Δfinal_loss | Δloss_auc | Δpeak_mem_gb | Δtrain_time_s |
|---|---|---|---|---|---|---|
| sota E-0001 | 1 | +0.014 | -0.017 | -0.036 | -1.522 | -0.036 |
| parent E-0003 | 1 | -0.161 | -0.020 | -0.036 | -0.404 | -0.029 |

## 数字来源

```evidence
[{"id": "acc-s42", "value": "71.4047", "source": "outputs/E-0011/s42/metrics.json"}, {"id": "mean:acc", "value": "71.4047", "source": "outputs/E-0011/stats.json"}, {"id": "delta:sota:acc", "value": "0.014", "source": "outputs/E-0011/stats.json"}, {"id": "delta:sota:final_loss", "value": "-0.0175", "source": "outputs/E-0011/stats.json"}, {"id": "delta:sota:loss_auc", "value": "-0.036", "source": "outputs/E-0011/stats.json"}, {"id": "delta:sota:peak_mem_gb", "value": "-1.5224", "source": "outputs/E-0011/stats.json"}, {"id": "delta:sota:train_time_s", "value": "-0.035812", "source": "outputs/E-0011/stats.json"}, {"id": "delta:parent:acc", "value": "-0.1607", "source": "outputs/E-0011/stats.json"}, {"id": "delta:parent:final_loss", "value": "-0.0196", "source": "outputs/E-0011/stats.json"}, {"id": "delta:parent:loss_auc", "value": "-0.0359", "source": "outputs/E-0011/stats.json"}, {"id": "delta:parent:peak_mem_gb", "value": "-0.4039", "source": "outputs/E-0011/stats.json"}, {"id": "delta:parent:train_time_s", "value": "-0.028885", "source": "outputs/E-0011/stats.json"}]
```
