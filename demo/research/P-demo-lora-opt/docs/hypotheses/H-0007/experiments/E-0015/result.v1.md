---
id: "D-0081"
doc_type: "experiment_result"
version: 1
title: "E-0015 统计结果"
summary: "E-0015 判定 close"
about: []
author_role: "worker"
author_id: "h0007"
created_at: "2026-10-08T19:49:15Z"
---
> 本文档属于虚构示例项目，方法、文献与数字均为演示而编造，不代表真实研究结果。

## 判定：close

均值 acc 71.414，seeds [42]（train_time_s 为相对SOTA均值的比例，其余为差值；正值更好）

| 比较 | 配对seed | Δacc | Δfinal_loss | Δloss_auc | Δpeak_mem_gb | Δtrain_time_s |
|---|---|---|---|---|---|---|
| sota E-0001 | 1 | +0.023 | +0.004 | -0.004 | +6.071 | -0.019 |

## 数字来源

```evidence
[{"id": "acc-s42", "value": "71.4136", "source": "outputs/E-0015/s42/metrics.json"}, {"id": "mean:acc", "value": "71.4136", "source": "outputs/E-0015/stats.json"}, {"id": "delta:sota:acc", "value": "0.0229", "source": "outputs/E-0015/stats.json"}, {"id": "delta:sota:final_loss", "value": "0.004", "source": "outputs/E-0015/stats.json"}, {"id": "delta:sota:loss_auc", "value": "-0.0039", "source": "outputs/E-0015/stats.json"}, {"id": "delta:sota:peak_mem_gb", "value": "6.0714", "source": "outputs/E-0015/stats.json"}, {"id": "delta:sota:train_time_s", "value": "-0.019485", "source": "outputs/E-0015/stats.json"}]
```
