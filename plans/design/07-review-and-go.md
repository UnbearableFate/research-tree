---
title: "阶段 6：GO 候选复核与 GO / NOT GO"
stage: "阶段 6"
status: "proposed; not implemented"
prepared_on: "2026-10-06"
package: "plans/design（见 README.md）"
sources: "设计文档 §12 D8、8.3；ARIS experiment-audit、paper-claim-audit、reviewer-independence"
language: "zh-CN"
---

# 07 阶段 6：GO 候选复核与 GO / NOT GO

## 1. 不设置常驻 Reviewer

保留 worker 自审和 Leader 负责最终研究判断。只有进入最终候选的少数节点触发定向复核任务，且任务必须说明具体风险和终止条件。

独立复核首先是独立证据路径。两个同类模型重复赞同同一段总结，不自动增加实验独立性。

复核由 pi 非交互评审执行（09，kind=`candidate_recheck`），每个维度一次新会话、只给文件路径；reviewer 不可用记 `REVIEW_UNAVAILABLE`，不得由 Leader 自评代替。现有规则"RLD 亲自复核"改为"RLD 组织复核并对结论负责"。

## 2. 核验范围

| 维度 | 首选方式 | 通过意味着什么 |
|---|---|---|
| 数字完整性 | 从登记输入重算；必要时独立评分 | 报告数字能由相应材料得到 |
| 协议合规 | 实际命令、版本、训练量、数据与评测路径检查 | 没有发现违反已批准设定 |
| 方法—代码对齐 | 定向代码审阅与最小行为测试 | 所声明干预确实出现在执行代码中 |
| 新颖性 | 最近邻原始研究逐项比对 | 当前检索范围未发现直接覆盖，并存在可说明差异 |
| 理论/论证可靠性 | 核对假设、推导、反例和结论范围 | 声明没有已知未解决错误，不等于普适证明 |

这与 CoE 的核验维度相近，但这里只服务 Stage 1 候选，不要求自动生成完整论文。[R03B]

### 2.1 复核清单

借 ARIS `experiment-audit` 的 A–F 与 `paper-claim-audit`：

| 项 | 检查 |
|---|---|
| A GT 来源 | 评测标签来自数据集切分，不是基线或骨干模型的输出 |
| B 归一化 | 没有按自身输出极值归一化；原始与归一化分数并列 |
| C 数字可追溯 | 结果文档每个数字能在所引文件中找到（05 §2.4 已确定性核验，这里复核采样与解释） |
| D 死指标代码 | 报告的指标函数确实被调用 |
| E 措辞与证据 | "robust / extensive" 等措辞与实际 N 场景、N seed 相称；不超出评测类型的结论上限（04 §6） |
| F 评测类型 | 标签与实际一致 |
| G 方法—代码对齐 | 声明的干预确实出现在执行代码中；最小行为测试 |
| H 新颖性 | 最接近工作逐项比对（引用 02 的查新文档，但范围不限于创建时的文献） |
| I 论证 | 假设、推导、反例与结论范围 |

复核 brief 只含路径与结构化元数据，不含 worker 或 Leader 的总结（ARIS reviewer-independence）。

## 3. 复核依据必须版本化

每份复核绑定方法代码、协议及 Evaluation，并注明检查范围。只检查实现对应关系的复核，可在统计追加 seed 后按依赖关系复用；涉及具体数值结论的复核要引用新的 Evaluation。

不要求任何变化都全量重审，也不能让旧版 `pass` 自动覆盖修改后的方法。

## 4. 理论复核不是强制证明定理

方法提出了收敛或误差界声明时，应核查相应推导。纯经验方法可以检查论证、必要条件和解释是否超出证据，不应因没有定理而自动判为失败。

复核结果允许 `pass / fail / uncertain / not_applicable`，但 `not_applicable` 必须说明该维度为什么不属于所作声明。关键未解决问题不能用 not_applicable 绕过。

## 5. 独立执行与预算

复核任务可以由另一个短生命周期 worker 执行；默认只读被审对象和证据，修复由原 owner 执行。新增 GPU 复现必须来自已授权预算，不因“审计”而自动获得额外资源。

GO 报告应区分“解析重算”“独立重评分”和“重新训练复现”，不得统一写作“已复现”。

## 6. GO、NOT GO 与暂停

GO 通过第 6、7、12 节的资格检查形成；Stage 2 仍需要用户决定。

NOT GO 表示“在当前问题、范围和证据下，不建议继续投入”，不是“所有可能假说均已被科学证伪”。Leader 应逐项交代未探索、工程失败、不确定、重复方向、明确反证及投入价值判断。

不再为了满足“所有节点必须科学失败”而制造假阴性；但也不能把预算耗尽直接记为 NOT GO。预算不足默认停止新增准入、进入等待用户决定，并让模型休眠；不必为保持项目 active 而持续生成低价值工作。

当前 `not_go` 要求所有节点 prunable 且清理完成的规则需要与这里同步修订；只改提示词不够。[S12]

GO 的资格查询以 05 §3 的 Evaluation 与 eligibility 为准；此外要求该节点的 obligation 账本（06 §6）无 OPEN 项、必要复核绑定到当前 Evaluation。GO 报告区分"解析重算""独立重评分""重新训练复现"，列出阶段 2 要验证的外部适用性问题。NOT GO 逐项交代未探索、工程失败、不确定、重复方向、明确反证与投入价值判断。

<!-- 引用链接 -->

[R03B]: https://research.google/blog/science-one-framework-a-verifiable-autonomous-research-framework-via-chain-of-evidence/
[S12]: https://github.com/UnbearableFate/research-tree/blob/48b3841d97275b2e9ad010d91d261acc9c7c4f5c/shared/research-tree/tools/research_db.py#L780-L858
