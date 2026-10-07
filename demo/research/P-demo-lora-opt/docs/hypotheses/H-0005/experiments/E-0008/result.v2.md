---
id: "D-0053"
doc_type: "experiment_result"
version: 2
title: "E-0008 统计结果"
summary: "E-0008 判定 close"
about: []
author_role: "worker"
author_id: "h0005"
created_at: "2026-10-07T00:42:15Z"
---
> 本文档属于虚构示例项目，方法、文献与数字均为演示而编造，不代表真实研究结果。

## 判定：close

均值 acc 71.486，seeds [42, 43]（train_time_s 为相对SOTA均值的比例，其余为差值；正值更好）

| 比较 | 配对seed | Δacc | Δfinal_loss | Δloss_auc | Δpeak_mem_gb | Δtrain_time_s |
|---|---|---|---|---|---|---|
| sota E-0001 | 2 | +0.068 | +0.000 | -0.005 | -0.392 | +0.002 |

## 数字来源

```evidence
[{"id": "acc-s42", "value": "71.4655", "source": "outputs/E-0008/s42/metrics.json"}, {"id": "acc-s43", "value": "71.5061", "source": "outputs/E-0008/s43/metrics.json"}, {"id": "mean:acc", "value": "71.4858", "source": "outputs/E-0008/stats.json"}, {"id": "delta:sota:acc", "value": "0.06765", "source": "outputs/E-0008/stats.json"}, {"id": "delta:sota:final_loss", "value": "0.0003", "source": "outputs/E-0008/stats.json"}, {"id": "delta:sota:loss_auc", "value": "-0.0054", "source": "outputs/E-0008/stats.json"}, {"id": "delta:sota:peak_mem_gb", "value": "-0.39175", "source": "outputs/E-0008/stats.json"}, {"id": "delta:sota:train_time_s", "value": "0.002291", "source": "outputs/E-0008/stats.json"}]
```
